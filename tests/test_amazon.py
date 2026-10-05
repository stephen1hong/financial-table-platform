import json
from pathlib import Path
from bs4 import BeautifulSoup
import pytest

from sec_downloader.accounting import AMAZON_SEGMENTS
from sec_downloader.metrics import _build_report_for_document
from sec_downloader.segment_reporting import build_report
from sec_downloader.inventory import select_statement_index
from sec_downloader.segments import select_segment_tables
from sec_downloader.benchmark import collect_predictions, evaluate


def document():
    return next(d for d in json.loads(Path("data/manifest.json").read_text())["documents"] if d["id"] == "amzn-2025")


@pytest.mark.real_data
def test_amazon_ascending_periods_custom_expenses_and_cost_not_double_counted():
    report = _build_report_for_document(document())
    assert [g["period"]["fiscal_year"] for g in report["periods"]] == [2023, 2024, 2025]
    facts = report["reported_facts"]
    assert facts["technology_infrastructure"]["value"] == 108521
    assert facts["technology_infrastructure"]["hierarchical_label"][1] == "Operating expenses:"
    assert facts["net_product_sales"]["value"] + facts["net_service_sales"]["value"] == 716924
    assert facts["net_sales"]["value"] - facts["total_operating_expenses"]["value"] == 79975
    assert report["calculated_facts"]["gross_profit"]["value"] == 360510
    assert "not an Amazon-reported subtotal" in report["calculated_facts"]["gross_profit"]["accounting_note"]


@pytest.mark.real_data
def test_segment_losses_and_disclosed_net_income_bridge():
    r = build_report()
    assert len(r["facts"]) == 48
    loss = next(f for f in r["facts"] if f["segment"] == "International" and f["metric"] == "operating_income" and f["year_header"] == "2023")
    assert loss["value"] == -2656
    bridge = next(x for x in r["reconciliations"] if x["name"] == "2025 disclosed net-income bridge")
    assert [f["value"] for f in bridge["inputs"]] == [79975, 17336, -19087, -554]
    assert bridge["value"] == 77670
    assert len(r["reconciliations"]) == 48
    assert all(x["status"] == "MATCH" for x in r["reconciliations"])
    assert len(r["exceptions"]) == 3
    assert all(x["status"] == "AMBIGUOUS" for x in r["exceptions"])
    assert all(c["metric"] == "operating_margin_percentage" for c in r["calculations"])


@pytest.mark.real_data
def test_amazon_selection_uses_evidence_after_table_positions_change():
    soup = BeautifulSoup(Path("data/raw/amzn-20251231.htm").read_text(encoding="utf-8"), "html.parser")
    before = select_statement_index(soup, document())
    segment_before = select_segment_tables(soup, AMAZON_SEGMENTS)[0][0]
    soup.find("table").insert_before(soup.new_tag("table"))
    assert select_statement_index(soup, document()) == before + 1
    assert select_segment_tables(soup, AMAZON_SEGMENTS)[0][0] == segment_before + 1


@pytest.mark.real_data
def test_all_frozen_source_checked_benchmark_facts():
    expected = json.loads(Path("tests/fixtures/benchmark_facts.json").read_text())["facts"]
    predictions, _, _ = collect_predictions()
    result = evaluate(expected, predictions)
    assert result["present"] == 56
    assert result["coverage"] == 1
    assert result["end_to_end_accuracy"] == 1
