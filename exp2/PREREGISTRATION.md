# Experiment 2 pre-registration: does zurix catch broken dependencies in fresh agent output?

Frozen at git tag `prereg-v2`, pushed publicly before the first scored run. Changes after the tag go
in `exp2/DEVIATIONS.md` with the date and reason.

Conflict of interest: this experiment measures the author's own product. ZurixAI sells a PR check
whose open-source `zurix` CLI is the detector being tested. To keep that honest: the detector is
frozen at a public release commit before any run, ground truth comes from an independent clean
install plus a person's review, the method and analysis are fixed here, and the results are
published whatever they are.

## Why this experiment exists

Experiment 1 (tag `prereg-v1`) found that phantom packages were rare (1 run in 270), but that
Claude Haiku 4.5 pinned versions that don't exist in 12 of its 90 runs, and that `zurix` 0.3.0
caught none of those. `zurix` 0.4.0 adds a check for declared versions that don't exist. It was
written after seeing experiment 1's data, so its performance there doesn't count as evidence. This
experiment tests it on new tasks and new runs it has never seen.

## Question

On fresh projects built by an AI coding agent, how many dependency problems that break a clean
install does `zurix` 0.4.0 flag (recall), how many of its flags are real (precision), and how often
does each model ship such problems?

## Setup

- **Agent**: Claude Code 2.1.289, headless, same container image and prompt suffix as experiment 1.
- **Models**: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`), chosen deliberately because it shipped
  broken dependencies in experiment 1 and a detection test needs real failures to detect; and Claude
  Sonnet 5.5 (`claude-sonnet-5-5`) as a control that rarely did, to measure false alarms.
- **Tasks**: 30 new tasks in `exp2/tasks/tasks.yaml` (none reused from experiment 1): 15 Python,
  15 JavaScript/TypeScript; 10 each mainstream / niche / integration. No prompt names a package or a
  version.
- **Prompt**: task text, blank line, then verbatim: "Work non-interactively. Include a dependency
  manifest (requirements.txt or package.json)."
- **Repeats**: Haiku 5 per task (150 runs), Sonnet 2 per task (60 runs): 210 runs.
- **Environment, run outcomes, retries, pause rules**: as experiment 1, including its deviations
  (API errors, network failures and usage limits are infrastructure failures, rerun until they
  reach the model). Run order shuffled with seed `20261007`.
- **Detector**: `zurix` at the public 0.4.0 release commit recorded in `exp2/experiment.yaml` at the
  freeze. No change to `zurix` affects this experiment's numbers.

## Ground truth and definitions

For each run, a clean install of the shipped manifest in a fresh container (`pip install -r` /
`pip install .` / `npm install --ignore-scripts`), independent of `zurix`. Every problem reported by
`zurix` or by the install becomes a **finding** (one run × package × problem) in
`exp2/review/findings.csv`:

- `missing_package`: the package does not exist on its registry.
- `missing_version`: the package exists, but no published release satisfies the declared version
  or range.
- `other_install_failure`: the install failed for another reason (build error, platform, Python or
  Node version).

A person records a verdict and date for every finding:

- `real` (dependency problem): `missing_package` when the name and its normalized spellings return
  "not found" on pypi.org / npmjs.com on the review date and it isn't local, built-in, or a
  path/git/URL dependency; `missing_version` when the registry's release list (including yanked
  releases, noted) has no version satisfying the declared constraint.
- `false_alarm`: `zurix` flagged it, but the package or a satisfying version exists, or it isn't a
  registry dependency.
- `not_dependency`: an install failure not caused by a missing package or version.

## Metrics

Primary:
- **Recall**: of the `real` `missing_package` / `missing_version` findings that the clean install
  revealed, the share `zurix` also flagged; overall and per problem type, 95% Wilson interval.
  Problems only `zurix` can see (an imported package that is missing from both the manifest and the
  registry) are reported separately, because no independent signal exists for them.
- **Precision**: of every `zurix` flag (phantom packages and versions that don't exist), the share
  judged `real`; 95% Wilson interval.

Secondary:
- Per model: runs with at least one `real` dependency problem (95% bootstrap over tasks), runs `zurix`
  flagged, and runs it flagged without a real problem (false-alarm runs; the Sonnet control's number
  is the main false-alarm measure).
- Count of `other_install_failure` runs (not something `zurix` claims to catch).

## What may be quoted

Detection claims must give recall and precision with their counts ("flagged X of Y"), state that
the models were Claude Haiku 4.5 and Sonnet 5.5 on small new projects, and that Haiku was chosen
because it produced such problems before. Frequency claims are limited to the model and setting
tested. Results are published whatever they are, including low recall or false alarms.

## Analysis

`ZX_EXPERIMENT=exp2 python -m harness.detect_report` computes every number above from
`exp2/scores/` and `exp2/review/findings.csv`. It refuses to produce final results while any planned
run has no score, `zurix` failed to scan a run, or any finding is unreviewed. Anything else is
labelled exploratory.

## Pilot

None: the harness, environment and scoring are the ones from experiment 1, already exercised on 270
runs. The new parts (version findings, detection metrics) are covered by unit tests and by a
development check on experiment 1's data (12 of 12 runs with nonexistent versions flagged, none of
the other 258), which is not part of this experiment's results.
