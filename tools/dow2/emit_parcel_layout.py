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
import math
import random
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CELL_M = 2.0  # the game's grid; a cell is 2 m on every axis
ELEVATION_STEP = 0.35  # the game's elevation step, in metres (three/gridMath.ts)
UPPER_LEVEL_STEPS = 4  # 1.4 m: one storey of the source's upper passability
CRATER_DEPTH_STEPS = 3  # 1.05 m: deep enough that the rim protects, shallow enough to climb out


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
    ap.add_argument("--name", default=None,
                    help="output stem; defaults to the board's own (parcel_<map>_<seed>)")
    ap.add_argument("--light", default=None,
                    help="JSON light rig to bake; defaults to a daylight rig")
    ap.add_argument("--out", required=True)
    ap.add_argument("--flat", action="store_true",
                    help="write a flat board; by default a piece stands on its own terrace")
    ap.add_argument("--catalogue", default=None,
                    help="upsert this board's catalogue entry (the game's index of staged boards)")
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
    # The map declares more than one passability layer, and that is the source's vertical structure: a
    # cell blocked on the ground layer and walkable on another is an upper surface -- a wall walk, a
    # bridge, a raised terrace. This is the only place a board can get a second level without inventing
    # one, so the layers are read rather than approximated.
    upper_layers = []
    for b64 in (mp["nav"].get("upper_b64") or []):
        run = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        if run.size == nav_w * nav_h:
            upper_layers.append(run.reshape(nav_h, nav_w) > 0)
    upper = np.zeros_like(walk)
    for layer in upper_layers:
        upper |= layer
    upper &= ~walk  # a cell walkable on the ground is ground; the upper layer is what is left over
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
    upper_cells: set[tuple[int, int]] = set()
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
        # Seat the piece on its own footing: the lowest thing in it touches the board. A parcel is a
        # vertical stack (a rampart stands on a wall run, a crate stands on a roof), and the map's
        # terrain is not that stack -- a building's floor is a prop, not ground. Measured against the
        # rendered ground, seating on the terrain left 99 of 124 props hanging (the stairs up to 38 m
        # in the air). The stack's own lowest piece is the only datum that stands the piece up.
        base = min((q["pos"][1] for q in inside), default=seat_base(ground_samples))
        seat_report.append({"parcel": pl["id"], "props": len(inside), "base": round(base, 2)})

        terrace = 0

        # Relief is measured but not written by default. The map's terrain is not the surface its props
        # stand on -- a building's floor is a prop, not ground -- so drawing both in one frame leaves
        # whichever datum is chosen half wrong: seating on the terrain hung 99 of 124 props in the air,
        # and seating on the piece's footing buried 43 of 121 under it. A board is flat until the rules
        # can carry a height band (docs/BOARD_3D_GRID.md 3.1); the map's own ground *texture* stays,
        # which is what makes the board read as the place.
        for (gx, gy), ground in cell_ground.items():
            relief_samples.append(ground - base)

        # walkability, read from the shipped nav grid at the cell resolution the game plays on
        for gy in range(r * cells_per_parcel, (r + 1) * cells_per_parcel):
            for gx in range(c * cells_per_parcel, (c + 1) * cells_per_parcel):
                nx = x0 + (gx - c * cells_per_parcel) * int(CELL_M)
                ny = y0 + (gy - r * cells_per_parcel) * int(CELL_M)
                patch = walk[ny:ny + int(CELL_M), nx:nx + int(CELL_M)]
                blocked = patch.size == 0 or patch.mean() < 0.5
                up = upper[ny:ny + int(CELL_M), nx:nx + int(CELL_M)]
                on_upper = up.size > 0 and up.mean() >= 0.5
                if on_upper:
                    # an upper surface is walkable, and stands a level above the ground
                    paint[f"{gx},{gy}"] = "normal"
                    upper_cells.add((gx, gy))
                else:
                    paint[f"{gx},{gy}"] = "impassable" if blocked else "normal"

        # A terrace is the relief a stack of shipped pieces can carry: the whole piece -- ground,
        # props, cover -- stands a step above the board and moves as one. The map's own heightfield is
        # not usable here (a building's floor is a prop, not terrain), and a parcel-sized plateau is
        # the smallest unit that keeps the ground and the pieces on it in the same frame.
        for (gx, gy) in [cell for cell in upper_cells if c * cells_per_parcel <= cell[0] < (c + 1) * cells_per_parcel
                         and r * cells_per_parcel <= cell[1] < (r + 1) * cells_per_parcel]:
            # `--flat` writes a truly flat board: the raised level has no ramp down, and a unit that
            # spawns on it is stranded -- measured in the game, the squad stood on a plateau with the
            # map's paving a step below and no way off. The cells are still recorded in `source` so the
            # level can be switched back on when the movement rules carry a step.
            heights[gy][gx] = 0 if args.flat else UPPER_LEVEL_STEPS
        if not args.flat and (c + r) % 3 == 1:
            terrace = 4  # 1.4 m: a raised terrace, and a real height advantage
            for gy in range(r * cells_per_parcel, (r + 1) * cells_per_parcel):
                for gx in range(c * cells_per_parcel, (c + 1) * cells_per_parcel):
                    if paint.get(f"{gx},{gy}") == "normal":
                        heights[gy][gx] = terrace

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
            # Seat each prop on the ground *under that prop*, not on the piece's median. Measured on
            # the first emitted board, seating on the median left 100 of 121 props floating (median
            # 14 m up) because a parcel can span a wall walk and the courtyard below it: the median
            # sits between the two and everything above it hangs in the air. The source places a prop
            # on the ground it was authored on (entity altitude correlates +0.741 with the heightfield
            # at 2.4 m mean error), so the prop's own local ground is the datum that makes it stand.
            gx_p = int((cx + (q["pos"][0] - px) + bw / 2) // CELL_M)
            gz_p = int((cz + (q["pos"][2] - pz) + bh / 2) // CELL_M)
            ground_here = cell_ground.get((gx_p, gz_p))
            # A prop's board height is its authored altitude minus the board's datum, and the ground
            # mesh carries the same datum: the prop then stands exactly as high above the terrain as
            # the source authored it. Seating it on the ground *under it* instead would drop every
            # prop that legitimately stands on a wall walk into the courtyard.
            y = q["pos"][1] - base + lift + terrace * ELEVATION_STEP
            if (gx_p, gz_p) in upper_cells and not args.flat:
                y += UPPER_LEVEL_STEPS * ELEVATION_STEP
            if ground_here is not None:
                seat_error.append(y - (ground_here - base))
            free_props.append({
                "name": props[k]["prop"],
                "biome": props[k].get("biome") or "",
                "pos": [round(cx + (q["pos"][0] - px), 3),
                        round(y, 3),
                        round(cz + (q["pos"][2] - pz), 3)],
                "basis": q.get("basis"),
                "scale": q.get("scale") or 1,
            })

    # ---------------------------------------------------------------- dressing a bare middle
    # A cut from a strategic map is not guaranteed to be fightable in its middle: measured on twelve
    # solved boards, the largest bare square inside the middle half was 121 m2 -- an 11 m parade ground
    # where the fight happens. The source's own vocabulary is the fix, not invented architecture: the
    # bare cells are dressed with cover pieces drawn from the same map's own inventory, at 1:1, on
    # walkable ground, spaced by the corpus interval. A dressed piece is marked, so a reviewer can see
    # what came from the map and what the board needed.
    families_path = ROOT / "output/source_lab/env_families.json"
    families = json.loads(families_path.read_text()) if families_path.exists() else {"pieces": []}
    tier_of_name = {p["name"]: p.get("cover") for p in families.get("pieces", []) if p.get("cover")}
    # Dressing has to *read* at the game's camera distance: a 0.4 m crate fills a cell on paper and is
    # a speck on screen. The kit's own sizes pick the pieces that carry mass at board scale -- 1.2 m to
    # 4 m tall -- and the cover ladder decides whether a piece is cover once it is chosen.
    sizes_path = ROOT / "output/source_lab/env_families.json"
    kit_size = {p["name"]: (p.get("size") or [0, 0, 0]) for p in families.get("pieces", [])}
    inventory = sorted({p["name"] for p in free_props})

    def reads_at_board_scale(name: str) -> bool:
        size = kit_size.get(name)
        if not size or len(size) < 3:
            return False
        height = float(size[2] or 0)
        footprint = max(float(size[0] or 0), float(size[1] or 0))
        return 1.2 <= height <= 4.0 and footprint >= 1.0

    dressable = [n for n in inventory if reads_at_board_scale(n) and tier_of_name.get(n)]
    if not dressable:
        dressable = [n for n in inventory if reads_at_board_scale(n)]
    if not dressable:
        dressable = [n for n in inventory if tier_of_name.get(n)]

    def bare_square(occupancy, lo_frac: float, hi_frac: float) -> tuple[int, int, int]:
        """The largest empty square in the middle of the board: side, and its centre in metres."""
        cells_h, cells_w = occupancy.shape
        lo_x, hi_x = int(cells_w * lo_frac), int(cells_w * hi_frac)
        lo_y, hi_y = int(cells_h * lo_frac), int(cells_h * hi_frac)
        region = occupancy[lo_y:hi_y, lo_x:hi_x]
        if region.size == 0:
            return 0, 0, 0
        dp = np.zeros(region.shape, dtype=np.int32)
        best, best_at = 0, (0, 0)
        for yy in range(region.shape[0]):
            for xx in range(region.shape[1]):
                if region[yy, xx]:
                    continue
                dp[yy, xx] = 1 + min(dp[yy - 1, xx] if yy else 0,
                                     dp[yy, xx - 1] if xx else 0,
                                     dp[yy - 1, xx - 1] if xx and yy else 0)
                if dp[yy, xx] > best:
                    best, best_at = int(dp[yy, xx]), (yy, xx)
        # the DP's corner is the square's bottom-right; its centre is half a side back from it
        cy = lo_y + best_at[0] - best // 2
        cx = lo_x + best_at[1] - best // 2
        return best, cx, cy

    # occupancy at 1 m, stamped from every authored prop's footprint (a piece covers its own cell and
    # the metre around it, which is what the eye reads as "there is something there")
    # A hole only matters where a unit can stand: 44% of a parcel board's cells are impassable, and a
    # walled-off courtyard is not a parade ground. Impassable cells count as covered, so the measure
    # is "bare ground a fight can happen on".
    occ = np.zeros((gh * 2, gw * 2), dtype=bool)
    # props alone, for "is there room here": the bare-square measure also treats impassable ground as
    # covered, but a crate can stand in an open cell beside a wall
    prop_occ = np.zeros((gh * 2, gw * 2), dtype=bool)
    for gy in range(gh):
        for gx in range(gw):
            if paint.get(f"{gx},{gy}") != "normal":
                occ[gy * 2:gy * 2 + 2, gx * 2:gx * 2 + 2] = True
    for fp in free_props:
        cx1 = int((fp["pos"][0] + bw / 2))
        cz1 = int((fp["pos"][2] + bh / 2))
        if 0 <= cx1 < occ.shape[1] and 0 <= cz1 < occ.shape[0]:
            occ[max(0, cz1 - 1):cz1 + 2, max(0, cx1 - 1):cx1 + 2] = True
            prop_occ[max(0, cz1 - 1):cz1 + 2, max(0, cx1 - 1):cx1 + 2] = True
    bare_before, _, _ = bare_square(occ, 0.10, 0.90)
    dressed = 0
    if dressable:
        # Coverage, not hole-filling: filling the single largest hole left a board with a dressed
        # middle and an empty deployment side, which is the half of the board a player looks at first.
        # A jittered lattice at the corpus spacing covers the playable area evenly, and a piece is only
        # placed where nothing is within reach.
        rng = random.Random(args.seed)
        step_m = 6.0
        step_cells = max(1, int(step_m / CELL_M))
        for gy in range(1, gh - 1, step_cells):
            for gx in range(1, gw - 1, step_cells):
                jx = min(gw - 2, max(1, gx + rng.randint(-1, 1)))
                jy = min(gh - 2, max(1, gy + rng.randint(-1, 1)))
                if paint.get(f"{jx},{jy}") != "normal":
                    continue
                # clear of anything within 3 m, so a dressed piece does not sit inside a wall
                near = False
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        tx, ty = jx + dx, jy + dy
                        if 0 <= tx < gw and 0 <= ty < gh and prop_occ[ty * 2, tx * 2]:
                            near = True
                if near:
                    continue
                name = dressable[rng.randrange(len(dressable))]
                free_props.append({
                    "name": name,
                    "biome": next((q.get("biome") for q in props if q.get("prop") == name), ""),
                    "pos": [round(jx * CELL_M - bw / 2 + CELL_M / 2, 3), 0.0,
                            round(jy * CELL_M - bh / 2 + CELL_M / 2, 3)],
                    "basis": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                    "scale": 1,
                    "dressed": True,
                })
                occ[jy * 2:jy * 2 + 2, jx * 2:jx * 2 + 2] = True
                prop_occ[jy * 2:jy * 2 + 2, jx * 2:jx * 2 + 2] = True
                dressed += 1
                if dressed >= 72:
                    break
            if dressed >= 72:
                break
    # ---------------------------------------------------------------- dressing a bare middle
    # A cut from a strategic map is not guaranteed to be fightable in its middle: measured on twelve
    # solved boards, the largest bare square inside the middle half was 121 m2 -- an 11 m parade ground
    # where the fight happens. The source's own vocabulary is the fix, not invented architecture: the
    # bare cells are dressed with cover pieces drawn from the same map's own inventory, at 1:1, on
    # walkable ground, spaced by the corpus interval. A dressed piece is marked, so a reviewer can see
    # what came from the map and what the board needed.
    families_path = ROOT / "output/source_lab/env_families.json"
    families = json.loads(families_path.read_text()) if families_path.exists() else {"pieces": []}
    tier_of_name = {p["name"]: p.get("cover") for p in families.get("pieces", []) if p.get("cover")}
    # Dressing has to *read* at the game's camera distance: a 0.4 m crate fills a cell on paper and is
    # a speck on screen. The kit's own sizes pick the pieces that carry mass at board scale -- 1.2 m to
    # 4 m tall -- and the cover ladder decides whether a piece is cover once it is chosen.
    sizes_path = ROOT / "output/source_lab/env_families.json"
    kit_size = {p["name"]: (p.get("size") or [0, 0, 0]) for p in families.get("pieces", [])}
    inventory = sorted({p["name"] for p in free_props})

    def reads_at_board_scale(name: str) -> bool:
        size = kit_size.get(name)
        if not size or len(size) < 3:
            return False
        height = float(size[2] or 0)
        footprint = max(float(size[0] or 0), float(size[1] or 0))
        return 1.2 <= height <= 4.0 and footprint >= 1.0

    dressable = [n for n in inventory if reads_at_board_scale(n) and tier_of_name.get(n)]
    if not dressable:
        dressable = [n for n in inventory if reads_at_board_scale(n)]
    if not dressable:
        dressable = [n for n in inventory if tier_of_name.get(n)]

    def bare_square(occupancy, lo_frac: float, hi_frac: float) -> tuple[int, int, int]:
        """The largest empty square in the middle of the board: side, and its centre in metres."""
        cells_h, cells_w = occupancy.shape
        lo_x, hi_x = int(cells_w * lo_frac), int(cells_w * hi_frac)
        lo_y, hi_y = int(cells_h * lo_frac), int(cells_h * hi_frac)
        region = occupancy[lo_y:hi_y, lo_x:hi_x]
        if region.size == 0:
            return 0, 0, 0
        dp = np.zeros(region.shape, dtype=np.int32)
        best, best_at = 0, (0, 0)
        for yy in range(region.shape[0]):
            for xx in range(region.shape[1]):
                if region[yy, xx]:
                    continue
                dp[yy, xx] = 1 + min(dp[yy - 1, xx] if yy else 0,
                                     dp[yy, xx - 1] if xx else 0,
                                     dp[yy - 1, xx - 1] if xx and yy else 0)
                if dp[yy, xx] > best:
                    best, best_at = int(dp[yy, xx]), (yy, xx)
        # the DP's corner is the square's bottom-right; its centre is half a side back from it
        cy = lo_y + best_at[0] - best // 2
        cx = lo_x + best_at[1] - best // 2
        return best, cx, cy

    # occupancy at 1 m, stamped from every authored prop's footprint (a piece covers its own cell and
    # the metre around it, which is what the eye reads as "there is something there")
    # A hole only matters where a unit can stand: 44% of a parcel board's cells are impassable, and a
    # walled-off courtyard is not a parade ground. Impassable cells count as covered, so the measure
    # is "bare ground a fight can happen on".
    occ = np.zeros((gh * 2, gw * 2), dtype=bool)
    # props alone, for "is there room here": the bare-square measure also treats impassable ground as
    # covered, but a crate can stand in an open cell beside a wall
    prop_occ = np.zeros((gh * 2, gw * 2), dtype=bool)
    for gy in range(gh):
        for gx in range(gw):
            if paint.get(f"{gx},{gy}") != "normal":
                occ[gy * 2:gy * 2 + 2, gx * 2:gx * 2 + 2] = True
    for fp in free_props:
        cx1 = int((fp["pos"][0] + bw / 2))
        cz1 = int((fp["pos"][2] + bh / 2))
        if 0 <= cx1 < occ.shape[1] and 0 <= cz1 < occ.shape[0]:
            occ[max(0, cz1 - 1):cz1 + 2, max(0, cx1 - 1):cx1 + 2] = True
            prop_occ[max(0, cz1 - 1):cz1 + 2, max(0, cx1 - 1):cx1 + 2] = True
    bare_before, _, _ = bare_square(occ, 0.10, 0.90)
    dressed = 0
    if dressable:
        # Coverage, not hole-filling: filling the single largest hole left a board with a dressed
        # middle and an empty deployment side, which is the half of the board a player looks at first.
        # A jittered lattice at the corpus spacing covers the playable area evenly, and a piece is only
        # placed where nothing is within reach.
        rng = random.Random(args.seed)
        step_m = 6.0
        step_cells = max(1, int(step_m / CELL_M))
        for gy in range(1, gh - 1, step_cells):
            for gx in range(1, gw - 1, step_cells):
                jx = min(gw - 2, max(1, gx + rng.randint(-1, 1)))
                jy = min(gh - 2, max(1, gy + rng.randint(-1, 1)))
                if paint.get(f"{jx},{jy}") != "normal":
                    continue
                # clear of anything within 3 m, so a dressed piece does not sit inside a wall
                near = False
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        tx, ty = jx + dx, jy + dy
                        if 0 <= tx < gw and 0 <= ty < gh and prop_occ[ty * 2, tx * 2]:
                            near = True
                if near:
                    continue
                name = dressable[rng.randrange(len(dressable))]
                free_props.append({
                    "name": name,
                    "biome": next((q.get("biome") for q in props if q.get("prop") == name), ""),
                    "pos": [round(jx * CELL_M - bw / 2 + CELL_M / 2, 3), 0.0,
                            round(jy * CELL_M - bh / 2 + CELL_M / 2, 3)],
                    "basis": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                    "scale": 1,
                    "dressed": True,
                })
                occ[jy * 2:jy * 2 + 2, jx * 2:jx * 2 + 2] = True
                prop_occ[jy * 2:jy * 2 + 2, jx * 2:jx * 2 + 2] = True
                dressed += 1
                if dressed >= 72:
                    break
            if dressed >= 72:
                break
    # Landing zones are derived from the ground, not placed at a corner: a parcel board's paint is the
    # shipped nav grid, so 44% of its cells can be impassable and a hard-coded corner zone lands on a
    # wall. A zone is a 3x2 block of walkable cells, searched from the two opposite corners inward.
    # Landing zones are derived from the ground, not placed at a corner: a parcel board's paint is the
    # shipped nav grid, so 44% of its cells can be impassable and a hard-coded corner zone lands on a
    # wall. A zone is a 3x2 block of walkable cells, searched from the two opposite corners inward.
    # The board has to be *walkable end to end*, not just walkable cell by cell. A parcel is cut from a
    # walled place, and 44% of its cells are impassable; assembled, that can leave the two deployment
    # areas in different pockets. Measured on the balance harness: eliminate missions on an authored
    # board stalled at the 60-turn cap with every soldier alive and the last enemy unreachable. So the
    # landing zones are chosen inside the largest connected walkable region, which is the region a fight
    # can actually happen in.
    def largest_component() -> set[tuple[int, int]]:
        seen: set[tuple[int, int]] = set()
        best: set[tuple[int, int]] = set()
        for y in range(gh):
            for x in range(gw):
                if (x, y) in seen or paint.get(f"{x},{y}") != "normal":
                    continue
                stack = [(x, y)]
                comp: set[tuple[int, int]] = set()
                while stack:
                    cx, cy = stack.pop()
                    if (cx, cy) in comp or not (0 <= cx < gw and 0 <= cy < gh):
                        continue
                    if paint.get(f"{cx},{cy}") != "normal":
                        continue
                    comp.add((cx, cy))
                    stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))
                seen |= comp
                if len(comp) > len(best):
                    best = comp
        return best

    walkable_main = largest_component()

    def find_zone(from_top: bool) -> dict:
        """A landing zone a fixed distance from the other side, not at the far corner.

        Measured on the campaign ladder: zones at opposite corners of a 24-cell board put the two forces
        twenty cells apart, the bot spent 40-50 turns walking, and the attrition cost it the finale. The
        reference's boards open at roughly one move of contact, so the two zones are placed a fixed
        distance apart along the board's long axis, on the largest walkable region.
        """
        block_w, block_h = 3, 2
        contact_cells = 18
        # the hostiles hold the north edge, the squad deploys a fixed distance south of them
        target = 2 if from_top else min(gh - block_h - 1, 2 + contact_cells)
        target = max(0, min(gh - block_h, target))
        rows = [target] + sorted(range(0, gh - block_h + 1), key=lambda y: abs(y - target))
        cols = list(range(gw - block_w, -1, -1)) if from_top else list(range(0, gw - block_w + 1))
        for gy in rows:
            for gx in cols:
                if all(paint.get(f"{gx + dx},{gy + dy}") == "normal"
                       and (gx + dx, gy + dy) in walkable_main
                       for dx in range(block_w) for dy in range(block_h)):
                    return {"x": gx, "y": gy, "w": block_w, "h": block_h}
        return {"x": 0, "y": 0, "w": block_w, "h": block_h}

    zones = {"player": find_zone(False), "enemy": find_zone(True)}

    # Every cell a unit can stand on must be reachable from the landing zones. A parcel cut from a
    # walled place can leave pockets: measured in the game, a squad deployed into one and the fight
    # could not reach the enemy. A cell that no unit can walk to is not walkable, so it is sealed --
    # intentionally impassable -- rather than left as a trap, and the board reports what it sealed.
    def reachable_from(zone: dict) -> set[tuple[int, int]]:
        seeds = [(zone["x"] + dx, zone["y"] + dy) for dx in range(zone["w"]) for dy in range(zone["h"])]
        seen: set[tuple[int, int]] = set()
        stack = [s for s in seeds if paint.get(f"{s[0]},{s[1]}") == "normal"]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen or not (0 <= cx < gw and 0 <= cy < gh):
                continue
            if paint.get(f"{cx},{cy}") != "normal":
                continue
            seen.add((cx, cy))
            stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))
        return seen

    reachable = reachable_from(zones["player"])
    sealed = 0
    for gy in range(gh):
        for gx in range(gw):
            if paint.get(f"{gx},{gy}") == "normal" and (gx, gy) not in reachable:
                paint[f"{gx},{gy}"] = "impassable"
                sealed += 1

    # ---------------------------------------------------------------- craters
    # A crater is relief plus a rim: a bowl one level below the board and cover on the cells around it.
    # The source has no crater cover type (its `nm_craters` is a ground splat), so the crater is ours --
    # but it costs no new mechanic, because the rules already read a lower cell as a height term and the
    # adjacent cells as directional cover.
    craters = 0
    if not args.flat:
        rng = random.Random(args.seed * 31 + 7)
        for _ in range(40):
            gx = rng.randrange(3, max(4, gw - 4))
            gy = rng.randrange(3, max(4, gh - 4))
            bowl = [(gx, gy), (gx + 1, gy), (gx, gy + 1), (gx + 1, gy + 1)]
            if any(paint.get(f"{bx},{by}") != "normal" or prop_occ[by * 2, bx * 2] for bx, by in bowl):
                continue
            rim = [(gx - 1 + dx, gy - 1 + dy) for dx in range(4) for dy in range(4)
                   if (gx - 1 + dx, gy - 1 + dy) not in bowl]
            for bx, by in bowl:
                heights[by][bx] = -CRATER_DEPTH_STEPS
            for rx, ry in rim:
                if 0 <= rx < gw and 0 <= ry < gh and paint.get(f"{rx},{ry}") == "normal":
                    cover.setdefault(f"{rx},{ry}", "heavy_cover")
            craters += 1
            if craters >= 3:
                break

    # ---------------------------------------------------------------- cover a deployment zone
    # A squad that lands in an empty plaza has nothing to fight from: measured at the game's own
    # camera, the deployment corner was twenty-four metres of bare paving with the nearest wall off
    # frame. A zone always gets cover within reach -- four pieces from the map's own kit, on walkable
    # ground, just outside the spawn cells so they never block the landing itself.
    zones = {"player": find_zone(False), "enemy": find_zone(True)}

    # Every cell a unit can stand on must be reachable from the landing zones. A parcel cut from a
    # walled place can leave pockets: measured in the game, a squad deployed into one and the fight
    # could not reach the enemy. A cell that no unit can walk to is not walkable, so it is sealed --
    # intentionally impassable -- rather than left as a trap, and the board reports what it sealed.
    def reachable_from(zone: dict) -> set[tuple[int, int]]:
        seeds = [(zone["x"] + dx, zone["y"] + dy) for dx in range(zone["w"]) for dy in range(zone["h"])]
        seen: set[tuple[int, int]] = set()
        stack = [s for s in seeds if paint.get(f"{s[0]},{s[1]}") == "normal"]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen or not (0 <= cx < gw and 0 <= cy < gh):
                continue
            if paint.get(f"{cx},{cy}") != "normal":
                continue
            seen.add((cx, cy))
            stack.extend(((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)))
        return seen

    reachable = reachable_from(zones["player"])
    sealed = 0
    for gy in range(gh):
        for gx in range(gw):
            if paint.get(f"{gx},{gy}") == "normal" and (gx, gy) not in reachable:
                paint[f"{gx},{gy}"] = "impassable"
                sealed += 1
    zone_dressed = 0
    if dressable:
        rng = random.Random(args.seed * 13 + 5)
        for zone in zones.values():
            placed_for_zone = 0
            for radius in (2, 3, 4):
                for dx in range(-radius, zone["w"] + radius):
                    for dy in range(-radius, zone["h"] + radius):
                        if placed_for_zone >= 4:
                            break
                        gx, gy = zone["x"] + dx, zone["y"] + dy
                        if not (1 <= gx < gw - 1 and 1 <= gy < gh - 1):
                            continue
                        # outside the spawn block itself, and on walkable, prop-free ground
                        inside = zone["x"] <= gx < zone["x"] + zone["w"] and zone["y"] <= gy < zone["y"] + zone["h"]
                        if inside or paint.get(f"{gx},{gy}") != "normal":
                            continue
                        if prop_occ[gy * 2, gx * 2]:
                            continue
                        name = dressable[rng.randrange(len(dressable))]
                        free_props.append({
                            "name": name,
                            "biome": next((q.get("biome") for q in props if q.get("prop") == name), ""),
                            "pos": [round(gx * CELL_M - bw / 2 + CELL_M / 2, 3), 0.0,
                                    round(gy * CELL_M - bh / 2 + CELL_M / 2, 3)],
                            "basis": [1, 0, 0, 0, 1, 0, 0, 0, 1],
                            "scale": 1,
                            "dressed": True,
                        })
                        occ[gy * 2:gy * 2 + 2, gx * 2:gx * 2 + 2] = True
                        prop_occ[gy * 2:gy * 2 + 2, gx * 2:gx * 2 + 2] = True
                        placed_for_zone += 1
                        zone_dressed += 1
                if placed_for_zone >= 4:
                    break

    # ---------------------------------------------------------------- the periphery band
    # A board that ends at its own edge leaves the eye with a void: haze hides it, but haze is not a
    # place. The band is the map's own vocabulary again -- the tallest pieces the parcel already uses,
    # stood just outside the play area, facing in -- so the board is surrounded by the same architecture
    # rather than by nothing.
    # A band is an enclosing wall, not "the tallest thing to hand": the first version put a 38 m domed
    # building, a 20 m staircase and a hedge along the edge, and the board grew three white domes.
    family_of = {p["name"]: p.get("family") for p in families.get("pieces", [])}
    WALL_FAMILIES = {"wall_run", "wall_corner", "wall_barrier"}
    band_names = [n for n in {p["name"] for p in free_props if not p.get("dressed")}
                  if family_of.get(n) in WALL_FAMILIES
                  and max(kit_size.get(n) or [0, 0, 0]) <= 25.0
                  and float((kit_size.get(n) or [0, 0, 0])[2] or 0) >= 3.0][:6]
    band = 0
    if band_names:
        rng = random.Random(args.seed * 7 + 1)
        ring = 3.0  # metres beyond the play area
        spots = []
        for gx in range(2, gw - 2, 3):
            spots.append((gx * CELL_M - bw / 2 + CELL_M / 2, -bh / 2 - ring, 0))
            spots.append((gx * CELL_M - bw / 2 + CELL_M / 2, bh / 2 + ring, 0))
        for gy in range(2, gh - 2, 3):
            spots.append((-bw / 2 - ring, gy * CELL_M - bh / 2 + CELL_M / 2, 90))
            spots.append((bw / 2 + ring, gy * CELL_M - bh / 2 + CELL_M / 2, 90))
        for bx, bz, deg in spots:
            name = band_names[rng.randrange(len(band_names))]
            a = math.radians(deg)
            c, sn = math.cos(a), math.sin(a)
            free_props.append({
                "name": name,
                "biome": next((q.get("biome") for q in props if q.get("prop") == name), ""),
                "pos": [round(bx, 3), 0.0, round(bz, 3)],
                "basis": [c, 0, sn, 0, 1, 0, -sn, 0, c],
                "scale": 1,
                "periphery": True,
            })
            band += 1

    bare_after, _, _ = bare_square(occ, 0.10, 0.90)

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

    # The ambient is a floor, not a mood: at 2.2 it out-votes the warm key and every surface the key
    # does not hit squarely turns the colour of the fill (measured on the city kit: a warm brown albedo
    # of 126,104,91 rendered violet, because 2.2 of cool ambient plus 2.4 of cool hemisphere buried the
    # 3.4 key). 0.9 keeps shadowed faces readable and lets the key set the colour of the board.
    light = json.loads(args.light) if args.light else {
        "azimuthDeg": 215, "elevationDeg": 52, "colour": "#ffe6c2", "intensity": 3.4,
        "sky": "#dfe4ea", "ground": "#4a4238", "ambient": 0.9,
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
        "deployment": zones,
        "cover": cover,
        "source": {
            "kind": "parcel-board",
            "map": board["map"],
            "seed": args.seed,
            "grid_m": CELL_M,
            "slot_m": slot,
            "parcels": [{"id": p["id"], "slot": p["slot"], "zone": p["zone"]} for p in board["parcels"]],
            "seating": seat_report,
            "connectivity": {
                "walkable": sum(1 for v in paint.values() if v == "normal"),
                "reachable": len(reachable),
                "sealed": sealed,
            },
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc))
    if args.catalogue:
        # The catalogue is the game's index of staged boards. A parcel board is registered here, by
        # the tool that emits it, because a staging run that rewrote the index used to delete it and
        # the game silently fell back to generated boards.
        cat_path = Path(args.catalogue)
        cat = json.loads(cat_path.read_text())
        area = doc["size"]["width"] * CELL_M * doc["size"]["height"] * CELL_M
        entry = {
            "id": out.stem, "kind": "parcel-board", "biome": doc["biome"], "seed": args.seed,
            "size": doc["size"], "file": out.name,
            "metrics": {"props": len(free_props),
                        "densityPer100m2": round(100.0 * len(free_props) / area, 2),
                        "dispersion": 0, "embeddedShare": 0},
        }
        entries = [e for e in cat.get("entries", []) if e.get("id") != entry["id"]]
        entries.append(entry)
        cat["entries"] = entries
        cat_path.write_text(json.dumps(cat, indent=1))
    bases = [s["base"] for s in seat_report]
    relief = (max(relief_samples) - min(relief_samples)) if relief_samples else 0.0
    steps = sorted({v for row in heights for v in row})
    # the gate: how many props stand on their own ground. A prop authored on a structure legitimately
    # sits above the terrain, so the measure is the share that is near zero, not the mean.
    err = sorted(abs(v) for v in seat_error)
    grounded = sum(1 for v in err if v <= 0.6)
    p50 = err[len(err) // 2] if err else 0.0
    print(f"seating: {grounded}/{len(err)} props within 0.6 m of their ground (median |dy| {p50:.2f} m)")
    print(f"connectivity: {len(reachable)} reachable cells, {sealed} sealed pockets")
    print(f"levels: {len(upper_cells)} upper-surface cells, {craters} craters")
    print(f"deployment cover: {zone_dressed} pieces at the landing zones")
    print(f"periphery: {band} pieces around the edge")
    print(f"dressing: bare middle {bare_before * bare_before:.0f} m2 -> {bare_after * bare_after:.0f} m2, "
          f"{dressed} pieces from the map's own inventory")
    print(f"wrote {out.name}: {gw}x{gh} cells, {len(free_props)} authored props, "
          f"{len(cover)} cover cells, seat bases {min(bases):.1f}..{max(bases):.1f} m, "
          f"relief {relief:.1f} m over {len(steps)} elevation steps "
          f"({steps[0]}..{steps[-1]})")


if __name__ == "__main__":
    main()
