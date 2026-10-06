"""Shared loading of the frozen experiment definition."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# Experiment 1 lives at the repo root; a later experiment lives in its own folder, selected with
# ZX_EXPERIMENT=exp2 (its own experiment.yaml, tasks/, runs/, scores/, review/, results/).
BASE = ROOT / os.environ["ZX_EXPERIMENT"] if os.environ.get("ZX_EXPERIMENT") else ROOT


@dataclass(frozen=True)
class Task:
    id: str
    language: str
    category: str
    prompt: str


@dataclass(frozen=True)
class Run:
    task: Task
    model: str
    rep: int

    @property
    def id(self) -> str:
        return f"{self.task.id}__{self.model}__r{self.rep}"


def load_config(path: Path = BASE / "experiment.yaml") -> dict:
    return yaml.safe_load(path.read_text())


def load_tasks(path: Path = BASE / "tasks" / "tasks.yaml") -> tuple[list[Task], str]:
    data = yaml.safe_load(path.read_text())
    tasks = [Task(t["id"], t["language"], t["category"], t["prompt"].strip()) for t in data["tasks"]]
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task ids")
    return tasks, data["suffix"].strip()


def full_prompt(task: Task, suffix: str) -> str:
    return f"{task.prompt}\n\n{suffix}"


def plan_runs(tasks: list[Task], models: list[str], reps: int | dict[str, int], seed: int) -> list[Run]:
    """Every task × model × rep, shuffled with a fixed seed so models interleave over time.

    `reps` is one count for every model, or a count per model.
    """
    def count(model: str) -> int:
        return reps[model] if isinstance(reps, dict) else reps

    runs = [Run(t, m, r) for t in tasks for m in models for r in range(1, count(m) + 1)]
    random.Random(seed).shuffle(runs)
    return runs
