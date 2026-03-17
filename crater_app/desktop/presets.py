from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional

from crater_app.core.settings import AnalysisSettings


def default_preset_dir() -> Path:
    return Path.home() / ".crater_analysis" / "presets"


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return cleaned.strip("._-") or "preset"


def save_preset(path: str, settings: AnalysisSettings) -> None:
    payload = settings.to_dict()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_preset(path: str) -> Optional[AnalysisSettings]:
    target = Path(path)
    if not target.exists():
        return None
    with target.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return AnalysisSettings.from_dict(payload)


def save_named_preset(name: str, settings: AnalysisSettings, preset_dir: Optional[Path] = None) -> Path:
    target_dir = preset_dir or default_preset_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_sanitize_name(name)}.json"
    path = target_dir / filename
    save_preset(str(path), settings)
    return path


def list_presets(preset_dir: Optional[Path] = None) -> List[Path]:
    target_dir = preset_dir or default_preset_dir()
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("*.json"), key=lambda p: p.name.lower())


def delete_named_preset(filename: str, preset_dir: Optional[Path] = None) -> bool:
    target_dir = (preset_dir or default_preset_dir()).resolve()
    target = (target_dir / filename).resolve()
    if target.parent != target_dir or not target.exists() or target.suffix.lower() != ".json":
        return False
    target.unlink()
    return True


def rename_named_preset(filename: str, new_name: str, preset_dir: Optional[Path] = None) -> Optional[Path]:
    target_dir = (preset_dir or default_preset_dir()).resolve()
    source = (target_dir / filename).resolve()
    if source.parent != target_dir or not source.exists() or source.suffix.lower() != ".json":
        return None
    target_name = f"{_sanitize_name(new_name)}.json"
    target = (target_dir / target_name).resolve()
    if target.parent != target_dir:
        return None
    source.rename(target)
    return target

