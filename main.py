"""A very simple mathematical simulation of the FIFA 2026 World Cup.

The 2026 tournament is the first with 48 teams: 12 groups of 4 play a single
round-robin; the 12 group winners, 12 runners-up and the 8 best third-placed
teams (32 teams total) advance to a brand-new Round of 32, followed by the
Round of 16, quarterfinals, semifinals and the final.

Match outcomes are *skill-based*: each game is drawn from the FIFA Elo
win-probability formula using published FIFA ranking points (see
``fifa_points.json``). The probability that team A beats team B is

    P(A) = 1 / (1 + 10 ** ((R_B - R_A) / s)),   with scale s = 600,

where R is a team's FIFA points. Stronger teams therefore advance more often,
and the script traces the progression through every round and reports the
champion.

Format and bracket pairings are the real ones (final draw of 5 December 2025).
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from itertools import combinations
from pathlib import Path

# --- Team strengths: FIFA ranking points (higher = stronger) ----------------
ELO_SCALE = 600  # FIFA's win-probability scale s
FIFA_POINTS: dict[str, float] = {
    team: points
    for team, points in json.loads(
        (Path(__file__).parent / "fifa_points.json").read_text(
            encoding="utf-8"
        )
    ).items()
    if not team.startswith("_")
}

# --- The real group draw (final draw, 5 December 2025) ----------------------
# A handful of slots were European/intercontinental play-off berths at draw
# time; they are filled here with their best-available resolution.
GROUPS: dict[str, list[str]] = {
    "A": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curaçao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

# --- Round of 32 pairings (real bracket, match numbers 73-88) ---------------
# Slot codes: "1X" = winner of group X, "2X" = runner-up of group X.
R32_FIXED: list[tuple[int, str, str]] = [
    (73, "2A", "2B"),
    (75, "1F", "2C"),
    (76, "1C", "2F"),
    (78, "2E", "2I"),
    (83, "2K", "2L"),
    (84, "1H", "2J"),
    (86, "1J", "2H"),
    (88, "2D", "2G"),
]

# Each third-placed slot pits a group winner against a best-third finisher
# whose source group must come from the allowed set.
# (match_no, winner_group, allowed)
R32_THIRD_SLOTS: list[tuple[int, str, frozenset[str]]] = [
    (74, "E", frozenset("ABCDF")),
    (77, "I", frozenset("CDFGH")),
    (79, "A", frozenset("CEFHI")),
    (80, "L", frozenset("EHIJK")),
    (81, "D", frozenset("BEFIJ")),
    (82, "G", frozenset("AEHIJ")),
    (85, "B", frozenset("EFGIJ")),
    (87, "K", frozenset("DEIJL")),
]

# --- Knockout feed-through (match_no, feeder_a, feeder_b) -------------------
# "W<n>" means "winner of match n".
KNOCKOUT_FEED: list[tuple[int, str, str]] = [
    # Round of 16
    (89, "W74", "W77"),
    (90, "W73", "W75"),
    (91, "W76", "W78"),
    (92, "W79", "W80"),
    (93, "W83", "W84"),
    (94, "W81", "W82"),
    (95, "W86", "W88"),
    (96, "W85", "W87"),
    # Quarterfinals
    (97, "W89", "W90"),
    (98, "W93", "W94"),
    (99, "W91", "W92"),
    (100, "W95", "W96"),
    # Semifinals
    (101, "W97", "W98"),
    (102, "W99", "W100"),
    # Final
    (104, "W101", "W102"),
]

ROUND_NAMES: list[tuple[str, range]] = [
    ("Round of 32", range(73, 89)),
    ("Round of 16", range(89, 97)),
    ("Quarterfinals", range(97, 101)),
    ("Semifinals", range(101, 103)),
    ("Final", range(104, 105)),
]


def win_probability(team_a: str, team_b: str) -> float:
    """FIFA Elo probability that ``team_a`` beats ``team_b``.

    P = 1 / (1 + 10 ** ((R_b - R_a) / s)) with scale s = 600.
    Equal points give 0.5, and win_prob(a, b) + win_prob(b, a) == 1.
    """
    diff = FIFA_POINTS[team_b] - FIFA_POINTS[team_a]
    return 1.0 / (1.0 + 10.0 ** (diff / ELO_SCALE))


def play(team_a: str, team_b: str) -> str:
    """Play a single match, drawing the winner from the Elo win
    probability."""
    return (
        team_a if random.random() < win_probability(team_a, team_b) else team_b
    )


def simulate_group(teams: list[str]) -> list[tuple[str, int]]:
    """Round-robin a group of 4, returning (team, wins) ranked
    1st -> 4th.

    Ranking is by wins; teams level on wins are separated by FIFA points
    (the higher-ranked side advances), a deterministic stand-in for the
    real goal-difference tiebreakers.
    """
    wins: Counter[str] = Counter()
    for home, away in combinations(teams, 2):
        wins[play(home, away)] += 1
    ranked = sorted(
        teams, key=lambda t: (wins[t], FIFA_POINTS[t]), reverse=True
    )
    return [(team, wins[team]) for team in ranked]


def simulate_group_stage() -> tuple[
    dict[str, str], dict[str, str], dict[str, str], dict[str, int]
]:
    """Run all 12 groups.

    Returns the winner, runner-up and third per group, plus each
    third-placed team's win count (needed to rank the best thirds).
    """
    winners: dict[str, str] = {}
    runners_up: dict[str, str] = {}
    thirds: dict[str, str] = {}
    third_wins: dict[str, int] = {}
    for group, teams in GROUPS.items():
        (first, _), (second, _), (third, third_w), _fourth = simulate_group(
            teams
        )
        winners[group] = first
        runners_up[group] = second
        thirds[group] = third
        third_wins[group] = third_w
    return winners, runners_up, thirds, third_wins


def pick_best_thirds(
    thirds: dict[str, str], third_wins: dict[str, int]
) -> list[str]:
    """Choose the source groups of the 8 best of the 12 third-placed
    teams.

    Thirds are ranked by wins, then by FIFA points (a deterministic
    proxy for the real points/goal-difference criteria). Returns the
    qualifying groups sorted alphabetically.
    """
    best = sorted(
        thirds,
        key=lambda g: (third_wins[g], FIFA_POINTS[thirds[g]]),
        reverse=True,
    )[:8]
    return sorted(best)


def assign_thirds(qualified_groups: list[str]) -> dict[int, str]:
    """Match the 8 qualifying third-placed groups onto the 8 third slots.

    Each slot only accepts thirds from its allowed set of groups (FIFA's
    495-combination matrix). We find any valid perfect matching via
    augmenting paths; one is always guaranteed to exist.
    Returns {match_no: group}.
    """
    match_of_group: dict[str, int] = {}

    def try_assign(group: str, seen: set[int]) -> bool:
        for match_no, _winner, allowed in R32_THIRD_SLOTS:
            if group in allowed and match_no not in seen:
                seen.add(match_no)
                occupant = next(
                    (g for g, m in match_of_group.items() if m == match_no),
                    None,
                )
                if occupant is None or try_assign(occupant, seen):
                    match_of_group[group] = match_no
                    return True
        return False

    for group in qualified_groups:
        if not try_assign(group, set()):
            raise RuntimeError(f"no valid third-place slot for group {group}")
    return {match_no: group for group, match_no in match_of_group.items()}


def simulate_knockout(
    winners: dict[str, str],
    runners_up: dict[str, str],
    thirds: dict[str, str],
    third_assignment: dict[int, str],
) -> tuple[dict[int, tuple[str, str, str]], str]:
    """Play the knockout bracket.

    Returns {match_no: (a, b, winner)} and the champion.
    """

    def slot_team(code: str) -> str:
        rank, group = code[0], code[1:]
        return winners[group] if rank == "1" else runners_up[group]

    results: dict[int, tuple[str, str, str]] = {}

    # Round of 32: fixed pairings, then group-winner vs assigned third-placed.
    for match_no, code_a, code_b in R32_FIXED:
        a, b = slot_team(code_a), slot_team(code_b)
        results[match_no] = (a, b, play(a, b))
    for match_no, winner_group, _allowed in R32_THIRD_SLOTS:
        a = winners[winner_group]
        b = thirds[third_assignment[match_no]]
        results[match_no] = (a, b, play(a, b))

    # Round of 16 onward: resolve "W<n>" feeders from earlier results.
    for match_no, feed_a, feed_b in KNOCKOUT_FEED:
        a = results[int(feed_a[1:])][2]
        b = results[int(feed_b[1:])][2]
        results[match_no] = (a, b, play(a, b))

    return results, results[104][2]


def simulate_world_cup(
    seed: int | None = None,
) -> tuple[str, dict, dict]:
    """Simulate one full tournament.

    Returns the champion plus the group-stage and knockout details
    needed to trace the progression. If ``seed`` is given the run is
    reproducible.
    """
    if seed is not None:
        random.seed(seed)

    winners, runners_up, thirds, third_wins = simulate_group_stage()
    qualified_groups = pick_best_thirds(thirds, third_wins)
    third_assignment = assign_thirds(qualified_groups)
    results, champion = simulate_knockout(
        winners, runners_up, thirds, third_assignment
    )

    group_stage = {
        "winners": winners,
        "runners_up": runners_up,
        "thirds": thirds,
        "qualified_thirds": qualified_groups,
    }
    return champion, group_stage, results


def print_trace(champion: str, group_stage: dict, results: dict) -> None:
    """Print a full, human-readable trace of the simulated tournament."""
    print("=" * 56)
    print("FIFA World Cup 2026 - simulated tournament")
    print("=" * 56)

    def labelled(team: str) -> str:
        return f"{team} ({FIFA_POINTS[team]:.0f})"

    print(
        "\nGroup stage (1st / 2nd / 3rd advance candidates;FIFA points shown):"
    )
    for group in GROUPS:
        w = group_stage["winners"][group]
        r = group_stage["runners_up"][group]
        t = group_stage["thirds"][group]
        print(
            f"  Group {group}:  1. {labelled(w):<28} "
            f"2. {labelled(r):<28} 3. {labelled(t)}"
        )

    qt = group_stage["qualified_thirds"]
    print(f"\nBest 8 third-placed teams advance (groups {', '.join(qt)}):")
    for group in qt:
        print(f"  {group}: {group_stage['thirds'][group]}")

    for name, match_range in ROUND_NAMES:
        print(f"\n{name}:")
        for match_no in match_range:
            a, b, winner = results[match_no]
            print(f"  Match {match_no}: {a:<24} vs {b:<24} -> {winner}")

    print("\n" + "=" * 56)
    print(f"CHAMPION: {champion}")
    print("=" * 56)


def run_many(runs: int, seed: int | None) -> None:
    """Simulate many tournaments and print a champion frequency tally."""
    if seed is not None:
        random.seed(seed)
    tally: Counter[str] = Counter()
    for _ in range(runs):
        champion, _, _ = simulate_world_cup()
        tally[champion] += 1

    print(
        f"Champions over {runs:,} simulated tournaments"
        f" (Elo-weighted, so stronger teams win more often):"
    )
    for team, count in tally.most_common():
        print(f"  {team:<24} {count:>7}  ({100 * count / runs:5.2f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate the FIFA 2026 World Cup with Elo-based match outcomes."
        )
    )
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    parser.add_argument(
        "--runs",
        type=int,
        default=None,
        help="simulate this many tournaments and print a champion tally",
    )
    args = parser.parse_args()

    if args.runs:
        run_many(args.runs, args.seed)
    else:
        champion, group_stage, results = simulate_world_cup(seed=args.seed)
        print_trace(champion, group_stage, results)


if __name__ == "__main__":
    main()
