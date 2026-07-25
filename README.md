# CodeDelta MCP server

[CodeDelta](https://codedelta.app) is a code-churn measurement engine
with AI-agent detection — a C++ engine that measures exactly what changed between two
versions of a codebase (changed / deleted / added logical statements), plus scanners
that find code which *runs* AI agents and code that may have been *written* by them.

CodeDelta ships with an **MCP server** (`codedelta_mcp.py`, included in every desktop
bundle), so AI agents can call the real engine instead of improvising their own churn
scripts. It speaks the Model Context Protocol over stdio — newline-delimited JSON-RPC
2.0, implemented directly with no SDK dependency; any Python 3.8+ runs it.

Everything executes locally against your working copies: **no network calls, nothing
leaves your machine.**

## Tools

Three deliberately coarse verbs:

| Tool | What it does |
|------|--------------|
| `churn_scan` | Measure churn between two directories or two git refs — CHG/DEL/ADD logical statements, REP_CHURN, per-file detail. Same numbers as the GUI and CI, every run. |
| `agent_scan` | Find code that **runs** AI agents (named SDK/agent-framework calls) plus agent evidence in git history (co-authorship trailers). |
| `ai_audit` | Heuristic + ML scan for AI-**written** code — positioned as pointers for review, not verdicts. |

## Setup

1. Download CodeDelta for your platform from [codedelta.app/download.html](https://codedelta.app/download.html)
   (free and fully unlocked until 31 August 2026 — the licence file is a second
   one-click download on the same page).
2. Register the server with your agent. Claude Code example (`claude mcp add` or
   `~/.claude.json`):

```json
{ "mcpServers": { "codedelta": {
    "command": "python3",
    "args": ["/path/to/CodeDelta/codedelta_mcp.py"] } } }
```

On macOS the bundle path is typically `/Applications/CodeDelta/codedelta_mcp.py`.

## See it work

The same engine runs as a GitHub Action on pull requests — live example on a real PR:
[code-delta-app/demo#2](https://github.com/code-delta-app/demo/pull/2).

Method papers with reproducible figures: [codedelta.app/papers.html](https://codedelta.app/papers.html) ·
User guide: [codedelta.app/user-guide.html](https://codedelta.app/user-guide.html)
