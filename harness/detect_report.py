"""Experiment 2: how well zurix catches broken dependencies in fresh agent output.

    ZX_EXPERIMENT=exp2 python -m harness.detect_report --review   # build/extend review/findings.csv
    ZX_EXPERIMENT=exp2 python -m harness.detect_report            # → results/detection.json + DETECTION.md

Ground truth comes from a clean install of each run's manifest (independent of zurix), plus a
person's verdict on every finding. A finding is one (run, package) problem:
  missing_package        the package doesn't exist on its registry
  missing_version        the package exists, but no release satisfies the declared version/range
  other_install_failure  the install failed for another reason (build error, platform, …)
`found_by` says who reported it: zurix, the install, or both.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from harness.common import BASE, load_config, load_tasks, plan_runs
from harness.report import task_bootstrap, wilson
from harness.score import install_findings, resolution_findings

FIELDS = ["run_id", "model", "task", "package", "registry", "problem", "spec", "found_by", "verdict",
          "reviewed_on", "note"]
SCORED = {"done", "truncated"}
DEPENDENCY_PROBLEMS = {"missing_package", "missing_version"}


def norm(registry: str, package: str) -> str:
    """Merge key for a package: PEP 503 for PyPI (notion_client == notion-client), lower-case for npm."""
    return re.sub(r"[-_.]+", "-", package).lower() if registry == "pypi" else package.lower()


def findings_for(record: dict, raw: dict) -> list[dict]:
    """Every dependency problem in one run, merged across zurix and the clean install."""
    found: dict[tuple[str, str, str], dict] = {}

    def add(registry: str, package: str, problem: str, source: str, spec: str = "") -> None:
        key = (registry, norm(registry, package), problem)
        row = found.setdefault(key, {"package": package, "registry": registry, "problem": problem,
                                     "spec": spec, "found_by": set()})
        row["found_by"].add(source)
        row["spec"] = row["spec"] or spec

    for p in record.get("reported_phantoms", []):
        add(p["registry"], p["package"], "missing_package", "zurix")
    for v in record.get("zurix_version_not_found", []):
        add(v["registry"], v["package"], "missing_version", "zurix", v["spec"])
    installs = raw.get("installs") or []
    missing_packages, missing_versions = install_findings(installs)
    resolved_packages, resolved_versions = resolution_findings(raw.get("resolutions") or [])
    missing_packages += resolved_packages
    missing_versions += resolved_versions
    for p in missing_packages:
        add(p["registry"], p["package"], "missing_package", "install")
    for v in missing_versions:
        add(v["registry"], v["package"], "missing_version", "install", v["requested"])
    install_failed = any(r.get("exit") != 0 for r in installs)
    if install_failed and not missing_packages and not missing_versions:
        add("", "", "other_install_failure", "install")

    rows = []
    for row in found.values():
        rows.append({"run_id": record["run_id"], "model": record["model"], "task": record["task"],
                     "package": row["package"], "registry": row["registry"], "problem": row["problem"],
                     "spec": row["spec"], "found_by": "+".join(sorted(row["found_by"])),
                     "verdict": "", "reviewed_on": "", "note": ""})
    return sorted(rows, key=lambda r: (r["problem"], r["registry"], r["package"].lower()))


def _key(row: dict) -> tuple[str, str, str, str]:
    return (row["run_id"], row["registry"], norm(row["registry"], row["package"]), row["problem"])


def update_review(scores: Path, review_csv: Path) -> int:
    existing = list(csv.DictReader(review_csv.open(newline=""))) if review_csv.is_file() else []
    seen = {_key(r) for r in existing}
    added = 0
    for path in sorted(scores.glob("*.json")):
        if path.name.endswith(".raw.json"):
            continue
        record = json.loads(path.read_text())
        raw_path = path.with_name(path.name.replace(".json", ".raw.json"))
        if record.get("status") not in SCORED or not raw_path.is_file():
            continue
        for row in findings_for(record, json.loads(raw_path.read_text())):
            if _key(row) not in seen:
                existing.append(row)
                seen.add(_key(row))
                added += 1
    review_csv.parent.mkdir(parents=True, exist_ok=True)
    with review_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(existing)
    return added


def _pct(k: int, n: int) -> float | None:
    return round(100 * k / n, 1) if n else None


def _with_wilson(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "pct": _pct(k, n), "ci95_wilson": [round(100 * lo, 1), round(100 * hi, 1)]}


def compute(records: list[dict], findings: list[dict], models: list[str], seed: int) -> dict:
    scored = [r for r in records if r["status"] in SCORED]
    real = [f for f in findings if f["verdict"] == "real"]
    zurix_findings = [f for f in findings if "zurix" in f["found_by"]]

    # Recall: problems a clean install revealed independently (so the denominator doesn't depend on zurix).
    independent = [f for f in real if f["problem"] in DEPENDENCY_PROBLEMS and "install" in f["found_by"]]
    caught = [f for f in independent if "zurix" in f["found_by"]]
    recall = {"overall": _with_wilson(len(caught), len(independent)), "by_problem": {}}
    for problem in sorted(DEPENDENCY_PROBLEMS):
        sub = [f for f in independent if f["problem"] == problem]
        recall["by_problem"][problem] = _with_wilson(sum("zurix" in f["found_by"] for f in sub), len(sub))
    # Repeats of a task often repeat the same mistake, so findings are clustered: also count distinct
    # mistakes (task, package, problem, spec; caught only if flagged every time it appeared) and give
    # a bootstrap over tasks.
    distinct: dict[tuple, list[bool]] = defaultdict(list)
    per_task: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in independent:
        hit = "zurix" in f["found_by"]
        distinct[(f["task"], f["registry"], norm(f["registry"], f["package"]), f["problem"], f["spec"])].append(hit)
        per_task[f["task"]][0] += int(hit)
        per_task[f["task"]][1] += 1
    recall["distinct_mistakes"] = _with_wilson(sum(all(h) for h in distinct.values()), len(distinct))
    lo, hi = task_bootstrap({t: (kn[0], kn[1]) for t, kn in per_task.items()}, seed)
    recall["overall"]["ci95_task_bootstrap"] = [round(100 * lo, 1), round(100 * hi, 1)]

    # Precision: every zurix flag, judged by a person.
    precision = _with_wilson(sum(f["verdict"] == "real" for f in zurix_findings), len(zurix_findings))

    broken_runs = {f["run_id"] for f in real if f["problem"] in DEPENDENCY_PROBLEMS}
    flagged_runs = {f["run_id"] for f in zurix_findings}
    per_model = {}
    for m in models:
        runs = [r for r in scored if r["model"] == m]
        ids = {r["run_id"] for r in runs}
        per_task: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in runs:
            per_task[r["task"]][0] += int(r["run_id"] in broken_runs)
            per_task[r["task"]][1] += 1
        lo, hi = task_bootstrap({t: (kn[0], kn[1]) for t, kn in per_task.items()}, seed)
        broken = len(ids & broken_runs)
        per_model[m] = {
            "runs": len(runs),
            "broken_runs": broken,
            "broken_pct": _pct(broken, len(runs)),
            "broken_ci95_task_bootstrap": [round(100 * lo, 1), round(100 * hi, 1)],
            "broken_runs_flagged_by_zurix": len(ids & broken_runs & flagged_runs),
            "runs_flagged_by_zurix": len(ids & flagged_runs),
            "runs_flagged_without_a_real_problem": len((ids & flagged_runs) - broken_runs),
            # What a buyer sees: the check failed (zurix exit 1) on a run with no real dependency
            # problem; the reasons are listed so undeclared imports etc. can be judged separately.
            "check_failed_without_a_real_dependency_problem": _failed_without(runs, broken_runs),
        }
    return {
        "recall": recall,
        "precision": precision,
        "per_model": per_model,
        "found_only_by_zurix": sum(f["found_by"] == "zurix" for f in real),
        "other_install_failures": sum(f["problem"] == "other_install_failure" for f in findings),
        "findings_by_verdict": dict(sorted(_count(f["verdict"] or "unreviewed" for f in findings).items())),
    }


def _failed_without(runs: list[dict], broken_runs: set[str]) -> dict:
    hits = [r for r in runs if r.get("zurix_exit") == 1 and r["run_id"] not in broken_runs]
    reasons = _count(reason for r in hits for reason in _reasons(r))
    return {"runs": len(hits), "reasons": dict(sorted(reasons.items()))}


def _reasons(record: dict) -> list[str]:
    reasons = []
    if record.get("reported_phantoms"):
        reasons.append("phantom package")
    if record.get("zurix_version_not_found"):
        reasons.append("version that doesn't exist")
    if record.get("undeclared"):
        reasons.append("undeclared import")
    if record.get("zurix_suspicious"):
        reasons.append("suspicious package")
    return reasons or ["other"]


def _count(items) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item] += 1
    return counts


def check_complete(records: list[dict], findings: list[dict], planned: set[str]) -> list[str]:
    problems = [f"no score file: {rid}" for rid in sorted(planned - {r["run_id"] for r in records})]
    problems += [f"zurix failed, rescore: {r['run_id']}" for r in records
                 if r["status"] in SCORED and not r.get("zurix_ok", False)]
    problems += [f"unreviewed finding: {f['run_id']} {f['registry']}:{f['package']} ({f['problem']})"
                 for f in findings if f["verdict"] not in ("real", "false_alarm", "not_dependency")]
    return problems


def render(summary: dict, draft: bool) -> str:
    rec, prec = summary["recall"], summary["precision"]
    lines = ["# Detection results" + (" (DRAFT)" if draft else ""), "",
             f"**Recall** (dependency problems a clean install revealed, flagged by zurix): "
             f"{rec['overall']['k']} of {rec['overall']['n']} = {rec['overall']['pct']}% "
             f"(95% Wilson {rec['overall']['ci95_wilson']}; task bootstrap "
             f"{rec['overall'].get('ci95_task_bootstrap')})",
             f"Distinct mistakes caught every time they appeared: {rec['distinct_mistakes']['k']} of "
             f"{rec['distinct_mistakes']['n']} ({rec['distinct_mistakes']['pct']}%)", ""]
    for problem, r in rec["by_problem"].items():
        lines.append(f"- {problem}: {r['k']} of {r['n']} ({r['pct']}%)")
    lines += ["", f"**Precision** (zurix flags that were real): {prec['k']} of {prec['n']} = {prec['pct']}% "
              f"(95% Wilson {prec['ci95_wilson']})", "",
              "| Model | Runs | Broken-dependency runs | % (task bootstrap) | Flagged by zurix | "
              "Flagged without a real problem | Check failed without a real dependency problem |",
              "|---|---|---|---|---|---|---|"]
    for m, s in summary["per_model"].items():
        failed = s["check_failed_without_a_real_dependency_problem"]
        lines.append(f"| {m} | {s['runs']} | {s['broken_runs']} | {s['broken_pct']} {s['broken_ci95_task_bootstrap']} | "
                     f"{s['broken_runs_flagged_by_zurix']} | {s['runs_flagged_without_a_real_problem']} | "
                     f"{failed['runs']} {failed['reasons'] or ''} |")
    lines += ["", f"Problems found only by zurix (no install signal, e.g. undeclared imports of missing "
              f"packages): {summary['found_only_by_zurix']}. Other install failures: "
              f"{summary['other_install_failures']}.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scores", type=Path, default=BASE / "scores")
    parser.add_argument("--review-csv", type=Path, default=BASE / "review" / "findings.csv")
    parser.add_argument("--out", type=Path, default=BASE / "results")
    parser.add_argument("--review", action="store_true", help="only add new findings to the review list")
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args(argv)

    if args.review:
        print(f"{update_review(args.scores, args.review_csv)} new findings in {args.review_csv}")
        return 0
    cfg = load_config()
    tasks, _ = load_tasks()
    records = [json.loads(p.read_text()) for p in sorted(args.scores.glob("*.json"))
               if not p.name.endswith(".raw.json")]
    findings = list(csv.DictReader(args.review_csv.open(newline=""))) if args.review_csv.is_file() else []
    planned = {r.id for r in plan_runs(tasks, cfg["models"], cfg["reps"], cfg["seed"])}
    problems = check_complete(records, findings, planned)
    if problems and not args.draft:
        raise SystemExit("Results are incomplete (or pass --draft):\n  " + "\n  ".join(problems[:50]))
    summary = compute(records, findings, cfg["models"], cfg["seed"])
    summary["completeness_problems"] = len(problems)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "detection.json").write_text(json.dumps(summary, indent=2))
    (args.out / "DETECTION.md").write_text(render(summary, bool(problems)))
    print(f"Wrote {args.out / 'detection.json'} and DETECTION.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
