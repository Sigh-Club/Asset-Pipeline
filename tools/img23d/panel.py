#!/usr/bin/env python3
"""panel.py — cut clean, per-view object panels out of a multi-view spec sheet.

Spec sheets (the Gemini concept sheets, shipped game art sheets) put several orthographic views on one
canvas with leader lines, dimension callouts, a title block and a grid. Hunyuan3D-2mv wants ONE object
per view, white background, nothing else in frame — so the sheet has to be split first. Feeding a whole
sheet makes the model fuse the annotations into the geometry.

What this does per view: crop the panel, drop the 1-3 px leader/dimension lines with a morphological
opening, keep the largest connected ink component, fill its holes, restore its outline, and write an
RGBA PNG on true alpha (the shape stage trusts real alpha and skips rembg).

Two options exist because of how the multiview preprocessor behaves (`hy3dgen/shapegen/preprocessors.py`
MVImageProcessorV2.recenter): it rescales EVERY view independently so that view's silhouette fills the
frame. Relative scale between views is therefore destroyed, and an elongated object (a rifle seen
muzzle-on) gets its cross-section inflated to the length of the gun. `--extent VIEW=W:H` re-cases one
view on a canvas of its true projected bounding box, which restores the correct proportion.

Usage:
  panel.py sheet.png --out DIR --box front:170,300,440,510 --box side:1120,310,580,560
  panel.py sheet.png --out DIR --box side:560,190,2200,850 --mirror left=side
  panel.py sheet.png --out DIR --box front:90,200,380,830 --extent front=1.994:0.863 \\
      --box side:560,190,2200,850 --mirror left=side

Boxes are `x,y,w,h` in sheet pixels; find them by cropping and looking, not by guessing.
`--extent` numbers come from the sheet's own dimensions or from a panel already at a known scale.
Writes `<out>/<view>.png` and `<out>/panels.json` (boxes, sizes, mask areas, extents applied).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def ink_mask(rgb: np.ndarray) -> np.ndarray:
    """Anything meaningfully darker or more colourful than paper."""
    grey = rgb.mean(2)
    chroma = rgb.max(2).astype(np.int16) - rgb.min(2).astype(np.int16)
    return ((grey < 205) | (chroma > 28)).astype(np.uint8) * 255


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill enclosed background: flood the outside, invert, union."""
    h, w = mask.shape
    flood = mask.copy()
    cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 255)
    return cv2.bitwise_or(mask, cv2.bitwise_not(flood))


def extract_panel(sheet: np.ndarray, box, open_px: int, keep: int, pad: int) -> Image.Image:
    x, y, w, h = box
    sub = sheet[y:y + h, x:x + w]
    if sub.size == 0:
        raise SystemExit(f"box {box} is outside the sheet")
    ink = ink_mask(sub)
    # leader lines and callout rules are 1-3 px: an opening deletes them, the object survives
    core = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px, open_px)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(core, 8)
    if n <= 1:
        raise SystemExit(f"no object in box {box} — widen it or lower --open")
    order = np.argsort(stats[1:, cv2.CC_STAT_AREA])[::-1][:keep] + 1
    obj = np.isin(labels, order).astype(np.uint8) * 255
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    obj = fill_holes(obj)
    obj = cv2.dilate(obj, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_px + 1, open_px + 1)))
    obj = fill_holes(obj)
    ys, xs = np.nonzero(obj)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + 1 + pad, obj.shape[0])
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + 1 + pad, obj.shape[1])
    rgba = np.dstack([sub, obj])[y0:y1, x0:x1]
    return Image.fromarray(rgba, "RGBA")


def apply_extent(panel: Image.Image, extent: tuple[float, float]) -> Image.Image:
    """Re-case the object on a canvas of its true projected bbox.

    The object is scaled to fill the extent's short side and centred; the rest of the canvas is white
    with alpha=1, so it is invisible in the model's white composite but still counts in the mask bbox —
    which is the whole point: recenter() will then scale by the TRUE extent, not by the silhouette.
    """
    ew, eh = extent
    cw, ch = (2000, max(1, round(2000 * eh / ew)))
    a = np.asarray(panel)
    ys, xs = np.nonzero(a[..., 3] > 8)
    obj = panel.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    scale = min(cw / obj.width, ch / obj.height)
    obj = obj.resize((max(1, round(obj.width * scale)), max(1, round(obj.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (cw, ch), (255, 255, 255, 1))
    canvas.paste(obj, ((cw - obj.width) // 2, (ch - obj.height) // 2), obj)
    return canvas


def parse_box(spec: str) -> tuple[str, tuple[int, int, int, int]]:
    name, _, nums = spec.partition(":")
    parts = [int(float(v)) for v in nums.replace(" ", ",").split(",") if v]
    if len(parts) != 4:
        raise SystemExit(f"--box {spec}: need view:x,y,w,h")
    return name, tuple(parts)


def parse_extent(spec: str) -> tuple[str, tuple[float, float]]:
    name, _, nums = spec.partition("=")
    parts = [float(v) for v in nums.split(":") if v]
    if len(parts) != 2:
        raise SystemExit(f"--extent {spec}: need view=W:H")
    return name, (parts[0], parts[1])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("sheet", type=Path, help="spec sheet image")
    p.add_argument("--out", type=Path, required=True, help="output directory")
    p.add_argument("--box", action="append", default=[], metavar="VIEW:X,Y,W,H",
                   help="panel to cut (repeat per view)")
    p.add_argument("--extent", action="append", default=[], metavar="VIEW:W:H",
                   help="true projected bbox for that view; re-cases it so multiview scale survives")
    p.add_argument("--mirror", action="append", default=[], metavar="NEW=SRC",
                   help="write NEW as a horizontal flip of SRC (2mv wants both sides)")
    p.add_argument("--open", type=int, default=5, help="opening kernel px; raise it if leader lines survive")
    p.add_argument("--keep", type=int, default=1, help="how many connected components to keep per view")
    p.add_argument("--pad", type=int, default=12, help="transparent margin px around the object")
    args = p.parse_args()

    sheet = np.asarray(Image.open(args.sheet).convert("RGB"))
    boxes = [parse_box(s) for s in args.box]
    extents = dict(parse_extent(s) for s in args.extent)
    stray = sorted(set(extents) - {name for name, _ in boxes})
    if stray:
        sys.exit(f"--extent names no --box view: {', '.join(stray)}")
    if not boxes:
        sys.exit("nothing to do: pass at least one --box VIEW:X,Y,W,H")
    args.out.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {"sheet": str(args.sheet), "views": {}}
    for name, box in boxes:
        panel = extract_panel(sheet, box, args.open, args.keep, args.pad)
        if name in extents:
            panel = apply_extent(panel, extents[name])
        path = args.out / f"{name}.png"
        panel.save(path)
        coverage = float(np.mean(np.asarray(panel)[..., 3] > 8))
        manifest["views"][name] = {"box": list(box), "file": str(path), "size": list(panel.size),
                                  "silhouette_fraction": round(coverage, 4),
                                  "extent": list(extents.get(name, [])) or None}
        print(f"{path}  {panel.size[0]}x{panel.size[1]}  silhouette={coverage:.1%}")

    for spec in args.mirror:
        new, _, src = spec.partition("=")
        origin = args.out / f"{src}.png"
        if not origin.exists():
            sys.exit(f"--mirror {spec}: {origin} does not exist")
        path = args.out / f"{new}.png"
        Image.open(origin).transpose(Image.FLIP_LEFT_RIGHT).save(path)
        manifest["views"][new] = {**manifest["views"].get(src, {}), "file": str(path),
                                  "mirrored_from": src}
        print(f"{path}  mirrored from {src}")

    (args.out / "panels.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{args.out / 'panels.json'}")


if __name__ == "__main__":
    main()
