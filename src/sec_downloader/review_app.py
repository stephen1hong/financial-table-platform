"""Localhost financial-table review app. Run with python -m sec_downloader.review_app."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import json
from pathlib import Path
import secrets
import shutil
import uuid

from flask import Flask, jsonify, request, render_template, send_from_directory, Response

from .downloader import RAW_DIR, compute_sha256
from .filing_profiles import PROFILES
from .review_pipeline import catalog, process
from .review_store import ReviewStore, compatible_comparison, encoded, now


def create_app(root='data/processed/review_app'):
    app=Flask(__name__);app.config['MAX_CONTENT_LENGTH']=50*1024*1024
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    store=ReviewStore(root/'reviews.sqlite3');pool=ThreadPoolExecutor(max_workers=2)
    token=secrets.token_urlsafe(32)
    app.extensions.update(review_store=store,review_pool=pool,review_root=root,review_token=token)
    with store.connect() as db:
        db.execute("UPDATE jobs SET status='interrupted',message='Processing was interrupted by a restart. Import the document again.' WHERE status IN ('queued','running')")

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('127.0.0.1','localhost'):
            return jsonify(error='Localhost access only.'),403
        if request.method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(request.headers.get('X-Local-Token',''),token):
            return jsonify(error='Session expired or request came from another origin. Reload the local app.'),403

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        return response

    @app.errorhandler(ValueError)
    def invalid(exc):return jsonify(error=str(exc)),400

    @app.errorhandler(KeyError)
    def absent(exc):return jsonify(error='Document or job not found.'),404

    @app.errorhandler(413)
    def too_large(exc):return jsonify(error='File exceeds the 50 MB upload limit.'),413

    @app.get('/')
    def index():return render_template('review.html',token=token)

    @app.get('/api/catalog')
    def sources():
        return jsonify(documents=catalog(),profiles=[{'id':k} for k in PROFILES])

    @app.get('/api/documents')
    def documents():return jsonify(store.list_documents())

    @app.get('/api/documents/<identifier>')
    def document(identifier):return Response(encoded(store.get(identifier)),mimetype='application/json')

    def job_update(identifier,status,progress,message,document_id=None):
        with store.connect() as db:
            db.execute('UPDATE jobs SET status=?,progress=?,message=?,document_id=? WHERE id=?',
                       (status,progress,message,document_id,identifier))

    def run(identifier,path,profile,name):
        try:
            result=process(path,profile,root/identifier,lambda n,s:job_update(identifier,'running',n,s))
            store.add_document(name,{'profile':profile,'format':result['format'],'source_sha256':compute_sha256(path),
                                   'asset_directory':identifier,'input_filename':path.name},result,identifier)
            job_update(identifier,'complete',100,'Ready for review',identifier)
        except Exception as exc:
            job_update(identifier,'failed',100,f'{type(exc).__name__}: {exc}. Original input was preserved; no partial review document was saved.')

    @app.post('/api/import')
    def import_document():
        identifier=uuid.uuid4().hex;directory=root/identifier;directory.mkdir()
        if request.is_json:
            body=request.get_json();source=next((d for d in catalog() if d['id']==body.get('document_id')),None)
            if not source:raise ValueError('Choose an existing supported document.')
            src=Path(source['path']) if 'path' in source else RAW_DIR/source['filename']
            if not src.exists():raise ValueError('Cached file is missing. Run python -m sec_downloader first.')
            if source.get('sha256') and compute_sha256(src)!=source['sha256']:raise ValueError('Cache checksum mismatch. Re-download before importing.')
            path=directory/('input'+src.suffix.lower());shutil.copyfile(src,path)
            name,profile=source['filename'],source['profile']
        else:
            upload=request.files.get('file');profile=request.form.get('profile')
            if not upload or profile not in PROFILES:raise ValueError('Select a file and a supported company/fiscal profile.')
            name=Path(upload.filename or '').name;suffix=Path(name).suffix.lower()
            if suffix not in ('.htm','.html','.pdf'):raise ValueError('Accepted uploads are .htm, .html and .pdf.')
            path=directory/('input'+suffix);upload.save(path)
            if not path.stat().st_size:raise ValueError('The uploaded file is empty.')
        with store.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)',(identifier,'queued',0,'Queued for processing',None,now()))
        pool.submit(run,identifier,path,profile,name)
        return jsonify(job_id=identifier),202

    @app.get('/api/jobs/<identifier>')
    def job(identifier):
        with store.connect() as db:r=db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone()
        if not r:raise KeyError(identifier)
        return jsonify(dict(r))

    @app.post('/api/documents/<identifier>/corrections')
    def correction(identifier):
        b=request.get_json()
        required=('fact_id','field','new_value','reason','revision')
        if not isinstance(b,dict) or any(k not in b for k in required):raise ValueError('Incomplete correction request.')
        result=store.correct(identifier,b['fact_id'],b['field'],b['new_value'],b['reason'],b['revision'])
        return Response(encoded(result),mimetype='application/json')

    @app.post('/api/compare')
    def compare():
        b=request.get_json();facts=[]
        view=b.get('view','reviewed')
        if view not in ('automatic','reviewed'):raise ValueError('Choose automatic or reviewed comparison.')
        for side in ('left','right'):
            spec=b.get(side,{})
            doc=store.get(spec.get('document_id',''))
            candidates=doc['automatic']['facts'] if view=='automatic' else doc['reviewed_facts']
            found=next((f for f in candidates if f['fact_id']==spec.get('fact_id')),None)
            if not found:raise ValueError('Select two existing facts.')
            facts.append(found)
        return jsonify(compatible_comparison(*facts))

    @app.get('/assets/<identifier>/<path:filename>')
    def asset(identifier,filename):
        doc=store.get(identifier)
        allowed={t.get('image') for t in doc['automatic']['tables'] if t.get('image')}
        if filename not in allowed:raise KeyError(filename)
        return send_from_directory(root/identifier,filename)

    @app.get('/api/documents/<identifier>/export')
    def export(identifier):
        doc=store.get(identifier);view=request.args.get('view','reviewed')
        if view not in ('automatic','reviewed'):raise ValueError('Choose automatic or reviewed export.')
        facts=doc['automatic']['facts'] if view=='automatic' else doc['reviewed_facts']
        calcs=doc['automatic']['calculations'] if view=='automatic' else doc['reviewed_calculations']
        fact_index={f['fact_id']:f for f in doc['reviewed_facts']}
        exceptions=doc['automatic']['exceptions']
        if view=='reviewed':
            exceptions=[{**e,'review_status':fact_index.get(e.get('fact_id') or e.get('table',{}).get('fact_id'),{}).get('review_status','source_exception'),
                         'original_validation_preserved':True} for e in exceptions]
        datasets={'facts':facts,'calculations':calcs,'exceptions':exceptions,'history':doc['history']}
        format_=request.args.get('format','json')
        if format_=='json':
            payload={'document_id':identifier,'view':view,'metadata':doc['metadata'],**datasets}
            return Response(encoded(payload),mimetype='application/json',headers={'Content-Disposition':f'attachment; filename="{view}-review.json"'})
        if format_!='csv' or request.args.get('dataset') not in datasets:raise ValueError('CSV dataset must be facts, calculations, exceptions or history.')
        rows=datasets[request.args['dataset']];buffer=io.StringIO(newline='')
        keys=sorted({k for row in rows for k in row}) or ['status']
        writer=csv.DictWriter(buffer,fieldnames=keys);writer.writeheader()
        for row in rows:
            values={k:encoded(v) if isinstance(v,(list,dict)) else v for k,v in row.items()}
            for k,v in values.items():
                if isinstance(v,str) and v.startswith(('=','+','@')):values[k]="'"+v
            writer.writerow(values)
        return Response(buffer.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="{view}-{request.args["dataset"]}.csv"'})
    return app


def main():
    from waitress import serve
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--data-dir',default='data/processed/review_app')
    args=p.parse_args()
    print(f'Financial review: http://127.0.0.1:{args.port} (localhost only)',flush=True)
    serve(create_app(args.data_dir),host='127.0.0.1',port=args.port,threads=4)


if __name__=='__main__':main()
