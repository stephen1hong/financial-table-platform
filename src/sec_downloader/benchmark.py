"""Evaluate frozen, source-checked facts without using expected semantics to locate predictions."""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from .metrics import build_financial_report
from .periods import period_identity
from .segments import build_segment_report
from .segment_reporting import build_report as build_amazon_segments
from .validation import build_validation


def source_key(fact):
    reference = fact.get("source_reference", "").replace("\\", "/").rsplit("/", 1)[-1]
    return fact.get("document_id"), fact.get("scope"), reference, fact.get("row"), fact.get("column")


def evaluate(expected, predictions):
    index = {}
    for fact in predictions:
        index.setdefault(source_key(fact), []).append(fact)
    correct = dict.fromkeys(("numeric", "period", "unit", "segment", "metric", "joint"), 0)
    present, missing, ambiguous, failures = 0, [], [], []
    for reference in expected:
        found = index.get(source_key(reference), [])
        if len(found) != 1 or found[0].get("value") is None:
            (ambiguous if len(found) > 1 else missing).append(reference["id"])
            continue
        actual = found[0]
        present += 1
        checks = {
            "numeric": Decimal(str(actual["value"])) == Decimal(reference["value"]),
            "period": period_identity(actual.get("period") or {}) == period_identity(reference["period"]),
            "unit": actual.get("unit") == reference["unit"],
            "segment": actual.get("segment") == reference["segment"],
            "metric": actual.get("metric") == reference["metric"],
        }
        checks["joint"] = all(checks.values())
        for field, matched in checks.items():
            correct[field] += int(matched)
        if not checks["joint"]:
            failures.append({"expected": reference, "actual": actual, "checks": checks})
    total = len(expected)
    return {"expected": total, "present": present, "missing": missing, "ambiguous": ambiguous,
            "coverage": present / total if total else None,
            "correct": correct, "accuracy_on_present": {k: v / present if present else None for k, v in correct.items()},
            "end_to_end_accuracy": correct["joint"] / total if total else None, "failures": failures}


def collect_predictions():
    financial = build_financial_report()
    walmart = build_segment_report()
    amazon = build_amazon_segments()
    predictions = [{**f, "segment": "Consolidated", "scope": "statement"}
                   for d in financial["documents"] for g in d["periods"] for f in g["reported_facts"].values()]
    predictions += [{**f, "scope": "segment_note"} for report in (walmart, amazon) for f in report["facts"]]
    return predictions, walmart, amazon


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", default="tests/fixtures/benchmark_facts.json")
    parser.add_argument("--output-dir", default="data/processed/benchmark")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(Path(args.expected).read_text())
    expected = fixture["facts"]
    predictions, walmart, amazon = collect_predictions()
    validation = build_validation()
    final = evaluate(expected, predictions)
    baseline_file = output / "baseline-predictions.json"
    baseline = evaluate(expected, json.loads(baseline_file.read_text())) if baseline_file.exists() else None
    baseline_stages = json.loads((output / "baseline.json").read_text()) if (output / "baseline.json").exists() else None
    exceptions = validation["exceptions"] + walmart["exceptions"] + amazon["exceptions"]
    result = {"method": fixture["method"], "baseline": baseline, "final": final, "baseline_stages": baseline_stages,
              "by_document": {doc: evaluate([f for f in expected if f["document_id"] == doc], predictions)
                              for doc in sorted({f["document_id"] for f in expected})},
              "remaining_exceptions": exceptions,
              "amazon_statement_facts": sum(len(d["comparisons"]) for d in validation["documents"] if d["id"] == "amzn-2025"),
              "amazon_segment_facts": len(amazon["facts"]), "amazon_reconciliations": len(amazon["reconciliations"]),
              "amazon_reconciliation_failures": [r for r in amazon["reconciliations"] if r["status"] != "MATCH"]}
    (output / "evaluation.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (output / "final-predictions.json").write_text(json.dumps(predictions, indent=2, default=str), encoding="utf-8")
    (output / "exceptions.json").write_text(json.dumps(exceptions, indent=2, default=str), encoding="utf-8")
    lines = ["# Generalization and benchmark comparison", fixture["method"],
             "Accuracy on present facts uses the present count as denominator; coverage and end-to-end accuracy include missing/ambiguous facts. Source coordinates locate predictions; expected periods, segments and values are never lookup keys. Accuracy here measures displayed table extraction, not XBRL agreement.",
             "\n| Measure | Baseline | Final |", "| --- | ---: | ---: |"]
    def percentage(value):
        return "unavailable" if value is None else f"{100*value:.2f}%"
    for key in ("coverage", "end_to_end_accuracy"):
        lines.append(f"| {key} | {percentage(baseline[key]) if baseline else 'unavailable'} | {percentage(final[key])} |")
    for key, value in final["accuracy_on_present"].items():
        lines.append(f"| {key} accuracy on present | {percentage(baseline['accuracy_on_present'][key]) if baseline else 'unavailable'} | {percentage(value)} |")
    lines += [f"\nFinal: {final['present']}/{final['expected']} present; missing={final['missing']}; ambiguous={final['ambiguous']}.",
              "\n## Baseline stages", ""]
    if baseline_stages:
        lines += [f"- {stage}: {record['status']}; {record.get('error', record.get('result'))}" for stage, record in baseline_stages["stages"].items()]
    else:
        lines.append("Baseline snapshot unavailable; not reconstructed from current code.")
    lines += ["\n## Final pipeline", "", f"Amazon: {result['amazon_statement_facts']} statement facts; {len(amazon['facts'])} segment-note facts; {len(amazon['reconciliations'])} reconciliations, {len(result['amazon_reconciliation_failures'])} failures.",
              "\n## Remaining XBRL/extraction exceptions", "", "Full originals, contexts, differences and candidates: exceptions.json."]
    for r in exceptions:
        fact = r.get("table", {})
        lines.append(f"- {fact.get('fact_id', r.get('name'))}: {r['status']}; {r.get('reason', '')}")
    lines += ["\n## Supported types and limits", "", "Reviewed annual income statements (Walmart, Apple, Amazon), Walmart three/nine-month 10-Q, and hierarchical Walmart/Amazon segment operating-results notes. No table indexes control selection. Amazon custom QName concepts, product/service dimensions and oldest-first dates are supported. No arbitrary issuer discovery, PDF, taxonomy inference or automatic accounting-definition equivalence. Benchmark is a curated development sample; unreviewed fields and false positives outside sampled cells are not scored.",
              "\n## Demonstrated changes", "", "Baseline rejected the unknown profile and calendar, and assumed Walmart segment labels/note punctuation and in-table units. Added reviewed mappings, qualified custom concepts, configurable consolidated selector anchors, calendar-year periods, profile-driven segment labels and note selection, and support for units declared immediately before the segment table. Shared merged-cell expansion needed no change. Markdown header pipes are escaped for correct column counts. Tax duplicates and sign disagreements remain exceptions."]
    (output / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Benchmark: {final['present']}/{final['expected']} present; joint accuracy={percentage(final['accuracy_on_present']['joint'])}; coverage={percentage(final['coverage'])}")
    if baseline:
        print(f"Baseline: {baseline['present']}/{baseline['expected']} present; coverage={percentage(baseline['coverage'])}")
    print(f"Remaining exceptions: {len(exceptions)}; report: {output / 'comparison.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
