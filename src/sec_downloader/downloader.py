from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import requests

from .manifest import load_manifest, save_manifest

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
RAW_DIR = DATA_DIR / "raw"


def compute_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    file_path = Path(path)

    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)

    return digest.hexdigest()


def verify_cached_file(path: str | Path, expected_sha256: str | None) -> bool:
    file_path = Path(path)
    if not file_path.exists() or expected_sha256 is None:
        return False

    return compute_sha256(file_path) == expected_sha256


def should_download_document(document: dict[str, Any], raw_dir: str | Path) -> bool:
    cache_path = Path(raw_dir) / document["filename"]
    if not cache_path.exists():
        return True

    expected_sha256 = document.get("sha256")
    if expected_sha256 is None:
        print(f"Checksum missing for {document['filename']}; re-downloading.")
        return True

    if verify_cached_file(cache_path, expected_sha256):
        print(f"Using cached file: {cache_path}")
        return False

    print(
        "Checksum mismatch for "
        f"{document['filename']}: expected {expected_sha256}, "
        f"found {compute_sha256(cache_path)}. Re-downloading."
    )
    return True


def _get_sec_user_agent() -> str:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent or not user_agent.strip():
        raise RuntimeError(
            "SEC_USER_AGENT is not set. Example PowerShell command: "
            "$env:SEC_USER_AGENT = 'Your Name <your.name@example.com>'"
        )
    return user_agent.strip()


def download_document(document: dict[str, Any], raw_dir: str | Path = RAW_DIR) -> dict[str, Any]:
    cache_dir = Path(raw_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    target_path = cache_dir / document["filename"]
    response = requests.get(
        document["source_url"],
        headers={
            "User-Agent": _get_sec_user_agent(),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30,
    )
    response.raise_for_status()

    target_path.write_bytes(response.content)
    document["sha256"] = compute_sha256(target_path)
    print(f"Downloaded {document['filename']} -> {document['sha256']}")
    manifest = load_manifest(MANIFEST_PATH)
    for manifest_document in manifest["documents"]:
        if manifest_document["id"] == document["id"]:
            manifest_document["sha256"] = document["sha256"]
            break
    save_manifest(manifest, MANIFEST_PATH)
    return document


def run_downloads(manifest_path: str | Path = MANIFEST_PATH, raw_dir: str | Path = RAW_DIR) -> None:
    manifest = load_manifest(manifest_path)
    for document in manifest["documents"]:
        if should_download_document(document, raw_dir):
            download_document(document, raw_dir)


def main() -> int:
    try:
        run_downloads()
    except requests.RequestException as exc:
        raise SystemExit(f"SEC download failed: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    return 0
