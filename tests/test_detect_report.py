"""Experiment 2 detection metrics: merging findings, recall against install truth, precision."""

from __future__ import annotations

from harness.detect_report import check_complete, compute, findings_for

PIP_MISSING_VERSION = ("ERROR: Could not find a version that satisfies the requirement openpyxl>=3.6.0 "
                       "(from versions: 3.0.10, 3.1.5)\nERROR: No matching distribution found for openpyxl>=3.6.0")
PIP_MISSING_PACKAGE = ("ERROR: Could not find a version that satisfies the requirement fakepkg==1.0 "
                       "(from versions: none)\nERROR: No matching distribution found for fakepkg==1.0")


def _record(run_id="t1__haiku__r1", task="t1", model="haiku", phantoms=(), versions=(), status="done"):
    return {"run_id": run_id, "task": task, "model": model, "status": status, "zurix_ok": True,
            "reported_phantoms": [{"package": p, "registry": "pypi", "kind": k} for p, k in phantoms],
            "zurix_version_not_found": [{"package": p, "registry": "pypi", "spec": s} for p, s in versions]}


def _raw(*outputs, exit_code=1):
    return {"installs": [{"manifest": "requirements.txt", "exit": exit_code, "output_tail": o} for o in outputs]}


def test_zurix_and_install_agreeing_on_a_missing_version_is_one_finding_found_by_both() -> None:
    rows = findings_for(_record(versions=[("openpyxl", ">=3.6.0")]), _raw(PIP_MISSING_VERSION))
    assert [(r["package"], r["problem"], r["found_by"], r["spec"]) for r in rows] == [
        ("openpyxl", "missing_version", "install+zurix", ">=3.6.0")]


def test_install_only_and_zurix_only_findings() -> None:
    rows = findings_for(_record(phantoms=[("ghostlib", "not_in_manifest")]), _raw(PIP_MISSING_PACKAGE))
    assert {(r["package"], r["problem"], r["found_by"]) for r in rows} == {
        ("fakepkg", "missing_package", "install"), ("ghostlib", "missing_package", "zurix")}


def test_unexplained_install_failure_is_its_own_finding() -> None:
    rows = findings_for(_record(), _raw("error: command 'gcc' failed"))
    assert [(r["problem"], r["found_by"]) for r in rows] == [("other_install_failure", "install")]
    assert findings_for(_record(), _raw("ok", exit_code=0)) == []


def _finding(run_id, problem, found_by, verdict, model="haiku", package="p"):
    return {"run_id": run_id, "model": model, "task": run_id.split("__")[0], "package": package,
            "registry": "pypi", "problem": problem, "spec": "", "found_by": found_by, "verdict": verdict}


def test_recall_uses_only_install_revealed_problems_and_precision_uses_every_zurix_flag() -> None:
    records = [_record(f"t{i}__haiku__r1", f"t{i}") for i in range(1, 6)] + [_record("t1__sonnet__r1", "t1", "sonnet")]
    findings = [
        _finding("t1__haiku__r1", "missing_version", "install+zurix", "real"),
        _finding("t2__haiku__r1", "missing_package", "install", "real", package="missed"),
        _finding("t3__haiku__r1", "missing_package", "zurix", "real", package="undeclared-ghost"),
        _finding("t4__haiku__r1", "missing_version", "zurix", "false_alarm"),
        _finding("t5__haiku__r1", "other_install_failure", "install", "not_dependency"),
        _finding("t1__sonnet__r1", "missing_version", "zurix", "false_alarm", model="sonnet"),
    ]
    s = compute(records, findings, ["haiku", "sonnet"], seed=1)
    assert (s["recall"]["overall"]["k"], s["recall"]["overall"]["n"]) == (1, 2)
    assert (s["precision"]["k"], s["precision"]["n"]) == (2, 4)
    assert s["per_model"]["haiku"]["broken_runs"] == 3
    assert s["per_model"]["haiku"]["broken_runs_flagged_by_zurix"] == 2
    assert s["per_model"]["haiku"]["runs_flagged_without_a_real_problem"] == 1
    assert s["per_model"]["sonnet"]["runs_flagged_without_a_real_problem"] == 1
    assert s["found_only_by_zurix"] == 1 and s["other_install_failures"] == 1


def test_completeness_requires_every_run_scored_and_every_finding_reviewed() -> None:
    records = [_record("t1__haiku__r1")]
    findings = [_finding("t1__haiku__r1", "missing_version", "zurix", "")]
    problems = check_complete(records, findings, {"t1__haiku__r1", "t2__haiku__r1"})
    assert problems[0] == "no score file: t2__haiku__r1"
    assert problems[1].startswith("unreviewed finding: t1__haiku__r1")


def test_pypi_spellings_merge_into_one_finding() -> None:
    out = ("ERROR: Could not find a version that satisfies the requirement notion_client==2.2.3 "
           "(from versions: 2.2.0, 2.2.1)\nERROR: No matching distribution found for notion_client==2.2.3")
    rows = findings_for(_record(versions=[("notion-client", "==2.2.3")]), _raw(out))
    assert [(r["problem"], r["found_by"]) for r in rows] == [("missing_version", "install+zurix")]


def test_per_dependency_resolution_reveals_every_bad_requirement() -> None:
    raw = {"installs": [{"manifest": "requirements.txt", "exit": 1, "output_tail": PIP_MISSING_VERSION}],
           "resolutions": [
               {"manifest": "requirements.txt", "requirement": "openpyxl>=3.6.0", "exit": 1,
                "output_tail": PIP_MISSING_VERSION},
               {"manifest": "requirements.txt", "requirement": "fakepkg==1.0", "exit": 1,
                "output_tail": PIP_MISSING_PACKAGE},
               # Real npm view output (npm 10): a bad range on a real package, and a missing package.
               {"manifest": "package.json", "requirement": "airtable@^2.1.0", "package": "airtable",
                "spec": "^2.1.0", "exit": 1, "stdout": "",
                "output_tail": "npm error code E404\nnpm error 404 No match found for version ^2.1.0"},
               {"manifest": "package.json", "requirement": "zx-nope@^1", "package": "zx-nope", "spec": "^1",
                "exit": 1, "stdout": "", "output_tail": "npm error code E404\nnpm error 404 Not Found - GET "
                "https://registry.npmjs.org/zx-nope - Not found"},
               {"manifest": "package.json", "requirement": "express@^4", "package": "express", "spec": "^4",
                "exit": 0, "stdout": "\"4.21.2\"", "output_tail": ""}]}
    rows = findings_for(_record(), raw)
    assert {(r["package"], r["problem"]) for r in rows} == {
        ("openpyxl", "missing_version"), ("fakepkg", "missing_package"),
        ("airtable", "missing_version"), ("zx-nope", "missing_package")}


def test_distinct_mistakes_and_buyer_facing_false_alarms() -> None:
    records = [_record(f"t1__haiku__r{i}", "t1") for i in (1, 2, 3)] + [
        {**_record("t2__sonnet__r1", "t2", "sonnet"), "zurix_exit": 1, "undeclared": ["requests"]}]
    findings = [_finding(f"t1__haiku__r{i}", "missing_version", "install+zurix", "real") for i in (1, 2)] + [
        _finding("t1__haiku__r3", "missing_version", "install", "real")]
    s = compute(records, findings, ["haiku", "sonnet"], seed=1)
    assert (s["recall"]["overall"]["k"], s["recall"]["overall"]["n"]) == (2, 3)
    assert (s["recall"]["distinct_mistakes"]["k"], s["recall"]["distinct_mistakes"]["n"]) == (0, 1)
    assert s["per_model"]["sonnet"]["check_failed_without_a_real_dependency_problem"] == {
        "runs": 1, "reasons": {"undeclared import": 1}}


def test_truncated_pip_output_still_tells_a_missing_version_from_a_missing_package() -> None:
    from harness.score import install_findings

    cut = (".0b1, 14.2.0, 14.3.0, 15.0.0, 16.0.0, 16.1.0b2)\n"
           "ERROR: No matching distribution found for stripe==10.13.0")
    packages, versions = install_findings([{"manifest": "requirements.txt", "output_tail": cut}])
    assert packages == [] and versions == [{"package": "stripe", "registry": "pypi", "requested": "==10.13.0"}]
    none_cut = "(from versions: none)\nERROR: No matching distribution found for fakepkg==1.0"
    packages, versions = install_findings([{"manifest": "requirements.txt", "output_tail": none_cut}])
    assert [p["package"] for p in packages] == ["fakepkg"] and versions == []
    bare = "ERROR: No matching distribution found for mystery==1.0"
    assert [p["package"] for p in install_findings([{"manifest": "requirements.txt", "output_tail": bare}])[0]] == ["mystery"]
