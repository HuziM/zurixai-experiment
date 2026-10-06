"""Runs inside the scoring container: collect raw facts about one run's shipped workspace.

Reads /in/workspace.tar.gz, writes /out/score_raw.json with:
  zurix:   `zurix check --json` output (or the error)
  installs: one record per manifest found, from a clean install into a fresh environment
No judgments here; harness/score.py interprets the raw facts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

WORK = Path("/home/scorer/work")
TAIL = 4000
INSTALL_TIMEOUT_S = 600
MANIFESTS = ("requirements.txt", "pyproject.toml", "setup.py", "package.json")
SKIP = {"node_modules", ".venv", "venv", ".git", "__pycache__", "dist", "build"}


def project_dir(work: Path) -> Path:
    """The workspace root, or the one subfolder holding a manifest when the root has none."""
    if any((work / m).is_file() for m in MANIFESTS):
        return work
    found = set()
    for manifest in MANIFESTS:
        for path in work.glob(f"*/{manifest}"):
            if path.parent.name not in SKIP:
                found.add(path.parent)
        for path in work.glob(f"*/*/{manifest}"):
            if not SKIP & set(path.relative_to(work).parts):
                found.add(path.parent)
    return found.pop() if len(found) == 1 else work


def _run(cmd: list[str], cwd: Path, timeout: int) -> dict:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return {"cmd": " ".join(cmd), "exit": proc.returncode,
                "output_tail": (proc.stdout + proc.stderr)[-TAIL:]}
    except subprocess.TimeoutExpired:
        return {"cmd": " ".join(cmd), "exit": None, "output_tail": "timeout"}


def _zurix(work: Path) -> dict:
    proc = subprocess.run(["zurix", "check", str(work), "--json"], capture_output=True, text=True,
                          timeout=600, check=False)
    try:
        return {"exit": proc.returncode, "result": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"exit": proc.returncode, "error": (proc.stdout + proc.stderr)[-TAIL:]}


def _installs(work: Path) -> list[dict]:
    records = []
    if (work / "requirements.txt").is_file():
        venv = Path("/tmp/venv-req")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        records.append({"manifest": "requirements.txt",
                        **_run([str(venv / "bin/pip"), "install", "-r", "requirements.txt"], work, INSTALL_TIMEOUT_S)})
    elif (work / "pyproject.toml").is_file() or (work / "setup.py").is_file():
        venv = Path("/tmp/venv-proj")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        name = "pyproject.toml" if (work / "pyproject.toml").is_file() else "setup.py"
        records.append({"manifest": name, **_run([str(venv / "bin/pip"), "install", "."], work, INSTALL_TIMEOUT_S)})
    if (work / "package.json").is_file():
        records.append({"manifest": "package.json",
                        **_run(["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], work,
                               INSTALL_TIMEOUT_S)})
    return records


RESOLVE_TIMEOUT_S = 120


def _python_requirements(work: Path) -> list[tuple[str, str]]:
    """(manifest, requirement) for every requirement line, skipping includes, editables and URLs."""
    reqs = []
    req_file = work / "requirements.txt"
    if req_file.is_file():
        for line in req_file.read_text(errors="replace").splitlines():
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith(("#", "-", ".", "/")) or "://" in line or line.startswith(("git+", "hg+")):
                continue
            reqs.append(("requirements.txt", line))
    pyproject = work / "pyproject.toml"
    if pyproject.is_file():
        try:
            deps = tomllib.loads(pyproject.read_text(errors="replace")).get("project", {}).get("dependencies") or []
        except tomllib.TOMLDecodeError:
            deps = []
        reqs += [("pyproject.toml", d) for d in deps if isinstance(d, str) and "://" not in d]
    return reqs


def _npm_dependencies(work: Path) -> list[tuple[str, str]]:
    package_json = work / "package.json"
    if not package_json.is_file():
        return []
    try:
        data = json.loads(package_json.read_text(errors="replace"))
    except json.JSONDecodeError:
        return []
    deps = []
    for field in ("dependencies", "devDependencies"):
        for name, rng in (data.get(field) or {}).items():
            if isinstance(rng, str) and ":" not in rng and "/" not in rng:
                deps.append((name, rng.strip() or "*"))
    return deps


def _resolutions(work: Path) -> list[dict]:
    """Resolve each declared dependency on its own with pip's and npm's own resolvers, so one bad
    requirement can't hide another (a full install stops at the first failure)."""
    records = []
    reqs = _python_requirements(work)
    if reqs:
        venv = Path("/tmp/venv-resolve")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        for manifest, req in reqs:
            records.append({"manifest": manifest, "requirement": req,
                            **_run([str(venv / "bin/pip"), "install", "--dry-run", "--no-deps",
                                    "--ignore-installed", req], work, RESOLVE_TIMEOUT_S)})
    for name, rng in _npm_dependencies(work):
        try:
            proc = subprocess.run(["npm", "view", f"{name}@{rng}", "version", "--json"], cwd=work,
                                  capture_output=True, text=True, timeout=RESOLVE_TIMEOUT_S, check=False)
            records.append({"manifest": "package.json", "requirement": f"{name}@{rng}", "package": name,
                            "spec": rng, "cmd": f"npm view {name}@{rng} version --json", "exit": proc.returncode,
                            "stdout": proc.stdout[-TAIL:], "output_tail": (proc.stdout + proc.stderr)[-TAIL:]})
        except subprocess.TimeoutExpired:
            records.append({"manifest": "package.json", "requirement": f"{name}@{rng}", "package": name,
                            "spec": rng, "exit": None, "stdout": "", "output_tail": "timeout"})
    return records


def main() -> None:
    WORK.mkdir(parents=True)
    with tarfile.open("/in/workspace.tar.gz") as tar:
        tar.extractall(WORK, filter="data")
    project = project_dir(WORK)
    raw = {"project_dir": str(project.relative_to(WORK)) or ".", "zurix": _zurix(project)}
    install_dir = Path("/home/scorer/install")
    shutil.copytree(project, install_dir)
    raw["installs"] = _installs(install_dir)
    raw["resolutions"] = _resolutions(project)
    Path("/out/score_raw.json").write_text(json.dumps(raw, indent=2))


if __name__ == "__main__":
    main()
