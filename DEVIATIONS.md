# Deviations from the pre-registration

Changes made after tag `prereg-v1`, with date and reason. Empty means the run followed the plan.

- 2026-10-05, before any scored run: `harness/run.py` stops the whole run after 3 runs in a row
  end on a 429 (usage or rate limit), instead of retrying every remaining run with backoff. The
  runs are on a Claude subscription with periodic usage limits; the operator reruns the same
  command after the limit resets and finished runs are skipped. Operational only: what is run,
  measured and counted is unchanged (rate-limited runs were already infrastructure failures).
