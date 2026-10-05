# Reproducible demo walkthrough

Use the pinned editable installation in the README and run from the repository
root. The small synthetic demo works without SEC access or OCR models.

1. Run `python scripts/offline_demo.py`. It verifies `demo/statement.html` against
   `demo/manifest.json`, parses three values (100, 60, 20), applies explicitly
   supplied fixture metadata, and checks `demo/expected.json`.
2. Expected summary: gross profit **40 USD millions**, gross margin **40%**,
   operating margin **20%**. Outputs are `data/processed/demo/summary.json`,
   `automatic.json`, and `reviews.sqlite3`. IDs/timestamps vary; summary values do
   not. Each invocation adds a new demo document to the local database.
3. Run `python -m sec_downloader.review_app --data-dir data/processed/demo`.
   Open <http://127.0.0.1:8765> and select the synthetic document. Review facts,
   calculations and exports. Change net sales from 100 to 120 with a reason:
   reviewed gross profit becomes 60, while the automatic value remains 40.
   Reload to check persistence. Stop the server with Ctrl+C.

The demo deliberately supplies period/unit/metric metadata. It demonstrates
parsing, calculation and review plumbing, not general issuer detection. Its tiny
HTML fixture is original project content with no external document material;
project licensing remains an owner decision.

## One real filing (optional download)

```powershell
$env:SEC_USER_AGENT = 'Your Name <your.name@example.com>'
python scripts/real_demo.py --download
```

This downloads only the Walmart FY2025 HTML 10-K named in
[`demo/real-manifest.json`](../demo/real-manifest.json), keeps the source and output
under `data/processed/real-demo/`, checks its reviewed SHA-256, and compares the
calculated output to [`demo/real-expected.json`](../demo/real-expected.json).
Expected gross profit is **162,785 USD millions** from sales **674,538** less cost
**511,753**. Gross margin is approximately **24.13%**; operating margin approximately
**4.31%**, using Walmart's total-revenues denominator. Full Decimal expectations
are stored in JSON. The output `report.json` includes facts, source locations,
periods, calculations and reconciliation. Repeat without `--download` to use cache.

The source checksum is never silently updated in the release manifest. HTTP 403,
TLS failures and changed source bytes fail explicitly. Use an approved CA bundle
through `REQUESTS_CA_BUNDLE` if needed; do not disable verification. Downloads
require internet and SEC fair-access identification; they are not CI steps.

For all supported regression sources run `python -m sec_downloader`, then
`python -m pytest -m real_data -q`. For the frozen broader evaluation follow
[the 12A protocol](../evaluation/PROTOCOL.md) and README; it is expected to show
zero held-out financial-table/fact coverage.
