# Experiment 2: deviations from the pre-registration

Changes made after tag `prereg-v2`, with date and reason. Empty means the run followed the plan.
- 2026-10-08, after scoring, before any verdicts or numbers: the host-side classification of pip
  output in `harness/score.py` (`install_findings`) mislabelled a long failure. Saved install output
  is cut to its last 4,000 characters, which for `stripe==10.13.0` (570 releases) removed the
  "Could not find a version that satisfies the requirement … (from versions: …)" line and left only
  "No matching distribution found for stripe==10.13.0", read as a missing package. It now treats a
  "No matching distribution" line preceded by the tail of a non-empty "(from versions: …)" list as a
  missing version (the package exists). This changed 1 finding (stripe: a split missing-package +
  missing-version pair became one missing-version finding found by both signals); the raw outputs,
  scoring image and `zurix` are unchanged, and the findings list was rebuilt before any verdicts
  were recorded. Experiment 1's report regenerates unchanged.
