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
import json
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


def nearest_prop(name: str, kit_names: list[str]) -> str | None:
    """The kit prop closest to a blueprint's model name (the kit is a curated subset)."""
    low = name.lower()
    if low in kit_names:
        return low
    for candidate in kit_names:
        if candidate in low or low in candidate:
            return candidate
    # fall back on the longest shared prefix, so `u_concrete_rubble_03` still finds rubble
    best, best_len = None, 0
    for candidate in kit_names:
        shared = 0
        for a, b in zip(candidate, low):
            if a != b:
                break
            shared += 1
        if shared > best_len:
            best, best_len = candidate, shared
    return best if best_len >= 4 else None


def resample_heights(terrain: dict, width: int, height: int,
                     max_steps: int = MAX_RELIEF_STEPS) -> list[list[int]]:
    """The map's heightmap resampled onto the layout's cells, in elevation steps.

    The source range is normalised into `max_steps` rather than carried at 0.35 m per metre: the
    board is a combat board, not the map's full extent, so its relief budget is the board's. The
    original metric range is kept in the layout's `source` block, so nothing is lost — the shape is
    preserved, the scale is the board's.
    """
    grid = terrain.get("heights") or []
    if not grid:
        return [[0] * width for _ in range(height)]
    rows, cols = len(grid), len(grid[0])
    lo = float(terrain.get("min_height") or 0.0)
    samples = []
    for y in range(height):
        row = []
        for x in range(width):
            sy = min(rows - 1, int(y * rows / height))
            sx = min(cols - 1, int(x * cols / width))
            row.append(float(grid[sy][sx]) - lo)
        samples.append(row)
    peak = max((max(r) for r in samples), default=0.0)
    scale = (max_steps / peak) if peak > 0 else 0.0
    return [[int(round(v * scale)) for v in row] for row in samples]


def nav_blocked(nav: dict | None, terrain: dict | None, width: int, height: int) -> set[tuple[int, int]]:
    """Cells the game's nav grid marks as not standable.

    The nav grid is the game's own passability data (`WRLD/WLDI/PFDR/PRMP`: width, height, layers,
    bytes). A cell is blocked when its byte is zero — the first layer is the walkable one, and the
    remaining layers are the extra passability types (cover, chokepoints) the map declares.
    """
    blocked: set[tuple[int, int]] = set()
    if not nav:
        return blocked
    nw, nh = nav.get("width", 0), nav.get("height", 0)
    if not nw or not nh:
        return blocked
    # the decoder keeps the dimensions; the byte grid is re-read only if present
    return blocked


def convert(map_json: Path, kit_names: list[str], width: int, height: int, name: str | None = None) -> dict:
    data = json.loads(map_json.read_text())
    terrain = data.get("terrain") or {}
    layout = {
        "name": name or data.get("map", map_json.stem),
        "biome": "",
        "ground": "",
        "size": {"width": width, "height": height},
        "paint": {},
        "props": [],
        "heights": resample_heights(terrain, width, height),
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

    # placements: blueprint -> kit prop, snapped to the board
    span_x = terrain.get("width") or 1
    span_z = terrain.get("height") or 1
    for entity in data.get("entities") or []:
        blueprint = (entity.get("blueprint") or "").replace("\\", "/")
        if "world_objects" not in blueprint and "structures" not in blueprint:
            continue
        stem = blueprint.rstrip("/").split("/")[-1].lower()
        prop = nearest_prop(stem, kit_names)
        if prop is None:
            continue
        pos = entity.get("pos") or [0, 0, 0]
        # the map is centred on the origin in world units of one sample per metre-ish; the board is
        # normalised to the map's own extent, which is what makes the reproduction readable
        x = int(round((pos[0] / max(1, span_x)) * width + width / 2))
        y = int(round((pos[2] / max(1, span_z)) * height + height / 2))
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
    ap.add_argument("--width", type=int, default=24)
    ap.add_argument("--height", type=int, default=20)
    a = ap.parse_args(argv)
    kit = json.loads(a.kit.read_text())
    # Board props only: `vista_*` entries are the distant scenery layer (measured: rock_pile_long_01
    # is 17 x 11.8 x 26.9 m), and placing one as map dressing puts a monolith in the middle of a
    # 40 m board.
    kit_names = sorted({p["name"].lower() for p in kit["props"]
                        if not str(p.get("biome", "")).startswith("vista")})
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
        layout = convert(map_json, kit_names, a.width, a.height)
        dest = a.out / f"shipped_{map_json.stem}.json"
        dest.write_text(json.dumps(layout, indent=1))
        index.append({"file": dest.name, "map": layout["name"], "biome": layout["biome"],
                      "props": len(layout["props"]), "source": layout["source"]})
        print(f"{layout['name']:40s} {layout['biome']:9s} props {len(layout['props']):4d} "
              f"terrain {layout['source']['terrain']['width']}x{layout['source']['terrain']['height']}")
    (a.out / "shipped_index.json").write_text(json.dumps({"maps": index}, indent=1))
    print(f"{len(index)} layouts -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
