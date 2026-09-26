from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .manifest import load_manifest
from .downloader import MANIFEST_PATH, RAW_DIR


def normalize_text(value: Any) -> str:
    return " ".join(str(value).replace("\xa0", " ").split())


def _row_count(table: Any) -> int:
    rows = table.find_all("tr")
    return len(rows)


def _column_count(table: Any) -> int:
    rows = table.find_all("tr")
    if not rows:
        return 0

    counts = []
    for row in rows:
        cells = row.find_all(["th", "td"])
        if cells:
            counts.append(len(cells))
    return max(counts, default=0)


def _nearest_heading_or_caption(table: Any) -> str:
    caption = table.find("caption")
    if caption:
        return normalize_text(caption.get_text(" ", strip=True))

    for tag_name in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div"):
        heading = table.find_previous(tag_name)
        if heading is not None:
            return normalize_text(heading.get_text(" ", strip=True))

    return ""


def _build_preview(table: Any, max_length: int = 160) -> str:
    text = normalize_text(table.get_text(" ", strip=True))
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def _source_reference(path: Path, table_index: int) -> str:
    relative = path.as_posix()
    if relative.startswith("/"):
        relative = relative.lstrip("/")
    return f"{relative}#table[{table_index}]"


def inventory_tables(document: dict[str, Any], raw_dir: str | Path) -> list[dict[str, Any]]:
    file_path = Path(raw_dir) / document["filename"]
    if not file_path.exists():
        raise FileNotFoundError(f"Local filing not found for {document['id']}: {file_path}")

    soup = BeautifulSoup(file_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    inventory: list[dict[str, Any]] = []

    for index, table in enumerate(soup.find_all("table"), start=1):
        heading = _nearest_heading_or_caption(table)
        inventory.append(
            {
                "document_id": document["id"],
                "document_company": document["company"],
                "table_index": index,
                "heading": heading,
                "row_count": _row_count(table),
                "column_count": _column_count(table),
                "preview": _build_preview(table),
                "source_reference": _source_reference(file_path, index),
            }
        )

    return inventory


def _is_income_statement_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text).lower().strip()
    if not normalized:
        return False

    if "consolidated" in normalized:
        return (
            "statement of income" in normalized
            or "statements of income" in normalized
            or "income statement" in normalized
            or "statement of operations" in normalized
            or "statements of operations" in normalized
        )

    has_income_signals = "net income" in normalized or "net sales" in normalized or "operating income" in normalized
    has_table_shape = "years ended" in normalized and "total revenue" in normalized.lower() if "total revenue" in normalized else True
    return has_income_signals and has_table_shape


def _is_income_statement_heading(heading: str) -> bool:
    return _is_income_statement_text(heading)


def identify_income_statements(document: dict[str, Any], raw_dir: str | Path) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for entry in inventory_tables(document, raw_dir):
        heading = entry["heading"]
        preview = entry["preview"]
        lowered_heading = heading.lower()
        is_index_page = "index to consolidated financial statements" in lowered_heading
        is_report_page = "report s of independent registered public accounting firm" in lowered_heading

        if is_index_page or is_report_page:
            continue

        if _is_income_statement_heading(heading) or _is_income_statement_text(preview):
            matches.append({**entry, "classification": "consolidated_income_statement"})
    return matches


def inventory_manifest(manifest_path: str | Path = MANIFEST_PATH, raw_dir: str | Path = RAW_DIR) -> list[dict[str, Any]]:
    manifest = load_manifest(manifest_path)
    inventory: list[dict[str, Any]] = []
    for document in manifest["documents"]:
        inventory.extend(inventory_tables(document, raw_dir))
    return inventory


def build_inventory_report(manifest_path: str | Path = MANIFEST_PATH, raw_dir: str | Path = RAW_DIR) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    tables: list[dict[str, Any]] = []
    selected_income_statements: dict[str, dict[str, Any]] = {}

    for document in manifest["documents"]:
        document_tables = inventory_tables(document, raw_dir)
        matches = identify_income_statements(document, raw_dir)
        if matches:
            selected_income_statements[document["id"]] = max(
                matches,
                key=lambda item: (item["row_count"], item["column_count"], item["table_index"]),
            )
        for entry in document_tables:
            entry["classification"] = (
                "consolidated_income_statement"
                if matches and entry["table_index"] == selected_income_statements[document["id"]]["table_index"]
                else "other"
            )
            tables.append(entry)

    return {
        "documents": [
            {
                "id": document["id"],
                "company": document["company"],
                "filename": document["filename"],
                "source_url": document["source_url"],
                "selected_income_statement": selected_income_statements.get(document["id"]),
            }
            for document in manifest["documents"]
        ],
        "tables": tables,
    }


def _safe_print(value: str) -> None:
    sanitized = value.encode("ascii", "replace").decode("ascii")
    print(sanitized)


def _print_inventory(report: dict[str, Any]) -> None:
    print("SEC table inventory")
    print("-" * 80)
    for entry in report["documents"]:
        _safe_print(f"{entry['company']} ({entry['id']}): {entry['filename']}")
        selected = entry["selected_income_statement"]
        if selected:
            _safe_print(
                "  Selected income statement: table_index="
                f"{selected['table_index']}, heading={selected['heading']}, source={selected['source_reference']}"
            )
        else:
            _safe_print("  Selected income statement: none found")

    print("\nDetailed table rows")
    print("document_id | table_index | heading | rows | cols | source_reference | preview")
    for table in report["tables"]:
        heading = table["heading"] or "(no heading)"
        preview = table["preview"]
        _safe_print(
            f"{table['document_id']} | {table['table_index']} | {heading[:80]} | {table['row_count']} | "
            f"{table['column_count']} | {table['source_reference']} | {preview[:100]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and classify SEC filing tables from local cached HTML files.")
    parser.add_argument("--manifest", type=str, default=str(MANIFEST_PATH), help="path to the SEC manifest JSON file")
    parser.add_argument("--raw-dir", type=str, default=str(RAW_DIR), help="path to the raw SEC HTML cache directory")
    parser.add_argument("--output", type=str, default=None, help="optional file path to save the JSON inventory report")
    args = parser.parse_args()

    report = build_inventory_report(args.manifest, args.raw_dir)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    _print_inventory(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
