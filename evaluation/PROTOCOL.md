# Milestone 12A evaluation protocol

The sample was declared on 2026-10-01 before calling the extraction pipeline.
`manifest.json` records ten additional official documents from five new companies:
Microsoft, Alphabet, Meta Platforms, Johnson & Johnson (healthcare), and Costco.
They are HTML/PDF pairs of five FY2024 filings, **not ten independent filings**.
Downloads use the existing SEC User-Agent, SHA-256 verification and ignored raw
cache. Alphabet's company PDF returned HTTP 403; the same annual-report group
was acquired from its official SEC ARS submission before extraction. That source
attempt remains recorded. No failed extraction is replaced with an easier filing.

## Split and contamination rules

- Development: both representations of Microsoft and Alphabet FY2024.
- Held out: both representations of Meta, Johnson & Johnson and Costco FY2024.
- All representations of a filing stay together. The split also separates issuers.
- Source inspection and annotation are permitted before evaluation. They do not
  feed the extraction code. This is an operational holdout, not a blinded or
  externally administered challenge: the implementing agent also annotated it.
- Development baseline runs precede fixes. Final code, manifest and reference
  hashes are frozen in `freeze.json` before held-out extraction. The runner checks
  hashes before and after processing. No parser/profile change is made from
  held-out errors. Any future such change makes these documents development data;
  a fresh issuer/filing sample is then required for another held-out claim.

## Reference construction

`reference_rows.json` contains manually transcribed literal values and metadata,
read from original HTML DOM tables, not extractor predictions. All 15 selected
PDF table pages were rendered and visually compared, including Alphabet's broken
text encoding. `scripts/compile_evaluation12a_references.py` only attaches original
DOM coordinates and checks those literals against source text. It imports no
`sec_downloader` code. It does not obtain expected numbers from automatic output.
The resulting `references.json` has 120 distinct facts and 240 representation
annotations: 48 distinct development facts and 72 distinct held-out facts.

Each filing contributes 24 distinct facts: nine consolidated statement facts,
nine segment/reconciling-item facts, and six income-tax-footnote facts, covering
FY2022, FY2023 and FY2024. Each is independently located in both representations.
References include original labels, metric, segment, displayed unit, exact fiscal
dates, day duration, fiscal year, source URL/checksum and DOM or PDF page/row/year
locations. Monetary values are displayed USD millions; Alphabet tax rates are
percentages. Costco's 53-week FY2023 and J&J's FY2022 ending in January 2023 are
retained. Dates are checked against original duration contexts and period notes.
One annotator checked two representations; no claim of second-human adjudication.

## Denominators and scope

1. **Selected financial-table detection:** three pre-annotated target tables per
   document (statement, segment operating-results note, tax footnote). TP requires
   matching document, type, and source table/page. Recall is TP / target count;
   precision is TP / predictions, undefined for zero predictions. This is scoped
   target recall, not recall over every table/footnote in an annual report. New
   predictions outside these targets require adjudication before interpreting
   them as false positives. The current run makes no such predictions.
2. **Automatic mapped facts:** source coordinates locate predictions, never gold
   values, expected periods or segments. Numeric, full-period, unit, segment,
   mapping and joint accuracies use present unambiguous predictions as denominator.
   Coverage is present / annotated facts. Missing/ambiguous facts remain in the
   denominator of end-to-end joint accuracy. Zero predictions mean N/A accuracy,
   not 100% accuracy. Duplicate predictions are ambiguous, never cherry-picked.
3. **Raw HTML diagnostic:** all HTML tables pass through existing merged-cell
   expansion without reference locations. Scoring afterwards inspects annotated
   cells. This conditional diagnostic measures numeric parsing and year labels;
   it is not semantic table detection, full-period inference, unit/segment accuracy,
   or financial fact/calculation coverage. Unclassified inventory counts receive
   no financial-detection credit. PDF discovery uses the existing page detector.
4. **Calculations:** count actual completed automatic financial calculations
   separately. No generic gross profit/ratio is inferred for unsupported issuers.
   No calculation reference set exists for new issuers, so calculation accuracy
   is not measured. Availability can be zero despite visible raw numeric cells.
5. Report by split, format, table type and document, with runtimes, all missing
   fact IDs, unresolved/unsupported stages and representative wrong values.

The collector receives only manifest documents, never reference annotations.
Benchmarks do not read the review database or manual corrections. There is no
gold-assisted issuer aliasing, table selection, missing-value repair, mapping or
calculation. Unsupported profile errors are retained, not converted to success.

## Scans and representativeness

No suitable genuine image-only financial report from an official source was
verified in the bounded source search. Historical library/archive scan results
were outside the chosen official SEC/company sample and were not silently added.
Genuine-scan coverage is **0 documents, not evaluated**. Milestone 10 simulated
scans are excluded here and retain their separately reported results. Alphabet's
CID-encoded text is a text-PDF failure, not a genuine scan.

This purposive US large-issuer annual sample does not cover IFRS, other currencies,
small issuers, arbitrary quarterly formats, handwritten tables or representative
real scanner noise. Correlated HTML/PDF pairs are not independent observations.
Neither raw-cell accuracy nor the existing curated benchmark establishes support
for most financial tables.
