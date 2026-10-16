#!/usr/bin/env python3
"""plate.py — single-view reconstruction -> printable relief plate.

Image-to-3D reconstructions from a single view inflate the unseen back
(Hunyuan returned a 1.85-deep slab for a ~0.4-deep book stack). For
case panels / wall plaques we only want the front relief on a flat back
anyway. This tool:

  1. loads the reconstructed mesh,
  2. rasterises the front-side surface to a heightfield,
  3. rebuilds it as a watertight slab: displaced front + flat back,
  4. exports STL (plus the heightmap PNG for inspection).

Usage:
  plate.py model.glb                        # band auto: p25..p90
  plate.py model.glb --lo 0.394 --hi 0.82   # explicit z band
  plate.py model.glb --relief 0.10 --res 420x400
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image


def heightfield(mesh, sel_frac=0.55, res=(420, 400), blur=80):
    """Rasterise the front (+z) surface to a dense height grid, hole-filled."""
    v = mesh.vertices
    zmin, zmax = v[:, 2].min(), v[:, 2].max()
    sel = v[:, 2] > zmin + sel_frac * (zmax - zmin)
    x, y, z = v[sel, 0], v[sel, 1], v[sel, 2]
    ny, nx = res
    gx = ((x - x.min()) / (x.max() - x.min()) * (nx - 1)).astype(int).clip(0, nx - 1)
    gy = ((y - y.min()) / (y.max() - y.min()) * (ny - 1)).astype(int).clip(0, ny - 1)
    acc = np.zeros((ny, nx)); cnt = np.zeros((ny, nx))
    np.add.at(acc, (gy, gx), z); np.add.at(cnt, (gy, gx), 1)
    H = acc / np.maximum(cnt, 1); mask = (cnt > 0).astype(float)
    for _ in range(blur):  # diffuse-fill empty bins
        Hs = np.pad(H, 1, mode="edge"); Ms = np.pad(mask, 1, mode="edge")
        Hn = (Hs[1:-1, 2:] + Hs[1:-1, :-2] + Hs[2:, 1:-1] + Hs[:-2, 1:-1]) * 0.25
        Mn = (Ms[1:-1, 2:] + Ms[1:-1, :-2] + Ms[2:, 1:-1] + Ms[:-2, 1:-1]) * 0.25
        H = np.where(mask > 0, H, Hn / Mn.clip(1e-6))
        mask = np.maximum(mask, ((Hn > 0) & (mask < 0.5)).astype(float))
    return H, x.min(), x.max(), y.min(), y.max()


def build_plate(H, x0, x1, y0, y1, lo, hi, relief=0.10, base=0.02):
    """Watertight slab: displaced front grid + flat back + stitched walls."""
    R = np.clip((H - lo) / (hi - lo), 0, 1)
    ny, nx = R.shape
    xs = np.linspace(x0, x1, nx); ys = np.linspace(y0, y1, ny)
    XX, YY = np.meshgrid(xs, ys)
    F = np.column_stack([XX.ravel(), YY.ravel(), (base + R * relief).ravel()])
    B = np.column_stack([XX.ravel(), YY.ravel(), np.zeros(ny * nx)])
    V = np.vstack([F, B])
    F2 = lambda r, c: r * nx + c
    B2 = lambda r, c: ny * nx + r * nx + c
    faces = []
    for r in range(ny - 1):  # front (+z, CCW up) and back (reversed)
        for c in range(nx - 1):
            f = [F2(r, c), F2(r, c + 1), F2(r + 1, c + 1), F2(r + 1, c)]
            b = [B2(r, c), B2(r, c + 1), B2(r + 1, c + 1), B2(r + 1, c)]
            faces += [[f[0], f[1], f[2]], [f[0], f[2], f[3]]]
            faces += [[b[0], b[2], b[1]], [b[0], b[3], b[2]]]
    for c in range(nx - 1):  # y0 / y1 walls
        A, Bb, Bf, Af = F2(0, c), F2(0, c + 1), B2(0, c + 1), B2(0, c)
        faces += [[A, Bb, Bf], [A, Bf, Af]]
        A, Bb, Bf, Af = F2(ny - 1, c), F2(ny - 1, c + 1), B2(ny - 1, c + 1), B2(ny - 1, c)
        faces += [[A, Bf, Bb], [A, Af, Bf]]
    for r in range(ny - 1):  # x0 / x1 walls
        A, Bb, Bf, Af = F2(r, 0), F2(r + 1, 0), B2(r + 1, 0), B2(r, 0)
        faces += [[A, Af, Bf], [A, Bf, Bb]]
        A, Bb, Bf, Af = F2(r, nx - 1), F2(r + 1, nx - 1), B2(r + 1, nx - 1), B2(r, nx - 1)
        faces += [[A, Bb, Bf], [A, Bf, Af]]
    m = trimesh.Trimesh(vertices=V, faces=np.array(faces), process=True)
    m.remove_unreferenced_vertices()
    return m, R


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path, help="reconstructed GLB/OBJ/STL")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--relief", type=float, default=0.10, help="relief amplitude, model units")
    p.add_argument("--base", type=float, default=0.02, help="min front height above back")
    p.add_argument("--res", type=str, default="420x400", help="plate grid NXxNY (x-separated)")
    p.add_argument("--lo", type=float, default=None, help="height band low (default p25)")
    p.add_argument("--hi", type=float, default=None, help="height band high (default p90)")
    p.add_argument("--sel", type=float, default=0.55, help="front-side selection fraction")
    a = p.parse_args()

    mesh = trimesh.load(a.mesh, force="mesh", process=True)
    ny, nx = (int(v) for v in a.res.split("x"))
    H, x0, x1, y0, y1 = heightfield(mesh, sel_frac=a.sel, res=(ny, nx))
    lo = a.lo if a.lo is not None else float(np.percentile(H, 25))
    hi = a.hi if a.hi is not None else float(np.percentile(H, 90))
    m, R = build_plate(H, x0, x1, y0, y1, lo, hi, a.relief, a.base)

    out = a.out or a.mesh.with_name(a.mesh.stem + "_plate.stl")
    m.export(out)
    png = out.with_suffix(".heightmap.png")
    Image.fromarray((R * 255).astype(np.uint8)).save(png)
    print(f"[plate] watertight={m.is_watertight} verts={len(m.vertices)} "
          f"faces={len(m.faces)} components={m.body_count}")
    print(f"[plate] band z {lo:.3f}..{hi:.3f} relief={a.relief} -> {out}")
    print(f"[plate] heightmap -> {png}")


if __name__ == "__main__":
    main()
