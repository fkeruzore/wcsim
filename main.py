"""A very simple mathematical simulation of the FIFA 2026 World Cup.

The 2026 tournament is the first with 48 teams: 12 groups of 4 play a single
round-robin; the 12 group winners, 12 runners-up and the 8 best third-placed
teams (32 teams total) advance to a brand-new Round of 32, followed by the
Round of 16, quarterfinals, semifinals and the final.

Match outcomes are *skill-based*: each game is drawn from the FIFA Elo
win-probability formula using published FIFA ranking points (see
``fifa_points.json``). The probability that team A beats team B is

    P(A) = 1 / (1 + 10 ** ((R_B - R_A) / s)),   with scale s = 600,

where R is a team's FIFA points. Group games can also end in a draw (3 points
for a win, 1 each for a draw): outcomes follow a Davidson tie model that adds a
draw probability while preserving the win/loss odds above. Knockout games never
draw -- a tie is resolved to a winner (extra time / penalties). Stronger teams
therefore advance more often, and the script traces the progression through
every round and reports the champion.

Format and bracket pairings are the real ones (final draw of 5 December 2025).
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from tqdm import trange

# --- Team strengths: FIFA ranking points (higher = stronger) ----------------
ELO_SCALE = 600  # FIFA's win-probability scale s
DRAW_NU = 2 / 3  # Davidson tie parameter; ~25% draws for evenly matched teams
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

# --- Results file: the real tournament status so far ------------------------
# A hand-editable record of matches already played. Modes start from it by
# default; ``--ignore-standings`` (or a missing/empty file) simulates fresh.
RESULTS_PATH = Path(__file__).parent / "results.json"


def knockout_match_numbers() -> list[int]:
    """All knockout match numbers actually used (73-104, skipping 103)."""
    return [
        match_no
        for _name, match_range in ROUND_NAMES
        for match_no in match_range
    ]


def build_scaffold() -> dict:
    """Build a blank results structure: every fixture with ``result: null``.

    Group matches are listed in the same ``combinations(teams, 2)`` order that
    :func:`simulate_group` iterates, so they map one-to-one onto the simulated
    fixtures. Knockout entries are keyed by match number (winner filled later).
    """
    groups = {
        group: [
            {"home": home, "away": away, "result": None}
            for home, away in combinations(teams, 2)
        ]
        for group, teams in GROUPS.items()
    }
    knockout = {str(match_no): None for match_no in knockout_match_numbers()}
    return {"updated": None, "groups": groups, "knockout": knockout}


def merge_results(scaffold: dict, existing: dict) -> dict:
    """Copy non-null results from ``existing`` onto a fresh ``scaffold``.

    Group matches are matched by ``(home, away)`` within a group and knockout
    matches by match number; anything in ``existing`` that no longer maps onto
    the scaffold (e.g. a renamed team) is silently dropped. ``scaffold`` is
    mutated and returned.
    """
    existing_groups = existing.get("groups", {})
    for group, matches in scaffold["groups"].items():
        previous = {
            (m.get("home"), m.get("away")): m.get("result")
            for m in existing_groups.get(group, [])
        }
        for match in matches:
            result = previous.get((match["home"], match["away"]))
            if result is not None:
                match["result"] = result
    existing_knockout = existing.get("knockout", {})
    for match_no in scaffold["knockout"]:
        if existing_knockout.get(match_no) is not None:
            scaffold["knockout"][match_no] = existing_knockout[match_no]
    return scaffold


def load_results(path: str | Path = RESULTS_PATH) -> dict | None:
    """Read and validate a results file into the form the simulator consumes.

    Returns ``None`` when the file is missing or records nothing yet (so the
    tournament is simulated fresh). Otherwise returns::

        {"groups": {group: {frozenset({home, away}): winner_or_"draw"}},
         "knockout": {match_no: winner}}

    with only the matches that have actually been played. Raises ``ValueError``
    with a clear message on a malformed file.
    """
    path = Path(path)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))

    groups: dict[str, dict[frozenset[str], str]] = {}
    for group, matches in raw.get("groups", {}).items():
        if group not in GROUPS:
            raise ValueError(f"unknown group {group!r} in {path}")
        valid_teams = set(GROUPS[group])
        known: dict[frozenset[str], str] = {}
        for match in matches:
            home, away, result = (
                match["home"],
                match["away"],
                match.get("result"),
            )
            if {home, away} - valid_teams:
                raise ValueError(
                    f"group {group}: {home!r} vs {away!r} are not "
                    "both in the group"
                )
            if result is None:
                continue
            if result.lower() != "draw" and result not in (home, away):
                raise ValueError(
                    f"group {group}: result {result!r} for {home} vs "
                    f'{away} must be {home!r}, {away!r}, "draw" or null'
                )
            known[frozenset((home, away))] = result
        if known:
            groups[group] = known

    knockout: dict[int, str] = {}
    for match_no, winner in raw.get("knockout", {}).items():
        if winner is None:
            continue
        if winner not in FIFA_POINTS:
            raise ValueError(
                f"knockout match {match_no}: unknown team {winner!r}"
            )
        knockout[int(match_no)] = winner

    if not groups and not knockout:
        return None
    return {"groups": groups, "knockout": knockout}


def standings_from_results(
    teams: list[str], known_group: dict[frozenset[str], str] | None
) -> list[tuple[str, int, int]]:
    """Current ``(team, points, played)`` from recorded matches only.

    Ranked by points then FIFA points, mirroring :func:`simulate_group`'s
    ranking. Unplayed matches are ignored.
    """
    points: Counter[str] = Counter()
    played: Counter[str] = Counter()
    for pair, result in (known_group or {}).items():
        a, b = tuple(pair)
        played[a] += 1
        played[b] += 1
        if result.lower() == "draw":
            points[a] += 1
            points[b] += 1
        else:
            points[result] += 3
    ranked = sorted(
        teams, key=lambda t: (points[t], FIFA_POINTS[t]), reverse=True
    )
    return [(team, points[team], played[team]) for team in ranked]


def win_probability(team_a: str, team_b: str) -> float:
    """FIFA Elo probability that ``team_a`` beats ``team_b``.

    P = 1 / (1 + 10 ** ((R_b - R_a) / s)) with scale s = 600.
    Equal points give 0.5, and win_prob(a, b) + win_prob(b, a) == 1.
    """
    diff = FIFA_POINTS[team_b] - FIFA_POINTS[team_a]
    return 1.0 / (1.0 + 10.0 ** (diff / ELO_SCALE))


def outcome_probabilities(
    team_a: str, team_b: str
) -> tuple[float, float, float]:
    """Davidson tie-model probabilities (P(A wins), P(draw), P(B wins)).

    Reduces to ``win_probability`` when ``DRAW_NU == 0``; preserves the
    win/loss odds ratio and is symmetric in A and B.
    """
    r = 10.0 ** ((FIFA_POINTS[team_a] - FIFA_POINTS[team_b]) / (2 * ELO_SCALE))
    denom = r + 1.0 / r + DRAW_NU
    return r / denom, DRAW_NU / denom, (1.0 / r) / denom


def play(team_a: str, team_b: str, draw_ok: bool = True) -> str | None:
    """Play a single match. Returns the winner, or ``None`` for a draw.

    With ``draw_ok=False`` the game always resolves to a winner (extra
    time / penalties), drawn straight from the Elo win probability.
    """
    if not draw_ok:
        return (
            team_a
            if random.random() < win_probability(team_a, team_b)
            else team_b
        )
    p_a, p_draw, _ = outcome_probabilities(team_a, team_b)
    x = random.random()
    if x < p_a:
        return team_a
    if x < p_a + p_draw:
        return None
    return team_b


def simulate_group(
    teams: list[str], known: dict[frozenset[str], str] | None = None
) -> list[tuple[str, int]]:
    """Round-robin a group of 4, returning (team, points) ranked
    1st -> 4th.

    Points are the usual 3 for a win, 1 each for a draw, 0 for a loss.
    Ranking is by points; teams level on points are separated by FIFA
    points (the higher-ranked side advances), a deterministic stand-in
    for the real goal-difference tiebreakers.

    ``known`` maps ``frozenset({home, away})`` of an already-played
    match to its recorded outcome (the winner's name or ``"draw"``);
    those matches are used as-is and consume no randomness, only the
    rest are simulated.
    """
    points: Counter[str] = Counter()
    for home, away in combinations(teams, 2):
        result = known.get(frozenset((home, away))) if known else None
        if result is None:  # not yet played -> simulate
            winner = play(home, away)  # draw_ok=True by default
        elif result.lower() == "draw":
            winner = None
        else:  # recorded winner
            winner = result
        if winner is None:
            points[home] += 1
            points[away] += 1
        else:
            points[winner] += 3
    ranked = sorted(
        teams, key=lambda t: (points[t], FIFA_POINTS[t]), reverse=True
    )
    return [(team, points[team]) for team in ranked]


def simulate_group_stage(
    known_groups: dict[str, dict[frozenset[str], str]] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, int]]:
    """Run all 12 groups.

    Returns the winner, runner-up and third per group, plus each
    third-placed team's points (needed to rank the best thirds).

    ``known_groups`` maps a group letter to its already-played matches (see
    :func:`simulate_group`); the remaining fixtures are simulated.
    """
    winners: dict[str, str] = {}
    runners_up: dict[str, str] = {}
    thirds: dict[str, str] = {}
    third_points: dict[str, int] = {}
    for group, teams in GROUPS.items():
        known = known_groups.get(group) if known_groups else None
        (first, _), (second, _), (third, third_pts), _fourth = simulate_group(
            teams, known
        )
        winners[group] = first
        runners_up[group] = second
        thirds[group] = third
        third_points[group] = third_pts
    return winners, runners_up, thirds, third_points


def pick_best_thirds(
    thirds: dict[str, str], third_points: dict[str, int]
) -> list[str]:
    """Choose the source groups of the 8 best of the 12 third-placed
    teams.

    Thirds are ranked by points, then by FIFA points (a deterministic
    proxy for the real points/goal-difference criteria). Returns the
    qualifying groups sorted alphabetically.
    """
    best = sorted(
        thirds,
        key=lambda g: (third_points[g], FIFA_POINTS[thirds[g]]),
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
    known_knockout: dict[int, str] | None = None,
) -> tuple[dict[int, tuple[str, str, str]], str]:
    """Play the knockout bracket.

    Returns {match_no: (a, b, winner)} and the champion. ``known_knockout``
    maps a match number to its recorded winner; a recorded winner is used as-is
    when it is one of the two participants (only possible once the relevant
    group results are settled), otherwise the match is simulated.
    """
    known_knockout = known_knockout or {}

    def slot_team(code: str) -> str:
        rank, group = code[0], code[1:]
        return winners[group] if rank == "1" else runners_up[group]

    def resolve(match_no: int, a: str, b: str) -> tuple[str, str, str]:
        recorded = known_knockout.get(match_no)
        winner = recorded if recorded in (a, b) else play(a, b, draw_ok=False)
        return (a, b, winner)

    results: dict[int, tuple[str, str, str]] = {}

    # Knockouts resolve to a winner (extra time / penalties): no draws.
    # Round of 32: fixed pairings, then group-winner vs assigned third-placed.
    for match_no, code_a, code_b in R32_FIXED:
        results[match_no] = resolve(
            match_no, slot_team(code_a), slot_team(code_b)
        )
    for match_no, winner_group, _allowed in R32_THIRD_SLOTS:
        a = winners[winner_group]
        b = thirds[third_assignment[match_no]]
        results[match_no] = resolve(match_no, a, b)

    # Round of 16 onward: resolve "W<n>" feeders from earlier results.
    for match_no, feed_a, feed_b in KNOCKOUT_FEED:
        a = results[int(feed_a[1:])][2]
        b = results[int(feed_b[1:])][2]
        results[match_no] = resolve(match_no, a, b)

    return results, results[104][2]


def simulate_world_cup(
    seed: int | None = None,
    known: dict | None = None,
) -> tuple[str, dict, dict]:
    """Simulate one full tournament.

    Returns the champion plus the group-stage and knockout details
    needed to trace the progression. If ``seed`` is given the run is
    reproducible. ``known`` is the parsed results from :func:`load_results`
    (``{"groups": ..., "knockout": ...}``); recorded matches are kept fixed and
    only the rest are simulated.
    """
    if seed is not None:
        random.seed(seed)

    known = known or {}
    winners, runners_up, thirds, third_points = simulate_group_stage(
        known.get("groups")
    )
    qualified_groups = pick_best_thirds(thirds, third_points)
    third_assignment = assign_thirds(qualified_groups)
    results, champion = simulate_knockout(
        winners, runners_up, thirds, third_assignment, known.get("knockout")
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


def run_many(runs: int, seed: int | None, known: dict | None = None) -> None:
    """Simulate many tournaments and print a champion frequency tally."""
    if seed is not None:
        random.seed(seed)
    tally: Counter[str] = Counter()
    for _ in trange(runs):
        champion, _, _ = simulate_world_cup(known=known)
        tally[champion] += 1

    print(
        f"Champions over {runs:,} simulated tournaments"
        f" (Elo-weighted, so stronger teams win more often):"
    )
    for team, count in tally.most_common():
        print(f"  {team:<24} {count:>7}  ({100 * count / runs:5.2f}%)")


def round_of_match(match_no: int) -> str:
    """Return the round name (e.g. "Round of 16") for a knockout match."""
    for name, match_range in ROUND_NAMES:
        if match_no in match_range:
            return name
    raise ValueError(f"unknown match number {match_no}")


def group_of(team: str) -> str | None:
    """Return the group letter a team belongs to, or None if not found."""
    for group, teams in GROUPS.items():
        if team in teams:
            return group
    return None


def simulate_meetings(
    team_a: str,
    team_b: str,
    runs: int,
    seed: int | None = None,
    known: dict | None = None,
) -> list[str]:
    """Run ``runs`` tournaments and report how often two teams meet.

    Returns the list of rounds in which the two teams met (one entry per
    meeting). Teams in the same group always meet once in the group stage and
    may meet again from the quarterfinals onward, so a single tournament can
    contribute more than one meeting. Also prints a human-readable summary.
    """
    for team in (team_a, team_b):
        if team not in FIFA_POINTS:
            raise KeyError(f"unknown team: {team!r}")
    if seed is not None:
        random.seed(seed)

    pair = {team_a, team_b}
    same_group = group_of(team_a) == group_of(team_b)

    rounds_met: list[str] = []
    tournaments_with_meeting = 0
    for _ in trange(runs):
        met_this_run: list[str] = []
        if same_group:  # a round-robin guarantees a group-stage meeting
            met_this_run.append("Group stage")
        _champion, _group_stage, results = simulate_world_cup(known=known)
        for match_no, (a, b, _winner) in results.items():
            if {a, b} == pair:
                met_this_run.append(round_of_match(match_no))
        rounds_met.extend(met_this_run)
        tournaments_with_meeting += bool(met_this_run)

    pct = 100 * tournaments_with_meeting / runs
    summary = (
        f"{team_a} met {team_b} {tournaments_with_meeting}/{runs} times "
        f"({pct:.1f}%)"
    )
    if rounds_met:
        top_round, top_count = Counter(rounds_met).most_common(1)[0]
        summary += (
            f", most often in the {top_round} ({100 * top_count / runs:.1f}%)"
        )
    print(summary)
    return rounds_met


def analyze_team(
    team: str, runs: int, seed: int | None = None, known: dict | None = None
) -> None:
    """Run ``runs`` tournaments and report on a single team's fortunes.

    Prints how often the team wins the cup and reaches each knockout round,
    the teams it loses to most often in the knockouts (and in which round),
    and the teams it faces most often in the knockout rounds. Group games are
    excluded from the loss/opponent tallies. Reuses :func:`simulate_world_cup`,
    mining the knockout results it returns.
    """
    if team not in FIFA_POINTS:
        raise KeyError(f"unknown team: {team!r}")
    if seed is not None:
        random.seed(seed)

    titles = 0
    rounds_reached: Counter[str] = Counter()
    losses_by_opponent: dict[str, Counter[str]] = defaultdict(Counter)
    knockout_opponents: Counter[str] = Counter()

    for _ in trange(runs):
        champion, _group_stage, results = simulate_world_cup(known=known)
        won = champion == team

        # Knockout matches involving the team: opponents faced and any loss.
        team_knockouts = [
            (match_no, a, b, winner)
            for match_no, (a, b, winner) in results.items()
            if team in (a, b)
        ]
        for match_no, a, b, winner in team_knockouts:
            rounds_reached[round_of_match(match_no)] += 1
            opponent = b if a == team else a
            knockout_opponents[opponent] += 1
            if winner != team:
                losses_by_opponent[opponent][round_of_match(match_no)] += 1

        if won:
            titles += 1

    print(f"{team} over {runs:,} simulated tournaments:")
    print(f"  Won the cup {titles}/{runs} times ({100 * titles / runs:.2f}%)")
    for round_name, _ in ROUND_NAMES:
        count = rounds_reached[round_name]
        print(
            f"  Made it to the {round_name:<16} "
            f"{count:>6}/{runs}  ({100 * count / runs:5.2f}%)"
        )

    print("  Lost most often to (knockout rounds only):")
    loss_totals = Counter(
        {
            opp: sum(rounds.values())
            for opp, rounds in losses_by_opponent.items()
        }
    )
    for opponent, total in loss_totals.most_common(3):
        when, _ = losses_by_opponent[opponent].most_common(1)[0]
        print(
            f"    {opponent:<24} {total:>7}  ({100 * total / runs:5.2f}%)"
            f", most often in the {when}"
        )

    print("  Faced most often (knockout rounds only):")
    for opponent, count in knockout_opponents.most_common(5):
        print(f"    {opponent:<24} {count:>7}  ({100 * count / runs:5.2f}%)")


def main() -> None:
    global ELO_SCALE, DRAW_NU
    parser = argparse.ArgumentParser(
        description=(
            "Simulate the FIFA 2026 World Cup with Elo-based match outcomes."
        )
    )
    parser.add_argument("--seed", type=int, default=None, help="random seed")
    parser.add_argument(
        "-n",
        "--runs",
        type=int,
        default=None,
        help="simulate this many tournaments and print a champion tally",
    )
    parser.add_argument(
        "--elo-scale",
        type=float,
        default=ELO_SCALE,
        help=f"FIFA Elo win-probability scale (default: {ELO_SCALE})",
    )
    parser.add_argument(
        "--nu",
        type=float,
        default=DRAW_NU,
        help=(
            "Davidson tie parameter for draw probability"
            f" (default: {DRAW_NU:.4f})"
        ),
    )
    parser.add_argument(
        "--meet",
        nargs=2,
        metavar=("TEAM_A", "TEAM_B"),
        help=(
            "run --runs tournaments (default 1000) and report how often the "
            "two teams meet, and in which round"
        ),
    )
    parser.add_argument(
        "--team",
        metavar="TEAM",
        help=(
            "run --runs tournaments (default 1000) and report on one team: "
            "title rate, exit stages, who it loses to, and who it faces most"
        ),
    )
    parser.add_argument(
        "--results-file",
        type=Path,
        default=RESULTS_PATH,
        help=(
            "real results so far to start from, as written by update.py "
            f"(default: {RESULTS_PATH.name})"
        ),
    )
    parser.add_argument(
        "--ignore-standings",
        action="store_true",
        help="ignore the results file and simulate the whole tournament fresh",
    )
    args = parser.parse_args()

    ELO_SCALE = args.elo_scale
    DRAW_NU = args.nu
    known = None if args.ignore_standings else load_results(args.results_file)

    if args.meet:
        simulate_meetings(
            args.meet[0], args.meet[1], args.runs or 1000, args.seed, known
        )
    elif args.team:
        analyze_team(args.team, args.runs or 1000, args.seed, known)
    elif args.runs:
        run_many(args.runs, args.seed, known)
    else:
        if known is not None:
            print(f"(continuing from {args.results_file})\n")
        champion, group_stage, results = simulate_world_cup(
            seed=args.seed, known=known
        )
        print_trace(champion, group_stage, results)


if __name__ == "__main__":
    main()
