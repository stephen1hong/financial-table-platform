"""Geometric adapter for text PDFs with a label column and aligned annual columns.

No HTML values, XBRL tags, fixed page numbers or issuer-specific coordinates are
used in extraction. Accounting labels remain in the existing reviewed mappings.
Coordinates are PDF points (x0, top, x1, bottom), with a top-left origin.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
import pdfplumber

from .downloader import MANIFEST_PATH, RAW_DIR, verify_cached_file
from .manifest import load_manifest
from .extractor import expand_table_cells
from .filing_profiles import PROFILES
from .metrics import calculate_metric, METRIC_FORMULAS, reported_periods
from .periods import period_identity, resolve_period
from .segments import extract_segment_table, build_segment_report
from .validation import number
from .benchmark import evaluate


def box(words):
    return [min(w['x0'] for w in words), min(w['top'] for w in words),
            max(w['x1'] for w in words), max(w['bottom'] for w in words)] if words else None


def lines_from_words(words):
    """Cluster baselines, including small superscripts; retain every original word."""
    lines = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        candidates = [line for line in lines[-2:] if abs(line[0]['top'] - word['top']) <= 3]
        if candidates:
            candidates[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w['x0']) for line in lines]


def text(words):
    return ' '.join(w['text'] for w in words)


def text_status(text_value, image_count=0):
    if len(re.sub(r'\s', '', text_value)) >= 40:
        return 'TEXT'
    if re.search(r'[A-Za-z0-9]', text_value):
        return 'LIMITED_TEXT'
    return 'UNSUPPORTED_IMAGE_ONLY' if image_count else 'NO_USABLE_TEXT'


def discover_tables(pages):
    """Exact statement heading plus content; segment note heading may precede page."""
    candidates = {'statement': [], 'segment_note': []}
    note = None
    for page in pages:
        t = page['text']
        headings = re.findall(r'^Note \d+\. .+$', t, re.M)
        if headings:
            note = {'text': headings[-1], 'page': page['page']}
        if re.search(r'^Consolidated Statements of Income\s*$', t, re.M) and all(
                s in t for s in ('Net sales', 'Cost of sales', 'Consolidated net income')):
            candidates['statement'].append({'page': page['page'], 'heading': 'Consolidated Statements of Income'})
        if note and 'Segments' in note['text'] and all(s in t for s in (
                'Walmart U.S.', 'Walmart International', "Sam's Club U.S.", 'Corporate and support', 'Cost of sales', 'Income before income taxes')):
            candidates['segment_note'].append({'page': page['page'], 'heading': note['text'], 'heading_page': note['page']})
    return candidates


def year_header(lines, pattern=r'Fiscal Years Ended'):
    candidates = [(i, [w for w in line if re.fullmatch(r'20\d{2}', w['text'])])
                  for i, line in enumerate(lines)]
    candidates = [(i, ws) for i, ws in candidates if i > 0 and len(ws) >= 2 and
                  re.search(pattern, text(lines[i-1]), re.I)]
    if len(candidates) != 1:
        raise ValueError('AMBIGUOUS_HEADER: expected one annual year-header row')
    i, years = candidates[0]
    if len({w['text'] for w in years}) != len(years):
        raise ValueError('AMBIGUOUS_HEADER: duplicate years')
    return i, years


def compatible_headers(first, second):
    return len(first) == len(second) and all(a['text'] == b['text'] and
        abs((a['x0'] + a['x1']) / 2 - (b['x0'] + b['x1']) / 2) <= 2
        for a, b in zip(first, second))


def geometric_table(page_parts, source, document, *, layout=None, period_resolver=None):
    """Join explicitly continued pages only when repeated headers agree.

    Uncertain words crossing column boundaries invalidate their row, rather than
    assigning their value to the nearest year. Wrapped labels are preserved as
    separate uncertain rows (not silently joined).
    """
    layout = layout or {}
    period_resolver = period_resolver or resolve_period
    rows, locations, repeated, footnotes, exceptions = [], [], [], [], []
    first_years = None
    for part in page_parts:
        lines = lines_from_words(part['words'])
        try:
            hi, years = year_header(lines, layout.get('header_pattern', r'Fiscal Years Ended'))
        except ValueError as exc:
            exceptions.append({'status': 'AMBIGUOUS_HEADER', 'page': part['page'], 'reason': str(exc)})
            continue
        if first_years and (not part.get('continued') or not compatible_headers(first_years, years)):
            exceptions.append({'status': 'AMBIGUOUS_CONTINUATION', 'page': part['page'],
                               'reason': 'Continuation needs explicit evidence and matching year positions'})
            continue
        centers = [(w['x0'] + w['x1']) / 2 for w in years]
        edges = [centers[0] - (centers[1]-centers[0])/2] + [
            (a+b)/2 for a,b in zip(centers, centers[1:])] + [part['width']]
        if first_years is None:
            first_years = years
            unit_words = [w for w in lines[hi] if w['x1'] < edges[0]]
            unit_pattern = layout.get('unit_pattern', r'Amounts in millions')
            if not re.search(unit_pattern, text(unit_words), re.I) and layout.get('preceding_units'):
                matches = [line for line in lines[:hi] if re.search(unit_pattern, text(line), re.I)]
                unit_words = matches[-1] if matches else []
            if not re.search(unit_pattern, text(unit_words), re.I):
                exceptions.append({'status': 'UNSUPPORTED_UNIT', 'page': part['page'], 'reason': text(unit_words)})
                break
            rows += [[('', 1), (text(lines[hi-1]), len(years))],
                     [(text(unit_words), 1)] + [(w['text'], 1) for w in years]]
            locations += [[([], 'ok'), (lines[hi-1], 'ok')], [(unit_words, 'ok')] + [([w], 'ok') for w in years]]
        else:
            repeated.append({'page': part['page'], 'text': text(lines[hi-1]) + ' | ' + text(lines[hi]),
                             'bbox': box(lines[hi-1] + lines[hi])})
        in_footnotes = False
        for line in lines[hi+1:]:
            t = text(line)
            if len(line) == 1 and t.isdigit() and min(w['top'] for w in line) > part['height'] * .94:
                continue  # isolated printed page number; never discard financial rows by height
            if re.match(r'^\(\d+\)\s', t) or t.startswith('See accompanying notes'):
                in_footnotes = True
            if in_footnotes:
                footnotes.append({'text': t, 'page': part['page'], 'bbox': box(line),
                                  'source_reference': f'{source}#page={part["page"]}'})
                continue
            if re.match(r'^Note \d+\.', t):
                break
            bins = [[] for _ in range(len(years)+1)]
            uncertain = False
            for w in line:
                if w['x1'] < edges[0]:
                    bins[0].append(w)
                    continue
                matches = [i+1 for i in range(len(years)) if w['x0'] >= edges[i] and w['x1'] <= edges[i+1]]
                if len(matches) == 1:
                    bins[matches[0]].append(w)
                else:
                    uncertain = True
            if not any(bins[1:]) and not uncertain:
                rows.append([(t, len(years)+1)])
                locations.append([(line, 'ok')])
            else:
                rows.append([(text(ws), 1) for ws in bins])
                locations.append([(ws, 'AMBIGUOUS' if uncertain else 'ok' if ws else 'MISSING_VALUE') for ws in bins])
            for ws, _ in locations[-1]:
                for w in ws:
                    w['page'] = part['page']
            if uncertain:
                exceptions.append({'status': 'AMBIGUOUS', 'page': part['page'], 'bbox': box(line),
                                   'reason': 'Word overlaps column boundary; row values withheld', 'words': line})
        # Headers also carry their original page coordinates.
        for line in lines[:hi+1]:
            for w in line:
                w['page'] = part['page']
    markup = '<table>' + ''.join('<tr>' + ''.join(f'<td colspan="{span}">{escape(t)}</td>' for t,span in row) + '</tr>' for row in rows) + '</table>'
    table = BeautifulSoup(markup, 'html.parser').table
    cells = expand_table_cells(table, source)
    flat_locations = [loc for row in locations for loc in row]
    for cell, (words, status) in zip(cells, flat_locations):
        page = words[0].get('page') if words else None
        cell.update(document_id=document['id'], page=page, bbox=box(words), words=words,
                    assignment_status=status, source_reference=f'{source}#page={page}' if page else source)
        if cell['period_label']:
            try:
                cell['period'] = period_resolver(cell['header_text'], document)
            except ValueError:
                cell.update(period=None, assignment_status='AMBIGUOUS')
    for cell in cells:
        if cell['page'] is None:
            siblings = [c for c in cells if c['row'] == cell['row'] and c['bbox']]
            if siblings:
                cell['page'] = siblings[0]['page']
                cell['source_reference'] = f'{source}#page={cell["page"]}'
                # An empty cell has a geometric region, not an invented text box.
                col = cell['column']
                centers = [(w['x0'] + w['x1'])/2 for w in first_years]
                bounds = [0, centers[0]-(centers[1]-centers[0])/2] + [(a+b)/2 for a,b in zip(centers, centers[1:])] + [page_parts[0]['width']]
                cell['bbox'] = [bounds[col], min(c['bbox'][1] for c in siblings), bounds[col+1], max(c['bbox'][3] for c in siblings)]
                cell['bbox_kind'] = 'empty_cell_region'
    # Replace header copies with geometrically enriched originals.
    by_position = {(c['row'], c['column']): c for c in cells}
    for cell in cells:
        cell['header_cells'] = [{k:v for k,v in by_position[(h['row'], h['column'])].items() if k != 'header_cells'} for h in cell['header_cells']]
    return table, cells, footnotes, repeated, exceptions


def statement_facts(cells, document, heading, *, mappings=None, unit='USD (millions)'):
    mappings = PROFILES[document['html_document_id']][4] if mappings is None else mappings
    facts, exceptions = [], []
    parent, parent_x = None, None
    for row in sorted({c['row'] for c in cells if c['row'] > 1}):
        row_cells = [c for c in cells if c['row'] == row]
        label = row_cells[0]['text']
        label_x = (row_cells[0].get('bbox') or [0])[0]
        if parent_x is not None and label_x <= parent_x + 1:
            parent, parent_x = None, None
        if label.endswith(':'):
            parent, parent_x = label, label_x
        matches = [(m, concept) for m,(reported, concept) in mappings.items() if reported == label]
        if not matches:
            if len(row_cells) > 1:
                exceptions.append({'status': 'UNMAPPED_ROW', 'label': label, 'row': row,
                                   'source_reference': row_cells[0]['source_reference'],
                                   'cells': row_cells,
                                   'reason': 'Cells retained; outside existing statement metric mappings'})
            continue
        metric, concept = matches[0]
        for cell in row_cells[1:]:
            status, value = cell['assignment_status'], None
            try:
                value = number(cell['text']) if status == 'ok' else None
            except ValueError:
                status = 'MISSING_VALUE'
            if not cell.get('period'):
                status, value = 'AMBIGUOUS', None
            fact = {'fact_id': f'{document["id"]}:statement:{row}:{cell["column"]}',
                    'company': document['company'], 'document_id': document['id'],
                    'scope': 'statement', 'segment': 'Consolidated', 'metric': metric,
                    'concept': concept, 'label': label, 'hierarchical_label': [heading] + ([parent] if parent else []) + [label],
                    'value': value, 'unit': unit, 'period': cell.get('period'),
                    'status': status, 'original_text': cell['original_text'], 'display_value': cell['text'],
                    'source_reference': cell['source_reference'], 'row': row, 'column': cell['column'],
                    'page': cell['page'], 'bbox': cell['bbox'], 'cell': cell,
                    'header_text': cell['header_text'], 'header_cells': cell['header_cells']}
            facts.append(fact)
            if status != 'ok':
                exceptions.append(fact)
    return facts, exceptions


def comparison_key(fact):
    return (fact.get('company'), fact.get('scope'), fact.get('metric'), fact.get('unit'),
            fact.get('segment'), period_identity(fact.get('period') or {}))


def compare_html(pdf_facts, html_facts):
    index = {}
    for fact in html_facts:
        index.setdefault(comparison_key(fact), []).append(fact)
    results = []
    pdf_counts = Counter(comparison_key(f) for f in pdf_facts)
    pdf_keys = {comparison_key(f) for f in pdf_facts}
    for fact in pdf_facts:
        candidates = index.get(comparison_key(fact), [])
        result = {'pdf': fact, 'html_candidates': candidates, 'difference': None}
        if any(fact.get(k) is None for k in ('company', 'metric', 'unit', 'segment')) or None in period_identity(fact.get('period') or {}):
            result.update(status='NO_COMPARABLE_FACT', reason='Incomplete PDF comparison metadata')
        elif pdf_counts[comparison_key(fact)] != 1:
            result.update(status='AMBIGUOUS', reason='Duplicate PDF facts for the same semantic key')
        elif fact.get('value') is None or not candidates or any(c.get('value') is None for c in candidates):
            result.update(status='NO_COMPARABLE_FACT', reason='Missing PDF value or no HTML fact with matching company, scope, metric, unit, segment and complete period')
        elif len(candidates) != 1:
            result.update(status='AMBIGUOUS', reason='Multiple matching HTML facts')
        else:
            difference = fact['value'] - Decimal(str(candidates[0]['value']))
            result.update(status='MATCH' if difference == 0 else 'MISMATCH', difference=difference,
                          reason='Same reported definition and display units; exact comparison, no sign or value replacement')
        results.append(result)
    for fact in html_facts:
        if comparison_key(fact) not in pdf_keys:
            results.append({'status': 'MISSING_PDF_FACT', 'pdf': None, 'html_candidates': [fact],
                            'reason': 'No independently extracted PDF counterpart', 'difference': None})
    return results


def build_report(manifest_path=MANIFEST_PATH, raw_dir=RAW_DIR, render_dir=None):
    manifest = load_manifest(manifest_path)
    document = next(d for d in manifest['pdf_documents'] if d['id'] == 'wmt-2025-pdf')
    path = Path(raw_dir) / document['filename']
    if not verify_cached_file(path, document.get('sha256')):
        raise ValueError('Missing or checksum-invalid PDF cache')
    tables, facts, exceptions = [], [], []
    with pdfplumber.open(path) as pdf:
        pages = []
        for p in pdf.pages:
            t = p.extract_text() or ''
            pages.append({'page': p.page_number, 'text': t, 'status': text_status(t, len(p.images))})
            p.close()
        verification = [p for p in pages if all(s in p['text'] for s in
            ('WALMART INC.', 'FORM 10-K', 'For the fiscal year ended January 31, 2025'))]
        if len(verification) != 1:
            raise ValueError('PDF company/form/fiscal-period verification failed')
        candidates = discover_tables(pages)
        for scope, selected in candidates.items():
            if len(selected) != 1:
                exceptions.append({'status': 'MISSING_TABLE' if not selected else 'AMBIGUOUS_TABLE',
                                   'scope': scope, 'candidates': selected})
                continue
            selection = selected[0]
            parts = []
            start = selection['page'] - 1
            for i in range(start, len(pages)):
                continued = i > start
                if continued and not re.search(r'\bcontinued\b', pages[i]['text'][:500], re.I):
                    break
                p = pdf.pages[i]
                parts.append({'page': p.page_number, 'words': p.extract_words(x_tolerance=2, y_tolerance=3),
                              'width': p.width, 'height': p.height, 'continued': continued})
                if render_dir:
                    p.to_image(resolution=120).save(Path(render_dir) / f'page-{p.page_number}.png')
            table, cells, footnotes, repeated, errors = geometric_table(parts, path.as_posix(), document)
            exceptions.extend(errors)
            if scope == 'segment_note' and cells:
                try:
                    extracted = extract_segment_table(table, document, path.as_posix(), selection['heading'], footnotes, supplied_cells=cells)
                except ValueError as exc:
                    extracted = {'facts': [], 'exceptions': [{'status': 'AMBIGUOUS_TABLE', 'scope': scope, 'reason': str(exc)}]}
                table_facts = extracted['facts']
                for f in table_facts:
                    c = f.get('cell') or {}
                    f.update(scope=scope, page=c.get('page'), bbox=c.get('bbox'), source_reference=c.get('source_reference', path.as_posix()))
                exceptions.extend(extracted['exceptions'])
            elif scope == 'statement':
                table_facts, errors = statement_facts(cells, document, selection['heading'])
                exceptions.extend(errors)
            else:
                table_facts = []
            facts.extend(table_facts)
            tables.append({'scope': scope, **selection, 'cells': cells, 'facts': table_facts,
                           'footnotes': footnotes, 'repeated_headers': repeated,
                           'source_reference': path.as_posix(), 'pages': [p['page'] for p in parts]})
    html_doc = next(d for d in manifest['documents'] if d['id'] == document['html_document_id'])
    html_facts = [{**f, 'scope': 'statement'} for g in reported_periods(html_doc, raw_dir) for f in g['reported_facts'].values()]
    html_facts += [{**f, 'scope': 'segment_note'} for f in build_segment_report(manifest_path, raw_dir)['facts']]
    comparisons = compare_html(facts, html_facts)
    exceptions.extend(c for c in comparisons if c['status'] != 'MATCH')
    calculations = []
    groups = {(f['scope'], f['segment'], period_identity(f['period'])) for f in facts if f.get('period')}
    for scope, segment, period in sorted(groups):
        members = [f for f in facts if (f['scope'], f['segment'], period_identity(f['period'] or {})) == (scope, segment, period)]
        counts = Counter(f['metric'] for f in members)
        inputs = {f['metric']: f for f in members if counts[f['metric']] == 1}
        for metric in METRIC_FORMULAS:
            calc = calculate_metric(metric, inputs)
            calc.update(scope=scope, segment=segment, input_period=members[0]['period'],
                        inputs=[f for f in inputs.values() if f['fact_id'] in calc['input_fact_ids']])
            calculations.append(calc)
            if calc['status'] != 'ok':
                exceptions.append({**calc, 'reason': 'No reported corporate sales/cost/revenue base; no margin or gross profit inferred' if segment == 'Corporate and support' else calc.get('reason')})
    exceptions.extend({'status': p['status'], 'page': p['page'],
                       'reason': 'No usable text; OCR is unsupported. This page was not used for financial extraction.'}
                      for p in pages if p['status'] in ('UNSUPPORTED_IMAGE_ONLY', 'NO_USABLE_TEXT'))
    return {'document': document, 'verification': {'page': verification[0]['page'], 'company': 'Walmart Inc.',
            'form': '10-K embedded in annual report', 'period_end': '2025-01-31'},
            'page_inventory': [{k:v for k,v in p.items() if k != 'text'} for p in pages],
            'tables': tables, 'facts': facts, 'comparisons': comparisons, 'calculations': calculations, 'exceptions': exceptions}


def render_report(report, benchmark):
    lines = ['# PDF extraction review', '', f"Source: {report['document']['source_url']}",
             f"SHA-256: `{report['document']['sha256']}`", str(report['verification']),
             'Locations use 1-based PDF pages and top-left bounding boxes in PDF points. Printed page numbers differ by two in this report.',
             'PDF and HTML values are independently extracted. Exact comparisons require company, full period, metric, unit, segment and table scope. No HTML values fill PDF gaps.',
             'Presentation: PDF combines currency symbols and amounts in cells, uses physical indentation and superscript footnotes, and repeats the HTML statement/segment values. Gross profit and margins are calculated, not reported subtotals.', '']
    lines += [f"Page text inventory: {dict(Counter(p['status'] for p in report['page_inventory']))}",
              f"Limited/unsupported pages: {[p for p in report['page_inventory'] if p['status'] != 'TEXT']}",
              'Row coverage: ' + str({t['scope']: {'numeric_rows': len({c['row'] for c in t['cells'] if c['row'] > 1 and c['column'] > 0 and c['is_numeric']}), 'mapped_facts': len(t['facts'])} for t in report['tables']})]
    for table in report['tables']:
        lines += [f"## {table['heading']} — PDF pages {table['pages']}", '', '| Row | Label / hierarchy | Values in source column order | Source locations |', '| --- | --- | --- | --- |']
        for row in sorted({c['row'] for c in table['cells']}):
            cells = [c for c in table['cells'] if c['row'] == row]
            lines.append(f"| {row} | {cells[0]['text']} | " + ' / '.join(c['text'] or '[missing]' for c in cells[1:]) + ' | ' + '; '.join(f"p{c['page']} {c['bbox']}" for c in cells) + ' |')
        lines += ['', 'Footnotes:'] + [f"- {f['text']} ({f['source_reference']}; {f['bbox']})" for f in table['footnotes']]
    lines += ['', '## Comparisons', '', '| Scope / segment / metric / FY | PDF | HTML | Difference | Status | Sources |', '| --- | ---: | ---: | ---: | --- | --- |']
    for c in report['comparisons']:
        f = c['pdf'] or c['html_candidates'][0]
        lines.append(f"| {f['scope']} / {f['segment']} / {f['metric']} / {(f.get('period') or {}).get('fiscal_year')} | {c['pdf']['value'] if c['pdf'] else 'missing'} | " + ', '.join(str(h['value']) for h in c['html_candidates']) + f" | {c['difference']} | {c['status']} | " + '; '.join(x['source_reference'] + f" row={x['row']} col={x['column']}" for x in ([c['pdf']] if c['pdf'] else []) + c['html_candidates']) + ' |')
    lines += ['', '## Calculations', '']
    for c in report['calculations']:
        lines.append(f"- {c['scope']} / {c['segment']} / {c['input_period']}: {c['metric']} = {c['value']} ({c['status']}); {c['formula']}; inputs: " + '; '.join(f"{f['fact_id']}={f['value']} at {f['source_reference']} bbox={f['bbox']}" for f in c['inputs']))
    lines += ['', '## Benchmark', '', 'Frozen examples transcribed from rendered PDF pages; coordinate-based lookup does not use expected values, periods or segments.', '```json', json.dumps(benchmark, indent=2, default=str), '```', '', '## Exceptions', '']
    lines += [f"- {e['status']}: {e.get('label', e.get('scope', ''))} {e.get('segment', '')} {e.get('metric', '')} {e.get('input_period', '')} {e.get('reason', '')}; page={e.get('page', '')} row={e.get('row', '')}" for e in report['exceptions']]
    lines += ['', 'All source cells, word geometry, header spans, footnotes and unresolved calculations are retained in report.json. The mapped statement subset excludes EPS/share counts and other rows outside the existing metric profile. Corporate margins are unresolved because no revenue/cost base is reported. No OCR, arbitrary layout inference, or unmarked continuation inference is supported.']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='data/processed/pdf')
    parser.add_argument('--expected', default='tests/fixtures/pdf_benchmark_facts.json')
    parser.add_argument('--render', action='store_true', help='Render selected source pages for review')
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = build_report(render_dir=output if args.render else None)
    fixture = json.loads(Path(args.expected).read_text(encoding='utf-8'))
    benchmark = evaluate(fixture['facts'], report['facts'])
    benchmark['missing_examples'] = [f for f in fixture['facts'] if f['id'] in benchmark['missing']]
    benchmark['tables'] = {scope: any(t['scope'] == scope and t['facts'] for t in report['tables']) for scope in fixture['expected_tables']}
    benchmark['table_coverage'] = sum(benchmark['tables'].values()) / len(benchmark['tables'])
    benchmark['selected_numeric_cells'] = sum(c['row'] > 1 and c['column'] > 0 and c['is_numeric'] for t in report['tables'] for c in t['cells'])
    benchmark['mapped_facts'] = len(report['facts'])
    benchmark['mapping_coverage_of_selected_numeric_cells'] = len(report['facts']) / benchmark['selected_numeric_cells'] if benchmark['selected_numeric_cells'] else 0
    for name, value in [('report.json', report), ('exceptions.json', report['exceptions']), ('benchmark.json', benchmark)]:
        (output/name).write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')
    (output/'review.md').write_text(render_report(report, benchmark), encoding='utf-8')
    (output/'exceptions.md').write_text('# PDF exceptions\n\n' + '\n'.join(f"- {e['status']}: {e.get('label', '')} {e.get('segment', '')} {e.get('metric', '')} {e.get('input_period', '')}; {e.get('reason', '')}; {e.get('source_reference', '')} page={e.get('page', '')} row={e.get('row', '')}" for e in report['exceptions']), encoding='utf-8')
    print(f"Tables: {len(report['tables'])}; facts: {len(report['facts'])}; comparisons: {dict(Counter(c['status'] for c in report['comparisons']))}; exceptions: {len(report['exceptions'])}")
    print(f"PDF benchmark: {benchmark['present']}/{benchmark['expected']} present; accuracy={benchmark['accuracy_on_present']}; missing tables={[s for s,found in benchmark['tables'].items() if not found]}")
    print(output/'review.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
