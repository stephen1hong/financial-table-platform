from pathlib import Path

from sec_downloader.manifest import load_manifest


def test_manifest_has_expected_documents():
    manifest = load_manifest(Path("data/manifest.json"))

    document_ids = [doc["id"] for doc in manifest["documents"]]
    assert document_ids == ["wmt-2025", "aapl-2025"]

    for doc in manifest["documents"]:
        assert doc["source_url"].startswith("https://www.sec.gov/")
        assert doc["filename"].endswith(".htm")
        assert doc["company"]
        assert doc["form"]


def test_manifest_references_expected_files():
    manifest = load_manifest(Path("data/manifest.json"))

    filenames = {doc["filename"] for doc in manifest["documents"]}
    assert filenames == {"wmt-20250131.htm", "aapl-20250927.htm"}
