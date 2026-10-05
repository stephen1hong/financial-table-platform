from copy import deepcopy
import json
from decimal import Decimal
import pytest

pytest.importorskip('flask')

from sec_downloader.review_store import ReviewStore, compatible_comparison, recalculate
from sec_downloader.periods import make_period
from sec_downloader.review_app import create_app
from sec_downloader.review_pipeline import clean_html_table


def snapshot():
    period=make_period('2024-02-01','2025-01-31',12,2025,'annual')
    facts=[]
    for metric,value in [('net_sales','100'),('cost_of_sales','60'),('operating_income','20')]:
        facts.append({'fact_id':metric,'metric':metric,'company':'Walmart','document_id':'wmt-2025','table_id':'statement',
                      'segment':'Consolidated','period':deepcopy(period),'unit':'USD (millions)','value':value,'status':'ok',
                      'source_reference':'fixture.htm#table[1]','accounting_definition':f'Walmart:{metric}',
                      'required_review_fields':[],'kind':'reported'})
    return {'facts':facts,'tables':[],'exceptions':[],'calculations':recalculate(facts)}


def test_correction_survives_restart_and_does_not_change_automatic_snapshot(tmp_path):
    path=tmp_path/'reviews.sqlite';store=ReviewStore(path);auto=snapshot()
    identifier=store.add_document('Source',{'profile':'wmt-2025'},auto)
    corrected=store.correct(identifier,'net_sales','value','120','Checked against source',0)
    reopened=ReviewStore(path).get(identifier)
    assert reopened['automatic']['facts'][0]['value']=='100'
    assert reopened['reviewed_facts'][0]['value']=='120'
    assert reopened['history'][0]['old_value']=='100' and reopened['history'][0]['new_value']=='120'
    assert reopened['history'][0]['timestamp'] and reopened['history'][0]['review_status']=='approved'
    assert reopened['history'][0]['source_reference']=='fixture.htm#table[1]'
    gp=next(c for c in reopened['reviewed_calculations'] if c['metric']=='gross_profit')
    assert gp['value']==Decimal(60) and {i['fact_id'] for i in gp['inputs']}=={'net_sales','cost_of_sales'}
    assert next(c for c in reopened['automatic']['calculations'] if c['metric']=='gross_profit')['value']=='40'


def test_optimistic_revision_and_validation_leave_audit_unchanged_on_failure(tmp_path):
    store=ReviewStore(tmp_path/'r.db');identifier=store.add_document('test',{'profile':'wmt-2025'},snapshot())
    with pytest.raises(ValueError,match='reason'):store.correct(identifier,'net_sales','value','120','',0)
    with pytest.raises(ValueError,match='finite'):store.correct(identifier,'net_sales','value','NaN','Review',0)
    store.correct(identifier,'net_sales','value','120','Review',0)
    with pytest.raises(ValueError,match='another tab'):store.correct(identifier,'net_sales','value','130','Review',0)
    assert len(store.get(identifier)['history'])==1


def test_unit_or_period_correction_blocks_incompatible_calculation(tmp_path):
    store=ReviewStore(tmp_path/'r.db');identifier=store.add_document('test',{'profile':'wmt-2025'},snapshot())
    r=store.correct(identifier,'cost_of_sales','unit','EUR (millions)','Source currency',0)
    assert next(c for c in r['reviewed_calculations'] if c['metric']=='gross_profit')['status']=='unit_mismatch'
    r=store.correct(identifier,'cost_of_sales','period',make_period('2023-02-01','2024-01-31',12,2024,'annual'),'Prior year column',1)
    assert all(c['status']!='ok' for c in r['reviewed_calculations'] if c['metric']=='gross_profit')


@pytest.mark.parametrize('change',[{'unit':'EUR (millions)'},{'accounting_definition':'different'},{'metric':'total_revenues'},{'segment':'Walmart U.S.'},{'status':'OCR_REVIEW'}])
def test_incompatible_comparisons_rejected(change):
    a=snapshot()['facts'][0];b={**deepcopy(a),**change}
    with pytest.raises(ValueError,match='blocked|resolved'):compatible_comparison(a,b)


def test_comparison_rejects_quarter_vs_annual_and_allows_exact_context():
    a=snapshot()['facts'][0];b=deepcopy(a)
    assert compatible_comparison(a,b)['difference']=='0'
    b['period']=make_period('2024-11-01','2025-01-31',3,2025,'quarter')
    with pytest.raises(ValueError,match='dates'):compatible_comparison(a,b)


def test_partial_ocr_review_does_not_approve_uncorrected_header(tmp_path):
    auto=snapshot();f=auto['facts'][0];f.update(value=None,status='OCR_REVIEW',required_review_fields=['value','period','unit'])
    store=ReviewStore(tmp_path/'r.db');identifier=store.add_document('OCR',{'profile':'wmt-2025'},auto)
    r=store.correct(identifier,'net_sales','value','100','Reviewed number',0)
    assert r['reviewed_facts'][0]['status']=='REVIEW_REQUIRED'
    assert next(c for c in r['reviewed_calculations'] if c['metric']=='gross_profit')['status']=='unresolved'


def test_mapping_review_is_persisted_and_duplicate_inputs_are_not_silently_selected(tmp_path):
    auto=snapshot();candidate=deepcopy(auto['facts'][0])
    candidate.update(fact_id='candidate',metric=None,concept=None,value=None,unit=None,status='UNMAPPED',required_review_fields=['mapping','unit','value'])
    auto['facts'].append(candidate)
    store=ReviewStore(tmp_path/'r.db');identifier=store.add_document('test',{'profile':'wmt-2025'},auto)
    store.correct(identifier,'candidate','mapping','net_sales','Reviewed definition',0)
    store.correct(identifier,'candidate','unit','USD (millions)','Reviewed scale',1)
    result=store.correct(identifier,'candidate','value','12','Reviewed amount',2)
    mapped=next(f for f in ReviewStore(tmp_path/'r.db').get(identifier)['reviewed_facts'] if f['fact_id']=='candidate')
    assert mapped['metric']=='net_sales' and mapped['concept']=='us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'
    assert mapped['review_status']=='approved'
    calc=next(c for c in result['reviewed_calculations'] if c['metric']=='gross_profit')
    assert calc['status']=='unresolved' and calc['duplicates']==['net_sales']


def test_local_api_requires_token_and_exports_original_and_history_separately(tmp_path):
    app=create_app(tmp_path);client=app.test_client();store=app.extensions['review_store']
    identifier=store.add_document('Source',{'profile':'wmt-2025'},snapshot())
    body={'fact_id':'net_sales','field':'value','new_value':'120','reason':'Source checked','revision':0}
    assert client.post(f'/api/documents/{identifier}/corrections',json=body).status_code==403
    response=client.post(f'/api/documents/{identifier}/corrections',json=body,headers={'X-Local-Token':app.extensions['review_token']})
    assert response.status_code==200
    automatic=client.get(f'/api/documents/{identifier}/export?view=automatic').get_json()
    reviewed=client.get(f'/api/documents/{identifier}/export?view=reviewed').get_json()
    assert automatic['facts'][0]['value']=='100' and reviewed['facts'][0]['value']=='120'
    assert reviewed['history'][0]['reason']=='Source checked'
    assert reviewed['history'][0]['source_reference']=='fixture.htm#table[1]'
    csv=client.get(f'/api/documents/{identifier}/export?format=csv&dataset=history').text
    assert 'old_value' in csv and 'new_value' in csv and 'Source checked' in csv
    assert client.get('/',headers={'Host':'evil.example'}).status_code==403
    assert client.get(f'/assets/{identifier}/reviews.sqlite3').status_code==404


def test_comparison_api_honors_automatic_vs_reviewed_selection(tmp_path):
    app=create_app(tmp_path);client=app.test_client();store=app.extensions['review_store']
    left=store.add_document('left',{'profile':'wmt-2025'},snapshot())
    right=store.add_document('right',{'profile':'wmt-2025'},snapshot())
    store.correct(left,'net_sales','value','120','Checked',0)
    payload={'left':{'document_id':left,'fact_id':'net_sales'},'right':{'document_id':right,'fact_id':'net_sales'}}
    header={'X-Local-Token':app.extensions['review_token']}
    assert client.post('/api/compare',json={**payload,'view':'automatic'},headers=header).get_json()['difference']=='0'
    assert client.post('/api/compare',json={**payload,'view':'reviewed'},headers=header).get_json()['difference']=='20'


def test_untrusted_html_source_does_not_keep_scripts_or_external_resources():
    cleaned=clean_html_table('<table onclick="alert(1)"><tr><td><script>alert(1)</script><img src="https://evil/">Value</td></tr></table>')
    assert 'script' not in cleaned and 'onclick' not in cleaned and 'img' not in cleaned and 'Value' in cleaned
