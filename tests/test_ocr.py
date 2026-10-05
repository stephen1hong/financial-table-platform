from copy import deepcopy
from decimal import Decimal
import pytest

pytestmark = pytest.mark.ocr
pytest.importorskip('rapidocr_onnxruntime')

from sec_downloader.ocr_adapter import numeric_review, ocr_words, rotate_point, guard_facts
from sec_downloader.ocr_benchmark import evaluate
from sec_downloader.metrics import calculate_metric
from sec_downloader.periods import make_period


@pytest.mark.parametrize('text,reason',[('1O0','DIGIT_LETTER_CONFUSION'),('(2,439','UNBALANCED_OR_MISPLACED_SIGN'),
    ('2.439','UNEXPECTED_DECIMAL_IN_INTEGER_AMOUNT'),('12,34','INVALID_NUMERIC_GRAMMAR'),('1 234','MULTIPLE_NUMERIC_TOKENS')])
def test_ambiguous_numeric_readings_are_flagged_without_repair(text,reason):
    value,issues=numeric_review(text)
    assert reason in issues
    if 'O' in text or ' ' in text or text=='12,34':assert value is None


def test_parentheses_and_low_confidence_keep_original_parsed_reading():
    assert numeric_review('$ (2,439)')==(Decimal('-2439'),[])
    value,issues=numeric_review('123',.6)
    assert value==Decimal('123') and 'LOW_OCR_CONFIDENCE' in issues


def test_ocr_geometry_retains_source_polygon_and_estimates_skew():
    polygon=[[100,100],[400,106],[400,130],[100,124]]
    words,info=ocr_words([[polygon,'Long printed label',.99]],(600,800),(600,800))
    assert words[0]['source_polygon']==polygon
    assert .3<info['coordinate_correction_degrees']<5
    assert words[0]['ocr_original_text']=='Long printed label'


def test_loss_without_negative_sign_is_blocked_not_fixed():
    cells=[{'row':0,'column':0,'text':'Header','assignment_status':'ok','colspan':4},
           {'row':2,'column':0,'text':'Operating loss','ocr_original_text':'Operating loss','assignment_status':'ok','colspan':1}]
    fact={'row':2,'label':'Operating loss','segment':'Consolidated','source_reference':'scan#page=1',
          'value':Decimal(2439),'status':'ok','cell':{'ocr_original_text':'2,439','ocr_confidence':.99,'page':1,'source_bbox':[1,2,3,4]}}
    guard_facts([fact],cells,'statement')
    assert fact['value'] is None and fact['ocr_parsed_value']==Decimal(2439)
    assert 'LOSS_LABEL_WITHOUT_NEGATIVE_SIGN' in fact['review_reasons']


def test_calculator_blocks_review_status_even_if_numeric_value_exists():
    period=make_period('2024-02-01','2025-01-31',12,2025,'annual')
    base={'value':'100','unit':'USD (millions)','period':period,'fact_id':'sale','source_reference':'scan','status':'OCR_REVIEW'}
    result=calculate_metric('gross_profit',{'net_sales':base,'cost_of_sales':{**base,'status':'ok','value':'70','fact_id':'cost'}})
    assert result['status']=='unresolved' and result['value'] is None
    assert result['review_inputs']==['net_sales'] and result['input_fact_ids']==['sale','cost']


def test_spatial_benchmark_detects_wrong_period_and_segment_not_hidden_by_lookup():
    period=make_period('2024-02-01','2025-01-31',12,2025,'annual')
    gold={'source_point':[30,30],'value':'100','period':period,'unit':'USD (millions)','segment':'Walmart U.S.','metric':'net_sales'}
    fact={**gold,'value':Decimal(100),'bbox':[20,20,40,40],'status':'ok'}
    wrong=deepcopy(fact);wrong['segment']='Consolidated';wrong['period']['fiscal_year']=2024
    score=evaluate([gold],[wrong],0,(600,800))
    assert score['coverage']==1 and score['correct']['numeric']==1 and score['correct']['segment']==0 and score['correct']['period']==0
    assert evaluate([gold],[],0,(600,800))['coverage']==0
    wrong['value']=None
    assert evaluate([gold],[wrong],0,(600,800))['cases'][0]['status']=='UNRESOLVED'
