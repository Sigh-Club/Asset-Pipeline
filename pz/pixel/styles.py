#!/usr/bin/env python3
"""Named pixel-art style presets bundling every style dial.

Each preset: fixed palette (see palette.py), target sprite size, dither mode,
ink (outline) colour, and the prompt fragment comfy_gen.py appends. One flag
drives the whole chain:

    pixelise.py in.png out.png --style gameboy
    comfy_gen.py "..." out.png --style rotbile

Adding a style = adding an entry here. See PIXEL_STYLES.md for the research.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from palette import palette_list, ROT_AND_BILE  # noqa: E402


def _hexes(hexes):
    return [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in hexes]


GAMEBOY = _hexes(["#0f380f", "#306230", "#8bac0f", "#9bbc0f"])
PICO8 = _hexes([
    "#1D2B53", "#7E2553", "#008751", "#AB5236", "#5F574F", "#C2C3C7",
    "#FFF1E8", "#FF004D", "#FFA300", "#FFEC27", "#00E436", "#29ADFF",
    "#83769C", "#FF77A8", "#FFCCAA", "#000000",
])
DB16 = _hexes([
    "#140c1c", "#442434", "#30346d", "#4e4a4e", "#854c30", "#346524",
    "#d04648", "#757161", "#597dce", "#d27d2c", "#8595a1", "#6daa2c",
    "#d2aa99", "#6dc2ca", "#dad45e", "#deeed6",
])

STYLES = {
    # our house style: hue-shifted 28-colour ramps, detail-max dither
    # outline 0.62 / ink_luma 0.22 tuned 2026-10-05: keeps faces light
    "rotbile": {
        "palette": palette_list(),
        "size": 128,
        "dither": "bayer4",
        "ink": (18, 16, 26),
        "outline": 0.62,
        "ink_luma": 0.22,
        "prompt": ("thick bold black outlines, flat cel shading, rich detail, "
                   "modern indie pixel art style"),
    },
    # the canonical "proper indie" look: DawnBringer 16
    "db16": {
        "palette": DB16,
        "size": 64,
        "dither": "none",
        "ink": (20, 12, 28),
        "prompt": ("DawnBringer 16 palette pixel art, clean selective outlines, "
                   "hue-shifted shading, crisp single-pixel detail"),
    },
    # authentic Game Boy DMG: exactly 4 green shades
    "gameboy": {
        "palette": GAMEBOY,
        "size": 64,
        "dither": "none",
        "ink": (15, 56, 15),
        "prompt": ("Game Boy style 4-shade green pixel art, chunky pixels, "
                   "monochrome green palette"),
    },
    # PICO-8 toy look
    "pico8": {
        "palette": PICO8,
        "size": 64,
        "dither": "bayer2",
        "ink": (0, 0, 0),
        "prompt": ("PICO-8 16-colour pixel art style, warm limited palette, "
                   "tiny sprite aesthetic"),
    },
}


def get_style(name):
    if name not in STYLES:
        raise KeyError("unknown style %r (have: %s)" % (name, ", ".join(STYLES)))
    return STYLES[name]
