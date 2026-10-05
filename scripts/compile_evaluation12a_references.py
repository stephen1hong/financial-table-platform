"""Attach original-source locations to manually authored reference rows.

This annotation utility deliberately imports no extraction code. It never creates
expected values from source parsing: every expected number is a literal in the
reviewed reference_rows.json. The source assertion detects transcription errors.
"""
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
from bs4 import BeautifulSoup

def norm(s):return ' '.join(s.split())

def period(ticker,year):
    if ticker=='msft':start,end=f'{year-1}-07-01',f'{year}-06-30'
    elif ticker=='jnj':start,end={2024:('2024-01-01','2024-12-29'),2023:('2023-01-02','2023-12-31'),2022:('2022-01-03','2023-01-01')}[year]
    elif ticker=='cost':start,end={2024:('2023-09-04','2024-09-01'),2023:('2022-08-29','2023-09-03'),2022:('2021-08-30','2022-08-28')}[year]
    else:start,end=f'{year}-01-01',f'{year}-12-31'
    days=(date.fromisoformat(end)-date.fromisoformat(start)).days+1
    return dict(start_date=start,end_date=end,duration=f'P{days}D',duration_days=days,fiscal_year=year,period_type='annual')

def main():
    root=Path('evaluation'); source=json.loads((root/'reference_rows.json').read_text(encoding='utf-8'))
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    docs={d['id']:d for d in manifest['documents']};facts=[];tables=[]
    for ticker,company in source['companies'].items():
        soup=BeautifulSoup(Path(f'data/raw/evaluation12a/{ticker}-2024.htm').read_text(encoding='utf-8'),'html.parser')
        for scope,table in company['tables'].items():
            original=soup.find_all('table')[table['html_table']-1]
            rows=original.find_all('tr')
            for fmt in ['html','pdf']:
                doc=docs[f'{ticker}-2024-{fmt}']
                tables.append(dict(id=f'{doc["id"]}:{scope}',document_id=doc['id'],scope=scope,
                    heading=table['heading'],html_table=table['html_table'] if fmt=='html' else None,
                    page=table['pdf_page'] if fmt=='pdf' else None,printed_page=table['printed_page'] if fmt=='pdf' else None))
            for n,(label,occurrence,metric,segment,values) in enumerate(table['rows']):
                found=[(i,r) for i,r in enumerate(rows) if any(norm(c.get_text(' ',strip=True))==label for c in r.find_all(['td','th'],recursive=False))]
                for j,(year,value) in enumerate(zip(company['years'],values)):
                    ri,row=found[j if table.get('years_in_rows') else occurrence]
                    candidates=[];column=0
                    for ci,cell in enumerate(row.find_all(['td','th'],recursive=False)):
                        txt=norm(cell.get_text(' ',strip=True))
                        if re.fullmatch(r'[\s$(),.\d%\-]+',txt or 'x') and re.search(r'\d',txt):
                            number=re.sub(r'[\s$(),%]','',txt)
                            if '(' in txt:number='-'+number
                            if Decimal(number)==Decimal(value):candidates.append((ci,column,txt))
                        column+=int(cell.get('colspan',1))
                    # Equal rates in different columns are resolved by independently read year order.
                    chosen=candidates[j] if len(candidates)==len(values) and len(set(values))==1 else candidates[0]
                    assert len(candidates)==1 or len(set(values))==1,(ticker,label,value,candidates)
                    ci,col,original_text=chosen
                    unique=f'{ticker}:{scope}:{n}:{year}'
                    for fmt in ['html','pdf']:
                        doc=docs[f'{ticker}-2024-{fmt}']
                        location=(f'{doc["filename"]}#table[{table["html_table"]}]/row[{ri}]/column[{col}]' if fmt=='html' else
                                  f'{doc["filename"]}#page={table["pdf_page"]}; {table["heading"]}; {segment}; {label}; FY{year}')
                        facts.append(dict(id=f'{unique}:{fmt}',unique_fact_id=unique,document_id=doc['id'],
                            company=doc['company'],split=doc['split'],format=fmt,scope=scope,
                            metric=metric,segment=segment,hierarchical_label=[table['heading'],segment,label],
                            value=value,unit=table.get('unit','USD (millions)'),period=period(ticker,year),
                            row=ri if fmt=='html' else None,column=col if fmt=='html' else None,
                            table_index=table['html_table'] if fmt=='html' else None,
                            page=table['pdf_page'] if fmt=='pdf' else None,
                            printed_page=table['printed_page'] if fmt=='pdf' else None,
                            source_label=label,label_occurrence=occurrence,source_reference=location,
                            source_url=doc['source_url'],source_sha256=doc['sha256'],
                            verification='HTML DOM visible cell assertion and visual PDF comparison; manually authored value',
                            html_cell_text=original_text))
    result=dict(method=source['method'],period_method='Fiscal dates checked against original headers/accounting-period disclosure and original SEC duration contexts. Exact day durations retain 52/53-week years.',tables=tables,facts=facts)
    (root/'references.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f'{len(facts)} representation annotations; {len(set(f["unique_fact_id"] for f in facts))} distinct facts; {len(tables)} tables')

if __name__=='__main__':main()
