from pathlib import Path

from localbot.session import encode_project_dir, latest_session_id, list_sessions


def test_encode_project_dir():
    assert encode_project_dir(Path("/Users/me/proj")) == "-Users-me-proj"


def test_latest_session_id(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "-tmp-proj"
    project.mkdir(parents=True)
    (project / "aaa.jsonl").write_text("{}")
    (project / "bbb.jsonl").write_text("{}\n{}\n")
    monkeypatch.setattr("localbot.session.project_dir_for_cwd", lambda cwd=None: project)
    sessions = list_sessions()
    assert len(sessions) == 2
    assert latest_session_id() in {"aaa", "bbb"}
