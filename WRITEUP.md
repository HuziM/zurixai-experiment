# Do AI coding agents ship dependencies that don't exist?

*A pre-registered test, what it found, and the product I built and then decided not to pursue.*

**Draft.** Experiment 2 numbers below are provisional until its hand-checked verdicts are final; update the marked lines, then publish.

## Summary

- I built ZurixAI, a PR check for AI-written code: it flags imports and dependencies that don't exist, and keeps a signed, verifiable log of what was checked. The CLI is open source.
- Before selling it, I tested the assumption underneath it. I pre-registered the method (public tag and archived timestamp) and ran Claude Code with three models on 270 small projects.
- **Hallucinated package names were nearly absent: 1 run in 270.** The common failure was one level down: **Haiku 4.5 pinned versions that don't exist in 12 of its 90 runs (13%)**, and every one of those projects failed to install. Opus 5.5 and Sonnet 5.5 had none. My own detector missed 12 of those 13 broken runs, because it only checked package names.
- I added a version check and tested it on fresh output it had never seen: **it flagged all 29 install-breaking problems** in 150 new Haiku runs (19% of runs) with 0 on the Sonnet control. **[provisional]** 8 of its 37 flags were false alarms, all from one import-name mapping gap.
- Conclusion: the problem is real but narrow, and it is concentrated in smaller models. With free alternatives and no evidence of demand, I decided not to run it as a business.

## What I tested

30 realistic prompts (15 Python, 15 JavaScript/TypeScript; mainstream, niche-format and service-integration tasks), none naming a package. Each ran in a fresh container with network access, three times per model. A project counted as broken if a clean install failed on a package or version that doesn't exist, confirmed by hand against PyPI and npm using criteria written beforehand. Intervals account for repeated runs of the same task.

## What I found

| | Opus 5.5 | Sonnet 5.5 | Haiku 4.5 |
|---|---|---|---|
| Phantom package (of 90 runs) | 0 | 0 | 1 |
| Nonexistent pinned version | 0 | 0 | 12 |
| Agent ran an install itself | 62 | 24 | 16 |

The models that checked their own work by installing shipped working dependencies. The one that mostly didn't did not.

## What the detector did

`zurix` 0.3.0 had perfect precision (1 of 1) but caught 1 of 13 install-breaking problems. Version 0.4.0, built after seeing that data and tested on new tasks, caught 29 of 29 **[provisional]**, with 78% precision **[provisional]**.

An exploratory scan of all 480 workspaces for known-vulnerable pinned dependencies found none in Opus 5.5's runs, a few repeated mistakes in Sonnet's, and the most in Haiku's. GitHub's free dependency-review already covers that case.

## How I kept it honest

The method, tasks and analysis were fixed before any scored run (git tags, archived on the Wayback Machine). Every change after that is in a deviations log, including a network outage that corrupted 48 runs and a bug in my own labelling that I found while reviewing results. I chose Haiku for the second experiment *because* it fails, and say so. The detector's author and the experiment's author are the same person; I disclose that and had every flagged problem checked by hand.

## Limits

Claude models only, small greenfield projects, web search enabled, one person. Frontier models may fail differently on large existing codebases. Whether a team would pay for a signed audit log is untested.

## What I built

A GitHub App backend (webhook with fail-closed signature checks, per-repo plans and run caps keyed on GitHub IDs, private-repo cloning), an Ed25519 signed hash-chained audit log that a customer can verify offline, a typed and tested open-source CLI (four releases), and the experiment harness. I built it with an AI coding agent; the product decisions, experiment design, reviews and the decision to stop were mine.

## Links

Code: github.com/HuziM/zurixai (CLI) · github.com/HuziM/zurixai-experiment (method, data, deviations). Pre-registrations: tags `prereg-v1`, `prereg-v2`.
