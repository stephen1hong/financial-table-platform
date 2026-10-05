from pathlib import Path

from sec_downloader.downloader import compute_sha256, should_download_document, verify_cached_file


def test_sha256_is_stable_for_sample_text(tmp_path):
    sample_path = tmp_path / "sample.htm"
    sample_path.write_text("Walmart and Apple", encoding="utf-8")

    digest = compute_sha256(sample_path)
    assert len(digest) == 64
    assert digest == "f0a932ff69a72ef5e87e092bc749f81ab2f8c506a602f36c4c008b01c335fc65"


def test_cached_file_is_valid_when_hash_matches(tmp_path):
    cache_path = tmp_path / "sample.htm"
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


def test_download_10q_uses_configured_agent_updates_supplied_manifest_and_reuses_cache(tmp_path, monkeypatch):
    import json
    from sec_downloader.downloader import run_downloads
    from sec_downloader.manifest import load_manifest
    from unittest.mock import Mock

    document = {"id": "wmt-2026-q3", "filename": "wmt-20251031.htm", "sha256": None,
                "source_url": "https://www.sec.gov/Archives/edgar/data/104169/000010416925000191/wmt-20251031.htm"}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [document]}), encoding="utf-8")
    monkeypatch.setenv("SEC_USER_AGENT", "Test Downloader tests@example.com")
    response = Mock(content=b"<html><body>cached fixture</body></html>")
    get = Mock(return_value=response)
    monkeypatch.setattr("sec_downloader.downloader.requests.get", get)
    raw = tmp_path / "raw"
    run_downloads(manifest, raw)
    get.assert_called_once()
    assert get.call_args.kwargs["headers"]["User-Agent"] == "Test Downloader tests@example.com"
    assert get.call_args.args[0] == document["source_url"]
    stored = load_manifest(manifest)["documents"][0]
    assert stored["sha256"] == compute_sha256(raw / document["filename"])
    assert "tests@example.com" not in manifest.read_text()
    run_downloads(manifest, raw)
    assert get.call_count == 1


def test_download_http_failure_does_not_cache_response_or_change_checksum(tmp_path, monkeypatch):
    import requests
    from unittest.mock import Mock
    import pytest
    from sec_downloader.downloader import download_document

    monkeypatch.setenv("SEC_USER_AGENT", "Test Downloader tests@example.com")
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("403")
    monkeypatch.setattr("sec_downloader.downloader.requests.get", Mock(return_value=response))
    document = {"filename": "wmt-20251031.htm", "source_url": "https://www.sec.gov/fixture", "sha256": None}
    with pytest.raises(requests.HTTPError):
        download_document(document, tmp_path)
    assert not (tmp_path / document["filename"]).exists()
    assert document["sha256"] is None


def test_pdf_download_manifest_checksum_cache_and_content_guard(tmp_path, monkeypatch):
    import json
    from unittest.mock import Mock
    import pytest
    from sec_downloader.downloader import run_downloads, download_document
    monkeypatch.setenv("SEC_USER_AGENT", "Test Downloader tests@example.com")
    html = tmp_path / "existing.htm"
    html.write_text("cached")
    pdf = {"id": "pdf", "format": "pdf", "filename": "annual.pdf", "sha256": None,
           "source_url": "https://www.sec.gov/annual.pdf"}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [{"id": "html", "filename": html.name,
        "sha256": compute_sha256(html)}], "pdf_documents": [pdf]}))
    response = Mock(content=b"%PDF-1.7\nfixture")
    get = Mock(return_value=response)
    monkeypatch.setattr("sec_downloader.downloader.requests.get", get)
    run_downloads(manifest, tmp_path)
    assert get.call_args.kwargs['headers']['Accept'] == 'application/pdf'
    assert get.call_args.kwargs['headers']['User-Agent'] == 'Test Downloader tests@example.com'
    assert json.loads(manifest.read_text())['pdf_documents'][0]['sha256'] == compute_sha256(tmp_path/'annual.pdf')
    run_downloads(manifest, tmp_path)
    assert get.call_count == 1
    response.content = b'<html>Access denied</html>'
    before = (tmp_path/'annual.pdf').read_bytes()
    with pytest.raises(RuntimeError, match='not a PDF'):
        download_document(pdf, tmp_path, manifest)
    assert (tmp_path/'annual.pdf').read_bytes() == before
