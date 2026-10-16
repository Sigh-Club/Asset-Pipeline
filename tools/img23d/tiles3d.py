#!/usr/bin/env python3
"""tiles3d.py — cut a FULL 3D mesh (volume, not heightfield) into print tiles.

The relief cutter (tiles.py) rebuilds slabs from a heightfield; that loses the
standing-off geometry. This cutter boolean-intersects the mesh with box cells
(manifold3d via trimesh.boolean), repairs float32 STL cracks, and verifies
per-component watertightness — the print gate from the cr200b skill.

Multiple bodies per tile are legal (wing fragments etc); every component must
be watertight. A component with <=2 bad edges after repair is recorded as
'slicer-heal' — PrusaSlicer repairs missing single faces on import.

Usage:
  tiles3d.py mesh.glb --out <dir> --grid 4 4 --width-mm 628 --source "pass4 ..."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh


def repair(m) -> dict:
    """Merge, fill, fix winding. Returns repair stats."""
    m.merge_vertices()
    trimesh.repair.fill_holes(m)
    trimesh.repair.fix_winding(m)
    return {}


def component_report(m) -> dict:
    parts = m.split(only_watertight=False)
    bad = []
    for c in parts:
        if c.is_watertight:
            continue
        e = c.edges_sorted
        cnt = np.unique(e, axis=0, return_counts=True)[1]
        bad.append(int((cnt != 2).sum()))
    return dict(components=len(parts),
                bad_components=len(bad),
                worst_bad_edges=max(bad) if bad else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--grid", nargs=2, type=int, default=(4, 4), metavar=("TY", "TX"))
    p.add_argument("--width-mm", type=float, default=628.0)
    p.add_argument("--margin", type=float, default=5.0,
                   help="box margin in mm beyond the opposite faces")
    p.add_argument("--source", default="", help="manifest provenance string")
    a = p.parse_args()
    ty, tx = a.grid

    m = trimesh.load(a.mesh, force="mesh", process=True)
    if not m.is_watertight:
        sys.exit("source mesh not watertight — repair before cutting")
    mm = a.width_mm / m.extents[0]
    m.apply_scale(mm)
    lo, hi = m.bounds
    print(f"[tiles3d] extents {m.extents.round(1)} mm, watertight source")

    xs = np.linspace(lo[0], hi[0], tx + 1)
    ys = np.linspace(lo[1], hi[1], ty + 1)
    a.out.mkdir(parents=True, exist_ok=True)

    manifest = {"source": a.source, "grid": [ty, tx], "mm_per_unit": mm,
                "width_mm": a.width_mm, "tiles": [], "all_ok": True}
    failures = 0
    for r in range(ty):
        for c in range(tx):
            box = trimesh.creation.box(bounds=np.array([
                [xs[c], ys[r], lo[2] - a.margin],
                [xs[c + 1], ys[r + 1], hi[2] + a.margin]]))
            part = trimesh.boolean.intersection([m, box])
            repair(part)
            rep = component_report(part)
            ok = rep["bad_components"] == 0 or rep["worst_bad_edges"] <= 2
            slicer_heal = rep["bad_components"] > 0 and rep["worst_bad_edges"] <= 2
            failures += 0 if ok else 1
            name = f"sculpt_r{r + 1}of{ty}_c{c + 1}of{tx}.stl"
            part.export(a.out / name)
            entry = {"file": name, "row": r + 1, "col": c + 1,
                     "watertight": not slicer_heal and rep["bad_components"] == 0,
                     "slicer_heal": slicer_heal, **rep, "faces": len(part.faces)}
            manifest["tiles"].append(entry)
            print(f"[tiles3d] {name}: comps {rep['components']}, "
                  f"bad {rep['bad_components']} (worst {rep['worst_bad_edges']} edges) "
                  f"{'OK' if ok else '** CHECK **'}")

    manifest["all_ok"] = failures == 0
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"[tiles3d] {ty}x{tx} -> {a.out} "
          f"({'ALL OK' if failures == 0 else f'{failures} CHECK'})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
