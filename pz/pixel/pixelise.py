#!/usr/bin/env python3
"""Programmatic pixeliser: smooth cel-shaded master -> true pixel sprite.

Recipe (2026-10 pipeline consultation, see GEMINI_CONSULTATION.md replies):
  1. FILL: box (area) downsample of the master - preserves local colour mass
     far better than Lanczos, which makes colour soup at sharp edges,
  2. OUTLINE: dark-ink mask extracted at master scale, area-downsampled and
     thresholded (default 0.40) into a solid outline layer,
  3. PALETTE: nearest colour in the FIXED reference palette measured in Oklab
     (raw-RGB distance distorts greens/purples; k-means destroys set-wide
     consistency),
  4. outline re-imposed over the quantised interior,
  5. orphan pixels (no identical orthogonal neighbour) adopt their darkest
     opaque neighbour.

Input must be a cut master (transparent background, binary alpha) as produced
by cut_emotes.py masters. Masters should be flat cel-shaded with thick ink
outlines (6-8px at ~1024px) - soft gradients turn into noise.

    pixelise.py in.png out.png [--size 128] [--outline 0.40] [--selftest]
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from palette import INK, palette_list  # noqa: E402
import styles as style_registry  # noqa: E402

BAYER2 = np.array([[0, 2], [3, 1]], float) / 4.0 - 0.5
BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9],
                   [15, 7, 13, 5]], float) / 16.0 - 0.5


def _srgb_to_linear(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_oklab(rgb):
    """rgb float array (..., 3) in 0..255 -> Oklab (..., 3)."""
    lin = _srgb_to_linear(rgb)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    lms = lin @ m1.T
    lms = np.cbrt(lms)
    return lms @ m2.T


def nearest_palette(rgb, pal):
    """Map rgb (H,W,3 uint8) to nearest palette entry in Oklab."""
    pal_lab = to_oklab(np.array(pal, dtype=float))
    lab = to_oklab(rgb.astype(float))
    flat = lab.reshape(-1, 3)
    # (N, P) distances to each palette entry
    d = ((flat[:, None, :] - pal_lab[None, :, :]) ** 2).sum(-1)
    idx = d.argmin(1)
    pal = np.array(pal, dtype=np.uint8)
    return pal[idx].reshape(rgb.shape)


def orphan_fix(a, iters=3):
    """Opaque pixels with no identical orthogonal neighbour adopt their
    darkest opaque neighbour's colour (dark merge keeps outlines coherent)."""
    for _ in range(iters):
        rgb, al = a[:, :, :3].astype(int), a[:, :, 3]
        op = al == 255
        has_same = np.zeros(al.shape, bool)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb_rgb = np.roll(np.roll(rgb, dy, 0), dx, 1)
            nb_al = np.roll(np.roll(al, dy, 0), dx, 1)
            has_same |= (rgb == nb_rgb).all(-1) & op & (nb_al == 255)
        orphan = op & ~has_same
        orphan[0, :] = orphan[-1, :] = False
        orphan[:, 0] = orphan[:, -1] = False
        if not orphan.any():
            break
        ys, xs = np.where(orphan)
        for y, x in zip(ys, xs):
            best, best_l = None, 1e9
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if al[ny, nx] == 255:
                    l = (rgb[ny, nx] * [0.299, 0.587, 0.114]).sum()
                    if l < best_l:
                        best, best_l = rgb[ny, nx].copy(), l
            if best is not None:
                a[y, x, :3] = best
    return a


def pixelise(img, size, outline_thr=0.40, ink_luma=0.35, palette=None,
             dither="none", ink=None):
    """RGBA PIL image -> pixelised RGBA PIL image at size x size.

    palette: fixed target palette (default: house Rot & Bile).
    dither:  none | bayer2 | bayer4 - ordered perturbation of the fill BEFORE
             quantisation, producing checkerboard transitions between ramp
             steps (the console-era look).
    ink:     outline colour (default: the palette's contour ink)."""
    img = img.convert("RGBA")
    # 1+2. area downsample fill; ink = BINARY dark mask at master scale,
    # area-downsampled then thresholded (NOT the raw luminance - that would
    # mark everything mid-bright as ink)
    fill = np.array(img.resize((size, size), Image.BOX))
    luma = np.array(img.convert("L")).astype(float) / 255.0
    opa = np.array(img.split()[3]).astype(float) / 255.0
    ink_bin = ((luma < ink_luma) & (opa > 0.5)).astype(float)
    ink_mask_img = Image.fromarray((ink_bin * 255).astype(np.uint8), "L")
    ink_frac = np.array(ink_mask_img.resize((size, size), Image.BOX)).astype(float) / 255.0

    # 3. optional ordered dither, then palette mapping in Oklab
    rgba = fill.copy()
    op = rgba[:, :, 3] > 127
    if dither in ("bayer2", "bayer4"):
        b = BAYER2 if dither == "bayer2" else BAYER4
        tile = np.tile(b, (size // b.shape[0] + 1, size // b.shape[1] + 1))[:size, :size]
        perturb = (tile[:, :, None] * 24.0).astype(int)
        body = rgba[:, :, :3].astype(int)
        body[op] = np.clip(body[op] + perturb[op], 0, 255)
        rgba[:, :, :3] = body.astype(np.uint8)
    pal = palette if palette is not None else palette_list()
    rgba[:, :, 3] = np.where(op, 255, 0).astype(np.uint8)
    if op.any():
        rgba[op, :3] = nearest_palette(rgba[op, :3], pal)

    # 4. re-impose ink outline
    ink_rgb = ink if ink is not None else tuple(int(INK[i:i + 2], 16) for i in (1, 3, 5))
    rgba[ink_frac >= outline_thr, :3] = ink_rgb

    # 5. orphan cleanup + hard alpha
    rgba = orphan_fix(rgba)
    return Image.fromarray(rgba, "RGBA")


def selftest():
    """Synthetic flat-cel sprite: hard outline, 3-tone shading, text blob.
    Verify binary alpha, palette compliance, outline presence, no orphans."""
    w = 512
    img = Image.new("RGBA", (w, w), (255, 255, 255, 0))
    px = img.load()
    GREEN, DARK, BONE = (118, 155, 61), (47, 72, 34), (237, 227, 194)
    for y in range(64, 448):
        for x in range(96, 416):
            edge = min(x - 96, 415 - x, y - 64, 447 - y) < 24
            px[x, y] = ((18, 16, 26, 255) if edge else
                        (DARK + (255,)) if y < 200 else
                        (GREEN + (255,)) if y < 380 else (BONE + (255,)))
    out = np.array(pixelise(img, 128))
    al = out[:, :, 3]
    problems = []
    if not np.all(np.isin(al, (0, 255))):
        problems.append("alpha not binary")
    pal = set(palette_list())
    used = set(map(tuple, out[al == 255][:, :3]))
    off = used - pal
    if off:
        problems.append("off-palette colours: %s" % list(off)[:3])
    ink_px = (out[:, :, :3] == (18, 16, 26)).all(-1).sum()
    if ink_px < 200:
        problems.append("outline lost (%d ink px)" % ink_px)
    # orphan check (same definition as verify_pixel_asset)
    rgb, a2 = out[:, :, :3].astype(int), out[:, :, 3]
    orphans = 0
    for y in range(1, 127):
        for x in range(1, 127):
            if a2[y, x] != 255:
                continue
            c = rgb[y, x]
            nbs = [rgb[y - 1, x], rgb[y + 1, x], rgb[y, x - 1], rgb[y, x + 1]]
            if not any((c == n).all() for n in nbs):
                orphans += 1
    if orphans:
        problems.append("%d orphan pixels" % orphans)
    if problems:
        for p in problems:
            print("FAIL:", p)
        return 1
    print("selftest OK: binary alpha, on-palette, outline present, no orphans")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Palette-locked pixeliser")
    ap.add_argument("input", nargs="?")
    ap.add_argument("output", nargs="?")
    ap.add_argument("--size", type=int, default=0, choices=(0, 64, 128, 256))
    ap.add_argument("--outline", type=float, default=0.40)
    ap.add_argument("--ink-luma", type=float, default=0.35)
    ap.add_argument("--style", help="named preset (see styles.py); palette, "
                    "size, dither and ink all follow it unless overridden")
    ap.add_argument("--dither", choices=("none", "bayer2", "bayer4"))
    ap.add_argument("--palette-file", help="txt: one #rrggbb per line")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.input or not a.output:
        ap.error("input and output required (or --selftest)")
    size, outline_thr, ink_luma = a.size, a.outline, a.ink_luma
    outline_given = a.outline != 0.40
    ink_luma_given = a.ink_luma != 0.35
    dither, ink, pal = a.dither, None, None
    if a.style:
        st = style_registry.get_style(a.style)
        size = size or st["size"]
        dither = dither or st["dither"]
        ink = st["ink"]
        pal = st["palette"]
        if not outline_given:
            outline_thr = st.get("outline", outline_thr)
        if not ink_luma_given:
            ink_luma = st.get("ink_luma", ink_luma)
    if a.palette_file:
        pal = [tuple(int(h.strip()[i:i + 2], 16) for i in (1, 3, 5))
               for h in open(a.palette_file) if h.strip().startswith("#")]
    size = size or 128
    dither = dither or "none"
    pixelise(Image.open(a.input), size, outline_thr, ink_luma, pal, dither,
             ink).save(a.output)
    print("wrote", a.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
