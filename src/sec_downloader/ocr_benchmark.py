"""Evaluate simulated scans using frozen, independently checked spatial references."""
import argparse
from decimal import Decimal
import json
from pathlib import Path

from .downloader import verify_cached_file
from .ocr_adapter import extract_file, rotate_point, ENGINE_SETTINGS
from .periods import period_identity


def evaluate(expected, facts, rotation, page_size):
    correct = dict.fromkeys(('numeric','period','unit','segment','metric','joint'), 0)
    cases, present = [], 0
    for gold in expected:
        point = rotate_point(gold['source_point'], [page_size[0]/2,page_size[1]/2], rotation)
        matches = [f for f in facts if f.get('bbox') and
                   f['bbox'][0]-2 <= point[0] <= f['bbox'][2]+2 and f['bbox'][1]-2 <= point[1] <= f['bbox'][3]+2]
        case = {'expected': gold, 'source_point_on_scan': point}
        if len(matches) != 1:
            case.update(status='MISSING' if not matches else 'AMBIGUOUS', candidates=matches)
        elif matches[0].get('value') is None or matches[0]['status'] != 'ok':
            case.update(status='UNRESOLVED', actual=matches[0])
        else:
            f = matches[0]; present += 1
            checks = {'numeric': Decimal(str(f['value'])) == Decimal(gold['value']),
                      'period': period_identity(f.get('period') or {}) == period_identity(gold['period']),
                      'unit': f['unit'] == gold['unit'], 'segment': f['segment'] == gold['segment'],
                      'metric': f['metric'] == gold['metric']}
            checks['joint'] = all(checks.values())
            for k,v in checks.items():correct[k] += int(v)
            case.update(status='MATCH' if checks['joint'] else 'MISMATCH', checks=checks, actual=f)
        cases.append(case)
    return {'expected':len(expected), 'present':present, 'coverage':present/len(expected),
            'accuracy_on_present':{k:v/present if present else None for k,v in correct.items()},
            'correct':correct,'end_to_end_accuracy':correct['joint']/len(expected), 'cases':cases}


def main():
    from rapidocr_onnxruntime import RapidOCR
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan-manifest',default='data/processed/ocr/scans/manifest.json')
    parser.add_argument('--expected',default='tests/fixtures/ocr_benchmark_facts.json')
    parser.add_argument('--output-dir',default='data/processed/ocr/benchmark')
    args=parser.parse_args();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(Path(args.scan_manifest).read_text());fixture=json.loads(Path(args.expected).read_text())
    engine=RapidOCR(**ENGINE_SETTINGS);results=[]
    for scan in manifest['scans']:
        if not verify_cached_file(scan['pdf'],scan['pdf_sha256']):raise ValueError('Scan checksum failed')
        sub=out/f"{scan['id']}-{scan['original_page']}"
        report=extract_file(scan['pdf'],sub,engine)
        gold=[f for f in fixture['facts'] if f['page']==scan['original_page']]
        score=evaluate(gold,report['facts'],scan['rotation_degrees'],(scan['page_width'],scan['page_height']))
        results.append({'scan':scan,'score':score,'review':(sub/'review.md').as_posix(),
                        'exception_count':len(report['exceptions']),'facts':len(report['facts'])})
        print(scan['id'],scan['original_page'],score['present'],'/',score['expected'],score['accuracy_on_present'],flush=True)
    combined={}
    for variant in sorted({r['scan']['id'] for r in results}):
        scores=[r['score'] for r in results if r['scan']['id']==variant]
        present=sum(s['present'] for s in scores);total=sum(s['expected'] for s in scores)
        correct={k:sum(s['correct'][k] for s in scores) for k in scores[0]['correct']}
        combined[variant]={'present':present,'expected':total,'coverage':present/total,
                           'accuracy_on_present':{k:v/present if present else None for k,v in correct.items()},
                           'end_to_end_accuracy':correct['joint']/total}
    (out/'evaluation.json').write_text(json.dumps({'method':fixture['method'],'variants':combined,'results':results},indent=2,default=str),encoding='utf-8')
    lines=['# Simulated scan OCR benchmark','',fixture['method'],
           'These are simulated scans, not real scanner captures. Missing and unresolved facts reduce coverage; accepted accuracy excludes them. No benchmark values are used in extraction.',
           '', '| Variant | Present | Coverage | Numeric | Period | Unit | Segment | End-to-end |','| --- | --- | --- | --- | --- | --- | --- | --- |']
    for variant,s in combined.items():
        a=s['accuracy_on_present'];fmt=lambda v:'n/a' if v is None else f'{100*v:.2f}%'
        lines.append(f"| {variant} | {s['present']}/{s['expected']} | {fmt(s['coverage'])} | {fmt(a['numeric'])} | {fmt(a['period'])} | {fmt(a['unit'])} | {fmt(a['segment'])} | {fmt(s['end_to_end_accuracy'])} |")
    for r in results:
        relative=Path(r['review']).relative_to(out).as_posix()
        lines += ['',f"## {r['scan']['id']} / source page {r['scan']['original_page']}",f'[Table image, cells and review]({relative})','']
        for case in r['score']['cases']:
            if case['status']!='MATCH':
                f=case.get('actual',{});g=case['expected']
                lines.append(f"- {case['status']}: {g['segment']} {g['metric']} FY{g['period']['fiscal_year']}; expected={g['value']}; OCR={f.get('ocr_original_text','missing')!r}; parsed={f.get('ocr_parsed_value')}; reasons={f.get('review_reasons',[])}; location={case['source_point_on_scan']}")
    (out/'review.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(combined,indent=2))


if __name__=='__main__':main()
