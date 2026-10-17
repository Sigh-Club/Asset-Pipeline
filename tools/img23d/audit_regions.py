#!/usr/bin/env python3
"""audit_regions.py — per-region capture audit: mesh render vs reference.

The honesty scan for the detail question. Renders the mesh front-on at the
reference framing, edge-detects both, and reports per-cell capture: what
fraction of each region's reference detail the mesh carries. Heatmap png:
green = reference detail present in mesh, red = lost.

Usage:
  audit_regions.py mesh.glb reference.jpg --grid 4 4 [--out png]
Exits 0 always; the numbers are the deliverable.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

RES = 1024


def render_front(mesh: Path, workdir: Path) -> np.ndarray:
    out = workdir / "audit_front.png"
    subprocess.run(
        ["f3d", str(mesh), "--output", str(out), "--no-background",
         "--camera-orthographic", "--camera-position", "0,0,5",
         "--camera-focal-point", "0,0,0", "--camera-view-up", "0,1,0",
         "--resolution", f"{RES},{RES}", "--filename=0",
         "--light-intensity", "1.2"],
        check=True, capture_output=True)
    im = np.asarray(Image.open(out).convert("RGBA"))
    alpha = im[:, :, 3] > 128
    n, labels, stats, _ = cv2.connectedComponentsWithStats(alpha.astype(np.uint8), 8)
    if n > 1:  # kill the f3d corner gizmo
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha = labels == big
    rgb = im[:, :, :3].astype(float)
    grey = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]) / 255
    return np.where(alpha, grey, np.nan), alpha


def edges(g, mask, pct=80):
    g = np.nan_to_num(g, nan=np.nanmean(g) if np.isfinite(g).any() else 0)
    e = cv2.GaussianBlur(g, (0, 0), 1.2)
    gy, gx = np.gradient(e)
    m = np.hypot(gx, gy)
    t = np.percentile(m[mask], pct) if mask.any() else 1e9
    return (m > t) & mask


def dilate(mask, r=4):
    return cv2.dilate(mask.astype(np.uint8) * 255, np.ones((2 * r + 1, 2 * r + 1), np.uint8)) > 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("reference", type=Path)
    p.add_argument("--grid", nargs=2, type=int, default=(4, 4), metavar=("RY", "RX"))
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()
    ty, tx = a.grid

    with tempfile.TemporaryDirectory() as td:
        mesh_g, mesh_mask = render_front(a.mesh, Path(td))
    ref = np.asarray(Image.open(a.reference).convert("L").resize(
        (RES, RES), Image.LANCZOS), float) / 255

    # reference mask: crop to content (light bg assumption), same aspect as mesh bbox
    ys, xs = np.where(mesh_mask)
    bx0, bx1, by0, by1 = xs.min(), xs.max(), ys.min(), ys.max()
    ref_c = np.full_like(ref, np.nan)
    ref_c[by0:by1 + 1, bx0:bx1 + 1] = ref[by0:by1 + 1, bx0:bx1 + 1]
    ref_mask = np.isfinite(ref_c)

    pe = edges(ref_c, ref_mask)
    me = edges(mesh_g, mesh_mask & np.isfinite(mesh_g))

    cap = np.zeros((ty, tx))
    print(f"[audit] {'region':>12s} capture%  ref-edges")
    for r in range(ty):
        for c in range(tx):
            r0, r1 = int(RES * r / ty), int(RES * (r + 1) / ty)
            c0, c1 = int(RES * c / tx), int(RES * (c + 1) / tx)
            cell = np.zeros((RES, RES), bool)
            cell[r0:r1, c0:c1] = True
            m = pe & cell
            denom = m.sum()
            cap[r, c] = 100 * (m & dilate(me)).sum() / max(denom, 1)
            print(f"[audit] r{r+1}c{c+1:<8d} {cap[r, c]:6.1f}  {denom:7d}")

    heat = np.zeros((RES, RES, 3), np.uint8)
    heat[..., 1] = np.where(pe & dilate(me), 200, 0)      # green: captured
    heat[..., 0] = np.where(pe & ~dilate(me), 220, 0)      # red: lost
    heat[..., 2] = np.where(me & ~dilate(pe), 90, 0)       # blue: mesh-only
    for r in range(1, ty):
        heat[int(RES * r / ty)] = 70
    for c in range(1, tx):
        heat[:, int(RES * c / tx)] = 70
    out = a.out or a.mesh.parent / f"{a.mesh.stem}_audit.png"
    Image.fromarray(heat).save(out)

    flat = cap.ravel()
    print(f"[audit] mean {flat.mean():.1f}% min {flat.min():.1f}% "
          f"(r{cap.min(axis=1).argmax()+1}c{cap.argmin()%tx+1}) "
          f"max {flat.max():.1f}%")
    print(f"[audit] heatmap (green=kept red=LOST blue=extra) -> {out}")


if __name__ == "__main__":
    main()
