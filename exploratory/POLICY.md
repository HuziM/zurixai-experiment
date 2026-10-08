# Exploratory: policies a model can't know (not pre-registered)

Run 2026-10-08 on the 480 finished workspaces of experiments 1 and 2 (`exploratory/policy_scan.py`;
policies fixed in that file before the first scan). No policy was given to the agents. Advisories,
licences and release dates are as of the scan date. Treat this as a lead, not a result.

| Model | Runs with deps | P1 vulnerable (HIGH/CRITICAL) | P2 copyleft only | P3 stale (>2 y or deprecated) |
|---|---|---|---|---|
| Opus 5.5 | 66 | 0 | 0 | 7 (10.6%) |
| Sonnet 5.5 | 116 | 6 (5.2%) | 0 | 11 (9.5%) |
| Haiku 4.5 | 227 | 39 (17.2%) | 1 (0.4%) | 29 (12.8%) |

How to read it:
- **P1 is the real signal, and it clusters.** Sonnet's 6 runs are 3 repeated mistakes (3 of 60 tasks:
  `music-metadata@7.14.0`, `nodemailer@6.10.1`, `sharp@0.33.5`); Haiku's 39 span 13 of 60 tasks. Opus: none.
  Runs where the agent installed its own dependencies were vulnerable 6 of 136 times (4.4%); runs where it
  didn't, 39 of 273 (14.3%). Newer advisories than the model's training data are the likely cause.
- **P2 doesn't discriminate:** one hit in 480, and it is uncertain (a GPL classifier on `pillow-heif`).
- **P3 is noisy:** half of the 20 stale packages are just over the 2-year line (`openpyxl`,
  `python-dateutil`), widely used and stable. The age threshold isn't a good staleness test.
- **P1 and licences are not unique to us:** GitHub's dependency-review action flags vulnerable and
  disallowed-licence dependencies in PRs for free.
- A team could put these rules in the agent's instructions; this scan doesn't test whether that works.
