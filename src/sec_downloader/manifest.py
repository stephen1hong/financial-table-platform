from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest at {manifest_path} must contain a JSON object.")

    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError(f"Manifest at {manifest_path} does not contain a non-empty documents list.")

    return manifest


def save_manifest(manifest: dict[str, Any], path: str | Path) -> None:
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
