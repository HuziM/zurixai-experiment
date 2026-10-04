"""Facts from a Claude Code stream-json transcript and a shipped workspace tarball."""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path

SOURCE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")
_INSTALL = re.compile(
    r"\b(pip3?|uv pip|python3? -m pip)\s+install\b|\bnpm\s+(install|i|add|ci)\b|\b(pnpm|yarn)\s+(add|install)\b"
    r"|\bpoetry\s+add\b|\buv\s+add\b")
_RUN_CODE = re.compile(r"\b(python3?|node|tsx|ts-node|deno|bun)\s+\S|\bpytest\b|\bnpm\s+(test|run|start)\b|\bnpx\s+\S")


def read_events(path: Path) -> list[dict]:
    events = []
    if not path.is_file():
        return events
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def bash_commands(events: list[dict]) -> list[str]:
    commands = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for item in (event.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") == "Bash":
                command = (item.get("input") or {}).get("command")
                if isinstance(command, str):
                    commands.append(command)
    return commands


def result_event(events: list[dict]) -> dict | None:
    for event in reversed(events):
        if event.get("type") == "result":
            return event
    return None


def summarize(events: list[dict]) -> dict:
    result = result_event(events) or {}
    commands = bash_commands(events)
    subtype = str(result.get("subtype", "")) if result else ""
    return {
        "has_result": bool(result),
        "result_subtype": subtype or None,
        "is_error": result.get("is_error"),
        "cost_usd": result.get("total_cost_usd"),
        "num_turns": result.get("num_turns"),
        "budget_hit": "budget" in subtype,
        "api_error_status": result.get("api_error_status"),
        "ran_install": any(_INSTALL.search(c) for c in commands),
        "ran_code": any(_RUN_CODE.search(c) for c in commands),
        "bash_commands": len(commands),
    }


def source_files(workspace: Path) -> list[str]:
    if not workspace.is_file():
        return []
    try:
        with tarfile.open(workspace) as tar:
            return sorted(m.name for m in tar.getmembers() if m.isfile() and m.name.endswith(SOURCE_SUFFIXES))
    except (tarfile.TarError, OSError):
        return []
