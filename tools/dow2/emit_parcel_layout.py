#!/usr/bin/env python3
"""Emit a solved parcel board as a staged board the game can load.

The board is the product's unit of play: a lattice of parcels cut from one shipped map, each at the
transforms that map recorded. This tool turns a solved board into the staged-layout document the
game already understands — cells, cover, light, deployment, ground — plus `free_props`, the authored
placements at 1:1.

Two measurements matter here and both come from the source data, never from a guess:

* **Seating.** A source placement carries the map's absolute altitude, and a board is assembled from
  nine different places at nine different altitudes. Each parcel is seated on its own dominant floor
  level (the mode of its placements' heights), which keeps the piece's internal relief — wall tops
  stay above the courtyard — while putting the floor the place is played on at the board's zero.
* **Footprint.** A parcel's walkable cells are read from the map's own nav grid, so an impassable
  cell in the game is a cell the shipped map says a unit cannot stand on.

Usage:
    python3 -u tools/dow2/emit_parcel_layout.py --boards output/source_lab/boards_dense3.json \
        --seed 0 --out <game>/frontend/public/assets/maps/staged/parcel_<map>_<seed>.json
"""
from __future__ import annotations

import argparse
import base64
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CELL_M = 2.0  # the game's grid; a cell is 2 m on every axis
ELEVATION_STEP = 0.35  # the game's elevation step, in metres (three/gridMath.ts)


def load_map(maps: Path, name: str) -> dict:
    return json.loads((maps / f"{name}.json").read_text())


def seat_base(ground_samples: list[float]) -> float:
    """The level a piece is seated on: the median ground height under it.

    The ground, not the props: a prop's stored altitude is its height in the map, so subtracting the
    ground beneath the piece leaves its true height above that ground (a wall walk stays 10 m up, a
    boulder stays on the floor). Seating on the props' own mode instead made the terrain under a
    piece read as a 24 m pit whenever the props happened to stand on a roof.
    """
    if not ground_samples:
        return 0.0
    ordered = sorted(ground_samples)
    return ordered[len(ordered) // 2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boards", default=str(ROOT / "output/source_lab/boards_dense3.json"))
    ap.add_argument("--parcels", default=str(ROOT / "output/source_lab/parcels_xcom.json"))
    ap.add_argument("--maps", default=str(ROOT / "output/source_lab/maps"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--light", default=None,
                    help="JSON light rig to bake; defaults to a daylight rig")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    boards = json.loads(Path(args.boards).read_text())["boards"]
    board = next((b for b in boards if b["seed"] == args.seed), None)
    if board is None:
        raise SystemExit(f"no board with seed {args.seed} in {args.boards}")
    catalogue = {p["id"]: p for p in json.loads(Path(args.parcels).read_text())["catalogue"]}
    mp = load_map(Path(args.maps), board["map"])
    nav_w, nav_h = int(mp["nav"]["width"]), int(mp["nav"]["height"])
    raw = np.frombuffer(base64.b64decode(mp["nav"]["walkable_b64"]), dtype=np.uint8)
    walk = raw[: nav_w * nav_h].reshape(nav_h, nav_w) > 0
    props = mp.get("props") or []
    placements = [p for p in (mp.get("placements") or []) if p.get("pos") and len(p["pos"]) >= 3]

    cols, rows = board["cols"], board["rows"]
    slot = int(board["parcels"][0]["size_xy"][0])
    bw, bh = cols * slot, rows * slot
    gw, gh = int(bw / CELL_M), int(bh / CELL_M)
    cells_per_parcel = int(slot / CELL_M)

    paint: dict[str, str] = {}
    cover: dict[str, str] = {}
    free_props: list[dict] = []
    seat_report: list[dict] = []
    # the board's relief, in elevation steps, taken from the map's own heightfield. The terrain is
    # centred on its own extent (`terrain.width` metres), not on the nav grid: sampling it at nav
    # coordinates measures a correlation of -0.06 against where the props actually stand, and that
    # reads as "the heightfield is unrelated to the ground", which is false.
    heights = [[0] * gw for _ in range(gh)]
    terrain_meta = mp.get("terrain") or {}
    H = terrain_meta.get("heights") or []
    stride_m = float(terrain_meta.get("stride") or 8)
    span_m = float(terrain_meta.get("width") or 0)
    relief_samples: list[float] = []
    seat_error: list[float] = []

    for pl in board["parcels"]:
        c, r = pl["slot"]
        parcel = catalogue[pl["id"]]
        x0, y0 = parcel["origin"]
        w, h = parcel["size_xy"]
        # the ground under this piece, sampled on a 2 m lattice: it is both the piece's datum and
        # the relief the board carries
        ground_samples = []
        cell_ground = {}
        for gy in range(r * cells_per_parcel, (r + 1) * cells_per_parcel):
            for gx in range(c * cells_per_parcel, (c + 1) * cells_per_parcel):
                mx = x0 + (gx - c * cells_per_parcel + 0.5) * CELL_M - nav_w / 2
                mz = y0 + (gy - r * cells_per_parcel + 0.5) * CELL_M - nav_h / 2
                if H and span_m > 0:
                    sx = int((mx + span_m / 2) / stride_m)
                    sz = int((mz + span_m / 2) / stride_m)
                    if 0 <= sz < len(H) and 0 <= sx < len(H[0]):
                        ground_samples.append(float(H[sz][sx]))
                        cell_ground[(gx, gy)] = float(H[sz][sx])

        # the placements inside this piece, and the level it is played at
        inside = []
        for q in placements:
            nx, ny = q["pos"][0] + nav_w / 2, q["pos"][2] + nav_h / 2
            if x0 <= nx < x0 + w and y0 <= ny < y0 + h:
                k = q.get("kind")
                if isinstance(k, int) and 0 <= k < len(props):
                    inside.append(q)
        base = seat_base(ground_samples)
        seat_report.append({"parcel": pl["id"], "props": len(inside), "base": round(base, 2)})

        # relief: the shipped ground under each cell of this piece, against the same datum the props
        # are seated on, so the terrain and the pieces on it stay in one frame
        for (gx, gy), ground in cell_ground.items():
            heights[gy][gx] = round((ground - base) / ELEVATION_STEP)
            relief_samples.append(ground - base)

        # walkability, read from the shipped nav grid at the cell resolution the game plays on
        for gy in range(r * cells_per_parcel, (r + 1) * cells_per_parcel):
            for gx in range(c * cells_per_parcel, (c + 1) * cells_per_parcel):
                nx = x0 + (gx - c * cells_per_parcel) * int(CELL_M)
                ny = y0 + (gy - r * cells_per_parcel) * int(CELL_M)
                patch = walk[ny:ny + int(CELL_M), nx:nx + int(CELL_M)]
                blocked = patch.size == 0 or patch.mean() < 0.5
                paint[f"{gx},{gy}"] = "impassable" if blocked else "normal"

        # board-space transform: the parcel's slot centre, minus its own centre in the map
        cx = (c + 0.5) * slot - bw / 2
        cz = (r + 0.5) * slot - bh / 2
        px = x0 + w / 2 - nav_w / 2
        pz = y0 + h / 2 - nav_h / 2
        # A piece can hold more than one level (a courtyard under a wall walk). Seating on the mode
        # alone buries the lower level under the board, where nothing renders. So the piece is seated
        # on the mode and then lifted by however much its lowest piece would have sunk: relief is
        # preserved, and no authored prop is hidden below the floor.
        offsets = [q["pos"][1] - base for q in inside]
        lift = max(0.0, -min(offsets)) if offsets else 0.0
        seat_report[-1]["lift"] = round(lift, 2)
        for q in inside:
            k = q["kind"]
            # the gate on seating: a prop's height above the ground under it. The source places props
            # on the ground, so a large error means the datum is wrong, not the prop.
            gx_p = int((cx + (q["pos"][0] - px) + bw / 2) // CELL_M)
            gz_p = int((cz + (q["pos"][2] - pz) + bh / 2) // CELL_M)
            ground_here = cell_ground.get((gx_p, gz_p))
            if ground_here is not None:
                seat_error.append(abs((q["pos"][1] - base + lift) - (ground_here - base)))
            free_props.append({
                "name": props[k]["prop"],
                "biome": props[k].get("biome") or "",
                "pos": [round(cx + (q["pos"][0] - px), 3),
                        round(q["pos"][1] - base + lift, 3),
                        round(cz + (q["pos"][2] - pz), 3)],
                "basis": q.get("basis"),
                "scale": q.get("scale") or 1,
            })

    # cover cells under the pieces that ship a cover tier, so the rules and the HUD agree with what
    # is drawn rather than with a separate, generated cover map
    families = json.loads((ROOT / "output/source_lab/env_families.json").read_text()) \
        if (ROOT / "output/source_lab/env_families.json").exists() else {"pieces": []}
    tier_of = {p["name"]: p.get("cover") for p in families.get("pieces", []) if p.get("cover")}
    tier_cell = {"low": "light_cover", "high": "cover", "climb": "heavy_cover"}
    for fp in free_props:
        name = tier_cell.get(tier_of.get(fp["name"]) or "")
        if not name:
            continue
        gx = int((fp["pos"][0] + bw / 2) // CELL_M)
        gy = int((fp["pos"][2] + bh / 2) // CELL_M)
        if 0 <= gx < gw and 0 <= gy < gh and paint.get(f"{gx},{gy}") == "normal":
            cover[f"{gx},{gy}"] = name

    light = json.loads(args.light) if args.light else {
        "azimuthDeg": 215, "elevationDeg": 52, "colour": "#ffe6c2", "intensity": 3.4,
        "sky": "#cfd8e6", "ground": "#4a4238", "ambient": 2.2,
    }
    terrain = json.loads((ROOT.parent / "Imperium-of-Ash/frontend/public/assets/maps/terrain"
                          / board["map"] / "terrain.json").read_text())
    first = catalogue[board["parcels"][0]["id"]]
    doc = {
        "name": f"parcel board {board['map']} {args.seed}",
        "biome": next((p.get("biome") for p in props if p.get("biome")), "desert"),
        "ground": board["map"],
        "size": {"width": gw, "height": gh},
        "paint": paint,
        "heights": heights,
        "rooms": [],
        "props": [],
        "free_props": free_props,
        "decals": [],
        "terrain": terrain,
        "light": light,
        "deployment": {"player": {"x": 1, "y": gh - 4, "w": 3, "h": 2},
                       "enemy": {"x": gw - 4, "y": 1, "w": 3, "h": 2}},
        "cover": cover,
        "source": {
            "kind": "parcel-board",
            "map": board["map"],
            "seed": args.seed,
            "grid_m": CELL_M,
            "slot_m": slot,
            "parcels": [{"id": p["id"], "slot": p["slot"], "zone": p["zone"]} for p in board["parcels"]],
            "seating": seat_report,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc))
    bases = [s["base"] for s in seat_report]
    relief = (max(relief_samples) - min(relief_samples)) if relief_samples else 0.0
    steps = sorted({v for row in heights for v in row})
    err = sorted(seat_error)
    p50 = err[len(err) // 2] if err else 0.0
    p90 = err[int(len(err) * 0.9)] if err else 0.0
    print(f"seat error to ground: median {p50:.2f} m, p90 {p90:.2f} m over {len(err)} props")
    print(f"wrote {out.name}: {gw}x{gh} cells, {len(free_props)} authored props, "
          f"{len(cover)} cover cells, seat bases {min(bases):.1f}..{max(bases):.1f} m, "
          f"relief {relief:.1f} m over {len(steps)} elevation steps "
          f"({steps[0]}..{steps[-1]})")


if __name__ == "__main__":
    main()
