# Third-party software and source data

The project license is undecided; see [LICENSE_DECISION.md](LICENSE_DECISION.md).
Dependency licenses do not license this project's code. No third-party binaries,
filing pages, downloaded PDF files or model weights are proposed for the GitHub
source release. Installing dependencies downloads their separately licensed packages.

## Software

The version-pinned dependency list is in `requirements/`. The companion
[dependency inventory](docs/DEPENDENCIES.md) records installed package metadata for
base, UI, tests, build tools and optional OCR. Metadata is an inventory, not a
replacement for each distribution's actual LICENSE/NOTICE files.

| Components | Declared upstream terms / notices |
| --- | --- |
| Beautiful Soup, pdfplumber, pdfminer.six | MIT |
| Requests | Apache-2.0 |
| Flask / Werkzeug / Jinja2 / MarkupSafe | BSD-3-Clause |
| Waitress | ZPL-2.1 |
| Pillow | MIT-CMU and bundled third-party notices |
| pypdfium2 / PDFium | BSD-3-Clause / Apache-2.0 plus PDFium dependency notices |
| RapidOCR | Apache-2.0; check bundled model provenance separately |
| ONNX Runtime | MIT plus bundled dependency notices |
| OpenCV Python | Apache-2.0 plus `LICENSE-3RD-PARTY.txt` |
| NumPy | Multiple terms listed in wheel metadata and bundled LICENSE files |
| ReportLab | BSD terms plus bundled font notices (including Bitstream Vera) |

Retain applicable copyright, license and NOTICE files when redistributing dependencies.
Native wheels can include additional libraries beyond the Python package's main
license. In particular, inspect PDFium, OpenCV, ONNX Runtime, NumPy and font notices
before preparing any bundled binary distribution. This preparation only builds
the project's own wheel; it does not vendor those libraries.

Optional RapidOCR 1.4.4 contains `ch_PP-OCRv4_det_infer.onnx`,
`ch_PP-OCRv4_rec_infer.onnx`, and `ch_ppocr_mobile_v2.0_cls_infer.onnx` in its installed
package. They are not committed or included in default CI. Upstream
[RapidOCR license](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE) and
[PaddleOCR license](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)
provide the Apache-2.0 project terms; redistribution of specific model artifacts
still requires checking their corresponding release/provenance and notices.
No independent model training-data rights audit was performed here.

## Documents, annotations and fixtures

- SEC documents are referenced by official URL, form, issuer, filename and SHA-256
  in `data/manifest.json`, `demo/real-manifest.json`, and `evaluation/manifest.json`.
  The [SEC webmaster FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)
  states that government-created content and EDGAR public filing content are free
  to access and reuse. Preserve provenance; SEC hosting is not endorsement.
- Investor-relations PDFs for Meta, Johnson & Johnson and Costco remain external
  source materials. No blanket reuse license was verified for those company-hosted
  reports. Download them locally for evaluation; do not bundle or assume rights to
  reproduce full reports, artwork or logos in a release.
- `evaluation/references.json`, `reference_rows.json` and `tests/fixtures/*facts.json`
  contain selected numerical facts, short labels and source coordinates, not full
  reports. Original annotation work remains subject to the project's license decision.
- `demo/statement.html` and inline synthetic test tables/word geometry are original
  minimal fixtures, with no copied issuer pages or weights. They are suitable for
  an offline source release once the owner selects the project's terms.
- Simulated scans are derived from a real PDF and remain ignored generated outputs;
  they are neither original synthetic text fixtures nor genuine scanner evidence.

## Access obligations

Supply an identifying SEC User-Agent and follow
[SEC fair-access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions).
The SEC currently limits automated access to 10 requests/second. The single-document
demo makes one download request; do not launch concurrent bulk jobs that exceed the
limit. TLS verification remains enabled. URLs and permissions can change, so source
retrieval may fail; such failure does not authorize bypassing access controls.
