#!/usr/bin/env python3
"""Fixed master palette for the MTC zombie emote family ("Rot & Bile", 28 colours).

Single source of truth: pixelise.py maps every asset to this palette and
verify_pixel_asset.py audits shipped PNGs against it. Sets must share ONE
palette - never k-means per image.
"""

# category: [(hex, ...), ...]
ROT_AND_BILE = {
    "contour":  ["#12101A", "#241D35", "#3B314C"],
    "skin":     ["#2F4822", "#4B692F", "#769B3D", "#A7C854"],
    "gore":     ["#4A1224", "#8A1E34", "#C7383C", "#E86B79"],
    "bone":     ["#4E493B", "#A89F81", "#EDE3C2"],
    "eye":      ["#E0A526", "#FCEE54"],
    "denim":    ["#1E2738", "#2E3E5C", "#46628A", "#7B93B8"],
    "drab":     ["#26241E", "#484134", "#6E634E", "#9C8E72"],
    "badge":    ["#523B08", "#9E7413", "#E8AE23", "#FFE373"],
}

INK = ROT_AND_BILE["contour"][0]  # the re-imposed outline colour


def palette_list():
    """Flat [(r, g, b), ...] in category order."""
    out = []
    for cols in ROT_AND_BILE.values():
        for h in cols:
            out.append(tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)))
    return out
