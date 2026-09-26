# SEC Filing Download Milestone

This project downloads two SEC 10-K HTML filings into `data/raw/` and records their SHA-256 checksums in `data/manifest.json`.

## PowerShell setup

Set your SEC user agent to an identifying value with your own name and email before downloading:

```powershell
$env:SEC_USER_AGENT = "Your Name <your.name@example.com>"
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install requests pytest
```

Replace the example value with your real name and email. Keep that value only in your local environment; do not commit it to Git.

## Run the downloader

```powershell
python -m sec_downloader
```

## Run tests

```powershell
pytest -q
```

## Inventory cached filing tables

After the SEC HTML files are cached locally, you can inspect the table inventory from the repo root:

```powershell
python -m sec_downloader.inventory
```

This reads the verified local files in `data/raw/`, inventories each HTML table, records its nearest heading or caption, row and column counts, preview text, and source reference, and identifies the consolidated income statement in each filing.

The downloader reuses a valid cached file when the manifest checksum matches the file on disk. If the file is present but the checksum does not match, it reports the mismatch and downloads a fresh copy instead of silently trusting the stale cache.
