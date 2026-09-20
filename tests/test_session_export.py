import json
from pathlib import Path

from localbot.session import ClaudeSession
from localbot.session_export import (
    ARCHIVE_DIR,
    HANDOFF_DIR,
    archive_session,
    build_handoff_markdown,
    export_handoff,
    parse_session_messages,
)


def _write_turn(path: Path, role: str, text: str, sidechain: bool = False) -> None:
    payload = {
        "type": role,
        "message": {"role": role, "content": text},
        "isSidechain": sidechain,
    }
    with path.open("a") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_parse_session_messages(tmp_path: Path):
    session_path = tmp_path / "abc.jsonl"
    with session_path.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "build feature x"},
                }
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "working on it"}],
                    },
                }
            )
            + "\n"
        )
        handle.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "side note"},
                    "isSidechain": True,
                }
            )
            + "\n"
        )

    turns = parse_session_messages(session_path)
    assert turns == [("user", "build feature x"), ("assistant", "working on it")]


def test_export_and_archive(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "-tmp-proj"
    project.mkdir(parents=True)
    session_path = project / "sess1.jsonl"
    _write_turn(session_path, "user", "finish the CLI")
    _write_turn(session_path, "assistant", "done")

    monkeypatch.setattr("localbot.session.project_dir_for_cwd", lambda cwd=None: project)
    monkeypatch.setattr("localbot.session_export.HANDOFF_DIR", tmp_path / "handoffs")
    monkeypatch.setattr("localbot.session_export.ARCHIVE_DIR", tmp_path / "archive")

    session, handoff_path = export_handoff()
    assert handoff_path.exists()
    assert "finish the CLI" in handoff_path.read_text()
    assert (tmp_path / "handoffs" / "latest.md").exists()

    archived = archive_session(session)
    assert not session_path.exists()
    assert archived.exists()


def test_build_handoff_markdown(tmp_path: Path):
    session = ClaudeSession(
        session_id="abc",
        path=tmp_path / "abc.jsonl",
        modified_at=tmp_path.stat().st_mtime if tmp_path.exists() else __import__("datetime").datetime.now(),
    )
    _write_turn(session.path, "user", "goal")
    markdown = build_handoff_markdown(session, tmp_path)
    assert "overdraft session handoff" in markdown
    assert "goal" in markdown
