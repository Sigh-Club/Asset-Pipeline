#!/usr/bin/env python3
"""Recolour a DoW faction atlas into an IoA faction palette (selective hue shift).

DoW's Blood Ravens red is remapped to the Iron Directorate forge-blue while gold,
steel, bone and skin are preserved (only saturated red hues move). This is the
re-skin step for the DoW import path — no geometry change.

Usage: recolour_atlas.py IN.png OUT.png --hue 0.58 --sat 0.55
"""
import argparse
import colorsys
from pathlib import Path

from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--hue', type=float, default=0.58, help='target hue 0..1 (0.58 = blue)')
    ap.add_argument('--sat', type=float, default=0.52, help='target saturation ceiling')
    ap.add_argument('--min-sat', type=float, default=0.22, help='only pixels above this saturation move')
    a = ap.parse_args()

    img = Image.open(a.src).convert('RGBA')
    out = img.copy()
    src_px = img.load()
    dst_px = out.load()
    w, h = img.size
    moved = 0
    for y in range(h):
        for x in range(w):
            r, g, b, alpha = src_px[x, y]
            hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            # red/orange hues only (Blood Ravens cloth + armour panels)
            is_red = (hh < 0.075 or hh > 0.94) and ss >= a.min_sat
            if is_red:
                ss = min(a.sat, ss * 1.05)
                rr, gg, bb = colorsys.hsv_to_rgb(a.hue, ss, vv)
                dst_px[x, y] = (int(rr * 255), int(gg * 255), int(bb * 255), alpha)
                moved += 1
    out.save(a.dst)
    print(f'{a.dst}: remapped {moved} red pixels ({moved/(w*h)*100:.1f}%) to hue {a.hue}')


if __name__ == '__main__':
    main()
