#!/usr/bin/env python3
"""score_generated.py — score generated boards against the shipped maps' measured composition.

The grammar's unit tests assert its bands directly. This is the stronger check: it takes boards the
generator produced and scores them with the same `score_board` the corpus model uses, so "the
generator matches the shipped maps" is a measurement rather than an intention.

Usage:
    npx ts-node --compiler-options '{"module":"commonjs"}' scripts/exportGeneratedBoards.ts /tmp/gb 12
    python3 tools/dow2/score_generated.py /tmp/gb

Exit code 0 when every board is inside the corpus band; 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dow2"))

from composition_model import clumping, score_board  # noqa: E402

TILE_M = 2.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boards", type=Path, help="directory of generated layout JSON files")
    ap.add_argument("--model", type=Path,
                    default=ROOT / "output" / "source_lab" / "composition_model.json")
    ap.add_argument("--max-deviation", type=float, default=2.0,
                    help="a board fails when its mean deviation from the corpus band exceeds this")
    a = ap.parse_args(argv)

    if not a.model.is_file():
        print(f"missing {a.model}; run tools/dow2/composition_model.py first")
        return 2
    model = json.loads(a.model.read_text())["parameters"]
    boards = sorted(a.boards.glob("*.json"))
    if not boards:
        print(f"no boards in {a.boards}")
        return 2

    failures = []
    scores = []
    dispersions = []
    for path in boards:
        layout = json.loads(path.read_text())
        size = layout.get("size") or {}
        width, height = int(size.get("width") or 0), int(size.get("height") or 0)
        if not width or not height:
            failures.append(f"{path.name}: no board size")
            continue
        area = width * height * TILE_M * TILE_M
        # the model's board band is the 48 m window; scale it to this board's area
        band = model.get("windows", {}).get("48") or {}
        if not band:
            failures.append("model has no 48 m window band")
            break
        # A layout is authored in cells; the model measures metres. Convert once, here, so every
        # metric (clumping cells, spacing, density) is in the same units as the corpus.
        props = [(float(p["x"]) * TILE_M, float(p["y"]) * TILE_M) for p in layout.get("props") or []]
        region = (0.0, 0.0, width * TILE_M, height * TILE_M)
        score = score_board(props, area, {**model, **band}, region=region)
        lump = clumping(
            __import__("numpy").array(props) if props else __import__("numpy").empty((0, 2)),
            region=region,
        )
        scores.append(score["score"])
        dispersions.append(lump["dispersion"])
        print(f"{path.name:22s} props {len(props):3d} density {len(props) * 100 / area:5.2f}/100m2 "
              f"dispersion {lump['dispersion']:5.2f} deviation {score['score']}")
        if score["score"] is None or score["score"] > a.max_deviation:
            failures.append(f"{path.name}: deviation {score['score']} > {a.max_deviation}")

    if scores:
        mean = sum(s for s in scores if s is not None) / max(1, len([s for s in scores if s is not None]))
        print(f"\n{len(scores)} boards, mean deviation {mean:.2f} (band: <= {a.max_deviation})")
    if dispersions:
        # the metric that actually separates an authored board from a scatter: the corpus sits at
        # 1.30 (p10 0.81, p90 2.14) and a uniform scatter measures 0.94
        ordered = sorted(dispersions)
        median = ordered[len(ordered) // 2]
        print(f"clumping: median dispersion {median:.2f} (corpus 1.30, uniform scatter 0.94)")
        if not (1.0 <= median <= 2.3):
            failures.append(f"median dispersion {median:.2f} outside 1.0-2.3")
    if failures:
        print("FAIL:")
        for f in failures[:10]:
            print(f"  - {f}")
        return 1
    print("GENERATED BOARDS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
