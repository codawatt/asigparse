"""Registry of the synthetic demo documents in backend/samples."""

from __future__ import annotations

import json
from pathlib import Path

from .config import settings


def _load_manifest() -> dict:
    path = settings.samples_dir / "manifest.json"
    if not path.exists():
        return {"sets": [], "extra_files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


_MANIFEST = _load_manifest()
SAMPLE_SETS = [
    {k: s[k] for k in ("id", "title", "description", "identity", "registration")} for s in _MANIFEST.get("sets", [])
]
_ALLOWED = {s["identity"] for s in SAMPLE_SETS} | {s["registration"] for s in SAMPLE_SETS} | set(
    _MANIFEST.get("extra_files", {}).values()
)


def sample_path(filename: str) -> Path | None:
    if filename not in _ALLOWED:  # whitelist: no path traversal possible
        return None
    path = settings.samples_dir / filename
    return path if path.exists() else None


def manifest() -> dict:
    return _MANIFEST
