# Historical implementation notes

Detailed milestone 1?12A notes retained for reference. Use the root README for
current installation and test commands. Commands below assume the repository root.

# SEC income-statement pipeline

Caches and analyzes Walmart FY2025 and Apple FY2025 10-Ks plus Walmart's
[October 31, 2025 10-Q](https://www.sec.gov/Archives/edgar/data/104169/000010416925000191/wmt-20251031.htm)
(Q3 FY2026), plus Amazon FY2025 10-K. These four reviewed HTML filings and the
Walmart FY2025 text-based annual-report PDF are supported within the scopes below.

## Setup

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install -e . pytest
$env:SEC_USER_AGENT = "Your Name <your.name@example.com>"
```

Use your real identifying User-Agent and keep it only in the environment, never
in Git. The downloader reuses checksum-valid files, downloads absent or changed
files with that User-Agent, and saves SHA-256 checksums in `data/manifest.json`.
Raw filings and generated outputs under `data/raw/` and `data/processed/` are ignored.

## Run the complete pipeline

```powershell
python -m sec_downloader
python -m sec_downloader.inventory --output data/processed/inventory.json
python -m sec_downloader.extractor --processed-dir data/processed
python -m sec_downloader.metrics --output data/processed/financial-report.json
python -m sec_downloader.validation --output-dir data/processed/validation
python -m pytest -q
```

Inventory, extraction, metrics and validation share a selector based on mapped
statement row labels, entity identity, consolidated duration contexts and dates.
It rejects segment rows and stops on absent or ambiguous statements; no table
index determines selection. The annual statements are currently Walmart table 50
and Apple table 23. Financial amounts are read from visible cells, never constants
or replacement XBRL values. Extraction and validation verify cached checksums.

## Multi-period income statements (milestone 6)

The 10-Q report has four distinct columns, preserving the filing's order:

| Column | Start | End | Duration | Fiscal year | Type |
| --- | --- | --- | --- | --- | --- |
| Current three-month | 2025-08-01 | 2025-10-31 | P3M / 92 days | 2026 | quarter |
| Prior-year three-month | 2024-08-01 | 2024-10-31 | P3M / 92 days | 2025 | quarter |
| Current nine-month | 2025-02-01 | 2025-10-31 | P9M / 273 days | 2026 | year_to_date |
| Prior-year nine-month | 2024-02-01 | 2024-10-31 | P9M / 274 days | 2025 | year_to_date |

Period metadata is resolved from the visible duration/date/year headings, across
colspans, rather than inferred from the position or amount of a numeric fact.
Every extracted value includes period metadata, normalized combined `header_text`,
and `header_cells` containing the exact original text of each header cell and
its coordinates/spans. Exact visible value text is also retained. Each period has
start/end dates, ISO-style duration, inclusive day count, fiscal year and type.
Annual 10-K comparative columns also have this metadata; Apple's week-based annual
periods retain their exact 364/371-day lengths despite the annual P12M label.

Financial JSON uses `documents[].periods[]`, with separate `reported_facts`,
`calculated_facts` and `reconciliation` in each period. Annual documents also retain
a current-year top-level view for compatibility. The 10-Q has no unlabeled
single-period alias. Values use Decimal arithmetic and serialize as decimal strings.

Calculations require matching dates, duration, fiscal year, period type, company,
source document and units. Missing inputs and zero denominators remain unresolved:

- Gross profit = net sales - cost of sales.
- Gross margin percentage = 100 * gross profit / net sales.
- Operating margin percentage = 100 * operating income / total revenues for Walmart;
  Apple uses net sales because that is its reported revenue total.

These are calculated metrics, separate from reported facts. Formula, input IDs,
source references and the exact period are retained. Percentages display to two
decimals; JSON retains full Decimal precision. No quarter is derived by subtracting
YTD amounts. Walmart gross profit has no reported subtotal for reconciliation;
Apple's reported gross profit is reconciled independently for each annual period.

## Inline XBRL validation and reports

`python -m sec_downloader.validation` validates reported metrics directly from the
current financial pipeline against Inline XBRL in the same cached HTML. Matching
requires the same concept, entity, USD unit, exact start/end dates (therefore exact
duration), and dimension-free consolidated context. Walmart parent net income
(`NetIncomeLoss`) is distinct from consolidated net income (`ProfitLoss`).

Results are `MATCH`, `MISMATCH`, `AMBIGUOUS`, or `NO_COMPARABLE_FACT`. Reports retain
both original values, XBRL concept/context/unit/scale/sign, source references,
rejected candidates, table-minus-XBRL USD differences and rounding tolerance.
Tolerance is half the coarser reported precision, normally USD 500,000, with no
percentage tolerance. Equal duplicates retain all evidence; conflicting duplicates
are ambiguous. Scaling and sign discrepancies are diagnosed without overwriting
reported values. Missing, nil, unsupported-format or incompatible-context facts
cannot be selected as comparable facts.

Generated artifacts:

- `data/processed/<document_id>-income-statement.json`: expanded cells and provenance.
- `data/processed/financial-report.json` and `.md`: per-period figures and formulas.
- `data/processed/validation/report.md`: readable multi-column financial report,
  validation statuses, source references and actual exceptions.
- `data/processed/validation/validation.json` and `exceptions.json`: full evidence.

## Segment note extraction and reconciliation (milestone 7)

```powershell
python -m sec_downloader.segments
python -m pytest -q
```

This offline command uses only the checksum-verified Walmart FY2025 10-K.
Optional arguments are `--manifest`, `--raw-dir`, and `--output-dir` (default
`data/processed/segments`). The selector requires the segment-note heading and
the hierarchical operating-results table's content, rather than an index. Its
current location is Note 12, table 85. Disaggregated product revenues, assets,
geographic tables, and segment tables in other filings are outside this milestone.

Outputs, all ignored by Git:

- `segments.json`: expanded original cells, hierarchical labels, merged headers,
  periods, units, footnotes, original reported facts, calculations, reconciliation
  inputs/targets, and full XBRL evidence.
- `report.md`: three-year segment tables, source references, accounting-definition
  qualifications, calculations, reconciliations, validation statuses and exceptions.
- `exceptions.json`: every unresolved extraction/calculation/reconciliation or
  nonmatching XBRL result with investigation evidence.

The supported layout has FY2025, FY2024 and FY2023 across merged column headers,
and Walmart U.S., Walmart International, Sam's Club U.S., Corporate and support,
and Consolidated as parent rows. Missing values and ambiguous/duplicate headers
are flagged; blanks are never substituted with zero. Reported labels and inherited
footnotes are retained separately from canonical metric names. `operating_expenses`
maps only the reported operating, selling, general and administrative expense row;
it is not a label for all expenses including cost of sales.

Gross profit and margins reuse the existing formulas within one segment and
period. Cross-segment calculation inputs are rejected. Corporate margins and gross
profit are not computed because the table supplies no net-sales, cost-of-sales or
total-revenue base. As the filing explains, segment expense mixes are not directly
comparable across segments; calculated margins are analytical measures, not a
claim of comparability or reported segment performance measures.

Reconciliation follows the note's rows: three operating segments supply net sales
and cost of sales. Corporate membership/other income contributes to consolidated
membership income and total revenues; corporate expenses and operating loss also
contribute. No separate elimination amount is disclosed in this table, so none is
invented. Each category's revenue less expenses is checked against its operating
income. Consolidated operating income less net interest and other losses bridges
to pretax income. All nine consolidated note rows are separately checked against
the consolidated income statement, for all three years. Every reconciliation
retains coefficients, formula, input facts, target, difference and disclosure text.

Dimensional XBRL validation requires the exact entity, dates, concept, USD unit
and complete dimension set. Operating segments require both the business-segment
member and OperatingSegmentsMember; Corporate and support uses
CorporateAndReconcilingItemsMember; consolidated facts are dimension-free.
Dimension order is canonicalized; raw contexts remain available. This does not
perform general taxonomy equivalence or infer absent segment facts.

Verified extraction: 90 reported facts; 63 reconciliations match. Of 90 XBRL
comparisons, 84 match and six retain `MISMATCH` because consolidated net-interest
expense and other losses use opposite signs from their income-positive XBRL
concepts (three years each). These are explained sign-convention differences,
not unexplained consolidation gaps; neither original value is overwritten.
Footnote source references use zero-based document element positions; table cell
references use the existing zero-based row/column coordinates.

## Scope and limitations

Verified run: all 75 tests pass, including benchmark, segment, annual and quarterly regressions.
The October 31, 2025 10-Q selects table 7 using
document evidence, with 28 reported metric comparisons across four periods, all
MATCH. Including both 10-Ks' comparative periods, 64 comparisons match and the
exception report is empty. Net sales, cost of sales, operating income and parent
net income were also inspected directly in the original cached 10-Q table.

This is a filing-specific HTML/Inline XBRL pipeline, not a general taxonomy engine.
Supported numeric transforms are plain numeric, `num-dot-decimal`, and `fixed-zero`.
New filing layouts, fiscal calendars, header wording, units or concepts require
review. Reported monetary metrics use reviewed USD-million table units. Selection
uses Inline XBRL context evidence, while visible table amounts and header periods
are extracted independently of XBRL numeric attributes. Table/tag agreement checks
consistency within one source, not independent assurance of accounting figures.
Calculated margins are not presented as XBRL-reported facts. The PDF adapter is
described under milestone 9 below. Standalone-quarter subtraction, an LLM and a
dashboard are not included.


## Amazon generalization and benchmark (milestone 8)

Source: [Amazon FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm).
The original cached bytes and manifest SHA-256 use the same downloader/User-Agent
workflow. No identity is stored in the manifest or code.

```powershell
python -m sec_downloader
python -m sec_downloader.inventory --output data/processed/inventory.json
python -m sec_downloader.extractor
python -m sec_downloader.metrics --output data/processed/financial-report.json
python -m sec_downloader.validation
python -m sec_downloader.segments
python -m sec_downloader.segment_reporting
python -m sec_downloader.benchmark
python -m pytest -q
```

The Amazon segment command writes `data/processed/amazon-segments/` (report.md,
segments.json and exceptions.json). Consolidated commands process all four filings.
Benchmark outputs are `data/processed/benchmark/comparison.md`, `evaluation.json`,
`final-predictions.json`, and `exceptions.json`. All generated outputs remain ignored.

Before adding Amazon configuration or changing extraction logic, the existing
pipeline was run on its original cache: inventory found 92 tables; statement
selection, cell extraction, metrics and validation failed with `Unsupported filing:
amzn-2025`. The Walmart-specific segment selector found zero supported tables.
Baseline stage results, source checksum and source-code hashes are preserved in
`data/processed/benchmark/baseline.json`; prior pipeline predictions were frozen in
`baseline-predictions.json`. These baseline files are historical generated artifacts,
not recomputed with the modified parser. If absent, the benchmark explicitly reports
baseline unavailable rather than inventing results.

Demonstrated adaptations are reusable: selectors use configured anchor metrics;
concepts accept fully-qualified custom namespaces; calendars and segment names,
metric mappings and reconciliation rules reside in `accounting.py`; segment-note
headings accept alternate punctuation/capitalization; units may be evidenced in
note text immediately preceding a table. The existing merged-cell expansion handled
Amazon's ascending FY2023/FY2024/FY2025 columns without modification. JSON preserves
exact header cells; embedded header separators are escaped in Markdown tables.
Tables 36 and 70 are observed source locations, never selection inputs.

### Amazon accounting definitions

`accounting.py` documents each reported label and concept, including custom
`amzn:FulfillmentExpense` and `amzn:TechnologyAndInfrastructureExpense` concepts.
Product and service sales use distinct ProductOrServiceAxis members while remaining
consolidated measures. Segment facts use North America, International and AWS
business-segment members; dimension-free totals remain separate.

All six operating expense categories are extracted: cost of sales, fulfillment,
technology and infrastructure, sales and marketing, general and administrative,
and other operating expense. Their sum reconciles to total operating expenses.
Operating income is sales minus **total operating expenses**, with no additional
cost-of-sales deduction. Calculated gross profit is sales minus the reported
cost-of-sales category alone; it excludes fulfillment, technology/infrastructure,
marketing, G&A and other operating expenses and is never a reported subtotal.
This qualification is included in each calculation and the readable report.

Segment cost-of-sales categories are not separately disclosed, so segment gross
profit/margins are not inferred; only operating margins are calculated. The note
states that segments have no internal revenue transactions. Segment sales, total
operating expenses and operating income sum to consolidated values. Consolidated
operating income plus non-operating income plus the displayed signed tax provision
and equity-method activity reconciles to net income. No corporate or elimination
amounts are invented. All inputs, coefficients and source references are retained.

### Benchmark method and results

`tests/fixtures/benchmark_facts.json` contains 56 frozen, independently source-checked
expected facts: Apple annual (6), Walmart annual/segment (9), Walmart three/nine-month
quarterly (8), and Amazon annual/segment (33). Values and period assignments were
transcribed from original HTML; a separate DOM inspection checked visible text and
counted source-cell positions. No extractor outputs supplied expected answers.
Source references and reported labels accompany every expected value.

Predictions are located by filing, statement/segment-note scope and source cell,
not expected year, segment, metric or amount. Numeric equality uses Decimal with
no tolerance; period scoring includes exact dates, duration, fiscal year and type.
Unit, segment and canonical metric assignments are scored independently. Duplicate
predictions are ambiguous and missing numeric values reduce coverage.

| Measure | Baseline | Final |
| --- | ---: | ---: |
| Present facts | 23/56 | 56/56 |
| Coverage | 41.07% | 100% |
| Numeric/period/unit/segment/metric accuracy on present facts | 100% | 100% |
| Joint end-to-end accuracy (missing included) | 41.07% | 100% |

Final Amazon extraction has 48 consolidated and 48 segment-note facts covering all
three years, with 48 reconciliation checks passing. This is a curated development
benchmark, not held-out evidence of arbitrary-issuer generalization; false positives
outside the sampled cells are not scored. Passing displayed-value extraction does
not imply XBRL agreement.

Actual unresolved XBRL cases: three Amazon other-operating-expense sign differences
and three tax-provision duplicate ambiguities in the statement, plus the same three
tax ambiguities in the segment note. Rounded narrative tax facts (7.1/9.3/19.1 billion)
differ from table facts (7.120/9.265/19.087 billion); their precision intervals overlap,
but the conservative duplicate policy retains AMBIGUOUS rather than choosing a value.
The displayed tax provisions also carry an expense-negative sign. Together with
six prior Walmart sign exceptions, the combined report contains 15 entries, not
15 independent underlying discrepancies. Original values and all candidates remain
available. No unexplained reconciliation differences or benchmark missing facts remain.


## Milestone 9: text-based annual-report PDF adapter

The manifest's `pdf_documents` collection adds Walmart's official FY2025 annual
report, linked to the existing `wmt-2025` HTML filing. The SEC ARS index reports a
January 31, 2025 period end. The downloaded PDF's embedded 10-K cover independently
identifies Walmart Inc. and that fiscal year; the adapter verifies this text on
every run. The official URL, SHA-256 and verification evidence are in the manifest.
`documents` remains the HTML collection; the downloader caches and verifies both.
No contact information is stored in the manifest.

Windows setup (Python 3.12+, PowerShell):

```powershell
# If needed, first create the environment:
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m pip install pytest
$env:SEC_USER_AGENT = 'Your Name <your.email@example.com>'
.venv/Scripts/python -m sec_downloader
.venv/Scripts/python -m sec_downloader.pdf_adapter --render
.venv/Scripts/python -m sec_downloader.benchmark
.venv/Scripts/python -m pytest -q
```

`pdfplumber` supplies text/word geometry; its PDFium dependency renders selected
pages without a separate Poppler installation on Windows. Downloads and generated
reports/images are under the already ignored `data/raw/` and `data/processed/`.
The static, independently transcribed benchmark fixture is tracked source data.

The adapter discovers the consolidated income statement from its heading and
content, and the segment table from the segment-note heading plus segment and
metric labels. A note heading can be on the preceding page. It does not select by
page number. In this source, selection finds PDF pages 55 and 80, corresponding to
printed pages 53 and 78. Rendered-page review independently checked the year order,
merged fiscal heading, corporate loss parentheses and superscript footnotes.

Word coordinates yield label and annual-value columns. The adapter emits the
existing cell schema (including header cells and spans) and fact schema, augmented
with 1-based PDF pages, word geometry and bounding boxes. Coordinates are points
from the top-left corner: `[x0, top, x1, bottom]`. Empty cells have explicitly marked
geometric regions rather than invented text boxes. Hierarchy, raw labels and all
source rows survive even where no canonical metric mapping exists. Segment facts
reuse the shared segment mapper; statements reuse the existing filing mappings;
all calculations use the shared Decimal calculator.

Explicitly marked continuations with matching repeated year headers and column
positions are joined; repeated header evidence is retained without duplicate data
rows. Conflicting years, shifted columns and overlapping words become exceptions.
This source's two selected tables each fit on one page: multi-page support is
covered by synthetic geometry tests, not a real multi-page benchmark. Unmarked
continuations, wrapped labels requiring inference, rotated/multi-panel tables and
arbitrary issuer layouts are not supported. No OCR is performed. Each page receives
a text-availability status; short cover text is distinct from image-only/blank
pages. This PDF's page 97 has no usable text; neither selected table is affected.

Review outputs:

- `data/processed/pdf/review.md`: every selected table row, values, page locations,
  PDF/HTML comparisons, calculations with input facts, benchmark and exceptions.
- `report.json`: full cells, word/bounding-box geometry, original headers,
  footnotes, periods, values, comparison candidates and calculation inputs.
- `exceptions.md` / `exceptions.json`: unmapped rows, unresolved calculations,
  unsupported pages, missing facts and disagreements.
- `benchmark.json`: numeric/period/unit/segment/metric accuracy, coverage,
  missing facts and table coverage. `page-55.png` and `page-80.png` support review.

The PDF is extracted before HTML is read. Comparisons require matching company,
full fiscal period, metric, unit, segment and table scope, with unique candidates.
PDF gaps are never filled from HTML. PDF currency-symbol grouping, physical
indentation and superscript footnotes differ from HTML cell markup, but the mapped
reported values agree. Gross profit and margins remain calculated subtotals.

Observed results: 2/2 requested tables, 21 mapped statement facts and 90 segment
facts across FY2025/FY2024/FY2023; all 111 PDF/HTML comparisons match. Examples in
USD millions: FY2025 consolidated sales 674,538, cost of sales 511,753, Walmart U.S.
sales 462,415, Sam's Club sales 90,238, and corporate operating loss (2,439).
There are 153 numeric source cells: all are retained, but only 111 (72.55%) have
canonical mappings. Fourteen statement rows (42 cells) are explicitly unmapped,
including interest components, taxes, noncontrolling interest, EPS, share counts
and dividends. Nine corporate gross-profit/margin calculations remain unresolved
because corporate sales/cost/revenue bases are not reported.

`tests/fixtures/pdf_benchmark_facts.json` contains 45 examples manually transcribed
from rendered PDF pages, including all three years and all segment identities.
Expected values were not generated from extractor output. Source coordinates locate
predictions without using expected periods, segments or values. Thirty-nine facts
are present: 86.67% coverage and joint end-to-end accuracy; numeric, period, unit,
segment and metric accuracy on present facts are each 100%. Six missing examples
are three tax provisions and three basic EPS values outside the existing statement
mapping profile. Both tables are found (100% table coverage). This is a curated
development sample, not evidence of general PDF accuracy. The existing 56-example
HTML benchmark is evaluated separately and remains unchanged.


## Milestone 10: local OCR for simulated scans and table images

Install optional CPU OCR dependencies in PowerShell:

```powershell
.venv/Scripts/python -m pip install -e ".[ocr]"
.venv/Scripts/python -m sec_downloader.simulated_scans
.venv/Scripts/python -m sec_downloader.ocr_benchmark
.venv/Scripts/python -m sec_downloader.ocr_adapter --input data/processed/ocr/scans/clean-page-80.pdf --output-dir data/processed/ocr/single
# PNG/JPEG images also work; --dpi specifies the source image DPI.
.venv/Scripts/python -m sec_downloader.ocr_adapter --input data/processed/ocr/scans/clean-page-55.png --dpi 300
```

The tested stack uses RapidOCR-ONNXRuntime 1.4.4, ONNX Runtime 1.30.0,
OpenCV 5.0.0.93 and ReportLab 5.0.1, with the existing PDFium renderer. No GPU,
Tesseract installation or cloud OCR service is required. Model weights ship with
the OCR package under the ignored virtual environment. Installation downloads
packages; OCR inference itself is local. Per-run output records package versions,
model SHA-256 checksums, engine settings and image fingerprints.

`tests/fixtures/scan_recipe.json` specifies original PDF checksum and pages 55/80,
300-DPI clean renders, 100-DPI reduced-resolution renders and 200-DPI renders
rotated 1.5 degrees. All six generated PDFs contain only losslessly embedded images,
no text layer. Deterministic PDF metadata and rendering settings are recorded in
`data/processed/ocr/scans/manifest.json`, together with image/PDF checksums.
These are **simulated scans**, not independently acquired real scanner captures.

OCR detection polygons are transformed into the existing geometric cell schema.
Source polygons/boxes and original OCR text remain separate from deskew geometry
and Decimal readings. Existing merged-header/row hierarchy extraction, fiscal
period resolver, mappings and calculations are reused. Numeric grammar rejects
letter substitutions, malformed comma/sign groupings and merged numeric tokens.
Unexpected decimals in integer monetary rows, confidence below 0.95 and an
operating-loss label with no negative sign require review. No values are repaired
from references, totals or neighboring periods. Unresolved inputs block calculations
and are identified by metric, fact ID and source reference.

The frozen OCR reference fixture reuses the 45 independently checked PDF examples.
Source anchor points come directly from the original printed amounts' geometry;
they locate predictions spatially without using expected period, segment or amount
as matching keys. Rotation settings transform reference coordinates only during
evaluation; OCR deskew estimates its own angle from detections.

| Simulated variant | Present reference facts | Coverage | Numeric / period / unit / segment accuracy on present | Joint end-to-end |
| --- | ---: | ---: | --- | ---: |
| Clean, 300 DPI | 34/45 | 75.56% | 100% each | 75.56% |
| Rotated 1.5 degrees, 200 DPI | 26/45 | 57.78% | 100% each | 57.78% |
| Reduced resolution, 100 DPI | 0/45 | 0% | Not measurable: none accepted | 0% |

Actual errors include `S 2,192` instead of a currency symbol and amount (flagged
letter confusion, no replacement), low-confidence currency/sign readings such as
`$ (2,243)`, and uncertain rotated row/segment labels. The 100-DPI pages did not
pass table/header recognition. Six tax/EPS examples still lack canonical mappings,
as in milestone 9. Confidence gates can reject correct readings as well as errors.
See `data/processed/ocr/benchmark/review.md` and `evaluation.json` for every missing,
unresolved or mismatched example, and each scan's `review.md`, source image,
bounding-box overlay, raw OCR output and calculation inputs.

## Milestone 11: local financial review interface

Flask provides the small Python interface and calls existing adapters directly.
Waitress serves it without development/debug mode; SQLite persists immutable
extraction snapshots and append-only correction history. There are no external
frontend assets or cloud services.

```powershell
.venv/Scripts/python -m pip install -e ".[review,ocr]"
.venv/Scripts/python -m sec_downloader.review_app
# Open http://127.0.0.1:8765
# Optional separate workspace or port:
.venv/Scripts/python -m sec_downloader.review_app --port 8766 --data-dir data/processed/my-review
```

Use **Import document** to select a cached filing or upload HTML/PDF with the
matching company/fiscal profile. File signatures and PDF text availability select
the adapter; unsupported profiles/layouts produce actionable errors. Processing
runs in background jobs with stage/progress messages. Unfinished jobs are marked
interrupted after restart; completed documents and all corrections persist.

Source & facts shows sanitized HTML tables or rendered PDF/scanned pages next to
extracted values. Selecting a PDF fact highlights its bounding box. Expand the cell
panel for raw cell text, header, row/column, page and box data. Filter company,
period, table, metric and segment. Reported facts, calculated values and unmapped
source candidates are separate; candidates do not inflate automatic benchmark
coverage. Calculations show formulas and supporting inputs and remain blocked when
inputs require review or have incompatible periods/units.

Review a value, complete period, unit, metric mapping or segment with a mandatory
reason. Corrections record old/new values, UTC timestamp and approval state, with
optimistic revision checks to prevent one tab overwriting another. Partial OCR
review cannot approve unrelated uncertain fields. Reviewed calculations are
recomputed; automatic extraction and source exceptions stay unchanged. Mapping
choices are constrained to existing reviewed canonical metrics. The exception queue
marks reviewed overrides while preserving original XBRL/reconciliation evidence.
The app does not automatically rerun validation after edits.

Compare & export blocks comparisons with differing dates/duration, units/currency,
canonical metric, accounting definition or segment context. JSON exports all four
datasets; CSV exports facts, calculations, source exceptions or correction history
individually. Each retains provenance. Choose **Automatic extraction** or **Reviewed
results** explicitly. Benchmarks do not read the SQLite review database.

Persistence is under `data/processed/review_app/`: uploaded source copies, rendered
assets, job artifacts and `reviews.sqlite3`. This entire directory is ignored.
The server binds only to localhost and checks mutation tokens/Host headers.
Uploaded HTML source views are stripped of active content and sandboxed. It is a
single-user local tool, not a multi-user deployment.

Validation commands:

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m sec_downloader.benchmark
.venv/Scripts/python -m sec_downloader.pdf_adapter --render
# Optional browser demonstration with an installed Chrome:
.venv/Scripts/python -m pip install playwright
.venv/Scripts/python scripts/review_demo.py
```

The browser demonstration imports Walmart HTML and text PDF, inspects source tables,
adds one to a value to check recalculation, verifies automatic data is unchanged,
then restores the source value with a second audit entry. It tests reload persistence,
blocks a cross-period comparison, exports JSON and uploads a clean simulated scan.
Screenshots and measured results are in `data/processed/review_demo/`. See
[SUPPORTED_FORMATS.md](../SUPPORTED_FORMATS.md) for precise layout and OCR limitations.


Final verification for milestones 10/11: **116 tests passed**. The local browser
flow completed HTML, text PDF and scanned-PDF import, correction/recalculation,
restore, export, incompatible-period rejection and restart-persistence checks with
no JavaScript errors. HTML and PDF each displayed 111 mapped facts plus 42 unresolved
source candidates; the uploaded segment scan displayed 90 facts with 11 held for
review. Detailed results and changed-file inventory are in the ignored
`data/processed/review_demo/REPORT.md`.

## Milestone 12A: broader real-document evaluation

The frozen sample in [evaluation/manifest.json](../evaluation/manifest.json) contains
ten additional official documents from Microsoft, Alphabet, Meta, Johnson &
Johnson (healthcare), and Costco. These are paired HTML/PDF representations of
five FY2024 filings, not ten independent filings. Microsoft/Alphabet are development
groups; Meta/J&J/Costco are held out. All representations of a filing stay together.

[Protocol](../evaluation/PROTOCOL.md), [reference rows](../evaluation/reference_rows.json),
[located annotations](../evaluation/references.json), and [evaluation findings](../evaluation/REPORT.md)
describe the sample, 120 distinct independently source-checked facts (240
representation annotations), denominators, errors and capability limits.
Original numbers were transcribed from source tables and checked against rendered
PDF pages; no extractor output or manual-review database populated the answer key.
This is a single-annotator evaluation, not external human adjudication.

Run from the project directory in PowerShell using the existing virtual environment:

```powershell
$env:SEC_USER_AGENT = 'Your Name <your.name@example.com>'
.venv/Scripts/python scripts/download_evaluation12a.py
.venv/Scripts/python -m sec_downloader.evaluation --split development --run-name final-development
.venv/Scripts/python -m sec_downloader.evaluation --split held_out --run-name final-held-out
.venv/Scripts/python -m pytest -q
```

No new Python package is required. The existing `evaluation/freeze.json` checks
source-code, manifest and reference hashes before held-out evaluation and rejects
changes. Do not re-freeze the same held-out set after tuning on its errors: move
it to development and acquire fresh held-out filing groups. The initial declaration
utility `scripts/prepare_evaluation12a.py` refuses to overwrite an existing sample.
The annotation compiler can verify/rebuild locations from the manually authored
rows, but is never called by the extraction collector.

Generated reports, complete predictions, per-fact failures and runtime measurements
are under `data/processed/evaluation12a/`; downloads are under
`data/raw/evaluation12a/`. Both directories are ignored by Git. The review app's
corrections never enter these scores. Genuine scanned-document coverage is zero;
milestone 10 simulated scans remain a separate evaluation.

If Requests cannot verify your workstation's HTTPS certificates, configure
`REQUESTS_CA_BUNDLE` with an approved PEM CA bundle. The measured run combined the
existing certifi bundle with certificates from Windows ROOT/CA stores in an ignored
local file, then used:

```powershell
$env:REQUESTS_CA_BUNDLE = (Resolve-Path data/processed/evaluation12a/windows-ca.pem).Path
```

TLS verification was not disabled. Alphabet's original company URL returned 403;
its official SEC annual-report mirror was used and the attempt recorded in the
manifest. Retrieval failures are retained in `download-errors.json`.
