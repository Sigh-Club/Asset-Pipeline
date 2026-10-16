#!/usr/bin/env python3
"""tiles.py — CR-200B print prep: plate/reconstruction -> bed-sized tiles.

Splits a relief into watertight tiles for small beds (Creality CR-200B:
200x200x200, keep <=190 mm). The cut happens on the shared heightfield BEFORE
meshing, so every tile is watertight by construction and the front relief is
continuous across seams (adjacent edges sample the same global function).
Seams: butt joint + glue; optional printed 6 mm dowels. Keep fine detail away
from tile borders — the CR-200B's outer 15 mm of bed is unreliable (see the
cr200b skill).

Usage:
  tiles.py plate.stl --width 628 --bed 190
  tiles mesh.glb --width 628 --relief-mm 38

Outputs into <name>_tiles/:
  tile_r<R>of<TY>_c<C>of<TX>.stl            watertight tile, flat back
  tile_..._heightmap.png                    per-tile QC
  dowel_6x8.stl                             print N of these
  manifest.json                             grid layout, dims, checks
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
_spec = importlib.util.spec_from_file_location("plate", _HERE / "plate.py")
plate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plate)


def slab_from_grid(R, x0, x1, y0, y1, relief_units, base_units=0.02):
    """Watertight heightfield slab — same construction as plate.build_plate."""
    return plate.build_plate(R, x0, x1, y0, y1,
                             lo=0.0, hi=1.0,  # R already normalised
                             relief=relief_units, base=base_units)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path, help="reconstruction glb or plate stl")
    p.add_argument("--width", type=float, default=628.0, help="target width mm")
    p.add_argument("--bed", type=float, default=190.0, help="max tile footprint mm")
    p.add_argument("--relief-mm", type=float, default=38.0,
                   help="relief amplitude at target scale (6%% of width)")
    p.add_argument("--grid-res", type=int, default=960, help="heightfield samples across width")
    p.add_argument("--sel", type=float, default=0.3)
    p.add_argument("--lo", type=float, default=None)
    p.add_argument("--hi", type=float, default=None)
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()

    mesh = trimesh.load(a.mesh, force="mesh", process=True)
    ext = mesh.extents
    mm_per_unit = a.width / ext[0]
    height_mm = ext[1] * mm_per_unit

    res_x = a.grid_res
    res_y = int(a.grid_res * ext[1] / ext[0])
    H, x0, x1, y0, y1 = plate.heightfield(mesh, sel_frac=a.sel, res=(res_y, res_x), blur=180)
    lo = a.lo if a.lo is not None else float(np.nanpercentile(H, 25))
    hi = a.hi if a.hi is not None else float(np.nanpercentile(H, 90))
    R = np.clip((H - lo) / (hi - lo), 0, 1)
    ny, nx = R.shape

    tx = max(1, math.ceil(a.width / a.bed))
    ty = max(1, math.ceil(height_mm / a.bed))
    cols = np.linspace(0, nx, tx + 1).astype(int)
    rows = np.linspace(0, ny, ty + 1).astype(int)

    relief_units = a.relief_mm / mm_per_unit
    out = a.out or a.mesh.parent / (a.mesh.stem + "_tiles")
    out.mkdir(parents=True, exist_ok=True)

    manifest = {"source": str(a.mesh), "bed_mm": a.bed, "width_mm": a.width,
                "height_mm": round(height_mm, 1),
                "relief_mm": a.relief_mm, "grid": [ty, tx], "tiles": []}
    failures = 0
    for r in range(ty):
        for c in range(tx):
            r0, r1 = rows[r], rows[r + 1]
            c0, c1 = cols[c], cols[c + 1]
            sub = R[r0:r1, c0:c1]
            sx0 = x0 + (x1 - x0) * c0 / nx
            sx1 = x0 + (x1 - x0) * c1 / nx
            sy0 = y0 + (y1 - y0) * r0 / ny
            sy1 = y0 + (y1 - y0) * r1 / ny
            m, _ = slab_from_grid(sub, sx0, sx1, sy0, sy1,
                                  relief_units=relief_units)
            name = f"tile_r{r + 1}of{ty}_c{c + 1}of{tx}"
            w_mm = (sx1 - sx0) * mm_per_unit
            h_mm = (sy1 - sy0) * mm_per_unit
            ok = m.is_watertight and m.body_count == 1 and max(w_mm, h_mm) <= a.bed + 0.5
            failures += 0 if ok else 1
            m.export(out / f"{name}.stl")
            Image.fromarray((sub * 255).astype(np.uint8)).save(out / f"{name}_heightmap.png")
            entry = {"file": f"{name}.stl", "row": r + 1, "col": c + 1,
                     "mm": [round(w_mm, 1), round(h_mm, 1)],
                     "watertight": bool(m.is_watertight), "faces": len(m.faces)}
            manifest["tiles"].append(entry)
            print(f"[tiles] {name}: {w_mm:.1f} x {h_mm:.1f} mm, {len(m.faces)} faces, "
                  f"watertight={m.is_watertight} {'OK' if ok else '** CHECK **'}")

    cyl = trimesh.creation.cylinder(radius=3.0, height=8.0, sections=32)
    cyl.export(out / "dowel_6x8.stl")
    n_dow = 2 * (tx - 1) * ty + 2 * (ty - 1) * tx
    manifest["dowels"] = {"dia_mm": 6, "len_mm": 8, "count": n_dow,
                          "note": "drill 6 mm holes into flat backs across seams, glue; "
                                  "or butt-glue with clamps only"}
    manifest["all_ok"] = failures == 0
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"[tiles] {tx} x {ty} grid, {len(manifest['tiles'])} tiles -> {out}"
          f"  ({'ALL OK' if failures == 0 else f'{failures} CHECK'})")


if __name__ == "__main__":
    main()
