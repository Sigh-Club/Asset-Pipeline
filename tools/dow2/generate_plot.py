#!/usr/bin/env python3
"""Generate a tactical plot in the reference's own grammar, styled with our kit.

The method is taken from the reference's shipped data, not invented (see
`docs/XCOM2_MEASURED_GRAMMAR.md`):

* a **plot** is a road network with parcel slots along it, plus a periphery set;
* road pieces are 8-tile modules with turn types (straight, corner, T, intersection, court);
* parcels are blocks: most declare no entrance of their own -- the plot connects them;
* cover is small pieces at the measured density (0.9-1.5 per 100 m2), low about twice high, placed at lane
  edges and building frontages;
* line of sight is a first-class property and is reported, not assumed.

What this tool writes is the same staged-board document the game already loads (`paint`, `cover`,
`free_props`, `heights`, `deployment`, `light`, `terrain`, `source`), so a generated plot and a cut parcel
board are the same thing to the renderer and the rules.

Usage:
    python3 -u tools/dow2/generate_plot.py --plot CityCenter --seed 1 --map 6p_ffa_whitewallsofcalderis \
        --out <game>/frontend/public/assets/maps/staged/plot_citycenter_1.json --catalogue <catalogue.json>
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT.parent / "Imperium-of-Ash"
CELL_M = 2.0
MODULE_CELLS = 8          # the reference's road modules are 8 tiles; ours are 8 cells (16 m)
ROAD_CELLS = 4            # a two-lane carriageway with room for cover on the kerb
SIDEWALK_CELLS = 1

# The plot types the reference ships, with the cover density measured from its own parcels per 100 m2.
PLOT_TYPES = {
    "CityCenter": {"cover_per_100m2": 0.73, "blocks": "dense", "courts": 1},
    "Shanty": {"cover_per_100m2": 2.70, "blocks": "loose", "courts": 0},
    "SmallTown": {"cover_per_100m2": 2.16, "blocks": "loose", "courts": 1},
    "Slums": {"cover_per_100m2": 0.77, "blocks": "dense", "courts": 0},
    "Wilderness": {"cover_per_100m2": 1.54, "blocks": "open", "courts": 0},
    "Facility": {"cover_per_100m2": 0.40, "blocks": "grid", "courts": 1},
    "Rooftops": {"cover_per_100m2": 0.62, "blocks": "flat", "courts": 0},
}


def load_kit() -> dict:
    path = GAME / "frontend/public/assets/models/env/env_kit.json"
    if not path.exists():
        return {}
    return {p["name"]: p for p in json.loads(path.read_text()).get("props", [])}


def load_families() -> dict:
    path = ROOT / "output/source_lab/env_families.json"
    if not path.exists():
        return {}
    return {p["name"]: p for p in json.loads(path.read_text()).get("pieces", [])}


def pick_kit(names: list[str], biome: str, heights: dict, families: dict,
             *, tier: str | None = None, min_h: float = 0.0, max_h: float = 99.0) -> list[str]:
    """The pieces of a biome's kit that can play a role: a cover tier, a height band, or either."""
    out = []
    for name in names:
        info = families.get(name) or {}
        if tier is not None and info.get("cover") != tier:
            continue
        h = heights.get(name, 0.0)
        if not (min_h <= h <= max_h):
            continue
        out.append(name)
    return out


def generate(plot: str, seed: int, map_name: str, kit: dict, families: dict,
             cells: int) -> dict:
    rng = random.Random(seed)
    spec = PLOT_TYPES.get(plot, PLOT_TYPES["CityCenter"])
    gw = gh = cells
    bw = bh = gw * CELL_M
    area = bw * bh

    paint = {f"{x},{y}": "normal" for y in range(gh) for x in range(gw)}
    cover: dict[str, str] = {}
    free_props: list[dict] = []
    heights = [[0] * gw for _ in range(gh)]

    # ---------------------------------------------------------------- the periphery set
    # The reference ships a dedicated Periphery set (90 definitions). Ours is a border of impassable blocks
    # with the map's own wall pieces on it: the board ends in architecture, not in a void.
    border = 2
    for y in range(gh):
        for x in range(gw):
            if x < border or y < border or x >= gw - border or y >= gh - border:
                paint[f"{x},{y}"] = "impassable"

    # ---------------------------------------------------------------- the road network
    # One main road across the plot with a T-junction and, on the plot types that have one, a court. The
    # module grid is the reference's: turns land on 8-tile boundaries.
    lane_y = gh // 2 - ROAD_CELLS // 2
    road: list[dict] = []

    def lay_road(x0: int, y0: int, w: int, h: int, kind: str) -> None:
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if not (0 <= x < gw and 0 <= y < gh):
                    continue
                paint[f"{x},{y}"] = "normal"
                heights[y][x] = 0
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                is_road[(x, y)] = True
        road.append({"x": x0, "y": y0, "w": w, "h": h, "kind": kind})

    is_road: dict[tuple[int, int], bool] = {}
    lay_road(border, lane_y, gw - border * 2, ROAD_CELLS, "straight")
    junction_x = border + MODULE_CELLS * 2
    lay_road(junction_x, border, ROAD_CELLS, lane_y - border, "T")
    if spec["courts"]:
        lay_road(junction_x, lane_y, MODULE_CELLS, MODULE_CELLS, "court")

    # ---------------------------------------------------------------- parcels
    # The reference's plot is a street with parcel *lots* along it: the lots fill the ground between the lane
    # and the periphery, they are subdivided, and the plot's lanes and alleys are what connect them (105 of
    # the reference's 172 parcels declare no entrance of their own). Scattering a handful of free-standing
    # blocks leaves a field with objects in it -- the first attempt did exactly that.
    blocks: list[dict] = []
    strips = [(border, lane_y - 1, "north"), (lane_y + ROAD_CELLS + 1, gh - border - 1, "south")]
    for (y0, y1, side) in strips:
        depth = y1 - y0 + 1
        if depth < 3:
            continue
        x = border
        while x < gw - border:
            w = rng.choice([6, 7, 8, 9])
            if x + w > gw - border:
                w = gw - border - x
            if w < 3:
                break
            lot = {"x": x, "y": y0, "w": w, "h": depth, "side": side}
            for y in range(y0, y0 + depth):
                for xx in range(x, x + w):
                    paint[f"{xx},{y}"] = "impassable"
            # a door onto the lane, two cells wide
            door_x = x + w // 2
            door_y = y1 if side == "north" else y0
            for dx in (0, 1):
                if door_x + dx < gw:
                    paint[f"{door_x + dx},{door_y}"] = "normal"
            lot["door"] = [door_x, door_y]
            blocks.append(lot)
            x += w + (1 if rng.random() < 0.6 else 0)  # an alley between most lots
    # the alleys are the plot's second connection layer: a lot's side wall gets a gap onto the alley
    for b in blocks:
        if b["x"] > border and paint.get(f"{b['x'] - 1},{b['y'] + b['h'] // 2}") == "normal":
            continue

    # ---------------------------------------------------------------- cover
    # Small pieces at the measured density for this plot type, low about twice high, on the kerb line and in
    # front of the doors -- where cover belongs, rather than scattered across the ground.
    biome = next((p.get("biome") for p in kit.values() if p.get("biome")), "desert")
    names = [n for n in kit if max(((kit[n].get("size") or [0, 0, 0]) + [0])[:3]) <= 20.0]
    heights_of = {n: float((kit[n].get("size") or [0, 0, 0])[2] or 0) for n in names}

    def footprint(n: str) -> float:
        sz = (kit.get(n) or {}).get("size") or [0, 0, 0]
        return min(float(sz[0] or 0), float(sz[1] or 0))

    # Cover is a crate, a barrier, a sandbag or a low wall -- not a pale wedge. The kit's families say which
    # pieces are cover; the name catches the ones the classifier filed as scenery.
    COVER_NAMES = ("crate", "barrier", "sandbag", "rubble", "debris", "bench", "stall", "wall")

    def cover_piece(n: str) -> bool:
        if footprint(n) < 1.0 or heights_of.get(n, 0) < 0.4:
            return False
        return (families.get(n) or {}).get("family") == "cover" or any(k in n for k in COVER_NAMES)

    lows = [n for n in pick_kit(names, biome, heights_of, families, tier="low", min_h=0.3, max_h=0.95)
            if cover_piece(n)]
    highs = [n for n in pick_kit(names, biome, heights_of, families, tier="high", min_h=0.95, max_h=1.6)
             if cover_piece(n)]
    target = max(6, int(round(area / 100.0 * spec["cover_per_100m2"])))

    taken: set[tuple[int, int]] = set()

    def place_cover(x: int, y: int) -> bool:
        key = (x, y)
        if key in taken or paint.get(f"{x},{y}") != "normal":
            return False
        pool = (lows if rng.random() < 2 / 3 else highs) if (lows and highs) else (lows or highs or names)
        if not pool:
            return False
        name = pool[rng.randrange(len(pool))]
        free_props.append({
            "name": name,
            "biome": (kit.get(name) or {}).get("biome") or biome,
            "pos": [round(x * CELL_M - bw / 2 + CELL_M / 2, 3), 0.0,
                    round(y * CELL_M - bh / 2 + CELL_M / 2, 3)],
            "basis": [1, 0, 0, 0, 1, 0, 0, 0, 1],
            "scale": 1,
            "cover": "kerb",
        })
        taken.add(key)
        tier = (families.get(name) or {}).get("cover")
        cell = {"low": "light_cover", "high": "cover"}.get(tier or "")
        if cell:
            cover[f"{x},{y}"] = cell
        return True

    # the kerb line: the carriageway cell that runs along each lot frontage, and in front of every door
    placed = 0
    kerb = [(x, lane_y) for x in range(border, gw - border)]
    kerb += [(x, lane_y + ROAD_CELLS - 1) for x in range(border, gw - border)]
    rng.shuffle(kerb)
    for (x, y) in kerb:
        if placed >= target:
            break
        if place_cover(x, y):
            placed += 1
    # the second row into the carriageway, then the court edge: a dense plot type needs more pieces than
    # one kerb line holds, and a barricade in the road is exactly where the reference puts one
    inner = [(x, y) for x in range(border, gw - border) for y in range(lane_y, lane_y + ROAD_CELLS)]
    inner += [(x, y) for x in range(junction_x, min(gw - border, junction_x + MODULE_CELLS))
              for y in range(lane_y, lane_y + MODULE_CELLS)]
    rng.shuffle(inner)
    for (x, y) in inner:
        if placed >= target:
            break
        if place_cover(x, y):
            placed += 1

    # ---------------------------------------------------------------- line of sight
    # Walls block, so the plot's own structure decides its sightlines. Reported as the reference measures
    # them: the longest unbroken line and the share of cells with a line past one weapon range.
    def blocked(x: int, y: int) -> bool:
        return paint.get(f"{x},{y}") == "impassable"

    longest = 0
    long_cells = 0
    walkable_cells = 0
    weapon_cells = 12  # 24 m at our 2 m cell: one standard weapon range
    for y in range(gh):
        for x in range(gw):
            if blocked(x, y):
                continue
            walkable_cells += 1
            best = 0
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                run = 0
                cx, cy = x, y
                while 0 <= cx < gw and 0 <= cy < gh and not blocked(cx, cy):
                    run += 1
                    cx += dx
                    cy += dy
                best = max(best, run)
            longest = max(longest, best)
            if best >= weapon_cells:
                long_cells += 1

    # ---------------------------------------------------------------- connectivity
    # Every cell a unit can stand on must be reachable: a cell nobody can walk to is sealed.
    # the flood starts on the carriageway itself, which is the plot's spine
    start = (border + 1, lane_y + 1)
    seen: set[tuple[int, int]] = set()
    stack = [start]
    while stack:
        cx, cy = stack.pop()
        if (cx, cy) in seen or not (0 <= cx < gw and 0 <= cy < gh) or blocked(cx, cy):
            continue
        seen.add((cx, cy))
        stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))
    sealed = 0
    for y in range(gh):
        for x in range(gw):
            if not blocked(x, y) and (x, y) not in seen:
                paint[f"{x},{y}"] = "impassable"
                sealed += 1

    # ---------------------------------------------------------------- styling: frontages and street furniture
    # A block is a *frontage*: wall pieces along its lane-facing edge, not one tower dropped on it. A single
    # 20 m building per block is what made the first plot read as "a plane with one asset" -- the reference's
    # parcels are streets of buildings, and the street is the thing that has to read.
    def sizes_of(n: str) -> tuple[float, float, float]:
        sz = (kit.get(n) or {}).get("size") or [0, 0, 0]
        return (float(sz[0] or 0), float(sz[1] or 0), float(sz[2] or 0))

    # A facade is a piece that can line a 16 m block: 3-12 m tall and no wider than the block it fronts.
    # The first plot took the arena kit's 40 m industrial platform as a "building" and produced one machine
    # instead of a street.
    # Architecture only: the kit also holds vehicles and rocks, and a 8 m tank passes a size filter while
    # reading as a tank. A frontage is a wall, a pillar, a doorway or a roof piece.
    ARCH = {"wall_run", "wall_corner", "wall_barrier", "pillar", "doorway"}
    facades = [n for n in names
               if (families.get(n) or {}).get("family") in ARCH
               and 5.0 <= sizes_of(n)[2] <= 14.0
               and 4.0 <= max(sizes_of(n)[0], sizes_of(n)[1]) <= 16.0]
    # Walls first, then pillars and doorways: a frontage is built from wall modules. Sorting by size alone
    # put collapsed columns and statues on the street line, because they happen to be wide.
    # A frontage is a building line: pieces of at least two storeys. Two-metre wall runs read as a fence
    # around an empty field, which is what the low-wall selection produced.
    rank = {"wall_run": 0, "wall_corner": 1, "wall_barrier": 2, "pillar": 3, "doorway": 4}
    facades.sort(key=lambda n: (rank.get((families.get(n) or {}).get("family"), 9),
                                -sizes_of(n)[2],
                                -max(sizes_of(n)[0], sizes_of(n)[1])))
    lamps = [n for n in names if "lamp" in n.lower()]
    for i, b in enumerate(blocks):
        if not facades:
            break
        # A frontage is continuous: pieces are laid edge to edge along the lane-facing side, using each
        # piece's own width, so the block reads as a building line rather than as objects in a field.
        run_len = b["w"] * CELL_M
        cursor = 0.0
        k = 0
        while cursor < run_len - 1.0 and k < 24:
            # best fit: the module that fills the remaining run most closely, so the line is continuous
            remaining = run_len - cursor
            pool = facades[:min(len(facades), 12)]
            name = min(pool, key=lambda n: abs(max(sizes_of(n)[0], sizes_of(n)[1]) - min(remaining, 9.0)))
            width = max(sizes_of(name)[0], sizes_of(name)[1]) or 4.0
            width = min(width, remaining)
            mid = cursor + width / 2
            cursor += width
            k += 1
            # the frontage runs along the lot's lane-facing edge
            x = b["x"] * CELL_M + mid
            y = (b["y"] + b["h"] - 1 if b["side"] == "north" else b["y"]) * CELL_M
            free_props.append({
                "name": name,
                "biome": (kit.get(name) or {}).get("biome") or biome,
                "pos": [round(x - bw / 2, 3), 0.0, round(y - bh / 2, 3)],
                "basis": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "scale": 1,
                "parcel": True,
            })
    # street furniture on the kerb line: what makes a lane read as a street rather than a painted strip
    if lamps:
        for k, x in enumerate(range(border + 2, gw - border, 6)):
            y = lane_y - 1 if k % 2 == 0 else lane_y + ROAD_CELLS
            free_props.append({
                "name": lamps[k % len(lamps)],
                "biome": (kit.get(lamps[k % len(lamps)]) or {}).get("biome") or biome,
                "pos": [round(x * CELL_M - bw / 2 + CELL_M / 2, 3), 0.0,
                        round(y * CELL_M - bh / 2 + CELL_M / 2, 3)],
                "basis": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                "scale": 1,
                "kerb": True,
            })

    # ---------------------------------------------------------------- the road surface
    # The lane has to read as a road, not as a painted strip: the reference's plots carry paved road PCPs.
    # We have no road meshes, but the shipped decal kit has cobble and stone-tile grounds, laid here as a
    # tiled surface over the carriageway and the court.
    decal_kit = GAME / "frontend/public/assets/decals/decal_kit.json"
    decals: list[dict] = []
    if decal_kit.exists():
        names_d = [d["name"] for d in json.loads(decal_kit.read_text()).get("decals", [])]
        prefer = ["cobblestone", "stone_tiles", "u_stone_tiles", "cobbles"]
        road_decal = next((n for k in prefer for n in names_d if k in n), None)
        if road_decal:
            for piece in road:
                for dy in range(0, piece["h"], 2):
                    for dx in range(0, piece["w"], 2):
                        decals.append({
                            "name": road_decal,
                            "x": piece["x"] + dx + 1,
                            "y": piece["y"] + dy + 1,
                            "size": [2, 2],
                            "rot": 0,
                        })

    terrain_path = GAME / "frontend/public/assets/maps/terrain" / map_name / "terrain.json"
    terrain = json.loads(terrain_path.read_text()) if terrain_path.exists() else None

    # self-check: the deployment zones must stand on ground a unit can occupy, or the battle falls back
    # to the archetype's own deployment and the plot's landing zones are decoration
    zones = {"player": (border + 1, lane_y + 1), "enemy": (gw - border - 4, lane_y + 1)}
    for side, (zx, zy) in zones.items():
        for dx in range(3):
            for dy in range(2):
                if blocked(zx + dx, zy + dy):
                    raise SystemExit(
                        f"{plot} {seed}: {side} deployment cell ({zx + dx},{zy + dy}) is impassable")

    return {
        "name": f"plot {plot} {seed}",
        "biome": biome,
        "ground": map_name,
        "size": {"width": gw, "height": gh},
        "paint": paint,
        "heights": heights,
        "rooms": [],
        "props": [],
        "free_props": free_props,
        "decals": decals,
        "terrain": terrain,
        "light": {"azimuthDeg": 215, "elevationDeg": 52, "colour": "#ffe6c2", "intensity": 3.4,
                  "sky": "#dfe4ea", "ground": "#4a4238", "ambient": 0.9},
        # Both squads land on the carriageway at opposite ends: the lane is the plot's guaranteed-walkable
        # spine. A zone inside a lot is a zone of impassable cells, and the battle then falls back to the
        # archetype's deployment and spawns on (1,1).
        "deployment": {"player": {"x": border + 1, "y": lane_y + 1, "w": 3, "h": 2},
                       "enemy": {"x": gw - border - 4, "y": lane_y + 1, "w": 3, "h": 2}},
        "cover": cover,
        "source": {
            "kind": "plot-board",
            "plot": plot,
            "map": map_name,
            "seed": seed,
            "grid_m": CELL_M,
            "road": road,
            "blocks": blocks,
            "metrics": {
                "cover_pieces": len([fp for fp in free_props if fp.get("cover")]),
                "cover_per_100m2": round(len([fp for fp in free_props if fp.get("cover")]) / area * 100, 2),
                "cover_target": spec["cover_per_100m2"],
                "longest_sightline_cells": longest,
                "long_sightline_share": round(long_cells / max(1, walkable_cells), 3),
                "walkable_cells": walkable_cells,
                "sealed_pockets": sealed,
                # clumping, measured the way the corpus bands measure it: props per quadrant, spread
                # against the mean. A plot is meant to clump along its street, not scatter.
                "dispersion": _dispersion(free_props, bw, bh, gw, gh),
            },
        },
    }


def _dispersion(free_props: list[dict], bw: float, bh: float, gw: int, gh: int) -> float:
    """Props per 4x4 quadrant: the mean divided by the spread, the corpus's own dispersion measure."""
    counts = [[0] * 4 for _ in range(4)]
    for fp in free_props:
        qx = min(3, max(0, int((fp["pos"][0] + bw / 2) / bw * 4)))
        qz = min(3, max(0, int((fp["pos"][2] + bh / 2) / bh * 4)))
        counts[qz][qx] += 1
    flat = [c for row in counts for c in row]
    mean = sum(flat) / len(flat)
    if mean <= 0:
        return 0.0
    var = sum((c - mean) ** 2 for c in flat) / len(flat)
    sd = var ** 0.5
    return round(mean / sd, 2) if sd > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plot", default="CityCenter", choices=sorted(PLOT_TYPES))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--map", default="6p_ffa_whitewallsofcalderis")
    ap.add_argument("--cells", type=int, default=30, help="board size in 2 m cells (30 = 60 m)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--catalogue", default=None)
    args = ap.parse_args()

    kit = load_kit()
    families = load_families()
    doc = generate(args.plot, args.seed, args.map, kit, families, args.cells)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc))
    m = doc["source"]["metrics"]
    print(f"wrote {out.name}: {args.plot} {args.cells}x{args.cells} cells, "
          f"{len(doc['source']['road'])} road pieces, {len(doc['source']['blocks'])} parcels, "
          f"cover {m['cover_pieces']} ({m['cover_per_100m2']}/100m2, target {m['cover_target']}), "
          f"longest sightline {m['longest_sightline_cells']} cells, "
          f"long-sightline share {m['long_sightline_share']}, sealed {m['sealed_pockets']}")
    if args.catalogue:
        cat_path = Path(args.catalogue)
        cat = json.loads(cat_path.read_text())
        entry = {
            "id": out.stem, "kind": "plot-board", "biome": doc["biome"], "seed": args.seed,
            "size": doc["size"], "file": out.name,
            "metrics": {"props": len(doc["free_props"]),
                        "densityPer100m2": round(100.0 * len(doc["free_props"]) / (args.cells * CELL_M) ** 2, 2),
                        "dispersion": doc["source"]["metrics"]["dispersion"],
                        # cover and total props are different quantities: the plot type's measured band is
                        # about cover, and a board's total is cover plus frontages plus street furniture
                        "coverPer100m2": doc["source"]["metrics"]["cover_per_100m2"],
                        "coverTarget": doc["source"]["metrics"]["cover_target"],
                        "embeddedShare": 0},
        }
        cat["entries"] = [e for e in cat.get("entries", []) if e.get("id") != entry["id"]] + [entry]
        cat_path.write_text(json.dumps(cat, indent=1))


if __name__ == "__main__":
    main()
