"""Immutable extraction snapshots and append-only local correction history."""
from copy import deepcopy
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
import uuid

from .metrics import calculate_metric, METRIC_FORMULAS
from .periods import period_identity
from .filing_profiles import PROFILES
from .accounting import GROSS_PROFIT_NOTES, qname


def encoded(value):
    return json.dumps(value, default=str, ensure_ascii=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def recalculate(facts):
    groups = {}
    for f in facts:
        key = (f.get('company'), f.get('table_id'), f.get('segment'), period_identity(f.get('period') or {}))
        groups.setdefault(key, []).append(f)
    result = []
    for (company, table, segment, _), members in groups.items():
        inputs = {}
        duplicates = set()
        for f in members:
            metric = f.get('metric')
            if metric in inputs: duplicates.add(metric)
            inputs[metric] = f
        for metric in duplicates: inputs.pop(metric, None)
        for metric in METRIC_FORMULAS:
            calc = calculate_metric(metric, inputs)
            calc.update(company=company, table_id=table, segment=segment, kind='calculated',
                        period=members[0].get('period'), duplicates=sorted(m for m in duplicates if m),
                        inputs=[f for f in members if f['fact_id'] in calc['input_fact_ids']],
                        accounting_note=GROSS_PROFIT_NOTES.get(company,'Calculated from reported net sales and cost of sales; not a reported subtotal. Cost of sales is not deducted a second time from total operating expenses.'))
            result.append(calc)
    return result


def compatible_comparison(a, b):
    if a.get('status','ok') != 'ok' or b.get('status','ok') != 'ok' or a.get('value') is None or b.get('value') is None:
        raise ValueError('Both facts must have resolved, reviewed or automatic values.')
    if None in period_identity(a.get('period') or {}) or period_identity(a.get('period') or {}) != period_identity(b.get('period') or {}):
        raise ValueError('Comparison blocked: fiscal dates, duration or period type differ.')
    for field in ('unit','metric','accounting_definition'):
        if not a.get(field) or a[field] != b.get(field):
            raise ValueError(f'Comparison blocked: {field} differs or is unresolved.')
    if a.get('segment') != b.get('segment'):
        raise ValueError('Comparison blocked: segment/consolidation contexts differ.')
    return {'left':a['fact_id'], 'right':b['fact_id'],
            'difference':str(Decimal(str(a['value']))-Decimal(str(b['value']))),
            'unit':a['unit'], 'source_references':[a['source_reference'],b['source_reference']]}


def validated_period(value):
    if not isinstance(value,dict): raise ValueError('Period must be a JSON object with complete dates and duration.')
    try:
        start, end = date.fromisoformat(value['start_date']), date.fromisoformat(value['end_date'])
        days = (end-start).days+1
        limits = {'P12M':('annual',300,380), 'P3M':('quarter',70,110), 'P9M':('year_to_date',240,300)}
        kind, low, high = limits[value['duration']]
        if value['period_type'] != kind or not low<=days<=high or not isinstance(value['fiscal_year'],int): raise ValueError()
        if not 1900<=value['fiscal_year']<=2200: raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise ValueError('Period needs valid start_date/end_date, fiscal_year, and compatible P12M/annual, P3M/quarter or P9M/year_to_date metadata.')
    return {**value, 'duration_days':days, 'id':f'{start}/{end}/{kind}'}


def view_facts(automatic, history):
    facts = deepcopy(automatic['facts']); index = {f['fact_id']:f for f in facts}
    for f in facts:
        f['review_status'] = 'automatic'
        f['reviewed_fields'] = []
        f['extraction_kind'] = f.get('kind','reported')
    for edit in history:
        f = index[edit['fact_id']]
        if edit['field'] == 'mapping':
            f.update(edit['new_value'])
        else:
            f[edit['field']] = edit['new_value']
        f['reviewed_fields'] = sorted(set(f['reviewed_fields']+[edit['field']]))
        missing = set(f.get('required_review_fields', [])) - set(f['reviewed_fields'])
        complete = not missing and f.get('value') is not None and f.get('metric') and f.get('unit') and f.get('period') and f.get('segment')
        f['review_status'] = 'approved' if complete else 'needs_review'
        f['status'] = 'ok' if complete else 'REVIEW_REQUIRED'
        if complete:f['kind']='reported'
        f['remaining_review_fields'] = sorted(missing)
    return facts


class ReviewStore:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, name TEXT NOT NULL,
                created TEXT NOT NULL, metadata TEXT NOT NULL, automatic TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS corrections (id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL REFERENCES documents(id), fact_id TEXT NOT NULL,
                field TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
                reason TEXT NOT NULL, timestamp TEXT NOT NULL, review_status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, progress INTEGER NOT NULL,
                message TEXT NOT NULL, document_id TEXT, created TEXT NOT NULL);
            ''')

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30);db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def add_document(self, name, metadata, automatic, document_id=None):
        identifier=document_id or uuid.uuid4().hex
        ids=[f['fact_id'] for f in automatic['facts']]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate fact IDs: extraction requires review before import.')
        with self.connect() as db:
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,0)',(identifier,name,now(),encoded(metadata),encoded(automatic)))
        return identifier

    def list_documents(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,name,created,revision FROM documents ORDER BY created DESC')]

    def _load(self, db, identifier):
        row=db.execute('SELECT * FROM documents WHERE id=?',(identifier,)).fetchone()
        if row is None:raise KeyError(identifier)
        result=dict(row);result['metadata']=json.loads(row['metadata']);result['automatic']=json.loads(row['automatic'])
        history=[]
        source_facts={f['fact_id']:f for f in result['automatic']['facts']}
        for r in db.execute('SELECT * FROM corrections WHERE document_id=? ORDER BY id',(identifier,)):
            item=dict(r)
            for k in ('old_value','new_value'):item[k]=json.loads(item[k])
            source=source_facts[item['fact_id']]
            item.update(source_reference=source.get('source_reference'),page=source.get('page'),bbox=source.get('bbox'))
            history.append(item)
        result['history']=history
        result['reviewed_facts']=view_facts(result['automatic'],history)
        result['reviewed_calculations']=recalculate(result['reviewed_facts'])
        return result

    def get(self, identifier):
        with self.connect() as db:return self._load(db,identifier)

    def correct(self, identifier, fact_id, field, value, reason, revision):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('A correction reason is required.')
        if field not in ('value','period','unit','mapping','segment'):raise ValueError('Unsupported correction field.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            doc=self._load(db,identifier)
            if revision!=doc['revision']:raise ValueError('This document changed in another tab. Reload before saving.')
            fact=next((f for f in doc['reviewed_facts'] if f['fact_id']==fact_id),None)
            if fact is None:raise ValueError('Fact not found.')
            old=fact.get(field)
            if field=='value':
                try:
                    numeric=Decimal(str(value))
                    if not numeric.is_finite():raise InvalidOperation()
                    value=str(numeric)
                except (InvalidOperation,ValueError):raise ValueError('Value must be a finite decimal number, without currency symbols or commas.')
            elif field=='period':value=validated_period(value)
            elif field=='unit':
                import re
                if not isinstance(value,str) or not re.fullmatch(r'(?:[A-Z]{3}(?: \((?:millions|thousands)\)|/share)?|percent|shares(?: \(millions\))?)',value):
                    raise ValueError('Use a currency and scale, e.g. USD (millions), USD, EUR (thousands), USD/share, or shares (millions).')
            elif field=='segment':
                if not isinstance(value,str) or not value.strip() or len(value)>100:raise ValueError('Segment must be a non-empty label under 100 characters.')
                value=value.strip()
            elif field=='mapping':
                from .segments import MAPPINGS
                mappings=dict(PROFILES[doc['metadata']['profile']][4])
                for label,(metric,concept) in MAPPINGS.items():mappings.setdefault(metric,(label,concept))
                if value not in mappings:raise ValueError('Select a supported canonical metric.')
                metric=value;concept=qname(mappings[metric][1])
                old={k:fact.get(k) for k in ('metric','concept','accounting_definition')}
                value={'metric':metric,'concept':concept,'accounting_definition':f"{fact['company']}:{metric}:{concept}"}
            db.execute('INSERT INTO corrections(document_id,fact_id,field,old_value,new_value,reason,timestamp,review_status) VALUES (?,?,?,?,?,?,?,?)',
                       (identifier,fact_id,field,encoded(old),encoded(value),reason.strip(),now(),'approved'))
            db.execute('UPDATE documents SET revision=revision+1 WHERE id=?',(identifier,))
        return self.get(identifier)
