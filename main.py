import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import math
from pathlib import Path

import model


def _round_half_up(value):
    value = min(100.0, max(0.0, float(value)))
    rounded = math.floor(value * 10000.0 + 0.5) / 10000.0
    if rounded == math.floor(rounded):
        return int(rounded)
    return rounded


def _build_output(case):
    trophies = case.get("trophies", []) if isinstance(case, dict) else []
    predictions = model.forecast(case)
    rows = []
    for index, trophy in enumerate(trophies):
        trophy_id = trophy.get("id", index + 1) if isinstance(trophy, dict) else index + 1
        quantiles = predictions[index] if index < len(predictions) else [0.01] * 5
        rounded = []
        previous = 0.0
        for value in quantiles[:5]:
            number = float(value)
            if not math.isfinite(number):
                number = 0.01
            number = min(100.0, max(previous, min(100.0, max(0.0, number))))
            result = _round_half_up(number)
            rounded.append(result)
            previous = number
        while len(rounded) < 5:
            rounded.append(rounded[-1] if rounded else 0.01)
        rows.append({"id": trophy_id, "q": rounded})
    return {"trophies": rows}


def main():
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for case_path in sorted(input_dir.glob("*.in"), key=lambda path: path.name):
        case = {}
        try:
            with case_path.open("r", encoding="utf-8") as stream:
                case = json.load(stream)
            output = _build_output(case)
            case_id = str(case.get("id", case_path.stem)) if isinstance(case, dict) else case_path.stem
            if not case_id or case_id in (".", "..") or Path(case_id).name != case_id:
                case_id = case_path.stem
        except Exception:
            # Keep the process useful for neighboring files; the valid-input path
            # above remains deterministic and every readable case gets an output.
            trophies = case.get("trophies", []) if isinstance(case, dict) else []
            if not isinstance(trophies, list):
                trophies = []
            output = {"trophies": [
                {"id": trophy.get("id", index + 1) if isinstance(trophy, dict) else index + 1,
                 "q": [0.01, 0.01, 0.01, 0.01, 0.01]}
                for index, trophy in enumerate(trophies)
            ]}
            case_id = case_path.stem
        destination = output_dir / (case_id + ".out")
        with destination.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(output, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.write("\n")


if __name__ == "__main__":
    main()
