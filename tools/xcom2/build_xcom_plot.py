#!/usr/bin/env python3
"""Build a board out of the reference game's own parts, in its own module grammar.

This is the "copy the map, then work backwards" step made literal. The reference ships its environment as
modular kits on a 0.96 m grid — `BLDGKit_Wall_x06_A_FRAC` is 5.76 m wide and 2.56 m tall, its windows are
0.96 m and 1.92 m wide, its boulevard modules are 16x16 and 16x08 tiles — and its plots are assembled from
those modules along a road network. This tool lays those same modules out on a road plan and writes the
board document our engine already loads, so the board on screen is built from the reference's parts.

No generated geometry, no invented pieces: every prop placed here has `source: xcom2` in the kit.

Usage:
    python3 tools/xcom2/build_xcom_plot.py --out <game>/frontend/public/assets/maps/staged/xcom_boulevard_1.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT.parent / "Imperium-of-Ash"
ASSETS = GAME / "frontend/public/assets"
KIT = ASSETS / "models/env/env_kit.json"

CELL_M = 2.0           # our board cell
MODULE_M = 0.96        # the reference's tile: every kit piece is a multiple of it
ROAD_W = 7.68          # 16x08 boulevard module: 8 tiles of carriageway
LOT_W = 15.36          # 16 tiles, the width of a 16x16 module
LOT_D = 12.48          # 13 tiles deep
BOARD_CELLS = 36       # 72 m
STOREYS = 2            # wall modules stacked into a two-storey shell


def load_pieces() -> dict[str, dict]:
    kit = json.loads(KIT.read_text())
    return {p["name"]: p for p in kit["props"] if p.get("source") == "xcom2"}


def pick(pieces: dict[str, dict], pattern: list[str], *, height: tuple[float, float] | None = None,
         width: tuple[float, float] | None = None) -> list[dict]:
    out = []
    for p in pieces.values():
        mesh = p["name"].split("__")[-1].lower()
        if not all(k.lower() in mesh for k in pattern):
            continue
        w, d, h = p["size"]
        if height and not (height[0] <= h <= height[1]):
            continue
        if width and not (width[0] <= max(w, d) <= width[1]):
            continue
        out.append(p)
    out.sort(key=lambda p: max(p["size"][0], p["size"][1]))
    return out


def place(props: list[dict], name: str, x: float, z: float, rot: float = 0.0, y: float = 0.0) -> None:
    c, s = math.cos(rot), math.sin(rot)
    props.append({
        "name": name,
        "biome": "urban",
        "pos": [round(x, 3), round(y, 3), round(z, 3)],
        "basis": [round(c, 6), 0, round(s, 6), 0, 1, 0, round(-s, 6), 0, round(c, 6)],
        "scale": 1,
        "xcom": True,
    })


def wall_run(props: list[dict], walls: list[dict], x0: float, z0: float, x1: float, z1: float,
             gaps: list[tuple[float, float]] = ()) -> None:
    """Lay wall modules edge to edge along a line, leaving doorways where `gaps` says (fractions)."""
    run = math.hypot(x1 - x0, z1 - z0)
    if run < MODULE_M:
        return
    rot = math.atan2(z1 - z0, x1 - x0)
    cursor = 0.0
    while cursor < run - 0.05:
        t = cursor / run
        if any(a <= t <= b for a, b in gaps):
            cursor += MODULE_M
            continue
        remaining = run - cursor
        pool = [w for w in walls if max(w["size"][0], w["size"][1]) <= remaining + 0.01]
        piece = pool[-1] if pool else walls[0]
        width = min(max(piece["size"][0], piece["size"][1]), remaining)
        mid = cursor + width / 2
        px = x0 + (x1 - x0) * (mid / run)
        pz = z0 + (z1 - z0) * (mid / run)
        # A wall module is one storey (2.56 m). A building is two or three, so the courses are stacked:
        # a single course on a 15 m lot reads as a paddock, not as a building.
        height = piece["size"][2] or 2.56
        for storey in range(STOREYS):
            place(props, piece["name"], px, pz, rot, y=round(storey * height, 3))
        cursor += width


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--catalogue", default=None)
    args = ap.parse_args()

    pieces = load_pieces()
    if not pieces:
        raise SystemExit("no imported pieces in the kit: run tools/xcom2/import_pieces.py first")

    # A shell is built from solid wall modules. The kit also ships window walls, and a lot whose whole
    # perimeter is windows reads as a fence of glass: solids first, windows placed deliberately.
    solid = [w for w in pick(pieces, ["wall"], height=(2.0, 3.2), width=(0.9, 6.0))
             if "wndw" not in w["name"].lower()]
    walls = solid or pick(pieces, ["wall"], height=(2.0, 3.2), width=(0.9, 6.0))
    windows = pick(pieces, ["wndw"], width=(0.9, 2.2))
    floors = pick(pieces, ["floor"])
    roofs = pick(pieces, ["roof"])
    trim_low = pick(pieces, ["trim", "locov"])
    roads = {p["name"]: p for p in pieces.values() if p["name"].startswith("cty_blvd")}
    furniture_low = [p for p in pieces.values() if p.get("cover") == "low"]
    furniture_high = [p for p in pieces.values() if p.get("cover") == "high"]

    gw = gh = BOARD_CELLS
    bw = bh = gw * CELL_M
    paint = {f"{x},{y}": "impassable" for y in range(gh) for x in range(gw)}
    cover: dict[str, str] = {}
    props: list[dict] = []

    def walk(x0: float, z0: float, x1: float, z1: float) -> None:
        for cy in range(gh):
            for cx in range(gw):
                wx = cx * CELL_M - bw / 2 + CELL_M / 2
                wz = cy * CELL_M - bh / 2 + CELL_M / 2
                if x0 <= wx <= x1 and z0 <= wz <= z1:
                    paint[f"{cx},{cy}"] = "normal"

    # ---- the boulevard: the reference's own road modules, edge to edge, with a T at the east end
    road_y = -ROAD_W / 2
    x = -bw / 2 + 4
    straight = roads.get("cty_blvd_str_16x08_01") or next(iter(roads.values()))
    straight_w = max(straight["size"][0], straight["size"][1])
    placed_roads = 0
    while x + straight_w <= bw / 2 - 4 and placed_roads < 4:
        place(props, straight["name"], x + straight_w / 2, 0.0)
        x += straight_w
        placed_roads += 1
    walk(-bw / 2 + 4, road_y, x, ROAD_W / 2)

    # ---- lots either side: the reference's modular walls, windows on the street face, a door gap
    lot_x = -bw / 2 + 4
    lots = []
    while lot_x + LOT_W <= bw / 2 - 4:
        for side, sgn in (("north", -1), ("south", 1)):
            z0 = sgn * (ROAD_W / 2 + 0.2)
            z1 = sgn * (ROAD_W / 2 + LOT_D)
            zs, ze = min(z0, z1), max(z0, z1)
            # shell: four walls, door on the street side, windows either side of it
            wall_run(props, walls, lot_x, z0, lot_x + LOT_W, z0, gaps=[(0.42, 0.58)])
            wall_run(props, walls, lot_x, z1, lot_x + LOT_W, z1)
            wall_run(props, walls, lot_x, zs, lot_x, ze)
            wall_run(props, walls, lot_x + LOT_W, zs, lot_x + LOT_W, ze)
            if windows:
                for t in (0.2, 0.32, 0.68, 0.8):
                    w = windows[t % len(windows)] if isinstance(t, int) else windows[int(t * 10) % len(windows)]
                    place(props, w["name"], lot_x + LOT_W * t, z0, 0.0)
            # floor inside the lot, and a roof on top: a shell with neither reads as a fence
            if floors:
                floor = min(floors, key=lambda p: abs(max(p["size"][0], p["size"][1]) - LOT_W))
                place(props, floor["name"], lot_x + LOT_W / 2, (z0 + z1) / 2, y=0.02)
            # A roof is assembled from modules, not dropped as one cap: the kit's roof pieces are 5-6 m
            # and a lot is 15 m, so a single cap read as a floating slab. Roofs come back once the cap is
            # tiled from the kit; the floor stays, because a room needs one.
            walk(lot_x + 0.6, zs + 0.6, lot_x + LOT_W - 0.6, ze - 0.6)
            lots.append((lot_x, z0, z1))
        lot_x += LOT_W

    # ---- cover on the kerb: the reference's own low and high cover pieces, alternating
    kerb_z = [ROAD_W / 2 + 0.35, -ROAD_W / 2 - 0.35]
    for i, kx in enumerate(range(int(-bw / 2 + 5), int(bw / 2 - 5), 3)):
        pool = furniture_low if i % 3 else (furniture_high or furniture_low)
        if not pool:
            break
        piece = pool[i % len(pool)]
        z = kerb_z[i % 2]
        place(props, piece["name"], float(kx), z)
        cx = int((kx + bw / 2) // CELL_M)
        cy = int((z + bh / 2) // CELL_M)
        if 0 <= cx < gw and 0 <= cy < gh and paint[f"{cx},{cy}"] == "normal":
            cover[f"{cx},{cy}"] = "light_cover" if piece.get("cover") == "low" else "cover"

    if trim_low:
        for i, tx in enumerate(range(int(-bw / 2 + 6), int(bw / 2 - 6), 6)):
            place(props, trim_low[i % len(trim_low)]["name"], float(tx), kerb_z[i % 2])

    board = {
        "name": "reference boulevard",
        "biome": "urban",
        "ground": "4p_desertshowdown",
        "size": {"width": gw, "height": gh},
        "paint": paint,
        "heights": [[0] * gw for _ in range(gh)],
        "rooms": [],
        "props": [],
        "free_props": props,
        "decals": [],
        "terrain": None,
        "light": {"azimuthDeg": 215, "elevationDeg": 52, "colour": "#ffe6c2", "intensity": 3.4,
                  "sky": "#dfe4ea", "ground": "#4a4238", "ambient": 0.9},
        "deployment": {"player": {"x": 4, "y": gh // 2 - 2, "w": 3, "h": 3},
                       "enemy": {"x": gw - 7, "y": gh // 2 - 2, "w": 3, "h": 3}},
        "cover": cover,
        "source": {
            "kind": "xcom-plot",
            "kit": "xcom2",
            "module_m": MODULE_M,
            "road_width_m": ROAD_W,
            "lot_m": [LOT_W, LOT_D],
            "lots": len(lots),
            "metrics": {
                "props": len(props),
                "cover_pieces": len(cover),
                "cover_per_100m2": round(len(cover) / (bw * bh) * 100, 2),
            },
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(board))
    m = board["source"]["metrics"]
    print(f"wrote {out.name}: {len(props)} pieces from the reference kit, {len(lots)} lots, "
          f"cover {m['cover_per_100m2']}/100m2, {gw}x{gh} cells")

    if args.catalogue:
        cat_path = Path(args.catalogue)
        cat = json.loads(cat_path.read_text())
        entry = {
            "id": out.stem, "kind": "xcom-plot", "biome": "urban", "seed": 0,
            "size": board["size"], "file": out.name,
            "metrics": {"props": len(props),
                        "densityPer100m2": round(100.0 * len(props) / (bw * bh), 2),
                        "coverPer100m2": m["cover_per_100m2"], "coverTarget": m["cover_per_100m2"],
                        "dispersion": 0},
        }
        cat["entries"] = [e for e in cat.get("entries", []) if e.get("id") != entry["id"]] + [entry]
        cat_path.write_text(json.dumps(cat, indent=1))


if __name__ == "__main__":
    main()
