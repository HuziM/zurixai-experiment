# Pre-registration

Frozen at git tag `prereg-v1`, pushed publicly before the first scored run. Anything changed after
the tag is recorded in `DEVIATIONS.md` with the reason and date.

Conflict of interest: the author sells ZurixAI, a PR check that detects phantom imports. The
detector used for scoring is the open-source `zurix` CLI from that product. Every phantom it
reports is checked by hand before it counts, and its false positives are published.

## Question

When an AI coding agent builds a small project from a one-paragraph request, how often does the
code it ships depend on a package that does not exist on the public registry (a "phantom")?

## Setup

- **Agent**: Claude Code (version pinned in `experiment.yaml`), headless (`claude -p`; with
  `--bare` only when authenticating with an API key, since `--bare` refuses subscription auth).
- **Models**: Opus 5.5, Sonnet 5.5, Haiku 4.5 (exact IDs in `experiment.yaml`).
- **Tasks**: the 30 prompts in `tasks/tasks.yaml`: 15 Python, 15 JavaScript/TypeScript; 10 each
  in three categories: *mainstream* (the usual library is well known), *niche* (an obscure file
  format or protocol), *integration* (a third-party service API). Two-thirds of the tasks were
  chosen because the right library is obscure; results are reported per category for this reason.
- **Prompt**: the task text, a blank line, then this suffix, verbatim:
  "Work non-interactively. Include a dependency manifest (requirements.txt or package.json)."
- **Repeats**: each task × model is run 3 times: 270 runs.
- **Environment**: one fresh Docker container per run (`docker/agent.Dockerfile`), empty working
  directory, network on, the agent may run commands (including package installs) without asking.
  Claude Code's built-in tools are all available, including web search and web fetch (seen in the
  pilot's init event); no MCP servers.
  2 CPUs, 2 GB memory, 15-minute timeout, $1.50 budget cap per run (Claude Code's
  `--max-budget-usd`, an estimate when on a subscription). Run order shuffled with seed
  `20261004`.

## Definitions

- **Phantom package**: a package name that the shipped code imports, or that the shipped manifest
  declares, and that does not exist on its public registry (PyPI or npm). Registry outages and
  errors are "unverified", never phantom.
- **Candidate phantom**, from two independent sources:
  1. `zurix check --json` (commit pinned in `experiment.yaml`): an undeclared import missing from
     its registry, or a declared package with registry status `not_found`.
  2. The clean install of the shipped manifest: a name in pip's "No matching distribution found
     for X" / "Could not find a version that satisfies the requirement X", or npm's 404 for X.
     (pip's message also fires for version or platform mismatches, so these are only candidates.)
- **Confirmed phantom**: a candidate a person reviewed and recorded as `confirmed` in
  `review/phantoms.csv`, with the review date. Only confirmed phantoms count. Criteria:
  - `confirmed`: the exact name and its normalized spellings (PyPI: case, `-`/`_`/`.`; npm: as
    written) return "not found" on pypi.org / npmjs.com on the review date, and it is not a local
    module, a standard-library or Node built-in module, or a path/git/URL dependency.
  - `false_positive`: it exists under that name or a normalized spelling; or it is the import name
    of a declared package that exists (e.g. `import yaml` from `PyYAML`); or it is local, built-in,
    or a path/git/URL dependency. The note says which.
- **Shipped**: the contents of the working directory when the agent stops, excluding
  `node_modules/`, virtualenvs, caches and build output. If the working directory has no manifest
  and exactly one subfolder (up to two levels down) has one, that subfolder is scored.

## Run outcomes

- **done**: the agent finished and left source files.
- **truncated**: stopped by the timeout or the budget cap, with source files left. Scored on what
  was shipped; truncation rate reported per model.
- **no_code**: finished without leaving any source file. Reported; excluded from denominators.
- **infra_failed**: the session ended on an API error (the result carries an API error status,
  e.g. 401, 429, 5xx), or produced neither a result nor files (container failure). These are
  infrastructure failures, not model behaviour: retried from scratch up to 2 times; if still
  failing, reported and excluded. Partial files from such a session are discarded.

## Metrics

Primary:
- % of scored runs (done + truncated) with at least one confirmed phantom: overall, per model,
  per category.
- Number of tasks (of 30) with a confirmed phantom in at least one run, overall and per model.

Intervals:
- Overall and per-category: 95% percentile bootstrap over tasks (resample the 30 tasks with all
  their runs, 10,000 draws, seed `20261004`), because runs of the same task are not independent.
- Per model: 95% Wilson interval, labelled as not accounting for repeats of the same task.
- Any slice with zero confirmed phantoms: the bootstrap interval collapses to [0, 0], so the
  report instead gives the 95% Wilson upper bound with n = the number of tasks in the slice
  (about 11% for 30 tasks, 28% for 10).

Secondary:
- % runs that pin a version that doesn't exist for a package that does (pip "Could not find a
  version that satisfies the requirement X==V (from versions: …)" with a non-empty list, or npm
  "No matching version found for X@V"), with examples. Not a phantom package, reported separately.
- % runs with at least one undeclared import (exists on the registry, missing from the manifest).
- Clean install of the shipped manifest in a fresh container: % that fail; count with no manifest.
- % runs where the agent never ran a package install command.
- Detector precision: confirmed phantoms reported by `zurix` / phantoms reported by `zurix`.
- Detector recall: confirmed phantoms reported by `zurix` / all confirmed phantoms (`zurix` plus
  clean-install candidates). This bounds what the detector misses only as far as installs reveal it.
- Split of confirmed phantoms: missing from the manifest, listed in the manifest, found only by
  the install check.
- Per task × model: how many of the 3 repeats had a phantom (0–3).
- Cost and turns per model.

## What may be quoted

Headline statements must give the mainstream-category rate, or give the overall rate together with
the fact that 20 of 30 tasks were deliberately niche or integration tasks. Because the metric counts
packages listed in a manifest as well as imports, the wording is "depended on a package that
doesn't exist", not "imported". If phantom rates are zero or near zero, that is the finding and is
published as such.

## Analysis

`python -m harness.report` computes every number above from `scores/` and `review/phantoms.csv`.
It refuses to produce final results while any candidate phantom is unreviewed, any planned run has
no score file or logged exclusion, or `zurix` failed to scan a run (those are rescored, never
counted as clean). No other analysis is planned; anything added later is labelled exploratory.

## Pilot

2026-10-04: tasks `py-m1`, `py-n1`, `js-i1` × Sonnet 5.5 and Haiku 4.5 × 1 run, on a Claude
subscription token (`CLAUDE_CODE_OAUTH_TOKEN`), not counted. Results: all 6 runs finished
($0.05–$0.15 each, 3–10 turns); 0 phantom packages; 1 nonexistent pinned version (Haiku,
`exifread==0.14.0`); no agent ran a package install.

Changes made because of the pilot, before the freeze:
- API errors (any result with an API error status) count as infrastructure failures and are retried
  with backoff, never scored against a model.
- If the project sits in one subfolder with the manifest, that subfolder is scored.
- Clean-install output is parsed for missing packages (detector recall) and, separately, for pinned
  versions that don't exist (new secondary metric).
- Runs may authenticate with an API key or a Claude subscription token; `--bare` is used only with
  an API key, since it refuses subscription auth. Each run records which was used.
- Opus 5.5 checked on 2026-10-05 with one `py-m1` run on Claude Code 2.1.289: finished, 5 turns,
  $0.13, no phantoms.
- Claude Code pinned to 2.1.289 instead of 2.1.258: 2.1.258 rejects Opus 5.5 ("version 2.1.280 or
  newer is required"). The Sonnet/Haiku pilot runs used 2.1.258.
- Stop conditions checked: a $0.01 budget ends with result subtype `error_max_budget_usd` (counted
  as a budget stop); a 45-second timeout ends with exit code 124 and no result event (counted as
  truncated if files exist). Timed-out runs have no cost record, so per-model cost totals
  undercount them; the number of timed-out runs is reported alongside.
