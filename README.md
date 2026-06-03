# wcsim

A Monte Carlo simulator for the FIFA 2026 World Cup.
Match outcomes are drawn from the [FIFA Elo win-probability formula](https://en.wikipedia.org/wiki/FIFA_World_Rankings#Mathematical_development_of_the_model) using real FIFA ranking points, and the bracket follows the real final draw of 5 December 2025 (48 teams, 12 groups, Round of 32 through Final).

## Usage

**Single tournament trace** — play one full tournament and print every result:

```
$ uv run main.py --seed 42  # seed is optional
...
Round of 32:  Match 73: Czech Republic  vs Switzerland  -> Switzerland
              Match 74: Germany         vs United States -> United States  ...
...
Final:        Match 104: Switzerland    vs Portugal      -> Portugal
========================================================
CHAMPION: Portugal
========================================================
```

**Champion tally** — simulate many tournaments and rank teams by how often they win:

```
$ uv run main.py --runs 10000 --seed 42
Champions over 10,000 simulated tournaments (Elo-weighted, so stronger teams win more often):
  France                      1323  (13.23%)
  Spain                       1317  (13.17%)
  Argentina                   1268  (12.68%)
  England                      840  ( 8.40%)
  ...
```

**Matchup probability** — report how often two specific teams meet across many tournaments:

```
$ uv run main.py --meet France Argentina --runs 10000 --seed 42
France met Argentina 654/10000 times (6.5%), most often in the Final (3.2%)
```

Pass `--seed <int>` to any mode for reproducible results.
