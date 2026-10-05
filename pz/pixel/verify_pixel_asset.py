#!/usr/bin/env python3
"""QC audit for shipped pixel assets (consultation item 5, adapted).

Checks, in order:
  1. alpha binarisation          - semi-transparent pixels are a FAIL
  2. palette compliance          - off-palette colours are a FAIL (tolerance
                                   per channel via --tol for near-miss review)
  3. orphan pixels               - no identical orthogonal neighbour: WARN
  4. silhouette rim contrast     - bright rim pixels blow out on Discord light
                                   mode: FAIL if > --rim-pct of rim pixels
                                   exceed --rim-luma (badges/sparkles touching
                                   transparency make a hard 100% rule useless)

    verify_pixel_asset.py in.png [--tol 6] [--rim-luma 140] [--rim-pct 25]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from palette import palette_list  # noqa: E402


def audit(path, tol=6, rim_luma=140, rim_pct=25.0, verbose=True):
    a = np.array(Image.open(path).convert("RGBA")).astype(int)
    rgb, alpha = a[:, :, :3], a[:, :, 3]
    fails, warns = [], []

    # 1. alpha binarisation
    semi = (alpha > 0) & (alpha < 255)
    if semi.any():
        fails.append("alpha not binary: %d semi-transparent px" % semi.sum())

    # 2. palette compliance
    op = alpha == 255
    if op.any():
        cols = rgb[op]
        pal = np.array(palette_list())
        if tol == 0:
            ok = (cols[:, None, :] == pal[None]).all(-1).any(1)
        else:
            d = np.abs(cols[:, None, :] - pal[None]).max(-1)
            ok = d.min(1) <= tol
        off = (~ok).sum()
        if off:
            fails.append("%d off-palette px (tol %d)" % (off, tol))

    # 3. orphan pixels
    orphans = 0
    h, w = alpha.shape
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if alpha[y, x] != 255:
                continue
            c = rgb[y, x]
            nbs = [rgb[y - 1, x], rgb[y + 1, x], rgb[y, x - 1], rgb[y, x + 1]]
            if not any((c == n).all() for n in nbs):
                orphans += 1
    if orphans:
        warns.append("%d orphan pixels" % orphans)

    # 4. silhouette rim contrast (dark vs light theme)
    tr = alpha == 0
    rim = op & (np.roll(tr, 1, 0) | np.roll(tr, -1, 0) |
                np.roll(tr, 1, 1) | np.roll(tr, -1, 1))
    if rim.any():
        lum = (rgb[rim] * [0.299, 0.587, 0.114]).sum(1)
        bright = (lum > rim_luma).sum() / rim.sum() * 100.0
        if bright > rim_pct:
            fails.append("rim too bright: %.0f%% of rim px over luma %d "
                         "(blows out on light backgrounds)" % (bright, rim_luma))
        elif verbose and bright > 0:
            print("note: %.0f%% of rim px over luma %d (badges/sparkles)" %
                  (bright, rim_luma))

    name = os.path.basename(path)
    for f in fails:
        print("[FAIL] %s: %s" % (name, f))
    for wmsg in warns:
        print("[WARN] %s: %s" % (name, wmsg))
    if not fails and not warns and verbose:
        print("[OK] %s" % name)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description="Pixel asset QC audit")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--tol", type=int, default=6)
    ap.add_argument("--rim-luma", type=int, default=140)
    ap.add_argument("--rim-pct", type=float, default=25.0)
    a = ap.parse_args()
    rc = 0
    for p in a.inputs:
        rc |= audit(p, a.tol, a.rim_luma, a.rim_pct)
    return rc


if __name__ == "__main__":
    sys.exit(main())
