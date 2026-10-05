import pytest
from decimal import Decimal

from sec_downloader.metrics import build_financial_report, calculate_metric


@pytest.mark.real_data
def test_build_financial_report_uses_company_specific_mappings_for_real_filings():
    report = build_financial_report()
    apple = next(doc for doc in report["documents"] if doc["company"] == "Apple")
    walmart = next(doc for doc in report["documents"] if doc["company"] == "Walmart")

    assert apple["document_id"] == "aapl-2025"
    assert apple["reported_facts"]["net_sales"]["value"] == Decimal("416161")
    assert apple["reported_facts"]["gross_profit"]["value"] == Decimal("195201")
    assert apple["reported_facts"]["operating_income"]["value"] == Decimal("133050")
    assert apple["reported_facts"]["net_income"]["value"] == Decimal("112010")
    assert apple["reconciliation"]["gross_profit"]["status"] == "matched"

    assert walmart["document_id"] == "wmt-2025"
    assert walmart["reported_facts"]["net_sales"]["value"] == Decimal("674538")
    assert walmart["calculated_facts"]["gross_profit"]["value"] == Decimal("162785")
    assert walmart["calculated_facts"]["gross_profit"]["formula"] == "net_sales - cost_of_sales"
    assert walmart["reconciliation"]["gross_profit"]["status"] == "not_applicable"
    assert walmart["reported_facts"]["cost_of_sales"]["value"] == Decimal("511753")
    assert walmart["reported_facts"]["operating_income"]["value"] == Decimal("29348")
    assert walmart["reported_facts"]["net_income"]["value"] == Decimal("19436")
    assert all(fact["source_reference"].endswith("#table[50]") for fact in walmart["reported_facts"].values())
    assert all("row" in fact and "column" in fact for fact in walmart["reported_facts"].values())


@pytest.mark.real_data
def test_report_uses_changed_visible_cells_not_constants_or_xbrl_attributes(tmp_path):
    import json
    from pathlib import Path
    from bs4 import BeautifulSoup
    from sec_downloader.downloader import compute_sha256

    manifest = json.loads(Path("data/manifest.json").read_text())
    document = manifest["documents"][0]
    soup = BeautifulSoup((Path("data/raw") / document["filename"]).read_text(encoding="utf-8"), "html.parser")
    sales = soup.find_all("table")[49].find("ix:nonfraction", attrs={
        "name": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"})
    sales.string = "674,539"
    sales["scale"] = "3"  # This attribute must not determine the visible table amount.
    path = tmp_path / document["filename"]
    path.write_text(str(soup), encoding="utf-8")
    document["sha256"] = compute_sha256(path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"documents": [document]}), encoding="utf-8")
    report = build_financial_report(manifest_path, tmp_path)["documents"][0]
    assert report["reported_facts"]["net_sales"]["value"] == Decimal("674539")
    assert report["calculated_facts"]["gross_profit"]["value"] == Decimal("162786")


def test_calculate_metric_handles_missing_inputs_period_and_unit_mismatches():
    result_ok = calculate_metric(
        "gross_profit",
        {
            "net_sales": {"value": Decimal("100"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t1"},
            "cost_of_sales": {"value": Decimal("60"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t2"},
        },
    )
    assert result_ok["status"] == "ok"
    assert result_ok["value"] == Decimal("40")

    missing = calculate_metric(
        "gross_profit",
        {"net_sales": {"value": Decimal("100"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t1"}},
    )
    assert missing["status"] == "unresolved"

    mismatch = calculate_metric(
        "gross_profit",
        {
            "net_sales": {"value": Decimal("100"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t1"},
            "cost_of_sales": {"value": Decimal("60"), "unit": "EUR (millions)", "period": "FY2025", "source_reference": "src#t2"},
        },
    )
    assert mismatch["status"] == "unit_mismatch"

    year_mismatch = calculate_metric(
        "gross_profit",
        {
            "net_sales": {"value": Decimal("100"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t1"},
            "cost_of_sales": {"value": Decimal("60"), "unit": "USD (millions)", "period": "FY2024", "source_reference": "src#t2"},
        },
    )
    assert year_mismatch["status"] == "period_mismatch"

    negative = calculate_metric(
        "gross_profit",
        {
            "net_sales": {"value": Decimal("100"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t1"},
            "cost_of_sales": {"value": Decimal("-60"), "unit": "USD (millions)", "period": "FY2025", "source_reference": "src#t2"},
        },
    )
    assert negative["status"] == "negative_value"
