from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, ResultSet, Tag
from bs4.element import Tag

from .inventory import select_statement_index
from .downloader import verify_cached_file
from .manifest import load_manifest
from .periods import resolve_period


def normalize_text(value: Any) -> str:
    return " ".join(str(value).replace("\xa0", " ").split())


def parse_numeric_value(text: Any) -> dict[str, Any]:
    display: str = normalize_text(text or "")
    if display == "" or display == "-":
        return {"display_value": display, "normalized_value": None, "is_numeric": False}

    # A standalone four-digit year is a table header label, not a financial value.
    if re.fullmatch(r"20\d{2}", display):
        return {"display_value": display, "normalized_value": None, "is_numeric": False}

    # Some filings put a closing parenthesis in a neighboring cell. An incomplete
    # sign must remain unresolved, never silently become a positive magnitude.
    candidate = display.strip().removeprefix("$").strip()
    if candidate.endswith("%"):
        candidate = candidate[:-1].strip()
    if candidate.count("(") != candidate.count(")"):
        return {"display_value": display, "normalized_value": None, "is_numeric": False}
    if not re.fullmatch(r"(?:\(\s*\$?\s*\d[\d,]*(?:\.\d+)?\s*\)|-?\d[\d,]*(?:\.\d+)?)", candidate):
        return {"display_value": display, "normalized_value": None, "is_numeric": False}

    # detect parentheses as negative
    neg = False
    s: str = candidate
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s: str = s[1:-1].strip()

    # remove currency symbols and commas
    s_clean: str = re.sub(r"[^0-9.\-]", "", s)
    if s_clean == "" or s_clean == "-":
        return {"display_value": display, "normalized_value": None, "is_numeric": False}

    try:
        val = float(s_clean)
        if neg:
            val: float = -val
        return {"display_value": display, "normalized_value": val, "is_numeric": True}
    except ValueError:
        return {"display_value": display, "normalized_value": None, "is_numeric": False}


def expand_table_cells(table_html: str | Any, source_reference: str) -> list[dict[str, Any]]:
    # accept either HTML string containing a <table> or a BeautifulSoup Tag
    if isinstance(table_html, str):
        soup = BeautifulSoup(table_html, "html.parser")
        table: Tag | None = soup.find("table")
    else:
        table = table_html

    if table is None:
        return []

    # first pass: place original cells with start row/col using occupied map
    rows: ResultSet[Tag] | Any = table.find_all("tr")
    records: list[dict[str, Any]] = []
    occupied = {}
    for r_idx, row in enumerate(rows):
        col_idx = 0
        for cell in row.find_all(["th", "td"]):
            while occupied.get((r_idx, col_idx)):
                col_idx += 1

            rowspan = int(cell.get("rowspan") or 1)
            colspan = int(cell.get("colspan") or 1)
            original_text = cell.get_text()
            text: str = normalize_text(cell.get_text(" ", strip=True))

            rec = {
                "tag": cell.name,
                "text": text,
                "original_text": original_text,
                "row": r_idx,
                "column": col_idx,
                "rowspan": rowspan,
                "colspan": colspan,
                "source_reference": source_reference,
            }
            records.append(rec)

            for dr in range(rowspan):
                for dc in range(colspan):
                    occupied[(r_idx + dr, col_idx + dc)] = True

            col_idx += colspan

    # determine grid size
    total_rows: int = len(rows)
    total_cols = 0
    for rec in records:
        total_cols: int = max(total_cols, rec["column"] + rec["colspan"])

    # Include blank leading rows and full-date headings. A header cell contains
    # a year, possibly with a spelled-out month/day, but no financial amount.
    year_rows = [rec["row"] for rec in records
                 if re.fullmatch(r"(?:[A-Za-z]+\s+\d{1,2},?\s+)?20\d{2}", rec["text"])]
    header_row_count = min(year_rows) + 1 if year_rows else 0

    # build header text per column by looking at occupying cells in header rows.
    # We intentionally resolve the text for each logical column from the original
    # cells, so colspan blocks keep a single year label across all covered columns.
    headers: dict[int, list[str]] = {c: [] for c in range(total_cols)}
    for rec in records:
        if rec["row"] >= header_row_count:
            continue
        for dc in range(rec["colspan"]):
            col = rec["column"] + dc
            if col >= total_cols:
                continue
            txt = rec["text"]
            if txt:
                headers[col].append(txt)

    header_texts: list[str] = [" | ".join(headers.get(c, [])).strip() for c in range(total_cols)]

    # assign header_text and parse numeric info
    cells_out: list[dict[str, Any]] = []
    for rec in records:
        col = rec["column"]
        htxt = header_texts[col] if col < len(header_texts) else ""

        parsed: dict[str, Any] = parse_numeric_value(rec["text"])
        period_label = None
        m: re.Match[str] | None = re.search(r"(20\d{2})", htxt)
        if m:
            period_label: str | Any = m.group(1)

        cell = {
            "document_id": None,
            "text": rec["text"],
            "original_text": rec["original_text"],
            "header_cells": [dict(h) for h in records if h["row"] < header_row_count and h["column"] <= col < h["column"] + h["colspan"] and h["text"]],
            "display_value": parsed["display_value"],
            "normalized_value": parsed["normalized_value"],
            "is_numeric": parsed["is_numeric"],
            "row": rec["row"],
            "column": rec["column"],
            "rowspan": rec["rowspan"],
            "colspan": rec["colspan"],
            "tag": rec["tag"],
            "header_text": htxt,
            "period_label": period_label,
            "source_reference": rec["source_reference"],
        }
        if re.search(r"\d", rec["text"]) and rec["text"].count("(") != rec["text"].count(")"):
            cell["numeric_issue"] = "UNBALANCED_PARENTHESES: review adjacent source cells; sign not inferred"
        cells_out.append(cell)

    return cells_out


def extract_document_statement(document: dict[str, Any], raw_dir: str | Path) -> dict[str, Any]:
    raw_path = Path(raw_dir) / document["filename"]
    if not verify_cached_file(raw_path, document.get("sha256")):
        raise ValueError(f"Missing or checksum-invalid cached filing: {raw_path}")
    soup = BeautifulSoup(raw_path.read_text(encoding="utf-8"), "html.parser")
    index = select_statement_index(soup, document)
    source = f"{raw_path.as_posix()}#table[{index}]"
    cells = expand_table_cells(soup.find_all("table")[index - 1], source)
    for cell in cells:
        cell["document_id"] = document["id"]
        cell["period"] = resolve_period(cell["header_text"], document) if cell["period_label"] else None
    return {"document_id": document["id"], "company": document["company"],
            "filename": document["filename"], "table_index": index,
            "source_reference": source, "cells": cells}


def extract_manifest_statements(manifest_path: str | Path = Path("data/manifest.json"), raw_dir: str | Path = Path("data/raw"), processed_dir: str | Path = Path("data/processed")) -> list[dict[str, Any]]:
    manifest: dict[str, Any] = load_manifest(manifest_path)
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for document in manifest["documents"]:
        out = extract_document_statement(document, raw_dir)
        cells = out["cells"]
        for c in cells:
            c["document_id"] = document["id"]

        out_path: Path = processed_dir / f"{document['id']}-income-statement.json"
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        results.append(out)

    return results


def _print_preview(result: dict[str, Any]) -> None:
    print(f"{result['company']} ({result['document_id']}): {result['filename']}")
    print(f"  source: {result['source_reference']}")
    keys: list[str] = [
        "net sales",
        "total net sales",
        "total revenues",
        "cost of sales",
        "cost of goods sold",
        "gross profit",
        "operating income",
        "operating loss",
    ]
    for label in keys:
        for cell in result["cells"]:
            if cell["text"] and label in cell["text"].lower():
                print(f"   {cell['text']} @ r{cell['row']} c{cell['column']} -> {cell['display_value']} (period={cell['period_label']})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=str, default="data/manifest.json")
    parser.add_argument("--raw-dir", type=str, default="data/raw")
    parser.add_argument("--processed-dir", type=str, default="data/processed")
    args: argparse.Namespace = parser.parse_args()

    results: list[dict[str, Any]] = extract_manifest_statements(args.manifest, args.raw_dir, args.processed_dir)
    for r in results:
        _print_preview(r)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
