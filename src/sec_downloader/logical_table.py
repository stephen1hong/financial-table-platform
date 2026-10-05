from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .raw_table import RawCell, RawTable


@dataclass
class LogicalCell:
    logical_row: int
    logical_column: int
    text: str
    source_row_index: int
    source_cell_index: int
    raw_cell: RawCell | None
    is_span_expansion: bool = False
    is_original: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_row": self.logical_row,
            "logical_column": self.logical_column,
            "text": self.text,
            "source_row_index": self.source_row_index,
            "source_cell_index": self.source_cell_index,
            "rowspan": self.raw_cell.rowspan if self.raw_cell is not None else None,
            "colspan": self.raw_cell.colspan if self.raw_cell is not None else None,
            "is_span_expansion": self.is_span_expansion,
            "is_original": self.is_original,
        }


@dataclass
class LogicalRow:
    row_index: int
    cells: list[LogicalCell] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"row_index": self.row_index, "cells": [cell.to_dict() for cell in self.cells]}


@dataclass
class LogicalTable:
    source_file: str
    table_id: int
    rows: list[LogicalRow]
    column_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "table_id": self.table_id,
            "rows": [row.to_dict() for row in self.rows],
            "column_count": self.column_count,
        }


class LogicalPlacementError(ValueError):
    """Raised when a logical-cell placement could not be represented safely."""


def _blank_cell(logical_row: int, logical_column: int) -> LogicalCell:
    return LogicalCell(
        logical_row=logical_row,
        logical_column=logical_column,
        text="",
        source_row_index=-1,
        source_cell_index=-1,
        raw_cell=None,
        is_span_expansion=False,
        is_original=False,
    )


def _make_cell(
    *,
    logical_row: int,
    logical_column: int,
    raw_cell: RawCell | None,
    text: str,
    source_row_index: int,
    source_cell_index: int,
    is_original: bool,
    is_span_expansion: bool,
) -> LogicalCell:
    return LogicalCell(
        logical_row=logical_row,
        logical_column=logical_column,
        text=text,
        source_row_index=source_row_index,
        source_cell_index=source_cell_index,
        raw_cell=raw_cell,
        is_original=is_original,
        is_span_expansion=is_span_expansion,
    )


def _next_available_column(row_map: dict[int, LogicalCell], reserved: dict[tuple[int, int], RawCell], row_index: int) -> int:
    column = 0
    while column in row_map or (row_index, column) in reserved:
        column += 1
    return column


def build_logical_table(raw_table: RawTable) -> LogicalTable:
    """Convert a physical RawTable into a rectangular logical table grid."""
    if not raw_table.rows:
        return LogicalTable(source_file=raw_table.source_file, table_id=raw_table.table_id, rows=[], column_count=0)

    row_span_reservations: dict[tuple[int, int], RawCell] = {}
    logical_rows: list[LogicalRow] = []
    max_columns = 0

    for physical_row_index, raw_row in enumerate(raw_table.rows):
        row_map: dict[int, LogicalCell] = {}

        for (row_idx, col_idx), raw_cell in sorted(
            row_span_reservations.items(), key=lambda item: item[0][1]
        ):
            if row_idx == physical_row_index:
                if col_idx in row_map:
                    raise LogicalPlacementError(
                        f"Conflicting rowspan reservation at row {physical_row_index}, column {col_idx}"
                    )
                row_map[col_idx] = _make_cell(
                    logical_row=physical_row_index,
                    logical_column=col_idx,
                    raw_cell=raw_cell,
                    text=raw_cell.normalized_text,
                    source_row_index=raw_cell.row_index,
                    source_cell_index=raw_cell.cell_index,
                    is_original=False,
                    is_span_expansion=True,
                )

        for raw_cell in raw_row.cells:
            col = _next_available_column(row_map, row_span_reservations, physical_row_index)
            occupied = set(range(col, col + raw_cell.colspan))
            for candidate in occupied:
                if candidate in row_map or (physical_row_index, candidate) in row_span_reservations:
                    raise LogicalPlacementError(
                        "Impossible placement for source cell "
                        f"{raw_cell.row_index}:{raw_cell.cell_index} at logical row {physical_row_index}, column {candidate}"
                    )

            row_map[col] = _make_cell(
                logical_row=physical_row_index,
                logical_column=col,
                raw_cell=raw_cell,
                text=raw_cell.normalized_text,
                source_row_index=raw_cell.row_index,
                source_cell_index=raw_cell.cell_index,
                is_original=True,
                is_span_expansion=False,
            )

            for offset in range(1, raw_cell.colspan):
                target_col = col + offset
                row_map[target_col] = _make_cell(
                    logical_row=physical_row_index,
                    logical_column=target_col,
                    raw_cell=raw_cell,
                    text=raw_cell.normalized_text,
                    source_row_index=raw_cell.row_index,
                    source_cell_index=raw_cell.cell_index,
                    is_original=False,
                    is_span_expansion=True,
                )

            if raw_cell.rowspan > 1:
                for span_row in range(physical_row_index + 1, physical_row_index + raw_cell.rowspan):
                    for span_col in range(col, col + raw_cell.colspan):
                        if (span_row, span_col) in row_span_reservations:
                            previous = row_span_reservations[(span_row, span_col)]
                            if previous is not raw_cell:
                                raise LogicalPlacementError(
                                    f"Rowspan conflict at row {span_row}, column {span_col} "
                                    f"for source cell {raw_cell.row_index}:{raw_cell.cell_index}"
                                )
                        row_span_reservations[(span_row, span_col)] = raw_cell

        row_length = max(max_columns, max(row_map.keys(), default=-1) + 1)
        row_values = [
            row_map.get(column, _blank_cell(physical_row_index, column))
            for column in range(row_length)
        ]
        logical_rows.append(LogicalRow(row_index=physical_row_index, cells=row_values))
        max_columns = max(max_columns, row_length)

    for row in logical_rows:
        while len(row.cells) < max_columns:
            row.cells.append(_blank_cell(row.row_index, len(row.cells)))

    source_positions = {
        (cell.row_index, cell.cell_index)
        for raw_row in raw_table.rows
        for cell in raw_row.cells
    }
    logical_source_positions = {
        (cell.source_row_index, cell.source_cell_index)
        for row in logical_rows
        for cell in row.cells
        if cell.source_row_index >= 0 and cell.source_cell_index >= 0
    }
    missing = source_positions - logical_source_positions
    if missing:
        raise LogicalPlacementError(f"Missing source-cell provenance for {sorted(missing)!r}")

    return LogicalTable(
        source_file=raw_table.source_file,
        table_id=raw_table.table_id,
        rows=logical_rows,
        column_count=max_columns,
    )


def build_logical_grid(raw_table: RawTable) -> LogicalTable:
    return build_logical_table(raw_table)


def preview_logical_table(logical_table: LogicalTable, max_rows: int = 10) -> list[list[str]]:
    return [[cell.text for cell in row.cells] for row in logical_table.rows[:max_rows]]


def logical_span_statistics(raw_table: RawTable, logical_table: LogicalTable) -> dict[str, int]:
    colspan_sources = 0
    rowspan_sources = 0
    colspan_expansions = 0
    rowspan_expansions = 0

    for raw_row in raw_table.rows:
        for raw_cell in raw_row.cells:
            if raw_cell.colspan > 1:
                colspan_sources += 1
            if raw_cell.rowspan > 1:
                rowspan_sources += 1

    for row in logical_table.rows:
        for cell in row.cells:
            if cell.raw_cell is None:
                continue
            if cell.raw_cell.colspan > 1 and cell.is_span_expansion:
                colspan_expansions += 1
            if cell.raw_cell.rowspan > 1 and cell.is_span_expansion:
                rowspan_expansions += 1

    return {
        "physical_row_count": len(raw_table.rows),
        "logical_row_count": len(logical_table.rows),
        "max_logical_column_count": logical_table.column_count,
        "cells_with_colspan_gt_1": colspan_sources,
        "cells_with_rowspan_gt_1": rowspan_sources,
        "colspan_expansion_positions": colspan_expansions,
        "rowspan_expansion_positions": rowspan_expansions,
    }
