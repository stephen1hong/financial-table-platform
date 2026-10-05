"""Deterministic synthetic parsing/calculation/review demo; no issuer discovery claim."""
import argparse
import hashlib
import json
from pathlib import Path

from sec_downloader.extractor import expand_table_cells
from sec_downloader.periods import make_period
from sec_downloader.review_store import ReviewStore, recalculate, encoded


def run(output):
    source = Path('demo/statement.html')
    manifest = json.loads(Path('demo/manifest.json').read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['sha256']
    cells = expand_table_cells(source.read_text(), 'demo/statement.html#table[1]')
    period = make_period('2024-02-01', '2025-01-31', 12, 2025, 'annual')
    # This explicit fixture mapping is not inferred company/period/unit support.
    facts = []
    for row, metric in enumerate(('net_sales', 'cost_of_sales', 'operating_income'), 1):
        cell = next(c for c in cells if c['row'] == row and c['column'] == 1)
        facts.append(dict(fact_id=metric, metric=metric, value=str(cell['normalized_value']),
            label=metric.replace('_', ' ').title(), row=row, column=1,
            original_text=cell['text'],
            company='Synthetic demo', document_id='synthetic', table_id='statement',
            segment='Consolidated', period=period, unit='USD (millions)', status='ok',
            source_reference=cell['source_reference'], accounting_definition=f'Walmart:{metric}',
            required_review_fields=[], kind='reported'))
    calculations = recalculate(facts)
    summary = {c['metric']: format(c['value'].normalize(), 'f') for c in calculations if c['status'] == 'ok'}
    assert summary == json.loads(Path('demo/expected.json').read_text())
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    store = ReviewStore(output/'reviews.sqlite3')
    table = dict(id='statement', heading='Synthetic statement (explicit fixture mapping)',
                 source_html=source.read_text(), cells=cells)
    snapshot = dict(facts=facts, calculations=calculations, exceptions=[], tables=[table])
    identifier = store.add_document('Synthetic demo (explicit fixture mapping)',
        {'profile':'wmt-2025', 'format':'synthetic HTML'}, snapshot)
    (output/'automatic.json').write_text(encoded(snapshot))
    print(json.dumps({'expected':summary, 'document_id':identifier, 'output':str(output)}))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/processed/demo')
    run(parser.parse_args().output)
