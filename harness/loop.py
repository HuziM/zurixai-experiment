"""Run until every planned run is finished, waiting out subscription usage limits.

    caffeinate -i python -m harness.loop --concurrency 1            # full run, unattended
    python -m harness.loop --concurrency 1 --wait-hours 5.5 --max-rounds 12

Takes the same options as harness.run. After a round that stops on a usage limit it reads the
reset time from the limit message and waits until then (plus 5 minutes); if no time can be read,
it waits --wait-hours. Finished runs are skipped. Runs that failed for any other reason already
had their pre-registered retries and are not rerun.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harness import run as runner
from harness.limits import latest_reset

SHORT_WAIT_S = 15 * 60
RESET_MARGIN_S = 5 * 60
CHECK_EVERY_S = 60


def sleep_until(target: datetime, now=lambda: datetime.now(UTC), sleep=time.sleep) -> None:
    """Wait until a wall-clock time. Short naps against the real clock, because a single long
    time.sleep() stops counting while the computer sleeps and would wake up late."""
    while (left := (target - now()).total_seconds()) > 0:
        sleep(min(CHECK_EVERY_S, left))


def limit_messages(out: Path, run_ids: list[str]) -> list[str]:
    """Usage-limit messages (from the result and stderr) of runs that stopped on a 429."""
    messages = []
    for run_id in run_ids:
        meta = runner.read_meta(out / run_id)
        if not meta or meta.get("api_error_status") != 429:
            continue
        if meta.get("error_message"):
            messages.append(meta["error_message"])
        stderr = out / run_id / "stderr.txt"
        if stderr.is_file():
            messages.append(stderr.read_text(errors="replace")[-1000:])
    return messages


def wait_seconds(out: Path, left: list[str], stopped_on_limit: bool, fallback_hours: float,
                 now: datetime) -> tuple[float, str]:
    """How long to wait before the next round, and why."""
    if not stopped_on_limit:
        return SHORT_WAIT_S, "some runs left; short pause"
    messages = limit_messages(out, left)
    reset = latest_reset(messages, now)
    if reset is not None:
        return (reset - now).total_seconds() + RESET_MARGIN_S, f"limit resets at {reset:%Y-%m-%d %H:%M} UTC"
    sample = (messages[0] if messages else "no message").strip().replace("\n", " ")[:160]
    return fallback_hours * 3600, f"couldn't read a reset time, waiting {fallback_hours} h (message: {sample!r})"


def remaining(out: Path, runs: list) -> list[str]:
    return [r.id for r in runs if runner.needs_run(runner.read_meta(out / r.id))]


def main(argv: list[str] | None = None) -> int:
    parser = runner.build_parser()
    parser.add_argument("--wait-hours", type=float, default=5.5, help="wait after a usage-limit stop")
    parser.add_argument("--max-rounds", type=int, default=12)
    args = parser.parse_args(argv)
    if args.dry_run:
        parser.error("--dry-run: use harness.run")
    _, runs, _ = runner.plan(args, parser)
    forwarded = [a for a in (argv if argv is not None else sys.argv[1:])]
    for flag in ("--wait-hours", "--max-rounds"):
        if flag in forwarded:
            i = forwarded.index(flag)
            del forwarded[i:i + 2]

    for round_no in range(1, args.max_rounds + 1):
        left = remaining(args.out, runs)
        if not left:
            print(_finished(args.out, runs), flush=True)
            return 0
        print(f"Round {round_no}: {len(left)} of {len(runs)} runs to go "
              f"({datetime.now():%Y-%m-%d %H:%M}).", flush=True)
        code = runner.main(forwarded)
        if code not in (0, 2, 3):
            return code
        left = remaining(args.out, runs)
        if not left:
            print(_finished(args.out, runs), flush=True)
            return 0
        if code == 3:
            wait_s, why = SHORT_WAIT_S, "API unreachable (network/DNS); checking again in 15 minutes"
        else:
            wait_s, why = wait_seconds(args.out, left, code == 2, args.wait_hours, datetime.now(UTC))
        resume = datetime.now(UTC) + timedelta(seconds=wait_s)
        print(f"{len(left)} runs left; {why}. Next round at {resume.astimezone():%Y-%m-%d %H:%M} "
              "(this machine's time).", flush=True)
        sleep_until(resume)
    print(f"Gave up after {args.max_rounds} rounds; {len(remaining(args.out, runs))} runs left. "
          "Check runs/run.log, then rerun.", flush=True)
    return 1


def _finished(out: Path, runs: list) -> str:
    excluded = sum(1 for r in runs if (runner.read_meta(out / r.id) or {}).get("status") == "infra_failed")
    note = f"; {excluded} excluded after failing for a reason other than a usage limit" if excluded else ""
    return f"Nothing left to run: {len(runs) - excluded} of {len(runs)} runs finished{note}."


if __name__ == "__main__":
    sys.exit(main())
