#!/usr/bin/env python3
"""assemble_parcels.py — XCOM's plot solver over parcels cut from the shipped maps.

The catalogue from `cut_parcels.py` is real geography: each entry is a piece of an authored DoW2
location, carrying its props, its ground and its measured edge openings. This assembles boards from
it the way XCOM assembles a plot from its parcel definitions:

  * an objective parcel is chosen first (XCOM: `ChooseObjectiveParcel`);
  * the remaining lattice slots are filled by an exhaustive backtracking search
    (XCOM: `ChooseNonObjectiveParcels`) that only accepts a parcel whose **entrance matches the
    neighbour's entrance** at the same offset and length;
  * a parcel is never used twice on one board (XCOM: "don't dupe the parcel map");
  * a parcel must come from the same map as its neighbour, which keeps terrain, prop language and
    lighting continuous across the seam — the DoW2-specific constraint XCOM does not need because
    its parcels are authored to a common metric.

The point of the measurement is to prove the assembled board is *traversable*: a flood fill over the
joined walkability grids must reach every parcel slot. A board that solves its entrances but does not
connect is not a map.

Usage:
    python3 tools/dow2/assemble_parcels.py --parcels output/source_lab/parcels_12.json \
        --grid 4x3 --seeds 200 --report
"""
from __future__ import annotations

import argparse
import base64
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]

# A seam is legal when the two openings overlap on at least this many nav cells. Exact offset equality
# is too strict for a 1 m grid: an authored street that continues across a tile boundary can be off by
# a cell. Overlap is the property that matters -- a unit walks through the join.
MIN_SEAM_OVERLAP_CELLS = 2
# Height continuity across a seam, in metres. DoW2 maps have plateaus and ramps, so a small step is
# normal; a large one is a cliff that no unit can cross.
MAX_SEAM_HEIGHT_STEP_M = 1.2

OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}


def overlaps(a: dict, b: dict) -> int:
    """Cells of overlap between two openings described by offset and length."""
    lo = max(a["offset"], b["offset"])
    hi = min(a["offset"] + a["length"], b["offset"] + b["length"])
    return max(0, hi - lo)


def seam_ok(a: dict, b: dict) -> bool:
    return any(overlaps(oa, ob) >= MIN_SEAM_OVERLAP_CELLS
               for oa in a.get("openings", {}).get(OPPOSITE.get(b["side"], ""), [])
               for ob in b.get("openings", {}).get(b["side"], []))


def matching_openings(parcel: dict, side: str, other: dict, other_side: str) -> bool:
    return any(overlaps(oa, ob) >= MIN_SEAM_OVERLAP_CELLS
               for oa in parcel.get("openings", {}).get(side, [])
               for ob in other.get("openings", {}).get(other_side, []))


class Corpus:
    """Source maps, kept so a board's walkability can be joined and flood-filled."""

    def __init__(self, maps_dir: Path):
        self.dir = maps_dir
        self._nav: dict[str, np.ndarray] = {}

    def nav(self, name: str) -> np.ndarray | None:
        if name not in self._nav:
            p = self.dir / f"{name}.json"
            if not p.exists():
                self._nav[name] = None  # type: ignore[assignment]
            else:
                d = json.loads(p.read_text())
                nav = d.get("nav") or {}
                raw = np.frombuffer(base64.b64decode(nav["walkable_b64"]), dtype=np.uint8)
                w, h = int(nav["width"]), int(nav["height"])
                self._nav[name] = raw[:w * h].reshape(h, w) > 0
        return self._nav[name]

    def tile(self, parcel: dict) -> np.ndarray | None:
        g = self.nav(parcel["map"])
        if g is None:
            return None
        x, y = parcel["origin"]
        s = parcel["size_m"]
        return g[y:y + s, x:x + s]


def solve(catalogue: list[dict], cols: int, rows: int, rng: random.Random,
          corpus: Corpus) -> list[dict] | None:
    """Backtracking fill of a cols x rows lattice, entrance-matched. Returns the parcel list."""
    slots = [(c, r) for r in range(rows) for c in range(cols)]
    by_map: dict[str, list[dict]] = {}
    for p in catalogue:
        if p["entrance_edges"]:
            by_map.setdefault(p["map"], []).append(p)
    maps = [m for m, ps in by_map.items() if len(ps) >= cols * rows]
    if not maps:
        return None
    rng.shuffle(maps)

    for mapname in maps[:6]:
        pool = by_map[mapname]
        rng.shuffle(pool)
        # Objective parcel first: the one with the most openings, as XCOM places the objective parcel
        # before filling the rest of the plot.
        pool.sort(key=lambda p: -p["opening_count"])
        objective = pool[0]
        placed: dict[tuple[int, int], dict] = {}
        used: set[tuple[str, tuple[int, int]]] = set()

        def fits(cand: dict, c: int, r: int) -> bool:
            key = (cand["map"], tuple(cand["origin"]))
            if key in used:
                return False
            # Every already-placed neighbour must match this parcel's facing edge.
            for dc, dr, side, other_side in ((0, -1, "N", "S"), (0, 1, "S", "N"),
                                             (-1, 0, "W", "E"), (1, 0, "E", "W")):
                nb = placed.get((c + dc, r + dr))
                if nb is None:
                    continue
                if not matching_openings(cand, side, nb, other_side):
                    return False
                ha, hb = cand.get("height"), nb.get("height")
                if ha and hb and abs(ha["mean"] - hb["mean"]) > MAX_SEAM_HEIGHT_STEP_M:
                    return False
            return True

        def fill(i: int) -> bool:
            if i == len(slots):
                return True
            c, r = slots[i]
            if i == 0:
                candidates = [objective]
            else:
                candidates = pool
            for cand in candidates:
                if not fits(cand, c, r):
                    continue
                placed[(c, r)] = cand
                used.add((cand["map"], tuple(cand["origin"])))
                if fill(i + 1):
                    return True
                used.discard((cand["map"], tuple(cand["origin"])))
                del placed[(c, r)]
            return False

        if fill(0):
            return [placed[slot] for slot in slots]
    return None


def connected(board: list[dict], cols: int, corpus: Corpus) -> tuple[bool, float]:
    """Flood fill the joined walkability of an assembled board."""
    tiles = [corpus.tile(p) for p in board]
    if any(t is None for t in tiles):
        return False, 0.0
    s = tiles[0].shape[0]
    rows = len(tiles) // cols
    grid = np.zeros((rows * s, cols * s), dtype=bool)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        grid[r * s:(r + 1) * s, c * s:(c + 1) * s] = t
    walk = int(grid.sum())
    if walk == 0:
        return False, 0.0
    # Largest connected walkable component, 4-connected.
    labels = np.zeros(grid.shape, dtype=np.int32)
    best, cur = 0, 0
    for y in range(grid.shape[0]):
        for x in range(grid.shape[1]):
            if not grid[y, x] or labels[y, x]:
                continue
            cur += 1
            stack, size = [(y, x)], 0
            labels[y, x] = cur
            while stack:
                cy, cx = stack.pop()
                size += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < grid.shape[0] and 0 <= nx < grid.shape[1] \
                            and grid[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = cur
                        stack.append((ny, nx))
            best = max(best, size)
    return best >= 0.9 * walk, best / float(walk)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parcels", default=str(ROOT / "output/source_lab/parcels_12.json"))
    ap.add_argument("--maps", default=str(ROOT / "output/source_lab/maps"))
    ap.add_argument("--grid", default="4x3")
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    cols, rows = (int(v) for v in args.grid.lower().split("x"))
    data = json.loads(Path(args.parcels).read_text())
    catalogue = data["catalogue"]
    corpus = Corpus(Path(args.maps))

    solved, connected_ok, shares, zones = 0, 0, [], Counter()
    for seed in range(args.seeds):
        board = solve(catalogue, cols, rows, random.Random(seed), corpus)
        if board is None:
            continue
        solved += 1
        ok, share = connected(board, cols, corpus)
        connected_ok += int(ok)
        shares.append(share)
        for p in board:
            zones[p["zone"]] += 1

    print(f"grid {cols}x{rows} ({cols * 12}x{rows * 12} m) | seeds {args.seeds} | solved {solved}")
    if solved:
        print(f"  traversable boards {connected_ok}/{solved} "
              f"({100.0 * connected_ok / solved:.0f}%)")
        shares.sort()
        print(f"  largest walkable component share: median {shares[len(shares) // 2]:.3f} "
              f"min {shares[0]:.3f}")
        print(f"  zones in boards: {dict(zones.most_common(6))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
