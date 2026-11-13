#!/usr/bin/env python3
"""denoise_atlas.py — remove sub-texel texture speckle from a baked atlas.

The grimdark material library carries high-frequency camo/weave detail authored
for boxy kit meshes. On curved base-mesh surfaces at the 2 cm texel grid that
detail lands at 1-2 texels and palette-locks to speckle. A median pass removes
the sub-texel noise while keeping the island shapes and the large flat panels,
so the palette lock reads material blocks instead of static.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--size", type=int, default=5)
    a = ap.parse_args()
    p = Path(a.path)
    im = Image.open(p).convert("RGB")
    im = im.filter(ImageFilter.MedianFilter(a.size))
    im.save(p)
    print(f"DENOISED {p} median {a.size}")


if __name__ == "__main__":
    main()
