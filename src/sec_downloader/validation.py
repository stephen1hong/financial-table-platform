"""Offline, filing-specific checks; table text is never replaced by tagged values."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bs4 import BeautifulSoup

from .downloader import MANIFEST_PATH, RAW_DIR, verify_cached_file
from .inventory import select_statement_index
from .manifest import load_manifest
from .metrics import build_financial_report, _report_text


from .filing_profiles import PROFILES
from .accounting import METRIC_DIMENSIONS, qname
from .xbrl_context import dimensional_context


def number(text):
    text = text.replace(",", "").replace("$", "").replace(" ", "").replace("\xa0", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        raise ValueError(f"Unsupported numeric text: {text!r}")
    return Decimal(text)


def read_inline(soup, filename):
    contexts = {}
    for tag in soup.find_all("xbrli:context"):
        def content(name):
            found = tag.find("xbrli:" + name)
            return found.get_text(strip=True) if found else None
        contexts[tag["id"]] = {
            "entity": (content("identifier") or "").lstrip("0"),
            "entity_scheme": tag.find("xbrli:identifier").get("scheme") if tag.find("xbrli:identifier") else None,
            "start": content("startdate"), "end": content("enddate"),
            "instant": content("instant"),
            "dimensions": [str(t) for t in tag.find_all(["xbrli:segment", "xbrli:scenario"])],
        }
    units = {}
    for tag in soup.find_all("xbrli:unit"):
        measures = [m.get_text(strip=True) for m in tag.find_all("xbrli:measure")]
        units[tag["id"]] = "USD" if measures == ["iso4217:USD"] and not tag.find("xbrli:divide") else str(tag)
    facts = []
    for index, tag in enumerate(soup.find_all("ix:nonfraction"), 1):
        fact = {"concept": tag.get("name"), "context_id": tag.get("contextref"),
                "context": contexts.get(tag.get("contextref")), "unit": units.get(tag.get("unitref")),
                "unit_ref": tag.get("unitref"), "text": tag.get_text(strip=True),
                "scale": tag.get("scale", "0"), "sign": tag.get("sign"),
                "decimals": tag.get("decimals"), "format": tag.get("format"),
                "source_reference": f"{filename}#{tag.get('id') or 'ix:nonfraction[' + str(index) + ']'}",
                "table_index": None, "value": None, "parse_error": None}
        parent = tag.find_parent("table")
        if parent is not None:
            fact["table_index"] = parent.get("data-validation-index")
        try:
            fmt = (fact["format"] or "").split(":")[-1]
            if tag.get("xsi:nil") in ("true", "1"):
                raise ValueError("nil fact")
            if fmt not in ("", "num-dot-decimal", "fixed-zero"):
                raise ValueError(f"unsupported transformation {fmt}")
            value = Decimal(0) if fmt == "fixed-zero" else number(fact["text"])
            fact["value"] = value * (Decimal(10) ** int(fact["scale"])) * (-1 if fact["sign"] == "-" else 1)
        except (ValueError, InvalidOperation) as error:
            fact["parse_error"] = str(error)
        facts.append(fact)
    return facts


def compare(table, facts, concept, expected):
    """Select by semantic context before looking at values; never choose a matching duplicate."""
    result = {"table": table, "concept": concept, "expected_context": expected,
              "status": "NO_COMPARABLE_FACT", "candidates": [], "rejected_candidates": [],
              "difference_usd": None, "tolerance_usd": None, "reason": "No corresponding concept in this filing"}
    period = table.get("period")
    if isinstance(period, dict):
        if (period.get("start_date") != expected.get("start")
                or period.get("end_date") != expected.get("end")):
            result["reason"] = "Table period differs from requested comparison context"
            return result
        days = (date.fromisoformat(period["end_date"]) - date.fromisoformat(period["start_date"])).days + 1
        if period.get("duration_days") != days:
            result["reason"] = "Table duration does not agree with its dates"
            return result
    for fact in facts:
        if fact["concept"] != concept:
            continue
        context = fact.get("context") or {}
        reasons = []
        if any(context.get(k) != v for k, v in expected.items()):
            reasons.append("entity, fiscal duration or dimensional context differs")
        if fact["unit"] != "USD":
            reasons.append("unit is not USD")
        if fact.get("value") is None:
            reasons.append(fact.get("parse_error") or "missing numeric value")
        if reasons:
            result["rejected_candidates"].append({**fact, "rejection": reasons})
        else:
            result["candidates"].append(fact)
    candidates = result["candidates"]
    if not candidates:
        if result["rejected_candidates"]:
            result["reason"] = "Facts exist, but none has the required entity, exact duration, consolidated context, unit and supported numeric representation"
        return result
    if len({f["value"] for f in candidates}) > 1:
        result.update(status="AMBIGUOUS", reason="Conflicting duplicate facts in comparable contexts; no candidate chosen")
        precisions = [f.get("decimals", "") or "" for f in candidates]
        if all(re.fullmatch(r"-?\d+", p) for p in precisions):
            intervals = [(f["value"] - Decimal(10) ** -int(p) / 2,
                          f["value"] + Decimal(10) ** -int(p) / 2) for f, p in zip(candidates, precisions)]
            if max(low for low, high in intervals) <= min(high for low, high in intervals):
                result["reason"] += "; candidate rounding intervals overlap, but differently rounded originals are retained without selecting one"
        return result
    if table.get("unit") not in ("USD", "USD (millions)") or table.get("value") is None:
        result["reason"] = "Missing table value or unsupported table unit"
        return result
    scale = Decimal(1000000) if table["unit"] == "USD (millions)" else Decimal(1)
    original = Decimal(str(table["value"]))
    normalized = original * scale
    # Compare at the coarser reported precision, never relative percentage tolerance.
    tolerances = [scale / 2]
    for fact in candidates:
        decimals = fact.get("decimals")
        if decimals and decimals != "INF":
            tolerances.append(Decimal(10) ** -int(decimals) / 2)
    tolerance = max(tolerances)
    value = candidates[0]["value"]
    difference = normalized - value
    reason = "Exact match after converting table units to USD"
    if difference:
        if abs(difference) <= tolerance:
            reason = "Difference is within reported rounding precision"
        elif normalized == -value:
            reason = "Opposite signs: investigate display versus XBRL sign convention"
        elif original == value or normalized == value * Decimal(1000000):
            reason = "Possible million-fold unit scaling error"
        else:
            reason = "Numeric discrepancy after context, concept and unit selection; investigate extraction or accounting mapping"
    result.update(status="MATCH" if abs(difference) <= tolerance else "MISMATCH",
                  difference_usd=difference, tolerance_usd=tolerance, reason=reason)
    return result


def build_validation(manifest_path=MANIFEST_PATH, raw_dir=RAW_DIR):
    manifest = load_manifest(manifest_path)
    metrics = {d["document_id"]: d for d in build_financial_report(manifest_path, raw_dir)["documents"]}
    report = {"documents": [], "exceptions": []}
    for document in manifest["documents"]:
        if document["id"] not in PROFILES:
            raise ValueError("Unsupported filing")
        path = Path(raw_dir) / document["filename"]
        if not verify_cached_file(path, document.get("sha256")):
            raise ValueError(f"Missing or checksum-invalid cached filing: {path}")
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        tables = soup.find_all("table")
        for index, tag in enumerate(tables, 1):
            tag["data-validation-index"] = index
        facts = read_inline(soup, document["filename"])
        _, entity, _, _, mappings = PROFILES[document["id"]]
        if document["id"] in METRIC_DIMENSIONS:
            for fact in facts:
                if fact["context"]:
                    fact["raw_context"] = fact["context"]
                    fact["context"] = dimensional_context(fact["context"])
        index = select_statement_index(soup, document)
        source = f"{document['filename']}#table[{index}]"
        comparisons = []
        for group in metrics[document["id"]]["periods"]:
            period = group["period"]
            expected = {"entity": entity, "entity_scheme": "http://www.sec.gov/CIK",
                        "start": period["start_date"], "end": period["end_date"],
                        "instant": None, "dimensions": []}
            for metric, table in group["reported_facts"].items():
                concept = qname(mappings[metric][1])
                metric_expected = {**expected, "dimensions": METRIC_DIMENSIONS.get(document["id"], {}).get(metric, [])}
                comparisons.append(compare(table, facts, concept, metric_expected))
        entry = {**document, "selected_table": source, "comparisons": comparisons,
                 "periods": metrics[document["id"]]["periods"]}
        report["documents"].append(entry)
        report["exceptions"].extend({"company": document["company"], "document_id": document["id"],
                                     "kind": "consolidated_validation", **r}
                                    for r in comparisons if r["status"] != "MATCH")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--output-dir", default="data/processed/validation")
    args = parser.parse_args()
    report = build_validation(args.manifest, args.raw_dir)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("validation.json", report), ("exceptions.json", report["exceptions"])):
        (output / name).write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    readable = []
    for doc in report["documents"]:
        readable.append(_report_text({**doc, "document_id": doc["id"]}))
        groups = doc["periods"]
        readable.append("\n| XBRL validation | " + " | ".join(g["header_text"].replace("|", " / ") for g in groups) + " |")
        readable.append("| --- | " + " | ".join("---" for g in groups) + " |")
        for metric in groups[0]["reported_facts"]:
            statuses = [next(r["status"] for r in doc["comparisons"] if r["table"]["metric"] == metric
                             and r["table"]["period"]["id"] == g["period"]["id"]) for g in groups]
            readable.append("| " + metric + " | " + " | ".join(statuses) + " |")
    readable.append("\nExceptions: " + ("none" if not report["exceptions"] else "see details below"))
    for exception in report["exceptions"]:
        readable.append(f"{exception['document_id']} {exception['table']['metric']} {exception['table']['period']['id']}: {exception['status']} - {exception['reason']}")
        readable.append("```json\n" + json.dumps(exception, default=str, indent=2) + "\n```")
    (output / "report.md").write_text("\n".join(readable) + "\n", encoding="utf-8")
    for doc in report["documents"]:
        print(doc["company"], doc["selected_table"])
        for result in doc["comparisons"]:
            print(f"  {result['table']['metric']} [{result['table']['period']['id']}]: {result['table']['value']} million USD | {result['status']}")
    print("Exceptions:")
    for exception in report["exceptions"]:
        table = exception["table"]
        print(f"  {exception['company']} {exception['kind']} {table['metric']}: {exception['status']} - {exception['reason']}")
        print(f"    Original: {table['value']} {table['unit']} at {table['source_reference']}; concept={exception['concept']}")
        for fact in exception.get("source_value_facts", []):
            print(f"    Source XBRL: {fact['value']} {fact['unit']} context={fact['context_id']} at {fact['source_reference']}")
    print(f"Full evidence: {output / 'validation.json'}; exceptions: {output / 'exceptions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
