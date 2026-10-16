#!/usr/bin/env python3
"""verify.py — measure how much of the artwork's detail survived into the mesh.

Renders the reconstruction's front heightfield, compares edge structure against
the source artwork, and writes a side-by-side PNG. This is the honesty check:
numbers, not vibes.

Usage:
  verify.py mesh.glb artwork.jpg [--out report.png] [--sel 0.3]
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image


def grad(A):
    gy, gx = np.gradient(A)
    return np.hypot(gx, gy)


def dilate(M):
    P = np.pad(M, 3, mode="constant")
    out = np.zeros_like(M)
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            out |= P[3 + dy:3 + dy + M.shape[0], 3 + dx:3 + dx + M.shape[1]].astype(bool)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mesh", type=Path)
    p.add_argument("artwork", type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--sel", type=float, default=0.3, help="front-side fraction as in plate.py")
    a = p.parse_args()

    art = np.asarray(Image.open(a.artwork).convert("L").resize((480, 456), Image.LANCZOS), float) / 255
    an = (art - art.min()) / (art.max() - art.min())

    m = trimesh.load(a.mesh, force="mesh", process=True)
    v = m.vertices
    zmin, zmax = v[:, 2].min(), v[:, 2].max()
    sel = v[:, 2] > zmin + a.sel * (zmax - zmin)
    x, y, z = v[sel, 0], v[sel, 1], v[sel, 2]
    W, Hh = 480, 456
    gx = ((x - x.min()) / (x.max() - x.min()) * (W - 1)).astype(int).clip(0, W - 1)
    gy = ((1 - (y - y.min()) / (y.max() - y.min())) * (Hh - 1)).astype(int).clip(0, Hh - 1)
    acc = np.zeros((Hh, W)); cnt = np.zeros((Hh, W))
    np.add.at(acc, (gy, gx), z); np.add.at(cnt, (gy, gx), 1)
    Z = acc / np.maximum(cnt, 1)
    Z = np.where(np.isnan(Z), np.nanmedian(Z), Z)
    zn = (Z - Z.min()) / (Z.max() - Z.min())

    ga, gz = grad(an), grad(zn)
    ga /= ga.max(); gz /= gz.max()
    sa = ga > np.percentile(ga, 80); sz = gz > np.percentile(gz, 80)
    capture = 100 * (sa & dilate(sz)).sum() / sa.sum()
    spurious = 100 * (sz & dilate(sa)).sum() / sz.sum()

    print(f"[verify] artwork detail captured in mesh : {capture:.1f}%")
    print(f"[verify] mesh edges explained by artwork : {spurious:.1f}%")
    verdict = "GOOD" if capture >= 85 else ("ACCEPTABLE" if capture >= 70 else "POOR — regenerate or raise resolution")
    print(f"[verify] verdict: {verdict}")

    comp = np.hstack([ga, gz, (ga + gz) / 2])
    out = a.out or a.mesh.with_name(a.mesh.stem + "_verify.png")
    Image.fromarray((comp * 255).astype(np.uint8)).save(out)
    print(f"[verify] edges side-by-side (art | mesh | blend) -> {out}")
    return 0 if capture >= 70 else 1


if __name__ == "__main__":
    sys.exit(main())
