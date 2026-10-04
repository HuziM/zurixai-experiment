"""Compute the pre-registered metrics from scores/ and the hand-check log.

    python -m harness.report                     # → results/summary.json + results/RESULTS.md
    python -m harness.report --draft             # allow unreviewed phantoms (counted as unconfirmed)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from harness.common import ROOT, load_config, load_tasks, plan_runs

Z95 = 1.959963984540054
BOOTSTRAP_DRAWS = 10_000
SCORED = {"done", "truncated"}


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def task_bootstrap(per_task: dict[str, tuple[int, int]], seed: int,
                   draws: int = BOOTSTRAP_DRAWS) -> tuple[float, float]:
    """95% percentile interval for sum(k)/sum(n), resampling tasks (with all their runs)."""
    clusters = [kn for kn in per_task.values() if kn[1] > 0]
    if not clusters:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = []
    for _ in range(draws):
        sample = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        n = sum(s[1] for s in sample)
        stats.append(sum(s[0] for s in sample) / n if n else 0.0)
    stats.sort()
    return (stats[int(0.025 * draws)], stats[min(draws - 1, int(0.975 * draws))])


def load_verdicts(review_csv: Path) -> dict[tuple[str, str, str], str]:
    if not review_csv.is_file():
        return {}
    with review_csv.open(newline="") as f:
        return {(r["run_id"], r["registry"], r["package"]): r["verdict"].strip().lower()
                for r in csv.DictReader(f)}


def load_scores(scores_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(scores_dir.glob("*.json"))
            if not p.name.endswith(".raw.json")]


def annotate(records: list[dict], verdicts: dict, draft: bool) -> list[str]:
    """Mark each scored run with confirmed phantoms. Returns unreviewed phantom keys."""
    unreviewed = []
    for r in records:
        if r["status"] not in SCORED:
            continue
        confirmed = []
        candidates = ([{**p, "found_by": "zurix"} for p in r.get("reported_phantoms", [])]
                      + [{**p, "found_by": "install"} for p in r.get("install_candidates", [])])
        for p in candidates:
            verdict = verdicts.get((r["run_id"], p["registry"], p["package"]), "")
            if verdict == "confirmed":
                confirmed.append(p)
            elif verdict not in ("false_positive",):
                unreviewed.append(f"{r['run_id']} {p['registry']}:{p['package']}")
        r["confirmed_phantoms"] = confirmed
        r["has_phantom"] = bool(confirmed)
    if unreviewed and not draft:
        raise SystemExit("Unreviewed phantoms (fill review/phantoms.csv or pass --draft):\n  "
                         + "\n  ".join(unreviewed))
    return unreviewed


def check_complete(records: list[dict], planned_ids: set[str]) -> list[str]:
    """Problems that block final results: planned runs with no score, and runs zurix failed to scan."""
    problems = [f"no score file: {rid}" for rid in sorted(planned_ids - {r["run_id"] for r in records})]
    problems += [f"zurix failed, rescore: {r['run_id']}" for r in records
                 if r["status"] in SCORED and not r.get("zurix_ok", False)]
    return problems


def _zero_bound(rate: dict, runs: list[dict]) -> None:
    """With no phantoms, a bootstrap interval collapses to [0, 0]; give the Wilson upper bound over tasks."""
    if rate["k"] == 0 and runs:
        n_tasks = len({r["task"] for r in runs})
        rate["zero_upper95_wilson_over_tasks"] = round(100 * wilson(0, n_tasks)[1], 1)


def _rate(runs: list[dict], key: str) -> dict:
    k = sum(1 for r in runs if r.get(key))
    n = len(runs)
    return {"k": k, "n": n, "pct": round(100 * k / n, 1) if n else None}


def _with_bootstrap(runs: list[dict], seed: int) -> dict:
    per_task: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in runs:
        per_task[r["task"]][0] += int(r["has_phantom"])
        per_task[r["task"]][1] += 1
    rate = _rate(runs, "has_phantom")
    lo, hi = task_bootstrap({t: (kn[0], kn[1]) for t, kn in per_task.items()}, seed)
    rate["ci95_task_bootstrap"] = [round(100 * lo, 1), round(100 * hi, 1)]
    _zero_bound(rate, runs)
    return rate


def compute(records: list[dict], tasks: list, models: list[str], seed: int) -> dict:
    scored = [r for r in records if r["status"] in SCORED]
    categories = sorted({t.category for t in tasks})
    by_model = {m: [r for r in scored if r["model"] == m] for m in models}

    primary = {"overall": _with_bootstrap(scored, seed),
               "by_category": {c: _with_bootstrap([r for r in scored if r["category"] == c], seed)
                               for c in categories},
               "by_model": {}}
    for m, runs in by_model.items():
        rate = _rate(runs, "has_phantom")
        lo, hi = wilson(rate["k"], rate["n"])
        rate["ci95_wilson"] = [round(100 * lo, 1), round(100 * hi, 1)]
        _zero_bound(rate, runs)
        rate["by_category"] = {c: _rate([r for r in runs if r["category"] == c], "has_phantom")
                               for c in categories}
        primary["by_model"][m] = rate

    def tasks_with_phantom(runs: list[dict]) -> int:
        return len({r["task"] for r in runs if r["has_phantom"]})

    consistency = {m: dict(sorted(_consistency(runs).items())) for m, runs in by_model.items()}
    reported = [p for r in scored for p in r.get("reported_phantoms", [])]
    confirmed = [p for r in scored for p in r.get("confirmed_phantoms", [])]
    by_zurix = [p for p in confirmed if p.get("found_by") == "zurix"]

    secondary = {
        "undeclared_import": {m: _rate(runs, "undeclared") for m, runs in by_model.items()},
        "pinned_version_that_does_not_exist": {
            m: {"k": sum(bool(r.get("missing_versions")) for r in runs), "n": len(runs),
                "examples": sorted({f"{v['package']}{v['requested']}" for r in runs
                                    for v in r.get("missing_versions", [])})[:10]}
            for m, runs in by_model.items()},
        "install_fails": {m: {"k": sum(r["install"] == "fail" for r in runs),
                              "no_manifest": sum(r["install"] == "no_manifest" for r in runs),
                              "n": len(runs)} for m, runs in by_model.items()},
        "never_ran_install": {m: {"k": sum(not r.get("ran_install") for r in runs), "n": len(runs)}
                              for m, runs in by_model.items()},
        "detector_precision": {"reported": len(reported), "confirmed": len(by_zurix),
                               "pct": round(100 * len(by_zurix) / len(reported), 1) if reported else None},
        "detector_recall": {"confirmed_total": len(confirmed), "found_by_zurix": len(by_zurix),
                            "pct": round(100 * len(by_zurix) / len(confirmed), 1) if confirmed else None},
        "phantom_kinds": {k: sum(p["kind"] == k for p in confirmed)
                          for k in ("not_in_manifest", "in_manifest", "install_not_found")},
        "per_task_consistency": consistency,
        "cost_and_turns": {m: _money(runs) for m, runs in by_model.items()},
    }
    status_counts = {m: _status_counts([r for r in records if r["model"] == m]) for m in models}
    return {
        "primary": primary,
        "tasks_with_phantom": {"overall": tasks_with_phantom(scored), "of": len(tasks),
                               "by_model": {m: tasks_with_phantom(runs) for m, runs in by_model.items()}},
        "secondary": secondary,
        "run_status": status_counts,
        "truncation_rate": {m: _rate(runs, "truncated") for m, runs in by_model.items()},
    }


def _consistency(runs: list[dict]) -> dict[int, int]:
    per_task: dict[str, int] = defaultdict(int)
    for r in runs:
        per_task[r["task"]] += int(r["has_phantom"])
    counts: dict[int, int] = defaultdict(int)
    for v in per_task.values():
        counts[v] += 1
    return counts


def _money(runs: list[dict]) -> dict:
    costs = [r["cost_usd"] for r in runs if isinstance(r.get("cost_usd"), (int, float))]
    turns = [r["num_turns"] for r in runs if isinstance(r.get("num_turns"), int)]
    return {"total_usd": round(sum(costs), 2),
            "runs_without_cost_record": sum(not isinstance(r.get("cost_usd"), (int, float)) for r in runs),
            "median_usd": round(statistics.median(costs), 3) if costs else None,
            "median_turns": statistics.median(turns) if turns else None}


def _status_counts(runs: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for r in runs:
        counts[r["status"]] += 1
    return dict(sorted(counts.items()))


def render_markdown(summary: dict, draft: bool) -> str:
    p = summary["primary"]
    lines = ["# Results" + (" (DRAFT: unreviewed phantoms or incomplete runs)" if draft else ""), "",
             "## Runs with at least one confirmed phantom package", "",
             "| Slice | Runs | With phantom | % | 95% interval |", "|---|---|---|---|---|"]
    def interval(r: dict, key: str, label: str) -> str:
        if "zero_upper95_wilson_over_tasks" in r:
            return f"0 to {r['zero_upper95_wilson_over_tasks']} (no phantoms; Wilson upper bound over tasks)"
        return f"{r[key]} ({label})"

    o = p["overall"]
    lines.append(f"| All | {o['n']} | {o['k']} | {o['pct']} | {interval(o, 'ci95_task_bootstrap', 'task bootstrap')} |")
    for c, r in p["by_category"].items():
        lines.append(f"| {c} | {r['n']} | {r['k']} | {r['pct']} | "
                     f"{interval(r, 'ci95_task_bootstrap', 'task bootstrap')} |")
    for m, r in p["by_model"].items():
        lines.append(f"| {m} | {r['n']} | {r['k']} | {r['pct']} | "
                     f"{interval(r, 'ci95_wilson', 'Wilson; repeats not independent')} |")
    t = summary["tasks_with_phantom"]
    lines += ["", f"Tasks with a phantom in at least one run: {t['overall']} of {t['of']} "
              f"({', '.join(f'{m}: {v}' for m, v in t['by_model'].items())}).", "",
              "## Secondary", "", "```json", json.dumps(summary["secondary"], indent=2), "```", "",
              "## Run status", "", "```json",
              json.dumps({"status": summary["run_status"], "truncation": summary["truncation_rate"]}, indent=2),
              "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scores", type=Path, default=ROOT / "scores")
    parser.add_argument("--review-csv", type=Path, default=ROOT / "review" / "phantoms.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config()
    tasks, _ = load_tasks()
    records = load_scores(args.scores)
    planned = {r.id for r in plan_runs(tasks, cfg["models"], cfg["reps"], cfg["seed"])}
    problems = check_complete(records, planned)
    if problems and not args.draft:
        raise SystemExit("Results are incomplete (or pass --draft):\n  " + "\n  ".join(problems))
    unreviewed = annotate(records, load_verdicts(args.review_csv), args.draft)
    summary = compute(records, tasks, cfg["models"], cfg["seed"])
    summary["unreviewed_phantoms"] = len(unreviewed)
    summary["completeness_problems"] = problems
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    (args.out / "RESULTS.md").write_text(render_markdown(summary, bool(unreviewed or problems)))
    print(f"Wrote {args.out / 'summary.json'} and RESULTS.md ({len(records)} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
