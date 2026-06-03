# wcsim

A Monte Carlo simulator for the FIFA 2026 World Cup.
Match outcomes are drawn from the [FIFA Elo win-probability formula](https://en.wikipedia.org/wiki/FIFA_World_Rankings#Mathematical_development_of_the_model) using real FIFA ranking points, and the bracket follows the real final draw of 5 December 2025 (48 teams, 12 groups, Round of 32 through Final).

## Basic usage

**Single tournament trace** — play one full tournament and print every result:

```sh
uv run main.py --seed 47  # seed is optional
```
```
========================================================
FIFA World Cup 2026 - simulated tournament
========================================================

Group stage (1st / 2nd / 3rd advance candidates;FIFA points shown):
  Group A:  1. Mexico (1681)                2. South Korea (1589)           3. South Africa (1430)
  Group B:  1. Canada (1556)                2. Switzerland (1649)           3. Bosnia and Herzegovina (1386)
[...]

Best 8 third-placed teams advance (groups B, C, D, G, H, I, K, L):
  B: Bosnia and Herzegovina
  C: Scotland
  D: United States
  G: New Zealand
  H: Cape Verde
  I: Norway
  K: Portugal
  L: Croatia

Round of 32:
  Match 73: South Korea              vs Switzerland              -> Switzerland
  Match 74: Ecuador                  vs United States            -> United States
[...]

Final:
  Match 104: France                   vs Japan                    -> France

========================================================
CHAMPION: France
========================================================
```

**Champion tally** — simulate many tournaments and rank teams by how often they win:

```sh
uv run main.py --runs 10000 --seed 47
```
```
Champions over 10,000 simulated tournaments (Elo-weighted, so stronger teams win more often):
  France                      1343  (13.43%)
  Spain                       1210  (12.10%)
  Argentina                   1173  (11.73%)
  England                      883  ( 8.83%)
[...]
```

**Matchup probability** — report how often two specific teams meet across many tournaments:

```sh
uv run main.py --meet France Argentina --runs 10000 --seed 47
```
```
France met Argentina 693/10000 times (6.9%), most often in the Semifinals (3.7%)
```

Pass `--seed <int>` to any mode for reproducible results.

## Advanced

**Varying simulation parameters** — adjust the Elo scale (`--elo-scale`) or the draw probability (`--nu`) to explore different physical assumptions:

```sh
uv run main.py -n 10000 --elo-scale 1200 --seed 47  # wide scale: win probabilities closer to 50/50, more upsets
```
```
Champions over 10,000 simulated tournaments (Elo-weighted, so stronger teams win more often):
  France                       781  ( 7.81%)
  Spain                        688  ( 6.88%)
  Argentina                    679  ( 6.79%)
  England                      558  ( 5.58%)
[...]
```

```sh
uv run main.py -n 10000 --nu 0 --seed 47  # no draws: every group game has a winner
```
```
Champions over 10,000 simulated tournaments (Elo-weighted, so stronger teams win more often):
  France                      1276  (12.76%)
  Spain                       1238  (12.38%)
  Argentina                   1220  (12.20%)
  England                      868  ( 8.68%)
[...]
```
