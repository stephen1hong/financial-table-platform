from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .downloader import MANIFEST_PATH, RAW_DIR
from .manifest import load_manifest
from .extractor import extract_document_statement
from .filing_profiles import PROFILES
from .periods import period_identity
from .accounting import GROSS_PROFIT_NOTES, METRIC_PARENTS

METRIC_FORMULAS = {
    "gross_profit": "net_sales - cost_of_sales",
    "gross_margin_percentage": "100 * (net_sales - cost_of_sales) / net_sales",
    "operating_margin_percentage": "100 * operating_income / revenue",
}


def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value).replace("$", "").replace(",", "").replace("(", "-").replace(")", "").replace(" ", ""))
    except InvalidOperation:
        return None


def reported_periods(document, raw_dir):
    statement = extract_document_statement(document, raw_dir)
    cells = statement["cells"]
    groups = {}
    for metric, (label, _) in PROFILES[document["id"]][4].items():
        rows = {cell["row"] for cell in cells if cell["text"] == label}
        values = [cell for cell in cells if cell["row"] in rows and cell.get("period") and cell["is_numeric"]]
        if not values:
            raise ValueError(f"No reported values for {document['id']} {label}")
        for cell in values:
            period = cell["period"]
            group = groups.setdefault(period["id"], {"period": period, "column": cell["column"],
                "header_text": cell["header_text"], "header_cells": cell["header_cells"], "reported_facts": {}})
            if metric in group["reported_facts"]:
                raise ValueError(f"Ambiguous reported value for {label} {period['id']}")
            value = _to_decimal(cell["text"])
            if value is None:
                raise ValueError(f"Non-numeric reported value: {cell['text']}")
            group["reported_facts"][metric] = {
                "fact_id": f"{document['id']}:{period['id']}:{metric}", "metric": metric,
                "label": label, "segment": "Consolidated", "hierarchical_label": ["Consolidated"] + ([METRIC_PARENTS[document["company"]][metric]] if metric in METRIC_PARENTS.get(document["company"], {}) else []) + [label], "value": value, "display_value": cell["text"],
                "original_text": cell["original_text"], "unit": "USD (millions)",
                "period": period, "source_reference": statement["source_reference"],
                "row": cell["row"], "column": cell["column"],
                "header_text": cell["header_text"], "header_cells": cell["header_cells"],
                "company": document["company"], "document_id": document["id"],
            }
    result = sorted(groups.values(), key=lambda group: group["column"])
    expected_count = 4 if document["form"] == "10-Q" else 3
    if len(result) != expected_count:
        raise ValueError(f"Expected {expected_count} distinct periods, found {len(result)}")
    for group in result:
        if set(group["reported_facts"]) != set(PROFILES[document["id"]][4]):
            raise ValueError(f"Incomplete metrics in period {group['period']['id']}")
    return result


def reported_metrics(document, raw_dir):
    """Compatibility view for the current annual period; quarterly callers must select a period."""
    if document["form"] != "10-K":
        raise ValueError("Quarterly metrics require an explicit period")
    return next(g["reported_facts"] for g in reported_periods(document, raw_dir)
                if g["period"]["fiscal_year"] == document["fiscal_year"])


def calculate_metric(metric, inputs):
    if metric not in METRIC_FORMULAS:
        raise KeyError(f"Unsupported metric {metric!r}")
    denominator = "total_revenues" if "total_revenues" in inputs else "net_sales"
    required = ["operating_income", denominator] if metric == "operating_margin_percentage" else ["net_sales", "cost_of_sales"]
    formula = METRIC_FORMULAS[metric].replace(" / revenue", " / " + denominator)
    result = {"metric": metric, "status": "unresolved", "value": None,
              "formula": formula, "input_fact_ids": [], "source_references": [],
              "period": None, "unit": None}
    def fail(status, reason):
        return {**result, "status": status, "reason": reason}
    unresolved = [name for name in required if name not in inputs or
                  inputs[name].get('status', 'ok') != 'ok' or
                  _to_decimal(inputs[name].get('value')) is None]
    if unresolved:
        result.update(input_fact_ids=[inputs[n].get('fact_id') for n in required if n in inputs],
                      source_references=[inputs[n].get('source_reference') for n in required if n in inputs],
                      review_inputs=unresolved)
        return fail('unresolved', 'Review required inputs: ' + ', '.join(unresolved))
    facts = [inputs[name] for name in required]
    result.update(input_fact_ids=[f.get("fact_id") for f in facts],
                  source_references=[f.get("source_reference") for f in facts])
    periods = [f.get("period") for f in facts]
    keys = [period_identity(p) if isinstance(p, dict) else p for p in periods]
    if any(p is None for p in periods) or len(set(keys)) != 1:
        return fail("period_mismatch", "input dates, duration, fiscal year or period type differ")
    if any(isinstance(p, dict) and any(v is None for v in period_identity(p)) for p in periods):
        return fail("period_mismatch", "incomplete period metadata")
    result["period"] = periods[0]
    units = {f.get("unit") for f in facts}
    if len(units) != 1 or None in units:
        return fail("unit_mismatch", "input units differ or are missing")
    for key in ("company", "document_id", "segment"):
        if len({f.get(key) for f in facts}) > 1:
            return fail("source_mismatch", f"input {key} differs")
    values = {name: _to_decimal(inputs[name]["value"]) for name in required}
    if any(not value.is_finite() for value in values.values()):
        return fail("unresolved", "non-finite input value")
    if any(value < 0 for name, value in values.items() if name != "operating_income"):
        return fail("negative_value", "negative sales or cost input")
    if metric == "gross_profit":
        value = values["net_sales"] - values["cost_of_sales"]
    else:
        divisor = values[denominator] if metric == "operating_margin_percentage" else values["net_sales"]
        if divisor == 0:
            return fail("zero_denominator", "margin denominator is zero")
        numerator = values["operating_income"] if metric == "operating_margin_percentage" else values["net_sales"] - values["cost_of_sales"]
        value = 100 * numerator / divisor
    result.update(status="ok", value=value, unit="percent" if metric.endswith("percentage") else facts[0]["unit"])
    return result


def _build_report_for_document(document, raw_dir=RAW_DIR):
    groups = reported_periods(document, raw_dir)
    for group in groups:
        reported = group["reported_facts"]
        group["calculated_facts"] = {metric: {
            **calculate_metric(metric, reported),
            "fact_id": f"{document['id']}:{group['period']['id']}:{metric}:calculated"}
            for metric in METRIC_FORMULAS}
        reported_value = reported.get("gross_profit", {}).get("value")
        calculated = group["calculated_facts"]["gross_profit"]["value"]
        status = "not_applicable" if reported_value is None else "matched" if calculated == reported_value else "mismatch"
        group["reconciliation"] = {"gross_profit": {"status": status, "reported_value": reported_value,
            "calculated_value": calculated, "reason": "No reported subtotal" if reported_value is None else "Calculated versus reported subtotal"}}
    for group in groups:
        for name in ("gross_profit", "gross_margin_percentage"):
            group["calculated_facts"][name]["accounting_note"] = GROSS_PROFIT_NOTES.get(document["company"], "Calculated from reported net sales and cost of sales")
    report = {"document_id": document["id"], "company": document["company"],
              "filename": document["filename"], "source_url": document["source_url"],
              "periods": groups}
    # Existing annual consumers retain a current-year view. Never alias a 10-Q
    # to one unlabeled period, which could conceal its three/nine-month distinction.
    if document["form"] == "10-K":
        current = next(g for g in groups if g["period"]["fiscal_year"] == document["fiscal_year"])
        report.update({key: current[key] for key in ("reported_facts", "calculated_facts", "reconciliation")})
    return report


def build_financial_report(manifest_path=MANIFEST_PATH, raw_dir=RAW_DIR):
    return {"documents": [_build_report_for_document(d, raw_dir) for d in load_manifest(manifest_path)["documents"]]}


def _report_text(report):
    groups = report["periods"]
    lines = [f"{report['company']} ({report['document_id']})", f"Source: {report['source_url']}"]
    titles = [g["header_text"].replace("|", " / ") for g in groups]
    lines += ["| Metric (USD millions except %) | " + " | ".join(titles) + " |",
              "| --- | " + " | ".join("---:" for g in groups) + " |"]
    for kind in ("reported_facts", "calculated_facts"):
        for metric in groups[0][kind]:
            values = [g[kind][metric]["value"] for g in groups]
            formatted = [f"{v:,.2f}%" if metric.endswith("percentage") and v is not None else f"{v:,}" if v is not None else "unresolved" for v in values]
            lines.append("| " + metric + " | " + " | ".join(formatted) + " |")
    lines.append("Gross margin: 100 * (net sales - cost of sales) / net sales. Operating margin: 100 * operating income / total revenues where reported, otherwise net sales.")
    if report["company"] in GROSS_PROFIT_NOTES:
        lines.append(GROSS_PROFIT_NOTES[report["company"]])
    for group in groups:
        p = group["period"]
        lines.append(f"Period {p['id']}: FY{p['fiscal_year']}, {p['duration']}, {p['duration_days']} days; header: {group['header_text']}")
        for metric, fact in group["reported_facts"].items():
            lines.append(f"  {metric}: {fact['source_reference']} row={fact['row']} column={fact['column']} (zero-based)")
        for metric, calc in group["calculated_facts"].items():
            if calc["status"] != "ok":
                lines.append(f"  Exception: {metric}: {calc['status']} {calc.get('reason', '')}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Build period-specific financial reports from cached statements.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--output", default="data/processed/financial-report.json")
    args = parser.parse_args()
    report = build_financial_report(args.manifest, args.raw_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    text = "\n\n".join(_report_text(d) for d in report["documents"])
    output.with_suffix(".md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
