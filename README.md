# Do AI coding agents ship imports of packages that don't exist?

Claude Code, run headless with three Claude models (Opus 5.5, Sonnet 5.5, Haiku 4.5), builds 30
small projects three times each. We check whether the code it ships imports or declares a package
that isn't on PyPI or npm. Method, metrics and analysis were fixed before any scored run: see
[PREREGISTRATION.md](PREREGISTRATION.md) and the `prereg-v1` tag. Results: `results/RESULTS.md`.

Conflict of interest: the author sells [ZurixAI](https://zurixai.com), whose open-source `zurix`
CLI does the detection here. Every reported phantom is checked by hand, and the detector's false
positives are published.

## Layout

| Path | What |
|---|---|
| `tasks/tasks.yaml` | The 30 prompts and the fixed suffix |
| `experiment.yaml` | Models, repeats, budget, timeout, seed, pinned versions |
| `docker/` | Agent image (Claude Code, Python, Node) and scoring image (pinned `zurix`) |
| `harness/run.py` | Runs every task × model × repeat in a fresh container; resumable |
| `harness/score.py` | `zurix check --json` + clean install per run; builds the hand-check log |
| `harness/report.py` | The pre-registered metrics → `results/summary.json`, `results/RESULTS.md` |
| `review/phantoms.csv` | Hand-check verdict for every reported phantom |
| `pilot/` | Harness shake-down runs; not part of the results |

## Rerun it

You need Docker and an Anthropic API key. A full run is 270 agent sessions, capped at $1.50 each.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
docker build -f docker/agent.Dockerfile -t zurixai-exp-agent:prereg-v1 docker
docker build -f docker/score.Dockerfile -t zurixai-exp-score:prereg-v1 docker
export ANTHROPIC_API_KEY=...            # use a dedicated key with a spend limit; revoke it after
.venv/bin/python -m harness.run         # runs/<task>__<model>__r<n>/
.venv/bin/python -m harness.score       # scores/ + review/phantoms.csv
# fill in review/phantoms.csv (confirmed / false_positive), then:
.venv/bin/python -m harness.report      # results/
```

The agent runs with permission checks off inside its container, which has network access and the
API key; packages it installs can run code there. Use a key you revoke afterwards.

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests cover the counting rules and the statistics, without Docker or the API.
