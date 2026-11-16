"""Shared helpers for Claude Code hooks (stdlib only). Hooks never call the network."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or SCRIPTS.parent).resolve()
sys.path.insert(0, str(SCRIPTS))


def read_event() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def project_for(path: Path) -> Path | None:
    """Nearest project.json above a written file, inside the repository."""
    try:
        path = path.resolve()
        path.relative_to(ROOT)
    except (OSError, ValueError):
        return None
    for folder in [path.parent, *path.parents]:
        candidate = folder / "project.json"
        if candidate.is_file():
            return candidate
        if folder == ROOT:
            break
    return None


def all_projects() -> list[Path]:
    found = []
    for base in ("projects", "examples"):
        folder = ROOT / base
        if folder.is_dir():
            found.extend(sorted(folder.glob("*/project.json")))
    return found


def last_checkpoint(project: dict) -> datetime | None:
    history = project.get("checkpoints") or []
    if not history:
        return None
    try:
        return datetime.fromisoformat(history[-1]["at"])
    except (KeyError, ValueError):
        return None
