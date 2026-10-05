from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from sec_downloader.extractor import expand_table_cells
from sec_downloader.metrics import calculate_metric, _build_report_for_document
from sec_downloader.periods import resolve_period
from sec_downloader.validation import compare


DOCUMENT = {"id": "wmt-2026-q3", "company": "Walmart", "form": "10-Q", "fiscal_year": 2026}
HEADERS = [f"{duration} Months Ended October 31, | {year}"
           for duration in ("Three", "Nine") for year in (2025, 2024)]


def test_header_periods_have_exact_dates_durations_and_fiscal_years():
    periods = [resolve_period(header, DOCUMENT) for header in HEADERS]
    assert [(p["start_date"], p["end_date"], p["duration"], p["duration_days"], p["fiscal_year"], p["period_type"])
            for p in periods] == [
        ("2025-08-01", "2025-10-31", "P3M", 92, 2026, "quarter"),
        ("2024-08-01", "2024-10-31", "P3M", 92, 2025, "quarter"),
        ("2025-02-01", "2025-10-31", "P9M", 273, 2026, "year_to_date"),
        ("2024-02-01", "2024-10-31", "P9M", 274, 2025, "year_to_date"),
    ]


@pytest.mark.parametrize("years", [(2025, 2024), (2024, 2025)])
def test_spanning_headers_resolve_year_and_duration_independent_of_column_order(years):
    html = f'''<table><tr><td></td><td colspan="2">Three Months Ended October 31,</td>
    <td colspan="2">Nine Months Ended October 31,</td></tr>
    <tr><td>Amounts in millions</td><td>{years[0]}</td><td>{years[1]}</td><td>{years[0]}</td><td>{years[1]}</td></tr>
    <tr><td>Net sales</td><td>177,769</td><td>168,003</td><td>517,500</td><td>495,708</td></tr></table>'''
    cells = [c for c in expand_table_cells(html, "sample#table[1]") if c["row"] == 2 and c["is_numeric"]]
    periods = [resolve_period(c["header_text"], DOCUMENT) for c in cells]
    assert [p["duration"] for p in periods] == ["P3M", "P3M", "P9M", "P9M"]
    assert [p["fiscal_year"] for p in periods] == [years[0]+1, years[1]+1]*2
    assert cells[0]["header_cells"][0]["original_text"] == "Three Months Ended October 31,"


@pytest.mark.parametrize("metric", ["gross_profit", "gross_margin_percentage", "operating_margin_percentage"])
@pytest.mark.parametrize("other_period", [1, 2, 3])
def test_calculations_reject_prior_year_and_ytd_mixing(metric, other_period):
    periods = [resolve_period(header, DOCUMENT) for header in HEADERS]
    inputs = {name: {"value": Decimal(value), "unit": "USD (millions)", "period": periods[0]}
              for name, value in (("net_sales", "100"), ("cost_of_sales", "60"), ("operating_income", "10"), ("total_revenues", "101"))}
    changed = "operating_income" if metric == "operating_margin_percentage" else "cost_of_sales"
    inputs[changed]["period"] = periods[other_period]
    assert calculate_metric(metric, inputs)["status"] == "period_mismatch"


def test_margin_formulas_zero_denominators_and_negative_operating_income():
    period = resolve_period(HEADERS[0], DOCUMENT)
    inputs = {name: {"value": Decimal(value), "unit": "USD (millions)", "period": period}
              for name, value in (("net_sales", "100"), ("cost_of_sales", "60"), ("operating_income", "-10"), ("total_revenues", "125"))}
    assert calculate_metric("gross_profit", inputs)["value"] == 40
    assert calculate_metric("gross_margin_percentage", inputs)["value"] == 40
    assert calculate_metric("operating_margin_percentage", inputs)["value"] == -8
    inputs["net_sales"]["value"] = 0
    assert calculate_metric("gross_margin_percentage", inputs)["status"] == "zero_denominator"


def test_xbrl_never_uses_equal_value_from_wrong_year_or_duration():
    period = resolve_period(HEADERS[0], DOCUMENT)
    expected = {"entity": "104169", "start": period["start_date"], "end": period["end_date"], "dimensions": []}
    fact = {"concept": "us-gaap:Revenues", "context": expected, "unit": "USD", "value": Decimal("100000000"), "decimals": "-6"}
    table = {"value": 100, "unit": "USD (millions)", "period": period}
    assert compare(table, [fact], fact["concept"], expected)["status"] == "MATCH"
    altered = {**table, "period": resolve_period(HEADERS[2], DOCUMENT)}
    assert compare(altered, [fact], fact["concept"], expected)["status"] == "NO_COMPARABLE_FACT"
    for header in HEADERS[1:]:
        other = resolve_period(header, DOCUMENT)
        wrong = {**fact, "context": {**expected, "start": other["start_date"], "end": other["end_date"]}}
        assert compare(table, [wrong], fact["concept"], expected)["status"] == "NO_COMPARABLE_FACT"


@pytest.mark.real_data
def test_original_10q_four_columns_and_calculations():
    document = next(d for d in json.loads(Path("data/manifest.json").read_text())["documents"] if d["id"] == DOCUMENT["id"])
    report = _build_report_for_document(document)
    groups = report["periods"]
    assert len(groups) == 4
    expected = {
        "net_sales": [177769, 168003, 517500, 495708],
        "total_revenues": [179496, 169588, 522507, 500431],
        "cost_of_sales": [134706, 127340, 391780, 375581],
        "operating_income": [6696, 6708, 21117, 21489],
        "net_income": [6143, 4577, 17656, 14182],
    }
    for metric, values in expected.items():
        assert [g["reported_facts"][metric]["value"] for g in groups] == values
    assert [g["period"] for g in groups] == [resolve_period(h, DOCUMENT) for h in HEADERS]
    assert [g["calculated_facts"]["gross_profit"]["value"] for g in groups] == [43063, 40663, 125720, 120127]
    assert "reported_facts" not in report  # No unlabeled current-quarter alias.
    for group in groups:
        assert all(f["period"] == group["period"] for f in group["calculated_facts"].values())
        assert group["reported_facts"]["net_sales"]["header_cells"]
