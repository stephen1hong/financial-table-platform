"""Download the declared sample, retaining failures; no outcome-based substitution."""
import json
from pathlib import Path
from sec_downloader.downloader import download_document, should_download_document
from sec_downloader.manifest import load_manifest, save_manifest

def main():
    path=Path('evaluation/manifest.json')
    manifest=load_manifest(path)
    # Same Alphabet FY2024 annual report, official SEC mirror after company HTTP 403.
    for d in manifest['documents']:
        if d['id']=='goog-2024-pdf' and 'abc.xyz' in d['source_url']:
            d['source_attempts']=[{'url':d['source_url'],'result':'HTTP 403 before extraction'}]
            d['source_url']='https://www.sec.gov/Archives/edgar/data/1652044/000130817925000513/goog012714-ars.pdf'
    save_manifest(manifest,path)
    errors=[]
    for d in manifest['documents']:
        try:
            if should_download_document(d,'data/raw/evaluation12a'):
                download_document(d,'data/raw/evaluation12a',path)
        except Exception as exc:
            errors.append({'document':d['id'],'error':str(exc)})
            print(d['id'],str(exc))
    out=Path('data/processed/evaluation12a');out.mkdir(parents=True,exist_ok=True)
    (out/'download-errors.json').write_text(json.dumps(errors,indent=2),encoding='utf-8')
    return bool(errors)

if __name__=='__main__':raise SystemExit(main())
