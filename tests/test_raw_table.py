import pytest
from pathlib import Path
from bs4 import BeautifulSoup

from sec_downloader.raw_table import parse_table_tag, extract_table_from_file


def test_parse_basic_table_cells_and_whitespace_cleanup():
    html = """
    <table>
      <tr><th> Item </th><th> Amount </th></tr>
      <tr><td>Revenue</td><td> $ 1,000 </td></tr>
      <tr><td> Cost </td><td> ( 200 ) </td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    raw = parse_table_tag(table, source_file="data/raw/example.htm", table_id=1)

    assert raw.table_id == 1
    assert raw.rows[0].cells[0].tag == "th"
    assert raw.rows[1].cells[1].raw_text.strip() == "$ 1,000"
    assert raw.rows[1].cells[1].normalized_text == "$ 1,000"


def test_rowspan_and_colspan_preserved_and_attrs():
    html = """
    <table>
      <tr><th rowspan="2">Header</th><th colspan="2">Years</th></tr>
      <tr><th>2025</th><th>2024</th></tr>
      <tr><td>Net sales</td><td>100</td><td>90</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    raw = parse_table_tag(table, source_file="data/raw/example2.htm", table_id=2)

    # header cell with rowspan preserved
    assert raw.rows[0].cells[0].rowspan == 2
    assert raw.rows[0].cells[1].colspan == 2
    # attributes preserved
    assert raw.rows[0].cells[0].attrs.get("rowspan") == "2"


def test_empty_cells_and_ixbrl_content():
    html = """
    <table>
      <tr><th>Label</th><th>Value</th></tr>
      <tr><td></td><td><ix:nonFraction contextRef="c1">123</ix:nonFraction></td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    raw = parse_table_tag(table, source_file="data/raw/example3.htm", table_id=3)

    assert raw.rows[1].cells[0].raw_text.strip() == ""
    # inner ix content becomes part of raw_text (we don't interpret it here)
    assert "123" in raw.rows[1].cells[1].raw_text


@pytest.mark.real_data
def test_extract_table_from_file_on_real_cached_files():
    # smoke test: ensure function can open real cached files from manifest
    # this does not assert contents, just that parsing runs without exception
    manifest_path = Path("data/manifest.json")
    assert manifest_path.exists()
    import json

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for doc in manifest["documents"]:
        filename = Path("data/raw") / doc["filename"]
        assert filename.exists()
        # we will not hard-assert a specific index here; attempt to parse the first table
        t = extract_table_from_file(filename, 1)
        assert t.rows is not None
