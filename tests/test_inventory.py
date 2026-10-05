from pathlib import Path
import pytest
from bs4 import BeautifulSoup

from sec_downloader.inventory import identify_income_statements, inventory_tables, select_statement_index


@pytest.mark.real_data
def test_inventory_tables_detects_file_structure():
    document = {
        "id": "wmt-2025",
        "company": "Walmart",
        "filename": "wmt-20250131.htm",
    }

    tables = inventory_tables(document, Path("data/raw"))
    assert tables
    assert all("document_id" in row for row in tables)
    assert all("source_reference" in row for row in tables)
    assert all("table_index" in row for row in tables)
    assert all(row["row_count"] >= 0 for row in tables)
    assert all(row["column_count"] >= 0 for row in tables)


@pytest.mark.real_data
def test_income_statement_selection_matches_heading_text():
    document = {
        "id": "aapl-2025",
        "company": "Apple",
        "filename": "aapl-20250927.htm",
    }

    matches = identify_income_statements(document, Path("data/raw"))
    assert matches
    statement = max(matches, key=lambda match: (match["row_count"], match["column_count"]))
    assert statement["table_index"] == 23
    assert "operations" in statement["heading"].lower() or "net income" in statement["heading"].lower() or "total net" in statement["heading"].lower()
    assert statement["source_reference"].startswith("data/raw/")


@pytest.mark.real_data
def test_source_reference_points_back_to_file_and_table():
    document = {
        "id": "wmt-2025",
        "company": "Walmart",
        "filename": "wmt-20250131.htm",
    }

    first_table = inventory_tables(document, Path("data/raw"))[0]
    assert "data/raw/wmt-20250131.htm#table[" in first_table["source_reference"].replace('\\', '/')
    assert first_table["source_reference"].endswith("]")


@pytest.mark.real_data
def test_walmart_selection_rejects_larger_segment_table_and_tracks_position():
    document = {"id": "wmt-2025", "company": "Walmart", "filename": "wmt-20250131.htm"}
    soup = BeautifulSoup(Path("data/raw/wmt-20250131.htm").read_text(encoding="utf-8"), "html.parser")
    assert select_statement_index(soup, document) == 50
    soup.find("table").insert_before(soup.new_tag("table"))
    assert select_statement_index(soup, document) == 51
    statement = soup.find_all("table")[50]
    statement.decompose()
    with pytest.raises(ValueError, match="Expected one consolidated"):
        select_statement_index(soup, document)


@pytest.mark.real_data
def test_duplicate_consolidated_statements_fail_instead_of_ranking_by_size():
    from copy import deepcopy
    document = {"id": "aapl-2025"}
    soup = BeautifulSoup(Path("data/raw/aapl-20250927.htm").read_text(encoding="utf-8"), "html.parser")
    statement = soup.find_all("table")[22]
    statement.insert_after(deepcopy(statement))
    with pytest.raises(ValueError, match="Expected one consolidated"):
        select_statement_index(soup, document)
