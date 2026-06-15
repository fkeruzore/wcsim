"""Create or refresh the editable results file and report standings.

``results.json`` records the real FIFA 2026 World Cup matches played so
far. Running this script builds the file the first time (every fixture
blank) and, on later runs, validates and re-summarises it while keeping
the results you typed in by hand. ``main.py`` starts from this file by
default; pass ``--ignore-standings`` there to simulate from scratch.

Edit ``results.json`` by hand between runs: set a group match's
``"result"`` to the winning team's name or ``"draw"`` (leave ``null`` if
not yet played), and set a knockout entry to its winner's name.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from main import (
    GROUPS,
    RESULTS_PATH,
    build_scaffold,
    merge_results,
    round_of_match,
    standings_from_results,
)


def refresh(path: Path) -> dict:
    """Build a blank scaffold, merge existing results, write it back."""
    data = build_scaffold()
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        merge_results(data, existing)
    data["updated"] = date.today().isoformat()
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return data


def print_status(data: dict) -> None:
    """Print per-group standings and any recorded knockout results."""
    print(f"Tournament status (updated {data['updated']}):\n")
    for group, matches in data["groups"].items():
        known = {
            frozenset((m["home"], m["away"])): m["result"]
            for m in matches
            if m["result"] is not None
        }
        print(f"  Group {group}  ({len(known)}/{len(matches)} played):")
        standings = standings_from_results(GROUPS[group], known)
        for rank, (team, points, played) in enumerate(standings, start=1):
            print(f"    {rank}. {team:<24} {points:>2} pts  ({played} played)")

    recorded = {
        int(no): w for no, w in data["knockout"].items() if w is not None
    }
    print("\n  Knockout results so far:")
    if not recorded:
        print("    none yet")
    for match_no in sorted(recorded):
        round_name = round_of_match(match_no)
        print(f"    Match {match_no} ({round_name}): {recorded[match_no]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh results.json and report the current standings."
    )
    parser.add_argument(
        "--results-file",
        type=Path,
        default=RESULTS_PATH,
        help=f"path to the results file (default: {RESULTS_PATH.name})",
    )
    args = parser.parse_args()

    data = refresh(args.results_file)
    print(f"Wrote {args.results_file}\n")
    print_status(data)


if __name__ == "__main__":
    main()
