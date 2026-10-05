from copy import deepcopy
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from sec_downloader.validation import build_validation, compare, read_inline


CONTEXT = {"entity": "104169", "entity_scheme": "http://www.sec.gov/CIK",
           "start": "2024-02-01", "end": "2025-01-31", "instant": None, "dimensions": []}
CONCEPT = "us-gaap:Revenues"


def fact(value="100000000", **changes):
    return {"concept": CONCEPT, "context": deepcopy(CONTEXT), "context_id": "annual",
            "unit": "USD", "value": Decimal(value), "decimals": "-6",
            "source_reference": "filing.htm#fact1", **changes}


def check(facts, value="100", unit="USD (millions)"):
    return compare({"value": Decimal(value), "unit": unit}, facts, CONCEPT, CONTEXT)


@pytest.mark.parametrize("changes", [
    {"entity": "320193"}, {"start": "2024-11-01"}, {"end": "2024-01-31"},
    {"dimensions": ["WalmartUSSegmentMember"]}, {"dimensions": ["typed dimension"]},
    {"instant": "2025-01-31", "start": None}, {"entity_scheme": "other"},
])
def test_context_selection_rejects_other_entities_periods_and_segments(changes):
    wrong = fact(context={**CONTEXT, **changes})
    result = check([wrong, fact()])
    assert result["status"] == "MATCH"
    assert len(result["candidates"]) == 1
    assert result["rejected_candidates"][0]["rejection"]
    assert check([wrong])["status"] == "NO_COMPARABLE_FACT"


def test_units_scaling_and_sign_diagnostics():
    assert check([fact()])["difference_usd"] == 0
    assert check([fact()], "100000000", "USD")["status"] == "MATCH"
    assert check([fact(unit="EUR")])["status"] == "NO_COMPARABLE_FACT"
    assert check([fact()], unit="shares")["status"] == "NO_COMPARABLE_FACT"
    assert "scaling" in check([fact("100")])["reason"]
    assert "Opposite signs" in check([fact("-100000000")])["reason"]


def test_rounding_boundary_and_mismatch_preserve_values():
    assert check([fact("100500000")])["status"] == "MATCH"
    result = check([fact("100500001")])
    assert result["status"] == "MISMATCH"
    assert result["difference_usd"] == Decimal("-500001")
    assert result["table"]["value"] == 100
    assert result["candidates"][0]["value"] == 100500001


def test_equal_duplicates_preserve_evidence_conflicts_are_ambiguous():
    duplicate = fact(context_id="equivalent-context", source_reference="filing.htm#fact2")
    result = check([fact(), duplicate])
    assert result["status"] == "MATCH"
    assert len(result["candidates"]) == 2
    result = check([fact(), fact("100000001")])
    assert result["status"] == "AMBIGUOUS"
    assert result["difference_usd"] is None


def test_missing_and_different_accounting_concepts_are_not_substituted():
    assert check([])["status"] == "NO_COMPARABLE_FACT"
    assert check([fact(concept="us-gaap:ProfitLoss")])["status"] == "NO_COMPARABLE_FACT"


def test_inline_parser_preserves_scale_sign_context_units_and_unsupported_facts():
    soup = BeautifulSoup('''
    <xbrli:context id="annual"><xbrli:entity>
    <xbrli:identifier scheme="http://www.sec.gov/CIK">0000104169</xbrli:identifier>
    </xbrli:entity><xbrli:period><xbrli:startdate>2024-02-01</xbrli:startdate>
    <xbrli:enddate>2025-01-31</xbrli:enddate></xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <xbrli:unit id="ratio"><xbrli:divide><xbrli:unitnumerator>
    <xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitnumerator>
    <xbrli:unitdenominator><xbrli:measure>xbrli:shares</xbrli:measure>
    </xbrli:unitdenominator></xbrli:divide></xbrli:unit>
    <ix:nonfraction id="f1" name="us-gaap:Revenues" contextref="annual"
    unitref="usd" scale="6" sign="-" decimals="-6" format="ixt:num-dot-decimal">1,234</ix:nonfraction>
    <ix:nonfraction name="us-gaap:Revenues" contextref="annual" unitref="ratio"
    format="ixt:fixed-zero">-</ix:nonfraction>
    <ix:nonfraction name="us-gaap:Revenues" contextref="annual" unitref="usd"
    format="ixt:unknown">one</ix:nonfraction>
    <ix:nonfraction name="us-gaap:Revenues" contextref="annual" unitref="usd"
    xsi:nil="true"></ix:nonfraction>
    ''', "html.parser")
    facts = read_inline(soup, "sample.htm")
    assert facts[0]["value"] == -1234000000
    assert facts[0]["text"] == "1,234"
    assert facts[0]["source_reference"] == "sample.htm#f1"
    assert facts[0]["context"] == CONTEXT
    assert facts[1]["value"] == 0 and facts[1]["unit"] != "USD"
    assert facts[2]["parse_error"] == "unsupported transformation unknown"
    assert facts[3]["parse_error"] == "nil fact"


@pytest.mark.real_data
def test_current_cached_filings_and_corrected_metrics():
    report = build_validation()
    results = [r for d in report["documents"] for r in d["comparisons"]]
    assert len(results) == 112
    assert all(r["status"] == "MATCH" for d in report["documents"] if d["id"] != "amzn-2025" for r in d["comparisons"])
    walmart = next(d for d in report["documents"] if d["id"] == "wmt-2025")
    metrics = {r["table"]["metric"]: r for r in walmart["comparisons"] if r["table"]["period"]["fiscal_year"] == 2025}
    assert metrics["net_sales"]["table"]["value"] == 674538
    assert metrics["net_income"]["table"]["value"] == 19436
    assert metrics["consolidated_net_income"]["concept"] == "us-gaap:ProfitLoss"
    assert len(report["exceptions"]) == 6
    assert all(e["document_id"] == "amzn-2025" for e in report["exceptions"])
    assert walmart["periods"][0]["calculated_facts"]["gross_profit"]["value"] == 162785


def test_checksum_failure_stops_validation(tmp_path):
    with pytest.raises(ValueError, match="checksum-invalid"):
        build_validation(raw_dir=tmp_path)
