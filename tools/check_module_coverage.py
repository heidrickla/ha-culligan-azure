"""Hold every integration module to the coverage floor, not just the total.

The test-coverage rule asks for above 95% for all integration modules.
--cov-fail-under gates the aggregate, where a well covered coordinator hides a
thinly covered platform, so the per-file figures are checked here from the JSON
report the same run writes.

    python tools/check_module_coverage.py [coverage.json]
"""

from __future__ import annotations

import json
import os
import sys

FLOOR = 95.0
DEFAULT_REPORT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "coverage.json"
)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPORT
    if not os.path.isfile(path):
        print(f"no coverage report at {path}; run pytest with --cov-report=json")
        return 1

    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)

    files = report.get("files", {})
    if not files:
        print("the coverage report names no files")
        return 1

    below = []
    for name in sorted(files):
        percent = files[name]["summary"]["percent_covered"]
        marker = " " if percent >= FLOOR else "<"
        print(f"  {marker} {percent:6.2f}%  {name}")
        if percent < FLOOR:
            below.append((name, percent))

    if below:
        for name, percent in below:
            print(f"FAIL {name} is at {percent:.2f}%, under the {FLOOR:.0f}% floor")
        return 1
    print(f"every module is at or above {FLOOR:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
