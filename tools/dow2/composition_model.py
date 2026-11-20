#!/usr/bin/env python3
"""composition_model.py — how the shipped maps are actually laid out, measured.

A map is not a scatter of props. It is lanes, cover pockets, landmark rings and a decal layer, and
the shipped maps agree on the shape of those things closely enough to be measured. This extracts the
numbers, so authoring rules can cite a measurement instead of a taste, and so a generated layout can
be *scored* against the reference rather than argued about.

Coordinate frame, measured from the corpus (do not assume it):

  * placements carry world metres in `pos` as (x, height, z);
  * the nav grid's cell is **1 m** and its dimensions are the playable extent
    (e.g. 256x288 for a 1v1 map, 448x448 for a large one), so a placement maps to a nav cell by
    `nav_x = x + width/2`, `nav_y = z + height/2`.

Usage:
    python3 tools/dow2/composition_model.py --maps output/source_lab/maps \
        --out output/source_lab/composition_model.json [--report]
"""
from __future__ import annotations

import argparse
import base64
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]

# Cover structure is measured on a fixed grid, not by single-linkage clustering. Measured reason:
# single linkage at 3-20 m reports a median cluster size of 1-2 on every shipped map, because props
# are *dispersed* across the playable area rather than gathered into pockets — nearest-neighbour
# median is 4.1 m at a density of 0.86 props/100 m2, i.e. slightly clumped uniform coverage, not
# clusters. The index of dispersion on a 10 m grid measures that clumping without inventing a radius.
CLUMP_CELL_M = 10.0
HOT_CELL_PROPS = 3
# Landmarks are the gameplay entities that define the space (victory and strategic points, turret
# positions). Blockers are shape, not landmarks.
LANDMARK_PATTERN = ("victory_point", "strategic_point", "relic_point", "turret_position", "capture")
BLOCKER_PATTERN = ("move_blockers", "move_shot_blockers", "blocker")
GAMEPLAY_PATTERN = ("starting_position",)


def nav_grid(nav: dict | None) -> np.ndarray | None:
    """The walkable grid as a boolean array (True = a unit can stand there)."""
    if not nav or "walkable_b64" not in nav:
        return None
    raw = np.frombuffer(base64.b64decode(nav["walkable_b64"]), dtype=np.uint8)
    w, h = int(nav.get("width") or 0), int(nav.get("height") or 0)
    if not w or not h or raw.size < w * h:
        return None
    return raw[:w * h].reshape(h, w) > 0


def classify(blueprint: str) -> str:
    low = blueprint.lower()
    if any(p in low for p in BLOCKER_PATTERN):
        return "blocker"
    if any(p in low for p in LANDMARK_PATTERN):
        return "landmark"
    if any(p in low for p in GAMEPLAY_PATTERN):
        return "spawn"
    return "prop"


def clumping(points: np.ndarray, cell_m: float = CLUMP_CELL_M,
             region: tuple[float, float, float, float] | None = None) -> dict:
    """How props distribute on the ground: dispersion index and hot-cell share.

    The index of dispersion (variance / mean of props per `cell_m` cell) is the standard measure of
    clumping, and it is only meaningful over the **whole** region including empty cells: counting
    occupied cells alone biases the index downward and makes a Poisson scatter look evenly spaced
    (measured: random scatters scored 0.40 against shipped windows at 0.55 before this was fixed).

    With the full region: 1.0 is a uniform random scatter, above 1 is clumping (props gathered into
    lanes and pockets), below 1 is even spacing. Hot cells carry `HOT_CELL_PROPS` or more.
    """
    if len(points) == 0:
        return {"dispersion": 0.0, "hot_cell_share": 0.0, "hot_cells": 0, "occupied_cells": 0}
    if region is None:
        pad = cell_m
        x0, z0 = float(points[:, 0].min()) - pad, float(points[:, 1].min()) - pad
        x1, z1 = float(points[:, 0].max()) + pad, float(points[:, 1].max()) + pad
    else:
        x0, z0, x1, z1 = region
    cells: Counter[tuple[int, int]] = Counter()
    for x, z in points:
        if not (x0 <= x <= x1 and z0 <= z <= z1):
            continue
        cells[(int((x - x0) // cell_m), int((z - z0) // cell_m))] += 1
    nx = max(1, int(math.ceil((x1 - x0) / cell_m)))
    nz = max(1, int(math.ceil((z1 - z0) / cell_m)))
    grid = np.zeros((nz, nx), dtype=float)
    for (cx, cz), count in cells.items():
        if 0 <= cz < nz and 0 <= cx < nx:
            grid[cz, cx] = count
    dispersion = float(grid.var() / grid.mean()) if grid.mean() > 0 else 0.0
    hot = [c for c in cells.values() if c >= HOT_CELL_PROPS]
    return {
        "dispersion": round(dispersion, 2),
        "hot_cells": len(hot),
        "occupied_cells": len(cells),
        "hot_cell_share": round(sum(hot) / max(1, len(points)), 3),
    }


def lane_stats(walkable: np.ndarray) -> dict:
    """Corridor widths, from the clearance field of the walkable grid.

    The distance transform gives every walkable cell its clearance to the nearest blocked cell. The
    local maxima of that field are the centres of corridors, and twice the clearance there is the
    corridor's width. That is the measured width a board's lanes should be built to.
    """
    clearance = ndimage.distance_transform_edt(walkable)
    if not clearance.any():
        return {}
    ridge = (clearance == ndimage.maximum_filter(clearance, size=7)) & (clearance > 1.5)
    widths = (clearance[ridge] * 2.0).astype(float)
    if widths.size == 0:
        return {}
    return {
        "corridor_width_m": {
            "p10": round(float(np.percentile(widths, 10)), 1),
            "median": round(float(np.median(widths)), 1),
            "p90": round(float(np.percentile(widths, 90)), 1),
        },
        "walkable_fraction": round(float(walkable.mean()), 3),
    }


def window_stats(points: np.ndarray, window_m: float, samples: int = 4) -> list[dict]:
    """Composition of board-sized windows of a map.

    A board is a *window* into a map at 1:1 scale, not the whole map squashed. Measuring whole maps
    answers the wrong question: a 256x256 m map's density says nothing about a 48x40 m board, and it
    is why the first import put 172 props on a board that should carry ~17.
    """
    if len(points) < 10:
        return []
    out = []
    half = window_m / 2
    # deterministic offsets, so the measurement does not depend on a random seed
    offsets = [(-1, -1), (1, -1), (-1, 1), (1, 1)][:max(1, samples)]
    cx0, cz0 = points.mean(axis=0)
    for ox, oz in offsets:
        cx, cz = cx0 + ox * window_m * 0.25, cz0 + oz * window_m * 0.25
        inside = points[(np.abs(points[:, 0] - cx) <= half) & (np.abs(points[:, 1] - cz) <= half)]
        if len(inside) < 5:
            continue
        area = window_m * window_m
        if len(inside) > 1:
            d = np.hypot(inside[:, None, 0] - inside[None, :, 0], inside[:, None, 1] - inside[None, :, 1])
            np.fill_diagonal(d, np.inf)
            nearest = float(np.median(d.min(axis=1)))
        else:
            nearest = 0.0
        lump = clumping(inside, region=(cx - half, cz - half, cx + half, cz + half))
        out.append({
            "window_m": window_m,
            "props": int(len(inside)),
            "props_per_100m2": round(len(inside) * 100.0 / area, 2),
            "nearest_prop_m": round(nearest, 2),
            "dispersion": lump["dispersion"],
            "hot_cell_share": lump["hot_cell_share"],
        })
    return out


def measure_map(data: dict) -> dict | None:
    nav = nav_grid(data.get("nav"))
    if nav is None:
        return None
    h, w = nav.shape
    ents = data.get("entities") or []
    kinds: dict[str, list[tuple[float, float]]] = {"prop": [], "landmark": [], "spawn": [], "blocker": []}
    for e in ents:
        pos = e.get("pos") or [0, 0, 0]
        kinds[classify(e.get("blueprint") or "")].append((float(pos[0]), float(pos[2])))

    props = np.array(kinds["prop"]) if kinds["prop"] else np.empty((0, 2))
    area_m2 = float(w * h)  # nav cells are 1 m
    if len(props) == 0:
        return None
    if len(props) > 1:
        d = np.hypot(props[:, None, 0] - props[None, :, 0], props[:, None, 1] - props[None, :, 1])
        np.fill_diagonal(d, np.inf)
        nearest = d.min(axis=1)
    else:
        nearest = np.array([0.0])

    landmarks = np.array(kinds["landmark"]) if kinds["landmark"] else np.empty((0, 2))
    landmark_spacing = None
    if len(landmarks) > 1:
        ld = np.hypot(landmarks[:, None, 0] - landmarks[None, :, 0], landmarks[:, None, 1] - landmarks[None, :, 1])
        np.fill_diagonal(ld, np.inf)
        landmark_spacing = {
            "min_m": round(float(ld.min()), 1),
            "median_m": round(float(np.median(ld.min(axis=1))), 1),
        }

    counts = data.get("counts") or {}
    return {
        "map": data.get("map"),
        "windows": window_stats(props, 80.0) + window_stats(props, 48.0),
        "playable_m": [w, h],
        "area_m2": area_m2,
        "props": int(len(props)),
        "blockers": len(kinds["blocker"]),
        "landmarks": len(kinds["landmark"]),
        "spawns": len(kinds["spawn"]),
        "splats": counts.get("splats", 0),
        "vista_objects": counts.get("vista_objects", 0),
        "props_per_100m2": round(len(props) * 100.0 / area_m2, 3),
        "splats_per_100m2": round(counts.get("splats", 0) * 100.0 / area_m2, 2),
        "nearest_prop_m": {
            "p10": round(float(np.percentile(nearest, 10)), 1),
            "median": round(float(np.median(nearest)), 1),
            "p90": round(float(np.percentile(nearest, 90)), 1),
        },
        "clumping": clumping(props),
        "landmark_spacing": landmark_spacing,
        "lanes": lane_stats(nav),
    }


def aggregate(per_map: list[dict]) -> dict:
    """Corpus-level parameters, with the spread that matters for authoring a board."""
    def col(path: str):
        vals = []
        for m in per_map:
            cur = m
            for part in path.split('.'):
                cur = (cur or {}).get(part) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if isinstance(cur, (int, float)):
                vals.append(float(cur))
        return np.array(vals)

    def dist(vals: np.ndarray) -> dict:
        if vals.size == 0:
            return {}
        return {"p10": round(float(np.percentile(vals, 10)), 2),
                "median": round(float(np.median(vals)), 2),
                "p90": round(float(np.percentile(vals, 90)), 2),
                "n": int(vals.size)}

    # Board-sized windows are the parameters an author actually builds to.
    windows = [w for m in per_map for w in (m.get("windows") or [])]
    by_size: dict[str, dict] = {}
    for size in sorted({w["window_m"] for w in windows}):
        rows = [w for w in windows if w["window_m"] == size]
        by_size[str(int(size))] = {
            "samples": len(rows),
            "props": dist(np.array([float(r["props"]) for r in rows])),
            "props_per_100m2": dist(np.array([float(r["props_per_100m2"]) for r in rows])),
            "nearest_prop_m": dist(np.array([float(r["nearest_prop_m"]) for r in rows])),
            "dispersion": dist(np.array([float(r["dispersion"]) for r in rows])),
            "hot_cell_share": dist(np.array([float(r["hot_cell_share"]) for r in rows])),
        }
    return {
        "maps": len(per_map),
        "windows": by_size,
        "props_per_100m2": dist(col("props_per_100m2")),
        "splats_per_100m2": dist(col("splats_per_100m2")),
        "nearest_prop_m": {k: dist(col(f"nearest_prop_m.{k}")) for k in ("p10", "median", "p90")},
        "dispersion": dist(col("clumping.dispersion")),
        "hot_cell_share": dist(col("clumping.hot_cell_share")),
        "corridor_width_median_m": dist(col("lanes.corridor_width_m.median")),
        "walkable_fraction": dist(col("lanes.walkable_fraction")),
        "landmarks_per_map": dist(np.array([float(m["landmarks"]) for m in per_map])),
        "spawns_per_map": dist(np.array([float(m["spawns"]) for m in per_map])),
        "vista_per_map": dist(np.array([float(m["vista_objects"]) for m in per_map])),
    }


def score_board(props: list[tuple[float, float]], area_m2: float, model: dict,
                region: tuple[float, float, float, float] | None = None) -> dict:
    """How close a prop set is to the corpus's composition, as the parameters it deviates on.

    A score is a list of z-like deviations in units of the corpus spread, so a caller can say *what*
    is wrong (too dense, too scattered, no pockets) rather than only that something is.
    """
    if not props:
        return {"deviations": {"density": None}, "score": float("inf")}
    pts = np.array(props)
    if len(pts) > 1:
        d = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
        np.fill_diagonal(d, np.inf)
        nearest = float(np.median(d.min(axis=1)))
    else:
        nearest = 0.0
    density = len(pts) * 100.0 / area_m2
    # The region has to be in the same coordinate space as the points. A layout is authored in cell
    # coordinates (0..width, 0..height) while a shipped map is in world metres centred on the origin,
    # so the caller passes its own region; without one the points' own bounding box is used, which
    # under-reports clumping because it excludes the empty ground the props were spread over.
    lump = clumping(pts, region=region)
    deviations = {
        "density": _dev(density, _band(model, "props_per_100m2")),
        "nearest_prop_m": _dev(nearest, _band(model, "nearest_prop_m")),
        "dispersion": _dev(lump["dispersion"], _band(model, "dispersion")),
        "hot_cell_share": _dev(lump["hot_cell_share"], _band(model, "hot_cell_share")),
    }
    known = [abs(v) for v in deviations.values() if v is not None]
    return {"deviations": deviations, "score": round(float(np.mean(known)), 2) if known else None}


def _band(model: dict, key: str) -> dict | None:
    """A model parameter as a {median, p90} band, whichever shape the model carries it in."""
    entry = model.get(key)
    if not isinstance(entry, dict):
        return None
    # the whole-map parameters nest a distribution per percentile; the window band is one flat
    # distribution. Normalising here keeps `score_board` usable against either.
    if isinstance(entry.get("median"), dict):
        return entry["median"]
    return entry


def _dev(value: float, band: dict | None) -> float | None:
    """Deviation in corpus-spread units, signed: 0 is the corpus median, 1 is the p90."""
    if not band or "median" not in band:
        return None
    med, p90 = band.get("median"), band.get("p90")
    if med is None or p90 is None:
        return None
    spread = max(abs(p90 - med), 1e-6)
    return round((value - med) / spread, 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=Path, default=ROOT / "output/source_lab/maps")
    ap.add_argument("--out", type=Path, default=ROOT / "output/source_lab/composition_model.json")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args(argv)

    per_map = []
    for f in sorted(a.maps.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        m = measure_map(data)
        if m:
            per_map.append(m)
    if not per_map:
        raise SystemExit("no measurable maps")
    model = {
        "generated_by": "asset-pipeline/tools/dow2/composition_model.py",
        "note": ("Measured composition of the shipped maps: density, cover-pocket structure, corridor "
                 "widths, landmark spacing and decal density. Rule-based authoring cites these numbers; "
                 "`score_board` measures a layout against them. Frame: nav cell = 1 m, playable extent "
                 "= nav dimensions, placement (x, height, z) in metres."),
        "parameters": aggregate(per_map),
        "per_map": per_map,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(model, indent=1))
    p = model["parameters"]
    print(f"{len(per_map)} maps measured -> {a.out}")
    print(f"  props/100m2     {p['props_per_100m2']}")
    print(f"  nearest prop    {p['nearest_prop_m']['median']}")
    print(f"  dispersion      {p['dispersion']}")
    print(f"  hot-cell share  {p['hot_cell_share']}")
    print(f"  corridor width  {p['corridor_width_median_m']}")
    print(f"  landmarks/map   {p['landmarks_per_map']}")
    print(f"  splats/100m2    {p['splats_per_100m2']}")
    if a.report:
        for m in sorted(per_map, key=lambda x: -x["props_per_100m2"])[:8]:
            print(f"    {m['map'][:30]:30s} props {m['props']:4d} /100m2 {m['props_per_100m2']:6.2f} "
                  f"disp {m['clumping']['dispersion']:5.2f} corridor {m['lanes'].get('corridor_width_m', {}).get('median')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
