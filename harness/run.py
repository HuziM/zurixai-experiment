"""Run every task × model × rep in a fresh container, resumably.

    ANTHROPIC_API_KEY=... python -m harness.run                     # full run into runs/
    CLAUDE_CODE_OAUTH_TOKEN=... python -m harness.run --concurrency 1 --out pilot/runs \
        --tasks py-m1,py-n1,js-i1 --reps 1                         # on a Claude subscription
    python -m harness.run --dry-run                                 # print the plan only

Auth is an API key or a subscription token (`claude setup-token`). The credential and the prompt
reach the container by name (`docker run -e NAME`), so neither appears in the process list or on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from harness.common import BASE, Run, full_prompt, load_config, load_tasks, plan_runs
from harness.transcript import read_events, source_files, summarize

FINISHED = {"done", "truncated", "no_code"}
_UNREACHABLE = ("Can't reach the API server", "ENOTFOUND", "ECONNREFUSED", "ECONNRESET", "ETIMEDOUT",
                "EAI_AGAIN", "Connection error")


def api_error(facts: dict) -> bool:
    """The session ended on an API error: a status code, or an "API Error: ..." result (e.g. DNS)."""
    message = facts.get("error_message") or ""
    return bool(facts.get("api_error_status")) or (bool(facts.get("is_error")) and message.startswith("API Error"))


def unreachable(meta: dict) -> bool:
    message = meta.get("error_message") or ""
    return any(marker in message for marker in _UNREACHABLE)
RETRY_LATER = {429, 500, 502, 503, 504, 529}
BACKOFF_S = 60
STOP_AFTER_RATE_LIMITED = 3


def classify(exit_code: int | None, facts: dict, files: list[str]) -> str:
    """Status of one attempt. infra_failed attempts are retried from scratch; the others are final."""
    if api_error(facts) or (not facts["has_result"] and not files):
        return "infra_failed"
    timed_out = exit_code in (124, 137) or exit_code is None
    if not files:
        return "no_code"
    if timed_out or facts["budget_hit"]:
        return "truncated"
    return "done"


def needs_run(meta: dict | None) -> bool:
    """Whether a run still has to be (re)run.

    Finished runs never rerun. An infrastructure failure already had its pre-registered retries,
    so it stays excluded, except when the model was never reached: a usage/rate limit (429) or an
    unreachable API (network/DNS). Those are run again once the limit resets or the network is back.
    """
    if meta is None:
        return True
    if meta.get("status") in FINISHED:
        return False
    if meta.get("status") != "infra_failed":
        return True
    return meta.get("api_error_status") == 429 or unreachable(meta)


def read_meta(run_dir: Path) -> dict | None:
    path = run_dir / "meta.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _container_name(run: Run) -> str:
    return "zxexp-" + hashlib.sha1(run.id.encode()).hexdigest()[:12]


AUTH_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def auth_mode() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api_key"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "subscription"
    return None


def _attempt(run: Run, run_dir: Path, cfg: dict, prompt: str) -> tuple[int | None, float]:
    for name in ("transcript.jsonl", "stderr.txt", "exit_code", "workspace.tar.gz"):
        (run_dir / name).unlink(missing_ok=True)
    env = {**os.environ, "ZX_PROMPT": prompt, "ZX_MODEL": run.model,
           "ZX_BUDGET_USD": str(cfg["budget_usd_per_run"]), "ZX_TIMEOUT_S": str(cfg["timeout_s"])}
    name = _container_name(run)
    cmd = ["docker", "run", "--rm", "--name", name,
           "--cpus", str(cfg["container"]["cpus"]), "--memory", cfg["container"]["memory"],
           *[arg for var in AUTH_VARS if os.environ.get(var) for arg in ("-e", var)],
           "-e", "ZX_PROMPT", "-e", "ZX_MODEL",
           "-e", "ZX_BUDGET_USD", "-e", "ZX_TIMEOUT_S",
           "-v", f"{run_dir.resolve()}:/out", cfg["images"]["agent"]]
    start = time.time()
    try:
        subprocess.run(cmd, env=env, capture_output=True, timeout=cfg["timeout_s"] + 180, check=False)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True, check=False)
    exit_file = run_dir / "exit_code"
    exit_code = int(exit_file.read_text().strip()) if exit_file.is_file() and exit_file.read_text().strip() else None
    return exit_code, time.time() - start


def execute(run: Run, out: Path, cfg: dict, suffix: str) -> dict:
    run_dir = out / run.id
    meta_path = run_dir / "meta.json"
    existing = read_meta(run_dir)
    if not needs_run(existing):
        return existing  # type: ignore[return-value]
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = full_prompt(run.task, suffix)
    attempts = []
    meta: dict = {}
    for attempt in range(1, cfg["infra_retries"] + 2):
        started = datetime.now(UTC).isoformat()
        exit_code, seconds = _attempt(run, run_dir, cfg, prompt)
        facts = summarize(read_events(run_dir / "transcript.jsonl"))
        files = source_files(run_dir / "workspace.tar.gz")
        status = classify(exit_code, facts, files)
        attempts.append({"attempt": attempt, "started_at": started, "seconds": round(seconds, 1),
                         "exit_code": exit_code, "status": status})
        meta = {"run_id": run.id, "auth": auth_mode(), "task": run.task.id, "language": run.task.language,
                "category": run.task.category, "model": run.model, "rep": run.rep,
                "status": status, "exit_code": exit_code, "timed_out": exit_code in (124, 137) or exit_code is None,
                "source_files": files, **{k: v for k, v in facts.items()}, "attempts": attempts}
        if status != "infra_failed":
            break
        if facts.get("api_error_status") in RETRY_LATER and attempt <= cfg["infra_retries"]:
            time.sleep(BACKOFF_S * attempt)
    meta_path.write_text(json.dumps(meta, indent=2))
    return meta


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=BASE / "runs")
    parser.add_argument("--tasks", help="comma-separated task ids (default: all)")
    parser.add_argument("--reps", type=int)
    parser.add_argument("--concurrency", type=int, help="override experiment.yaml (use 1 on a subscription)")
    parser.add_argument("--models", help="pilot only: comma-separated model ids (default: experiment.yaml)")
    parser.add_argument("--budget-usd", type=float, help="pilot only: override the per-run budget")
    parser.add_argument("--timeout-s", type=int, help="pilot only: override the per-run timeout")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def plan(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[dict, list[Run], str]:
    cfg = load_config()
    if args.budget_usd is not None:
        cfg["budget_usd_per_run"] = args.budget_usd
    if args.timeout_s is not None:
        cfg["timeout_s"] = args.timeout_s
    tasks, suffix = load_tasks()
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.id in wanted]
        if len(tasks) != len(wanted):
            parser.error("unknown task id in --tasks")
    models = args.models.split(",") if args.models else cfg["models"]
    return cfg, plan_runs(tasks, models, args.reps or cfg["reps"], cfg["seed"]), suffix


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg, runs, suffix = plan(args, parser)

    if args.dry_run:
        for run in runs:
            print(run.id)
        print(f"{len(runs)} runs", file=sys.stderr)
        return 0
    if auth_mode() is None:
        print("Set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN in this shell first.", file=sys.stderr)
        return 1
    if shutil.which("docker") is None:
        print("docker not found", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    done = 0
    rate_limited_in_a_row = 0
    with ThreadPoolExecutor(max_workers=args.concurrency or cfg["concurrency"]) as pool:
        futures = {pool.submit(execute, run, args.out, cfg, suffix): run for run in runs}
        for future in as_completed(futures):
            meta = future.result()
            done += 1
            cost = meta.get("cost_usd")
            print(f"[{done}/{len(runs)}] {meta['run_id']}: {meta['status']}"
                  + (f" ${cost:.2f}" if isinstance(cost, (int, float)) else ""), flush=True)
            limited = meta["status"] == "infra_failed" and meta.get("api_error_status") == 429
            offline = meta["status"] == "infra_failed" and unreachable(meta)
            rate_limited_in_a_row = rate_limited_in_a_row + 1 if (limited or offline) else 0
            if rate_limited_in_a_row >= STOP_AFTER_RATE_LIMITED:
                for pending in futures:
                    pending.cancel()
                if offline:
                    print(f"Stopped: {STOP_AFTER_RATE_LIMITED} runs in a row could not reach the API "
                          "(network/DNS). Rerun once the network is back; finished runs are skipped.", flush=True)
                    return 3
                print(f"Stopped: {STOP_AFTER_RATE_LIMITED} runs in a row hit a usage/rate limit (429). "
                      "Rerun the same command after the limit resets; finished runs are skipped.", flush=True)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
