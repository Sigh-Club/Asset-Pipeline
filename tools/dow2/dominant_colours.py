"""dominant_colours.py — the real colour scheme of a DoW2 part, from its own texture.

Our units were flat-filled with one palette colour per faction, which is why they read as
monochrome. The shipped `_dif.dds` next to each part carries the actual colours (skin, leather,
metal, cloth). This samples the dominant ones so a unit can be coloured from its own art instead of
from a faction constant.

Usage: python3 tools/dow2/dominant_colours.py <part.model|dir> [n]
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import Counter
from PIL import Image


def dominant(source: Path, n: int = 6) -> list[tuple[int, int, int]]:
    base = source if source.is_dir() else source.parent
    dds = sorted(base.glob("*_dif.dds")) or sorted(base.parent.glob("*_dif.dds"))
    if not dds:
        return []
    img = Image.open(dds[0]).convert("RGB")
    img.thumbnail((128, 128))
    counts: Counter[tuple[int, int, int]] = Counter()
    for px in img.getdata():
        # quantise to 24 levels per channel so texture noise collapses into usable tones
        counts[tuple((c // 24) * 24 + 12 for c in px)] += 1
    out = []
    for (r, g, b), _ in counts.most_common(64):
        if r + g + b < 30:            # skip near-black padding
            continue
        if all(abs(r - o[0]) + abs(g - o[1]) + abs(b - o[2]) > 60 for o in out):
            out.append((r, g, b))
        if len(out) >= n:
            break
    return out


if __name__ == "__main__":
    src = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    for c in dominant(src, n):
        print("0x%02x%02x%02x" % c)
