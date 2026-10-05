"""Geometry failures plus independently reviewed cached-PDF regression examples."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from sec_downloader.benchmark import evaluate
from sec_downloader.pdf_adapter import (build_report, compare_html, discover_tables,
    geometric_table, statement_facts, text_status)

DOC = {'id': 'wmt-2025-pdf', 'company': 'Walmart', 'form': 'ARS',
       'fiscal_year': 2025, 'html_document_id': 'wmt-2025'}


def word(t, x, y, width=20):
    return dict(text=t, x0=x, x1=x+width, top=y, bottom=y+8)


def part(page=1, continued=False, values=('100', '90', '80')):
    words = [word('Fiscal Years Ended January 31,', 90, 20, 150),
             word('(Amounts in millions)', 2, 35, 65)]
    words += [word(t, x, 35, 16) for t,x in zip(('2025','2024','2023'), (100,160,220))]
    words += [word('Net sales', 5, 50, 60)]
    words += [word(t, x, 50) for t,x in zip(values, (100,160,220)) if t]
    return dict(page=page, width=300, height=200, words=words, continued=continued)


def test_repeated_header_on_explicit_continuation_keeps_pages_and_one_header():
    a, b = part(), part(2, True, ('70','60','50'))
    b['words'][-4]['text'] = 'Cost of sales'
    _, cells, _, repeated, errors = geometric_table([a,b], 'fixture.pdf', DOC)
    assert not errors and len(repeated) == 1
    assert len([c for c in cells if c['text'] == '2025']) == 1
    facts, _ = statement_facts(cells, DOC, 'Consolidated Statements of Income')
    assert [f['value'] for f in facts] == list(map(Decimal, ('100','90','80','70','60','50')))
    assert [f['page'] for f in facts] == [1,1,1,2,2,2]
    assert all(f['bbox'] and f['cell']['header_cells'][0]['colspan'] == 3 for f in facts)


@pytest.mark.parametrize('mutate', ['years', 'position', 'no_evidence'])
def test_continuation_rejects_swapped_years_moved_columns_or_missing_evidence(mutate):
    b = part(2, True)
    if mutate == 'years':
        b['words'][2]['text'], b['words'][3]['text'] = '2024','2025'
    elif mutate == 'position':
        b['words'][2]['x0'] += 10
        b['words'][2]['x1'] += 10
    else:
        b['continued'] = False
    _, cells, _, _, errors = geometric_table([part(),b], 'fixture.pdf', DOC)
    assert errors[0]['status'] == 'AMBIGUOUS_CONTINUATION'
    assert not any(c['page'] == 2 for c in cells)


def test_overlapping_word_withholds_row_and_missing_cell_preserves_region():
    p = part(values=('100','','80'))
    _, cells, _, _, _ = geometric_table([p], 'fixture.pdf', DOC)
    missing = next(c for c in cells if c['row'] == 2 and c['column'] == 2)
    assert missing['assignment_status'] == 'MISSING_VALUE'
    assert missing['page'] == 1 and missing['bbox_kind'] == 'empty_cell_region'
    p['words'][-1]['x0'], p['words'][-1]['x1'] = 190, 205
    _, cells, _, _, errors = geometric_table([p], 'fixture.pdf', DOC)
    facts, _ = statement_facts(cells, DOC, 'Income')
    assert errors[0]['status'] == 'AMBIGUOUS'
    assert all(f['value'] is None for f in facts)


def test_text_detection_distinguishes_short_cover_scanned_and_blank_pages():
    assert text_status('', 1) == 'UNSUPPORTED_IMAGE_ONLY'
    assert text_status('  ', 0) == 'NO_USABLE_TEXT'
    assert text_status('Annual Report 2025', 1) == 'LIMITED_TEXT'
    assert text_status('Consolidated financial results for the annual reporting period') == 'TEXT'


def test_financial_rows_near_page_bottom_are_not_discarded_as_footers():
    p = part()
    for w in p['words'][-4:]:
        w['top'], w['bottom'] = 190, 198
    _, cells, _, _, errors = geometric_table([p], 'fixture.pdf', DOC)
    facts, _ = statement_facts(cells, DOC, 'Income')
    assert not errors and len(facts) == 3
    assert facts[0]['value'] == Decimal('100')


def test_discovery_ignores_toc_and_uses_previous_note_heading():
    pages = [{'page': 2, 'text': 'Consolidated Statements of Income 53'},
             {'page': 71, 'text': 'Note 12. Segments and Disaggregated Revenue'},
             {'page': 72, 'text': "Walmart U.S. Walmart International Sam's Club U.S. Corporate and support Cost of sales Income before income taxes"}]
    found = discover_tables(pages)
    assert found['statement'] == []
    assert found['segment_note'][0]['page'] == 72
    assert found['segment_note'][0]['heading_page'] == 71


@pytest.fixture(scope='module')
def pdf_report():
    return build_report()


@pytest.mark.real_data
def test_pdf_examples_hierarchy_merged_headers_footnotes_and_values(pdf_report):
    r = pdf_report
    assert r['verification']['page'] == 3
    assert [(t['scope'], t['page']) for t in r['tables']] == [('statement',55), ('segment_note',80)]
    assert len(r['facts']) == 111
    assert all(c['status'] == 'MATCH' for c in r['comparisons'])
    sam = next(f for f in r['facts'] if f['scope'] == 'segment_note' and f['segment'] == "Sam's Club U.S." and f['metric'] == 'net_sales' and f['period']['fiscal_year'] == 2025)
    assert sam['value'] == Decimal('90238')
    assert sam['hierarchical_label'][-2] == "Sam's Club U.S.(1)"
    assert 'fuel-related expenses' in sam['footnotes'][0]['text']
    assert sam['bbox'] and sam['page'] == 80
    assert sam['cell']['header_cells'][0]['colspan'] == 3
    corp = next(f for f in r['facts'] if f['segment'] == 'Corporate and support' and f['metric'] == 'operating_income' and f['period']['fiscal_year'] == 2025)
    assert corp['value'] == Decimal('-2439')
    operating = next(f for f in r['facts'] if f['scope'] == 'statement' and f['metric'] == 'operating_income')
    assert 'Costs and expenses:' not in operating['hierarchical_label']


@pytest.mark.real_data
@pytest.mark.parametrize('field,value', [('segment','Walmart International'), ('unit','USD'), ('company','Apple'), ('metric','net_income')])
def test_semantic_mismatch_never_compares_or_fills_values(pdf_report, field, value):
    pdf = deepcopy(pdf_report['facts'][0])
    html = deepcopy(pdf)
    html[field] = value
    result = compare_html([pdf], [html])
    assert result[0]['status'] == 'NO_COMPARABLE_FACT'
    assert result[1]['status'] == 'MISSING_PDF_FACT'
    assert pdf['value'] == pdf_report['facts'][0]['value']


@pytest.mark.real_data
def test_period_swap_duplicate_and_numeric_disagreement_remain_exceptions(pdf_report):
    pdf = deepcopy(pdf_report['facts'][0]); html = deepcopy(pdf)
    html['period']['start_date'] = '2024-08-01'
    assert compare_html([pdf], [html])[0]['status'] == 'NO_COMPARABLE_FACT'
    html = deepcopy(pdf); html['value'] += 1
    assert compare_html([pdf], [html])[0]['difference'] == -1
    assert compare_html([pdf], [html,html])[0]['status'] == 'AMBIGUOUS'
    assert compare_html([pdf,pdf], [html])[0]['status'] == 'AMBIGUOUS'
    pdf['value'] = None
    assert compare_html([pdf], [html])[0]['status'] == 'NO_COMPARABLE_FACT'
    assert pdf['value'] is None
    pdf['value'] = Decimal(1)
    pdf['period'] = None
    html['period'] = None
    assert compare_html([pdf], [html])[0]['status'] == 'NO_COMPARABLE_FACT'


@pytest.mark.real_data
def test_frozen_pdf_benchmark_measures_missing_mappings_and_table_coverage(pdf_report):
    fixture = json.loads(Path('tests/fixtures/pdf_benchmark_facts.json').read_text())
    score = evaluate(fixture['facts'], pdf_report['facts'])
    assert score['expected'] == 45 and score['present'] == 39
    assert len(score['missing']) == 6
    assert all(v == 1 for v in score['accuracy_on_present'].values())
    broken = deepcopy(pdf_report['facts'])
    broken[0]['period'], broken[1]['period'] = broken[1]['period'], broken[0]['period']
    assert evaluate(fixture['facts'], broken)['correct']['period'] == 37
    no_segments = [f for f in broken if f['scope'] != 'segment_note']
    assert evaluate(fixture['facts'], no_segments)['present'] == 21
