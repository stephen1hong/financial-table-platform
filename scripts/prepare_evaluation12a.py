"""Declare the evaluation sample before any extraction; download separately."""
import json
from pathlib import Path

SOURCES = [
 ('msft','Microsoft','development','2023-07-01','2024-06-30',
  'https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm',
  'https://www.sec.gov/Archives/edgar/data/789019/000119312524242888/d815777dars.pdf'),
 ('goog','Alphabet','development','2024-01-01','2024-12-31',
  'https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm',
  'https://abc.xyz/assets/99/21/46cafdba41089a12a2d86ea47d44/goog026-annualreport2024-web.pdf'),
 ('meta','Meta Platforms','held_out','2024-01-01','2024-12-31',
  'https://www.sec.gov/Archives/edgar/data/1326801/000132680125000017/meta-20241231.htm',
  'https://s21.q4cdn.com/399680738/files/doc_financials/2024/ar/Meta-12-31-2024-10K-ARS.pdf'),
 ('jnj','Johnson & Johnson','held_out','2024-01-01','2024-12-29',
  'https://www.sec.gov/Archives/edgar/data/200406/000020040625000038/jnj-20241229.htm',
  'https://www.jnj.com/download/johnson-johnson-2024-annual-report'),
 ('cost','Costco','held_out','2023-09-04','2024-09-01',
  'https://www.sec.gov/Archives/edgar/data/909832/000090983224000049/cost-20240901.htm',
  'https://s201.q4cdn.com/287523651/files/doc_financials/2024/ar/COST-2024-Annual-Report.pdf'),
]

def main():
    path=Path('evaluation/manifest.json')
    if path.exists():
        raise SystemExit('Sample already declared; do not overwrite the frozen selection.')
    documents=[]
    for ticker,company,split,start,end,html,pdf in SOURCES:
        for fmt,url in [('html',html),('pdf',pdf)]:
            documents.append(dict(id=f'{ticker}-2024-{fmt}', company=company,
                filing_group=f'{ticker}-2024', split=split, format=fmt,
                form='10-K' if fmt=='html' else 'Annual report including 10-K',
                fiscal_year=2024, start_date=start,end_date=end,
                source_url=url,filename=f'{ticker}-2024.{"htm" if fmt=="html" else "pdf"}',sha256=None,
                target_table_types=['statement','segment_note','financial_footnote']))
    manifest=dict(schema_version=1,declared_at='2026-10-01',
        selection='Purposive cross-issuer annual sample, fixed before extraction. Five new filing groups / ten additional documents (paired official HTML/PDF), not ten independent filings. Microsoft and Alphabet development; entire Meta, healthcare Johnson & Johnson, and Costco groups held out. No substitutions based on extraction outcomes.',
        annotation_plan='At least 100 distinct numeric facts across five filings, checked separately in each representation; include consolidated statements, segment notes and a financial footnote. Tables selected from audited notes, not MD&A repeats. Whole-document financial selection scored separately from class-agnostic table inventory and oracle-located cell diagnostics.',
        scan_coverage='No genuine scans selected: no suitable official image-only financial report verified in source search. Simulated scans are excluded from this evaluation and retain their separate milestone 10 scores.',
        documents=documents)
    path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
