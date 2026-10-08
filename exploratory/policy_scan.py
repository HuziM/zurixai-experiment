"""EXPLORATORY (not pre-registered): how often do agent-built projects violate policies a model can't know?

    python exploratory/policy_scan.py            # scans runs/ (experiment 1) and exp2/runs/

Three policies, fixed here before the first scan, applied to each run's direct dependencies at the
version pip/npm would install (an exact pin, else the highest release satisfying the range):

  P1 vulnerable   the resolved version has an OSV advisory rated HIGH or CRITICAL
  P2 copyleft     the resolved version is licensed only under strong copyleft or source-available terms
                  (GPL, AGPL, SSPL, BUSL, Commons Clause; LGPL is allowed; an OR with a permissive
                  option, or a permissive classifier next to a copyleft one, counts as compliant)
  P3 stale        the registry marks the version deprecated, or the package's last release is over 2 years old

No policy was given to the agents; these are the kind of private rules a team has and a model can't see.
Unresolvable requirements (a version that doesn't exist) are skipped: experiment 2 measures those.
"""

from __future__ import annotations

import json
import re
import sys
import tarfile
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import semantic_version
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "exploratory" / ".cache"
OUT = ROOT / "exploratory"
MANIFESTS = ("requirements.txt", "pyproject.toml", "package.json")
NOW = datetime.now(UTC)
PERMISSIVE = re.compile(r"\b(MIT|BSD|Apache|ISC|MPL|Mozilla|PSF|Python Software|Unlicense|CC0|Zlib|LGPL|"
                        r"Lesser General Public)\b", re.IGNORECASE)
STRONG = re.compile(r"(?<![L])\bA?GPL|Affero|GNU General Public|\bSSPL|Server Side Public|\bBUSL|"
                    r"Business Source|Commons Clause", re.IGNORECASE)


def fetch(url: str, data: dict | None = None) -> dict | None:
    key = CACHE / (re.sub(r"[^A-Za-z0-9._-]+", "_", url + json.dumps(data or {}, sort_keys=True))[:200] + ".json")
    if key.is_file():
        return json.loads(key.read_text())
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "zx-exploratory",
                                                          "Content-Type": "application/json"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                out = json.load(resp)
                CACHE.mkdir(parents=True, exist_ok=True)
                key.write_text(json.dumps(out))
                return out
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:  # noqa: BLE001 - retry on network trouble
            pass
    return None


def project_dir(work: Path) -> Path:
    if any((work / m).is_file() for m in MANIFESTS):
        return work
    found = {p.parent for m in MANIFESTS for p in list(work.glob(f"*/{m}")) + list(work.glob(f"*/*/{m}"))
             if not {"node_modules", ".venv", "venv"} & set(p.relative_to(work).parts)}
    return found.pop() if len(found) == 1 else work


def declared(run_tar: Path) -> list[tuple[str, str, str]]:
    """(ecosystem, name, spec) for each direct dependency of one run's project."""
    deps: list[tuple[str, str, str]] = []
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(run_tar) as tar:
        tar.extractall(tmp, filter="data")
        proj = project_dir(Path(tmp))
        lines = []
        if (proj / "requirements.txt").is_file():
            lines += (proj / "requirements.txt").read_text(errors="replace").splitlines()
        if (proj / "pyproject.toml").is_file():
            try:
                lines += tomllib.loads((proj / "pyproject.toml").read_text(errors="replace")).get(
                    "project", {}).get("dependencies") or []
            except tomllib.TOMLDecodeError:
                pass
        for line in lines:
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith(("#", "-", ".", "/")) or "://" in line:
                continue
            try:
                req = Requirement(line)
            except InvalidRequirement:
                continue
            if not req.url:
                deps.append(("PyPI", re.sub(r"[-_.]+", "-", req.name).lower(), str(req.specifier)))
        if (proj / "package.json").is_file():
            try:
                pkg = json.loads((proj / "package.json").read_text(errors="replace"))
            except json.JSONDecodeError:
                pkg = {}
            for field in ("dependencies", "devDependencies"):
                for name, rng in (pkg.get(field) or {}).items():
                    if isinstance(rng, str) and ":" not in rng and "/" not in rng:
                        deps.append(("npm", name, rng.strip()))
    return deps


def resolve(eco: str, name: str, spec: str) -> tuple[str | None, dict]:
    """The version pip/npm would install, and that package's registry facts."""
    if eco == "PyPI":
        doc = fetch(f"https://pypi.org/pypi/{name}/json")
        if not doc:
            return None, {}
        live = {v: f for v, f in doc["releases"].items() if f and not all(x.get("yanked") for x in f)}
        versions = []
        for v in live:
            try:
                versions.append(Version(v))
            except InvalidVersion:
                continue
        try:
            sset = SpecifierSet(spec)
        except Exception:  # noqa: BLE001
            return None, {}
        pinned = [str(s.version) for s in sset if s.operator in ("==", "===") and "*" not in s.version]
        if pinned:
            return (pinned[0] if pinned[0] in doc["releases"] else None), doc
        ok = [v for v in versions if sset.contains(v, prereleases=False)]
        return (str(max(ok)) if ok else None), doc
    doc = fetch(f"https://registry.npmjs.org/{name.replace('/', '%2f')}")
    if not doc:
        return None, {}
    vs = []
    for v in doc.get("versions", {}):
        try:
            vs.append(semantic_version.Version(v))
        except ValueError:
            continue
    if spec in ("", "*", "latest", "x"):
        latest = doc.get("dist-tags", {}).get("latest")
        return latest, doc
    try:
        best = semantic_version.NpmSpec(spec).select(vs)
    except ValueError:
        return None, {}
    return (str(best) if best else None), doc


def license_text(eco: str, name: str, version: str, doc: dict) -> str:
    if eco == "PyPI":
        info = (fetch(f"https://pypi.org/pypi/{name}/{version}/json") or {}).get("info", doc.get("info", {}))
        parts = [info.get("license_expression") or ""]
        parts += [c for c in info.get("classifiers", []) if c.startswith("License ::")]
        if not any(parts):
            parts.append((info.get("license") or "")[:200])
        return " | ".join(p for p in parts if p)
    lic = doc.get("versions", {}).get(version, {}).get("license") or doc.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    return str(lic or "")


def copyleft_only(text: str) -> bool:
    if not text or not STRONG.search(text):
        return False
    return not PERMISSIVE.search(text) and " OR " not in text.upper()


def stale(eco: str, version: str, doc: dict) -> str | None:
    if eco == "npm":
        dep = doc.get("versions", {}).get(version, {}).get("deprecated")
        if dep:
            return f"deprecated: {str(dep)[:80]}"
        stamp = (doc.get("time") or {}).get("modified")
    else:
        files = [f for f in (doc.get("releases") or {}).values() if f]
        stamp = max((f[0].get("upload_time_iso_8601") or "" for f in files), default="")
    try:
        age = (NOW - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).days
    except (ValueError, AttributeError):
        return None
    return f"last release {age // 365}y ago" if age > 730 else None


def vulnerabilities(items: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], list[str]]:
    """OSV advisories rated HIGH or CRITICAL per (ecosystem, name, version)."""
    result: dict[tuple[str, str, str], list[str]] = {}
    ids: dict[tuple[str, str, str], list[str]] = {}
    for i in range(0, len(items), 500):
        chunk = items[i:i + 500]
        resp = fetch("https://api.osv.dev/v1/querybatch", {"queries": [
            {"package": {"name": n, "ecosystem": e}, "version": v} for e, n, v in chunk]}) or {}
        for item, res in zip(chunk, resp.get("results", [])):
            ids[item] = [v["id"] for v in res.get("vulns", [])]
    unique = sorted({i for v in ids.values() for i in v})
    with ThreadPoolExecutor(8) as pool:
        details = dict(zip(unique, pool.map(lambda i: fetch(f"https://api.osv.dev/v1/vulns/{i}") or {}, unique)))
    for item, vulns in ids.items():
        high = [i for i in vulns if str((details[i].get("database_specific") or {}).get("severity", "")).upper()
                in ("HIGH", "CRITICAL")]
        result[item] = high
    return result


def main() -> int:
    runs = []
    for base, label in ((ROOT / "runs", "exp1"), (ROOT / "exp2" / "runs", "exp2")):
        for meta_path in sorted(base.glob("*/meta.json")):
            meta = json.loads(meta_path.read_text())
            if meta["status"] in ("done", "truncated"):
                runs.append((label, meta, meta_path.parent / "workspace.tar.gz"))
    print(f"{len(runs)} runs", flush=True)
    per_run = {m["run_id"]: declared(tar) for _, m, tar in runs}
    packages = sorted({(e, n, s) for deps in per_run.values() for e, n, s in deps})
    with ThreadPoolExecutor(8) as pool:
        resolved = dict(zip(packages, pool.map(lambda p: resolve(*p), packages)))
    versions = sorted({(e, n, v) for (e, n, _), (v, _) in resolved.items() if v})
    vulns = vulnerabilities(versions)
    findings: dict[tuple[str, str, str, str], dict] = {}
    for key, (version, doc) in resolved.items():
        if not version:
            continue
        eco, name, spec = key
        text = license_text(eco, name, version, doc)
        facts = {"P1_vulnerable": vulns.get((eco, name, version)) or None,
                 "P2_copyleft": text if copyleft_only(text) else None,
                 "P3_stale": stale(eco, version, doc)}
        findings[key] = {"version": version, **facts}
    rows = []
    for label, meta, _ in runs:
        hit = defaultdict(list)
        for eco, name, spec in per_run[meta["run_id"]]:
            f = findings.get((eco, name, spec))
            if not f:
                continue
            for policy in ("P1_vulnerable", "P2_copyleft", "P3_stale"):
                if f[policy]:
                    hit[policy].append(f"{name}@{f['version']}")
        rows.append({"experiment": label, "run_id": meta["run_id"], "task": meta["task"], "model": meta["model"],
                     "deps": len(per_run[meta["run_id"]]), **{p: sorted(set(v)) for p, v in hit.items()}})
    (OUT / "policy_scan.json").write_text(json.dumps({"runs": rows, "packages": {
        f"{e}:{n}:{s}": v for (e, n, s), v in findings.items()}}, indent=2))
    print("wrote exploratory/policy_scan.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
