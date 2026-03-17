from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from crater_app.desktop.exporter import export_starred_session


def default_session_dir() -> Path:
    return Path.home() / ".crater_analysis" / "sessions"


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return cleaned.strip("._-") or "session"


def save_session(path: str, payload: Dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    export_starred_session(payload, str(target))


def load_session(path: str) -> Optional[Dict]:
    target = Path(path)
    if not target.exists():
        return None
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload


def save_named_session(name: str, payload: Dict, session_dir: Optional[Path] = None) -> Path:
    target_dir = session_dir or default_session_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize_name(name)}.json"
    path = target_dir / filename
    save_session(str(path), payload)
    return path


def list_sessions(session_dir: Optional[Path] = None) -> List[Path]:
    target_dir = session_dir or default_session_dir()
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("*.json"), key=lambda p: p.name.lower())


def delete_named_session(filename: str, session_dir: Optional[Path] = None) -> bool:
    target_dir = (session_dir or default_session_dir()).resolve()
    target = (target_dir / filename).resolve()
    if target.parent != target_dir or not target.exists() or target.suffix.lower() != ".json":
        return False
    target.unlink()
    return True


def rename_named_session(filename: str, new_name: str, session_dir: Optional[Path] = None) -> Optional[Path]:
    target_dir = (session_dir or default_session_dir()).resolve()
    source = (target_dir / filename).resolve()
    if source.parent != target_dir or not source.exists() or source.suffix.lower() != ".json":
        return None
    target_name = f"{_sanitize_name(new_name)}.json"
    target = (target_dir / target_name).resolve()
    if target.parent != target_dir:
        return None
    source.rename(target)
    return target
