from __future__ import annotations

import re
from pathlib import Path


def default_session_dir() -> Path:
    return Path.home() / ".crater_analysis" / "sessions"


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return cleaned.strip("._-") or "session"
