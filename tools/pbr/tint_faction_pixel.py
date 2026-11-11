#!/usr/bin/env python3
"""tint_faction_pixel.py — rebuild a faction kit's pixel albedo on its identity ramp.

The image-generated material sheets are ash-toned by design ("ash-black with
purple-pink witchfire heat staining"). At the 32-50 px pixel-variant size the
staining averages out, so the palette lock snaps the slot to grey and the whole
faction reads as the Directorate. This preserves the source luminance and
texture detail but maps it onto the faction's authoritative ramp.

Writes `albedo_pixel.png` in place (original kept as `albedo_pixel_src.png`) and
records the ramp in `pixel_tint.json`. Rebuild the pixel library afterwards:
    blender -b -P tools/pbr/build_blender_library.py -- --pixel --only cinderborn
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "materials" / "faction_pixel_ramps.json"


def hex_rgb(value: str):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--faction", required=True)
    p.add_argument("--scope", default="all", choices=("all", "faction"),
                   help="all = every slot; faction = the configured slots")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def percentiles(grey, lo=2, hi=98):
    hist = grey.histogram()
    total = sum(hist)
    acc = 0
    lo_v = 0
    hi_v = 255
    for i, n in enumerate(hist):
        acc += n
        if acc >= total * lo / 100:
            lo_v = i
            break
    acc = 0
    for i, n in enumerate(hist):
        acc += n
        if acc >= total * hi / 100:
            hi_v = i
            break
    return lo_v, max(hi_v, lo_v + 1)


def recolour(path: Path, stops):
    src = path.read_bytes()
    img = Image.open(path).convert("RGB")
    grey = img.convert("L")
    lo, hi = percentiles(grey)
    ramp = [hex_rgb(s) for s in stops]
    lut = []
    for v in range(256):
        t = min(1.0, max(0.0, (v - lo) / (hi - lo)))
        pos = t * (len(ramp) - 1)
        i = min(len(ramp) - 2, int(pos))
        f = pos - i
        a, b = ramp[i], ramp[i + 1]
        lut.append(tuple(round(a[c] * (1 - f) + b[c] * f) for c in range(3)))
    import numpy as np
    arr = np.array(img)
    lum = np.array(grey)
    out = np.zeros_like(arr)
    for i, colour in enumerate(lut):
        out[lum == i] = colour
    Image.fromarray(out, "RGB").save(path)
    return src


def main():
    args = parse_args()
    cfg = json.loads(CONFIG.read_text())["factions"][args.faction]
    changed = []
    for slot, ramp in cfg["slots"].items():
        item = ROOT / "assets" / "materials" / "grimdark_scifi" / f"{args.faction}__{slot}"
        path = item / "albedo_pixel.png"
        if not path.exists():
            print(f"skip {slot}: no albedo_pixel.png")
            continue
        src = item / "albedo_pixel_src.png"
        if not src.exists() and not args.dry_run:
            src.write_bytes(path.read_bytes())
        if args.dry_run:
            print(f"would tint {path} -> {ramp}")
            continue
        recolour(path, ramp)
        (item / "pixel_tint.json").write_text(json.dumps({
            "ramp": ramp, "source": "albedo_pixel_src.png",
            "because": "generated sheet is ash-toned; faction hue lost at pixel-variant size",
        }, indent=2) + "\n")
        changed.append(slot)
    print(f"TINTED {args.faction}: {', '.join(changed) if changed else 'nothing'}")


main()
