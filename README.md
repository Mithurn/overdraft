# overdraft

When Claude Code runs out, keep coding on free backends.

Route Claude Code through Cloudflare Workers AI, Groq, OpenRouter, DeepSeek, Gemini, or Ollama. Track usage, fall back automatically, and hand off sessions when Anthropic limits hit.

## Quick start

```bash
pip install overdraft
overdraft setup          # keys + config wizard
overdraft doctor         # verify keys, proxy, Claude Code
overdraft                # start chatting
```

Requires [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) and at least one provider API key (Cloudflare or Groq recommended).

From source:

```bash
git clone https://github.com/Mithurn/overdraft.git
cd overdraft
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
overdraft setup
./overdraft              # dev wrapper
```

Optional background proxy + PATH shim (macOS):

```bash
overdraft install
```

## Daily use

| Command | What it does |
|---|---|
| `overdraft` | Start Claude Code. Uses Anthropic if `ANTHROPIC_API_KEY` is set, otherwise free backends. Auto-handoffs on limit errors. |
| `overdraft prevhandoff` | Export session summary, archive old context, start fresh on free backends |
| `/prevhandoff` | Same as above, from inside Claude Code (installed on first run) |
| `overdraft continue` | Resume the last session with full history on free backends |
| `overdraft usage` | Spend vs budget |
| `overdraft open src/foo.py:42` | Open file at line in Cursor/VS Code |
| `overdraft find "pattern" --open` | Ripgrep + optional editor jump |

Pass extra args to Claude Code:

```bash
overdraft -- --resume abc123
```

## Setup

`overdraft setup` writes:

- `~/.config/localbot/localbot.yaml`
- `~/.config/localbot/.env` (chmod 600)
- `~/.claude/commands/prevhandoff.md`

Add any provider keys you have. Disabled providers are skipped. Default fallback chain:

Cloudflare glm-4.7-flash → Cloudflare gpt-oss-20b → Groq gpt-oss-20b → OpenRouter → DeepSeek → Gemini → Ollama

## Handoff

**Automatic:** When `ANTHROPIC_API_KEY` is set, `overdraft` runs real Anthropic first. On limit errors it exports a handoff, archives the session, and restarts on free backends.

**Manual:** Run `overdraft prevhandoff` or type `/prevhandoff` in Claude Code.

Handoff files: `~/.localbot/handoffs/latest.md`  
Logs: `~/.localbot/handoff.log`

## Config

User config: `~/.config/localbot/localbot.yaml`  
Example: `config/localbot.example.yaml`

## Ops

```bash
overdraft doctor
overdraft stop
overdraft restart
overdraft serve
```

## Limits

- Claude Code CLI only. Cursor Agent handoff is not supported.
- Model quality changes after handoff to free backends.
- Cloudflare free tier: 10,000 neurons/day.

## Development

```bash
pytest -q
```

## License

MIT
