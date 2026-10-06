# Deviations from the pre-registration

Changes made after tag `prereg-v1`, with date and reason. Empty means the run followed the plan.

- 2026-10-05, before any scored run: `harness/run.py` stops the whole run after 3 runs in a row
  end on a 429 (usage or rate limit), instead of retrying every remaining run with backoff. The
  runs are on a Claude subscription with periodic usage limits; the operator reruns the same
  command after the limit resets and finished runs are skipped. Operational only: what is run,
  measured and counted is unchanged (rate-limited runs were already infrastructure failures).
- 2026-10-05, before any scored run: `harness/loop.py` reruns `harness.run` until every run is
  finished. After a usage-limit stop it reads the reset time from Claude Code's limit message
  (`harness/limits.py`; times without a timezone are UTC, the container clock) and waits until
  then plus 5 minutes, or 5.5 hours if no time can be read. Only runs that ended on a 429 are run
  again; any other infrastructure failure keeps its pre-registered 2 retries and is excluded.
  Run metadata now keeps the API error message so the reset time can be read. Operational only.
- 2026-10-06, during the run (after round 1): the loop's wait now checks the wall clock every
  minute instead of one long sleep, which on macOS stopped counting while the computer slept and
  so overshot the reset time. Operational only; no run results are affected.
- 2026-10-06, during the run: 48 runs (Opus 21, Sonnet 17, Haiku 10) started between 00:55 and
  03:30 UTC while the machine running the experiment had no internet. Each ended at once with
  "API Error: Can't reach the API server … (ENOTFOUND)", zero cost and no files, and was recorded
  as `no_code` because the classifier only recognised API errors that carry an HTTP status. They
  are infrastructure failures under the pre-registered definition ("the session ended on an API
  error"): the classifier now also treats any "API Error: …" result as one
  (`harness/run.py:api_error`), and the 48 records were relabelled with `harness/reclassify.py`,
  which keeps the old status in each `meta.json`. Their in-run retries happened during the same
  outage, so instead of being excluded after 2 retries they are run again in full once the network
  is back, like usage-limit stops; the model was never reached in any of them. No other run was
  affected (the other 222 finished runs have no error). Decided before any of these runs produced
  output, and before any scoring.
