"""Heuristic working-tree and reachable/reflog Git blob audit; never prints secrets."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from export_release import ROOT, proposed_files

RULES = {
    'private_key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'credential_token': rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9_-]{20,})',
    'credential_assignment': rb'(?i)(?:password|api[_-]?key|secret|access[_-]?token)\s*[=:]\s*[\"\'][^\"\'\s]{8,}[\"\']',
    'personal_path': rb'(?i)[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\s\"\']+',
    'email': rb'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
}
SUSPICIOUS = re.compile(r'(?i)(?:^|/)(?:data/(?:raw|processed)|\.venv|\.vscode|\.idea|.*\.egg-info)(?:/|$)|\.(?:sqlite3?|db|onnx|pt|pth|safetensors|pem|key|pdf|zip|whl)$|(?:^|/)\.env(?:\.|$)')


def scan(data):
    return {name:len(re.findall(pattern, data)) for name,pattern in RULES.items()
            if re.search(pattern, data)}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    tracked = git('ls-files','-z').decode().split('\0')
    proposed = proposed_files()
    working = []
    for name in sorted(set(tracked + proposed) - {''}):
        path = ROOT/name
        if path.is_file():
            hits=scan(path.read_bytes())
            if hits or SUSPICIOUS.search(name):
                working.append({'path':name,'rules':hits,'suspicious_path':bool(SUSPICIOUS.search(name))})
    history=[];count=0
    for line in git('rev-list','--objects','--all','--reflog').decode().splitlines():
        oid, _, name=line.partition(' ')
        if git('cat-file','-t',oid).strip()!=b'blob':continue
        count+=1;data=git('cat-file','blob',oid);hits=scan(data)
        if hits or SUSPICIOUS.search(name) or len(data)>2_000_000:
            history.append({'object':oid,'path':name,'bytes':len(data),'rules':hits,
                            'suspicious_path':bool(SUSPICIOUS.search(name))})
    output=ROOT/'release-artifacts/audit.json';output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({'scope':'tracked working files + proposed files; all refs and reflog-reachable blobs',
        'history_blob_count':count,'history':history,'working':working,
        'proposed_count':len(proposed),'limitations':'Heuristic patterns, not proof of absence. Commit identity metadata remains in Git.'},indent=2)+'\n')
    print(f'Audited {count} history blobs and {len(proposed)} proposed files. Findings: {output}')


if __name__=='__main__':main()
