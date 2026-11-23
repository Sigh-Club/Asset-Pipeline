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


def matching_openings(parcel: dict, side: str, other: dict, other_side: str) -> bool:
    return any(overlaps(oa, ob) >= MIN_SEAM_OVERLAP_CELLS
               for oa in parcel.get("openings", {}).get(side, [])
               for ob in other.get("openings", {}).get(other_side, []))


class EdgeIndex:
    """Parcels indexed by the edge they open onto, so a seam is a lookup, not a scan.

    The first version of this file scanned the whole per-map pool for every candidate at every
    slot: 70 s per board. A slot's candidates are decided entirely by the openings it must meet, so
    indexing them by (map, side) and filtering on overlap turns each slot into a handful of
    candidates. Constraint-first ordering, not a faster loop.
    """

    def __init__(self, catalogue: list[dict]):
        self.by_edge: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
        for p in catalogue:
            for side, opens in (p.get("openings") or {}).items():
                for o in opens:
                    self.by_edge.setdefault((p["map"], side), []).append((p, o))

    def candidates(self, mapname: str, side: str, need: dict) -> list[dict]:
        out, seen = [], set()
        for p, o in self.by_edge.get((mapname, side), ()):
            key = tuple(p["origin"])
            if key in seen or overlaps(o, need) < MIN_SEAM_OVERLAP_CELLS:
                continue
            seen.add(key)
            out.append(p)
        return out


class Corpus:
    """Source maps, kept so a board's walkability can be joined and flood-filled."""

    def __init__(self, maps_dir: Path):
        self.dir = maps_dir
        self._nav: dict[str, np.ndarray] = {}
        self._props: dict[str, list[tuple[float, float, str]]] = {}
        self._prop_index: dict[tuple[str, int, int, int, int], list[tuple[float, float, str]]] = {}

    def props(self, parcel: dict) -> list[tuple[float, float, str]]:
        """The parcel's props as (nav x, nav y, name) in the source map's own frame.

        Read from the map's placements, so a board can be measured for what it will actually show: a
        parcel can be "dense" by count and still leave its middle bare, which is the defect a board
        with an empty centre has.
        """
        name = parcel["map"]
        if name not in self._props:
            path = self.dir / f"{name}.json"
            out: list[tuple[float, float, str]] = []
            if path.exists():
                d = json.loads(path.read_text())
                props = d.get("props") or []
                nw = float((d.get("nav") or {}).get("width") or 0)
                nh = float((d.get("nav") or {}).get("height") or 0)
                for q in d.get("placements") or []:
                    pos = q.get("pos")
                    if not pos or len(pos) < 3:
                        continue
                    k = q.get("kind")
                    if not isinstance(k, int) or not (0 <= k < len(props)):
                        continue
                    out.append((pos[0] + nw / 2, pos[2] + nh / 2, props[k]["prop"]))
            self._props[name] = out
        x0, y0 = parcel["origin"]
        w, h = parcel["size_xy"]
        key = (name, x0, y0, w, h)
        if key not in self._prop_index:
            self._prop_index[key] = [t for t in self._props[name]
                                     if x0 <= t[0] < x0 + w and y0 <= t[1] < y0 + h]
        return self._prop_index[key]

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
        w, h = parcel["size_xy"]
        return g[y:y + h, x:x + w]


def seam_legal(parcel: dict, side: str, neighbour: dict, other_side: str) -> bool:
    """A seam is legal only if the two parcels agree about it.

    An opening on our side must be met by an opening on the neighbour's facing side, and a solid
    edge must be met by a solid edge. One-sided matching -- our parcel opens, the neighbour does not
    -- passes the "entrance matched" test but produces an entrance that walks into a wall, and it was
    the reason the exhaustive search never terminated: it left every seam half-decided, so later
    slots had nothing to constrain them.
    """
    ours = parcel.get("openings", {}).get(side, [])
    theirs = neighbour.get("openings", {}).get(other_side, [])
    if not ours and not theirs:
        return True
    if not ours or not theirs:
        return False
    return any(overlaps(a, b) >= MIN_SEAM_OVERLAP_CELLS for a in ours for b in theirs)


def solve(catalogue: list[dict], cols: int, rows: int, rng: random.Random,
          corpus: Corpus, cap: int = 16, attempts: int = 8,
          require_entry: bool = False) -> list[dict] | None:
    """Fill a cols x rows lattice from one map, seams symmetric, with random restarts.

    Order is constraint-first (objective at the centre, slots outward) and every candidate set comes
    from an index keyed on the edge it must meet, so a slot costs a lookup rather than a scan. The
    search is greedy with restarts rather than exhaustive: an exhaustive walk over a 12-slot lattice
    of authored parcels spent minutes proving a partial solution dead, and the measurement we want is
    the *success rate* of the catalogue, which restarts estimate directly.
    """
    index = EdgeIndex(catalogue)
    by_map: dict[str, list[dict]] = {}
    for p in catalogue:
        # Only pieces a unit can walk through: openings on >=2 edges that share one walkable
        # component. Measured need -- without it assembled boards were traversable 40% of the time.
        if p["entrance_edges"] and p.get("openings_connected"):
            by_map.setdefault(p["map"], []).append(p)
    maps = [m for m, ps in by_map.items() if len(ps) >= cols * rows]
    if not maps:
        return None
    rng.shuffle(maps)

    centre = (cols // 2, rows // 2)
    slots = sorted(((c, r) for r in range(rows) for c in range(cols)),
                   key=lambda s: (abs(s[0] - centre[0]) + abs(s[1] - centre[1]), s[1], s[0]))
    sides = ((0, -1, "N", "S"), (0, 1, "S", "N"), (-1, 0, "W", "E"), (1, 0, "E", "W"))

    for mapname in maps[:8]:
        pool = by_map[mapname]
        objective = [p for p in pool if len(p["entrance_edges"]) >= 3] or \
                    [p for p in pool if len(p["entrance_edges"]) >= 2]
        if not objective:
            continue
        rng.shuffle(objective)
        # Parcels that are solid on a given side, precomputed: the per-node pool scan was the reason
        # a run of 60 boards took minutes.
        solid = {side: {tuple(q["origin"]): q for q in pool
                        if not q.get("openings", {}).get(side)} for _, _, side, _ in sides}

        for _ in range(attempts):
            placed: dict[tuple[int, int], dict] = {}
            used: set[tuple[int, int]] = set()
            budget = [3000]

            def cands_for(i: int, c: int, r: int) -> list[dict]:
                if i == 0:
                    return objective[:cap]
                base = None
                for dc, dr, side, other_side in sides:
                    nb = placed.get((c + dc, r + dr))
                    if nb is None:
                        continue
                    got: dict[tuple[int, int], dict] = {}
                    for o in nb.get("openings", {}).get(other_side, []):
                        for q in index.candidates(mapname, side, o):
                            got[tuple(q["origin"])] = q
                    if not got:
                        # The neighbour is solid on this seam: only parcels solid on our side fit.
                        got = solid[side]
                    base = got if base is None else {k: v for k, v in base.items() if k in got}
                    if not base:
                        return []
                out = [v for k, v in base.items() if k not in used]
                out = [q for q in out if all(seam_legal(q, side, placed[(c + dc, r + dr)], other_side)
                                             for dc, dr, side, other_side in sides
                                             if (c + dc, r + dr) in placed)]
                # A parcel must be entered from the board, not only from off-board: a corner parcel
                # whose only openings faced the outer edge matched every seam and was still an island.
                if require_entry:
                    out = [q for q in out
                           if any(overlaps(a, o) >= MIN_SEAM_OVERLAP_CELLS
                                  for dc, dr, side, other_side in sides
                                  if (c + dc, r + dr) in placed
                                  for a in q.get("openings", {}).get(side, [])
                                  for o in placed[(c + dc, r + dr)].get("openings", {}).get(other_side, []))]
                rng.shuffle(out)
                return out[:cap]

            def fill(i: int) -> bool:
                if i == len(slots):
                    return True
                if budget[0] <= 0:
                    return False
                c, r = slots[i]
                for cand in cands_for(i, c, r):
                    budget[0] -= 1
                    key = tuple(cand["origin"])
                    placed[(c, r)] = cand
                    used.add(key)
                    if fill(i + 1):
                        return True
                    used.discard(key)
                    del placed[(c, r)]
                    if budget[0] <= 0:
                        return False
                return False

            if fill(0):
                # Row-major, because the consumer joins tiles by (row, column) index. Returning the
                # fill order instead silently mis-assembled every board's walkability.
                return [placed[(c, r)] for r in range(rows) for c in range(cols)]
    return None


def centre_hollow_m2(board: list[dict], cols: int, corpus: Corpus, cell_m: int = 1) -> float:
    """The largest square of board, in the middle half, with no prop within reach of it.

    A board can pass a density test and still be hollow where the fight happens: the parcels at the
    edges are dense and the middle one is a parade ground. Measured on the emitted boards, the middle
    of a 72 m board was bare for 12 m or more -- a lobby, not a firefight. Props count as reaching
    1.5 m, which is a piece you can take cover behind rather than a pebble.
    """
    slot = int(board[0]["size_xy"][0])
    bw, bh = cols * slot, len(board) // cols * slot
    grid = np.zeros((bh // cell_m, bw // cell_m), dtype=bool)
    names: list[str] = []
    for i, parcel in enumerate(board):
        r, c = divmod(i, cols)
        ox, oy = c * slot, r * slot
        x0, y0 = parcel["origin"]
        for px, py, name in corpus.props(parcel):
            gx = int(ox + (px - x0))
            gy = int(oy + (py - y0))
            if not (0 <= gx < bw and 0 <= gy < bh):
                continue
            grid[max(0, gy - 1):gy + 2, max(0, gx - 1):gx + 2] = True
            names.append(name)
    # the middle half of the board, where a fight is decided
    lo_x, hi_x = int(bw * 0.25), int(bw * 0.75)
    lo_y, hi_y = int(bh * 0.25), int(bh * 0.75)
    region = grid[lo_y:hi_y, lo_x:hi_x]
    if region.size == 0:
        return 0.0
    # largest all-empty square, by the standard dynamic program
    best = 0
    dp = np.zeros(region.shape, dtype=np.int32)
    for y in range(region.shape[0]):
        for x in range(region.shape[1]):
            if region[y, x]:
                continue
            dp[y, x] = 1 + min(dp[y - 1, x] if y else 0,
                               dp[y, x - 1] if x else 0,
                               dp[y - 1, x - 1] if x and y else 0)
            best = max(best, int(dp[y, x]))
    return float(best * best * cell_m * cell_m)


def name_dominance(board: list[dict], cols: int, corpus: Corpus) -> float:
    """The share of a board's props that one kit name supplies.

    A parcel is cut from one place, and a fortress is built from one wall family: placed as they come,
    a board shows the same module eight times and the eye reads tiling rather than architecture.
    """
    counts: Counter[str] = Counter()
    for parcel in board:
        for _x, _y, name in corpus.props(parcel):
            counts[name] += 1
    total = sum(counts.values())
    return (counts.most_common(1)[0][1] / total) if total else 0.0


def connected(board: list[dict], cols: int, corpus: Corpus) -> tuple[int, float]:
    """Join the board's walkability and report reachability.

    A global "largest component >= 90% of walkable cells" test was the wrong gate: a shipped map
    legitimately has pockets (behind a barricade, a terrace) that no unit reaches, so a faithful
    assembly scores below 90% while being perfectly playable. The property that matters is that every
    parcel is reachable from the same space, so this reports how many parcel slots have a walkable
    cell inside the largest component, alongside that component's share.
    """
    tiles = [corpus.tile(p) for p in board]
    if any(t is None for t in tiles):
        return 0, 0.0
    s = tiles[0].shape[0]
    rows = len(tiles) // cols
    grid = np.zeros((rows * s, cols * s), dtype=bool)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        grid[r * s:(r + 1) * s, c * s:(c + 1) * s] = t
    walk = int(grid.sum())
    if walk == 0:
        return 0, 0.0
    labels = np.zeros(grid.shape, dtype=np.int32)
    best_label, best_size, cur = 0, 0, 0
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
            if size > best_size:
                best_label, best_size = cur, size
    reachable = 0
    for i in range(len(tiles)):
        r, c = divmod(i, cols)
        block = labels[r * s:(r + 1) * s, c * s:(c + 1) * s]
        if (block == best_label).any():
            reachable += 1
    return reachable, best_size / float(walk)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parcels", default=str(ROOT / "output/source_lab/parcels_12.json"))
    ap.add_argument("--maps", default=str(ROOT / "output/source_lab/maps"))
    ap.add_argument("--grid", default="4x3")
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--min-density", type=float, default=0.0,
                    help="drop parcels whose prop density is below this (props/100 m2); the reference's "
                         "tactical pieces are far denser than a random cut from a strategic map")
    ap.add_argument("--min-cover", type=int, default=0,
                    help="drop parcels with fewer than this many cover pieces")
    ap.add_argument("--max-hollow", type=float, default=0.0,
                    help="reject a board whose middle half holds a bare square this large, m2 "
                         "(0 reports only: the emitter dresses a bare middle with the map's own kit)")
    ap.add_argument("--max-dominance", type=float, default=0.45,
                    help="largest share one kit name may take of a board's props (0 disables)")
    ap.add_argument("--out", default=None,
                    help="write the solved boards (slot + parcel origin) for a renderer or the game")
    args = ap.parse_args()

    cols, rows = (int(v) for v in args.grid.lower().split("x"))
    data = json.loads(Path(args.parcels).read_text())
    catalogue = data["catalogue"]
    # A board is assembled from the catalogue's usable parcels only. `usable` is the cut's own
    # verdict (the parcel opens onto the board, has a walkable share and a coherent palette), and
    # solving over the rejected cuts put pieces with no entrance into the boards.
    before = len(catalogue)
    catalogue = [p for p in catalogue if p.get("usable")]
    # The lattice is square, so only pieces whose footprint is the slot's own footprint can be
    # stitched into it. Rectangles (48x24) are cut and catalogued, but they need a layout model that
    # allows mixed footprints, which the square solver does not have.
    sizes = Counter(tuple(p["size_xy"]) for p in catalogue if p.get("size_xy"))
    slot = sizes.most_common(1)[0][0] if sizes else (24, 24)
    catalogue = [p for p in catalogue if tuple(p.get("size_xy") or ()) == slot]
    print(f"lattice slot {slot[0]}x{slot[1]} m")
    if args.min_density or args.min_cover:
        catalogue = [p for p in catalogue
                     if float(p.get("prop_density_100m2") or 0) >= args.min_density
                     and int(p.get("cover_total") or 0) >= args.min_cover]
        print(f"catalogue {before} -> {len(catalogue)} usable, density>={args.min_density} "
              f"cover>={args.min_cover}")
    corpus = Corpus(Path(args.maps))

    # Verification, not a hard placement rule: requiring every parcel to open into the board during
    # the search cut the solve rate to 11 of 40, while a solved board is fully reachable 73% of the
    # time. So solve freely, verify, retry -- a bounded loop that measures the yield it gets.
    solved, fully_reachable, shares, zones = 0, 0, [], Counter()
    hollows: list[float] = []
    dominances: list[float] = []
    attempts_used = []
    boards_out = []
    for seed in range(args.seeds):
        for attempt in range(args.retries):
            board = solve(catalogue, cols, rows, random.Random(seed * 1000 + attempt), corpus)
            if board is None:
                continue
            reach, share = connected(board, cols, corpus)
            hollow = centre_hollow_m2(board, cols, corpus) if args.max_hollow else 0.0
            dominance = name_dominance(board, cols, corpus) if args.max_dominance else 0.0
            # A board is accepted when it is playable *and* it reads: reachable, not hollow in the
            # middle, and not one module repeated. Each is measured, so a rejected board is rejected
            # for a stated reason rather than by taste.
            good = (reach == len(board)
                    and (not args.max_hollow or hollow <= args.max_hollow)
                    and (not args.max_dominance or dominance <= args.max_dominance))
            if good or attempt == args.retries - 1:
                break
        if board is None:
            continue
        solved += 1
        attempts_used.append(attempt + 1)
        if args.out:
            boards_out.append({
                "seed": seed,
                "cols": cols,
                "rows": rows,
                "map": board[0]["map"],
                "parcels": [
                    {"slot": [i % cols, i // cols], "id": p["id"], "map": p["map"],
                     "origin": p["origin"], "size_xy": p["size_xy"],
                     "zone": p.get("zone"), "facing": p.get("facing"),
                     "cover": p.get("cover"), "interior": p.get("has_interior")}
                    for i, p in enumerate(board)
                ],
            })
        fully_reachable += int(reach == len(board))
        shares.append(share)
        hollows.append(hollow)
        dominances.append(dominance)
        for p in board:
            zones[p["zone"]] += 1

    if args.out and boards_out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"boards": boards_out}, indent=1))
        print(f"wrote {len(boards_out)} boards to {args.out}")
    cell_m = 12
    if catalogue:
        cell_m = int(catalogue[0].get("size_m") or 12)
    print(f"grid {cols}x{rows} ({cols * cell_m}x{rows * cell_m} m) | seeds {args.seeds} | solved {solved}")
    if solved:
        print(f"  boards where every parcel is reachable {fully_reachable}/{solved} "
              f"({100.0 * fully_reachable / solved:.0f}%)")
        shares.sort()
        hollows.sort()
        dominances.sort()
        print(f"  bare middle (largest empty square): median {hollows[len(hollows) // 2]:.0f} m2, "
              f"max {hollows[-1]:.0f} m2")
        print(f"  one module's share of a board: median {dominances[len(dominances) // 2]:.2f}, "
              f"max {dominances[-1]:.2f}")
        print(f"  largest walkable component share: median {shares[len(shares) // 2]:.3f} "
              f"min {shares[0]:.3f}")
        attempts_used.sort()
        print(f"  solve attempts per board: median {attempts_used[len(attempts_used) // 2]}")
        print(f"  zones in boards: {dict(zones.most_common(6))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
