from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List

from bs4.element import Tag


def normalize_text(value: Any) -> str:
    """Light normalization for presentation: collapse whitespace and NBSPs."""
    if value is None:
        return ""
    s = str(value).replace("\xa0", " ")
    # collapse repeated whitespace
    return " ".join(s.split())


@dataclass
class RawCell:
    row_index: int
    cell_index: int
    tag: str
    raw_text: str
    normalized_text: str
    rowspan: int
    colspan: int
    attrs: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RawRow:
    row_index: int
    cells: List[RawCell]

    def to_dict(self) -> Dict[str, Any]:
        return {"row_index": self.row_index, "cells": [c.to_dict() for c in self.cells]}


@dataclass
class RawTable:
    source_file: str
    table_id: int
    title: str | None
    rows: List[RawRow]

    def to_dict(self) -> Dict[str, Any]:
        return {"source_file": self.source_file, "table_id": self.table_id, "title": self.title, "rows": [r.to_dict() for r in self.rows]}


def parse_table_tag(table_tag: Tag, source_file: str, table_id: int) -> RawTable:
    """Parse a BeautifulSoup <table> Tag into RawTable preserving HTML-level cell info.

    This function performs only minimal normalization (whitespace collapse) for presentation.
    It does NOT resolve row/col spans into a logical grid or interpret numeric values.
    """
    # nearest caption or heading as title
    title = None
    caption = table_tag.find("caption")
    if caption:
        title = normalize_text(caption.get_text(" ", strip=True))
    else:
        # try previous headings
        for tag_name in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div"):
            heading = table_tag.find_previous(tag_name)
            if heading is not None:
                title = normalize_text(heading.get_text(" ", strip=True))
                break

    rows: List[RawRow] = []
    for r_idx, row in enumerate(table_tag.find_all("tr")):
        cells: List[RawCell] = []
        for c_idx, cell in enumerate(row.find_all(["th", "td"])):
            raw_text = cell.get_text(" ", strip=False)
            norm_text = normalize_text(raw_text)
            rowspan = int(cell.get("rowspan") or 1)
            colspan = int(cell.get("colspan") or 1)
            attrs = dict(cell.attrs)
            rc = RawCell(
                row_index=r_idx,
                cell_index=c_idx,
                tag=cell.name,
                raw_text=raw_text,
                normalized_text=norm_text,
                rowspan=rowspan,
                colspan=colspan,
                attrs=attrs,
            )
            cells.append(rc)
        rows.append(RawRow(row_index=r_idx, cells=cells))

    return RawTable(source_file=source_file, table_id=table_id, title=title, rows=rows)


def extract_table_from_file(source_path: Path, table_index: int) -> RawTable:
    """Load an HTML file and parse the table at 1-based index `table_index`."""
    html = source_path.read_text(encoding="utf-8", errors="replace")
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if table_index < 1 or table_index > len(tables):
        raise IndexError("table_index out of range")
    tag = tables[table_index - 1]
    return parse_table_tag(tag, source_file=str(source_path.as_posix()), table_id=table_index)
