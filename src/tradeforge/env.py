"""Minimal local .env loader; secrets never belong in source control."""

from __future__ import annotations

import os
from pathlib import Path


def load_local_env(path: str | Path | None = None) -> None:
    """Load simple KEY=VALUE entries without overriding real environment vars."""
    env_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(value[0]):
            value = value[1:-1]
        if key and value:
            os.environ.setdefault(key, value)
