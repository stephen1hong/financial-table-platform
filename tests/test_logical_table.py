from pathlib import Path

from bs4 import BeautifulSoup

from sec_downloader.raw_table import parse_table_tag
from sec_downloader.logical_table import build_logical_table


def _table_from_html(html: str, table_id: int = 1):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    return parse_table_tag(table, source_file="data/raw/example.htm", table_id=table_id)


def test_logical_table_no_spans():
    raw = _table_from_html(
        """
        <table>
          <tr><th>Metric</th><th>2025</th></tr>
          <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.column_count == 2
    assert len(logical.rows) == 2
    assert [cell.text for cell in logical.rows[0].cells] == ["Metric", "2025"]
    assert [cell.text for cell in logical.rows[1].cells] == ["Revenue", "100"]
    assert all(cell.is_original for cell in logical.rows[0].cells)


def test_logical_table_colspan_only():
    raw = _table_from_html(
        """
        <table>
          <tr><th colspan="3">Years Ended</th></tr>
          <tr><th>2025</th><th>2024</th><th>2023</th></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.column_count == 3
    assert len(logical.rows) == 2
    row0 = logical.rows[0].cells
    assert len(row0) == 3
    assert [cell.text for cell in row0] == ["Years Ended", "Years Ended", "Years Ended"]
    assert row0[0].raw_cell.colspan == 3
    assert row0[0].is_span_expansion is False
    assert row0[1].is_span_expansion is True
    assert row0[2].is_span_expansion is True


def test_logical_table_rowspan_only():
    raw = _table_from_html(
        """
        <table>
          <tr><th rowspan="2">Metric</th><th>2025</th></tr>
          <tr><td>Revenue</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.column_count == 2
    assert [cell.text for cell in logical.rows[0].cells] == ["Metric", "2025"]
    assert [cell.text for cell in logical.rows[1].cells] == ["Metric", "Revenue"]
    assert logical.rows[1].cells[0].source_row_index == 0
    assert logical.rows[1].cells[0].source_cell_index == 0
    assert logical.rows[1].cells[0].is_span_expansion is True


def test_logical_table_rowspan_and_colspan_together():
    raw = _table_from_html(
        """
        <table>
          <tr>
            <th rowspan="2" colspan="2">Region</th>
            <th>2025</th>
          </tr>
          <tr><td>North</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.column_count == 3
    assert len(logical.rows) == 2
    row0 = logical.rows[0].cells
    assert [cell.text for cell in row0] == ["Region", "Region", "2025"]
    assert row0[0].is_span_expansion is False
    assert row0[1].is_span_expansion is True
    assert logical.rows[1].cells[0].text == "Region"
    assert logical.rows[1].cells[1].text == "Region"
    assert logical.rows[1].cells[2].text == "North"


def test_logical_table_multiple_rowspans_across_rows():
    raw = _table_from_html(
        """
        <table>
          <tr>
            <th rowspan="3">Item</th>
            <th>2025</th>
            <th rowspan="2">Note</th>
          </tr>
          <tr><td>Revenue</td></tr>
          <tr><td>Cost</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.column_count == 3
    assert [cell.text for cell in logical.rows[0].cells] == ["Item", "2025", "Note"]
    assert [cell.text for cell in logical.rows[1].cells] == ["Item", "Revenue", "Note"]
    assert [cell.text for cell in logical.rows[2].cells] == ["Item", "Cost", ""]
    assert logical.rows[1].cells[2].is_span_expansion is True


def test_logical_table_preserves_blank_cells_and_irregular_rows():
    raw = _table_from_html(
        """
        <table>
          <tr><th></th><th>Value</th><th></th></tr>
          <tr><td>Net sales</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.column_count == 3
    assert len(logical.rows) == 2
    assert logical.rows[0].cells[0].text == ""
    assert logical.rows[0].cells[2].text == ""
    assert logical.rows[1].cells[0].text == "Net sales"
    assert logical.rows[1].cells[1].text == ""
    assert logical.rows[1].cells[2].text == ""


def test_logical_table_tracks_provenance_after_span_expansion():
    raw = _table_from_html(
        """
        <table>
          <tr><th colspan="2">Years</th></tr>
          <tr><td>2025</td><td>2024</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    assert logical.rows[0].cells[0].source_row_index == 0
    assert logical.rows[0].cells[0].source_cell_index == 0
    assert logical.rows[0].cells[1].source_row_index == 0
    assert logical.rows[0].cells[1].source_cell_index == 0
    assert logical.rows[0].cells[1].is_span_expansion is True
    assert logical.rows[0].cells[1].raw_cell is logical.rows[0].cells[0].raw_cell


def test_logical_table_represents_all_source_cells():
    raw = _table_from_html(
        """
        <table>
          <tr><th rowspan="2">A</th><th>2025</th></tr>
          <tr><td>100</td></tr>
        </table>
        """
    )

    logical = build_logical_table(raw)

    source_pairs = {(cell.row_index, cell.cell_index) for row in raw.rows for cell in row.cells}
    represented = {
        (logical_cell.source_row_index, logical_cell.source_cell_index)
        for row in logical.rows
        for logical_cell in row.cells
        if logical_cell.raw_cell is not None
    }

    assert source_pairs.issubset(represented)
