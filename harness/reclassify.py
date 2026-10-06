"""Re-apply the current run classification to recorded runs, keeping an audit trail.

    python -m harness.reclassify            # dry run: show what would change
    python -m harness.reclassify --apply

Used once (see DEVIATIONS.md, 2026-10-06): 48 runs that failed because the API was unreachable
were recorded as `no_code`. Each changed meta.json keeps its old status under `reclassified`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from harness.common import BASE
from harness.run import classify


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=BASE / "runs")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    changed = 0
    for path in sorted(args.runs.glob("*/meta.json")):
        meta = json.loads(path.read_text())
        new = classify(meta.get("exit_code"), meta, meta.get("source_files") or [])
        if new == meta["status"]:
            continue
        changed += 1
        print(f"{meta['run_id']}: {meta['status']} -> {new}  ({(meta.get('error_message') or '')[:70]})")
        if args.apply:
            meta["reclassified"] = {"from": meta["status"], "to": new, "at": datetime.now(UTC).isoformat(),
                                    "reason": "API error without a status code (unreachable API)"}
            meta["status"] = new
            path.write_text(json.dumps(meta, indent=2))
    print(f"{changed} runs {'reclassified' if args.apply else 'would be reclassified'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
