#!/usr/bin/env python3
"""sculpt_detail.py — fuse the artwork's crisp detail into a 3D reconstruction.

The raw single-view mesh carries correct low-frequency form but smoothed
surface detail (the reconstruction latent is coarser than the artwork). This
tool displaces front-facing vertices along +z by the artwork's high-pass
luminance — the same proven transform as plate.py's --detail-image, applied to
the volume mesh instead of a heightfield. Displacement is a global function of
(x,y), so tiles cut from the same mesh stay seamless.

Usage:
  sculpt_detail.py mesh.glb artwork.jpg --strength 0.05   # model units
  works in place on tiles too (same rule => seamless across tile borders)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image


def art_highpass(image: Path, shape, blur=9):
    art = np.asarray(Image.open(image).convert("L").resize(
        (shape[1], shape[0]), Image.LANCZOS), dtype=float) / 255
    lo, hi = art.min(), art.max()
    art = (art - lo) / (hi - lo) if hi > lo else art * 0
    P = np.pad(art, blur, mode="edge")
    acc = np.zeros_like(art); n = 0
    for dy in range(0, 2 * blur + 1, 2):
        for dx in range(0, 2 * blur + 1, 2):
            acc += P[dy:dy + art.shape[0], dx:dx + art.shape[1]]; n += 1
    hp = art - acc / n
    return (hp - hp.min()) / (hp.max() - hp.min() + 1e-9) - 0.5  # centred ±0.5


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("artwork", type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--strength", type=float, default=0.05,
                   help="max displacement, model units (0.05 = ~15mm at 628mm panel)")
    p.add_argument("--nz", type=float, default=0.35, help="min face-normal z to displace")
    p.add_argument("--blur", type=int, default=9)
    a = p.parse_args()

    m = trimesh.load(a.mesh, force="mesh", process=True)
    v = m.vertices
    x, y = v[:, 0], v[:, 1]
    nx, ny = 960, int(960 * (y.max() - y.min()) / (x.max() - x.min()))
    hp = art_highpass(a.artwork, (ny, nx), blur=a.blur)
    gx = ((x - x.min()) / (x.max() - x.min()) * (nx - 1)).astype(int).clip(0, nx - 1)
    gy = ((y - y.min()) / (y.max() - y.min()) * (ny - 1)).astype(int).clip(0, ny - 1)
    disp = a.strength * hp[gy, gx]

    # front-facing weight from vertex normals (feathered, no seams)
    nz = np.zeros(len(v))
    nz[np.unique(m.faces)] = 1.0
    fn = m.face_normals
    fc = v[m.faces].mean(axis=1)
    for f_i in range(len(m.faces)):
        pass
    # vectorised vertex-normal weight:
    vz = np.zeros(len(v)); cnt = np.zeros(len(v))
    vi = m.faces.ravel()
    np.add.at(vz, vi, np.repeat(fn[:, 2], 3))
    np.add.at(cnt, vi, 1)
    nz = vz / np.maximum(cnt, 1)
    w = np.clip((nz - a.nz + 0.2) / 0.3, 0, 1)

    v[:, 2] += disp * w
    m.vertices = v
    m.export(a.out or a.mesh)  # in-place default: same geometry role, new detail
    moved = float(np.abs(disp * w).max())
    print(f"[sculpt-detail] max displacement {moved:.4f} units; wrote {a.out or a.mesh}")


if __name__ == "__main__":
    main()
