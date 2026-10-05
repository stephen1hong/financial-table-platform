"""Local UI routing into the existing HTML, text-PDF and OCR adapters."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import re
import shutil

from bs4 import BeautifulSoup
import pdfplumber

from .downloader import MANIFEST_PATH, RAW_DIR, compute_sha256
from .manifest import load_manifest
from .extractor import extract_document_statement, expand_table_cells
from .metrics import reported_periods
from .filing_profiles import PROFILES
from .accounting import qname
from .review_store import recalculate, encoded


def clean_html_table(markup):
    soup=BeautifulSoup(markup,'html.parser')
    for tag in list(soup.find_all(True)):
        if tag.name in ('script','style','iframe','object','embed','img','link','meta','form','input'):
            tag.decompose()
        elif tag.name not in ('table','tr','td','th','tbody','thead','tfoot','caption','span','div','p','br','b','strong','i','em','sup'):
            tag.unwrap()
        else:
            tag.attrs={k:v for k,v in tag.attrs.items() if k in ('rowspan','colspan') and str(v).isdigit()}
    return str(soup)


def catalog():
    manifest=load_manifest(MANIFEST_PATH)
    result=[{**d,'profile':d['id']} for d in manifest['documents']]
    result += [{**d,'profile':d['html_document_id']} for d in manifest.get('pdf_documents',[]) if d['id']=='wmt-2025-pdf']
    for page in (55,80):
        p=Path(f'data/processed/ocr/scans/clean-page-{page}.pdf')
        if p.exists():result.append({'id':f'scan-{page}','company':'Walmart','filename':p.name,'path':str(p),
                                    'profile':'wmt-2025','form':'Simulated scan','fiscal_year':2025})
    return result


def normalize(result, profile):
    facts=result['facts'];tables=result['tables']
    mapping=PROFILES[profile][4]
    for f in facts:
        f.setdefault('scope','statement');f.setdefault('segment','Consolidated');f.setdefault('kind','reported')
        f.setdefault('status','ok' if f.get('value') is not None else 'REVIEW_REQUIRED')
        f.setdefault('concept',mapping.get(f['metric'],('',None))[1])
        if f.get('concept'):f['concept']=qname(f['concept'])
        f['accounting_definition']=f"{f['company']}:{f['metric']}:{f.get('concept')}"
        f.setdefault('bbox',(f.get('cell') or {}).get('source_bbox') or (f.get('cell') or {}).get('bbox'))
        f.setdefault('page',(f.get('cell') or {}).get('page'))
        f['table_id']=next(t['id'] for t in tables if t['scope']==f['scope'] and (not t.get('page') or not f.get('page') or t['page']==f['page']))
        fields=set()
        for reason in f.get('review_reasons',[]):
            if reason=='UNCERTAIN_PERIOD_OR_UNIT_HEADER':fields.update(['period','unit'])
            elif reason=='UNCERTAIN_ROW_LABEL':fields.add('mapping')
            elif reason=='UNCERTAIN_SEGMENT_HEADER':fields.add('segment')
            else:fields.add('value')
        if f['status']!='ok' and not fields:fields.add('value')
        f['required_review_fields']=sorted(fields)
    # Unmapped cells remain review candidates, never canonical automatic facts.
    occupied={(f['table_id'],f['row'],f['column']) for f in facts}
    for t in tables:
        for c in t['cells']:
            if c['row']<=1 or c['column']==0 or not c.get('is_numeric') or (t['id'],c['row'],c['column']) in occupied:continue
            label=next((x['text'] for x in t['cells'] if x['row']==c['row'] and x['column']==0),'Unmapped row')
            period=c.get('period')
            if not period and c.get('period_label'):
                from .periods import resolve_period
                try:period=resolve_period(c['header_text'],{'company':result['company'],'form':'10-K','id':profile})
                except ValueError:pass
            f={'fact_id':f"candidate:{t['id']}:{c['row']}:{c['column']}",'company':result['company'],
               'document_id':profile,'scope':t['scope'],'table_id':t['id'],'metric':None,'concept':None,
               'label':label,'segment':'Consolidated' if t['scope']=='statement' else None,
               'value':None,'unit':None,'period':period,'kind':'unmapped','status':'UNMAPPED',
               'original_text':c.get('ocr_original_text',c['text']),'source_reference':c['source_reference'],
               'bbox':c.get('source_bbox') or c.get('bbox'),'page':c.get('page'), 'row':c['row'],'column':c['column'],
               'required_review_fields':['mapping','unit','value']+([] if period else ['period'])+([] if t['scope']=='statement' else ['segment'])}
            facts.append(f)
            result['exceptions'].append({'status':'UNMAPPED','fact_id':f['fact_id'],'reason':'Raw source cell needs a reviewed value, accounting mapping and unit before calculations.','source_reference':f['source_reference']})
    result['calculations']=recalculate(facts)
    return result


def process(path, profile, directory, progress=lambda n,s:None):
    path=Path(path);out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    manifest=load_manifest(MANIFEST_PATH)
    doc=deepcopy(next(d for d in manifest['documents'] if d['id']==profile))
    raw=out/'raw';raw.mkdir(exist_ok=True)
    progress(10,'Checking file signature and supported company profile')
    pdf=path.read_bytes()[:5]==b'%PDF-'
    if pdf:
        if profile!='wmt-2025':raise ValueError('PDF support is currently Walmart FY2025. Select that profile or use one of the supported HTML filings.')
        with pdfplumber.open(path) as p:
            text_present=any(bool(page.chars) for page in p.pages)
        if not text_present:
            progress(25,'Running local OCR, table geometry and uncertainty checks')
            from .ocr_adapter import extract_file
            r=extract_file(path,out,dpi=300,fiscal_year=doc['fiscal_year'])
            tables=[{'id':f"{p['scope']}:{p['page']}",'scope':p['scope'],'heading':p.get('heading','No supported table'),
                     'page':p['page'],'cells':p['cells'],'image':p.get('image'),'page_size':p.get('page_size')}
                    for p in r['pages'] if p.get('scope')]
            result={'company':doc['company'],'format':'scanned PDF (OCR)','tables':tables,'facts':r['facts'],'exceptions':r['exceptions']}
        else:
            progress(25,'Extracting text PDF tables and comparing with cached HTML')
            from .pdf_adapter import build_report
            pdfdoc=deepcopy(next(d for d in manifest['pdf_documents'] if d['id']=='wmt-2025-pdf'))
            pdfdoc.update(filename='input.pdf',sha256=compute_sha256(path))
            shutil.copyfile(path,raw/'input.pdf');shutil.copyfile(RAW_DIR/doc['filename'],raw/doc['filename'])
            temporary={'documents':[doc],'pdf_documents':[pdfdoc]}
            m=out/'manifest.json';m.write_text(encoded(temporary))
            r=build_report(m,raw,render_dir=out)
            tables=[{**t,'id':t['scope'],'image':f"page-{t['page']}.png"} for t in r['tables']]
            with pdfplumber.open(path) as p:
                for t in tables:t['page_size']=[p.pages[t['page']-1].width,p.pages[t['page']-1].height]
            result={'company':doc['company'],'format':'text PDF','tables':tables,'facts':r['facts'],'exceptions':r['exceptions']}
    else:
        if path.suffix.lower() not in ('.html','.htm'):raise ValueError('Upload HTML (.htm/.html) or a PDF. Images can use the OCR command directly.')
        progress(20,'Selecting HTML tables and extracting periods and reported values')
        doc.update(filename='input.htm',sha256=compute_sha256(path));shutil.copyfile(path,raw/doc['filename'])
        m=out/'manifest.json';m.write_text(encoded({'documents':[doc]}))
        extracted=extract_document_statement(doc,raw)
        soup=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
        table=soup.find_all('table')[extracted['table_index']-1]
        tables=[{'id':'statement','scope':'statement','heading':'Consolidated income statement',
                 'cells':extracted['cells'],'source_html':clean_html_table(str(table))}]
        facts=[{**f,'scope':'statement'} for group in reported_periods(doc,raw) for f in group['reported_facts'].values()]
        progress(55,'Validating Inline XBRL contexts and segment results')
        from .validation import build_validation
        errors=build_validation(m,raw)['exceptions']
        if profile in ('wmt-2025','amzn-2025'):
            if profile=='wmt-2025':
                from .segments import build_segment_report
                segments=build_segment_report(m,raw)
            else:
                from .segment_reporting import build_report
                segments=build_report(m,raw)
            index=int(re.search(r'#table\[(\d+)\]',segments['source_reference'])[1])
            tables.append({'id':'segment_note','scope':'segment_note','heading':segments['heading'] if 'heading' in segments else 'Segment results',
                           'cells':segments['cells'],'source_html':clean_html_table(str(soup.find_all('table')[index-1]))})
            facts += [{**f,'scope':'segment_note'} for f in segments['facts']]
            errors += segments['exceptions']
        result={'company':doc['company'],'format':'HTML','tables':tables,'facts':facts,'exceptions':errors}
    if not result['tables']:
        details='; '.join(e.get('reason',e.get('status','')) for e in result['exceptions'][:4])
        raise ValueError('No supported table was extracted. Try a clearer scan or a supported complete filing. '+details)
    progress(90,'Preserving the automatic snapshot and calculating review results')
    result=normalize(result,profile)
    (out/'automatic.json').write_text(encoded(result),encoding='utf-8')
    return result
