# v0.1.0 release notes — draft, unpublished

An initial research/development release for extracting and reviewing selected SEC
financial statements with source references. It includes HTML and limited text-PDF
adapters, period/unit checks, financial calculations, inline-XBRL comparisons and
a localhost review UI with separate automatic and corrected views.

## Measured scope

The 12A sample is ten HTML/PDF representations of five FY2024 filing groups, not
ten independent filings. Microsoft/Alphabet were development; Meta/J&J/Costco were
held out. The held-out financial pipeline selected **0/18 tables**, mapped **0/144
facts**, and completed **zero calculations**. Accuracy on present mapped facts is
undefined. Raw HTML cells at annotated locations had 72/72 correct sampled numbers
and 54/72 correct year labels; this does not establish semantic extraction support.

Existing curated HTML benchmark: 56/56 covered. Existing text-PDF benchmark: 39/45
covered, all present fields correct, and 111/111 HTML comparisons match. These are
development regressions, not broad generalization evidence. See
[12A report](../evaluation/REPORT.md) and [supported formats](../SUPPORTED_FORMATS.md).

## Install and demonstrate

Use Python 3.12 x64 and the repository-root instructions in [README](../README.md).
Run the [offline demo](DEMO.md) first; live downloads and OCR are optional and are
excluded from default CI. This release is a repository-oriented application: the
source manifests and demo files must remain available beside the installed package.

## Limitations and release gates

- General new-issuer selection, arbitrary footnotes, PDF font decoding, and genuine
  scans are not supported by the measured evaluation.
- UI is a local single-user tool, not an authenticated hosted service.
- Project license remains undecided; no open-source licensing claim is made.
- See [release verification](RELEASE_VERIFICATION.md) for actual checks and failures.
- No commits, tags, push, or GitHub publication are performed by this preparation.
