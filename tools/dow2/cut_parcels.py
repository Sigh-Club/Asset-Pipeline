#!/usr/bin/env python3
"""cut_parcels.py — cut the shipped maps into parcels, measured not invented.

The reference game assembles a map from hand-authored *parcels*: fixed-size pieces named after real
places, each declaring directional entrances, a street-front facing, land-use zones and objective
tags, stitched by a solver that only accepts a placement whose entrance matches its neighbour's.
That is why a reference map reads as a real location: the pieces are places and the streets are
solved.

DoW2 ships the same thing at a different granularity. Every shipped map is a hand-authored place --
thousands of prop placements with orientation, a terrain heightfield, splat masks and a nav grid, all
decoded into `output/source_lab/maps/*.json`. Cut that geography into parcel-sized rectangles and each
piece *is* an authored piece of a real location: it brings its own props, its own cover clusters, its
own ground and its own lighting context.

So the parcels are not authored again. They are cut from the corpus:

  * tile the nav grid at the reference's parcel sizes (small 16x16 tiles = 24x24 m, medium 32x16 =
    48x24 m, large 32x32 = 48x48 m, at the reference's 1.5 m tile -- `XCOM2Mods_LevelDesign.pdf`
    lines 985-987, and 1 tile = 96 uu = 1.5 m per `XComWorldData.uc`),
  * measure each piece's **edge openings from the shipped walkability grid** -- a run of walkable
    boundary cells that is also walkable two cells deep, which is the reference's
    "entrance of length N facing S", measured rather than declared,
  * derive the **street-front facing** from the widest opening (tie-broken by prop mass on that edge)
    and record the basis, so a facing is never invented silently,
  * record prop inventory, cover pieces by the shipped height ladder, enclosure, prop density, ground
    height range, the palette (map, biome, light) and how much map remains beyond each side for a
    periphery band, so a solver can match entrances and a renderer can draw the piece as authored.

Usage:
    python3 tools/dow2/cut_parcels.py --report
    python3 tools/dow2/cut_parcels.py --sizes 24x24 --out output/source_lab/parcels_24.json
    python3 tools/dow2/cut_parcels.py --tile 12 --out output/source_lab/parcels_12.json   # legacy
"""
from __future__ import annotations

import argparse
import base64
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT.parent / "Imperium-of-Ash"
FAMILIES = GAME / "frontend/public/assets/models/env/env_families.json"

# A boundary run only counts as an entrance if the passage continues into the piece: a one-cell sliver
# of walkable ground on the edge is a corner clip, not a street. Two cells of depth is the minimum
# that a unit can walk through at DoW2's 1 m nav resolution.
ENTRANCE_DEPTH_CELLS = 2
MIN_ENTRANCE_CELLS = 2
MAX_ENTRANCE_CELLS = 8

# The reference's parcel sizes in metres: 16x16, 32x16 and 32x32 tiles at 1.5 m. Our nav grid is 1 m,
# so the cuts are in nav cells: 24x24, 48x24, 48x48.
DEFAULT_SIZES = ("24x24", "48x24", "48x48")
SIZE_CLASS = {(24, 24): "small", (48, 24): "medium", (24, 48): "medium", (48, 48): "large"}

# Land use is read off the prop inventory rather than guessed from the map name, so a piece's zone is
# a measurement of what the level designers put there. Patterns are matched against prop names.
ZONE_PATTERNS = (
    ("industrial", ("generator", "industrial", "pipe", "tank", "refinery", "crane", "container")),
    ("fortified", ("wall", "barricade", "sandbag", "bunker", "gate", "turret")),
    ("overgrown", ("vine", "tree", "bush", "fern", "flora", "grass", "root")),
    ("ruined", ("rubble", "ruin", "debris", "wreck", "broken", "crater")),
    ("natural", ("rock", "cliff", "boulder", "mussel", "dune")),
    ("civic", ("lamp", "banner", "statue", "shrine", "altar", "monument")),
)

EDGES = ("N", "S", "E", "W")

# A piece needs this many walkable cells fully enclosed by the piece's own boundary to count as having
# an interior: a room you can walk into, not a doorway notch.
MIN_INTERIOR_CELLS = 6


def load_cover_tiers(path: Path) -> dict[str, str]:
    """Prop name -> cover tier ('low', 'high', 'climb') from the published kit manifest."""
    try:
        data = json.loads(path.read_text())
    except OSError:
        return {}
    out: dict[str, str] = {}
    for piece in data.get("pieces") or []:
        name, tier = piece.get("name"), piece.get("cover")
        if name and tier:
            out[str(name)] = str(tier)
    return out


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


def edge_openings(walk: np.ndarray, x0: int, y0: int, width: int, height: int) -> dict:
    """Openings on each edge, measured from the shipped walkability grid.

    An opening is a run of walkable boundary cells that is also walkable ENTRANCE_DEPTH_CELLS deep,
    so the passage actually connects into the piece. Length is reported in nav cells (1 m).
    """
    tile = walk[y0:y0 + height, x0:x0 + width]
    if tile.shape != (height, width):
        return {}
    depth = ENTRANCE_DEPTH_CELLS
    out: dict[str, list[dict]] = {}
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


def height_stats(terrain: dict | None, x0: int, y0: int, width: int, height: int) -> dict | None:
    """Ground height range for a piece, in metres, from the decoded heightfield."""
    if not terrain or not terrain.get("heights"):
        return None
    w, h = int(terrain["width"]), int(terrain["height"])
    scale = float(terrain.get("tile_world_scale") or 0) or 1.0
    heights = np.asarray(terrain["heights"], dtype=np.float32)
    if heights.size < w * h:
        return None
    grid = heights[:w * h].reshape(h, w)
    tw = max(1, int(round(width / max(scale, 1e-6))))
    th = max(1, int(round(height / max(scale, 1e-6))))
    tx, ty = int(round(x0 / max(scale, 1e-6))), int(round(y0 / max(scale, 1e-6)))
    patch = grid[ty:ty + th, tx:tx + tw]
    if patch.size == 0:
        return None
    return {"min": round(float(patch.min()), 2), "max": round(float(patch.max()), 2),
            "mean": round(float(patch.mean()), 2)}


def opening_connectivity(tile: np.ndarray, openings: dict) -> tuple[bool, int]:
    """Are a piece's openings in one walkable component?

    A piece whose openings sit in different components is a place with two halves that do not talk:
    it passes an entrance match on both sides and still cannot be walked through. Measured because
    assembled boards were failing traversability at 60% for exactly this reason.
    """
    labels, _count = ndimage.label(tile)  # type: ignore[name-defined]
    height, width = tile.shape
    comps = set()
    for edge, runs_ in openings.items():
        for o in runs_:
            for i in range(o["offset"], o["offset"] + o["length"]):
                y, x = {"N": (0, i), "S": (height - 1, i), "W": (i, 0), "E": (i, width - 1)}[edge]
                if labels[y, x]:
                    comps.add(int(labels[y, x]))
    return len(comps) == 1, len(comps)


def interior_stats(tile: np.ndarray) -> dict:
    """Walkable cells the piece's own boundary cannot reach: an interior, i.e. a room.

    The reference's parcels contain enterable buildings; a piece with an interior is what lets a
    board hold a building instead of a walled-off block. Measured by flood filling from every walkable
    boundary cell and counting what is left.
    """
    height, width = tile.shape
    walkable = tile.copy()
    if not walkable.any():
        return {"cells": 0, "share": 0.0}
    reached = np.zeros_like(walkable)
    stack: list[tuple[int, int]] = []
    for x in range(width):
        for y in (0, height - 1):
            if walkable[y, x]:
                stack.append((y, x))
    for y in range(height):
        for x in (0, width - 1):
            if walkable[y, x]:
                stack.append((y, x))
    while stack:
        y, x = stack.pop()
        if reached[y, x] or not walkable[y, x]:
            continue
        reached[y, x] = True
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < height and 0 <= nx < width and not reached[ny, nx]:
                stack.append((ny, nx))
    interior = int((walkable & ~reached).sum())
    return {"cells": interior, "share": round(interior / float(tile.size), 3)}


def zone_of(props: Counter) -> str:
    scores = {zone: sum(n for p, n in props.items() if any(k in p.lower() for k in keys))
              for zone, keys in ZONE_PATTERNS}
    best = max(scores, key=lambda z: scores[z]) if scores else "open"
    return best if scores.get(best, 0) > 0 else "open"


def facing_of(openings: dict, prop_mass: dict[str, int]) -> tuple[str | None, str]:
    """Derive the street-front facing, and say what the derivation rested on.

    The reference declares `eFacing` per parcel because a parcel is a building fronting a street. A
    cut from a continuous map has no such declaration, so it is derived: the edge with the most
    opening length, tie-broken by prop mass along that edge. The basis string is stored with the
    facing so a reviewer can see why a piece faces where it does -- never a silent guess.
    """
    by_edge = {e: sum(o["length"] for o in openings.get(e, [])) for e in EDGES}
    best = max(by_edge, key=lambda e: (by_edge[e], prop_mass.get(e, 0)))
    if by_edge[best] <= 0:
        best = max(prop_mass, key=lambda e: prop_mass.get(e, 0)) if prop_mass else None
        return best, "prop_mass_only"
    tied = [e for e in EDGES if by_edge[e] == by_edge[best]]
    if len(tied) > 1:
        best = max(tied, key=lambda e: prop_mass.get(e, 0))
        return best, "opening_length_tied_prop_mass"
    return best, "opening_length"


def prop_mass_by_edge(cells, x0, y0, width, height, band=3) -> dict[str, int]:
    out = {e: 0 for e in EDGES}
    for nx, ny, _name in cells:
        lx, ly = nx - x0, ny - y0
        if 0 <= lx < width and 0 <= ly < height:
            if ly < band:
                out["N"] += 1
            if ly >= height - band:
                out["S"] += 1
            if lx < band:
                out["W"] += 1
            if lx >= width - band:
                out["E"] += 1
    return out


def periphery_margin(w: int, h: int, x0: int, y0: int, width: int, height: int) -> dict[str, int]:
    """How much map remains beyond each side, in metres: the band a periphery could be drawn from."""
    return {"N": int(y0), "S": int(h - (y0 + height)), "W": int(x0), "E": int(w - (x0 + width))}


def cut_map(path: Path, sizes: list[tuple[int, int]], cover_tiers: dict[str, str]) -> dict:
    data = json.loads(path.read_text())
    walk = nav_grid(data.get("nav"))
    if walk is None:
        return {"map": data.get("map"), "parcels": [], "skipped": "no nav"}
    h, w = walk.shape
    palette = [p.get("prop") or "" for p in data.get("props") or []]
    biomes = [p.get("biome") or "" for p in data.get("props") or []]
    placements = data.get("placements") or []
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
            biome = biomes[kind] if isinstance(kind, int) and 0 <= kind < len(biomes) else ""
            cells.append((nx, ny, name, biome))

    parcels = []
    for width, height in sizes:
        if width > w or height > h:
            continue
        for y0 in range(0, h - height + 1, height):
            for x0 in range(0, w - width + 1, width):
                tile = walk[y0:y0 + height, x0:x0 + width]
                openings = edge_openings(walk, x0, y0, width, height)
                open_cells = sum(len(v) for v in openings.values())
                inside = [(nx, ny, name, biome) for nx, ny, name, biome in cells
                          if x0 <= nx < x0 + width and y0 <= ny < y0 + height]
                props = Counter(name for _nx, _ny, name, _b in inside if name)
                if not props and not open_cells:
                    continue
                walkable = int(tile.sum())
                joined, comps = opening_connectivity(tile, openings)
                interior = interior_stats(tile)
                mass = prop_mass_by_edge([(nx, ny, name) for nx, ny, name, _b in inside],
                                         x0, y0, width, height)
                facing, facing_basis = facing_of(openings, mass)
                cover = Counter()
                for _nx, _ny, name, _b in inside:
                    tier = cover_tiers.get(name)
                    if tier:
                        cover[tier] += 1
                biome = Counter(b for _nx, _ny, _n, b in inside if b).most_common(1)
                size_class = SIZE_CLASS.get((width, height), "custom")
                # A piece is usable when it can be entered from at least two sides and those entrances
                # reach each other. That is the minimum for a solver to stitch it into a street.
                usable = open_cells >= 2 and joined and len([e for e in EDGES if openings.get(e)]) >= 2
                parcels.append({
                    "id": f"{data.get('map')}_{size_class}_{x0}_{y0}",
                    "map": data.get("map"),
                    "origin": [int(x0), int(y0)],
                    "eSize": size_class,
                    "size_xy": [int(width), int(height)],
                    # legacy field for the square-tile assembler; rectangles are catalogue-only
                    "size_m": int(width) if width == height else None,
                    "biome": biome[0][0] if biome else None,
                    "palette": {"map": data.get("map"), "biome": biome[0][0] if biome else None},
                    "walkable_share": round(walkable / float(tile.size), 3),
                    "openings": openings,
                    "opening_count": open_cells,
                    "openings_connected": bool(joined),
                    "opening_components": int(comps),
                    "entrance_edges": [e for e in EDGES if openings.get(e)],
                    "facing": facing,
                    "facing_basis": facing_basis,
                    "zone": zone_of(props),
                    "prop_total": int(sum(props.values())),
                    "prop_density_100m2": round(100.0 * sum(props.values()) / float(tile.size), 2),
                    "unique_props": len(props),
                    "prop_inventory": dict(props.most_common(8)),
                    "cover": {tier: int(n) for tier, n in sorted(cover.items())},
                    "cover_total": int(sum(cover.values())),
                    "interior": interior,
                    "has_interior": interior["cells"] >= MIN_INTERIOR_CELLS,
                    "height": height_stats(data.get("terrain"), x0, y0, width, height),
                    "periphery_margin_m": periphery_margin(w, h, x0, y0, width, height),
                    "usable": bool(usable),
                })
    return {"map": data.get("map"), "size": [int(w), int(h)], "parcels": parcels}


def parse_sizes(values: list[str]) -> list[tuple[int, int]]:
    out = []
    for v in values:
        a, _, b = v.lower().partition("x")
        out.append((int(a), int(b or a)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", default=str(ROOT / "output/source_lab/maps"))
    ap.add_argument("--out", default=str(ROOT / "output/source_lab/parcels.json"))
    ap.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES),
                    help="parcel rectangles in nav cells, e.g. 24x24 48x24 48x48")
    ap.add_argument("--tile", type=int, default=None,
                    help="legacy: a single square edge in metres (overrides --sizes)")
    ap.add_argument("--families", default=str(FAMILIES))
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    sizes = [(args.tile, args.tile)] if args.tile else parse_sizes(args.sizes)
    maps = sorted(Path(args.maps).glob("*.json"))
    if not maps:
        print(f"no maps under {args.maps}")
        return 1
    cover_tiers = load_cover_tiers(Path(args.families))

    all_parcels, per_map = [], {}
    for p in maps:
        cut = cut_map(p, sizes, cover_tiers)
        per_map[cut["map"]] = len(cut["parcels"])
        all_parcels.extend(cut["parcels"])

    usable = [q for q in all_parcels if q["usable"]]
    out = {
        "sizes": [f"{w}x{h}" for w, h in sizes],
        "maps": len(maps),
        "cover_tiers_loaded": len(cover_tiers),
        "parcels": len(all_parcels),
        "usable_parcels": len(usable),
        "per_map": per_map,
        "catalogue": all_parcels,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1))

    if args.report:
        print(f"sizes {out['sizes']} | maps {len(maps)} | parcels {len(all_parcels)}")
        for w, h in sizes:
            label = SIZE_CLASS.get((w, h), "custom")
            group = [q for q in all_parcels if tuple(q["size_xy"]) == (w, h)]
            good = [q for q in group if q["usable"]]
            interiors = [q for q in good if q["has_interior"]]
            print(f"  {label:7s} {w}x{h} m: cut {len(group)} | usable {len(good)} | "
                  f"with interior {len(interiors)}")
        zones = Counter(q["zone"] for q in usable)
        print(f"  zones of usable: {dict(zones.most_common(8))}")
        cover = Counter()
        for q in usable:
            for tier, n in q["cover"].items():
                cover[tier] += n
        print(f"  cover pieces in usable parcels: {dict(sorted(cover.items()))}")
        dens = sorted(q["prop_density_100m2"] for q in usable)
        if dens:
            print(f"  prop density /100m2 of usable: median {dens[len(dens)//2]:.2f} "
                  f"p90 {dens[int(len(dens)*0.9)]:.2f}")
        facings = Counter(q["facing"] for q in usable)
        print(f"  derived facings: {dict(facings.most_common())}")
        print(f"  facing bases: {dict(Counter(q['facing_basis'] for q in usable).most_common())}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
