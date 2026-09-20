from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from localbot.paths import STATE_DIR
from localbot.session import ClaudeSession, list_sessions, project_dir_for_cwd

HANDOFF_DIR = STATE_DIR / "handoffs"
ARCHIVE_DIR = STATE_DIR / "archived-sessions"
MAX_HANDOFF_CHARS = 12000


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind == "tool_use":
                parts.append(f"[tool {block.get('name')}]")
            elif kind == "tool_result":
                parts.append("[tool result]")
        return "\n".join(part for part in parts if part).strip()
    return ""


def parse_session_messages(path: Path) -> list[tuple[str, str]]:
    turns: list[tuple[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("isSidechain"):
            continue
        role = payload.get("type")
        message = payload.get("message") or {}
        if role not in {"user", "assistant"}:
            role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = _content_text(message.get("content"))
        if text:
            turns.append((role, text))
    return turns


def build_handoff_markdown(session: ClaudeSession, cwd: Path) -> str:
    turns = parse_session_messages(session.path)
    lines = [
        "# CloudAI session handoff",
        "",
        f"- session: `{session.session_id}`",
        f"- project: `{cwd}`",
        f"- exported: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Conversation summary",
        "",
    ]
    for role, text in turns[-40:]:
        label = "User" if role == "user" else "Assistant"
        clipped = text if len(text) <= 1200 else text[:1200] + "…"
        lines.append(f"### {label}")
        lines.append(clipped)
        lines.append("")
    lines.extend(
        [
            "## Continue the work",
            "",
            "Pick up from the latest user goal above. Do not restart from scratch unless required.",
            "Confirm the current repo state before making changes.",
        ]
    )
    body = "\n".join(lines)
    if len(body) > MAX_HANDOFF_CHARS:
        body = body[:MAX_HANDOFF_CHARS] + "\n\n[truncated for context limits]\n"
    return body


def export_handoff(cwd: Path | None = None, session_id: str | None = None) -> tuple[ClaudeSession, Path]:
    sessions = list_sessions(cwd)
    if not sessions:
        raise FileNotFoundError("No Claude Code session found for this directory.")

    session = next((item for item in sessions if item.session_id == session_id), sessions[0])
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    markdown = build_handoff_markdown(session, cwd or Path.cwd())
    out_path = HANDOFF_DIR / f"{session.session_id}.md"
    latest_path = HANDOFF_DIR / "latest.md"
    out_path.write_text(markdown)
    latest_path.write_text(markdown)
    return session, out_path


def archive_session(session: ClaudeSession) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / session.path.name
    if session.path.exists():
        shutil.move(str(session.path), str(target))
    return target
