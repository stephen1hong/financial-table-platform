import pytest
from pathlib import Path

from sec_downloader.extractor import (
    expand_table_cells,
    extract_manifest_statements,
    parse_numeric_value,
)


def test_parse_numeric_value_handles_currency_and_negatives():
    assert parse_numeric_value("$ 1,234") == {"display_value": "$ 1,234", "normalized_value": 1234.0, "is_numeric": True}
    assert parse_numeric_value("( 1,234 )") == {"display_value": "( 1,234 )", "normalized_value": -1234.0, "is_numeric": True}
    assert parse_numeric_value("-") == {"display_value": "-", "normalized_value": None, "is_numeric": False}
    assert parse_numeric_value("") == {"display_value": "", "normalized_value": None, "is_numeric": False}


def test_expand_table_cells_preserves_spans_and_periods():
    html = """
    <table>
      <tr>
        <td colspan="2">Fiscal Years Ended</td>
        <td colspan="2">2025</td>
        <td colspan="2">2024</td>
      </tr>
      <tr>
        <td>Item</td>
        <td>Label</td>
        <td>Net sales</td>
        <td>Cost</td>
        <td>Net sales</td>
        <td>Cost</td>
      </tr>
      <tr>
        <td>Revenue</td>
        <td>$</td>
        <td>5000</td>
        <td>3000</td>
        <td>4500</td>
        <td>2800</td>
      </tr>
    </table>
    """

    cells = expand_table_cells(html, source_reference="data/raw/example.htm#table[10]")
    numeric_cells = [cell for cell in cells if cell["is_numeric"]]

    # original cells: 3 header + 6 column headers + 6 data = 15
    assert len(cells) == 15
    # third header cell (row 0) starts at column 4 and spans two columns
    assert cells[2]["row"] == 0 and cells[2]["column"] == 4
    assert cells[2]["colspan"] == 2 and "2024" in cells[2]["header_text"]
    assert numeric_cells[0]["period_label"] == "2025"
    assert numeric_cells[1]["period_label"] == "2025"
    assert numeric_cells[2]["period_label"] == "2024"
    assert numeric_cells[0]["normalized_value"] == 5000.0
    assert numeric_cells[0]["source_reference"] == "data/raw/example.htm#table[10]"


@pytest.mark.real_data
def test_extract_manifest_statements_writes_processed_json():
    processed_dir = Path("data/processed")
    results = extract_manifest_statements(
        manifest_path=Path("data/manifest.json"),
        raw_dir=Path("data/raw"),
        processed_dir=processed_dir,
    )

    assert results
    assert all("source_reference" in entry for entry in results)
    assert all((processed_dir / f"{entry['document_id']}-income-statement.json").exists() for entry in results)
    assert {entry["document_id"]: entry["table_index"] for entry in results if entry["document_id"] != "wmt-2026-q3"} == {"aapl-2025": 23, "wmt-2025": 50, "amzn-2025": 36}
    for entry in results:
        periods = {cell["period_label"] for cell in entry["cells"] if cell["is_numeric"]}
        assert ({"2025", "2024"} if entry["document_id"] == "wmt-2026-q3" else {"2025", "2024", "2023"}) <= periods
