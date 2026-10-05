import importlib.util
from pathlib import Path

from sec_downloader.review_app import create_app


def test_offline_demo_parsing_calculations_persistence_and_ui(tmp_path):
    spec = importlib.util.spec_from_file_location('offline_demo', Path('scripts/offline_demo.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.run(tmp_path)['gross_profit'] == '40'
    app = create_app(tmp_path)
    client = app.test_client()
    assert client.get('/').status_code == 200
    assert client.get('/static/review.js').status_code == 200
    assert len(app.extensions['review_store'].list_documents()) == 1
    store = app.extensions['review_store']
    identifier = store.list_documents()[0]['id']
    automatic = store.get(identifier)['automatic']
    assert automatic['tables'][0]['source_html'] and automatic['tables'][0]['cells']
    result = store.correct(identifier, 'net_sales', 'value', '120', 'Demo review', 0)
    gross = lambda rows: next(c for c in rows if c['metric'] == 'gross_profit')
    from decimal import Decimal
    assert Decimal(gross(result['reviewed_calculations'])['value']) == 60
    assert Decimal(gross(result['automatic']['calculations'])['value']) == 40
