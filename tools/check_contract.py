#!/usr/bin/env python3
"""Exercise main.py against deterministic synthetic contract edge cases."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "main.py"


def trophies(count):
    return [
        {"id": index + 1, "name": "Trophy %d" % (index + 1), "description": "",
         "tier": "bronze", "points": 15, "secret": False}
        for index in range(count)
    ]


def read(at, players, rates, slot=None):
    return {"slot": slot or at, "at": at, "players_tracked": players,
            "trophies_earned": 0, "rates": rates}


def make_case(case_id, at, target, rates, history, count=None, horizon=90):
    trophy_count = len(rates) if count is None else count
    return {
        "schema": "makefun/gta6-trophies-case/v1", "id": case_id,
        "at": at, "target": target, "horizon_minutes": horizon,
        "levels": [0.05, 0.25, 0.5, 0.75, 0.95],
        "game": {"name": "Synthetic", "platform": "PS5"},
        "trophies": trophies(trophy_count), "history": history, "notes": "synthetic",
    }


def synthetic_cases():
    stamp = "2026-11-19T01:00:00Z"
    rates = [0.0, 100.0, 2.5, 0.2]
    cases = [make_case("empty", stamp, "2026-11-19T02:30:00Z", rates, [])]
    cases.append(make_case("one", stamp, "2026-11-19T02:30:00Z", rates,
                           [read(stamp, 1000, rates)]))
    duplicate_rates = [0.0, 100.0, 2.5, 0.2]
    cases.append(make_case("duplicate", "2026-11-19T03:00:00Z", "2026-11-19T05:00:00Z",
                           duplicate_rates, [
                               read("2026-11-19T01:00:00Z", 1000, duplicate_rates, "same-slot"),
                               read("2026-11-19T01:00:00Z", 1000, duplicate_rates, "same-slot"),
                               read("2026-11-19T02:00:00Z", 1100, [0.1, 100.0, 2.7, 0.2], "same-slot"),
                           ]))
    cases.append(make_case("nulls", "2026-11-19T04:00:00Z", "2026-11-19T06:00:00Z",
                           [None, 99.99, None, 0.0], [
                               read("2026-11-19T01:00:00Z", 800, [None, 100.0, 0.0, None]),
                               read("2026-11-19T03:30:00Z", 1600, [None, 99.99, 0.0, 0.0]),
                           ]))
    cases.append(make_case("missing-trophy", "2026-11-19T05:00:00Z", "2026-11-19T07:00:00Z",
                           [5.0, 1.0, None, 0.02, None], [
                               read("2026-11-19T01:00:00Z", 1000, [8.0, 1.5, None, 0.02, None]),
                               read("2026-11-19T03:00:00Z", 2400, [5.0, 1.0, None, 0.02, None]),
                           ]))
    cases.append(make_case("zero-hundred", "2026-11-19T08:00:00Z", "2026-11-19T09:30:00Z",
                           [0.0, 100.0, 0.01], [
                               read("2026-11-19T01:00:00Z", 500, [0.0, 100.0, 0.0]),
                               read("2026-11-19T04:00:00Z", 2000, [0.0, 100.0, 0.0]),
                               read("2026-11-19T07:30:00Z", 6000, [0.0, 100.0, 0.01]),
                           ]))
    cases.append(make_case("irregular", "2026-11-20T00:00:00Z", "2026-11-20T12:00:00Z",
                           [4.0, 0.8, 0.04], [
                               read("2026-11-19T00:10:00Z", 500, [10.0, 1.0, 0.02]),
                               read("2026-11-19T06:00:00Z", 2000, [6.0, 0.9, 0.02]),
                               read("2026-11-19T19:20:00Z", 9000, [4.0, 0.8, 0.04]),
                           ]))
    many_rates = [100.0 if index == 1 else (2.5 if index == 2 else 0.0) for index in range(55)]
    cases.append(make_case("fifty-five", "2026-11-20T00:00:00Z", "2026-11-20T02:00:00Z",
                           many_rates, [read("2026-11-19T20:00:00Z", 10000, many_rates)], 55))
    return cases


def run_main(input_dir, output_dir):
    env = os.environ.copy()
    env["MAKEFUN_INPUT_DIR"] = str(input_dir)
    env["MAKEFUN_OUTPUT_DIR"] = str(output_dir)
    subprocess.run([sys.executable, str(MAIN)], check=True, cwd=str(ROOT), env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def validate_output(path, case):
    with path.open("r", encoding="utf-8") as stream:
        output = json.load(stream)
    assert list(output.keys()) == ["trophies"], "wrong top-level keys"
    rows = output["trophies"]
    assert len(rows) == len(case["trophies"]), "wrong trophy count"
    assert all(set(row.keys()) == {"id", "q"} for row in rows), "wrong row shape"
    for expected, row in zip(case["trophies"], rows):
        assert row["id"] == expected["id"], "trophy ordering/id changed"
        assert len(row["q"]) == 5, "wrong quantile count"
        assert all(isinstance(value, (int, float)) and math.isfinite(value)
                   and 0.0 <= value <= 100.0 for value in row["q"]), "invalid quantile"
        assert row["q"] == sorted(row["q"]), "quantiles are not monotone"


def main():
    cases = synthetic_cases()
    with tempfile.TemporaryDirectory(prefix="contract-check-", dir=str(ROOT)) as temporary:
        base = Path(temporary)
        input_dir = base / "input"
        input_dir.mkdir()
        for case in cases:
            with (input_dir / (case["id"] + ".in")).open("w", encoding="utf-8") as stream:
                json.dump(case, stream, separators=(",", ":"))
        first_dir = base / "first"
        second_dir = base / "second"
        run_main(input_dir, first_dir)
        run_main(input_dir, second_dir)
        first_files = sorted(path.name for path in first_dir.glob("*.out"))
        second_files = sorted(path.name for path in second_dir.glob("*.out"))
        assert first_files == second_files == sorted(case["id"] + ".out" for case in cases)
        for case in cases:
            first = first_dir / (case["id"] + ".out")
            second = second_dir / (case["id"] + ".out")
            validate_output(first, case)
            assert first.read_bytes() == second.read_bytes(), "output changed between runs"
    print("PASS: %d synthetic cases; valid, monotone, finite, deterministic output" % len(cases))


if __name__ == "__main__":
    main()
