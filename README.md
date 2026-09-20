# cloudai

Keep coding in Claude Code when Anthropic limits hit. Route the same CLI through free or cheap backends (Cloudflare Workers AI, Groq, OpenRouter, DeepSeek, Gemini, Ollama) with automatic fallback and session handoff.

## Quick start

```bash
pip install cloudai
cloudai setup          # keys + config wizard
cloudai doctor         # verify keys, proxy, Claude Code
cloudai                # start chatting
```

From source:

```bash
git clone https://github.com/Mithurn/localbot.git
cd localbot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cloudai setup
./cloudai              # dev wrapper, same as cloudai
```

Optional background proxy + PATH shim:

```bash
cloudai install
```

## Daily use

| Command | What it does |
|---|---|
| `cloudai` | Start Claude Code. Uses Anthropic if `ANTHROPIC_API_KEY` is set, otherwise free backends. Auto-handoffs on limit errors. |
| `cloudai prevhandoff` | Export session summary, archive old context, start fresh on free backends |
| `/prevhandoff` | Same as above, from inside Claude Code (installed on first run) |
| `cloudai continue` | Resume the last session with full history on free backends |
| `cloudai smart` | Same as default `cloudai` (kept for compatibility) |
| `cloudai usage` | Spend vs budget |
| `cloudai open src/foo.py:42` | Open file at line in Cursor/VS Code |
| `cloudai find "pattern" --open` | Ripgrep + optional editor jump |

Pass extra args to Claude Code:

```bash
cloudai -- --resume abc123
```

## Setup

`cloudai setup` writes:

- `~/.config/localbot/localbot.yaml`
- `~/.config/localbot/.env` (chmod 600)
- `~/.claude/commands/prevhandoff.md`

Add any provider keys you have. Disabled providers are skipped. Default fallback chain:

Cloudflare glm-4.7-flash → Cloudflare gpt-oss-20b → Groq gpt-oss-20b → OpenRouter → DeepSeek → Gemini → Ollama

Copy `.env.example` if you prefer editing env vars by hand.

## Handoff

**Automatic:** When `ANTHROPIC_API_KEY` is set, `cloudai` runs real Anthropic first. On limit/rate/quota errors it exports a handoff, archives the session, and restarts on free backends.

**Manual:** Run `cloudai prevhandoff` or type `/prevhandoff` in Claude Code.

Handoff files: `~/.localbot/handoffs/latest.md`  
Logs: `~/.localbot/handoff.log`

## Config

User config: `~/.config/localbot/localbot.yaml`  
Example: `config/localbot.example.yaml`

Key fields:

- `providers` — enable backends and model IDs
- `routing.primary` / `routing.fallbacks` — fallback chain
- `handoff.limit_patterns` — regex list for auto-handoff
- `claude_code` — model aliases for Claude Code

Dev-only repo config (gitignored): `config/localbot.yaml`

## Ops

```bash
cloudai doctor    # config, keys, proxy health, Claude Code version
cloudai stop      # stop background proxy
cloudai restart   # restart proxy
cloudai serve     # run proxy in foreground (debug)
```

## Limits

- Claude Code CLI only. Cursor Agent handoff is not supported.
- Model quality changes after handoff to free backends.
- Auto-detect uses pattern matching on terminal output.
- Cloudflare free tier: 10,000 neurons/day.

## Development

```bash
pytest -q
```

CI runs on push/PR via GitHub Actions (`.github/workflows/ci.yml`).

## License

MIT
