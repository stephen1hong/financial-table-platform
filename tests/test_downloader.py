from pathlib import Path

from sec_downloader.downloader import compute_sha256, should_download_document, verify_cached_file


def test_sha256_is_stable_for_sample_text(tmp_path):
    sample_path = tmp_path / "sample.htm"
    sample_path.write_text("Walmart and Apple", encoding="utf-8")

    digest = compute_sha256(sample_path)
    assert len(digest) == 64
    assert digest == "f0a932ff69a72ef5e87e092bc749f81ab2f8c506a602f36c4c008b01c335fc65"


def test_cached_file_is_valid_when_hash_matches():
    cache_path = Path("data/raw/sample.htm")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("Walmart and Apple", encoding="utf-8")

    assert verify_cached_file(cache_path, "f0a932ff69a72ef5e87e092bc749f81ab2f8c506a602f36c4c008b01c335fc65") is True
    assert verify_cached_file(cache_path, "00" * 32) is False

    cache_path.unlink(missing_ok=True)


def test_should_download_document_reuses_valid_cache(tmp_path):
    cache_path = tmp_path / "cached.htm"
    cache_path.write_text("Walmart and Apple", encoding="utf-8")

    document = {
        "id": "wmt-2025",
        "filename": "cached.htm",
        "sha256": "f0a932ff69a72ef5e87e092bc749f81ab2f8c506a602f36c4c008b01c335fc65",
    }

    assert should_download_document(document, tmp_path) is False
