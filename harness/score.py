"""Score finished runs and keep the phantom hand-check log up to date.

    python -m harness.score                       # runs/ → scores/
    python -m harness.score --runs pilot/runs --scores pilot/scores
    python -m harness.score --review              # add newly reported phantoms to review/phantoms.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import urllib.parse
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.common import BASE, load_config

SCORED_STATUSES = {"done", "truncated"}
REVIEW_FIELDS = ["run_id", "package", "registry", "kind", "found_by", "registry_url", "verdict",
                 "reviewed_on", "note"]
_PIP_NO_VERSION = re.compile(r"Could not find a version that satisfies the requirement (\S+) "
                             r"\(from versions: ([^)]*)\)")
_PIP_NO_DIST = re.compile(r"No matching distribution found for (\S+)")
_PIP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_NPM_NO_VERSION = re.compile(r"No matching version found for ((?:@[^/\s]+/)?[^@\s]+)@(\S+?)\.?(?:\s|$)")
_NPM_404_URL = re.compile(r"404 Not Found - GET https://registry\.npmjs\.org/(\S+)")
_NPM_404_MSG = re.compile(r"'((?:@[^/\s']+/)?[^@\s']+)@[^'\s]*' is not in this registry")


_VERSION_LIST_TAIL = re.compile(r"(?:^|[\s,])\d[\w.!+-]*(?:,\s*\d[\w.!+-]*)+\)\s*$")


def _versions_listed_before(text: str, end: int) -> bool:
    """Whether the text just before `end` finishes a non-empty pip "(from versions: a, b, c)" list."""
    return bool(_VERSION_LIST_TAIL.search(text[max(0, end - 400):end].rstrip().removesuffix("ERROR:").rstrip()))


def install_findings(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """What a clean install says is missing: an independent check on the detector.

    Returns (packages it could not find at all, pinned versions that don't exist for a package that
    does). pip's "from versions: none" also fires when a package exists but has no build for this
    platform, so missing packages are only candidates for the hand check, never confirmations.
    """
    packages: dict[tuple[str, str], dict] = {}
    versions: dict[tuple[str, str], dict] = {}
    for r in records:
        text = r.get("output_tail") or ""
        if r.get("manifest") == "package.json":
            for name in [urllib.parse.unquote(m) for m in _NPM_404_URL.findall(text)] + _NPM_404_MSG.findall(text):
                name = name.strip().rstrip(".,;")
                packages.setdefault(("npm", name.lower()), {"package": name, "registry": "npm"})
            for name, wanted in _NPM_NO_VERSION.findall(text):
                versions.setdefault(("npm", name.lower()),
                                    {"package": name, "registry": "npm", "requested": wanted})
            continue
        seen_with_versions = set()
        for requirement, available in _PIP_NO_VERSION.findall(text):
            name = _PIP_NAME.match(requirement).group(0)
            seen_with_versions.add(name.lower())
            if available.strip() == "none":
                packages.setdefault(("pypi", name.lower()), {"package": name, "registry": "pypi"})
            else:
                versions.setdefault(("pypi", name.lower()), {"package": name, "registry": "pypi",
                                                             "requested": requirement[len(name):]})
        for match_ in _PIP_NO_DIST.finditer(text):
            requirement = match_.group(1)
            match = _PIP_NAME.match(requirement)
            if match and match.group(0).lower() not in seen_with_versions:
                name = match.group(0)
                if _versions_listed_before(text, match_.start()):
                    # The "Could not find a version…" line was cut off by output truncation, but the
                    # tail of its non-empty "(from versions: …)" list is there: the package exists.
                    versions.setdefault(("pypi", name.lower()), {"package": name, "registry": "pypi",
                                                                 "requested": requirement[len(name):].rstrip(";")})
                else:
                    packages.setdefault(("pypi", name.lower()), {"package": name, "registry": "pypi"})
    return list(packages.values()), list(versions.values())


def resolution_findings(resolutions: list[dict]) -> tuple[list[dict], list[dict]]:
    """Missing packages and missing versions from per-dependency resolution (pip --dry-run / npm view)."""
    packages: list[dict] = []
    versions: list[dict] = []
    for r in resolutions:
        if r.get("manifest") == "package.json":
            text = r.get("output_tail") or ""
            # npm view: a real package with no matching release says "No match found for version";
            # a package that doesn't exist says "404 Not Found - GET https://registry.npmjs.org/…".
            if "No match found for version" in text or (
                    r.get("exit") == 0 and (r.get("stdout") or "").strip() in ("", "[]")):
                versions.append({"package": r["package"], "registry": "npm", "requested": r["spec"]})
            elif "Not Found - GET https://registry.npmjs.org/" in text:
                packages.append({"package": r["package"], "registry": "npm"})
            continue
        if r.get("exit") == 0:
            continue
        found_packages, found_versions = install_findings([{**r, "manifest": "requirements.txt"}])
        packages += found_packages
        versions += found_versions
    return packages, versions


def install_candidates(records: list[dict]) -> list[dict]:
    return install_findings(records)[0]


def registry_url(registry: str, package: str) -> str:
    return (f"https://www.npmjs.com/package/{package}" if registry == "npm"
            else f"https://pypi.org/project/{package}/")


def interpret(raw: dict, meta: dict) -> dict:
    """Turn raw scoring facts into the per-run record the report reads."""
    zurix = raw.get("zurix") or {}
    checks = (zurix.get("result") or {}).get("checks") or {}
    imports = checks.get("imports") or {}
    details = (checks.get("supply_chain") or {}).get("details") or {}

    phantoms = [{"package": p["package"], "registry": p["source"], "kind": "not_in_manifest"}
                for p in imports.get("phantom", [])]
    seen = {(p["registry"], p["package"].lower()) for p in phantoms}
    sources = _declared_sources(checks)
    for name, info in sorted(details.items()):
        if (info or {}).get("status") == "not_found":
            registry = sources.get(name, "pypi")
            if (registry, name.lower()) not in seen:
                phantoms.append({"package": name, "registry": registry, "kind": "in_manifest"})

    unverified = [p["package"] for p in imports.get("unverified", [])]
    unverified += [n for n, info in sorted(details.items()) if (info or {}).get("status") == "unavailable"]

    records = raw.get("installs") or []
    reported = {(p["registry"], p["package"].lower()) for p in phantoms}
    missing_packages, missing_versions = install_findings(records)
    install_only = [{**c, "kind": "install_not_found"} for c in missing_packages
                    if (c["registry"], c["package"].lower()) not in reported]
    if not records:
        install = "no_manifest"
    elif all(r.get("exit") == 0 for r in records):
        install = "pass"
    else:
        install = "fail"

    return {
        "run_id": meta["run_id"], "task": meta["task"], "language": meta["language"],
        "category": meta["category"], "model": meta["model"], "rep": meta["rep"],
        "status": meta["status"], "truncated": meta["status"] == "truncated",
        "zurix_ok": "result" in zurix,
        "zurix_exit": zurix.get("exit"),
        "zurix_suspicious": sorted(p["name"] for p in (checks.get("supply_chain") or {}).get("suspicious_packages", [])
                                   if p.get("score", 0) >= 3),
        "project_dir": raw.get("project_dir", "."),
        "reported_phantoms": phantoms,
        "install_candidates": install_only,
        "missing_versions": missing_versions,
        "undeclared": sorted(p["package"] for p in imports.get("undeclared", [])),
        # zurix >= 0.4: declared versions/ranges that no published release satisfies.
        "zurix_version_not_found": [{"package": v["name"], "registry": v["source"], "spec": v["spec"]}
                                    for v in (checks.get("supply_chain") or {}).get("version_not_found", [])],
        "unverified": sorted(set(unverified)),
        "install": install,
        "install_records": [{k: r.get(k) for k in ("manifest", "cmd", "exit")} for r in records],
        "ran_install": meta.get("ran_install"), "ran_code": meta.get("ran_code"),
        "cost_usd": meta.get("cost_usd"), "num_turns": meta.get("num_turns"),
    }


def _declared_sources(checks: dict) -> dict[str, str]:
    """Registry of each declared package, from the supply-chain suspicious list when present."""
    sources = {}
    for pkg in (checks.get("supply_chain") or {}).get("suspicious_packages") or []:
        if pkg.get("name") and pkg.get("source"):
            sources[pkg["name"]] = pkg["source"]
    return sources


def _score_one(run_dir: Path, scores: Path, image: str) -> str:
    meta = json.loads((run_dir / "meta.json").read_text())
    target = scores / f"{meta['run_id']}.json"
    if target.is_file():
        previous = json.loads(target.read_text())
        if previous.get("zurix_ok", True):
            return f"{meta['run_id']}: already scored"
    if meta["status"] not in SCORED_STATUSES:
        target.write_text(json.dumps({"run_id": meta["run_id"], "task": meta["task"],
                                      "language": meta["language"], "category": meta["category"],
                                      "model": meta["model"], "rep": meta["rep"],
                                      "status": meta["status"]}, indent=2))
        return f"{meta['run_id']}: {meta['status']} (not scored)"
    with tempfile.TemporaryDirectory(prefix="zxscore-") as tmp:
        subprocess.run(["docker", "run", "--rm", "--cpus", "2", "--memory", "2g",
                        "-v", f"{(run_dir / 'workspace.tar.gz').resolve()}:/in/workspace.tar.gz:ro",
                        "-v", f"{tmp}:/out", image], capture_output=True, timeout=1800, check=False)
        raw_path = Path(tmp) / "score_raw.json"
        if not raw_path.is_file():
            return f"{meta['run_id']}: scoring container produced no output"
        raw = json.loads(raw_path.read_text())
    (scores / f"{meta['run_id']}.raw.json").write_text(json.dumps(raw, indent=2))
    target.write_text(json.dumps(interpret(raw, meta), indent=2))
    return f"{meta['run_id']}: scored"


def update_review(scores: Path, review_csv: Path) -> int:
    """Append a row for every reported phantom not yet in the hand-check log. Returns rows added."""
    existing = set()
    rows = []
    if review_csv.is_file():
        with review_csv.open(newline="") as f:
            rows = list(csv.DictReader(f))
        existing = {(r["run_id"], r["registry"], r["package"]) for r in rows}
    added = 0
    for path in sorted(scores.glob("*.json")):
        if path.name.endswith(".raw.json"):
            continue
        record = json.loads(path.read_text())
        candidates = ([(p, "zurix") for p in record.get("reported_phantoms", [])]
                      + [(p, "install") for p in record.get("install_candidates", [])])
        for p, found_by in candidates:
            key = (record["run_id"], p["registry"], p["package"])
            if key in existing:
                continue
            rows.append({"run_id": record["run_id"], "package": p["package"], "registry": p["registry"],
                         "kind": p["kind"], "found_by": found_by,
                         "registry_url": registry_url(p["registry"], p["package"]),
                         "verdict": "", "reviewed_on": "", "note": ""})
            existing.add(key)
            added += 1
    review_csv.parent.mkdir(parents=True, exist_ok=True)
    with review_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=BASE / "runs")
    parser.add_argument("--scores", type=Path, default=BASE / "scores")
    parser.add_argument("--review-csv", type=Path, default=BASE / "review" / "phantoms.csv")
    parser.add_argument("--review", action="store_true", help="only update the hand-check log")
    args = parser.parse_args(argv)

    if args.review:
        print(f"{update_review(args.scores, args.review_csv)} new phantom rows in {args.review_csv}")
        return 0

    cfg = load_config()
    args.scores.mkdir(parents=True, exist_ok=True)
    run_dirs = sorted(d for d in args.runs.iterdir() if (d / "meta.json").is_file())
    with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as pool:
        for line in pool.map(lambda d: _score_one(d, args.scores, cfg["images"]["score"]), run_dirs):
            print(line, flush=True)
    print(f"{update_review(args.scores, args.review_csv)} new phantom rows in {args.review_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
