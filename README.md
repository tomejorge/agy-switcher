# agy-switcher

A lightweight, high-performance, zero-dependency multi-account session manager and resilient coding agent delegator for Google Antigravity CLI (`agy`).

## Why agy-switcher?

When using Antigravity (`agy`) for deep coding tasks, users frequently hit per-account rate limits ("individual quota reached", HTTP 429, `RESOURCE_EXHAUSTED`).

`agy-switcher` solves this problem seamlessly:
1. **Zero Runtime Dependencies**: Written entirely in pure modern Python 3.10+ standard library.
2. **Native Cross-Platform Vault**:
   - **Windows**: Advapi32 Credential Manager (`CredReadW`/`CredWriteW`/`CredDeleteW`)
   - **macOS**: Keychain via `/usr/bin/security`
   - **Linux**: Secret Service via `secret-tool`
   - **Headless Fallback**: File vault (`~/.gemini/antigravity_vault.json`)
3. **Resilient Coding Agent Delegation (`gemini-coder`)**: Runs `agy --model <model> --dangerously-skip-permissions -p <prompt>`, intercepts quota exhaustion errors, rotates to the next available account, and replays the prompt automatically.
4. **Model Context Protocol (MCP)**: Native stdio server exposing the `gemini_code` tool for Claude Code and OpenAI Codex CLI.

---

## Installation

```bash
git clone https://github.com/tomejorge/agy-switcher.git
cd agy-switcher
pip install -e .
```

---

## Quick Start (PowerShell / Windows)

### 1. Save your current Antigravity account to a named slot
Log in with Antigravity as usual, then save the session:
```powershell
agy-switcher save work --email user@work.com
```

Log in with your secondary account, then save it:
```powershell
agy-switcher save personal --email user@personal.com
```

### 2. Fast Switching (`switch-gemini`)
```powershell
# Switch to work account
switch-gemini work

# Switch to personal account
switch-gemini personal

# Rotate to the least recently used account
switch-gemini --rotate

# Inspect pool and cooldown status
switch-gemini --status
```

---

## Resilient Coding Delegation (`gemini-coder`)

Delegate a prompt directly to `agy`. If your current account hits quota exhaustion, `gemini-coder` automatically marks it on a 1-hour cooldown, rotates to the next available account, and re-executes the prompt without losing work:

```powershell
gemini-coder "Implement JWT authentication in auth.py and add unit tests" --model gemini-3.8-flash
```

---

## Model Context Protocol (MCP) Integration

`agy-switcher` includes a built-in stdio MCP server exposing the `gemini_code` tool.

### Claude Code Setup

Add to your Claude Code or Claude Desktop MCP configuration (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gemini": {
      "command": "agy-switcher",
      "args": ["mcp"]
    }
  }
}
```

Or via CLI:
```bash
claude mcp add gemini -- agy-switcher mcp
```

### OpenAI Codex CLI Setup

Run with MCP:
```bash
codex --mcp "agy-switcher mcp"
```

---

## CLI Reference

### `agy-switcher`
- `agy-switcher save <name> [--email <email>] [--secret <secret>]`: Save credentials to a slot.
- `agy-switcher switch <name>`: Switch active session.
- `agy-switcher rotate [--cooldown <seconds>]`: Rotate to next slot.
- `agy-switcher status`: View slot status table and cooldown timers.
- `agy-switcher list`: List configured slots.
- `agy-switcher remove <name>`: Remove a slot.
- `agy-switcher code <prompt> [--model <model>]`: Run resilient coder delegation.
- `agy-switcher mcp`: Launch MCP stdio server.

### `switch-gemini`
- `switch-gemini <name>`: Quick switch to slot.
- `switch-gemini -r`: Rotate to next account.
- `switch-gemini -s`: Show status.

### `gemini-coder`
- `gemini-coder <prompt> [--model <model>]`: Run coding agent with automatic quota retry.

---

## Testing

Run unit tests across all backends:
```bash
python -m pytest -v
```

## License
MIT License (c) 2026 Tome Gaspar.
