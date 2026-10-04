# Results (DRAFT: unreviewed phantoms or incomplete runs)

## Runs with at least one confirmed phantom package

| Slice | Runs | With phantom | % | 95% interval |
|---|---|---|---|---|
| All | 7 | 0 | 0.0 | 0 to 56.1 (no phantoms; Wilson upper bound over tasks) |
| integration | 2 | 0 | 0.0 | 0 to 79.3 (no phantoms; Wilson upper bound over tasks) |
| mainstream | 3 | 0 | 0.0 | 0 to 79.3 (no phantoms; Wilson upper bound over tasks) |
| niche | 2 | 0 | 0.0 | 0 to 79.3 (no phantoms; Wilson upper bound over tasks) |
| claude-opus-5-5 | 1 | 0 | 0.0 | 0 to 79.3 (no phantoms; Wilson upper bound over tasks) |
| claude-sonnet-5-5 | 3 | 0 | 0.0 | 0 to 56.1 (no phantoms; Wilson upper bound over tasks) |
| claude-haiku-4-5-20251001 | 3 | 0 | 0.0 | 0 to 56.1 (no phantoms; Wilson upper bound over tasks) |

Tasks with a phantom in at least one run: 0 of 30 (claude-opus-5-5: 0, claude-sonnet-5-5: 0, claude-haiku-4-5-20251001: 0).

## Secondary

```json
{
  "undeclared_import": {
    "claude-opus-5-5": {
      "k": 0,
      "n": 1,
      "pct": 0.0
    },
    "claude-sonnet-5-5": {
      "k": 0,
      "n": 3,
      "pct": 0.0
    },
    "claude-haiku-4-5-20251001": {
      "k": 0,
      "n": 3,
      "pct": 0.0
    }
  },
  "pinned_version_that_does_not_exist": {
    "claude-opus-5-5": {
      "k": 0,
      "n": 1,
      "examples": []
    },
    "claude-sonnet-5-5": {
      "k": 0,
      "n": 3,
      "examples": []
    },
    "claude-haiku-4-5-20251001": {
      "k": 1,
      "n": 3,
      "examples": [
        "exifread==0.14.0"
      ]
    }
  },
  "install_fails": {
    "claude-opus-5-5": {
      "k": 0,
      "no_manifest": 0,
      "n": 1
    },
    "claude-sonnet-5-5": {
      "k": 0,
      "no_manifest": 0,
      "n": 3
    },
    "claude-haiku-4-5-20251001": {
      "k": 1,
      "no_manifest": 0,
      "n": 3
    }
  },
  "never_ran_install": {
    "claude-opus-5-5": {
      "k": 1,
      "n": 1
    },
    "claude-sonnet-5-5": {
      "k": 3,
      "n": 3
    },
    "claude-haiku-4-5-20251001": {
      "k": 3,
      "n": 3
    }
  },
  "detector_precision": {
    "reported": 0,
    "confirmed": 0,
    "pct": null
  },
  "detector_recall": {
    "confirmed_total": 0,
    "found_by_zurix": 0,
    "pct": null
  },
  "phantom_kinds": {
    "not_in_manifest": 0,
    "in_manifest": 0,
    "install_not_found": 0
  },
  "per_task_consistency": {
    "claude-opus-5-5": {
      "0": 1
    },
    "claude-sonnet-5-5": {
      "0": 3
    },
    "claude-haiku-4-5-20251001": {
      "0": 3
    }
  },
  "cost_and_turns": {
    "claude-opus-5-5": {
      "total_usd": 0.13,
      "runs_without_cost_record": 0,
      "median_usd": 0.131,
      "median_turns": 5
    },
    "claude-sonnet-5-5": {
      "total_usd": 0.29,
      "runs_without_cost_record": 0,
      "median_usd": 0.085,
      "median_turns": 4
    },
    "claude-haiku-4-5-20251001": {
      "total_usd": 0.15,
      "runs_without_cost_record": 0,
      "median_usd": 0.053,
      "median_turns": 7
    }
  }
}
```

## Run status

```json
{
  "status": {
    "claude-opus-5-5": {
      "done": 1
    },
    "claude-sonnet-5-5": {
      "done": 3
    },
    "claude-haiku-4-5-20251001": {
      "done": 3
    }
  },
  "truncation": {
    "claude-opus-5-5": {
      "k": 0,
      "n": 1,
      "pct": 0.0
    },
    "claude-sonnet-5-5": {
      "k": 0,
      "n": 3,
      "pct": 0.0
    },
    "claude-haiku-4-5-20251001": {
      "k": 0,
      "n": 3,
      "pct": 0.0
    }
  }
}
```
