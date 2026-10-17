#!/usr/bin/env python3
"""hero_sculpt.py — pass 5: region-locked hero detail (dragon head etc).

Passes 1-4 carve globally with coarse bands; hero elements (head, horns, jaw)
need fine bands confined to their region and displacement along the vertex
NORMAL, not the axis — near-silhouette forms (horn tips) must move sideways.

  1. front-project the mesh, high-pass the artwork at fine bands (1920 grid)
  2. mask: bbox in uv with cosine feather, front-facing verts only
  3. displace along vertex normal, amplitude per band
  4. audit: front verify + renders; the user eye-gates the head crop

Same displacement rule as sculpt_detail (global function of position) so
tiles stay seamless. Run with the repo venv.

Usage:
  hero_sculpt.py mesh.glb artwork.jpg --region 0.36,0.58,0.58,0.96
      --bands 16,8,4 --amplitudes 0.020,0.012,0.006 --out carved.glb
region = x0,x1,ylo,yup in unit uv (y up).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

RES = 1920  # fine grid (sculpt_detail uses 960; hero detail needs 2x)


def art_highpass(image: Path, shape, blur: int) -> np.ndarray:
    """Centred high-pass of the artwork luminance at `shape`; +/-0.5."""
    import cv2
    art = np.asarray(Image.open(image).convert("L").resize(
        (shape[1], shape[0]), Image.LANCZOS), dtype=float) / 255
    art = cv2.GaussianBlur(art, (0, 0), 1.5)  # kill photo grain -> no stipple
    lo, hi = art.min(), art.max()
    art = (art - lo) / (hi - lo) if hi > lo else art * 0
    p = np.pad(art, blur, mode="edge")
    acc = np.zeros_like(art)
    n = 0
    for dy in range(0, 2 * blur + 1, 2):
        for dx in range(0, 2 * blur + 1, 2):
            acc += p[dy:dy + art.shape[0], dx:dx + art.shape[1]]
            n += 1
    hp = art - acc / n
    return np.clip(hp * 4, -0.5, 0.5)


def region_mask(shape, region) -> np.ndarray:
    """Cosine-feathered box in uv; y flipped to image rows."""
    x0, x1, ylo, yup = region
    h, w = shape
    xs = np.linspace(0, 1, w)[None, :]
    ys = np.linspace(0, 1, h)[:, None]
    fx = np.clip((xs - x0) / 0.04, 0, 1) * np.clip((x1 - xs) / 0.04, 0, 1)
    fy = np.clip((ys - ylo) / 0.04, 0, 1) * np.clip((yup - ys) / 0.04, 0, 1)
    m = fx * fy
    return m[::-1]  # image rows: top = y max


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("artwork", type=Path)
    p.add_argument("--region", required=True,
                   help="x0,x1,ylo,yup unit-uv bbox of the hero element")
    p.add_argument("--bands", default="16,8,4",
                   help="high-pass radii at the 1920 grid, px")
    p.add_argument("--amplitudes", default="0.020,0.012,0.006",
                   help="max normal displacement per band, model units")
    p.add_argument("--nz", type=float, default=0.2,
                   help="damp below this front-facing-ness (blend, not a cut)")
    p.add_argument("--out", type=Path, default=None)
    a = p.parse_args()

    region = [float(v) for v in a.region.split(",")]
    bands = [int(v) for v in a.bands.split(",")]
    amps = [float(v) for v in a.amplitudes.split(",")]
    if len(bands) != len(amps):
        sys.exit("bands/amplitudes length mismatch")

    m = trimesh.load(a.mesh, force="mesh", process=True)
    v = m.vertices.copy()
    x, y = v[:, 0], v[:, 1]
    nx = RES
    ny = int(RES * (y.max() - y.min()) / (x.max() - x.min()))
    mask = region_mask((ny, nx), region)

    col = ((x - x.min()) / (x.max() - x.min()) * (nx - 1)).astype(int).clip(0, nx - 1)
    gy = ((y - y.min()) / (y.max() - y.min()) * (ny - 1)).astype(int).clip(0, ny - 1)
    row = ny - 1 - gy

    # vertex normals, unit
    n = np.asarray(m.vertex_normals)

    total = np.zeros(len(v))
    for blur, amp in zip(bands, amps):
        hp = art_highpass(a.artwork, (ny, nx), blur=blur)
        total += amp * hp[row, col] * mask[row, col]

    # front-facing weight: keep some side effect but damp backfaces
    w = np.clip((n[:, 2] - a.nz + 0.3) / 0.5, 0, 1)
    disp = total * w

    v += n * disp[:, None]
    m2 = m.copy()
    m2.vertices = v
    out = a.out or a.mesh
    m2.export(out)
    print(f"[hero] max normal displacement {np.abs(disp).max():.4f} units "
          f"on {(np.abs(disp) > 1e-5).sum()} verts -> {out}")


if __name__ == "__main__":
    main()
