"""SEC filing download utilities."""

from .downloader import compute_sha256, download_document, load_manifest, should_download_document, verify_cached_file
from .inventory import build_inventory_report, identify_income_statements, inventory_tables
from .logical_table import LogicalCell, LogicalPlacementError, LogicalRow, LogicalTable, build_logical_grid, build_logical_table, logical_span_statistics, preview_logical_table
from .metrics import build_financial_report, calculate_metric

__all__ = [
    "compute_sha256",
    "download_document",
    "load_manifest",
    "should_download_document",
    "verify_cached_file",
    "inventory_tables",
    "identify_income_statements",
    "build_inventory_report",
    "build_financial_report",
    "calculate_metric",
    "LogicalCell",
    "LogicalRow",
    "LogicalTable",
    "LogicalPlacementError",
    "build_logical_table",
    "build_logical_grid",
    "preview_logical_table",
    "logical_span_statistics",
]
