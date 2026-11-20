"""Deterministic, standard-library-only GTA VI trophy rate forecaster."""

from datetime import datetime, timezone
import math


CONFIG = {
    "RECENT_P": 6,
    "RECENT_G": 6,
    "DAMP": 0.75,
    "CAP_GROWTH": 6.0,
    "MIN_RATE": 0.004,
    "PARENT_FLOOR_SHARE": 0.35,
    "GAMMA_SIGMA": 0.30,
    "P_SIGMA": 0.25,
    "STALE_WIDEN": 1.6,
    "FAMILY_SIGMA": {
        "always": 0.02,
        "early": 0.45,
        "mid": 0.40,
        "late": 0.55,
        "grind": 0.60,
    },
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


def _story_parent(index, trophies, current_rates):
    if current_rates[index] is None:
        return None
    try:
        trophy_id = int(trophies[index].get("id"))
    except (TypeError, ValueError, AttributeError):
        return None
    if trophy_id < 1 or trophy_id > 13:
        return None
    candidates = []
    for other_index, trophy in enumerate(trophies):
        try:
            other_id = int(trophy.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        rate = current_rates[other_index]
        if 1 <= other_id < trophy_id <= 13 and rate is not None and rate > current_rates[index]:
            candidates.append((other_id, other_index))
    if not candidates:
        return None
    return max(candidates)[1]


def _parent_flow(states, parent_index):
    observations = []
    for state in states:
        rate = state["rates"][parent_index]
        earned = _earners(rate, state["P"])
        if earned is not None:
            observations.append((state["t"], earned))
    if len(observations) < 2:
        return 0.0, observations[-1][1] if observations else 0
    elapsed = observations[-1][0] - observations[0][0]
    if elapsed <= 0.0:
        return 0.0, observations[-1][1]
    flow = max(0.0, (observations[-1][1] - observations[0][1]) / elapsed)
    return flow, observations[-1][1]


def _quantiles(rate_med, sigma, family):
    if family == "always":
        return [100.0] * 5
    rate_med = min(99.5, max(CONFIG["MIN_RATE"], rate_med))
    center = _logit_percent(rate_med)
    return [_sigmoid_percent(center + z * sigma) for z in CONFIG["Z"]]


def forecast(case):
    """Return one five-quantile percent-rate row for each trophy in ``case``."""
    trophies = case.get("trophies", []) if isinstance(case, dict) else []
    if not isinstance(trophies, list):
        trophies = []
    states = _build_states(case if isinstance(case, dict) else {})
    if not states:
        return [[0.01] * 5 for _trophy in trophies]

    last_state = states[-1]
    observations = [_trophy_observations(states, index) for index in range(len(trophies))]
    current_rates = [series[-1][1] if series else None for series in observations]
    families = [_family(rate) for rate in current_rates]
    p_now, p_target = _pool_forecast(states, case.get("at"), case.get("target"))
    pool_ratio = max(1.0, p_target / max(p_now, 1.0))

    try:
        horizon_hours = max(0.0, _finite_number(case.get("horizon_minutes"), 0.0) / 60.0)
    except AttributeError:
        horizon_hours = 0.0
    if horizon_hours <= 0.0:
        try:
            horizon_hours = max(0.0, (_parse_time(case["target"]) - _parse_time(case["at"])).total_seconds() / 3600.0)
        except (KeyError, TypeError, ValueError, OverflowError):
            horizon_hours = 0.0

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
    results = []

    for index, family in enumerate(families):
        series = observations[index]
        r_now = series[-1][1] if series else CONFIG["MIN_RATE"]
        e_now = float(series[-1][2]) if series else 0.0

        if family == "always":
            rate_med = 100.0
        elif stale_shape or single_state:
            rate_med = r_now
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
            rate_med = r_now * (pool_ratio ** (gamma - 1.0))

            if family in ("late", "grind"):
                parent_index = _story_parent(index, trophies, current_rates)
                if parent_index is not None:
                    parent_flow, parent_earners = _parent_flow(states, parent_index)
                    share = e_now / parent_earners if parent_earners > 0 else 0.0
                    floor_earners = e_now + CONFIG["PARENT_FLOOR_SHARE"] * share * parent_flow * horizon_hours
                    rate_med = max(rate_med, 100.0 * floor_earners / max(p_target, 1.0))

        rate_med = min(99.5, max(CONFIG["MIN_RATE"], rate_med)) if family != "always" else 100.0
        if stale_shape:
            sigma = CONFIG["FAMILY_SIGMA"][family] * CONFIG["STALE_WIDEN"]
        elif single_state:
            sigma = CONFIG["FAMILY_SIGMA"][family]
        else:
            sigma = math.sqrt(
                CONFIG["FAMILY_SIGMA"][family] ** 2
                + (CONFIG["GAMMA_SIGMA"] * math.log(pool_ratio)) ** 2
                + (CONFIG["P_SIGMA"] * math.log(pool_ratio)) ** 2
            )
        results.append(_quantiles(rate_med, sigma, family))

    return results
