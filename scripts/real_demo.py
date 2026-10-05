"""Opt-in single-filing demo; rejects source drift against the reviewed manifest."""
import argparse
import json
from pathlib import Path
import shutil

from sec_downloader.downloader import download_document, verify_cached_file
from sec_downloader.metrics import build_financial_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--output',type=Path,default=Path('data/processed/real-demo'))
    args=parser.parse_args()
    manifest=Path('demo/real-manifest.json')
    document=json.loads(manifest.read_text())['documents'][0]
    raw=args.output/'raw'; source=raw/document['filename']
    if not verify_cached_file(source,document['sha256']):
        if not args.download:raise SystemExit('Run with --download and SEC_USER_AGENT to acquire the reviewed source.')
        args.output.mkdir(parents=True,exist_ok=True)
        local=args.output/'download-manifest.json';shutil.copyfile(manifest,local)
        download_document(dict(document),raw,local)
        if not verify_cached_file(source,document['sha256']):
            raise SystemExit('Source checksum changed. Review source drift; expected manifest was not modified.')
    report=build_financial_report(manifest,raw)
    summary={key:str(report['documents'][0]['calculated_facts'][key]['value'])
             for key in ('gross_profit','gross_margin_percentage','operating_margin_percentage')}
    expected=json.loads(Path('demo/real-expected.json').read_text())
    if summary!=expected:raise SystemExit(f'Unexpected results: {summary}')
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
