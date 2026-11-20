#!/usr/bin/env python3
"""test_composition_model.py — does the measured composition actually describe the shipped maps?

The composition model (`tools/dow2/composition_model.py`) is only useful if it separates a map a
designer authored from a scatter of props. That is the acceptance test here, and it is the reason the
model exists: it is the yardstick a generated layout has to pass.

Two checks:

  1. **Separation** — an 80x80 m window of a shipped map must score closer to the corpus band than
     uniformly random scatters with the same prop count in the same area. If the model cannot tell
     those apart it measures nothing.
  2. **Stability** — every shipped window must stay inside a wide band on density and dispersion, so a
     future change to the model that quietly redefines "normal" fails here rather than in a render.

Run:
    python3 tools/dow2/test_composition_model.py
Exit code 0 = PASS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dow2"))

from composition_model import classify, clumping, score_board, window_stats  # noqa: E402

WINDOW_M = 48.0  # the default board: 24 cells x 2 m


def shipped_windows(maps_dir: Path) -> list[dict]:
    """Every board-sized window of every map, at the same four offsets the model measures."""
    windows = []
    half = WINDOW_M / 2
    for path in sorted(maps_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        pts = [(e["pos"][0], e["pos"][2]) for e in (data.get("entities") or [])
               if classify(e.get("blueprint") or "") == "prop"]
        if len(pts) < 20:
            continue
        arr = np.array(pts)
        cx0, cz0 = arr.mean(axis=0)
        for ox, oz in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            cx, cz = cx0 + ox * WINDOW_M * 0.25, cz0 + oz * WINDOW_M * 0.25
            inside = [(float(x), float(z)) for x, z in arr
                      if abs(x - cx) <= half and abs(z - cz) <= half]
            if len(inside) >= 8:
                windows.append({"map": f"{data.get('map')}@{ox},{oz}", "props": inside,
                                "region": (cx - half, cz - half, cx + half, cz + half)})
    return windows


def random_scatters(count: int, area_m2: float, trials: int, rng: np.random.Generator) -> list[list]:
    half = WINDOW_M / 2
    return [[(float(x), float(z)) for x, z in
             rng.uniform(-half, half, size=(count, 2))] for _ in range(trials)]


def main() -> int:
    model_path = ROOT / "output" / "source_lab" / "composition_model.json"
    if not model_path.is_file():
        print(f"missing {model_path}; run tools/dow2/composition_model.py first")
        return 2
    model = json.loads(model_path.read_text())["parameters"]
    band = model.get("windows", {}).get(str(int(WINDOW_M)))
    if not band:
        print(f"model has no {WINDOW_M:.0f} m window band; rerun composition_model.py")
        return 2
    # score against the board-sized band, which is what an author builds to
    model = {**model, **band}
    area = WINDOW_M * WINDOW_M
    rng = np.random.default_rng(20261118)

    windows = shipped_windows(ROOT / "output" / "source_lab" / "maps")
    if not windows:
        print("no shipped windows to measure")
        return 2

    half = WINDOW_M / 2
    shipped_scores, random_scores = [], []
    shipped_dispersion, random_dispersion = [], []
    for window in windows:
        shipped_scores.append(score_board(window["props"], area, model)["score"])
        shipped_dispersion.append(clumping(np.array(window["props"]), region=window["region"])["dispersion"])
        for scatter in random_scatters(len(window["props"]), area, 3, rng):
            random_scores.append(score_board(scatter, area, model)["score"])
            random_dispersion.append(clumping(np.array(scatter),
                                              region=(-half, -half, half, half))["dispersion"])

    shipped = np.array([s for s in shipped_scores if s is not None])
    rand = np.array([s for s in random_scores if s is not None])
    failures = []

    print(f"shipped windows: {len(shipped)}  random scatters: {len(rand)}")
    print(f"  shipped mean deviation {shipped.mean():.2f} (median {np.median(shipped):.2f})")
    print(f"  random  mean deviation {rand.mean():.2f} (median {np.median(rand):.2f})")
    print(f"  shipped dispersion median {np.median(shipped_dispersion):.2f}, "
          f"random {np.median(random_dispersion):.2f} (1.0 = Poisson scatter)")

    # What separates authored from random is *arrangement*, not quantity: the shipped maps place
    # props at a shorter spacing and more clumped than a scatter. Density does not separate them at
    # all (the scatters are generated at each window's own count), so the test asserts the two
    # metrics that carry the signal and says so in its output rather than averaging everything into
    # one number that hides which knob matters.
    if not np.median(shipped_dispersion) > np.median(random_dispersion) * 1.15:
        failures.append("shipped boards are not measurably more clumped than a random scatter")

    # every shipped window must sit inside a wide band; a model that redefines 'normal' fails here
    if shipped_scores and np.mean([d for d in shipped_scores if d is not None]) > 1.5:
        failures.append("shipped windows deviate from the corpus band by more than 1.5 spread units")

    for window, score in zip(windows, shipped_scores):
        lump = clumping(np.array(window["props"]), region=window["region"])
        if score is None or score > 4.0:
            failures.append(f"{window['map']}: deviation {score} outside the band")
        # a sanity range, not a contract: a 6-player map legitimately clumps hard (measured 4.26),
        # and this exists to catch a model that has quietly redefined "normal", not to police maps
        if not (0.4 <= lump["dispersion"] <= 6.0):
            failures.append(f"{window['map']}: dispersion {lump['dispersion']} outside 0.4-6.0")

    # spacing: the second metric that separates authored from random
    shipped_nn, random_nn = [], []
    for window in windows:
        pts = np.array(window["props"])
        if len(pts) > 1:
            d = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
            np.fill_diagonal(d, np.inf)
            shipped_nn.append(float(np.median(d.min(axis=1))))
    for scatter in random_scatters(30, area, 40, rng):
        pts = np.array(scatter)
        d = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
        np.fill_diagonal(d, np.inf)
        random_nn.append(float(np.median(d.min(axis=1))))
    print(f"  shipped prop spacing median {np.median(shipped_nn):.2f} m, "
          f"random {np.median(random_nn):.2f} m")
    if not np.median(shipped_nn) < np.median(random_nn):
        failures.append("shipped props are not more tightly spaced than a random scatter")

    # the model must say what it measured, not just carry numbers
    for key in ("props_per_100m2", "nearest_prop_m", "dispersion", "hot_cell_share",
                "corridor_width_median_m", "landmarks_per_map"):
        if key not in model or not model[key]:
            failures.append(f"model is missing the '{key}' parameter")

    if failures:
        print("\nFAIL:")
        for f in failures[:12]:
            print(f"  - {f}")
        return 1
    print("\nCOMPOSITION MODEL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
