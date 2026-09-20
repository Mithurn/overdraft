from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

CLAUDE_HOOK_START = "<!-- localbot:editor -->"
CLAUDE_HOOK_END = "<!-- /localbot:editor -->"
CLAUDE_HOOK_BODY = """\
When the user asks to open, show, or explain part of the code:

1. Search first (Grep/Glob). Pick the smallest relevant line range.
2. Reply in at most 4 short sentences. Name the file and line range (e.g. "Lines 49–87 in bridge.py route Claude requests to Cloudflare").
3. Include exactly one code citation in this format (required):
   ```startLine:endLine:relative/path/from/repo/root
   ```
   Use the real line numbers from the file. Keep the cited block to the relevant lines only, not the whole file.
4. Run: overdraft open relative/path:startLine-endLine

Do not paste large code dumps outside the citation. Do not use cursor/code directly.
"""

CURSOR_APP_BIN = Path("/Applications/Cursor.app/Contents/Resources/app/bin/cursor")
LOCATION_RE = re.compile(r"^(?P<path>.+?)(?::(?P<line>\d+))?(?::(?P<column>\d+))?$")
RANGE_RE = re.compile(r"^(?P<path>.+):(?P<start>\d+)-(?P<end>\d+)$")


@dataclass
class SearchHit:
    path: Path
    line: int
    text: str


@dataclass
class ParsedLocation:
    path: Path
    line: int | None = None
    end_line: int | None = None
    column: int | None = None


def parse_location(raw: str, cwd: Path | None = None) -> ParsedLocation:
    text = raw.strip()
    base = cwd or Path.cwd()

    range_match = RANGE_RE.match(text)
    if range_match:
        path = Path(range_match.group("path"))
        if not path.is_absolute():
            path = (base / path).resolve()
        start = int(range_match.group("start"))
        end = int(range_match.group("end"))
        if end < start:
            raise ValueError(f"Invalid range: {raw}")
        return ParsedLocation(path=path, line=start, end_line=end)

    match = LOCATION_RE.match(text)
    if not match:
        raise ValueError(f"Invalid location: {raw}")
    path = Path(match.group("path"))
    if not path.is_absolute():
        path = (base / path).resolve()
    line = int(match.group("line")) if match.group("line") else None
    column = int(match.group("column")) if match.group("column") else None
    return ParsedLocation(path=path, line=line, column=column)


def resolve_editor_command() -> list[str]:
    override = os.environ.get("LOCALBOT_EDITOR", "").strip().lower()
    if override == "code" and shutil.which("code"):
        return ["code"]
    if override == "cursor":
        if CURSOR_APP_BIN.exists():
            return [str(CURSOR_APP_BIN)]
        if shutil.which("cursor"):
            return ["cursor"]

    if CURSOR_APP_BIN.exists():
        return [str(CURSOR_APP_BIN)]
    if shutil.which("code"):
        return ["code"]
    if shutil.which("cursor"):
        return ["cursor"]
    raise RuntimeError(
        "No editor found. Install VS Code (code) or Cursor, or set LOCALBOT_EDITOR=code|cursor"
    )


def open_in_editor(location: ParsedLocation) -> None:
    if not location.path.exists():
        raise FileNotFoundError(f"File not found: {location.path}")

    editor = resolve_editor_command()
    target = str(location.path)
    if location.line is not None:
        target = f"{target}:{location.line}"
        if location.column is not None:
            target = f"{target}:{location.column}"

    command = [*editor, "-g", target, "-r"]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Editor failed ({completed.returncode}): {' '.join(command)}")


def format_open_label(location: ParsedLocation) -> str:
    label = str(location.path)
    if location.line is None:
        return label
    if location.end_line is not None:
        return f"{label}:{location.line}-{location.end_line}"
    if location.column is not None:
        return f"{label}:{location.line}:{location.column}"
    return f"{label}:{location.line}"


def search_repo(
    pattern: str,
    root: Path | None = None,
    *,
    glob: str | None = None,
    limit: int = 20,
) -> list[SearchHit]:
    if not shutil.which("rg"):
        raise RuntimeError("ripgrep (rg) not found in PATH")

    search_root = (root or Path.cwd()).resolve()
    command = ["rg", "--line-number", "--no-heading", pattern, str(search_root)]
    if glob:
        command.extend(["--glob", glob])

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or "rg failed")

    hits: list[SearchHit] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        file_part, line_no, _, text = line.split(":", 3)
        hits.append(
            SearchHit(
                path=Path(file_part),
                line=int(line_no),
                text=text.strip(),
            )
        )
        if len(hits) >= limit:
            break
    return hits


def ensure_claude_editor_hook(project_root: Path | None = None) -> bool:
    root = (project_root or Path.cwd()).resolve()
    claude_md = root / "CLAUDE.md"
    block = f"{CLAUDE_HOOK_START}\n{CLAUDE_HOOK_BODY}{CLAUDE_HOOK_END}"

    if claude_md.exists():
        content = claude_md.read_text()
        if CLAUDE_HOOK_START in content and CLAUDE_HOOK_END in content:
            start = content.index(CLAUDE_HOOK_START)
            end = content.index(CLAUDE_HOOK_END) + len(CLAUDE_HOOK_END)
            updated = content[:start] + block + content[end:]
            if updated == content:
                return False
            claude_md.write_text(updated)
            return True
        if CLAUDE_HOOK_START in content:
            return False
        claude_md.write_text(content.rstrip() + "\n\n" + block + "\n")
        return True

    claude_md.write_text(block + "\n")
    return True
