from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from sec_downloader.metrics import calculate_metric
from sec_downloader.periods import make_period
from sec_downloader.segments import (
    build_segment_report, select_segment_tables, extract_segment_table,
    dimensional_context, validate_segment, reconcile,
)


@pytest.fixture(scope="module")
def report():
    return build_segment_report()


def get(report, segment, metric, year="2025"):
    return next(f for f in report["facts"] if (f["segment"], f["metric"], f["year_header"]) == (segment, metric, year))


@pytest.mark.real_data
def test_source_checked_values_hierarchy_headers_and_footnotes(report):
    # Independently read from Note 12's FY2025/FY2024/FY2023 columns.
    assert len(report["facts"]) == 90
    expected = {
        "Walmart U.S.": [462415, 441817, 420553],
        "Walmart International": [121885, 114641, 100983],
        "Sam's Club U.S.": [90238, 86179, 84345],
        "Consolidated": [674538, 642637, 605881],
    }
    for segment, values in expected.items():
        assert [get(report, segment, "net_sales", y)["value"] for y in ("2025", "2024", "2023")] == values
    sam = get(report, "Sam's Club U.S.", "net_sales")
    assert sam["hierarchical_label"] == ["Note 12. Segments and Disaggregated Revenue", "Sam's Club U.S. (1)", "Net sales"]
    assert "9.9 billion" in sam["footnotes"][0]["text"]
    assert sam["cell"]["header_cells"][-1]["colspan"] > 1
    assert sam["cell"]["header_cells"][-1]["original_text"] == "2025"
    corporate = get(report, "Corporate and support", "membership_other_income")
    assert corporate["value"] == 52
    assert "corporate campus" in corporate["footnotes"][0]["text"]
    assert get(report, "Corporate and support", "operating_income")["value"] == -2439
    assert len(report["footnotes"]) == 2


@pytest.mark.real_data
def test_disclosed_adjustments_and_pretax_bridge_independent_examples(report):
    rows = {r["name"]: r for r in report["reconciliations"]}
    operating = rows["2025 segments to consolidated operating_income"]
    assert [f["value"] for f in operating["inputs"]] == [23882, 5501, 2404, -2439]
    assert sum(f["value"] for f in operating["inputs"][:3]) == 31787
    assert operating["value"] == 29348
    assert operating["status"] == "MATCH"
    revenue = rows["2025 segments to consolidated total_revenues"]
    assert [f["value"] for f in revenue["inputs"]] == [465009, 123363, 92561, 52]
    assert revenue["value"] == 680985
    bridge = rows["2025 operating income to pretax income"]
    assert [f["value"] for f in bridge["inputs"]] == [29348, 2245, 794]
    assert bridge["coefficients"] == [1, -1, -1]
    assert bridge["value"] == 26309
    assert len(report["reconciliations"]) == 63
    assert all(r["status"] == "MATCH" for r in report["reconciliations"])
    assert all(r["inputs"] and r["source_references"] and r["disclosure_evidence"] for r in report["reconciliations"])


@pytest.mark.real_data
def test_missing_adjustment_is_not_zero_and_wrong_period_is_rejected(report):
    row = next(r for r in report["reconciliations"] if r["name"] == "2025 segments to consolidated operating_income")
    inputs = deepcopy(row["inputs"])
    assert reconcile("without corporate", inputs[:3], row["target"])["status"] == "MISMATCH"
    inputs[-1]["value"] = None
    assert reconcile("missing corporate", inputs, row["target"])["status"] == "UNRESOLVED"
    inputs = deepcopy(row["inputs"])
    inputs[-1]["period"] = get(report, "Corporate and support", "operating_income", "2024")["period"]
    assert reconcile("wrong year", inputs, row["target"])["status"] == "UNRESOLVED"


@pytest.mark.real_data
def test_calculations_cannot_mix_segments_and_corporate_margins_are_not_invented(report):
    inputs = {"net_sales": get(report, "Walmart U.S.", "net_sales"),
              "cost_of_sales": get(report, "Walmart International", "cost_of_sales")}
    assert calculate_metric("gross_profit", inputs)["status"] == "source_mismatch"
    us = next(c for c in report["calculations"] if c["segment"] == "Walmart U.S." and c["year"] == "2025" and c["metric"] == "gross_profit")
    assert us["value"] == 125964
    assert len(us["inputs"]) == 2
    assert not any(c["segment"] == "Corporate and support" for c in report["calculations"])
    assert len(report["unsupported_calculations"]) == 3


@pytest.mark.real_data
def test_dimensional_validation_does_not_accept_same_value_from_other_segment(report):
    source = get(report, "Walmart U.S.", "net_sales")
    validation = next(v for v in report["validations"] if v["table"]["fact_id"] == source["fact_id"])
    candidate = deepcopy(validation["candidates"][0])
    assert validate_segment(source, [candidate])["status"] == "MATCH"
    candidate["context"]["dimensions"] = [("us-gaap:StatementBusinessSegmentsAxis", "wmt:WalmartInternationalMember")]
    assert validate_segment(source, [candidate])["status"] == "NO_COMPARABLE_FACT"
    assert validate_segment(source, [])["status"] == "NO_COMPARABLE_FACT"
    candidate["context"]["dimensions"] = []
    assert validate_segment(source, [candidate])["status"] == "NO_COMPARABLE_FACT"


def test_dimension_order_is_semantic_and_unknown_context_content_not_ignored():
    a = '<xbrli:segment><xbrldi:explicitmember dimension="b">two</xbrldi:explicitmember><xbrldi:explicitmember dimension="a">one</xbrldi:explicitmember></xbrli:segment>'
    b = '<xbrli:segment><xbrldi:explicitmember dimension="a">one</xbrldi:explicitmember><xbrldi:explicitmember dimension="b">two</xbrldi:explicitmember></xbrli:segment>'
    assert dimensional_context({"dimensions": [a]}) == dimensional_context({"dimensions": [b]})
    assert dimensional_context({"dimensions": [a.replace('</xbrli:segment>', '<custom>other</custom></xbrli:segment>')]}) != dimensional_context({"dimensions": [a]})


@pytest.mark.real_data
def test_sign_exceptions_preserve_original_values(report):
    assert len(report["exceptions"]) == 6
    assert sum(r["status"] == "MATCH" for r in report["validations"]) == 84
    for r in report["exceptions"]:
        assert r["status"] == "MISMATCH"
        assert r["table"]["metric"] in ("interest_net", "other_gains_losses")
        assert r["table"]["value"] * 1000000 == -r["candidates"][0]["value"]
        assert "positive" in r["reason"]


def test_missing_values_and_duplicate_year_headers_are_flagged():
    html = '''<table><tr><td></td><td colspan="6">Fiscal Years Ended January 31,</td></tr>
    <tr><td>(Amounts in millions)</td><td colspan="2">2025</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td colspan="7">Walmart U.S.</td></tr>
    <tr><td>Net sales</td><td>$</td><td>100</td><td>$</td><td></td><td>$</td><td>80</td></tr></table>'''
    document = {"id": "wmt-2025", "company": "Walmart", "form": "10-K", "fiscal_year": 2025}
    parse = lambda h: extract_segment_table(BeautifulSoup(h, "html.parser").table, document, "fixture#table[1]", "Segments", [])
    result = parse(html)
    assert [f["value"] for f in result["facts"]] == [100, None, 80]
    assert result["facts"][1]["status"] == "MISSING_VALUE"
    assert result["facts"][0]["period"]["fiscal_year"] == 2025
    ambiguous = parse(html.replace('>2024<', '>2025<'))
    assert any(e["status"] == "AMBIGUOUS_HEADER" for e in ambiguous["exceptions"])


@pytest.mark.real_data
def test_selection_uses_note_and_content_not_table_position():
    soup = BeautifulSoup(Path('data/raw/wmt-20250131.htm').read_text(encoding='utf-8'), 'html.parser')
    before = select_segment_tables(soup)[0][0]
    soup.find('table').insert_before(soup.new_tag('table'))
    assert select_segment_tables(soup)[0][0] == before + 1
    _, table, _ = select_segment_tables(soup)[0]
    table.insert_after(deepcopy(table))
    with pytest.raises(ValueError, match="Expected one"):
        select_segment_tables(soup)
