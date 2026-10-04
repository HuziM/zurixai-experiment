# Pilot checklist (before the `prereg-v1` freeze)

Pilot: 3 tasks × 3 models × 1 run, into `pilot/runs` and `pilot/scores`. Not counted.

```bash
.venv/bin/python -m harness.run --out pilot/runs --tasks py-m1,py-n1,js-i1 --reps 1
.venv/bin/python -m harness.score --runs pilot/runs --scores pilot/scores --review-csv pilot/phantoms.csv
.venv/bin/python -m harness.report --scores pilot/scores --review-csv pilot/phantoms.csv --out pilot/results --draft
```

- [x] All three model IDs work (no 4xx on model name).
- [x] Record the tools Claude Code offers (the stream's `system`/`init` event).
      State in PREREGISTRATION.md whether web search / fetch were available.
- [x] Map every result `subtype` seen. Force the budget cap once (tiny `budget_usd_per_run`) and
      the timeout once (short `timeout_s`); record the real subtype and exit code, and fix
      `transcript.summarize` / `run.classify` if `"budget" in subtype` doesn't catch it.
- [x] Check whether agents put the project in a subfolder; confirm `project_dir` in the raw score.
- [x] Real cost per run per model; decide whether $1.50 is enough for Opus before the freeze.
- [x] No `sk-ant-` in any file under `pilot/`.
- [x] Each run has workspace, transcript, meta and score; the scoring container saw only the tarball.

At the freeze:
- [x] Fill in the Pilot section of PREREGISTRATION.md (tasks, date, changes made after it).
- [x] Record base image digests and built image IDs in `experiment.yaml`.
- [ ] Tag `prereg-v1` (done), push, and save the tag page to the Wayback Machine for an independent timestamp.
