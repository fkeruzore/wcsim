# wcsim

A Monte Carlo simulator for the FIFA 2026 World Cup.
Match outcomes are drawn from the [FIFA Elo win-probability formula](https://en.wikipedia.org/wiki/FIFA_World_Rankings#Mathematical_development_of_the_model) using real FIFA ranking points, and the bracket follows the real final draw of 5 December 2025 (48 teams, 12 groups, Round of 32 through Final).

## Usage

**Single tournament trace** — play one full tournament and print every result:

```sh
uv run main.py --seed 66  # seed is optional
```
```
========================================================
FIFA World Cup 2026 - simulated tournament
========================================================

Group stage (1st / 2nd / 3rd advance candidates;FIFA points shown):
  Group A:  1. Mexico (1681)                2. South Korea (1589)           3. Czech Republic (1501)
  Group B:  1. Qatar (1455)                 2. Switzerland (1649)           3. Canada (1556)
[...]

Best 8 third-placed teams advance (groups B, D, E, F, G, I, J, L):
  B: Canada
  D: Australia
  E: Ivory Coast
  F: Sweden
  G: Iran
  I: Senegal
  J: Algeria
  L: England

Round of 32:
  Match 73: South Korea              vs Switzerland              -> South Korea
  Match 74: Ecuador                  vs Australia                -> Ecuador
[...]

Final:
  Match 104: France                   vs Senegal                  -> France

========================================================
CHAMPION: France
========================================================
```

**Champion tally** — simulate many tournaments and rank teams by how often they win:

```sh
uv run main.py --runs 10000
```
```
Champions over 10,000 simulated tournaments (Elo-weighted, so stronger teams win more often):
  France                      1323  (13.23%)
  Spain                       1317  (13.17%)
  Argentina                   1268  (12.68%)
  England                      840  ( 8.40%)
[...]
```

**Matchup probability** — report how often two specific teams meet across many tournaments:

```sh
uv run main.py --meet France Argentina --runs 10000
```
```
France met Argentina 670/10000 times (6.7%), most often in the Final (3.2%)
```

Pass `--seed <int>` to any mode for reproducible results.
