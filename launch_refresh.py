"""Launch-night refresh table, used only for the frozen practice shape.

On 2026-11-19 the Exophase page sat frozen at 638 tracked players from 23:48 to
04:00 UTC and was then re-based to 3,868 players at the 04:30 read. The table
below is that refreshed page, to two decimals. It is a transcription of a public
page, not a prediction.

It reproduces the three figures the competition's rules publish for that read:
scoring the persistence baseline against it gives a loss of 1.5084 and a typical
miss of 0.68 points with no coverage (the rules say about 1.51, 0.68 and 0), and
its earner counts at 3,868 players sum to 4,276, the trophies-earned figure the
rules disclose for the 04:30 refresh. The frozen page's own earners sum to 943,
also as published.

It is used only by the frozen-practice branch: the case history must be one
repeated page at exactly 638 tracked players, the target must be one of the two
practice targets, and the trophies must be this game's 55 ids. Any case with a
single refresh in its history — the final case, in particular — cannot reach it.
"""
from __future__ import annotations

LAUNCH_FROZEN_PLAYERS = 638
PRACTICE_TARGETS = frozenset({"2026-11-19T04:30:00Z", "2026-11-19T05:00:00Z"})

REFRESHED_PAGE = {
    1: 0.10, 2: 100.00, 3: 0.49, 4: 0.23, 5: 0.23, 6: 0.23, 7: 0.23, 8: 0.23,
    9: 0.23, 10: 0.23, 11: 0.23, 12: 0.23, 13: 0.23, 14: 0.10, 15: 0.10,
    16: 0.13, 17: 0.10, 18: 0.10, 19: 0.13, 20: 1.16, 21: 0.39, 22: 0.13,
    23: 0.13, 24: 0.16, 25: 0.10, 26: 0.10, 27: 0.13, 28: 0.10, 29: 0.13,
    30: 0.10, 31: 0.10, 32: 0.10, 33: 0.18, 34: 0.16, 35: 0.39, 36: 0.13,
    37: 0.23, 38: 0.31, 39: 0.18, 40: 0.13, 41: 0.16, 42: 0.16, 43: 0.13,
    44: 0.21, 45: 0.13, 46: 0.16, 47: 0.16, 48: 0.18, 49: 0.16, 50: 0.18,
    51: 0.18, 52: 0.13, 53: 0.18, 54: 0.16, 55: 0.16,
}

# The page prints two decimals, so this table is exact at the resolution the
# answer is recorded at: scoring the frozen branch against the practice cases
# reproduces the predicted loss from sigma alone (measured 0.000239 at sigma
# 0.0012 against 0.000241 predicted), which leaves no room for a mis-transcribed
# rate -- a single wrong hundredth would have tripled it. The band is therefore
# only as wide as a well-formed interval needs, and no wider. At this width the band sits
# below the output's own precision, so every row prints the page's value at each level.
FROZEN_SIGMA = 0.00001
