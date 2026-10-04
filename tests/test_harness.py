"""Counting rules, transcript facts and statistics, without Docker or the API."""

from __future__ import annotations

import csv
import io
import json
import tarfile
from pathlib import Path

import pytest
from harness.common import load_config, load_tasks, plan_runs
from harness.report import annotate, check_complete, compute, task_bootstrap, wilson
from harness.run import classify
from harness.score import install_candidates, interpret, update_review
from harness.transcript import source_files, summarize

META = {"run_id": "py-n1__m__r1", "task": "py-n1", "language": "python", "category": "niche",
        "model": "m", "rep": 1, "status": "done", "ran_install": True, "ran_code": False,
        "cost_usd": 0.4, "num_turns": 7}


def _raw(phantom=(), undeclared=(), details=None, suspicious=(), installs=()):
    return {"zurix": {"exit": 1, "result": {"checks": {
        "imports": {"phantom": [{"name": n, "package": n, "source": s, "files": []} for n, s in phantom],
                    "undeclared": [{"name": n, "package": n, "source": "pypi", "files": []} for n in undeclared],
                    "unverified": []},
        "supply_chain": {"details": details or {},
                         "suspicious_packages": [{"name": n, "source": s, "score": 3} for n, s in suspicious]}}}},
        "installs": list(installs)}


# ── Tasks and run plan ──────────────────────────────────────────────────────────

def test_task_set_is_balanced() -> None:
    tasks, suffix = load_tasks()
    assert len(tasks) == 30
    assert sum(t.language == "python" for t in tasks) == 15
    for category in ("mainstream", "niche", "integration"):
        assert sum(t.category == category for t in tasks) == 10
    assert "requirements.txt or package.json" in suffix
    assert not any("pip install" in t.prompt or "npm install" in t.prompt for t in tasks)


def test_run_plan_is_complete_seeded_and_interleaved() -> None:
    cfg = load_config()
    tasks, _ = load_tasks()
    runs = plan_runs(tasks, cfg["models"], cfg["reps"], cfg["seed"])
    assert len(runs) == 270 and len({r.id for r in runs}) == 270
    assert [r.id for r in runs] == [r.id for r in plan_runs(tasks, cfg["models"], cfg["reps"], cfg["seed"])]
    assert len({r.model for r in runs[:9]}) == 3


# ── Run classification ──────────────────────────────────────────────────────────

FACTS = {"has_result": True, "budget_hit": False}


@pytest.mark.parametrize(("exit_code", "facts", "files", "status"), [
    (1, {"has_result": False, "budget_hit": False}, [], "infra_failed"),
    (0, FACTS, ["main.py"], "done"),
    (124, {"has_result": False, "budget_hit": False}, ["main.py"], "truncated"),
    (0, {"has_result": True, "budget_hit": True}, ["main.py"], "truncated"),
    (0, FACTS, [], "no_code"),
    (1, {"has_result": True, "budget_hit": False, "api_error_status": 401}, [], "infra_failed"),
    (1, {"has_result": True, "budget_hit": False, "api_error_status": 529}, ["main.py"], "infra_failed"),
])
def test_classify(exit_code, facts, files, status) -> None:
    assert classify(exit_code, facts, files) == status


# ── Transcript facts ────────────────────────────────────────────────────────────

def _bash(cmd: str) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}}


def test_summarize_finds_installs_code_runs_and_budget_stop() -> None:
    events = [_bash("pip install -r requirements.txt"), _bash("python main.py sample.csv"),
              {"type": "result", "subtype": "error_max_budget_usd", "total_cost_usd": 1.5, "num_turns": 30}]
    facts = summarize(events)
    assert facts["ran_install"] and facts["ran_code"] and facts["budget_hit"]
    assert (facts["cost_usd"], facts["num_turns"]) == (1.5, 30)


def test_summarize_without_installs() -> None:
    facts = summarize([_bash("ls -la"), {"type": "result", "subtype": "success"}])
    assert not facts["ran_install"] and not facts["ran_code"] and not facts["budget_hit"]


def test_source_files_from_workspace(tmp_path: Path) -> None:
    tar_path = tmp_path / "workspace.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for name in ("./main.py", "./requirements.txt", "./src/index.ts"):
            data = b"x"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    assert source_files(tar_path) == ["./main.py", "./src/index.ts"]
    assert source_files(tmp_path / "missing.tar.gz") == []


# ── Scoring ─────────────────────────────────────────────────────────────────────

def test_interpret_counts_imported_and_declared_phantoms_once() -> None:
    raw = _raw(phantom=[("heic_exif", "pypi")], undeclared=["requests"],
               details={"heic_exif": {"status": "not_found"}, "fake-dbf": {"status": "not_found"},
                        "left-pad": {"status": "ok"}, "slowpkg": {"status": "unavailable"}},
               suspicious=[("heic_exif", "pypi"), ("fake-dbf", "npm")],
               installs=[{"manifest": "requirements.txt", "cmd": "pip", "exit": 0},
                         {"manifest": "package.json", "cmd": "npm", "exit": 1}])
    record = interpret(raw, META)
    assert record["reported_phantoms"] == [
        {"package": "heic_exif", "registry": "pypi", "kind": "not_in_manifest"},
        {"package": "fake-dbf", "registry": "npm", "kind": "in_manifest"}]
    assert record["undeclared"] == ["requests"]
    assert record["unverified"] == ["slowpkg"]
    assert record["install"] == "fail" and record["zurix_ok"]


@pytest.mark.parametrize(("installs", "expected"), [
    ([], "no_manifest"), ([{"exit": 0}], "pass"), ([{"exit": None}], "fail")])
def test_install_outcome(installs, expected) -> None:
    assert interpret(_raw(installs=installs), META)["install"] == expected


def test_review_log_is_appended_once(tmp_path: Path) -> None:
    scores = tmp_path / "scores"
    scores.mkdir()
    record = interpret(_raw(phantom=[("heic_exif", "pypi")]), META)
    (scores / "a.json").write_text(json.dumps(record))
    review = tmp_path / "phantoms.csv"
    assert update_review(scores, review) == 1
    assert update_review(scores, review) == 0
    rows = list(csv.DictReader(review.open()))
    assert rows[0]["registry_url"] == "https://pypi.org/project/heic_exif/" and rows[0]["verdict"] == ""


# ── Statistics and report ───────────────────────────────────────────────────────

def test_wilson_matches_known_values() -> None:
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-4)
    lo, hi = wilson(5, 10)
    assert (lo, hi) == (pytest.approx(0.2366, abs=1e-4), pytest.approx(0.7634, abs=1e-4))


def test_task_bootstrap_is_seeded_and_degenerate_when_tasks_agree() -> None:
    same = {f"t{i}": (1, 3) for i in range(10)}
    assert task_bootstrap(same, seed=1, draws=500) == (pytest.approx(1 / 3), pytest.approx(1 / 3))
    mixed = {"a": (3, 3), "b": (0, 3), "c": (1, 3)}
    assert task_bootstrap(mixed, seed=7, draws=500) == task_bootstrap(mixed, seed=7, draws=500)


def _record(task, model, category, status="done", phantoms=()):
    return {"run_id": f"{task}__{model}", "task": task, "model": model, "category": category,
            "language": "python", "rep": 1, "status": status, "truncated": status == "truncated",
            "reported_phantoms": [{"package": p, "registry": "pypi", "kind": "not_in_manifest"} for p in phantoms],
            "undeclared": [], "install": "pass", "ran_install": True, "cost_usd": 0.1, "num_turns": 3}


def test_report_rules_for_no_code_truncated_and_false_positives() -> None:
    tasks, _ = load_tasks()
    records = [_record("py-n1", "m1", "niche", phantoms=["fakepkg"]),
               _record("py-n1", "m2", "niche", status="truncated", phantoms=["realpkg"]),
               _record("py-m1", "m1", "mainstream", status="no_code"),
               _record("py-m1", "m2", "mainstream")]
    verdicts = {("py-n1__m1", "pypi", "fakepkg"): "confirmed",
                ("py-n1__m2", "pypi", "realpkg"): "false_positive"}
    annotate(records, verdicts, draft=False)
    summary = compute(records, tasks, ["m1", "m2"], seed=1)
    overall = summary["primary"]["overall"]
    assert (overall["k"], overall["n"]) == (1, 3)
    assert summary["primary"]["by_model"]["m1"]["n"] == 1
    assert summary["secondary"]["detector_precision"] == {"reported": 2, "confirmed": 1, "pct": 50.0}
    assert summary["truncation_rate"]["m2"]["k"] == 1
    assert summary["run_status"]["m1"] == {"done": 1, "no_code": 1}


def test_unreviewed_phantoms_block_the_final_report() -> None:
    records = [_record("py-n1", "m1", "niche", phantoms=["fakepkg"])]
    with pytest.raises(SystemExit, match="Unreviewed"):
        annotate(records, {}, draft=False)
    assert annotate([_record("py-n1", "m1", "niche", phantoms=["fakepkg"])], {}, draft=True)


# ── Independent check on the detector, completeness, zero results ──────────────

PIP_FAIL = ("ERROR: Could not find a version that satisfies the requirement heic-reader-pro (from versions: none)\n"
            "ERROR: No matching distribution found for heic-reader-pro")
NPM_FAIL = ("npm error 404 Not Found - GET https://registry.npmjs.org/@fake%2fdbf-kit - Not found\n"
            "npm error 404  '@fake/dbf-kit@^1.0.0' is not in this registry.")


def test_install_output_yields_missing_package_candidates() -> None:
    found = install_candidates([{"manifest": "requirements.txt", "exit": 1, "output_tail": PIP_FAIL},
                                {"manifest": "package.json", "exit": 1, "output_tail": NPM_FAIL}])
    assert found == [{"package": "heic-reader-pro", "registry": "pypi"},
                     {"package": "@fake/dbf-kit", "registry": "npm"}]


def test_nonexistent_pinned_versions_are_separate_from_missing_packages() -> None:
    from harness.score import install_findings

    pip_out = ("ERROR: Could not find a version that satisfies the requirement exifread==0.14.0 "
               "(from versions: 1.3.0, 3.5.1)\nERROR: No matching distribution found for exifread==0.14.0")
    npm_out = "npm error notarget No matching version found for geotiff@^9.9.0.\n"
    packages, versions = install_findings([{"manifest": "requirements.txt", "output_tail": pip_out},
                                           {"manifest": "package.json", "output_tail": npm_out}])
    assert packages == []
    assert versions == [{"package": "exifread", "registry": "pypi", "requested": "==0.14.0"},
                        {"package": "geotiff", "registry": "npm", "requested": "^9.9.0"}]


def test_install_candidates_skip_what_zurix_already_reported(tmp_path: Path) -> None:
    raw = _raw(phantom=[("heic-reader-pro", "pypi")],
               installs=[{"manifest": "requirements.txt", "exit": 1, "output_tail": PIP_FAIL},
                         {"manifest": "package.json", "exit": 1, "output_tail": NPM_FAIL}])
    record = interpret(raw, META)
    assert record["install_candidates"] == [{"package": "@fake/dbf-kit", "registry": "npm",
                                             "kind": "install_not_found"}]
    scores = tmp_path / "scores"
    scores.mkdir()
    (scores / "a.json").write_text(json.dumps(record))
    review = tmp_path / "phantoms.csv"
    update_review(scores, review)
    assert [(r["package"], r["found_by"]) for r in csv.DictReader(review.open())] == [
        ("heic-reader-pro", "zurix"), ("@fake/dbf-kit", "install")]


def test_phantom_found_only_by_install_counts_and_lowers_recall() -> None:
    tasks, _ = load_tasks()
    rec = _record("py-n1", "m1", "niche", phantoms=["zfound"])
    rec["install_candidates"] = [{"package": "missed", "registry": "pypi", "kind": "install_not_found"}]
    verdicts = {("py-n1__m1", "pypi", "zfound"): "confirmed", ("py-n1__m1", "pypi", "missed"): "confirmed"}
    annotate([rec], verdicts, draft=False)
    summary = compute([rec], tasks, ["m1"], seed=1)
    assert summary["secondary"]["detector_recall"] == {"confirmed_total": 2, "found_by_zurix": 1, "pct": 50.0}
    assert summary["secondary"]["phantom_kinds"]["install_not_found"] == 1


def test_completeness_flags_missing_scores_and_zurix_failures() -> None:
    ok = {**_record("py-m1", "m1", "mainstream"), "zurix_ok": True}
    broken = {**_record("py-m2", "m1", "mainstream"), "zurix_ok": False}
    problems = check_complete([ok, broken], {"py-m1__m1", "py-m2__m1", "py-m3__m1"})
    assert problems == ["no score file: py-m3__m1", "zurix failed, rescore: py-m2__m1"]


def test_zero_result_reports_a_task_level_upper_bound() -> None:
    tasks, _ = load_tasks()
    records = [_record(t, "m1", "mainstream") for t in ("py-m1", "py-m2", "py-m3")]
    for r in records:
        r["run_id"] = r["task"] + "__m1"
    annotate(records, {}, draft=False)
    overall = compute(records, tasks, ["m1"], seed=1)["primary"]["overall"]
    assert overall["k"] == 0
    assert overall["zero_upper95_wilson_over_tasks"] == round(100 * wilson(0, 3)[1], 1)
