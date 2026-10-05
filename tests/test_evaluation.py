from copy import deepcopy
import json
from pathlib import Path

import pytest

from sec_downloader.evaluation import score_facts, score_tables, validate_sample, raw_diagnostic
from sec_downloader.extractor import parse_numeric_value, expand_table_cells

def test_microsoft_development_split_negative_does_not_become_positive():
    # Original Microsoft FY2024 tax table 60: closing ')' lives in the next td.
    cells=expand_table_cells('<table><tr><td>Deferred taxes</td><td>( 4,738</td><td>)</td></tr></table>','msft-source')
    assert cells[1]['normalized_value'] is None
    assert 'UNBALANCED_PARENTHESES' in cells[1]['numeric_issue']
    assert parse_numeric_value('( 4,738 )')['normalized_value']==-4738

@pytest.mark.parametrize('label',['Note 12','2024 (3)','Revenue FY2024','USD 123'])
def test_mixed_labels_do_not_turn_into_amounts(label):
    assert parse_numeric_value(label)['is_numeric'] is False

def reference():
    return {'id':'x','document_id':'d','table_index':2,'row':3,'column':4,'page':None,
            'value':'25','unit':'USD (millions)','segment':'A','metric':'revenue',
            'source_reference':'d.htm#table[2]',
            'period':{'start_date':'2023-01-01','end_date':'2023-12-31','duration_days':365,'fiscal_year':2023,'period_type':'annual'}}

def test_zero_predictions_do_not_claim_perfect_accuracy():
    r=score_facts([reference()],[])
    assert r['coverage']==0 and r['end_to_end_accuracy']==0
    assert r['accuracy_on_present']['numeric'] is None
    assert r['missing_or_ambiguous']==1
    t=score_tables([{'document_id':'d','scope':'statement','html_table':2,'page':None}],[])
    assert t['recall']==0 and t['precision'] is None and t['false_negative']==1

def test_score_uses_location_not_expected_semantics_and_counts_duplicates():
    gold=reference();bad=deepcopy(gold)
    bad.update(segment='B',unit='USD',value='26')
    bad['period']['fiscal_year']=2024
    r=score_facts([gold],[bad])
    assert r['present']==1 and r['correct']['metric']==1
    assert all(r['correct'][k]==0 for k in ['numeric','period','unit','segment','joint'])
    r=score_facts([gold],[gold,bad])
    assert r['present']==0 and r['failures'][0]['status']=='AMBIGUOUS'

def test_duration_difference_is_not_a_period_match():
    gold=reference();bad=deepcopy(gold);bad['period']['duration_days']=371
    assert score_facts([gold],[bad])['correct']['period']==0

def test_raw_numeric_cell_does_not_supply_semantic_fields():
    gold=reference();cell={**gold,'normalized_value':25,'period_label':'2023'}
    result=raw_diagnostic([gold],[cell])
    assert result['numeric_correct']==1
    assert 'unit_accuracy' not in result

def test_reference_sample_and_group_separation():
    manifest=json.loads(Path('evaluation/manifest.json').read_text(encoding='utf-8'))
    refs=json.loads(Path('evaluation/references.json').read_text(encoding='utf-8'))
    validate_sample(manifest,refs)
    assert len(refs['facts'])==240
    assert len({f['unique_fact_id'] for f in refs['facts']})==120
    assert {f['period']['duration_days'] for f in refs['facts'] if f['document_id']=='cost-2024-html'}=={364,371}
    broken=deepcopy(manifest);broken['documents'][1]['split']='held_out'
    with pytest.raises(ValueError,match='leaks'):validate_sample(broken,refs)
