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


def main() -> None:
    WORK.mkdir(parents=True)
    with tarfile.open("/in/workspace.tar.gz") as tar:
        tar.extractall(WORK, filter="data")
    project = project_dir(WORK)
    raw = {"project_dir": str(project.relative_to(WORK)) or ".", "zurix": _zurix(project)}
    install_dir = Path("/home/scorer/install")
    shutil.copytree(project, install_dir)
    raw["installs"] = _installs(install_dir)
    Path("/out/score_raw.json").write_text(json.dumps(raw, indent=2))


if __name__ == "__main__":
    main()
