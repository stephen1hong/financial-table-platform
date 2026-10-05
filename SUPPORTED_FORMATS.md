# Supported financial-table formats

| Input | Supported scope | Routing | Review limitations |
| --- | --- | --- | --- |
| SEC HTML | Walmart FY2025 annual, Walmart October 2025 three/nine-month 10-Q, Apple FY2025 annual, Amazon FY2025 annual | Existing table selection, mapping, calculation and Inline XBRL adapters | Other layouts/profiles require implementation and independent verification |
| Text-based PDF | Walmart FY2025 annual report; consolidated income statement and hierarchical segment note | Milestone 9 geometric adapter, without OCR | Full report/cover verification required; no general arbitrary-issuer PDF support |
| Image-only PDF | Walmart annual income/segment layouts exercised by FY2025 simulated scans | Local RapidOCR ONNX CPU → geometric table adapter → shared mappings/calculations | Low-resolution text, damaged signs, footnotes and uncertain labels may be unresolved; no guarantee for real-world scans |
| Table image | PNG/JPEG image of those Walmart tables, via `ocr_adapter` CLI | Same OCR path; caller supplies image DPI and fiscal year | Web upload currently accepts HTML/PDF; no automatic issuer or fiscal-calendar inference |
| Mixed PDF | Text path is selected if a text layer exists | Existing text PDF adapter | It does not selectively OCR scanned financial pages inside an otherwise textual report; split image-only pages first |

The local review app binds to `127.0.0.1`. It is a single-user workstation tool,
not a deployed or authenticated multi-user service. Files up to 50 MB are accepted.
Company/fiscal profiles are explicit. The partially started Amazon PDF experiment
is not advertised as supported. No additional general-purpose extraction work is
included in milestones 10/11.

OCR retains original text, detection polygons, confidence, parsed readings and
review reasons. Case-only matching to already reviewed row/segment labels is
recorded explicitly. It does not replace digits/letters, infer missing signs,
repair decimals from accounting totals, or use gold values to fill cells.
Confidence is a heuristic gate, not a calibrated probability. A confidently
misread complete number/sign can remain undetected; accounting accuracy requires
source review. Small geometric skew is estimated from OCR boxes; full orientation,
perspective distortion, handwriting and multi-page OCR table stitching are not
supported. Original OCR footnotes are retained even when their marker is wrong;
their semantic linkage is not guaranteed.

Automatic snapshots and reviewed values are separate. Corrections are appended
with old/new values, reason, UTC timestamp and approval state, then replayed to
derive reviewed results. An unresolved OCR period, unit or mapping requires its
own review; changing a number alone does not approve those fields. Calculations
reject unresolved inputs and incompatible dates/units. Fact comparison also
requires matching metric, accounting definition and segment context; cross-company
definitions are conservatively distinct. Corrections do not rerun XBRL validation
or reconciliation checks: original exceptions remain visible as source evidence.
Benchmarks only read automatic adapter output, never the review database.

## Broader evaluation boundaries (milestone 12A)

The new evaluation sample is **not a new supported-issuer list**. It contains five
new filing groups in ten HTML/PDF documents, including healthcare. See
[evaluation/REPORT.md](evaluation/REPORT.md) for measured denominators and
[evaluation/PROTOCOL.md](evaluation/PROTOCOL.md) for the holdout rules.

| Capability | Evidence and remaining limit |
| --- | --- |
| Raw HTML cell expansion | Can inventory/expand tables from new issuers; this does not infer accounting definitions, complete fiscal periods, currency or segments |
| Incomplete numeric signs | A development-source fix withholds unbalanced parentheses and flags the original cell; it does not infer a sign or join neighboring cells |
| New-issuer financial selection and mappings | No reviewed profiles for Microsoft, Alphabet, Meta, J&J or Costco; missing facts remain missing |
| Segment layouts with years in rows or two-level column headings | Included as difficult cases; existing financial pipeline does not support them for these issuers |
| Tax-footnote tables | Source annotations exist; no canonical extraction/calculation adapter is advertised |
| Text PDFs from additional issuers | Existing detector and complete adapter are Walmart-specific; a readable page is not a supported financial table |
| CID-encoded PDF fonts | Alphabet's tables render correctly but text extraction returns CID placeholders; not treated as successful text extraction or a genuine scan |
| Financial calculations | Continue to require supported mappings and compatible resolved inputs; raw-cell diagnostic accuracy grants no calculation credit |
| Genuine scanned documents | Zero verified official-source examples in this sample; no new real-scan support claim |

The evidence does not establish support for most financial tables. Paired
representations are correlated, and this is a purposive US annual-report sample,
not a population-wide estimate.
