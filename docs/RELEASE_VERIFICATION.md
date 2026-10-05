# Milestone 12B release verification

Prepared locally on 2026-10-05. No commit, tag, push, history rewrite or GitHub release
was performed. The release candidate remains a working-tree proposal for review.

## Clean installation and startup

`scripts/verify_release.py` clones the existing local HEAD into a newly created OS
temporary directory, removes only that clone's tracked working files, and overlays
the exact proposed working-tree file set. This is necessary because the milestone
implementation is not committed. It creates a fresh Python environment without
system site packages; no original `.venv`, raw cache, outputs or model weights are
copied. Dependency acquisition uses pip; a pre-existing pip wheel cache may be reused.

Validated locally on Windows x64 / CPython 3.12.10:

| Check | Result |
| --- | --- |
| Fresh venv and pinned dependency installation | Passed |
| Source distribution and wheel build | Passed |
| Wheel install, imports, template and JavaScript resources | Passed |
| Supported editable repository installation | Passed |
| `pip check` | Passed |
| Clean default offline test suite | 88 passed; 1 OCR module skipped; 29 real-data cases deselected |
| Synthetic demo and checked expected summary | Passed: 40, 40%, 20% |
| UI process startup over real localhost HTTP | Passed: index, catalog, document list, JavaScript |
| CLI argument/help startup | Passed |
| Original 12A source/reference freeze | 28 files match |
| Existing-workspace full suite with cached documents and OCR packages | 127 passed in 57.12 seconds |
| Updated demo correction/source-display integration test | Passed |
| Headless Chrome demo rendering | Passed, no JavaScript errors; source table and review dialog available |
| Single real-document demo against existing checksum-verified cache | Passed; gross profit 162785, margins matching stored Decimal expectations |

The full suite ran with `python -m pytest -q -o addopts= -p no:cacheprovider`.
No network is allowed by the autouse test fixture. Cached real-data tests do not
redownload sources. OCR tests exercise logic with existing dependencies; these are
not a fresh-model download or complete OCR accuracy rerun.

The Windows/Linux GitHub Actions matrix is prepared but **has not run on GitHub**.
Linux execution, fresh OCR installation/model inference, and fresh SEC retrieval
were not verified during 12B. Live access failures remain possible. The existing
12A reports were inspected, not rerun or relabeled as new results.

## Failures and limits retained honestly

- Initial sandboxed venv creation and pytest temporary directories failed with
  Windows access errors. The fresh-clone and full-suite runs succeeded with the
  needed filesystem access. No production permissions were changed.
- An initial PowerShell invocation with an empty `-m` argument failed argument
  parsing. The documented `-o addopts=` command avoids this shell behavior.
- The synthetic demo's first expected-string assertion exposed Decimal formatting
  differences. Summary serialization now normalizes Decimal text; values are unchanged.
- Code review found the UI requires a source table in the demo snapshot. The demo
  now includes its original synthetic table/cells; browser verification passed.
- A standalone installed wheel does not supply repository-relative manifests to
  every adapter. The supported install is an editable checkout. Wheel import/resource
  checks pass, but no standalone-wheel full CLI/catalog support is claimed.
- Locks pin all dependency versions, not binary hashes. Upstream index availability,
  Python/OS wheels and external documents remain reproducibility dependencies.
- No project license was chosen. Owner selection is required before publication;
  see `LICENSE_DECISION.md`. No second-party annotation or model-data rights audit
  is implied by these checks.

## Repository and history audit

`scripts/audit_release.py` scans tracked working files plus proposed release files,
and every blob reachable through all local refs and reflogs. The initial scan
covered **83 historical blobs**, including local Codex snapshot refs, beyond the
single `main` commit (`81bb332`). It checks credential patterns, email addresses,
personal paths, suspicious file types/directories and oversized blobs. Only rule
names, paths and counts are written; credential values are never printed.

Findings and disposition:

- A personal contact email appeared in current README/evaluation command examples
  and in earlier local snapshot-ref copies. Current examples now use `example.com`.
  Those historical snapshot objects were not altered. Ordinary Git author/committer
  metadata also contains a personal email identity and remains unchanged.
- Five generated `src/sec_filing_downloader.egg-info/*` files were tracked in main.
  Their local deletion is proposed, with an ignore rule preventing future additions.
  They remain in history. `.gitignore` does not retroactively untrack them; review
  their proposed deletions with the rest of the eventual commit.
- No actual credential-token/private-key matches, downloaded filing pages/PDFs,
  databases, model weights, or personal editor configuration were found in the
  scanned historical blobs or proposed release files. Expected example addresses
  and audit regex literals were reviewed as non-secret content.
- Existing raw/processed caches, local CA bundle, virtual environments and generated
  review databases remain local and excluded. The pre-existing exploratory notebook
  is preserved locally but excluded from the explicit proposed release set (three
  cells, no saved outputs). No local data was deleted to make the audit pass.

This is a heuristic content/path audit, not a guarantee that every possible secret
is absent. It does not inspect remote refs that are not present locally, unreachable
objects outside all refs/reflogs, or credentials stored outside this repository.
No remote is configured and no external publication state was inspected.

## Exact proposed files and review workflow

[`RELEASE_FILES.txt`](RELEASE_FILES.txt) lists the proposed source set. The exporter
uses an explicit root-file/directory allowlist, rejects unexpected private/generated
file extensions and files over 2 MB, and excludes ignored files. A fresh export:

```powershell
python scripts/audit_release.py
python scripts/export_release.py --output release-artifacts/v0.1.0-source
python scripts/verify_release.py
git diff --check
git status --short
```

The export command refuses to overwrite an existing directory; select a new name
for later candidates. Its adjacent `*-files.json` records every exported path,
byte length and SHA-256. The exact final candidate and local verification logs are
under ignored `release-artifacts/`. No generated database, model or downloaded
filing is included. Original-source freeze checks and `.gitattributes` protect
historically mixed line endings without re-freezing the held-out set.

Ignore checks cover raw/processed data, environments, build/dist, `.egg-info`,
databases, credentials/CA keys, editor config and model weights. Review the five
tracked metadata deletions; do not use a blanket `git add .` that would accidentally
include the excluded notebook. Owner license selection, review/staging of this
exact set, and eventual hosted CI are still publication gates.

Use [DEMO.md](DEMO.md) for the concise walkthrough and
[draft release notes](RELEASE_NOTES_v0.1.0.md) for the measured capability claims.
