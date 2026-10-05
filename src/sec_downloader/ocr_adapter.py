"""Local OCR for scanned Walmart annual income/segment tables and table images.

The adapter does not read benchmark answers, HTML facts or PDF text to repair OCR.
Original polygons/text survive geometric deskew, numeric parsing and review gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
from statistics import median

import numpy as np
import pdfplumber
from PIL import Image, ImageDraw

from .downloader import compute_sha256
from .pdf_adapter import geometric_table, statement_facts
from .segments import extract_segment_table, SEGMENTS, MAPPINGS, clean_label
from .metrics import calculate_metric, METRIC_FORMULAS
from .periods import period_identity

ENGINE_SETTINGS = dict(det_limit_side_len=2400, det_limit_type='max', max_side_len=3500,
                       use_cls=False, intra_op_num_threads=2, inter_op_num_threads=2)
MIN_CONFIDENCE = .95


def engine_metadata():
    import rapidocr_onnxruntime
    root = Path(rapidocr_onnxruntime.__file__).parent
    return {'settings': ENGINE_SETTINGS, 'minimum_confidence': MIN_CONFIDENCE,
            'versions': {p: importlib.metadata.version(p) for p in ('rapidocr-onnxruntime','onnxruntime','opencv-python','numpy','Pillow','pdfplumber','pypdfium2')},
            'models': {p.name: compute_sha256(p) for p in sorted((root/'models').glob('*.onnx'))}}


def recognize(image, engine, output, metadata):
    """Cache only by image pixels and complete engine/model configuration."""
    key = hashlib.sha256(image.tobytes() + str(image.size).encode() + json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    path = Path(output)/f'ocr-{key}.json'
    if path.exists():
        return json.loads(path.read_text())['detections']
    result, timing = engine(np.asarray(image.convert('RGB')), use_cls=False)
    result = result or []
    path.write_text(json.dumps({'image_pixel_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
                               'engine': metadata, 'timing': timing, 'detections': result}, indent=2), encoding='utf-8')
    return result


def rotate_point(point, center, degrees):
    """Image coordinates: positive angle rotates counterclockwise visually."""
    a = math.radians(degrees)
    x, y = point[0]-center[0], point[1]-center[1]
    return [center[0]+x*math.cos(a)+y*math.sin(a), center[1]-x*math.sin(a)+y*math.cos(a)]


def bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def ocr_words(detections, image_size, page_size):
    slopes = [math.degrees(math.atan2(q[1][1]-q[0][1], q[1][0]-q[0][0]))
              for q, t, score in detections if q[1][0]-q[0][0] > 150 and score >= MIN_CONFIDENCE]
    skew = median(slopes) if slopes else 0
    # Correct small page skew only. Larger rotations require explicit review.
    correction = skew if .3 < abs(skew) <= 5 else 0
    scale_x, scale_y = page_size[0]/image_size[0], page_size[1]/image_size[1]
    center = [image_size[0]/2, image_size[1]/2]
    words = []
    for polygon, original, confidence in detections:
        normalized = [rotate_point(p, center, correction) for p in polygon]
        source_polygon = [[p[0]*scale_x, p[1]*scale_y] for p in polygon]
        b = bounds([[p[0]*scale_x, p[1]*scale_y] for p in normalized])
        words.append({'text': original, 'ocr_original_text': original, 'confidence': float(confidence),
                      'x0': b[0], 'top': b[1], 'x1': b[2], 'bottom': b[3],
                      'source_polygon': source_polygon, 'source_bbox': bounds(source_polygon)})
    return words, {'estimated_skew_degrees': skew, 'coordinate_correction_degrees': correction,
                   'method': 'Median top-edge angle of long, confident OCR detections; no recipe angles used'}


def numeric_review(original, confidence=1, integer_amount=True):
    """Strict grammar. No O/0, I/1, decimal, minus or parentheses replacements."""
    s = original.strip()
    issues = []
    if confidence < MIN_CONFIDENCE:
        issues.append('LOW_OCR_CONFIDENCE')
    if s.count('(') != s.count(')') or ('(' in s and not re.fullmatch(r'\$?\s*\(.*\)', s)):
        issues.append('UNBALANCED_OR_MISPLACED_SIGN')
    if re.search(r'[A-Za-z]', s):
        issues.append('DIGIT_LETTER_CONFUSION')
    # Whitespace between digits is not removed: it may denote two merged cells.
    if re.search(r'\d\s+\d', s):
        issues.append('MULTIPLE_NUMERIC_TOKENS')
    grammar = r'\$?\s*(?:-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\))'
    value = None
    if not re.fullmatch(grammar, s):
        issues.append('INVALID_NUMERIC_GRAMMAR')
    else:
        cleaned = s.replace('$','').strip().replace(',','')
        if cleaned.startswith('('):
            cleaned = '-' + cleaned[1:-1]
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            issues.append('INVALID_NUMBER')
    if integer_amount and '.' in s:
        issues.append('UNEXPECTED_DECIMAL_IN_INTEGER_AMOUNT')
    return value, sorted(set(issues))


def gate_cells(cells):
    for c in cells:
        words = c.get('words', [])
        c['ocr_original_text'] = c['text']
        c['ocr_confidence'] = min((w['confidence'] for w in words), default=0)
        polygons = [p for w in words for p in w.get('source_polygon', [])]
        c['geometry_bbox'] = c.get('bbox')
        c['source_bbox'] = bounds(polygons) if polygons else c.get('bbox')
        c['ocr_review_reasons'] = []
        if c['row'] > 1 and c['column'] > 0:
            raw_value, issues = numeric_review(c['text'], c['ocr_confidence'], integer_amount=False)
            c['ocr_parsed_value'] = raw_value
            c['ocr_review_reasons'].extend(issues)
        elif c['text'] and c['ocr_confidence'] < MIN_CONFIDENCE:
            c['ocr_review_reasons'].append('LOW_OCR_CONFIDENCE')
        if c['ocr_review_reasons']:
            c['assignment_status'] = 'OCR_REVIEW'
    return cells


def guard_facts(facts, cells, scope):
    headers = [c for c in cells if c['row'] <= 1 and c['text']]
    bad_headers = [c for c in headers if c['assignment_status'] != 'ok']
    by_row = {c['row']: c for c in cells if c['column'] == 0}
    # An unrecognized section must not inherit a previous segment identity.
    segment_state, segment_issue = None, None
    state = {}
    for row in sorted(by_row):
        c = by_row[row]
        if scope == 'segment_note' and row > 1 and c['colspan'] > 1:
            label = clean_label(c['text'])
            segment_state = label if label in SEGMENTS else None
            segment_issue = None if segment_state and c['assignment_status'] == 'ok' else 'UNCERTAIN_SEGMENT_HEADER'
        state[row] = (segment_state, segment_issue)
    for f in facts:
        cell = f.get('cell') or {}
        label_cell = by_row.get(f['row'], {})
        confidence = cell.get('ocr_confidence', 0)
        original = cell.get('ocr_original_text', '')
        raw_value, reasons = numeric_review(original, confidence)
        reasons += cell.get('ocr_review_reasons', [])
        if label_cell.get('assignment_status') != 'ok':
            reasons.append('UNCERTAIN_ROW_LABEL')
        if bad_headers:
            reasons.append('UNCERTAIN_PERIOD_OR_UNIT_HEADER')
        if scope == 'segment_note' and (state[f['row']][1] or state[f['row']][0] != f['segment']):
            reasons.append('UNCERTAIN_SEGMENT_HEADER')
        if 'loss' in f['label'].lower() and 'income' not in f['label'].lower() and raw_value is not None and raw_value >= 0:
            reasons.append('LOSS_LABEL_WITHOUT_NEGATIVE_SIGN')
        if cell.get('assignment_status', 'ok') != 'ok':
            reasons.append('UNCERTAIN_CELL_ASSIGNMENT')
        f.update(ocr_original_text=original, ocr_original_label=label_cell.get('ocr_original_text'), ocr_parsed_value=raw_value, ocr_confidence=confidence,
                 review_reasons=sorted(set(reasons)), bbox=cell.get('source_bbox'),
                 page=cell.get('page'), scope=scope,
                 source_reference=cell.get('source_reference', f['source_reference']))
        if reasons:
            f.update(status='OCR_REVIEW', value=None)
    return facts


def extract_page(image, source, page_number, document, engine, output, metadata, page_size=None):
    page_size = page_size or (image.width*72/300, image.height*72/300)
    detections = recognize(image, engine, output, metadata)
    words, deskew = ocr_words(detections, image.size, page_size)
    visible = ' '.join(w['text'] for w in words).casefold()
    if 'consolidated statements of income' in visible:
        scope, heading = 'statement', 'Consolidated Statements of Income'
    elif all(s in visible for s in ('walmart u.s.', 'walmart international', 'corporate and support')):
        scope, heading = 'segment_note', 'Segment operating results (OCR content evidence)'
    else:
        return {'source_reference': source, 'page': page_number, 'cells': [], 'facts': [],
                'exceptions': [{'status': 'MISSING_TABLE', 'reason': 'Supported statement/segment anchors not recognized'}],
                'detections': detections, 'deskew': deskew, 'scope': None}
    part = {'page': page_number, 'width': page_size[0], 'height': page_size[1], 'words': words}
    table, cells, footnotes, repeated, exceptions = geometric_table([part], source, document)
    gate_cells(cells)
    # Case-only matching of reviewed labels is not numeric repair. Preserve every
    # original OCR string and log this normalization explicitly on the source cell.
    canonical = {label.casefold():label for label in [*SEGMENTS, *MAPPINGS]}
    for c in cells:
        if c['column'] == 0 and clean_label(c['text']).casefold() in canonical:
            normalized = canonical[clean_label(c['text']).casefold()]
            suffix = c['text'][len(clean_label(c['text'])):]
            if normalized + suffix != c['text']:
                c['label_normalization'] = 'Case-insensitive match to existing reviewed label; original OCR retained'
                c['text'] = normalized + suffix
    facts = []
    if cells:
        if scope == 'statement':
            facts, errors = statement_facts(cells, document, heading)
        else:
            try:
                extracted = extract_segment_table(table, document, source, heading, footnotes, supplied_cells=cells)
                facts, errors = extracted['facts'], extracted['exceptions']
            except ValueError as exc:
                facts, errors = [], [{'status': 'AMBIGUOUS_TABLE', 'reason': str(exc)}]
        exceptions.extend(errors)
        guard_facts(facts, cells, scope)
    exceptions.extend({'status': f['status'], 'fact_id': f['fact_id'], 'reason': ', '.join(f['review_reasons']),
                       'ocr_original_text': f['ocr_original_text'], 'bbox': f['bbox']} for f in facts if f['status'] != 'ok')
    return {'source_reference': source, 'page': page_number, 'page_size': page_size, 'scope': scope,
            'heading': heading, 'cells': cells, 'facts': facts, 'footnotes': footnotes,
            'exceptions': exceptions, 'deskew': deskew, 'detections': detections}


def calculations(facts):
    result = []
    groups = {(f['scope'], f['segment'], period_identity(f['period'])) for f in facts if f.get('period')}
    for scope, segment, period in sorted(groups):
        members = [f for f in facts if (f['scope'], f['segment'], period_identity(f.get('period') or {})) == (scope, segment, period)]
        counts = Counter(f['metric'] for f in members)
        inputs = {f['metric']: f for f in members if counts[f['metric']] == 1}
        for metric in METRIC_FORMULAS:
            calc = calculate_metric(metric, inputs)
            calc.update(segment=segment, scope=scope, input_period=members[0]['period'],
                        inputs=[{'fact_id': f['fact_id'], 'value': f['value'], 'status': f['status'],
                                 'ocr_original_text': f['ocr_original_text'], 'source_reference': f['source_reference'],
                                 'bbox': f['bbox']} for f in members if f['fact_id'] in calc['input_fact_ids']])
            result.append(calc)
    return result


def overlay(image, page, target):
    vis = image.copy()
    draw = ImageDraw.Draw(vis)
    pw, ph = page.get('page_size', (image.width*72/300, image.height*72/300))
    for c in page['cells']:
        b = c.get('source_bbox')
        if b:
            rectangle = [b[0]*image.width/pw, b[1]*image.height/ph, b[2]*image.width/pw, b[3]*image.height/ph]
            draw.rectangle(rectangle, outline='green' if c['assignment_status'] == 'ok' else 'red', width=2)
    vis.save(target)


def extract_file(path, output_dir, engine=None, dpi=300, fiscal_year=2025):
    from rapidocr_onnxruntime import RapidOCR
    path, out = Path(path), Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    metadata = engine_metadata()
    engine = engine or RapidOCR(**ENGINE_SETTINGS)
    document = {'id': path.stem, 'company': 'Walmart', 'form': 'ARS',
                'fiscal_year': fiscal_year, 'html_document_id': 'wmt-2025'}
    pages = []
    def run(image, n, size):
        result = extract_page(image, path.as_posix(), n, document, engine, out, metadata, size)
        result['image'] = f'page-{n}.png'
        result['overlay'] = f'page-{n}-review.png'
        image.save(out/result['image'])
        overlay(image, result, out/result['overlay'])
        pages.append(result)
    if path.suffix.lower() == '.pdf':
        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                if p.chars:
                    pages.append({'page': p.page_number, 'scope': None, 'cells': [], 'facts': [],
                                  'exceptions': [{'status': 'TEXT_PATH_AVAILABLE', 'reason': 'Use the existing text PDF adapter; OCR was not substituted'}]})
                    continue
                run(p.to_image(resolution=dpi).original.convert('RGB'), p.page_number, (p.width,p.height))
    else:
        with Image.open(path) as im:
            image = im.convert('RGB')
        run(image, 1, (image.width*72/dpi, image.height*72/dpi))
    facts = [f for p in pages for f in p['facts']]
    report = {'document': document, 'source': path.as_posix(), 'source_sha256': compute_sha256(path),
              'engine': metadata, 'raster_dpi': dpi, 'pages': pages, 'facts': facts,
              'calculations': calculations(facts), 'exceptions': [e for p in pages for e in p['exceptions']]}
    (out/'report.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
    (out/'exceptions.json').write_text(json.dumps(report['exceptions'], indent=2, default=str), encoding='utf-8')
    lines = ['# OCR review', '', f"Source: {path.as_posix()}; SHA-256: {report['source_sha256']}",
             'Local CPU OCR; no reference values are used to repair readings. Bounding boxes use top-left PDF points. Red cells require review; green indicates geometry/text gates passed, not guaranteed correctness.', '']
    for p in pages:
        lines += [f"## Page {p['page']}: {p['scope']}", '']
        if p.get('overlay'):
            lines += [f"![Source cells]({p['overlay']})", '', '| Row / column | Original OCR text | Confidence | Source bbox | Status |', '| --- | --- | ---: | --- | --- |']
        for c in p['cells']:
            lines.append(f"| {c['row']}/{c['column']} | {c['ocr_original_text'].replace('|',' / ')} | {c['ocr_confidence']:.3f} | {c['source_bbox']} | {c['assignment_status']} {c['ocr_review_reasons']} |")
    lines += ['', '## Calculations', '']
    for c in report['calculations']:
        lines.append(f"- {c['segment']} {c['input_period']['id']} {c['metric']}: {c['status']} {c['value']}; {c.get('reason','')}; inputs: {c['inputs']}")
    lines += ['', '## Exceptions', ''] + [f"- {e.get('status')}: {e.get('label', e.get('fact_id',''))} {e.get('reason','')}" for e in report['exceptions']]
    (out/'review.md').write_text('\n'.join(lines), encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, help='Image-only PDF or PNG/JPEG table image')
    p.add_argument('--output-dir', default='data/processed/ocr/single')
    p.add_argument('--dpi', type=int, default=300, help='PDF raster DPI; source DPI for a standalone image')
    p.add_argument('--fiscal-year', type=int, default=2025)
    args = p.parse_args()
    if args.dpi < 72 or args.dpi > 600:
        p.error('DPI must be between 72 and 600')
    r = extract_file(args.input, args.output_dir, dpi=args.dpi, fiscal_year=args.fiscal_year)
    print(f"Facts: {len(r['facts'])}; statuses: {dict(Counter(f['status'] for f in r['facts']))}; exceptions: {len(r['exceptions'])}")
    print(Path(args.output_dir)/'review.md')


if __name__ == '__main__':
    main()
