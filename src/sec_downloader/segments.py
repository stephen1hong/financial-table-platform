"""Walmart FY2025 segment-note extraction and disclosed reconciliation, offline."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from decimal import Decimal

from bs4 import BeautifulSoup

from .downloader import MANIFEST_PATH, RAW_DIR, verify_cached_file
from .extractor import expand_table_cells, normalize_text, extract_document_statement
from .manifest import load_manifest
from .metrics import calculate_metric, reported_periods, METRIC_FORMULAS
from .periods import resolve_period, period_identity
from .validation import read_inline, compare, number
from .xbrl_context import dimensional_context
from .accounting import qname

SEGMENTS = {
    "Walmart U.S.": "wmt:WalmartUSMember",
    "Walmart International": "wmt:WalmartInternationalMember",
    "Sam's Club U.S.": "wmt:SamsClubUSMember",
    "Corporate and support": None,
    "Consolidated": None,
}
OPERATING = list(SEGMENTS)[:3]
MAPPINGS = {
    "Net sales": ("net_sales", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "Membership and other income": ("membership_other_income", "OtherIncome"),
    "Total revenues": ("total_revenues", "Revenues"),
    "Cost of sales": ("cost_of_sales", "CostOfRevenue"),
    "Operating, selling, general and administrative expenses": ("operating_expenses", "SellingGeneralAndAdministrativeExpense"),
    "Operating income": ("operating_income", "OperatingIncomeLoss"),
    "Operating loss": ("operating_income", "OperatingIncomeLoss"),
    "Interest, net": ("interest_net", "InterestIncomeExpenseNonoperatingNet"),
    "Other (gains) and losses": ("other_gains_losses", "NonoperatingIncomeExpense"),
    "Income before income taxes": ("income_before_income_taxes", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
}


def clean_label(text):
    return re.sub(r"\s*\(\d+\)", "", text).strip()


def select_segment_tables(soup, profile=None):
    required = profile["required_content"] if profile else (*OPERATING, "Corporate and support", "Cost of sales", "Operating income")
    pattern = profile["heading_pattern"] if profile else r"^Note \d+\. .*Segments"
    selected = []
    for index, table in enumerate(soup.find_all("table"), 1):
        text = normalize_text(table.get_text(" ", strip=True))
        if not all(label in text for label in required):
            continue
        heading = next((p for p in table.find_all_previous(["div", "p"])
                        if not p.find("table") and re.match(r"^Note\s+\d+", normalize_text(p.get_text(" ", strip=True)))), None)
        if heading is None or not re.search(pattern, normalize_text(heading.get_text(" ", strip=True)), re.I):
            continue
        selected.append((index, table, heading))
    if len(selected) != 1:
        raise ValueError(f"Expected one hierarchical segment operating-results table in the segment note; found {len(selected)}")
    return selected


def extract_segment_table(table, document, source, heading, footnotes, profile=None, unit_evidence="", supplied_cells=None):
    segments = profile["segments"] if profile else SEGMENTS
    mappings = profile["mappings"] if profile else MAPPINGS
    cells = supplied_cells if supplied_cells is not None else expand_table_cells(table, source)
    facts, exceptions = [], []
    segment = None
    segment_label = None
    years = sorted({c["text"] for c in cells if re.fullmatch(r"20\d{2}", c["text"])}, reverse=True)
    if not years or ((profile["unit_evidence"] if profile else "(Amounts in millions)") not in (table.get_text(" ", strip=True) + unit_evidence)):
        raise ValueError("Unsupported segment year headers or monetary units")
    expected_years = [str(document["fiscal_year"] - offset) for offset in range(3)]
    year_headers = [c for c in cells if re.fullmatch(r"20\d{2}", c["text"])]
    if years != expected_years or len(year_headers) != 3:
        exceptions.append({"status": "AMBIGUOUS_HEADER", "source_reference": source,
                           "reason": "Expected three unique annual headers for this filing; missing or duplicate header",
                           "header_cells": year_headers})
        years = sorted(set(years + expected_years), reverse=True)
    for row in sorted({c["row"] for c in cells}):
        row_cells = [c for c in cells if c["row"] == row]
        label_cell = min(row_cells, key=lambda c: c["column"])
        label = label_cell["text"]
        cleaned = clean_label(label)
        if cleaned in segments:
            segment, segment_label = cleaned, label
            continue
        if segment is None or not cleaned:
            continue
        if cleaned not in mappings:
            exceptions.append({"status": "UNMAPPED_ROW", "label": label, "segment": segment, "source_reference": source, "row": row})
            continue
        metric, concept = mappings[cleaned]
        for year in years:
            candidates = [c for c in row_cells if c["period_label"] == year and c["text"] not in ("", "$")]
            status = "ok" if len(candidates) == 1 else "AMBIGUOUS" if candidates else "MISSING_VALUE"
            cell = candidates[0] if len(candidates) == 1 else None
            value, period = None, None
            if cell:
                try:
                    period = resolve_period(cell["header_text"], document)
                    value = number(cell["text"])
                except ValueError:
                    status = "AMBIGUOUS" if period is None else "MISSING_VALUE"
                if cell.get("assignment_status", "ok") != "ok":
                    status, value = cell["assignment_status"], None
            if period is None and cell:
                # Preserve the year as evidence, but do not invent missing dates.
                status = "AMBIGUOUS"
            refs = re.findall(r"\((\d+)\)", segment_label + " " + label)
            fact = {"fact_id": f"{document['id']}:segments:{segment}:{year}:{metric}",
                    "company": document["company"], "document_id": document["id"],
                    "segment": segment, "segment_label": segment_label, "label": label,
                    "hierarchical_label": [heading, segment_label, label], "metric": metric,
                    "concept": qname(concept), "value": value, "unit": "USD (millions)",
                    "period": period, "year_header": year, "status": status,
                    "source_reference": source, "row": row, "column": cell["column"] if cell else None,
                    "cell": cell, "candidate_cells": candidates,
                    "footnotes": [f for f in footnotes if any(f["text"].startswith(f"({n})") for n in refs)]}
            facts.append(fact)
            if status != "ok":
                exceptions.append(fact)
    keys = [f["fact_id"] for f in facts]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate segment/metric/year rows; selection is ambiguous")
    return {"cells": cells, "facts": facts, "exceptions": exceptions}




def validate_segment(fact, inline):
    if fact["status"] != "ok":
        return {"table": fact, "status": "NO_COMPARABLE_FACT", "reason": "Unresolved table value or period"}
    segment = fact["segment"]
    dimensions = []
    if segment in OPERATING:
        dimensions = [("srt:ConsolidationItemsAxis", "us-gaap:OperatingSegmentsMember"),
                      ("us-gaap:StatementBusinessSegmentsAxis", SEGMENTS[segment])]
    elif segment == "Corporate and support":
        dimensions = [("srt:ConsolidationItemsAxis", "wmt:CorporateAndReconcilingItemsMember")]
    expected = {"entity": "104169", "entity_scheme": "http://www.sec.gov/CIK",
                "start": fact["period"]["start_date"], "end": fact["period"]["end_date"],
                "instant": None, "dimensions": sorted(dimensions)}
    result = compare(fact, inline, fact["concept"], expected)
    if result["status"] == "MISMATCH" and fact["metric"] == "other_gains_losses":
        result["reason"] += "; table reports losses as positive, whereas NonoperatingIncomeExpense reports income as positive"
    if result["status"] == "MISMATCH" and fact["metric"] == "interest_net":
        result["reason"] += "; table reports net interest expense as positive, whereas InterestIncomeExpenseNonoperatingNet uses an income-positive convention"
    return result


def reconcile(name, inputs, target, coefficients=None, evidence=None):
    coefficients = coefficients or [1] * len(inputs)
    result = {"name": name, "inputs": inputs, "target": target, "coefficients": coefficients,
              "source_references": [f["source_reference"] for f in inputs + [target]],
              "disclosure_evidence": evidence, "status": "UNRESOLVED", "value": None, "difference": None,
              "formula": " + ".join(f"({c}) * {f['fact_id']}" for c, f in zip(coefficients, inputs))}
    if len(inputs) != len(coefficients) or any(f.get("value") is None or not f.get("period") for f in inputs + [target]):
        result["reason"] = "Missing input; absent segment rows are not assumed zero"
        return result
    if len({period_identity(f["period"]) for f in inputs + [target]}) != 1 or len({f["unit"] for f in inputs + [target]}) != 1:
        result["reason"] = "Period or unit mismatch"
        return result
    if any(len({f.get(k) for f in inputs + [target]}) != 1 for k in ("company", "document_id")):
        result["reason"] = "Company or filing mismatch"
        return result
    value = sum((Decimal(c) * f["value"] for c, f in zip(coefficients, inputs)), Decimal(0))
    difference = value - target["value"]
    result.update(value=value, difference=difference, status="MATCH" if difference == 0 else "MISMATCH")
    return result


def build_segment_report(manifest_path=MANIFEST_PATH, raw_dir=RAW_DIR):
    document = next(d for d in load_manifest(manifest_path)["documents"] if d["id"] == "wmt-2025")
    path = Path(raw_dir) / document["filename"]
    if not verify_cached_file(path, document.get("sha256")):
        raise ValueError("Missing or checksum-invalid Walmart FY2025 cache")
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
    index, table, heading_tag = select_segment_tables(soup)[0]
    heading = normalize_text(heading_tag.get_text(" ", strip=True))
    source = f"{path.as_posix()}#table[{index}]"
    nodes = list(soup.find_all(True))
    positions = {id(node): i for i, node in enumerate(nodes)}
    start, end = positions[id(heading_tag)], positions[id(table)]
    next_table = table.find_next("table")
    stop = positions[id(next_table)] if next_table else len(nodes)
    def passages(a, b):
        return [{"text": normalize_text(n.get_text(" ", strip=True)),
                 "source_reference": f"{path.as_posix()}#element[{positions[id(n)]}]"}
                for n in nodes[a:b] if n.name in ("div", "p") and not n.find(["div", "p", "table"])
                and not n.find_parent("table") and n.get_text(strip=True)]
    evidence = passages(start, end)
    footnotes = [p for p in passages(end, stop) if re.match(r"^\(\d+\)", p["text"])]
    extracted = extract_segment_table(table, document, source, heading, footnotes)
    facts = extracted["facts"]
    inline = read_inline(soup, path.as_posix())
    for fact in inline:
        if fact["context"]:
            fact["raw_context"] = deepcopy(fact["context"])
            fact["context"] = dimensional_context(fact["context"])
    validations = [validate_segment(f, inline) for f in facts]
    calculations, reconciliations, unsupported = [], [], []
    years = sorted({f["year_header"] for f in facts}, reverse=True)
    def get(segment, year, metric):
        found = [f for f in facts if f["segment"] == segment and f["year_header"] == year and f["metric"] == metric]
        return found[0] if found else {"fact_id": f"missing:{segment}:{year}:{metric}", "value": None,
                                      "source_reference": source, "period": None, "unit": "USD (millions)"}
    consolidated = reported_periods(document, raw_dir)
    statement = extract_document_statement(document, raw_dir)
    for year in years:
        for segment in SEGMENTS:
            inputs = {f["metric"]: f for f in facts if f["segment"] == segment and f["year_header"] == year}
            if segment == "Corporate and support":
                unsupported.append({"segment": segment, "year": year, "status": "NOT_APPLICABLE",
                                    "reason": "No reported net sales, cost of sales or total revenue base; do not infer corporate gross profit or margins"})
            else:
                for metric in METRIC_FORMULAS:
                    calc = calculate_metric(metric, inputs)
                    calc.update(segment=segment, year=year, inputs=[f for f in inputs.values() if f["fact_id"] in calc["input_fact_ids"]])
                    calculations.append(calc)
            revenue_metric = "membership_other_income" if segment == "Corporate and support" else "total_revenues"
            components = [get(segment, year, revenue_metric)]
            if segment != "Corporate and support":
                components.append(get(segment, year, "cost_of_sales"))
            components.append(get(segment, year, "operating_expenses"))
            reconciliations.append(reconcile(f"{year} {segment}: revenues less disclosed expenses", components,
                get(segment, year, "operating_income"), [1] + [-1] * (len(components)-1), evidence))
        for metric in ("net_sales", "cost_of_sales", "membership_other_income", "total_revenues", "operating_expenses", "operating_income"):
            parts = [get(s, year, metric) for s in OPERATING]
            if metric not in ("net_sales", "cost_of_sales"):
                parts.append(get("Corporate and support", year, "membership_other_income" if metric == "total_revenues" else metric))
            reconciliations.append(reconcile(f"{year} segments to consolidated {metric}", parts, get("Consolidated", year, metric), evidence=evidence))
        reconciliations.append(reconcile(f"{year} operating income to pretax income",
            [get("Consolidated", year, m) for m in ("operating_income", "interest_net", "other_gains_losses")],
            get("Consolidated", year, "income_before_income_taxes"), [1, -1, -1], evidence))
        annual = next(g for g in consolidated if str(g["period"]["fiscal_year"]) == year)
        for label, (metric, _) in MAPPINGS.items():
            if label == "Operating loss":
                continue
            target = annual["reported_facts"].get(metric)
            if target is None:
                rows = {c["row"] for c in statement["cells"] if c["text"] == label}
                values = [c for c in statement["cells"] if c["row"] in rows and c["period_label"] == year and c["is_numeric"]]
                target = {"fact_id": f"{document['id']}:income-statement:{year}:{metric}",
                          "value": number(values[0]["text"]) if len(values) == 1 else None,
                          "period": annual["period"], "unit": "USD (millions)",
                          "company": document["company"], "document_id": document["id"],
                          "source_reference": statement["source_reference"], "cells": values}
            reconciliations.append(reconcile(f"{year} segment note to income statement {metric}",
                [get("Consolidated", year, metric)], target, evidence=evidence))
    exceptions = list(extracted["exceptions"])
    exceptions += [r for r in validations + reconciliations if r["status"] != "MATCH"]
    exceptions += [r for r in calculations if r["status"] != "ok"]
    return {"document": document, "heading": heading, "source_reference": source,
            "disclosure_evidence": evidence, "footnotes": footnotes, **extracted,
            "calculations": calculations, "reconciliations": reconciliations,
            "validations": validations, "unsupported_calculations": unsupported, "exceptions": exceptions}


def render_report(report):
    lines = ["# Walmart FY2025 segment report", report["heading"], report["source_reference"],
             "USD millions; row and column coordinates are zero-based. Calculated margins are analytical, not reported segment measures."]
    lines += [p["text"] + " Source: " + p["source_reference"] for p in report["disclosure_evidence"]]
    for segment in SEGMENTS:
        lines += ["\n## " + segment, "", "| Reported metric | FY2025 | FY2024 | FY2023 |", "| --- | ---: | ---: | ---: |"]
        metrics = list(dict.fromkeys(f["metric"] for f in report["facts"] if f["segment"] == segment))
        for metric in metrics:
            fs = [next(f for f in report["facts"] if f["segment"] == segment and f["metric"] == metric and f["year_header"] == year) for year in ("2025", "2024", "2023")]
            lines.append("| " + fs[0]["label"] + " | " + " | ".join(str(f["value"]) if f["value"] is not None else f["status"] for f in fs) + " |")
        for f in [f for f in report["facts"] if f["segment"] == segment]:
            lines.append(f"\n{f['fact_id']}: {f['source_reference']} row={f['row']} col={f['column']}; header={f['cell']['header_text'] if f['cell'] else 'unresolved'}")
    lines += ["\n## Footnotes", ""] + [p["text"] + " Source: " + p["source_reference"] for p in report["footnotes"]]
    lines += ["\n## Calculations and reconciliations", ""]
    for result in report["calculations"] + report["reconciliations"]:
        lines.append(f"\n{result.get('name', str(result.get('segment')) + ' ' + str(result.get('year')) + ' ' + result.get('metric', ''))}: {result['status']}; value={result['value']}; formula={result['formula']}")
        for fact in result["inputs"]:
            lines.append(f"- Input {fact['fact_id']}: {fact['value']} {fact['unit']}; {fact['source_reference']}")
        if "target" in result:
            target = result["target"]
            lines.append(f"- Target {target['fact_id']}: {target['value']}; {target['source_reference']}; difference={result['difference']}")
    lines += ["\n## Unsupported calculations", ""] + [str(r) for r in report["unsupported_calculations"]]
    lines += ["\n## XBRL validation", ""]
    lines += [f"- {r['table']['fact_id']}: {r['status']} ({r['reason']})" for r in report["validations"]]
    lines += ["\n## Exceptions", "", f"Count: {len(report['exceptions'])}; full evidence in exceptions.json."]
    for r in report["exceptions"]:
        fact = r.get("table", {})
        lines.append(f"\n- {fact.get('fact_id', r.get('name', r.get('label', 'Extraction')))}: {r['status']}; {r.get('reason', '')}")
        if fact:
            lines.append(f"  Table: {fact['value']} {fact['unit']}; {fact['source_reference']}; USD difference={r.get('difference_usd')}")
            for candidate in r.get("candidates", []):
                lines.append(f"  XBRL: {candidate['value']} {candidate['unit']}; {candidate['concept']}; context={candidate['context_id']}; {candidate['source_reference']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--output-dir", default="data/processed/segments")
    args = parser.parse_args()
    report = build_segment_report(args.manifest, args.raw_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for filename, obj in (("segments.json", report), ("exceptions.json", report["exceptions"])):
        (out / filename).write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(render_report(report), encoding="utf-8")
    print(report["source_reference"])
    print(f"Facts: {len(report['facts'])}; reconciliations: {len(report['reconciliations'])}; exceptions: {len(report['exceptions'])}")
    for r in report["exceptions"]:
        print(r.get("table", {}).get("fact_id", r.get("name")), r["status"], r.get("reason"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
