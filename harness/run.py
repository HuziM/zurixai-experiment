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

from harness.common import ROOT, Run, full_prompt, load_config, load_tasks, plan_runs
from harness.transcript import read_events, source_files, summarize

FINISHED = {"done", "truncated", "no_code"}
RETRY_LATER = {429, 500, 502, 503, 504, 529}
BACKOFF_S = 60


def classify(exit_code: int | None, facts: dict, files: list[str]) -> str:
    """Status of one attempt. infra_failed attempts are retried from scratch; the others are final."""
    if facts.get("api_error_status") or (not facts["has_result"] and not files):
        return "infra_failed"
    timed_out = exit_code in (124, 137) or exit_code is None
    if not files:
        return "no_code"
    if timed_out or facts["budget_hit"]:
        return "truncated"
    return "done"


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
    if meta_path.is_file() and json.loads(meta_path.read_text()).get("status") in FINISHED:
        return json.loads(meta_path.read_text())
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "runs")
    parser.add_argument("--tasks", help="comma-separated task ids (default: all)")
    parser.add_argument("--reps", type=int)
    parser.add_argument("--concurrency", type=int, help="override experiment.yaml (use 1 on a subscription)")
    parser.add_argument("--models", help="pilot only: comma-separated model ids (default: experiment.yaml)")
    parser.add_argument("--budget-usd", type=float, help="pilot only: override the per-run budget")
    parser.add_argument("--timeout-s", type=int, help="pilot only: override the per-run timeout")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

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
    runs = plan_runs(tasks, models, args.reps or cfg["reps"], cfg["seed"])

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
    with ThreadPoolExecutor(max_workers=args.concurrency or cfg["concurrency"]) as pool:
        futures = {pool.submit(execute, run, args.out, cfg, suffix): run for run in runs}
        for future in as_completed(futures):
            meta = future.result()
            done += 1
            cost = meta.get("cost_usd")
            print(f"[{done}/{len(runs)}] {meta['run_id']}: {meta['status']}"
                  + (f" ${cost:.2f}" if isinstance(cost, (int, float)) else ""), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
