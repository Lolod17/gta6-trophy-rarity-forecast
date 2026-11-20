"""Deterministic, standard-library-only GTA VI trophy rate forecaster."""

from datetime import datetime, timezone
import math


CONFIG = {
    "RECENT_P": 6,
    "RECENT_G": 6,
    "DAMP": 0.75,
    "CAP_GROWTH": 5.0,
    "MIN_RATE": 0.01,
    "MAX_FACTOR": 8.0,
    "GAMMA_DAMP": 0.5,
    "GAMMA_SIGMA": 0.30,
    "P_SIGMA": 0.25,
    "STALE_WIDEN": 1.6,
    "FAMILY_SIGMA": {
        "always": 0.02,
        "early": 0.35,
        "mid": 0.45,
        "late": 0.70,
        "grind": 0.80,
    },
    "LAGGING_STORY_SIGMA": 1.40,
    "STORY_RUNG_RATIO_MIN": 0.05,
    "STORY_RUNG_RATIO_MAX": 0.60,
    "STORY_DEEP_RATIO": 0.60,
    "Z": (-1.645, -0.674, 0.0, 0.674, 1.645),
}

LAUNCH = datetime(2026, 11, 19, tzinfo=timezone.utc)


def _parse_time(value):
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _hours_since_launch(value):
    try:
        elapsed = (_parse_time(value) - LAUNCH).total_seconds() / 3600.0
    except (TypeError, ValueError, OverflowError):
        elapsed = 1.0 / 60.0
    return max(elapsed, 1.0 / 60.0)


def _finite_number(value, default=0.0):
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError, OverflowError):
        pass
    return default


def _normalized_rates(read, count):
    rates = read.get("rates", []) if isinstance(read, dict) else []
    result = []
    for index in range(count):
        value = rates[index] if index < len(rates) else None
        if value is None:
            result.append(None)
        else:
            number = _finite_number(value, float("nan"))
            result.append(number if math.isfinite(number) else None)
    return result


def _build_states(case):
    trophies = case.get("trophies", [])
    history = case.get("history", [])
    states = []
    for read in history:
        if not isinstance(read, dict):
            continue
        rates = _normalized_rates(read, len(trophies))
        players = _finite_number(read.get("players_tracked"), 0.0)
        state = {
            "at": read.get("at"),
            "t": _hours_since_launch(read.get("at")),
            "P": max(0.0, players),
            "rates": rates,
        }
        # Polls of an unchanged public page are not independent observations.
        key = (state["P"], tuple(rates))
        if states and states[-1]["key"] == key:
            continue
        state["key"] = key
        states.append(state)
    return states


def _earners(rate, players):
    if rate is None or players <= 0:
        return None
    # Rates are printed to 0.01%; multiplying back recovers integer counts.
    return max(0, int(math.floor(rate * players / 100.0 + 0.5)))


def _weighted_slope(points):
    """Weighted least-squares slope for (x, y, recency weight) tuples."""
    if len(points) < 2:
        return 0.0
    total_weight = sum(point[2] for point in points)
    if total_weight <= 0.0:
        return 0.0
    mean_x = sum(x * weight for x, _y, weight in points) / total_weight
    mean_y = sum(y * weight for _x, y, weight in points) / total_weight
    variance = sum(weight * (x - mean_x) ** 2 for x, _y, weight in points)
    if variance <= 1e-15:
        return 0.0
    covariance = sum(weight * (x - mean_x) * (y - mean_y)
                     for x, y, weight in points)
    slope = covariance / variance
    return slope if math.isfinite(slope) else 0.0


def _recency_weights(length):
    return [1.25 ** index for index in range(length)]


def _family(rate):
    if rate is None:
        return "grind"
    if rate >= 99.0:
        return "always"
    if rate >= 2.0:
        return "early"
    if rate >= 0.3:
        return "mid"
    if rate >= 0.05:
        return "late"
    return "grind"


def _median(values, default=1.0):
    if not values:
        return default
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _sigmoid_percent(logit_value):
    # Stable logistic without overflowing for wide prediction intervals.
    if logit_value >= 0.0:
        exp_value = math.exp(-min(logit_value, 745.0))
        return 100.0 / (1.0 + exp_value)
    exp_value = math.exp(max(logit_value, -745.0))
    return 100.0 * exp_value / (1.0 + exp_value)


def _logit_percent(rate):
    p = min(0.995, max(CONFIG["MIN_RATE"] / 100.0, rate / 100.0))
    return math.log(p / (1.0 - p))


def _trophy_observations(states, index):
    result = []
    for state in states:
        rate = state["rates"][index]
        if rate is None:
            continue
        earned = _earners(rate, state["P"])
        if earned is not None:
            result.append((state, rate, earned))
    return result


def _pool_forecast(states, at, target):
    current = states[-1]
    p_now = max(current["P"], 1.0)
    selected = states[-max(1, int(CONFIG["RECENT_P"])):]
    points = []
    weights = _recency_weights(len(selected))
    for state, weight in zip(selected, weights):
        if state["P"] > 0.0 and state["t"] > 0.0:
            points.append((math.log(state["t"]), math.log(state["P"]), weight))
    slope = _weighted_slope(points)
    t_now = _hours_since_launch(at or current["at"])
    t_target = _hours_since_launch(target)
    time_ratio = max(1.0, t_target / max(t_now, 1.0 / 60.0))
    growth = time_ratio ** (max(0.0, slope) * CONFIG["DAMP"])
    growth = min(CONFIG["CAP_GROWTH"], max(1.0, growth))
    return p_now, p_now * growth


def _gamma_estimates(states, families):
    result = {}
    family_values = {name: [] for name in CONFIG["FAMILY_SIGMA"]}
    selected = states[-max(1, int(CONFIG["RECENT_G"])):]

    for index, family in enumerate(families):
        points = []
        earned_levels = set()
        weights = _recency_weights(len(selected))
        for state, weight in zip(selected, weights):
            rate = state["rates"][index]
            if rate is None or state["P"] <= 0.0:
                continue
            earned = _earners(rate, state["P"])
            if earned is None:
                continue
            earned_floor = max(0.5, float(earned))
            earned_levels.add(earned_floor)
            points.append((math.log(state["P"]), math.log(earned_floor), weight))
        gamma = _weighted_slope(points)
        usable = len(earned_levels) >= 2 and len({point[0] for point in points}) >= 2
        result[index] = (gamma, len(earned_levels), usable)
        if usable:
            family_values[family].append(gamma)

    medians = {name: _median(values, 1.0) for name, values in family_values.items()}
    return result, medians


def _trophy_id(trophy):
    try:
        return int(trophy.get("id"))
    except (TypeError, ValueError, AttributeError):
        return None


def _description_is_story_rung(trophy):
    description = trophy.get("description", "") if isinstance(trophy, dict) else ""
    description = str(description).lower()
    return ("chapter" in description or "final mission" in description
            or "100% completion" in description or "gone fishing" in description)


def _story_ladder(trophies):
    """Return the union of story IDs and described rungs in case order."""
    members = set()
    for index, trophy in enumerate(trophies):
        if _description_is_story_rung(trophy):
            members.add(index)
        trophy_id = _trophy_id(trophy)
        if trophy_id is not None and 1 <= trophy_id <= 13:
            members.add(index)
    return [index for index in range(len(trophies)) if index in members]


def _story_rung_ratio(trophies, current_rates):
    """Estimate rung spacing from named campaign milestones in case order."""
    story_indices = [index for index, trophy in enumerate(trophies)
                     if _description_is_story_rung(trophy)]
    ratios = []
    for position in range(1, len(story_indices)):
        parent_rate = current_rates[story_indices[position - 1]]
        child_rate = current_rates[story_indices[position]]
        if parent_rate is None or child_rate is None or parent_rate < 1.0:
            continue
        ratio = max(0.0, child_rate) / parent_rate
        ratios.append(ratio)
    if not ratios:
        return 0.10
    return min(CONFIG["STORY_RUNG_RATIO_MAX"],
               max(CONFIG["STORY_RUNG_RATIO_MIN"], _median(ratios)))


def _clamp_median(rate_med, r_now):
    reference_rate = max(CONFIG["MIN_RATE"], r_now)
    lower = reference_rate / CONFIG["MAX_FACTOR"]
    upper = reference_rate * CONFIG["MAX_FACTOR"]
    return min(upper, max(lower, rate_med))


def _quantiles(rate_med, sigma, family):
    if family == "always":
        return [100.0] * 5
    rate_med = min(99.5, max(CONFIG["MIN_RATE"], rate_med))
    center = _logit_percent(rate_med)
    return [_sigmoid_percent(center + z * sigma) for z in CONFIG["Z"]]


def forecast_with_diagnostics(case):
    """Return per-trophy forecast details, including median, sigma, and family."""
    trophies = case.get("trophies", []) if isinstance(case, dict) else []
    if not isinstance(trophies, list):
        trophies = []
    states = _build_states(case if isinstance(case, dict) else {})
    if not states:
        return [{"q": [0.01] * 5, "median": 0.01, "sigma": 0.0,
                 "family": "grind", "lagging_story": False}
                for _trophy in trophies]

    last_state = states[-1]
    observations = [_trophy_observations(states, index) for index in range(len(trophies))]
    current_rates = [series[-1][1] if series else None for series in observations]
    families = [_family(rate) for rate in current_rates]
    p_now, p_target = _pool_forecast(states, case.get("at"), case.get("target"))
    pool_ratio = max(1.0, p_target / max(p_now, 1.0))

    gammas, family_medians = _gamma_estimates(states, families)
    raw_history = case.get("history", [])
    unchanged_end_rates = len(raw_history) >= 2 and (
        _normalized_rates(raw_history[0], len(trophies))
        == _normalized_rates(raw_history[-1], len(trophies))
    )
    stale_shape = unchanged_end_rates or (
        len(states) >= 2 and states[0]["rates"] == last_state["rates"]
    )
    single_state = len(states) == 1
    sparse_gamma = len(states) < 3
    ladder_indices = _story_ladder(trophies)
    rung_ratio = _story_rung_ratio(trophies, current_rates)

    def ladder_rate(index):
        rate = current_rates[index]
        return rate if rate is not None else 0.0

    rate_order = sorted(
        ladder_indices,
        key=lambda index: (
            -ladder_rate(index),
            _trophy_id(trophies[index]) if _trophy_id(trophies[index]) is not None else index,
            index,
        ),
    )
    rate_groups = []
    for index in rate_order:
        rate = ladder_rate(index)
        if not rate_groups or rate_groups[-1][0] != rate:
            rate_groups.append((rate, [index]))
        else:
            rate_groups[-1][1].append(index)

    rate_metadata = {}
    ordered_ladder = []
    for group_position, (_rate, group) in enumerate(rate_groups):
        parent_index = rate_groups[group_position - 1][1][-1] if group_position else None
        for depth, index in enumerate(group):
            rate_metadata[index] = (parent_index, depth)
            ordered_ladder.append(index)

    details = [None] * len(trophies)
    hedge_active = False
    forecast_order = ordered_ladder + [index for index in range(len(trophies))
                                       if index not in ladder_indices]
    for index in forecast_order:
        family = families[index]
        series = observations[index]
        r_now = series[-1][1] if series else CONFIG["MIN_RATE"]
        if family == "always":
            elasticity_med = 100.0
        elif stale_shape or single_state:
            elasticity_med = r_now
        else:
            raw_gamma, distinct_levels, usable = gammas[index]
            family_gamma = family_medians[family]
            if sparse_gamma:
                gamma = 1.0
            else:
                shrink = min(1.0, distinct_levels / 4.0)
                gamma = family_gamma + shrink * (raw_gamma - family_gamma)
                gamma = min(family_gamma + 0.5, max(family_gamma - 0.5, gamma))
                if not usable and distinct_levels == 0:
                    gamma = family_gamma
            gamma_eff = 1.0 + (gamma - 1.0) * CONFIG["GAMMA_DAMP"]
            elasticity_med = r_now * (pool_ratio ** (gamma_eff - 1.0))

        rate_med = elasticity_med
        # A frozen pre-refresh page carries no progression evidence at all: the
        # ladder must not fire on it, or a stale case would forecast a whole
        # story ladder from a pool that has not even been re-based yet.
        is_story = index in ladder_indices and not (stale_shape or single_state)
        is_lagging = False
        is_hedged_story = False
        parent_index = None
        depth = None
        expected = None
        if is_story:
            parent_index, depth = rate_metadata[index]
            if parent_index is not None:
                parent_rate = ladder_rate(parent_index)
                expected = (details[parent_index]["median"] * rung_ratio
                            * (CONFIG["STORY_DEEP_RATIO"] ** depth))
                if ladder_rate(index) <= parent_rate:
                    is_lagging = ladder_rate(index) < 0.25 * expected
                    if is_lagging:
                        rate_med = max(rate_med, expected)
                        hedge_active = True
                    is_hedged_story = hedge_active
                    # Rate ordering means this child is no more common than
                    # the strictly-higher-rate parent.
                    rate_med = min(rate_med, details[parent_index]["median"])
                else:
                    # Defensive path: never drag a more-common rung below its
                    # elasticity forecast to fit a rarer parent.
                    rate_med = elasticity_med
            if family != "always":
                rate_med = max(CONFIG["MIN_RATE"], _clamp_median(rate_med, r_now))
        elif family != "always":
            rate_med = max(CONFIG["MIN_RATE"], _clamp_median(rate_med, r_now))

        rate_med = min(99.5, rate_med) if family != "always" else 100.0
        if (is_story and parent_index is not None
                and ladder_rate(index) <= ladder_rate(parent_index)):
            rate_med = min(rate_med, details[parent_index]["median"])
            rate_med = max(CONFIG["MIN_RATE"], rate_med)
        row_sigma = (CONFIG["LAGGING_STORY_SIGMA"] if is_hedged_story
                     else CONFIG["FAMILY_SIGMA"][family])
        if stale_shape:
            sigma = row_sigma * CONFIG["STALE_WIDEN"]
        elif single_state:
            sigma = row_sigma
        else:
            sigma = math.sqrt(
                row_sigma ** 2
                + (CONFIG["GAMMA_SIGMA"] * math.log(pool_ratio)) ** 2
                + (CONFIG["P_SIGMA"] * math.log(pool_ratio)) ** 2
            )
        row = _quantiles(rate_med, sigma, family)
        details[index] = {
            "q": row,
            "median": rate_med,
            "sigma": sigma,
            "family": family,
            "lagging_story": is_lagging,
            "hedged_story": is_hedged_story,
            "story": is_story,
            "rung_ratio": rung_ratio,
            "parent_index": parent_index,
            "parent_id": (_trophy_id(trophies[parent_index])
                          if parent_index is not None else None),
            "ladder_depth": depth,
            "expected_median": expected,
            "last_rate": ladder_rate(index) if is_story else r_now,
        }

    return details


def forecast(case):
    """Return one five-quantile percent-rate row for each trophy in ``case``."""
    return [detail["q"] for detail in forecast_with_diagnostics(case)]
