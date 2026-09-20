from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ClaudeSession:
    session_id: str
    path: Path
    modified_at: datetime


def encode_project_dir(cwd: Path) -> str:
    return str(cwd.resolve()).replace("/", "-")


def project_dir_for_cwd(cwd: Path | None = None) -> Path:
    root = Path.home() / ".claude" / "projects"
    encoded = encode_project_dir(cwd or Path.cwd())
    return root / encoded


def list_sessions(cwd: Path | None = None) -> list[ClaudeSession]:
    project_dir = project_dir_for_cwd(cwd)
    if not project_dir.exists():
        return []

    sessions: list[ClaudeSession] = []
    for path in project_dir.glob("*.jsonl"):
        sessions.append(
            ClaudeSession(
                session_id=path.stem,
                path=path,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime),
            )
        )
    sessions.sort(key=lambda item: item.modified_at, reverse=True)
    return sessions


def latest_session_id(cwd: Path | None = None) -> str | None:
    sessions = list_sessions(cwd)
    if not sessions:
        return None
    return sessions[0].session_id


def session_exists(session_id: str, cwd: Path | None = None) -> bool:
    project_dir = project_dir_for_cwd(cwd)
    return (project_dir / f"{session_id}.jsonl").exists()


def read_session_title(session_id: str, cwd: Path | None = None) -> str | None:
    path = project_dir_for_cwd(cwd) / f"{session_id}.jsonl"
    if not path.exists():
        return None
    for line in path.read_text().splitlines()[:5]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "summary":
            return str(payload.get("summary") or "")
    return None
