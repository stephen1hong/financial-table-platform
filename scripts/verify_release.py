"""Clone HEAD temporarily, overlay exactly the proposed files, verify fresh install.

No commit/index/ref mutation in the original repository. Keeps the temporary clone
for diagnosis. Network is used by pip only; tests/demo never download documents.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from export_release import ROOT, proposed_files


def main():
    work = Path(tempfile.mkdtemp(prefix='finance-release-'))
    checkout = work/'checkout'
    logs = ROOT/'release-artifacts';logs.mkdir(exist_ok=True)
    outcomes=[]
    env=os.environ.copy()
    for key in ('PYTHONPATH','PYTHONHOME','SEC_USER_AGENT'):env.pop(key,None)
    def run(name, command, cwd=checkout):
        result=subprocess.run(command,cwd=cwd,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (logs/(name+'.log')).write_text(result.stdout,encoding='utf-8')
        outcomes.append({'check':name,'exit_code':result.returncode})
        print(name, result.returncode, flush=True)
        if result.returncode:raise RuntimeError(f'{name} failed; see release-artifacts/{name}.log')
    try:
        run('clone',['git','clone','--local','--no-hardlinks',str(ROOT),str(checkout)],work)
        # Remove only the cloned tracked files before copying the proposed snapshot.
        names=subprocess.check_output(['git','ls-files','-z'],cwd=checkout).decode().split('\0')
        for name in filter(None,names):
            path=(checkout/name).resolve()
            if not path.is_relative_to(checkout.resolve()):raise ValueError(name)
            path.unlink()
        for name in proposed_files():
            dst=checkout/name;dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,dst)
        assert not (checkout/'data/raw').exists()
        assert not (checkout/'data/processed').exists()
        run('venv',[sys.executable,'-m','venv',str(work/'venv')])
        python=str(work/('venv/Scripts/python.exe' if os.name=='nt' else 'venv/bin/python'))
        run('dependencies',[python,'-m','pip','install','-r','requirements/build.lock','-r','requirements/release.lock'])
        run('build',[python,'-m','build','--no-isolation'])
        wheel=next((checkout/'dist').glob('*.whl'))
        run('wheel-install',[python,'-m','pip','install','--no-deps',str(wheel)])
        run('wheel-resources',[python,'-c',"from importlib.resources import files; import sec_downloader.review_app; assert files('sec_downloader').joinpath('templates/review.html').is_file(); assert files('sec_downloader').joinpath('static/review.js').is_file()"])
        run('editable-install',[python,'-m','pip','install','--no-deps','--no-build-isolation','-e','.'])
        run('pip-check',[python,'-m','pip','check'])
        run('offline-tests',[python,'-m','pytest','-q','-o','pythonpath=','-p','no:cacheprovider'])
        run('demo',[python,'scripts/offline_demo.py'])
        run('freeze',[python,'scripts/check_freeze.py'])
        run('cli',[python,'-m','sec_downloader.metrics','--help'])
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with (logs/'startup.log').open('w') as log:
            server=subprocess.Popen([python,'-m','sec_downloader.review_app','--port',str(port),
                '--data-dir','data/processed/demo'],cwd=checkout,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                for attempt in range(80):
                    if server.poll() is not None:raise RuntimeError('UI exited before startup')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=1) as response:
                            assert response.status==200
                        break
                    except OSError:time.sleep(.25)
                else:raise RuntimeError('UI startup timed out')
                for route in ('/api/catalog','/api/documents','/static/review.js'):
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}{route}',timeout=5) as response:
                        assert response.status==200
                        if route=='/api/documents':assert len(json.load(response))==1
                outcomes.append({'check':'live-localhost-startup','exit_code':0})
            finally:
                server.terminate();server.wait(timeout=15)
    finally:
        (logs/'verification.json').write_text(json.dumps({'temporary_checkout':str(checkout),
            'checks':outcomes,'python':sys.version},indent=2)+'\n')
        print(f'Temporary checkout retained at {checkout}',flush=True)


if __name__=='__main__':main()
