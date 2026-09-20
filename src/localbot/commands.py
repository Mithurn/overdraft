from __future__ import annotations

from pathlib import Path

PREVHANDOFF_COMMAND = """\
---
description: Export this session and restart on overdraft free backends with a handoff summary
allowed-tools: Bash(overdraft:*)
---

The user wants to move this session to overdraft free backends with a clean restart.

1. Tell the user you are handing off and they should run this in their terminal if it does not start automatically:
   `overdraft prevhandoff`
2. If Bash is available, run `overdraft prevhandoff` yourself.

That command exports the session, archives the old context, and opens a fresh Claude Code session on free backends with the handoff summary.
"""


def ensure_prevhandoff_command(project_root: Path | None = None) -> bool:
    targets = [
        Path.home() / ".claude" / "commands" / "prevhandoff.md",
    ]
    if project_root:
        targets.append(project_root / ".claude" / "commands" / "prevhandoff.md")

    changed = False
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text() == PREVHANDOFF_COMMAND:
            continue
        path.write_text(PREVHANDOFF_COMMAND)
        changed = True
    return changed
