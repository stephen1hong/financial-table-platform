# Milestone 12A: measured evaluation and capability limits

The evaluation is implemented; **the broader documents are not supported end to
end**. On the frozen held-out set, the current financial pipeline selected **0/18
target tables**, produced **0/144 annotated mapped facts**, and completed **0
financial calculations**. Raw HTML numeric extraction was much stronger, but did
not provide complete financial semantics. These results do not establish support
for most financial tables.

## Sample and provenance

The declared sample is ten additional public documents from five companies:
paired official HTML 10-Ks and text annual-report PDFs for Microsoft, Alphabet,
Meta Platforms, Johnson & Johnson (healthcare), and Costco FY2024. This represents
**five independent filing groups**, not ten independent filings. Microsoft and
Alphabet are development; Meta, J&J and Costco are held out. Source URLs, fiscal
dates, document types, SHA-256 checksums and verification notes are in
[manifest.json](manifest.json). All ten downloads completed.

Sources include SEC filings, the SEC-hosted Microsoft and Alphabet annual reports,
and PDFs supplied by [Meta investor relations](https://investor.atmeta.com/search-results/default.aspx?PageNumber=215&SearchTerm=),
[Johnson & Johnson](https://www.jnj.com/download/johnson-johnson-2024-annual-report),
and [Costco investor relations](https://investor.costco.com/financials/annual-reports-and-proxy-statements/default.aspx).
Alphabet's original company PDF URL returned HTTP 403; the same report was
retrieved from its official SEC ARS submission before extraction. No source was
substituted in response to extraction performance. TLS verification remained on;
the local Requests trust issue was resolved using Windows ROOT/CA certificates.

The answer key contains **120 distinct numeric facts**, 24 per filing, checked in
both representations: **240 annotations** with periods, units, segment identities
and source locations. There are 30 selected table instances: ten statements, ten
segment tables and ten tax-footnote tables. Development has 96 annotations/12
tables; held out has 144 annotations/18 tables. Values were hand-transcribed from
original visible HTML cells and all 15 relevant PDF pages were rendered and
visually compared. The location compiler asserts these literals against the raw
DOM without importing extraction code. It does not generate expected values from
predictions. See [reference_rows.json](reference_rows.json),
[references.json](references.json) and [PROTOCOL.md](PROTOCOL.md).

The same implementing agent annotated the sources: this is not independent human
adjudication or a blinded challenge. Paired representations are correlated. The
sample is purposive and limited to large US companies and annual reporting.

## Baseline, development fix, and final held-out results

| Measure | Development baseline | Development after fix | Frozen held out |
| --- | ---: | ---: | ---: |
| Documents | 4 | 4 | 6 |
| Selected target tables | 0/12 | 0/12 | 0/18 |
| Table recall | 0% | 0% | 0% |
| Table precision | N/A: 0 predictions | N/A: 0 predictions | N/A: 0 predictions |
| Mapped fact coverage | 0/96 (0%) | 0/96 (0%) | 0/144 (0%) |
| Numeric/period/unit/segment/mapping accuracy on mapped facts | N/A: 0 present | N/A: 0 present | N/A: 0 present |
| End-to-end joint fact accuracy, including missing | 0/96 (0%) | 0/96 (0%) | 0/144 (0%) |
| Completed financial calculations | 0 | 0 | 0 |
| Raw HTML numbers correct / present | 45/48 (93.75%) | 45/45 (100%) | 72/72 (100%) |
| Raw HTML numeric coverage | 48/48 (100%) | 45/48 (93.75%) | 72/72 (100%) |
| Raw HTML correct year labels / annotations | 48/48 | 48/48 | 54/72 (75%) |
| Processing seconds | 64.77 | 62.59 | 111.24 |

The raw-cell rows are **conditional diagnostics at annotated locations**, after
expanding every HTML table. They are not financial table-detection scores, full
fiscal-period accuracy, segment/unit accuracy or calculation coverage. The existing
inventory found 645 HTML tables across five documents; none was semantically
selected by the financial pipeline. No credit is awarded just for enumerating
HTML `<table>` elements. PDF page discovery scanned all 556 pages across five PDFs.

Table recall is scoped to the three selected table types/locations per document,
not all financial footnotes in a report. There were no predictions requiring
out-of-sample false-positive adjudication. Missing facts are failures in coverage
and end-to-end accuracy; zero present predictions are never called 100% accurate.
Calculation accuracy is not measured: no calculation answer key exists for these
issuers, and no supported calculation completed.

### Held-out results by format and table type

| Group | Targets missed / targets | Mapped facts missing / references | Coverage | Accuracy on present |
| --- | ---: | ---: | ---: | --- |
| HTML | 9/9 | 72/72 | 0% | N/A |
| Text PDF | 9/9 | 72/72 | 0% | N/A |
| Income statement | 6/6 | 54/54 | 0% | N/A |
| Segment note | 6/6 | 54/54 | 0% | N/A |
| Financial tax footnote | 6/6 | 36/36 | 0% | N/A |

All six per-field accuracy counts and denominators, missing IDs, source references,
original automatic cells, failures and fingerprints are in the ignored machine
reports. Manual-review results and corrections were never loaded.

| Document | Runtime (seconds) | Unclassified inventory / PDF pages | Outcome |
| --- | ---: | ---: | --- |
| Microsoft HTML, development final | 24.14 | 92 tables | Unsupported profile; three raw split-sign amounts withheld |
| Microsoft PDF, development final | 8.35 | 96 pages | No supported statement/segment detected |
| Alphabet HTML, development final | 13.40 | 184 tables | Unsupported profile |
| Alphabet PDF, development final | 16.70 | 110 pages | No supported tables; CID placeholders on 77 pages |
| Meta HTML, held out | 6.36 | 71 tables | Unsupported profile; 24/24 raw numeric/year labels correct |
| Meta PDF, held out | 20.13 | 134 pages | No supported tables |
| J&J HTML, held out | 32.28 | 236 tables | Unsupported profile; 24/24 raw numbers, 15/24 year labels |
| J&J PDF, held out | 17.79 | 140 pages | No supported tables |
| Costco HTML, held out | 3.71 | 62 tables | Unsupported profile; 24/24 raw numbers, 15/24 year labels |
| Costco PDF, held out | 30.98 | 76 pages | No supported tables |

Runtimes include local parsing, inventory and available detector calls, excluding
download, source annotation and rendering. Development/held-out jobs overlapped
briefly; these are measured workstation runtimes, not controlled speed benchmarks.

## Demonstrated failures and actual source examples

1. **Fixed using development only: incomplete negative signs.** Microsoft HTML tax
   table 60 splits a displayed closing parenthesis into the next physical cell.
   The old parser read `( 4,738`, `( 6,059`, `( 5,702` as positive values. The source
   reports deferred tax expenses of **-4,738, -6,059, -5,702 USD millions** for
   FY2024/2023/2022 (PDF page 73, printed 71). The reusable parser now rejects an
   incomplete sign and attaches `UNBALANCED_PARENTHESES`; original text remains.
   It also rejects mixed label/number strings instead of stripping their letters.
   Three errors became three explicit unresolved cells, not repaired gold values.
   Accepted numeric accuracy increased; total correct numeric coverage did not.
2. **Unresolved PDF encoding on development:** Alphabet PDF page 58 visibly reports
   revenue **282,836 / 307,394 / 350,018** for FY2022/2023/2024; its extracted text
   contains `(cid:...)` placeholders. The PDF is text-based, not a scanned document.
   The existing page `TEXT` heuristic can overstate usability because it counts
   characters; the evaluation explicitly reports CID pages. No font decoding or
   OCR repair was introduced. PDFminer also emitted non-stroke color warnings;
   rendered table pages remained readable.
3. **Unresolved new-issuer selection/mapping:** the HTML selector rejects all five
   unknown filing profiles; the segment adapter has only reviewed Walmart/Amazon
   configurations. The complete PDF adapter verifies Walmart FY2025 and its page
   detector uses Walmart heading/content evidence. These deliberate support
   boundaries cause missing tables/facts. Aliasing new documents as Walmart would
   create invalid periods and accounting mappings and was not used.
4. **Held-out hierarchical headers, no tuning:** J&J table 177/PDF page 99 reports
   Innovative Medicine sales **56,964 / 54,759 / 52,563** and MedTech sales
   **31,857 / 30,400 / 27,427**. The years have footnote markers and each spans
   segment columns. All nine annotated raw values survive, but their year labels
   are unresolved. Unallocated expenses **5,972 / 7,853 / 735** must remain a
   separate reconciliation category, not a segment's operating income. No fix
   was made using these held-out results.
5. **Held-out years in rows, no tuning:** Costco table 55/PDF page 66 has segment
   columns and repeated FY2024/2023/2022 row blocks. US revenue **184,143 / 176,630 /
   165,294** is readable, but all nine annotated segment cells lack a year label.
   FY2023 is 371 days; FY2024 and FY2022 are 364 days. A generic year match would
   not establish equal durations. No fix was made using these held-out results.
6. **Unsupported footnote semantics:** tax tables include current versus deferred
   expense, country categories and percentage rates. For example Alphabet's
   effective rates are **15.9%, 13.9%, 16.4%**, not USD amounts. J&J's tax provision
   relates to continuing operations, unlike total earnings including discontinued
   operations. No automatic accounting-definition equivalence is inferred.

The final held-out raw numeric diagnostic found **zero wrong values among 72
present cells**; it found **18 missing year labels**, not swapped years. This does
not test every number in the filings or establish reliable general extraction.

## Supported-capabilities matrix

| Layer | Existing demonstrated support | New sample evidence / limit |
| --- | --- | --- |
| HTML table inventory/merged cells | Enumerates DOM tables, retains original text/spans/source references | 645 tables enumerated; no semantic detection credit |
| Raw numeric parsing | Displayed amounts and balanced signs; incomplete signs held for review | 72/72 held-out sampled HTML numbers correct; conditional only |
| Financial statement selection/mapping | Reviewed Walmart annual/quarterly, Apple and Amazon profiles | 0/10 new statement targets selected; unknown profiles |
| Segment extraction/reconciliation | Reviewed Walmart/Amazon definitions/layouts | 0/10 new segment targets selected; column hierarchies/row years unsupported |
| Financial footnotes | No general canonical mapper/calculator | 0/10 tax-footnote targets selected |
| Complete periods, units and segment assignments | Supported profiles and resolved contexts only | 0/240 mapped facts across both final splits; raw year labels insufficient |
| Text PDF financial extraction | Walmart FY2025 statement and segment note | 0/15 new PDF targets; CID fonts additionally problematic |
| Financial calculations | Existing Decimal calculations on compatible, resolved mapped inputs | No new-issuer calculations; not inferred from raw coverage |
| Genuine scans | Not established by this evaluation | 0 documents / N/A accuracy and coverage |
| Simulated scans | Separate milestone 10 experiment | Excluded here; no transfer of simulated scores to genuine scans |

No suitable official image-only financial report was verified in the bounded source
search. Image-only covers/decorative pages inside otherwise text-based PDFs are not
counted as genuine scanned financial tables. Genuine and simulated scan coverage
are therefore reported separately. This is not a claim that no suitable public
scans exist.

## Commands, tests, and reproducibility

Exact extraction/evaluation commands run from the repository:

```powershell
$env:SEC_USER_AGENT = 'Your Name <your.name@example.com>'
$env:REQUESTS_CA_BUNDLE = (Resolve-Path data/processed/evaluation12a/windows-ca.pem).Path
.venv/Scripts/python scripts/prepare_evaluation12a.py
.venv/Scripts/python scripts/download_evaluation12a.py
.venv/Scripts/python scripts/compile_evaluation12a_references.py
.venv/Scripts/python -m sec_downloader.evaluation --split development --run-name baseline-development
# Apply the documented development-only parser fix; then:
.venv/Scripts/python -m sec_downloader.evaluation --split development --run-name final-development
.venv/Scripts/python -m sec_downloader.evaluation --freeze
.venv/Scripts/python -m sec_downloader.evaluation --split held_out --run-name final-held-out
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m sec_downloader.benchmark
.venv/Scripts/python -m sec_downloader.pdf_adapter
```

The declaration and freeze commands are intentionally one-time and refuse to
overwrite existing files. For repeat runs use the download and evaluation commands
in README. All source/reference hashes were unchanged across the held-out run.
Future tuning based on its failures requires new held-out documents.

- Full regression suite: **126 passed in 68.01 seconds**, including HTML annual,
  quarterly, segments, text PDF, OCR and review persistence/calculation tests.
- Existing HTML benchmark: **56/56 present, 100% accuracy and coverage**;
  15 existing XBRL exception entries remain.
- Existing text-PDF regression checks: **111/111 HTML comparisons match**;
  reference benchmark **39/45 covered**, with all present fields correct.
- Initial restricted-shell test run had a Windows pytest temporary-directory
  permission error; the full run with access to that directory passed.
- New tests cover split leakage, duplicate predictions, zero-output denominators,
  wrong value/period/unit/segment assignments, 52/53-week periods, raw-versus-semantic
  separation and the development-source split-sign regression.
- No new dependencies: Python 3.12.10, Beautiful Soup 4.15.0, pdfplumber 0.11.10,
  pdfminer.six 20260107, pypdfium2 5.13.0, Pillow 12.3.0, Requests 2.34.2,
  pytest 9.1.1. Versions also saved in the ignored environment.json.

Detailed generated reports are in `data/processed/evaluation12a/` under
`baseline-development`, `final-development` and `final-held-out`. Raw documents,
rendered source images, parsed cells and scores remain outside Git through the
existing ignore rules. The evaluation manifests/reference annotations and this
authored analysis are intended project artifacts.

## Files changed for milestone 12A

- Added `src/sec_downloader/evaluation.py`: collector, frozen-run checks, separate
  table/fact/raw-cell scoring, per-format/type reports and runtime/failure records.
- Changed `src/sec_downloader/extractor.py`: conservative numeric grammar and
  explicit incomplete-parenthesis review flag.
- Added `evaluation/manifest.json`, `reference_rows.json`, `references.json`,
  `freeze.json`, `PROTOCOL.md`, and this authored `REPORT.md`.
- Added `scripts/prepare_evaluation12a.py`, `download_evaluation12a.py`,
  `compile_evaluation12a_references.py`, and `tests/test_evaluation.py`.
- Updated `README.md` and `SUPPORTED_FORMATS.md`.

Pre-existing uncommitted milestone files were retained. Nothing was committed or
deployed. Remaining work is issuer/calendar/mapping and layout generalization,
font-encoding handling, more diverse independent filings, genuine-scan sourcing
and external annotation review; these are not represented as completed support.
