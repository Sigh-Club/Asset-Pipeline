#!/usr/bin/env python3
"""cut_parcels.py — cut the shipped maps into XCOM-style parcels, measured not invented.

XCOM assembles a map from hand-authored *parcels*: fixed-size pieces named after real places, each
declaring directional entrances, selected by land-use zone and stitched by a solver that only accepts
a placement whose entrance matches its neighbour's. That is why an XCOM map reads as a real location
with a street network: the pieces are places and the streets are solved.

DoW2 ships the same thing at a different granularity. Every shipped map is a hand-authored place --
thousands of prop placements with orientation, a terrain heightfield, splat masks and a nav grid, all
decoded into `output/source_lab/maps/*.json`. Cut that geography into parcel-sized tiles and each
tile *is* an authored piece of a real location: it brings its own props, its own cover clusters, its
own ground and its own lighting context.

So the parcels are not authored again. They are cut from the corpus:

  * tile the nav grid at a parcel size,
  * measure each tile's **edge openings from the shipped walkability grid** -- a run of walkable
    boundary cells that is also walkable two cells deep, which is exactly XCOM's
    "entrance of length N facing S", measured rather than declared,
  * record the prop inventory, prop density, ground height range and edge heights, so a solver can
    require height continuity at a seam the way XCOM requires an entrance match.

Usage:
    python3 tools/dow2/cut_parcels.py --maps output/source_lab/maps \
        --out output/source_lab/parcels.json --tile 12 --report
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

# A boundary run only counts as an entrance if the passage continues into the tile: a one-cell sliver
# of walkable ground on the edge is a corner clip, not a street. Two cells of depth is the minimum
# that a unit can walk through at DoW2's 1 m nav resolution.
ENTRANCE_DEPTH_CELLS = 2
MIN_ENTRANCE_CELLS = 2
MAX_ENTRANCE_CELLS = 8

# Land use is read off the prop inventory rather than guessed from the map name, so a parcel's zone
# is a measurement of what the level designers put there. Patterns are matched against prop names.
ZONE_PATTERNS = (
    ("industrial", ("generator", "industrial", "pipe", "tank", "refinery", "crane", "container")),
    ("fortified", ("wall", "barricade", "sandbag", "bunker", "gate", "turret")),
    ("overgrown", ("vine", "tree", "bush", "fern", "flora", "grass", "root")),
    ("ruined", ("rubble", "ruin", "debris", "wreck", "broken", "crater")),
    ("natural", ("rock", "cliff", "boulder", "mussel", "dune")),
    ("civic", ("lamp", "banner", "statue", "shrine", "altar", "monument")),
)

EDGES = ("N", "S", "E", "W")


def nav_grid(nav: dict | None) -> np.ndarray | None:
    if not nav or "walkable_b64" not in nav:
        return None
    raw = np.frombuffer(base64.b64decode(nav["walkable_b64"]), dtype=np.uint8)
    w, h = int(nav.get("width") or 0), int(nav.get("height") or 0)
    if not w or not h or raw.size < w * h:
        return None
    return raw[:w * h].reshape(h, w) > 0


def runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous runs of True as (start, length)."""
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - start))
            start = None
    if start is not None:
        out.append((start, len(flags) - start))
    return out


def edge_openings(walk: np.ndarray, x0: int, y0: int, size: int) -> dict:
    """Openings on each edge of a tile, measured from the shipped walkability grid.

    An opening is a run of walkable boundary cells that is also walkable ENTRANCE_DEPTH_CELLS deep,
    so the passage actually connects into the parcel. Length is reported in nav cells (1 m).
    """
    tile = walk[y0:y0 + size, x0:x0 + size]
    if tile.shape != (size, size):
        return {}
    depth = min(ENTRANCE_DEPTH_CELLS, size)
    out: dict[str, list[dict]] = {}
    # North edge is the first row, south the last; west the first column, east the last. "Depth"
    # points inward from each edge, which is what decides whether the run is a passage.
    lines = {
        "N": (tile[0, :], tile[:depth, :].all(axis=0)),
        "S": (tile[-1, :], tile[-depth:, :].all(axis=0)),
        "W": (tile[:, 0], tile[:, :depth].all(axis=1)),
        "E": (tile[:, -1], tile[:, -depth:].all(axis=1)),
    }
    for edge, (boundary, inward) in lines.items():
        found = []
        for start, length in runs(boundary & inward):
            if MIN_ENTRANCE_CELLS <= length <= MAX_ENTRANCE_CELLS:
                found.append({"offset": int(start), "length": int(length)})
        out[edge] = found
    return out


def height_stats(terrain: dict | None, x0: int, y0: int, size: int, cell_m: float) -> dict | None:
    """Ground height range for a tile, in metres, from the decoded heightfield."""
    if not terrain or not terrain.get("heights"):
        return None
    w, h, stride = int(terrain["width"]), int(terrain["height"]), int(terrain["stride"])
    scale = float(terrain.get("tile_world_scale") or 0) or 1.0
    heights = np.asarray(terrain["heights"], dtype=np.float32)
    if heights.size < w * h:
        return None
    grid = heights[:w * h].reshape(h, w)
    # Terrain tiles are `tile_world_scale` metres each; convert the parcel rectangle into that frame.
    tw = max(1, int(round(size / max(scale, 1e-6))))
    tx, ty = int(round(x0 / max(scale, 1e-6))), int(round(y0 / max(scale, 1e-6)))
    patch = grid[ty:ty + tw, tx:tx + tw]
    if patch.size == 0:
        return None
    return {"min": round(float(patch.min()), 2), "max": round(float(patch.max()), 2),
            "mean": round(float(patch.mean()), 2)}


def opening_connectivity(tile: np.ndarray, openings: dict) -> tuple[bool, int]:
    """Are a tile's openings in one walkable component?

    A parcel whose openings sit in different components is a place with two halves that do not talk:
    it passes an entrance match on both sides and still cannot be walked through. Measured because
    assembled boards were failing traversability at 60% for exactly this reason.
    """
    labels, count = ndimage.label(tile)  # type: ignore[name-defined]
    comps = set()
    size = tile.shape[0]
    for edge, runs_ in openings.items():
        for o in runs_:
            for i in range(o["offset"], o["offset"] + o["length"]):
                y, x = {"N": (0, i), "S": (size - 1, i), "W": (i, 0), "E": (i, size - 1)}[edge]
                if labels[y, x]:
                    comps.add(int(labels[y, x]))
    return len(comps) == 1, len(comps)


def zone_of(props: Counter) -> str:
    names = " ".join(props).lower()
    scores = {zone: sum(n for p, n in props.items() if any(k in p.lower() for k in keys))
              for zone, keys in ZONE_PATTERNS}
    best = max(scores, key=lambda z: scores[z]) if scores else "open"
    return best if scores.get(best, 0) > 0 else "open"


def cut_map(path: Path, tile_m: int) -> dict:
    data = json.loads(path.read_text())
    walk = nav_grid(data.get("nav"))
    if walk is None:
        return {"map": data.get("map"), "parcels": [], "skipped": "no nav"}
    h, w = walk.shape
    palette = [p.get("prop") or "" for p in data.get("props") or []]
    placements = data.get("placements") or []
    # Placement world metres -> nav cell, per the measured corpus frame (1 m nav cells, centred).
    cells = []
    for pl in placements:
        pos = pl.get("pos") or []
        if len(pos) < 3:
            continue
        nx = int(round(pos[0] + w / 2))
        ny = int(round(pos[2] + h / 2))
        if 0 <= nx < w and 0 <= ny < h:
            kind = pl.get("kind")
            name = palette[kind] if isinstance(kind, int) and 0 <= kind < len(palette) else ""
            cells.append((nx, ny, name))

    parcels = []
    for y0 in range(0, h - tile_m + 1, tile_m):
        for x0 in range(0, w - tile_m + 1, tile_m):
            tile = walk[y0:y0 + tile_m, x0:x0 + tile_m]
            openings = edge_openings(walk, x0, y0, tile_m)
            if not openings:
                continue
            open_cells = sum(len(v) for v in openings.values())
            props = Counter(name for nx, ny, name in cells
                            if x0 <= nx < x0 + tile_m and y0 <= ny < y0 + tile_m and name)
            if not props and not open_cells:
                continue
            walkable = int(tile.sum())
            joined, comps = opening_connectivity(tile, openings)
            parcels.append({
                "map": data.get("map"),
                "origin": [int(x0), int(y0)],
                "size_m": tile_m,
                "walkable_share": round(walkable / float(tile.size), 3),
                "openings": openings,
                "opening_count": open_cells,
                "openings_connected": bool(joined),
                "opening_components": int(comps),
                "entrance_edges": [e for e in EDGES if openings.get(e)],
                "zone": zone_of(props),
                "prop_total": int(sum(props.values())),
                "prop_density_100m2": round(100.0 * sum(props.values()) / float(tile.size), 2),
                "prop_inventory": dict(props.most_common(8)),
                "height": height_stats(data.get("terrain"), x0, y0, tile_m, 1.0),
            })
    return {"map": data.get("map"), "size": [int(w), int(h)], "parcels": parcels}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", default=str(ROOT / "output/source_lab/maps"))
    ap.add_argument("--out", default=str(ROOT / "output/source_lab/parcels.json"))
    ap.add_argument("--tile", type=int, default=12, help="parcel edge in metres (nav cells)")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    maps = sorted(Path(args.maps).glob("*.json"))
    if not maps:
        print(f"no maps under {args.maps}")
        return 1

    all_parcels, per_map = [], {}
    for p in maps:
        cut = cut_map(p, args.tile)
        per_map[cut["map"]] = len(cut["parcels"])
        all_parcels.extend(cut["parcels"])

    usable = [q for q in all_parcels if q["opening_count"] >= 2 and q["openings_connected"]]
    connected = [q for q in usable if len(q["entrance_edges"]) >= 2]
    lengths = Counter(o["length"] for q in all_parcels for e in q["openings"].values() for o in e)
    zones = Counter(q["zone"] for q in all_parcels)
    out = {
        "tile_m": args.tile,
        "maps": len(maps),
        "parcels": len(all_parcels),
        "parcels_with_two_openings": len(usable),
        "parcels_with_two_edges": len(connected),
        "parcels_openings_connected": sum(1 for q in all_parcels if q.get("openings_connected")),
        "opening_lengths": dict(sorted(lengths.items())),
        "zones": dict(zones.most_common()),
        "per_map": per_map,
        "catalogue": all_parcels,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))

    if args.report:
        print(f"tile {args.tile} m | maps {len(maps)} | parcels {len(all_parcels)}")
        print(f"  with >=2 openings {len(usable)} | on >=2 edges {len(connected)}")
        print(f"  opening lengths {dict(sorted(lengths.items()))}")
        print(f"  zones {dict(zones.most_common(8))}")
        dens = [q["prop_density_100m2"] for q in all_parcels]
        if dens:
            dens.sort()
            print(f"  prop density /100m2: median {dens[len(dens)//2]:.2f} "
                  f"p90 {dens[int(len(dens)*0.9)]:.2f}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
