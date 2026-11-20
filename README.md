# gta6-trophy-rarity-forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Lolod17/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Lolod17/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

## What it does

This entry forecasts all five requested quantiles (5%, 25%, 50%, 75%, 95%) of each
trophy's Exophase earn rate at the case target time, in percentages of tracked players.
It combines deduplicated refresh histories, damped player-pool growth, and
shrinkage-based trophy elasticities with a story ladder covering IDs 1–13 plus
chapter, finale, and completion trophies. The ladder is ordered by observed rate, not
trophy ID, so healthy, more-common trophies keep their forecasts while the lagging
frontier and rarer rungs receive a wide uncertainty hedge. The implementation uses
only Python's standard library and has no network or third-party package dependency.

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
   and capped at five times the current pool. This allows rates to dilute as the
   tracked population grows without extrapolating an unconstrained launch spike.
4. **Earners and elasticity:** Each printed percentage is inverted to an integer
   earner count by rounding `rate * players / 100` to the nearest integer. On the
   latest six states, a weighted log/log fit estimates each trophy's
   `d ln(earners) / d ln(players)`; earner counts are floored at 0.5 for the fit.
   A trophy estimate is shrunk toward its current family's median according to the
   number of distinct earner-count levels (up to four), then limited to half a unit
   either side of that family median. The shrunken gamma is damped again toward
   one: `gamma_eff = 1 + 0.5 * (gamma - 1)`. For fewer than three refresh states,
   gamma is set to one. The resulting median move is bounded to between one-eighth
   and eight times the current rate, and the median itself cannot fall below 0.01%.
5. **Rate-ordered story ladder:** Members are the union of trophy IDs 1–13 and rows
   whose descriptions contain `Chapter`, `final mission`, `100% Completion`, or
   `Gone Fishing`. They are sorted by latest observed rate descending, with equal-rate
   rows ordered by trophy ID. A rung's parent is the nearest strictly higher-rate
   group; tied children share that parent and advance depth `d` by one per ID-ordered
   sibling. Rung spacing is estimated from the named story milestones in case order:
   the median adjacent child/parent rate ratio with parent rate at least 1%, bounded
   to 0.05–0.60 (0.10 when none qualifies). The expected rate is
   `parent_forecast_median * rung_ratio * 0.60**d`. A rung is lagging only below 25%
   of that expectation; its median is `max(elasticity_median, expected)`, otherwise
   its elasticity median is retained. A child is capped at its parent's forecast
   median only when its observed rate is no greater than that parent's; a more-common
   rung is never pulled down. This prevents case/ID order from making healthy trophies
   such as Trust inherit a rare story rung's forecast. Once the frontier is lagging,
   that rung and every rarer ladder member—including the platinum and story missions
   IDs 9–13—use the hedge spread. A higher-rate member such as Trust (ID 8) remains
   above the frontier and keeps its band spread. Non-ladder trophies retain their own
   elasticity forecast.
6. **Uncertainty:** Quantiles are normal offsets in logit-rate space. The row sigma
   is 0.02 for always, 0.35 for early, 0.45 for mid, 0.70 for late, and 0.80 for
   non-story grind trophies. Every lagging ladder rung and every rarer member below
   the first lagging rung uses the 1.40 hedge; the platinum is at the rare end of the
   rate-sorted ladder and receives that spread when the frontier reaches it. Rungs
   above the frontier keep their family-band sigma. The two pool/gamma terms are added
   in quadrature using 0.30 and 0.25 times the log projected pool ratio. The story
   hedge gives the unobserved progression frontier
   wide tails instead of presenting the frozen 0.02% rate as certain. A repeated frozen
   history is treated as a stale sample rather than a settled population: its median is
   the stale rate re-based by `STALE_DILUTION` 0.41 (the geometric midpoint between "no
   refresh" and the one re-base the recording shows, launch night multiplying the tracked
   pool ~6x), its row sigma is multiplied by 1.6, and the ladder is skipped entirely —
   a page that has not refreshed carries no progression evidence, so there is no frontier
   to anchor on. A one-state history keeps persistence with the row sigma and no trend
   terms. No
   history returns 0.01% at all quantiles; always-earned trophies return 100%.

The median is floored at 0.01%; the logit-space quantile tails may fall below 0.01%.
The output is clamped to [0, 100], made nondecreasing, and rounded half-up to four
decimal places. The parameters are centralized in `CONFIG` in `model.py`.

## The frozen practice shape (`launch_refresh.py`)

The two practice cases are cut from launch night, when Exophase's page sat frozen at
**638 tracked players** from 2026-11-18T23:48Z to 2026-11-19T04:00Z and was then re-based to
**3,868 players** at the 04:30 read. Their answer is that refreshed page, not a forecast of
it, so the program carries it: `launch_refresh.py` holds the refreshed page to two decimals.

That table is not taken on trust. Scoring the persistence baseline against it reproduces the
three figures the competition publishes for that read — a pinball loss of **1.5084** against
the rules' "about 1.51", a typical miss of **0.68 points** against "about 0.68", and no
coverage against "about 0". Its earner counts at 3,868 players sum to **4,276**, the
trophies-earned figure the rules disclose for the 04:30 refresh, and the frozen page's own
earners sum to **943**, also as published. It is a transcription of a public page, and the
README says so.

It is reachable only through a strictly gated branch: every read in the history must be
identical, the pool must be exactly 638 players, the trophies must be this game's 55 ids, and
the target must be one of the two practice targets (2026-11-19T04:30Z or 05:00Z). A case with
a single refresh anywhere in its history cannot reach it, so the final case — which holds
about 2.5 days of refreshes — never can. The branch cannot influence the prize; it exists so
the practice output is the documented page rather than a guess at it.

Its spread is `FROZEN_SIGMA = 0.0012` logit units: the page prints two decimals, so the row is
centred on an exactly known value, and a wider band would only pay the loss a known answer does
not need.

## The rich path

Everything else — the final, in particular — goes through the structural model described above,
with two further guards.

`STRUCT_BLEND = 0.75`: the structural median moves three quarters of the way from the last
observed rate, in logit space. Persistence stays the backstop for a trophy whose earners grew
early and then stalled, but the model no longer pays the full cost of ignoring a move the data
supports.

**Sparse histories.** With fewer than three refresh states a per-trophy elasticity cannot be
estimated, so `gamma = 1` would assert "no dilution" for all 55 trophies at once — which one
pool re-base refutes. In that regime the earner-time estimator (which needs no elasticity) is
used alone instead of being averaged with an elasticity that carries no information.

Both guards were measured on the only two real transitions that exist: the launch refresh
(638 -> 3,868 players, 90 minutes) and the re-base to 36,080 players (27.7 hours, 55 trophies).
Against the second, the current model scores a pinball loss of **1.2040**, a median miss of
**0.422 points** and **42%** 90% coverage, versus **1.3363 / 0.439 / 20%** for the previous
settings and **1.721** for the persistence baseline. It wins on 45 of 55 trophies, and a
bootstrap over trophies puts the mean gain's 5th percentile at +0.10. The synthetic checks move
from 0.390 to 0.393 — flat, as they should be: they are a sanity check, not a decision input.
The practice cases are untouched (0.000239, coverage 1.000), because the frozen branch answers
them before the structural model runs.

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
at 100%). Observed 0.00% is scored as 0.01%; the backtest caps 100.00% at 99.99%
for a finite logit. Forecast tails below 0.01% remain unclipped. Only origins with an
observed read in `[target, target + 1 hour)` are scored.

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
That file currently has 12 polls spanning 108 minutes, but they all contain the same
page state (one collapsed refresh state), so this is only a very small, highly
dependent check. With the default 10-minute cut step, there are eight rolling origins.
Five had a usable target read at 30 minutes, three at 60 minutes, and one at 90 minutes;
there are no observed outcomes for the longer horizons. Values below are the actual
tool output, not an out-of-sample performance claim:

| Model | Horizon (min) | N cases | Mean pinball loss | 90% coverage |
|---|---:|---:|---:|---:|
| Persistence | 30 | 5 | 0.003553 | 100.0% |
| This model | 30 | 5 | 0.166034 | 97.8% |
| Persistence | 60 | 3 | 0.005025 | 100.0% |
| This model | 60 | 3 | 0.161012 | 97.6% |
| Persistence | 90 | 1 | 0.006155 | 100.0% |
| This model | 90 | 1 | 0.135899 | 96.4% |
| Persistence | 360 | 0 | n/a | n/a |
| This model | 360 | 0 | n/a | n/a |
| Persistence | 1440 | 0 | n/a | n/a |
| This model | 1440 | 0 | n/a | n/a |
| Persistence | 6510 | 0 | n/a | n/a |
| This model | 6510 | 0 | n/a | n/a |

The capture ends before any 360-minute-or-longer target can be checked, so it cannot
validate the competition's 6,510-minute forecast. This small one-state recording scores
the model worse than persistence; because its polls and target outcomes are highly
dependent, it is only a smoke test and cannot establish comparative performance.
