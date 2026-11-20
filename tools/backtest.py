#!/usr/bin/env python3
"""Rolling-origin validator for the GTA VI trophy-rate forecaster."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import model


def parse_time(value):
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso_time(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clipped_logit(rate, observed=False):
    # Observed 0.00% scores as 0.01%; forecast tails below 0.01 remain valid.
    # 100.00 needs a finite upper endpoint for the logit transform.
    lower = 0.01 if observed else 1e-12
    bounded = min(99.99, max(lower, float(rate))) / 100.0
    return math.log(bounded / (1.0 - bounded))


def _sigmoid_percent(value):
    if value >= 0.0:
        exponential = math.exp(-min(value, 745.0))
        return 100.0 / (1.0 + exponential)
    exponential = math.exp(max(value, -745.0))
    return 100.0 * exponential / (1.0 + exponential)


def persistence_prediction(case, horizon_minutes):
    history = case.get("history", [])
    trophies = case.get("trophies", [])
    current = [None] * len(trophies)
    for read in history:
        rates = read.get("rates", [])
        for index in range(min(len(current), len(rates))):
            if rates[index] is not None:
                current[index] = float(rates[index])
    sigma = 0.25 * math.sqrt(max(0.0, horizon_minutes) / (60.0 * 24.0))
    result = []
    for index, trophy in enumerate(trophies):
        rate = current[index] if current[index] is not None else 0.01
        family = model._family(rate)
        if family == "always":
            result.append([100.0] * 5)
            continue
        center = _clipped_logit(min(99.5, max(model.CONFIG["MIN_RATE"], rate)))
        row = [_sigmoid_percent(center + z * sigma) for z in model.CONFIG["Z"]]
        result.append(row)
    return result


def _loss_and_coverage(prediction, truth):
    taus = (0.05, 0.25, 0.5, 0.75, 0.95)
    losses = []
    covered = 0
    count = 0
    for index, actual in enumerate(truth):
        if actual is None or index >= len(prediction):
            continue
        y = _clipped_logit(actual, observed=True)
        row = prediction[index]
        for tau, quantile in zip(taus, row):
            error = y - _clipped_logit(quantile)
            losses.append(tau * error if error >= 0.0 else (tau - 1.0) * error)
        covered += int(_clipped_logit(row[0]) <= y <= _clipped_logit(row[4]))
        count += 1
    return (sum(losses) / len(losses) if losses else None,
            covered / count if count else None)


def _synthetic_trophies(count):
    return [
        {"id": index + 1, "name": "Synthetic trophy %d" % (index + 1),
         "description": "", "tier": "bronze", "points": 15, "secret": False}
        for index in range(count)
    ]


def _case_for_cut(records, cut_index, horizon_minutes):
    cut_record = records[cut_index]
    cut_read_time = parse_time(cut_record.get("at", cut_record.get("slot")))
    cut_time = cut_read_time + timedelta(microseconds=1)
    history = []
    for record in records[:cut_index + 1]:
        read_time = parse_time(record.get("at", record.get("slot")))
        if read_time <= cut_read_time:
            history.append({
                "slot": record.get("slot", record.get("at")),
                "at": record.get("at", record.get("slot")),
                "players_tracked": record.get("players_tracked", 0),
                "trophies_earned": record.get("trophies_earned", 0),
                "rates": record.get("rates", []),
            })
    count = len(cut_record.get("rates", []))
    return {
        "schema": "makefun/gta6-trophies-case/v1",
        "id": "rolling-%d" % cut_index,
        "at": iso_time(cut_time),
        "horizon_minutes": horizon_minutes,
        "target": iso_time(cut_time + timedelta(minutes=horizon_minutes)),
        "levels": [0.05, 0.25, 0.5, 0.75, 0.95],
        "game": {"name": "Grand Theft Auto VI", "platform": "PS5"},
        "trophies": _synthetic_trophies(count),
        "history": history,
        "notes": "Rolling-origin backtest case",
    }


def _select_origins(records, step_minutes):
    if step_minutes <= 0:
        return list(range(len(records)))
    selected = []
    next_time = None
    step = timedelta(minutes=step_minutes)
    for index, record in enumerate(records):
        current = parse_time(record.get("at", record.get("slot")))
        if next_time is None or current >= next_time:
            selected.append(index)
            next_time = current + step
    return selected


def _score_reads(records, horizons, step_minutes):
    origins = _select_origins(records, step_minutes)
    output = []
    for horizon in horizons:
        model_scores = []
        persistence_scores = []
        for origin_index in origins:
            case = _case_for_cut(records, origin_index, horizon)
            target_time = parse_time(case["target"])
            actual_record = None
            for record in records:
                observed_at = parse_time(record.get("at", record.get("slot")))
                if target_time <= observed_at < target_time + timedelta(hours=1):
                    actual_record = record
                    break
            if actual_record is None:
                continue
            truth = actual_record.get("rates", [])
            model_pred = model.forecast(case)
            persistence_pred = persistence_prediction(case, horizon)
            model_score = _loss_and_coverage(model_pred, truth)
            persistence_score = _loss_and_coverage(persistence_pred, truth)
            if model_score[0] is not None:
                model_scores.append(model_score)
            if persistence_score[0] is not None:
                persistence_scores.append(persistence_score)
        output.append((horizon, persistence_scores, model_scores))
    return output


def _print_table(rows):
    print("model        horizon_min  n cases  mean pinball loss  90% coverage")
    print("------------ -----------  -------  -----------------  ------------")
    for horizon, persistence_scores, model_scores in rows:
        for name, scores in (("persistence", persistence_scores), ("this model", model_scores)):
            if not scores:
                loss = "n/a"
                coverage = "n/a"
            else:
                loss = "%.6f" % (sum(score[0] for score in scores) / len(scores))
                coverage = "%.1f%%" % (100.0 * sum(score[1] for score in scores) / len(scores))
            print("%-12s %11d  %7d  %17s  %12s" % (name, horizon, len(scores), loss, coverage))


def _truth_from_answer(answer, case):
    count = len(case.get("trophies", []))
    if isinstance(answer, list):
        if all(value is None or isinstance(value, (int, float)) for value in answer):
            return list(answer)
        rows = answer
    elif isinstance(answer, dict):
        for key in ("actual_rates", "rates", "truth", "observed_rates"):
            if isinstance(answer.get(key), list):
                return answer[key]
        rows = answer.get("trophies")
        if isinstance(rows, dict):
            by_id = rows
            return [by_id.get(str(trophy.get("id")), by_id.get(trophy.get("id")))
                    for trophy in case.get("trophies", [])]
        if rows is None and answer and all(isinstance(value, (int, float)) for value in answer.values()):
            return [answer.get(str(trophy.get("id")), answer.get(trophy.get("id")))
                    for trophy in case.get("trophies", [])]
    else:
        rows = None
    if isinstance(rows, list):
        truth = []
        for row in rows:
            if isinstance(row, dict):
                value = next((row[key] for key in ("actual", "rate", "observed") if key in row), None)
                truth.append(value)
            else:
                truth.append(None)
        return truth
    raise ValueError("answer must contain actual rates in 'rates' or trophy rows with 'rate'/'actual'")


def _score_single(case_path, answer_path):
    with case_path.open("r", encoding="utf-8") as stream:
        case = json.load(stream)
    with answer_path.open("r", encoding="utf-8") as stream:
        answer = json.load(stream)
    truth = _truth_from_answer(answer, case)
    horizon = float(case.get("horizon_minutes", 0.0))
    model_scores = [_loss_and_coverage(model.forecast(case), truth)]
    persistence_scores = [_loss_and_coverage(persistence_prediction(case, horizon), truth)]
    _print_table([(int(horizon), persistence_scores, model_scores)])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--reads", type=Path, help="JSONL page-read recording")
    group.add_argument("--case", type=Path, help="one case file (.in)")
    parser.add_argument("--answer", type=Path, help="actual-rate JSON for --case")
    parser.add_argument("--step-minutes", type=float, default=10.0,
                        help="minimum time between rolling origins (default: 10)")
    parser.add_argument("--horizons", default="30,60,90,360,1440,6510",
                        help="comma-separated forecast horizons in minutes")
    args = parser.parse_args(argv)

    if args.case is not None:
        if args.answer is None:
            parser.error("--case requires --answer with actual target rates")
        _score_single(args.case, args.answer)
        return
    if args.answer is not None:
        parser.error("--answer is only used with --case")

    records = []
    with args.reads.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict) or not isinstance(record.get("rates"), list):
                raise ValueError("line %d is not a page read with a rates list" % line_number)
            records.append(record)
    records.sort(key=lambda item: parse_time(item.get("at", item.get("slot"))))
    horizons = [int(float(value.strip())) for value in args.horizons.split(",") if value.strip()]
    if not horizons or any(value < 0 for value in horizons):
        parser.error("--horizons must contain one or more nonnegative minute values")
    _print_table(_score_reads(records, horizons, args.step_minutes))
    print("Reads: %d; rolling origins: %d; cut step: %g minutes" %
          (len(records), len(_select_origins(records, args.step_minutes)), args.step_minutes))


if __name__ == "__main__":
    main()
