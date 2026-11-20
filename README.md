# gta6-trophy-rarity-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Lolod17/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Lolod17/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

## What it does

This entry forecasts all five requested quantiles (5%, 25%, 50%, 75%, 95%) of each
trophy's Exophase earn rate at the case target time. Rates and output quantiles are
percentages of tracked players. The implementation uses Python's standard library
only and has no network or third-party package dependency.

## Forecast method

1. **Refresh states:** Consecutive page reads with the same tracked-player count and
   rate vector are collapsed to the first read in that run. This treats repeated
   polls of a cached page as one observation; changing states retain their original
   timestamps. The fits use recent states with recency weights that grow by 25% per
   state.
2. **Families:** The latest available rate assigns each trophy to `always` (at least
   99%), `early` (at least 2%), `mid` (at least 0.3%), `late` (at least 0.05%), or
   `grind` (below 0.05%). A trophy missing from every read is treated as grind.
3. **Player pool:** A weighted least-squares fit of `ln(players)` against elapsed
   `ln(hours since launch)` over the most recent six states estimates the pool's
   power-law growth. The nonnegative slope is damped by 0.75, projected to the target,
   and capped at six times the current pool. This allows rates to dilute as the
   tracked population grows without extrapolating an unconstrained launch spike.
4. **Earners and elasticity:** Each printed percentage is inverted to an integer
   earner count by rounding `rate * players / 100` to the nearest integer. On the
   latest six states, a weighted log/log fit estimates each trophy's
   `d ln(earners) / d ln(players)`; earner counts are floored at 0.5 for the fit.
   A trophy estimate is shrunk toward its current family's median according to the
   number of distinct earner-count levels (up to four), then limited to half a unit
   either side of that family median. For fewer than three refresh states, elasticity
   is unavailable and gamma is set to one (pure pool dilution).
5. **Median and story floor:** The median rate uses the observed rate multiplied by
   the projected pool ratio to the power `gamma - 1`. For late/grind story trophies
   among IDs 1–13, the nearest earlier, higher-rate story trophy supplies a
   progression floor: 35% of the observed earner share times that parent's measured
   earner flow is added across the horizon. The floor only raises the elasticity
   forecast; it never replaces a larger one.
6. **Uncertainty:** Quantiles are normal offsets in logit-rate space. Base family
   standard deviations are 0.02 / 0.45 / 0.40 / 0.55 / 0.60 for always / early /
   mid / late / grind. Two additional terms scale with the log projected pool ratio
   (0.30 for gamma uncertainty and 0.25 for pool uncertainty). A repeated frozen
   history whose first and last rate vectors match uses persistence for its median
   and widens the family's base spread by 1.6, allowing for a refresh landing during
   the forecast window. A single-read case uses persistence and the base family
   spread because it has no trend evidence.
   No-history cases return 0.01% at all five
   quantiles; always-earned trophies return 100% throughout.

The output is clamped to [0, 100], made nondecreasing, and rounded half-up to four
decimal places. The parameters are centralized in `CONFIG` in `model.py`.

## Run

The grader invokes the root entrypoint. Locally, input and output directories can be
overridden as follows:

```sh
MAKEFUN_INPUT_DIR=/path/to/input MAKEFUN_OUTPUT_DIR=/path/to/output python3 main.py
```

Every `*.in` file is processed in filename order and produces `<id>.out`. To exercise
empty history, a single read, duplicate slots/timestamps, null rates, zero/100% rates,
irregular refresh intervals and a 55-trophy case:

```sh
python3 tools/check_contract.py
```

The rolling-origin validator accepts JSONL page reads, reports mean pinball loss on
the logit scale and interval coverage, and compares the forecaster with persistence.
Its persistence benchmark holds the last observed rate and uses a logit-space
random-walk standard deviation of `0.25 * sqrt(horizon_days)` (always trophies remain
at 100%). Only origins with an observed read in `[target, target + 1 hour)` are scored.

```sh
python3 tools/backtest.py --reads /path/to/reads.jsonl
python3 tools/backtest.py --reads /path/to/reads.jsonl --step-minutes 20 --horizons 60,360
python3 tools/backtest.py --case case.in --answer actual-rates.json
```

For `--case`, the answer JSON supplies actual percentages in a `rates` array (or
`actual_rates`), or trophy rows with a `rate` / `actual` field.

## Backtest snapshot

Measured with the supplied live recording using
`python3 tools/backtest.py --reads /Users/mac/makefun-ops/gta6-forecast-data/reads.jsonl`.
That file currently has 10 polls spanning 88 minutes, but they all contain the same
page state (one collapsed refresh state); the 10 reads therefore provide only a very
small, highly dependent check. With the default 10-minute cut step, there are six
rolling origins. Four had a usable target read at 30 minutes and two at 60 minutes;
there are no observed outcomes for the longer horizons. Values below are the actual
tool output, not an out-of-sample performance claim:

| Model | Horizon (min) | N cases | Mean pinball loss | 90% coverage |
|---|---:|---:|---:|---:|
| Persistence | 30 | 4 | 0.269404 | 85.5% |
| This model | 30 | 4 | 0.290772 | 85.5% |
| Persistence | 60 | 2 | 0.269868 | 85.5% |
| This model | 60 | 2 | 0.288446 | 85.5% |
| Persistence | 90 | 0 | n/a | n/a |
| This model | 90 | 0 | n/a | n/a |
| Persistence | 360 | 0 | n/a | n/a |
| This model | 360 | 0 | n/a | n/a |
| Persistence | 1440 | 0 | n/a | n/a |
| This model | 1440 | 0 | n/a | n/a |
| Persistence | 6510 | 0 | n/a | n/a |
| This model | 6510 | 0 | n/a | n/a |

The capture ends before any 90-minute-or-longer target can be checked, so it cannot
validate the competition's 6,510-minute forecast. The close persistence comparison is
expected for a recording with no observed refresh transition.
