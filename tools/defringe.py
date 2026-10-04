#!/usr/bin/env python3
"""Background extraction + defringe for AI-generated pixel art (PZ emotes).

Takes a sprite or sprite sheet generated on a solid background and produces
clean transparent pixel art:
  1. background estimated from the corner patches,
  2. background removed by FLOOD FILL from the borders (connected background
     only - interior pixels that happen to match the background colour, e.g.
     bone-white highlights, survive),
  3. alpha binarized to 0/255 (pixel art must never carry semi-transparent
     anti-aliased edges),
  4. silhouette fringe culled: kept pixels adjacent to transparency whose
     colour is still near the background get dropped - that is the white
     bleed the owner reported,
  5. optional NEAREST downsample (never smooth resampling).

PZ sub-pipeline tool (MTCDeathsExpanded emotes) - outputs go to the caller's
explicit --out path, never into IoA assets/.

    defringe.py in.png out.png [--size 128] [--tol 40] [--bg #RRGGBB] [--selftest]
"""

import argparse
import collections
import os
import sys

import numpy as np
from PIL import Image


def estimate_bg(arr):
    """Median colour of the four 6px corner patches (the background shows
    there in virtually every AI sheet)."""
    h, w = arr.shape[:2]
    k = min(6, h // 4, w // 4)
    patches = [arr[:k, :k], arr[:k, -k:], arr[-k:, :k], arr[-k:, -k:]]
    stack = np.concatenate([p.reshape(-1, p.shape[-1]) for p in patches])
    return np.median(stack, axis=0)


def background_mask(rgb, bg, tol):
    """Flood fill from the borders over pixels within tol of the bg colour.
    Connectivity matters: an interior pixel that matches the background is
    NOT background (bone-white highlights inside the sprite must survive)."""
    h, w = rgb.shape[:2]
    diff = np.abs(rgb.astype(int) - np.array(bg[:3], dtype=int)).sum(axis=2)
    near = diff <= tol
    mask = np.zeros((h, w), bool)
    dq = collections.deque()
    for x in range(w):
        for y in (0, h - 1):
            if near[y, x] and not mask[y, x]:
                mask[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if near[y, x] and not mask[y, x]:
                mask[y, x] = True
                dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and near[ny, nx] and not mask[ny, nx]:
                mask[ny, nx] = True
                dq.append((ny, nx))
    return mask


def defringe_rgba(rgba, bg, tol, keep_tol):
    """Binary alpha + silhouette fringe cull. Returns the cleaned array."""
    arr = np.array(rgba.convert("RGBA"))
    rgb = arr[:, :, :3]
    rgb_f = rgb.astype(int)
    bg3 = np.array(bg[:3], dtype=int)
    diff = np.abs(rgb_f - bg3).sum(axis=2)

    h, w = rgb.shape[:2]
    bgmask = background_mask(rgb, bg, tol)

    alpha = np.where(bgmask, 0, 255).astype(np.uint8)
    if arr.shape[2] == 4:                        # binarize any existing alpha
        existing = arr[:, :, 3]
        alpha = np.where(existing > 128, alpha, 0)

    # fringe cull: kept pixels adjacent to transparency whose colour is still
    # near the background = blended edge bleed -> drop them (the interior of
    # the silhouette is unaffected; dark outlines are far from the bg and
    # always kept)
    transparent = alpha == 0
    adj = np.zeros((h, w), bool)
    adj[1:, :] |= transparent[:-1, :]
    adj[:-1, :] |= transparent[1:, :]
    adj[:, 1:] |= transparent[:, :-1]
    adj[:, :-1] |= transparent[:, 1:]
    near_bg = diff <= keep_tol
    cull = adj & near_bg & (alpha == 255)
    alpha[cull] = 0
    arr[:, :, 3] = alpha
    return Image.fromarray(arr, "RGBA")


def process(path_in, path_out, tol, keep_tol, size, bg_override):
    img = Image.open(path_in).convert("RGBA")
    arr = np.array(img)
    bg = np.array(list(int(bg_override[i:i + 2], 16) for i in (1, 3, 5)) + [255]) \
        if bg_override else estimate_bg(arr)
    clean = defringe_rgba(Image.fromarray(arr, "RGBA"), bg, tol, keep_tol)
    if size:
        clean = clean.resize((size, size), Image.NEAREST)
    clean.save(path_out)
    removed = int(np.sum(np.array(img.convert("RGBA"))[:, :, 3] > 0) -
                  np.sum(np.array(clean)[:, :, 3] > 0))
    print("wrote", os.path.normpath(path_out),
          "(background: %s, removed %d px)" %
          (("%d,%d,%d" % tuple(int(v) for v in bg[:3])), removed))


def selftest():
    """Synthetic sprite on white with blended edge pixels: the classic case."""
    size = 32
    img = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    px = img.load()
    DARK, GREEN, BONE = (26, 32, 26, 255), (106, 140, 84, 255), (222, 226, 210, 255)
    for y in range(6, 26):
        for x in range(6, 26):
            edge = x in (6, 25) or y in (6, 25)
            px[x, y] = DARK if edge else GREEN
    px[10, 10] = BONE; px[11, 10] = BONE          # interior bone-white highlight
    px[20, 20] = BONE
    # blended silhouette bleed: light pixels half-way between outline and bg
    for x, y in ((5, 10), (26, 10), (10, 5), (10, 26), (25, 25)):
        px[x, y] = (248, 248, 248, 255)
    arr = np.array(img)

    cleaned = defringe_rgba(img, (255, 255, 255, 255), 40, 100)
    out = np.array(cleaned)
    alpha = out[:, :, 3]
    problems = []
    if not np.all(np.isin(alpha, (0, 255))):
        problems.append("alpha not binary")
    # interior bone-white highlights survive
    if tuple(out[10, 10][:3]) != BONE[:3]:
        problems.append("interior bone pixel lost")
    if tuple(out[20, 20][:3]) != BONE[:3]:
        problems.append("second bone pixel lost")
    # no kept pixel adjacent to transparency may be near-white any more
    transparent = alpha == 0
    adj = np.zeros((size, size), bool)
    adj[1:, :] |= transparent[:-1, :]
    adj[:-1, :] |= transparent[1:, :]
    adj[:, 1:] |= transparent[:, :-1]
    adj[:, :-1] |= transparent[:, 1:]
    rgb = out[:, :, :3].astype(int)
    near_white = (rgb > 200).all(axis=2) & adj & (alpha == 255)
    if near_white.any():
        ys, xs = np.where(near_white)
        problems.append("white fringe remains at %s" % (list(zip(ys, xs))[:3],))
    # the sprite silhouette kept its dark outline
    if tuple(out[6, 10][:3]) != DARK[:3]:
        problems.append("dark outline eaten")
    if problems:
        for pr in problems:
            print("FAIL:", pr)
        return 1
    print("selftest OK: binary alpha, bone interior kept, fringe culled, outline kept")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Background extraction + defringe for pixel art")
    ap.add_argument("input", nargs="?", help="input PNG (AI sheet or emote)")
    ap.add_argument("output", nargs="?", help="clean transparent PNG")
    ap.add_argument("--size", type=int, default=0, help="optional NEAREST downsize")
    ap.add_argument("--tol", type=int, default=40, help="bg colour tolerance")
    ap.add_argument("--keep-tol", type=int, default=100,
                    help="fringe cull threshold (colour distance to bg)")
    ap.add_argument("--bg", default=None, help="force bg colour #RRGGBB")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.input or not args.output:
        ap.error("input and output required (or --selftest)")
    return process(args.input, args.output, args.tol, args.keep_tol, args.size, args.bg)


if __name__ == "__main__":
    sys.exit(main())
