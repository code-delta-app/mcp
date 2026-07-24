#!/usr/bin/env python3
# ─── Component versioning ─────────────────────────────────
# CODEDELTA_COMPONENT: codedelta_mcp
# CODEDELTA_BUILD: 1
# CODEDELTA_BUILD_DATE: 2026-06-13
# ──────────────────────────────────────────────────────────
"""
CodeDelta MCP server — lets AI agents (Claude Code, Cursor, etc.) call the
real CodeDelta engine instead of improvising their own churn scripts.

Speaks the Model Context Protocol over stdio: newline-delimited JSON-RPC 2.0,
implemented directly (initialize / tools/list / tools/call) — no SDK
dependency, runs on any Python 3.8+. The tools shell out to the same engine
binary and batch CLI that the GUI uses, so agents get CodeDelta's
deterministic numbers, licence enforcement included.

Register with your agent, e.g. Claude Code (~/.claude.json or `claude mcp add`):

  { "mcpServers": { "codedelta": {
      "command": "/usr/bin/python3",
      "args": ["/Applications/CodeDelta/codedelta_mcp.py"] } } }

Tools (deliberately coarse — three verbs, not thirty flags):
  churn_scan  — measure churn between two directories or two git refs
  agent_scan  — find code that RUNS AI agents + git-history agent evidence
  ai_audit    — heuristic + ML scan for AI-WRITTEN code (pointers, not verdicts)
"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROTOCOL_VERSION = "2024-11-05"


def _read_version():
    try:
        with open(os.path.join(SCRIPT_DIR, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "unknown"


def _engine_path():
    exe = "codedelta.exe" if os.name == "nt" else "codedelta"
    p = os.path.join(SCRIPT_DIR, exe)
    return p if os.path.isfile(p) else None


def _batch_cmd():
    """Command prefix for the batch CLI: frozen codedelta-gui if present,
    else this interpreter running codedelta_server.py."""
    exe = "codedelta-gui.exe" if os.name == "nt" else "codedelta-gui"
    frozen = os.path.join(SCRIPT_DIR, exe)
    if os.path.isfile(frozen):
        return [frozen]
    return [sys.executable, os.path.join(SCRIPT_DIR, "codedelta_server.py")]


def _out_dir(tag):
    d = os.path.join(tempfile.gettempdir(),
                     "codedelta-mcp", time.strftime("%Y%m%d-%H%M%S") + "-" + tag)
    os.makedirs(d, exist_ok=True)
    return d


def _run(cmd, cwd=None, timeout=1800):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       timeout=timeout, errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _parse_total_row(csv_path):
    """Engine CSV: return the TOTAL row as {column: value}."""
    with open(csv_path, newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    for row in rows[1:]:
        if row and row[0] == "TOTAL":
            return {h: v for h, v in zip(header, row) if h and h not in ("Status", "File")}
    return {}


# ── Tools ─────────────────────────────────────────────────────────────────────

def tool_churn_scan(args):
    """Engine churn measurement: dir-vs-dir or git ref range."""
    engine = _engine_path()
    if not engine:
        return {"error": "codedelta engine binary not found next to codedelta_mcp.py"}

    out = _out_dir("churn")
    report = os.path.join(out, "report.html")
    csv_out = os.path.join(out, "report.csv")

    git_range = (args.get("git_range") or "").strip()
    if git_range:
        repo = args.get("repo_dir") or os.getcwd()
        cmd = [engine, "--git", git_range]
        cwd = repo
    else:
        old_dir, new_dir = args.get("old_dir"), args.get("new_dir")
        if not old_dir or not new_dir:
            return {"error": "provide either git_range (with optional repo_dir) "
                             "or both old_dir and new_dir"}
        cmd = [engine, old_dir, new_dir]
        cwd = None
    cmd += ["-o", report, "--csv", csv_out,
            "-d", os.path.join(out, "codedelta.db"), "-q"]

    rc, output = _run(cmd, cwd=cwd)
    if rc != 0 or not os.path.isfile(csv_out):
        return {"error": f"engine exit code {rc}", "engine_output": output.strip()[-2000:]}

    totals = _parse_total_row(csv_out)
    return {
        "totals": totals,
        "interpretation": {
            "CHG_LLOC": "logical statements changed",
            "DEL_LLOC": "logical statements deleted",
            "ADD_LLOC": "logical statements added",
            "CRN_LLOC": "total churn (CHG+DEL+ADD)",
            "REP_CHURN": "share of churn that replaced code rather than reworking it (0-1)",
        },
        "reports": {
            "main": report,
            "overview": report.replace(".html", "_overview.html"),
            "diff_viewer": report.replace(".html", "_diff.html"),
            "csv": csv_out,
        },
    }


def _batch_scan(directory, mode, tag, threshold=None):
    out = _out_dir(tag)
    cmd = _batch_cmd() + ["scan", directory, "--mode", mode,
                          "--out-dir", out, "--json", "--html", "--quiet"]
    if threshold is not None:
        cmd += ["--threshold", str(threshold)]
    rc, output = _run(cmd)
    results = {}
    for fn in sorted(os.listdir(out)) if os.path.isdir(out) else []:
        if fn.endswith(".json"):
            try:
                with open(os.path.join(out, fn)) as f:
                    results[fn] = json.load(f)
            except (OSError, ValueError):
                pass
    if not results:
        return {"error": f"scan produced no JSON output (exit {rc})",
                "scan_output": output.strip()[-2000:]}
    reports = {fn: os.path.join(out, fn)
               for fn in os.listdir(out) if fn.endswith(".html")}
    return {"results": results, "reports": reports}


def tool_agent_scan(args):
    """Code that RUNS agents (SDK imports, dynamic exec, prompt injection)
    plus documentary git-history evidence of agent-WRITTEN commits."""
    d = args.get("dir")
    if not d or not os.path.isdir(d):
        return {"error": f"dir not found: {d}"}
    res = _batch_scan(d, "agent", "agent")
    if "results" in res:
        res["note"] = ("Pattern findings are pointers for review. The git_evidence "
                       "section (if present) is documentary: each match proves agent "
                       "involvement in that commit; absence proves nothing.")
    return res


def tool_ai_audit(args):
    """Heuristic + ML scan for AI-written code characteristics."""
    d = args.get("dir")
    if not d or not os.path.isdir(d):
        return {"error": f"dir not found: {d}"}
    res = _batch_scan(d, "ai", "audit", threshold=args.get("threshold", 50))
    if "results" in res:
        res["note"] = ("AI-authorship detection does not generalise; these scores are "
                       "pointers for human review, not verdicts. HIGH requires an ML "
                       "model for the language; pattern-only languages cap at ELEVATED.")
    return res


TOOLS = [
    {
        "name": "churn_scan",
        "description": (
            "Measure code churn with the CodeDelta engine — deterministic, "
            "reproducible numbers (SLOC/LLOC changed, deleted, added, replacement "
            "churn) plus HTML reports. Compare two directories, or two git refs "
            "of a repository (tags, branches, hashes). Use this instead of "
            "improvising diff scripts when the user asks how much code changed."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_dir":   {"type": "string", "description": "Path to the OLD version (directory mode)"},
                "new_dir":   {"type": "string", "description": "Path to the NEW version (directory mode)"},
                "git_range": {"type": "string", "description": "Git mode: '<oldref>..<newref>' e.g. 'v1.7..v1.8' or 'HEAD~10..HEAD'; bare ref means ref..HEAD"},
                "repo_dir":  {"type": "string", "description": "Repository root for git mode (default: current directory)"},
            },
        },
    },
    {
        "name": "agent_scan",
        "description": (
            "Inventory AI agent usage in a codebase: files that import AI SDKs or "
            "run agents (with risk ratings and an SDK inventory), plus documentary "
            "git-history evidence of agent-signed commits (Co-Authored-By trailers, "
            "bot accounts — Claude Code, Copilot, Cursor, Aider and others). "
            "Use for questions like 'does this code use AI?' or 'how much of this "
            "repo was written by agents?'"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "Directory to scan (a git repo enables history evidence)"},
            },
            "required": ["dir"],
        },
    },
    {
        "name": "ai_audit",
        "description": (
            "Scan source files for characteristics associated with AI-generated "
            "code (heuristics + per-language ML models). Returns per-file risk "
            "ratings (HIGH/ELEVATED/NORMAL) and an overall AI%. Results are "
            "pointers for human review, not verdicts."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dir":       {"type": "string", "description": "Directory to scan"},
                "threshold": {"type": "integer", "description": "Sensitivity 0-100 (default 50); affects rating cut-offs only"},
            },
            "required": ["dir"],
        },
    },
]

TOOL_FNS = {"churn_scan": tool_churn_scan,
            "agent_scan": tool_agent_scan,
            "ai_audit": tool_ai_audit}


# ── MCP plumbing: newline-delimited JSON-RPC 2.0 over stdio ──────────────────

def _reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method", "")
    msg_id = msg.get("id")

    if method == "initialize":
        _reply(msg_id, {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "codedelta", "version": _read_version()},
        })
    elif method == "tools/list":
        _reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        fn = TOOL_FNS.get(name)
        if fn is None:
            _reply(msg_id, error={"code": -32602, "message": f"unknown tool: {name}"})
            return
        try:
            result = fn(params.get("arguments") or {})
        except subprocess.TimeoutExpired:
            result = {"error": "scan timed out (30 min limit)"}
        except Exception as e:                       # tool crash → error result, not server death
            result = {"error": f"{type(e).__name__}: {e}"}
        _reply(msg_id, {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            "isError": "error" in result,
        })
    elif method == "ping":
        _reply(msg_id, {})
    elif msg_id is not None:                          # unknown request (not notification)
        _reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})
    # notifications (no id) — e.g. notifications/initialized — need no reply


def main():
    # stdout carries protocol messages only; anything else must go to stderr.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        try:
            handle(msg)
        except Exception as e:
            sys.stderr.write(f"codedelta-mcp: {type(e).__name__}: {e}\n")


if __name__ == "__main__":
    main()
