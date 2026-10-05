# Finance Table Platform

**Extract, validate, and review financial tables with traceable source evidence.**

Finance Table Platform is a Python research project for selected SEC filings. It
preserves visible table values, source locations, fiscal periods, units, and segment
context, then uses those facts for financial calculations and comparison with inline
XBRL. A local web interface lets you inspect results, record corrections, and export
both automatic and reviewed data.

**Status:** v0.1.0 release candidate. Support is limited to reviewed filing profiles;
this is not a general-purpose financial document parser. The broader evaluation
found **0/18 held-out target tables selected and 0/144 facts mapped**. See
[Evaluation](#evaluation) for the measured results.

## Features

- HTML table inventory and merged-cell expansion with original text and coordinates.
- Company-specific statement and segment mappings with fiscal-period and unit checks.
- Decimal-based gross profit and margin calculations that reject incompatible inputs.
- Inline-XBRL comparisons and explicit missing, ambiguous, or unsupported results.
- Limited text-PDF extraction and an optional experimental OCR workflow.
- Local review UI with correction reasons, persistent history, and JSON/CSV exports.
- Reproducible demos, source manifests, frozen evaluation references, and offline tests.

## Quick start

The verified environment is **Windows x64 with CPython 3.12.10**. Install Python 3.12
and Git, clone or download this repository, and open PowerShell in its root directory.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements/build.lock -r requirements/release.lock
.venv/Scripts/python -m pip install --no-deps --no-build-isolation -e .
.venv/Scripts/python -m pip check

# Create a small demo without downloading filings or OCR models
.venv/Scripts/python scripts/offline_demo.py

# Start the local review interface
.venv/Scripts/python -m sec_downloader.review_app --data-dir data/processed/demo
```

Open **http://127.0.0.1:8765** and select the synthetic demo document. Stop the server
with `Ctrl+C`. The demo produces gross profit of **40 USD millions**, gross margin
of **40%**, and operating margin of **20%**. Its period, unit, and metric metadata are
explicitly supplied; it does not demonstrate automatic issuer discovery.

Follow the [demo walkthrough](docs/DEMO.md) to inspect source cells, apply a correction,
and confirm that the original automatic result remains available.

The supported installation is an **editable repository checkout**. Keep the source
tree in place: some adapters resolve manifests relative to it. Wheel imports and UI
assets are checked, but a standalone wheel is not a supported full application install.

For Linux, use Python 3.12 and `.venv/bin/python` in place of `.venv/Scripts/python`.
A Linux CI job is configured; it was not executed during local release preparation.
Dependencies are version-pinned, rather than pinned to binary artifact hashes.

## Try a real filing

The single-document demo downloads the reviewed Walmart FY2025 HTML 10-K, verifies
its SHA-256 checksum, and checks the results against stored expectations.

```powershell
$env:SEC_USER_AGENT = 'Your Name <your.name@example.com>'
.venv/Scripts/python scripts/real_demo.py --download
```

Expected gross profit is **162,785 USD millions**, with gross margin approximately
**24.13%** and operating margin approximately **4.31%**. Source metadata and expected
values are in [the demo manifest](demo/real-manifest.json) and
[expected outputs](demo/real-expected.json). Generated files stay under
`data/processed/real-demo/`. Repeat without `--download` to use the cached source.

Use your own identifying SEC User-Agent only in the environment. Downloads require
internet access and may fail because of access restrictions, TLS configuration, or
changed source bytes. The demo rejects checksum drift. If your network requires a
custom certificate bundle, configure `REQUESTS_CA_BUNDLE`; keep TLS verification on.

## Command-line workflow

Run these commands from the repository root after installation. The download command
acquires the sources declared in [data/manifest.json](data/manifest.json).

```powershell
# Download supported regression sources (requires SEC_USER_AGENT)
.venv/Scripts/python -m sec_downloader

# Inventory, extract, calculate, and validate
.venv/Scripts/python -m sec_downloader.inventory --output data/processed/inventory.json
.venv/Scripts/python -m sec_downloader.extractor --processed-dir data/processed
.venv/Scripts/python -m sec_downloader.metrics --output data/processed/financial-report.json
.venv/Scripts/python -m sec_downloader.validation --output-dir data/processed/validation

# Segment reporting and existing benchmarks
.venv/Scripts/python -m sec_downloader.segment_reporting
.venv/Scripts/python -m sec_downloader.benchmark
.venv/Scripts/python -m sec_downloader.pdf_adapter

# Review cached sources and supported uploads
.venv/Scripts/python -m sec_downloader.review_app
```

The UI binds to localhost and is intended for a single local user. It offers source
inspection, corrections with reasons, recalculation, comparisons, and JSON/CSV
exports. Automatic snapshots remain separate from reviewed values and history.

## How it works

```text
Source manifests -> checksum-verified local cache
  -> HTML tables / text-PDF geometry / optional OCR
  -> issuer mappings + fiscal periods + units + segment context
  -> reported facts -> calculations + XBRL comparisons + exceptions
  -> local review database -> web UI -> JSON/CSV exports
```

| Path | Purpose |
| --- | --- |
| `src/sec_downloader/` | Downloading, parsing, mappings, calculations, validation, and review app |
| `data/manifest.json` | Supported regression source URLs and checksums |
| `demo/` | Small synthetic input, real-source manifest, and expected results |
| `evaluation/` | Broader evaluation protocol, annotations, frozen hashes, and findings |
| `tests/` | Offline unit/integration cases and opt-in cached-document regressions |
| `requirements/` | Pinned build, application/test, and optional OCR dependencies |
| `scripts/` | Demo, evaluation, audit, export, and release-verification utilities |
| `docs/` | Walkthroughs, implementation notes, and release documentation |

Raw downloads, generated reports, review databases, virtual environments, and model
weights are excluded from the proposed source release.

## Supported scope

| Input or table type | Demonstrated support |
| --- | --- |
| HTML income statements | Walmart FY2025, Apple FY2025, Amazon FY2025 annual statements; Walmart Q3 FY2026 quarter/YTD |
| HTML segment notes | Reviewed Walmart and Amazon layouts and accounting definitions |
| Text PDF | Walmart FY2025 income statement and segment note |
| Tax and other arbitrary footnotes | No general canonical mapping or calculation support |
| OCR | Experimental simulated-scan workflow with review requirements |

See [SUPPORTED_FORMATS.md](SUPPORTED_FORMATS.md) for detailed boundaries. Unknown
issuers, ambiguous headers, unsupported mappings, and incompatible calculation inputs
remain unresolved instead of being silently treated as supported.

## Evaluation

Milestone 12A evaluated **10 official HTML/PDF documents representing 5 FY2024 filing
groups**. Microsoft and Alphabet formed the development set; Meta, Johnson & Johnson,
and Costco were held out. The references contain 120 distinct numeric facts with
240 representation annotations.

| Held-out measure | Result |
| --- | ---: |
| Target financial tables selected | 0/18 |
| Mapped facts present | 0/144 |
| End-to-end joint fact accuracy | 0% |
| Accuracy on present mapped facts | N/A: no predictions |
| Completed financial calculations | 0 |
| Correct sampled raw HTML numbers | 72/72 |
| Correct raw HTML year labels | 54/72 |
| Genuine scanned documents evaluated | 0 |

The raw HTML diagnostic scores cells at annotated locations. It does **not** measure
successful financial-table selection, full fiscal-period resolution, unit/segment
mapping, or calculation support. Paired HTML/PDF documents are correlated, and the
annotations were checked by the implementing agent without a second independent
annotator.

Earlier curated regression results were **56/56 HTML facts covered** and **39/45
text-PDF facts covered**, with all present benchmark fields correct. The text-PDF
checks also produced **111/111 matching HTML comparisons**. These are development
regressions, not evidence of generalization to new issuers.

Read the [evaluation report](evaluation/REPORT.md) and [protocol](evaluation/PROTOCOL.md).
To reproduce the broader evaluation after setting `SEC_USER_AGENT`:

```powershell
.venv/Scripts/python scripts/download_evaluation12a.py
.venv/Scripts/python scripts/check_freeze.py
.venv/Scripts/python -m sec_downloader.evaluation --split development --run-name reproduced-development
.venv/Scripts/python -m sec_downloader.evaluation --split held_out --run-name reproduced-held-out
```

Do not re-freeze these held-out documents after tuning against their errors. Source
and reference hashes preserve the original evaluation; Git attributes retain their
historical line endings.

## Tests

```powershell
# Default: offline unit and integration tests
.venv/Scripts/python -m pytest -q

# Requires separately downloaded, checksum-verified regression sources
.venv/Scripts/python -m pytest -m real_data -q

# All available tests, including optional OCR tests
.venv/Scripts/python -m pytest -o addopts= -q
```

Release preparation verified **88 offline tests passing**, with the OCR module
skipped and 29 real-data cases deselected. The full existing environment passed
**127 tests** using cached sources and installed OCR dependencies. Fresh installation,
package building, CLI startup, and localhost UI startup also passed.

The [CI workflow](.github/workflows/tests.yml) is configured for Python 3.12 on Windows
and Linux. Default tests block outbound socket connections; download behavior is
mocked. Live SEC retrieval and OCR model downloads are outside default CI. Hosted CI
had not run at the time of local release preparation.

## Optional OCR

The default demo and test suite need no GPU, Tesseract, Poppler, or OCR models.
For the optional CPU OCR stack:

```powershell
.venv/Scripts/python -m pip install -r requirements/ocr.lock
.venv/Scripts/python -m pip check
.venv/Scripts/python -m pytest -m ocr -q
```

This installs larger native dependencies and bundled RapidOCR models. Windows may
require a Microsoft Visual C++ 2019-compatible runtime; see the
[ONNX Runtime installation guide](https://onnxruntime.ai/docs/install/).
PDF rendering uses PDFium/Pillow, and simulated-scan generation uses ReportLab.
See [third-party and model notices](THIRD_PARTY_NOTICES.md) before redistributing assets.

## Known limitations

- Financial extraction relies on reviewed issuer profiles and specific layouts.
- Hierarchical headers, years arranged in rows, and some PDF font encodings remain unresolved.
- The evaluation covers a narrow sample of large US issuers; general IFRS, currency,
  handwriting, and arbitrary quarterly-format support is not established.
- Genuine scanned financial reports were not evaluated; simulated scans are separate evidence.
- Missing values and ambiguous periods, units, or segments can block calculations.
- The UI is a local development tool, not a hosted multi-user service.
- Reproduction depends on upstream package and document availability.

## Release documentation

- [Demo walkthrough](docs/DEMO.md)
- [Changelog](CHANGELOG.md) and [draft v0.1.0 release notes](docs/RELEASE_NOTES_v0.1.0.md)
- [Verification results and repository/history audit](docs/RELEASE_VERIFICATION.md)
- [Proposed release file list](docs/RELEASE_FILES.txt)
- [Detailed implementation notes](docs/IMPLEMENTATION_NOTES.md)

The audit and exporter can be rerun locally with `scripts/audit_release.py` and
`scripts/export_release.py`. Use a new export-directory name for each candidate.
`scripts/verify_release.py` tests the proposed files in a temporary local clone with
a fresh environment. Logs and exported inventories are ignored under `release-artifacts/`.

## License

**A project license has not yet been selected.** See
[LICENSE_DECISION.md](LICENSE_DECISION.md); choose the project's terms before publishing
an open-source release. Dependency and dataset terms are documented separately in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the
[dependency inventory](docs/DEPENDENCIES.md).
