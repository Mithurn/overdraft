from pathlib import Path

from localbot.commands import ensure_prevhandoff_command


def test_ensure_prevhandoff_command(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "localbot.commands.Path.home",
        lambda: tmp_path / "home",
    )
    changed = ensure_prevhandoff_command(tmp_path / "repo")
    assert changed is True
    installed = tmp_path / "home" / ".claude" / "commands" / "prevhandoff.md"
    assert installed.exists()
    assert "overdraft prevhandoff" in installed.read_text()
    assert (tmp_path / "repo" / ".claude" / "commands" / "prevhandoff.md").exists()
    assert ensure_prevhandoff_command(tmp_path / "repo") is False
