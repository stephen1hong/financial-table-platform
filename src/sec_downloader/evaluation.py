"""Milestone 12A: frozen cross-issuer evaluation, without gold-assisted extraction.

Collection reads only the document manifest. Scoring reads references afterwards.
The raw HTML cell diagnostic is explicitly conditional on an annotated location;
it is NOT an end-to-end financial extraction or table-detection score.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import platform
import time

from bs4 import BeautifulSoup
import pdfplumber

from .downloader import compute_sha256, verify_cached_file
from .extractor import expand_table_cells
from .inventory import inventory_tables, identify_income_statements
from .metrics import reported_periods
from .pdf_adapter import discover_tables, text_status

ROOT=Path(__file__).resolve().parents[2]
EVAL=ROOT/'evaluation'
RAW=ROOT/'data/raw/evaluation12a'
OUTPUT=ROOT/'data/processed/evaluation12a'
FIELDS=('numeric','period','unit','segment','metric','joint')

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,default=str)+'\n',encoding='utf-8')

def fingerprint():
    paths=sorted((ROOT/'src/sec_downloader').glob('*.py'))
    paths += [EVAL/'manifest.json',EVAL/'references.json',EVAL/'reference_rows.json']
    return {p.relative_to(ROOT).as_posix():compute_sha256(p) for p in paths}

def validate_sample(manifest,references):
    docs=manifest['documents'];ids={d['id'] for d in docs}
    if len(ids)!=len(docs) or len(docs)<10 or len({d['company'] for d in docs})<5:
        raise ValueError('Need ten unique document IDs across at least five companies')
    groups={}
    for d in docs:
        groups.setdefault(d['filing_group'],set()).add(d['split'])
        if not d.get('sha256') or len(d['sha256'])!=64:raise ValueError('Missing checksum')
    if any(len(s)>1 for s in groups.values()):raise ValueError('Filing group leaks across splits')
    facts=references['facts']
    if len({f['unique_fact_id'] for f in facts})<100:raise ValueError('Need 100 distinct annotated facts')
    if any(f['document_id'] not in ids for f in facts):raise ValueError('Unknown reference document')
    for d in docs:
        fs=[f for f in facts if f['document_id']==d['id']]
        if not fs or any(f['source_sha256']!=d['sha256'] for f in fs):raise ValueError('Reference/source mismatch')

def collect(document):
    """No reference values, table indexes or source pages enter this function."""
    started=time.perf_counter();d=document;path=RAW/d['filename']
    result={'document_id':d['id'],'company':d['company'],'format':d['format'],'split':d['split'],
            'tables':[],'facts':[],'raw_cells':[],'exceptions':[],'calculations':[]}
    def error(stage,exc):result['exceptions'].append({'stage':stage,'status':'UNSUPPORTED_OR_FAILED','reason':str(exc)})
    try:
        if not verify_cached_file(path,d['sha256']):raise ValueError('Cache checksum mismatch or missing document')
        if d['format']=='html':
            inventory=inventory_tables(d,RAW);result['inventory_count']=len(inventory)
            soup=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
            # All tables are processed, not just gold locations. Raw cells have no
            # inferred currency, accounting definition, segment or complete period.
            for i,table in enumerate(soup.find_all('table'),1):
                cells=expand_table_cells(table,f'{d["filename"]}#table[{i}]')
                for c in cells:c.update(document_id=d['id'],table_index=i)
                result['raw_cells'].extend(cells)
            try:
                selected=identify_income_statements(d,RAW)
                result['tables'] += [{'scope':'statement','table_index':t['table_index']} for t in selected]
                for g in reported_periods(d,RAW):result['facts'].extend(g['reported_facts'].values())
            except (ValueError,KeyError) as exc:error('consolidated_statement',exc)
            # Existing segment entry points require a reviewed issuer configuration.
            # Never impersonate Walmart/Amazon or inject gold labels to bypass it.
            error('segment_note','No reviewed segment configuration for '+d['filing_group'])
            error('financial_footnote','No financial-footnote mapping adapter')
        elif d['format']=='pdf':
            pages=[]
            with pdfplumber.open(path) as pdf:
                for p in pdf.pages:
                    txt=p.extract_text() or ''
                    pages.append({'page':p.page_number,'text':txt,'status':text_status(txt,len(p.images))})
                    p.close()
            result['page_count']=len(pages)
            result['page_status_counts']=dict(Counter(p['status'] for p in pages))
            result['cid_text_pages']=[p['page'] for p in pages if '(cid:' in p['text']]
            candidates=discover_tables(pages)
            result['discovery_candidates']=candidates
            for scope,items in candidates.items():
                result['tables'].extend({'scope':scope,'page':t['page']} for t in items)
                if not items:error(scope,'Existing PDF heading/content detector found no supported table')
            error('pdf_financial_mapping','Current complete PDF adapter verifies Walmart FY2025 only; no issuer substitution attempted')
            error('financial_footnote','No financial-footnote mapping adapter')
        else:raise ValueError('Unsupported evaluation format')
    except Exception as exc:error('document',exc)
    result['runtime_seconds']=round(time.perf_counter()-started,4)
    return result

def ratio(n,d):return n/d if d else None

def fact_key(f):return f.get('document_id'),f.get('table_index'),f.get('row'),f.get('column'),f.get('page')

def score_facts(expected,predictions):
    index={}
    for f in predictions:index.setdefault(fact_key(f),[]).append(f)
    correct=dict.fromkeys(FIELDS,0);present=0;failures=[]
    for gold in expected:
        found=index.get(fact_key(gold),[])
        if len(found)!=1 or found[0].get('value') is None:
            failures.append({'id':gold['id'],'status':'AMBIGUOUS' if len(found)>1 else 'MISSING','source_reference':gold['source_reference']});continue
        p=found[0];present+=1
        checks={'numeric':Decimal(str(p['value']))==Decimal(gold['value']),
                'period':all((p.get('period') or {}).get(k)==gold['period'][k] for k in ('start_date','end_date','duration_days','fiscal_year','period_type')),
                'unit':p.get('unit')==gold['unit'],'segment':p.get('segment')==gold['segment'],'metric':p.get('metric')==gold['metric']}
        checks['joint']=all(checks.values())
        for k,v in checks.items():correct[k]+=int(v)
        if not checks['joint']:failures.append({'id':gold['id'],'status':'INCORRECT','checks':checks,'actual':p,'expected':gold})
    return dict(expected=len(expected),present=present,missing_or_ambiguous=len(expected)-present,
                coverage=ratio(present,len(expected)),correct=correct,
                accuracy_on_present={k:ratio(v,present) for k,v in correct.items()},
                end_to_end_accuracy=ratio(correct['joint'],len(expected)),failures=failures)

def score_tables(expected,predictions):
    def key(t):return t['document_id'],t['scope'],t.get('table_index',t.get('html_table')),t.get('page')
    gold={key(t) for t in expected};pred=[key(t) for t in predictions]
    tp=len(gold & set(pred));fp=len(pred)-tp;fn=len(gold)-tp
    return dict(expected=len(gold),predicted=len(pred),true_positive=tp,false_positive=fp,false_negative=fn,
                precision=ratio(tp,len(pred)),recall=ratio(tp,len(gold)))

def raw_diagnostic(expected,cells):
    index={fact_key(c):c for c in cells};present=0;correct=0;year_correct=0;errors=[]
    for g in expected:
        c=index.get(fact_key(g));value=c.get('normalized_value') if c else None
        ok=value is not None and Decimal(str(value))==Decimal(g['value'])
        present+=int(value is not None);correct+=int(ok)
        year_correct+=int(bool(c) and c.get('period_label')==str(g['period']['fiscal_year']))
        if not ok:errors.append({'id':g['id'],'source_reference':g['source_reference'],'expected':g['value'],
            'actual':value,'text':c.get('text') if c else None,'issue':c.get('numeric_issue') if c else None})
    return dict(expected=len(expected),present=present,numeric_correct=correct,numeric_accuracy_on_present=ratio(correct,present),
                numeric_coverage=ratio(present,len(expected)),correct_year_label=year_correct,
                year_label_accuracy_over_all=ratio(year_correct,len(expected)),errors=errors,
                caveat='Oracle-located raw HTML cells only. Year label is NOT a complete fiscal period. No unit/segment/metric inference, no financial-calculation credit.')

def aggregate(documents,references):
    ids={d['document_id'] for d in documents}
    fs=[f for f in references['facts'] if f['document_id'] in ids]
    ts=[t for t in references['tables'] if t['document_id'] in ids]
    facts=[f for d in documents for f in d['facts']]
    tables=[dict(t,document_id=d['document_id']) for d in documents for t in d['tables']]
    return dict(documents=len(documents),runtime_seconds=round(sum(d['runtime_seconds'] for d in documents),4),
        tables=score_tables(ts,tables),facts=score_facts(fs,facts),
        raw_html_cells=raw_diagnostic([f for f in fs if f['format']=='html'],[c for d in documents for c in d['raw_cells']]),
        calculations_produced=sum(len(d['calculations']) for d in documents),
        by_format={fmt:{'tables':score_tables([t for t in ts if t['document_id'] in {d['document_id'] for d in documents if d['format']==fmt}],
                     [t for t in tables if t['document_id'] in {d['document_id'] for d in documents if d['format']==fmt}]),
                     'facts':score_facts([f for f in fs if f['format']==fmt],facts)} for fmt in ('html','pdf')},
        by_table_type={scope:{'tables':score_tables([t for t in ts if t['scope']==scope],[t for t in tables if t['scope']==scope]),
                     'facts':score_facts([f for f in fs if f['scope']==scope],facts)} for scope in ('statement','segment_note','financial_footnote')})

def report(result,out):
    a=result['summary'];lines=['# Broader real-document evaluation',
        f"Run: {result['run_name']}; split: {result['split']}; UTC: {result['created_at']}",
        'Automatic output only. No manual correction overlays. Frozen code and source hashes are in results.json.',
        'Ten document representations / five filing groups. Three target tables per document; recall is over these annotated targets, not every financial footnote in each report. Precision is undefined when no tables are predicted.',
        '| Group | Tables TP / targets | Table precision | Mapped facts / references | Numeric accuracy on present | Fact coverage |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for group,s in [('all',a)]+list(a['by_format'].items())+list(a['by_table_type'].items()):
        t,f=s['tables'],s['facts']
        lines.append(f"| {group} | {t['true_positive']}/{t['expected']} | {t['precision'] if t['precision'] is not None else 'N/A (0 predictions)'} | {f['present']}/{f['expected']} | {f['accuracy_on_present']['numeric'] if f['present'] else 'N/A (0 facts)'} | {f['coverage']:.2%} |")
    lines += ['',f"Runtime: {a['runtime_seconds']:.2f} seconds; completed calculations: {a['calculations_produced']}.",
        'Period, unit, segment, metric and joint accuracies use the same present-fact denominator; all are N/A where no mapped facts exist. End-to-end accuracy includes missing facts.',
        '', '## Conditional raw HTML cell diagnostic', a['raw_html_cells']['caveat'],
        f"Numeric: {a['raw_html_cells']['numeric_correct']}/{a['raw_html_cells']['present']} present; {a['raw_html_cells']['present']}/{a['raw_html_cells']['expected']} coverage. Correct year labels: {a['raw_html_cells']['correct_year_label']}/{a['raw_html_cells']['expected']}.",
        '', '## Document failures and runtimes']
    for d in result['documents']:
        lines.append(f"\n### {d['document_id']} ({d['runtime_seconds']:.2f}s)")
        if 'inventory_count' in d:lines.append(f"Unclassified HTML table inventory: {d['inventory_count']}. This is not financial-table detection.")
        if 'page_count' in d:lines.append(f"PDF pages: {d['page_count']}; text statuses: {d['page_status_counts']}; CID-encoded text pages: {len(d['cid_text_pages'])}.")
        lines += [f"- {e['stage']}: {e['reason']}" for e in d['exceptions']]
    lines += ['', '## Actual raw-cell errors']
    lines += [f"- {e['source_reference']}: expected {e['expected']}; observed {e['actual']}; source text `{e['text']}`; issue {e['issue']}" for e in a['raw_html_cells']['errors']]
    lines += ['', 'All missing fact IDs/source references and per-field counts are retained in results.json. No broader support claim is established. See evaluation/PROTOCOL.md and evaluation/REPORT.md for scope, annotations and interpretation.']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split',choices=['development','held_out'],default='held_out')
    parser.add_argument('--run-name',default='final-held-out')
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args();manifest=read(EVAL/'manifest.json');refs=read(EVAL/'references.json')
    validate_sample(manifest,refs)
    if args.freeze:
        if (EVAL/'freeze.json').exists():raise SystemExit('Freeze already exists; do not silently replace it')
        write(EVAL/'freeze.json',{'created_at':datetime.now(timezone.utc).isoformat(),'fingerprint':fingerprint()});print('Frozen');return 0
    before=fingerprint()
    if args.split=='held_out' and read(EVAL/'freeze.json')['fingerprint']!=before:
        raise SystemExit('Code/sample/reference changes since freeze; held-out evaluation refused')
    results=[]
    for d in manifest['documents']:
        if d['split']!=args.split:continue
        print('Processing '+d['id'],flush=True);results.append(collect(d))
    if fingerprint()!=before:raise SystemExit('Inputs/code changed during run; no valid score written')
    result=dict(created_at=datetime.now(timezone.utc).isoformat(),run_name=args.run_name,split=args.split,
                python=platform.python_version(),fingerprint=before,summary=aggregate(results,refs),documents=results)
    out=OUTPUT/args.run_name;write(out/'results.json',result);report(result,out)
    print(json.dumps({k:result['summary'][k] for k in ('documents','runtime_seconds','tables','calculations_produced')}))
    print('Report: '+str(out/'report.md'));return 0

if __name__=='__main__':raise SystemExit(main())
