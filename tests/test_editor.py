from pathlib import Path

from localbot.editor import parse_location


def test_parse_location_line(tmp_path: Path):
    file_path = tmp_path / "src" / "auth" / "middleware.ts"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("export {}")
    loc = parse_location(f"src/auth/middleware.ts:42", cwd=tmp_path)
    assert loc.path == file_path.resolve()
    assert loc.line == 42
    assert loc.column is None


def test_parse_location_line_column(tmp_path: Path):
    file_path = tmp_path / "a.py"
    file_path.write_text("x = 1")
    loc = parse_location(str(file_path) + ":10:3", cwd=tmp_path)
    assert loc.line == 10
    assert loc.column == 3


def test_parse_location_range(tmp_path: Path):
    file_path = tmp_path / "bridge.py"
    file_path.write_text("a\nb\nc")
    loc = parse_location("bridge.py:49-87", cwd=tmp_path)
    assert loc.line == 49
    assert loc.end_line == 87
