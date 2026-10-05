from copy import deepcopy
import json
from pathlib import Path

from sec_downloader.benchmark import evaluate


def fixture():
    return json.loads(Path("tests/fixtures/benchmark_facts.json").read_text())["facts"]


def test_benchmark_does_not_hide_period_segment_or_unit_errors_by_lookup_key():
    expected = fixture()[:1]
    wrong = deepcopy(expected)
    wrong[0]["period"]["fiscal_year"] = 1999
    wrong[0]["segment"] = "AWS"
    wrong[0]["unit"] = "USD"
    result = evaluate(expected, wrong)
    assert result["coverage"] == 1
    assert result["accuracy_on_present"]["numeric"] == 1
    assert result["accuracy_on_present"]["period"] == 0
    assert result["accuracy_on_present"]["segment"] == 0
    assert result["accuracy_on_present"]["unit"] == 0
    assert result["end_to_end_accuracy"] == 0


def test_missing_duplicate_and_numeric_error_reduce_scores():
    expected = fixture()[:3]
    actual = deepcopy(expected[:2])
    actual[0]["value"] = "123"
    result = evaluate(expected, actual)
    assert result["present"] == 2
    assert result["missing"] == [expected[2]["id"]]
    assert result["accuracy_on_present"]["numeric"] == .5
    assert result["end_to_end_accuracy"] == 1/3
    result = evaluate(expected, actual + actual[:1])
    assert result["ambiguous"] == [expected[0]["id"]]
    assert result["coverage"] == 1/3


def test_fixture_spans_companies_years_scopes_and_quarter_durations():
    facts = fixture()
    assert len(facts) == 56
    assert {f["document_id"] for f in facts} == {"wmt-2025", "wmt-2026-q3", "aapl-2025", "amzn-2025"}
    assert {f["scope"] for f in facts} == {"statement", "segment_note"}
    assert {f["period"]["duration"] for f in facts} == {"P3M", "P9M", "P12M"}
    assert all(f["source_reference"] and f["source_label"] for f in facts)
