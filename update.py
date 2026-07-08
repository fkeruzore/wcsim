"""Fetch the live FIFA 2026 World Cup results and refresh results.json.

This pulls the real tournament status -- group stage and knockouts --
from ESPN's public, keyless soccer scoreboard API and writes it into
``results.json`` in the form ``main.py`` consumes. The web is the
source of truth: each run rebuilds the file from scratch, so any prior
hand edits are overwritten.

Only *who advances* is recorded for knockout games (the API's winner
flag already accounts for extra time and penalties); the shootout score
itself is not kept. ``main.py`` starts from this file by default; pass
``--ignore-standings`` there to simulate from scratch.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from main import (
    FIFA_POINTS,
    GROUPS,
    KNOCKOUT_FEED,
    R32_FIXED,
    R32_THIRD_SLOTS,
    RESULTS_PATH,
    assign_thirds,
    build_scaffold,
    group_of,
    pick_best_thirds,
    round_of_match,
    standings_from_results,
)

# ESPN's public scoreboard API for the men's World Cup. A single call
# over the tournament's date window returns all 104 matches.
ESPN_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/soccer/"
    "fifa.world/scoreboard"
)
DATE_WINDOW = "20260601-20260801"  # generous window around the cup

# ESPN spellings that differ from the canonical names in fifa_points.json
# / GROUPS. Everything else matches exactly.
NAME_MAP = {
    "Czechia": "Czech Republic",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Congo DR": "DR Congo",
    "Türkiye": "Turkey",
}


def source_url(window: str = DATE_WINDOW) -> str:
    """Full ESPN scoreboard URL for the given ``dates`` window."""
    return f"{ESPN_URL}?dates={window}&limit=500"


def fetch_events(url: str) -> list[dict]:
    """GET the ESPN scoreboard and return its ``events`` list.

    Raises ``RuntimeError`` with a clear message if the API can't be
    reached or returns something other than the expected JSON.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "wcsim/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"could not reach ESPN ({url}): {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bad JSON from ESPN ({url}): {exc}") from exc
    return payload.get("events", [])


def canonical(name: str) -> str | None:
    """Map an ESPN team name to its canonical name, or ``None``.

    Returns ``None`` for anything not in ``FIFA_POINTS`` -- e.g. the
    placeholder strings ("Round of 32 5 Winner") ESPN uses for matches
    whose participants aren't decided yet.
    """
    team = NAME_MAP.get(name, name)
    return team if team in FIFA_POINTS else None


def finished(event: dict) -> bool:
    """True if the match has been played to completion."""
    status = event["competitions"][0]["status"]["type"]
    return bool(status.get("completed"))


def teams_and_winner(event: dict) -> tuple[list[str], str | None] | None:
    """Return ``([team_a, team_b], winner_or_None)`` in canonical names.

    ``winner`` is ``None`` for a draw. Returns ``None`` if either side
    isn't a recognized team (an undecided knockout placeholder).
    """
    teams: list[str] = []
    winner: str | None = None
    for competitor in event["competitions"][0]["competitors"]:
        team = canonical(competitor["team"]["displayName"])
        if team is None:
            return None
        teams.append(team)
        if competitor.get("winner"):
            winner = team
    return teams, winner


def record_group(data: dict, teams: list[str], winner: str | None) -> None:
    """Set a group match's result in the scaffold by team pair."""
    group = group_of(teams[0])
    if group is None or group != group_of(teams[1]):
        return
    pair = set(teams)
    for match in data["groups"][group]:
        if {match["home"], match["away"]} == pair:
            match["result"] = winner if winner is not None else "Draw"
            return


def assign_knockouts(data: dict, web_ko: dict[frozenset[str], str]) -> None:
    """Map played knockout results onto match numbers in the scaffold.

    Reconstructs the bracket from the (complete) group standings, then
    walks it the way ``main.simulate_knockout`` does -- but instead of
    simulating, it looks each pairing up in ``web_ko`` (keyed by the two
    teams). Branches with feeders that haven't been played yet are left
    blank. Does nothing if the group stage isn't fully recorded.
    """
    known_groups: dict[str, dict[frozenset[str], str]] = {}
    for group, matches in data["groups"].items():
        played = {
            frozenset((m["home"], m["away"])): m["result"]
            for m in matches
            if m["result"] is not None
        }
        if len(played) < len(matches):
            print("  Knockout results skipped: group stage incomplete.")
            return
        known_groups[group] = played

    winners: dict[str, str] = {}
    runners_up: dict[str, str] = {}
    thirds: dict[str, str] = {}
    third_points: dict[str, int] = {}
    for group, teams in GROUPS.items():
        standings = standings_from_results(teams, known_groups[group])
        winners[group] = standings[0][0]
        runners_up[group] = standings[1][0]
        thirds[group] = standings[2][0]
        third_points[group] = standings[2][1]

    qualified = pick_best_thirds(thirds, third_points)
    assignment = assign_thirds(qualified)

    def slot_team(code: str) -> str:
        rank, group = code[0], code[1:]
        return winners[group] if rank == "1" else runners_up[group]

    match_winner: dict[int, str] = {}

    def record(match_no: int, a: str, b: str) -> None:
        winner = web_ko.get(frozenset((a, b)))
        if winner is not None:
            data["knockout"][str(match_no)] = winner
            match_winner[match_no] = winner

    for match_no, code_a, code_b in R32_FIXED:
        record(match_no, slot_team(code_a), slot_team(code_b))
    for match_no, winner_group, allowed in R32_THIRD_SLOTS:
        winner_team = winners[winner_group]
        # assign_thirds only guarantees *a* valid matching; when several
        # exist, it may not be the one FIFA actually drew. Prefer whichever
        # pairing the fetched web results confirm was actually played.
        actual_group = next(
            (
                group
                for group in allowed
                if group in qualified
                and frozenset((winner_team, thirds[group])) in web_ko
            ),
            assignment[match_no],
        )
        record(match_no, winner_team, thirds[actual_group])
    for match_no, feed_a, feed_b in KNOCKOUT_FEED:
        a = match_winner.get(int(feed_a[1:]))
        b = match_winner.get(int(feed_b[1:]))
        if a is not None and b is not None:
            record(match_no, a, b)


def fill_from_web(data: dict, events: list[dict]) -> None:
    """Populate a blank scaffold from fetched ESPN events."""
    web_ko: dict[frozenset[str], str] = {}
    for event in events:
        if not finished(event):
            continue
        slug = event.get("season", {}).get("slug", "")
        if slug == "3rd-place-match":
            continue  # not part of the simulated bracket
        parsed = teams_and_winner(event)
        if parsed is None:
            continue
        teams, winner = parsed
        if slug == "group-stage":
            record_group(data, teams, winner)
        elif winner is not None:
            web_ko[frozenset(teams)] = winner
    assign_knockouts(data, web_ko)


def refresh(path: Path, url: str) -> dict:
    """Build a fresh scaffold, fill it from the web, write it back."""
    data = build_scaffold()
    events = fetch_events(url)
    fill_from_web(data, events)
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
        description=(
            "Fetch live World Cup results from the web and refresh "
            "results.json."
        )
    )
    parser.add_argument(
        "--results-file",
        type=Path,
        default=RESULTS_PATH,
        help=f"path to the results file (default: {RESULTS_PATH.name})",
    )
    parser.add_argument(
        "--source-url",
        default=source_url(),
        help="ESPN scoreboard URL to fetch (default: the men's WC 2026)",
    )
    args = parser.parse_args()

    data = refresh(args.results_file, args.source_url)
    print(f"Wrote {args.results_file}\n")
    print_status(data)


if __name__ == "__main__":
    main()
