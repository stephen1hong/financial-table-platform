"""Configuration-driven hierarchical segment reporting (Amazon initial profile)."""
import argparse
import json
from pathlib import Path
from copy import deepcopy

from bs4 import BeautifulSoup

from .accounting import AMAZON_SEGMENTS
from .downloader import MANIFEST_PATH, RAW_DIR, verify_cached_file
from .extractor import normalize_text
from .manifest import load_manifest
from .metrics import reported_periods, calculate_metric
from .segments import select_segment_tables, extract_segment_table, reconcile
from .validation import read_inline, compare
from .xbrl_context import dimensional_context


def build_report(manifest_path=MANIFEST_PATH, raw_dir=RAW_DIR, profile=AMAZON_SEGMENTS):
    document = next(d for d in load_manifest(manifest_path)["documents"] if d["id"] == profile["document_id"])
    path = Path(raw_dir) / document["filename"]
    if not verify_cached_file(path, document.get("sha256")):
        raise ValueError("Missing or checksum-invalid segment filing")
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    index, table, heading = select_segment_tables(soup, profile)[0]
    source = f"{path.as_posix()}#table[{index}]"
    evidence = []
    for node in heading.find_all_next(["div", "p", "table"]):
        if node is table:
            break
        if node.name != "table" and not node.find(["div", "p", "table"]) and not node.find_parent("table"):
            text = normalize_text(node.get_text(" ", strip=True))
            if text:
                evidence.append({"text": text, "source_reference": source + ":preceding-note"})
    extraction = extract_segment_table(table, document, source, normalize_text(heading.get_text(" ", strip=True)), [],
                                       profile, " ".join(e["text"] for e in evidence))
    facts = extraction["facts"]
    inline = read_inline(soup, path.as_posix())
    for f in inline:
        if f["context"]:
            f["raw_context"] = deepcopy(f["context"])
            f["context"] = dimensional_context(f["context"])
    validations = []
    for fact in facts:
        if fact["status"] != "ok":
            validations.append({"table": fact, "status": "NO_COMPARABLE_FACT", "reason": "Unresolved extracted fact"})
            continue
        member = profile["segments"][fact["segment"]]
        expected = {"entity": profile["entity"], "entity_scheme": "http://www.sec.gov/CIK",
                    "start": fact["period"]["start_date"], "end": fact["period"]["end_date"], "instant": None,
                    "dimensions": [("us-gaap:StatementBusinessSegmentsAxis", member)] if member else []}
        validations.append(compare(fact, inline, fact["concept"], expected))
    groups = reported_periods(document, raw_dir)
    reconciliations, calculations = [], []
    def get(segment, year, metric):
        matches = [f for f in facts if f["segment"] == segment and f["year_header"] == year and f["metric"] == metric]
        return matches[0] if len(matches) == 1 else {"fact_id": f"missing:{segment}:{year}:{metric}", "value": None, "period": None, "source_reference": source}
    for group in groups:
        year = str(group["period"]["fiscal_year"])
        for segment in profile["segments"]:
            inputs = {f["metric"]: f for f in facts if f["segment"] == segment and f["year_header"] == year}
            calc = calculate_metric("operating_margin_percentage", inputs)
            calc.update(segment=segment, year=year, inputs=[f for f in inputs.values() if f["fact_id"] in calc["input_fact_ids"]])
            calculations.append(calc)
            reconciliations.append(reconcile(f"{segment} {year} sales less total operating expenses",
                [get(segment, year, "net_sales"), get(segment, year, "total_operating_expenses")],
                get(segment, year, "operating_income"), [1, -1], evidence))
        for metric in profile["summed_metrics"]:
            reconciliations.append(reconcile(f"{year} sum of segments: {metric}",
                [get(s, year, metric) for s, member in profile["segments"].items() if member],
                get("Consolidated", year, metric), evidence=evidence))
        reconciliations.append(reconcile(f"{year} disclosed net-income bridge",
            [get("Consolidated", year, metric) for metric, sign in profile["bridge"]],
            get("Consolidated", year, profile["bridge_target"]), [sign for metric, sign in profile["bridge"]], evidence))
        for metric, target in group["reported_facts"].items():
            if any(f["segment"] == "Consolidated" and f["metric"] == metric for f in facts):
                reconciliations.append(reconcile(f"{year} note to statement: {metric}", [get("Consolidated", year, metric)], target, evidence=evidence))
        expenses = profile["expense_components"]
        reconciliations.append(reconcile(f"{year} expense categories to total (cost of sales counted once)",
            [group["reported_facts"][m] for m in expenses], group["reported_facts"]["total_operating_expenses"], evidence=evidence))
    exceptions = extraction["exceptions"] + [v for v in validations + reconciliations if v["status"] != "MATCH"]
    return {"document": document, "source_reference": source, **extraction, "disclosure_evidence": evidence,
            "calculation_policy": profile["calculation_policy"], "calculations": calculations,
            "reconciliations": reconciliations, "validations": validations, "exceptions": exceptions}


def write_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, obj in (("segments.json", report), ("exceptions.json", report["exceptions"])):
        (directory / name).write_text(json.dumps(obj, default=str, indent=2), encoding="utf-8")
    lines = ["# Segment results", report["source_reference"], "USD millions.", report["calculation_policy"]]
    lines += [e["text"] for e in report["disclosure_evidence"]]
    for segment in dict.fromkeys(f["segment"] for f in report["facts"]):
        lines += ["\n## " + segment, "", "| Metric | FY2023 | FY2024 | FY2025 |", "| --- | ---: | ---: | ---: |"]
        for metric in dict.fromkeys(f["metric"] for f in report["facts"] if f["segment"] == segment):
            fs = [next(f for f in report["facts"] if f["segment"] == segment and f["metric"] == metric and f["year_header"] == y) for y in ("2023", "2024", "2025")]
            lines.append("| " + fs[0]["label"] + " | " + " | ".join(str(f["value"]) for f in fs) + " |")
    lines += ["\n## Provenance", ""] + [f"- {f['fact_id']}: {f['source_reference']} row={f['row']} column={f['column']}" for f in report["facts"]]
    lines += ["\n## Calculations and reconciliations", ""]
    for r in report["calculations"] + report["reconciliations"]:
        lines.append(f"\n{r.get('name', str(r.get('segment')) + ' ' + str(r.get('year')))}: {r['status']}, value={r['value']}; {r['formula']}\n")
        lines += [f"- {f['fact_id']}: {f['value']}; {f['source_reference']}" for f in r["inputs"]]
        if "target" in r:
            lines.append(f"- Target: {r['target']['fact_id']}, {r['target']['value']}; {r['target']['source_reference']}; difference={r['difference']}")
    lines += ["\n## Exceptions", "", "Full evidence: exceptions.json"]
    lines += [f"- {r.get('table', {}).get('fact_id', r.get('name'))}: {r['status']}; {r.get('reason', '')}" for r in report["exceptions"]]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data/processed/amazon-segments")
    args = parser.parse_args()
    report = build_report()
    write_report(report, args.output_dir)
    print(f"Facts={len(report['facts'])}, reconciliations={len(report['reconciliations'])}, exceptions={len(report['exceptions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
