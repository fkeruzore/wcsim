# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Monte Carlo simulator for the FIFA 2026 World Cup (48 teams, 12 groups, Round of 32 → Final). Match outcomes are drawn from the FIFA Elo win-probability formula using real FIFA ranking points. Pure Python standard library — no runtime dependencies.

## Commands

This is a `uv`-managed project (Python 3.12). Run everything through `uv run`:

```sh
uv run main.py                              # single-tournament trace (continues from results.json)
uv run main.py --seed 47                    # reproducible run
uv run main.py -n 10000 --seed 47           # champion tally over N tournaments
uv run main.py --meet France Argentina -n 10000   # how often two teams meet, and where
uv run main.py --team France -n 10000       # one team's title rate, exit stages, opponents
uv run main.py --ignore-standings           # simulate fresh, ignoring results.json
uv run update.py                            # create/refresh results.json and print standings
```

Knobs: `--elo-scale` (default 600; larger ⇒ outcomes closer to 50/50, more upsets) and `--nu` (Davidson draw parameter, default 2/3; `--nu 0` disables group draws). `--results-file PATH` reads an alternate results file.

Lint and format (ruff is the only dev dependency):

```sh
uv run ruff check .
uv run ruff format .
```

There is no test suite. Code style is enforced by `pyproject.toml`: line length 79, max doc/comment length 72, lint rules `E`, `F`, `B`.

## Architecture

Two scripts plus two JSON data files. `update.py` imports from `main.py`; `main.py` imports nothing local.

**`main.py`** — the simulator. The tournament structure is fully data-driven by module-level constants near the top; understanding these is the key to the file:
- `GROUPS` — the 12 real groups (final draw, 5 Dec 2025).
- `R32_FIXED` / `R32_THIRD_SLOTS` — Round-of-32 pairings. Most are fixed slot codes (`"1F"` = winner of group F, `"2C"` = runner-up of C). Eight slots pair a group winner against one of the 8 best third-placed teams, where each slot only accepts thirds from an `allowed` set of groups (FIFA's third-place matrix). `assign_thirds` solves this as a bipartite matching via augmenting paths.
- `KNOCKOUT_FEED` — Round of 16 onward, where each match feeds from `"W<n>"` (winner of match n).
- `ROUND_NAMES` — maps match-number ranges to round names. Note match 103 is intentionally skipped (no third-place playoff is simulated).

Match model: `win_probability` is the Elo formula `1 / (1 + 10**((R_b - R_a)/s))`. `outcome_probabilities` extends it to a Davidson tie model (win/draw/loss) for group games. `play` resolves a single match; with `draw_ok=False` (all knockout games) it always produces a winner. `ELO_SCALE` and `DRAW_NU` are module globals that `main()` reassigns from CLI args before simulating.

Simulation flow: `simulate_world_cup` → `simulate_group_stage` (each group via `simulate_group`) → `pick_best_thirds` → `assign_thirds` → `simulate_knockout`, returning the champion plus group/knockout detail. The reporting modes (`run_many`, `simulate_meetings`, `analyze_team`) all wrap `simulate_world_cup` and mine its returned results.

**Known-results overlay** — every simulation can start from matches already played. `load_results` parses `results.json` into `{"groups": {group: {frozenset({home,away}): winner_or_"draw"}}, "knockout": {match_no: winner}}`; recorded matches are kept fixed and consume no randomness, only the rest are simulated. This `known` dict threads through every simulate function. `main()` loads it by default unless `--ignore-standings` is passed.

**`update.py`** — maintains `results.json`. `build_scaffold` generates a blank file with every fixture `null` (group matches in the exact `combinations(teams, 2)` order `simulate_group` iterates, so they map one-to-one). `merge_results` re-applies hand-entered results onto a fresh scaffold by `(home, away)` / match number. Edit `results.json` by hand between runs: a group match's `"result"` is the winning team's name, `"draw"`, or `null`; a knockout entry is its winner's name.

**Data files**: `fifa_points.json` (team → FIFA ranking points; keys starting with `_` are metadata and skipped on load) and `results.json` (the live tournament status, hand-edited).

## Conventions

- Group-match identity is always a `frozenset({home, away})` so home/away order never matters when looking up a recorded result.
- When changing the bracket, keep `GROUPS`, the R32 constants, `KNOCKOUT_FEED`, and `ROUND_NAMES` mutually consistent — match numbers (73–104) are the shared key across all of them.
- Team names must match exactly between `GROUPS`, `fifa_points.json`, and `results.json`; `load_results` validates this and raises `ValueError` on mismatches.
