#!/usr/bin/env python3
"""forge_import.py — turn a shipped DoW2 map into a map-forge layout.

A decoded map (`scenario_decode.py` output) carries the terrain heightmap, the game's nav grid, and
every placement with its blueprint path. This converts that into the forge's authoring format so a
shipped map can be opened, studied and edited in `/maps` — which is the test of whether our authored
maps stand up: the game's own maps are the reference, not a taste judgement.

What carries across, and why:

  * **heights** — the terrain grid resampled to the layout's cells, in the engine's elevation steps
    (`ELEVATION_STEP` 0.35 m), so the board has the map's real relief;
  * **paint** — impassable where the game's nav grid says a unit cannot stand, so the walkable shape
    of the map is preserved without guessing;
  * **props** — each placement snapped to a cell and resolved to the nearest prop in the environment
    kit by blueprint name (the kit is the props the shipped maps use most, so most resolve).

Usage:
  python3 tools/dow2/forge_import.py --maps output/source_lab/maps --kit <env_kit.json> \
      --out ../Imperium-of-Ash/frontend/public/assets/maps --only 1v1typhonlowlands --width 24 --height 20
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ELEVATION_STEP = 0.35  # three/gridMath.ts
TILE_SIZE = 2.0
# A combat board is 2 m per cell and 0.35 m per elevation step. A shipped map's relief is 20-110 m
# across kilometres; carrying that range onto a 40 m board would put a 100 m cliff on a 20-cell map
# (measured: the first import produced 172-309 steps, i.e. 60-108 m of relief, and the camera sat
# inside the terrain). The cap is the board's own scale: at most 6 steps (2.1 m) of relief, which is
# what a 40 m board can express and what a unit can path over.
MAX_RELIEF_STEPS = 6


# Gameplay blueprints are named by their *function*, not by the model that draws them: a
# `victory_point_pvp` is drawn with the `victory_point_02` mesh and a `strategic_point_pvp` with the
# `capture_point` beacon. Measured across the corpus (36 distinct gameplay blueprints), this is the
# whole mapping that matters; anything else gameplay-shaped is an invisible helper and is skipped.
GAMEPLAY_ALIASES = (
    ("victory_point", "victory_point_02"),
    ("strategic_point", "capture_point"),
    ("relic_point", "capture_point_ffa"),
    ("resource_power_drop", "resource_power_drop"),
    ("resource_requisition_drop", "resource_requisition_drop"),
    ("container_power", "container"),
    ("container_requisition", "container"),
)
# these are shape or bookkeeping, not landmarks: blockers are the paint layer, spawns are invisible
GAMEPLAY_SKIP = ("blocker", "spawn", "position", "camo", "marker", "start")


# Tokens that carry no identity: size words, ordinals and stock suffixes.
_STOP_TOKENS = {
    "sb", "a", "b", "c", "the", "and", "long", "short", "small", "large", "lrg", "sml", "med", "mid",
    "one", "two", "three", "four", "five", "six", "stack", "single", "half", "full", "base", "top",
}


def _tokens(name: str) -> list[str]:
    parts = [t for t in re.split(r"[_\-\s]+", name.lower()) if t]
    return [t for t in parts if t not in _STOP_TOKENS and not t.isdigit()]


def gameplay_prop(blueprint: str, kit_names: list[str]) -> tuple[str | None, str]:
    """A gameplay blueprint to the mesh that draws it, or (None, "skip") for an invisible helper."""
    name = blueprint.rsplit("/", 1)[-1].lower()
    if any(skip in name for skip in GAMEPLAY_SKIP):
        return None, "skip"
    for prefix, prop in GAMEPLAY_ALIASES:
        if name.startswith(prefix) and prop in kit_names:
            return prop, "gameplay"
    return nearest_prop(name, kit_names)


def nearest_prop(name: str, kit_names: list[str]) -> tuple[str | None, str]:
    """The kit prop for a blueprint's model name, and how it was decided.

    The previous rule was a longest-shared-prefix heuristic, which is why a desert map placed
    `desert_mussel` 38 times: every `desert_*` blueprint shares that prefix. Identity is carried by
    the **head noun** (the last meaningful token), so a match requires it to agree, and the match is
    rejected rather than guessed when it does not.

    Returns (prop, "exact" | "token" | "none").
    """
    low = name.lower()
    if low in kit_names:
        return low, "exact"
    want = _tokens(low)
    if not want:
        return None, "none"
    head = want[-1]
    best, best_score = None, 0
    for candidate in kit_names:
        have = _tokens(candidate)
        if not have or head not in have:
            continue
        score = len(set(want) & set(have))
        if score > best_score:
            best, best_score = candidate, score
    # one shared token is the head noun alone, which is too weak to be an identity
    return (best, "token") if best and best_score >= 2 else (None, "none")


def height_at_world(terrain: dict, nav: dict | None, wx: float, wz: float) -> float:
    """Terrain height at a world position, from the map's own heightmap.

    The heightmap is indexed against the **playable extent** (the nav grid's dimensions, 1 m cells,
    centred on the origin) rather than the heightmap's own sample count. Measured caveat: some maps
    carry a heightmap wider than the playable area (a 385-sample heightmap on a 256 m map), so the
    relief is slightly compressed. That is immaterial here because the board normalises relief to a
    6-step budget anyway, and it is recorded rather than hidden.
    """
    grid = terrain.get("heights") or []
    if not grid:
        return 0.0
    rows, cols = len(grid), len(grid[0])
    nw = float((nav or {}).get("width") or 0)
    nh = float((nav or {}).get("height") or 0)
    if not nw or not nh:
        nw = nh = float(max(rows, cols))
    u = (wx + nw / 2.0) / nw
    v = (wz + nh / 2.0) / nh
    sx = min(cols - 1, max(0, int(u * cols)))
    sy = min(rows - 1, max(0, int(v * rows)))
    return float(grid[sy][sx])


def board_heights(terrain: dict, nav: dict | None, width: int, height: int,
                  centre: tuple[float, float],
                  max_steps: int = MAX_RELIEF_STEPS) -> list[list[int]]:
    """The board's relief, sampled from the map over the board's own 1:1 window.

    A board is a window into the map at 1:1 scale: cell (x, y) covers a real 2 m x 2 m square of the
    map centred at `centre`. The relief is normalised into `max_steps` (the board's budget) with the
    source range kept in `source.relief`.
    """
    cx, cz = centre
    raw = []
    for y in range(height):
        row = []
        for x in range(width):
            wx = cx + (x + 0.5 - width / 2.0) * TILE_SIZE
            wz = cz + (y + 0.5 - height / 2.0) * TILE_SIZE
            row.append(height_at_world(terrain, nav, wx, wz))
        raw.append(row)
    lo = min(min(r) for r in raw)
    peak = max(max(r) for r in raw) - lo
    scale = (max_steps / peak) if peak > 0 else 0.0
    return [[int(round((v - lo) * scale)) for v in row] for row in raw]


def nav_blocked(nav: dict | None, width: int, height: int) -> set[tuple[int, int]]:
    """Cells the game's own nav grid marks as not standable, in board cells.

    `WRLD/WLDI/PFDR/PRMP` layer 0 is the passability grid: one byte per nav cell, and a zero byte
    means nothing can stand there (measured on `xp2_a_chapterkeepselenon`: 93,168 of 163,840 cells
    are zero). Non-zero bytes are a bitfield of the map's passability types — which bit means what is
    not yet decoded, so the rule here is the one that is certain: zero is blocked.
    """
    blocked: set[tuple[int, int]] = set()
    if not nav or "walkable_b64" not in nav:
        return blocked
    raw = base64.b64decode(nav["walkable_b64"])
    nw, nh = int(nav.get("width") or 0), int(nav.get("height") or 0)
    if not nw or not nh or len(raw) < nw * nh:
        return blocked
    # a board cell is blocked when its nav footprint is mostly blocked: the board is coarser than the
    # nav grid, so the majority of the cells under it decides, and a sliver does not close a lane
    for by in range(height):
        for bx in range(width):
            x0, x1 = int(bx * nw / width), max(int(bx * nw / width) + 1, int((bx + 1) * nw / width))
            y0, y1 = int(by * nh / height), max(int(by * nh / height) + 1, int((by + 1) * nh / height))
            total = blocked_here = 0
            for ny in range(y0, min(y1, nh)):
                row = ny * nw
                for nx in range(x0, min(x1, nw)):
                    total += 1
                    if raw[row + nx] == 0:
                        blocked_here += 1
            if total and blocked_here / total >= 0.5:
                blocked.add((bx, by))
    return blocked


def board_centre(entities: list[dict], nav: dict | None) -> tuple[float, float]:
    """Where a board should look: the centroid of the props the map actually placed.

    A board is a window, and the window has to be over the authored action. The prop centroid is
    measured, not chosen: it is where the map's cover is.
    """
    pts = [(e["pos"][0], e["pos"][2]) for e in entities
           if "blockers" not in (e.get("blueprint") or "")]
    if not pts:
        return 0.0, 0.0
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def convert(map_json: Path, kit_names: list[str], width: int, height: int,
            name: str | None = None, decal_names: set[str] | None = None,
            a_terrain_dir: Path | None = None,
            override_centre: tuple[float, float] | None = None) -> dict:
    decal_names = decal_names or set()
    data = json.loads(map_json.read_text())
    terrain = data.get("terrain") or {}
    nav = data.get("nav") or {}
    centre = board_centre(data.get("entities") or [], nav)
    if override_centre is not None:
        centre = override_centre
    layout = {
        "name": name or data.get("map", map_json.stem),
        "biome": "",
        "ground": "",
        "size": {"width": width, "height": height},
        "paint": {},
        "props": [],
        "decals": [],
        "heights": board_heights(terrain, nav, width, height, centre),
        "source": {
            "map": data.get("map"),
            "terrain": {"width": terrain.get("width"), "height": terrain.get("height"),
                        "tile_world_scale": terrain.get("tile_world_scale"),
                        "min_height": terrain.get("min_height"),
                        "max_height": terrain.get("max_height")},
            "layers": [l["surface"] for l in (terrain.get("layers") or [])],
            "nav": data.get("nav"),
            "placements": len(data.get("entities") or []),
            "relief": {"source_m": round(float(terrain.get("max_height") or 0.0)
                                         - float(terrain.get("min_height") or 0.0), 2),
                       "board_steps": MAX_RELIEF_STEPS,
                       "board_m": round(MAX_RELIEF_STEPS * ELEVATION_STEP, 2)},
            "window": {"centre_m": [round(centre[0], 1), round(centre[1], 1)],
                       "size_m": [width * TILE_SIZE, height * TILE_SIZE],
                       "scale": "1:1 (a board is a window into the map, not the map squashed)"},
        },
    }
    # biome from the props the map places most
    from collections import Counter
    biomes = Counter()
    for entity in data.get("entities") or []:
        blueprint = entity.get("blueprint") or ""
        for segment, biome in (("desert_objects", "desert"), ("desert_terrain", "desert"),
                               ("ice_objects", "ice"), ("ice_terrain", "ice"),
                               ("jungle_objects", "jungle"), ("jungle_terrain", "jungle"),
                               ("urban_objects", "urban"), ("urban_terrain", "urban"),
                               ("volcanic_objects", "volcanic"), ("volcanic terrain", "volcanic"),
                               ("spacehulk", "spacehulk"), ("military_objects", "military"),
                               ("industrial_objects", "industrial"), ("rubble", "ruins")):
            if segment in blueprint:
                biomes[biome] += 1
                break
    layout["biome"] = biomes.most_common(1)[0][0] if biomes else "desert"

    # the game's own passability becomes the layout's paint, so an imported map carries its walkable
    # shape instead of an empty board
    for bx, by in sorted(nav_blocked(data.get("nav"), width, height)):
        layout["paint"][f"{bx},{by}"] = "impassable"

    # placements: blueprint -> kit prop, snapped to the board
    stats: dict[str, int] = {"exact": 0, "token": 0, "gameplay": 0, "skipped": 0, "none": 0}
    unresolved: dict[str, int] = {}
    for entity in data.get("entities") or []:
        blueprint = (entity.get("blueprint") or "").replace("\\", "/")
        if "world_objects" not in blueprint and "structures" not in blueprint:
            continue
        stem = blueprint.rstrip("/").split("/")[-1].lower()
        if "world_objects/gameplay" in blueprint:
            prop, how = gameplay_prop(blueprint, kit_names)
            if how == "skip":
                stats["skipped"] = stats.get("skipped", 0) + 1
                continue
        else:
            prop, how = nearest_prop(stem, kit_names)
        if prop is None:
            stats["none"] += 1
            unresolved[stem] = unresolved.get(stem, 0) + 1
            continue
        stats[how] = stats.get(how, 0) + 1
        pos = entity.get("pos") or [0, 0, 0]
        # 1:1 windowing: a board cell is a real 2 m square of the map, so the board carries the
        # density the map has (~26 props on a 24x20 board, measured) instead of squeezing a 256 m
        # map into it, which produced 172 props and a 6.6x overdensity.
        x = int(round((pos[0] - centre[0]) / TILE_SIZE + (width - 1) / 2))
        y = int(round((pos[2] - centre[1]) / TILE_SIZE + (height - 1) / 2))
        if not (0 <= x < width and 0 <= y < height):
            continue
        layout["props"].append({
            "name": prop,
            "biome": layout["biome"],
            "x": x,
            "y": y,
            "rot": 0,
            "elev": 0,
        })
    layout["source"]["placement_resolution"] = {
        **stats,
        "unresolved_top": sorted(unresolved.items(), key=lambda kv: -kv[1])[:12],
    }
    # decals inside the window: the painted ground layer (craters, stains, road markings, snow
    # patches). Positions are continuous, so they are stored in cell units as floats rather than
    # snapped to the grid.
    decal_stats = {"total": 0, "kept": 0, "unresolved": 0}
    for decal in data.get("decals") or []:
        decal_stats["total"] += 1
        cx = (decal.get("x") or 0.0) - centre[0]
        cz = (decal.get("z") or 0.0) - centre[1]
        bx = cx / TILE_SIZE + (width - 1) / 2
        by = cz / TILE_SIZE + (height - 1) / 2
        span = max(decal.get("size") or [1.0, 1.0])
        # a decal is kept when its own footprint reaches into the board
        margin = span / (2 * TILE_SIZE)
        if not (-margin <= bx <= width - 1 + margin and -margin <= by <= height - 1 + margin):
            continue
        if decal.get("name") not in decal_names:
            decal_stats["unresolved"] += 1
            continue
        decal_stats["kept"] += 1
        layout["decals"].append({
            "name": decal["name"],
            "x": round(bx, 3),
            "y": round(by, 3),
            "size": [round(float(decal["size"][0]), 2), round(float(decal["size"][1]), 2)],
            "rot": round(float(decal.get("rot") or 0.0), 3),
        })
    layout["source"]["decals"] = decal_stats

    # the map's own ground: eight layers and two masks, so the board renders the ground it stands on
    # rather than one tiled texture per biome
    terrain_manifest = Path(a_terrain_dir) / map_json.stem / "terrain.json" if a_terrain_dir else None
    if terrain_manifest and terrain_manifest.is_file():
        try:
            layout["terrain"] = json.loads(terrain_manifest.read_text())
        except json.JSONDecodeError:
            pass

    # one prop per cell, as the forge's model requires
    seen = {}
    for prop in layout["props"]:
        seen[(prop["x"], prop["y"])] = prop
    layout["props"] = sorted(seen.values(), key=lambda p: (p["y"], p["x"]))
    return layout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=Path, required=True, help="decoded map JSON directory")
    ap.add_argument("--kit", type=Path, required=True, help="env_kit.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--centre", default=None,
                    help="board centre in map metres, 'x,z' (default: the map's prop centroid). Use it "
                         "to put the window over a feature — a vista piece, a landmark, a bridge.")
    ap.add_argument("--terrain", type=Path, default=None,
                    help="terrain bundle directory (default: beside the kit, ../maps/terrain)")
    ap.add_argument("--width", type=int, default=24)
    ap.add_argument("--height", type=int, default=20)
    a = ap.parse_args(argv)
    kit = json.loads(a.kit.read_text())
    # Board props only: `vista_*` entries are the distant scenery layer (measured: rock_pile_long_01
    # is 17 x 11.8 x 26.9 m), and placing one as map dressing puts a monolith in the middle of a
    # 40 m board.
    kit_names = sorted({p["name"].lower() for p in kit["props"]})
    # the decal palette lives beside the kit, in the game's public assets
    # the kit is at <assets>/models/env/env_kit.json, so the terrain bundles are two levels up
    terrain_dir = a.terrain or (Path(a.kit).parents[2] / "maps" / "terrain")
    decal_names: set[str] = set()
    decal_manifest = Path(a.kit).parents[2] / "decals" / "decal_kit.json"
    if decal_manifest.is_file():
        decal_names = {d["name"] for d in json.loads(decal_manifest.read_text()).get("decals", [])}
    maps = sorted(a.maps.glob("*.json"))
    if a.only:
        maps = [m for m in maps if m.stem in a.only]
    elif a.limit:
        maps = maps[:a.limit]
    if not maps:
        raise SystemExit("no decoded maps found")
    a.out.mkdir(parents=True, exist_ok=True)
    index = []
    for map_json in maps:
        override = None
        if a.centre:
            ox, oz = (float(v) for v in a.centre.split(","))
            override = (ox, oz)
        layout = convert(map_json, kit_names, a.width, a.height, decal_names=decal_names,
                         a_terrain_dir=terrain_dir, override_centre=override)
        dest = a.out / f"shipped_{map_json.stem}{'_centred' if a.centre else ''}.json"
        dest.write_text(json.dumps(layout, indent=1))
        index.append({"file": dest.name, "map": layout["name"], "biome": layout["biome"],
                      "props": len(layout["props"]), "source": layout["source"]})
        res = layout["source"]["placement_resolution"]
        total = res["exact"] + res["token"] + res.get("gameplay", 0) + res["none"]
        print(f"{layout['name']:40s} {layout['biome']:9s} props {len(layout['props']):4d} "
              f"resolved {res['exact']} exact + {res['token']} token + "
              f"{res.get('gameplay', 0)} gameplay / {total} "
              f"({100 * (res['exact'] + res['token']) // max(1, total)}%)")
    # merge into the existing index so a single-map run (--only, --centre) does not drop the others
    index_path = a.out / "shipped_index.json"
    merged: dict[str, dict] = {}
    if index_path.is_file():
        try:
            for entry in json.loads(index_path.read_text()).get("maps", []):
                merged[entry["file"]] = entry
        except (json.JSONDecodeError, KeyError):
            merged = {}
    for entry in index:
        merged[entry["file"]] = entry
    index_path.write_text(json.dumps({"maps": sorted(merged.values(), key=lambda e: e["file"])}, indent=1))
    print(f"{len(index)} layouts -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
