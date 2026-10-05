from pathlib import Path

from sec_downloader.manifest import load_manifest


def test_manifest_has_expected_documents():
    manifest = load_manifest(Path("data/manifest.json"))

    document_ids = [doc["id"] for doc in manifest["documents"]]
    assert document_ids == ["wmt-2025", "aapl-2025", "wmt-2026-q3", "amzn-2025"]

    for doc in manifest["documents"]:
        assert doc["source_url"].startswith("https://www.sec.gov/")
        assert doc["filename"].endswith(".htm")
        assert doc["company"]
        assert doc["form"]


def test_manifest_references_expected_files():
    manifest = load_manifest(Path("data/manifest.json"))

    filenames = {doc["filename"] for doc in manifest["documents"]}
    assert filenames == {"wmt-20250131.htm", "aapl-20250927.htm", "wmt-20251031.htm", "amzn-20251231.htm"}


def test_pdf_manifest_has_official_source_checksum_and_matching_fiscal_year():
    manifest = load_manifest(Path("data/manifest.json"))
    pdf = manifest['pdf_documents'][0]
    html = next(d for d in manifest['documents'] if d['id'] == pdf['html_document_id'])
    assert pdf['format'] == 'pdf' and pdf['filename'].endswith('.pdf')
    assert pdf['company'] == html['company'] and pdf['fiscal_year'] == html['fiscal_year']
    assert pdf['period_end'] == pdf['verification']['fiscal_period_end'] == '2025-01-31'
    assert pdf['source_url'].startswith('https://www.sec.gov/Archives/')
    assert len(pdf['sha256']) == 64
