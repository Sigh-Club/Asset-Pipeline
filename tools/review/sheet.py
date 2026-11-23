#!/usr/bin/env python3
"""sheet.py — package ONE reference-vs-render comparison sheet for review.

The review loop judges from exactly one image (img2threejs, ARCHITECTURE.md: "One
image per review… not a scattering of screenshots"), and the vision model is the
only thing that may approve a pass. This tool builds that one image: the target
reference on the left, the candidate render on the right, both labelled, on an
opaque background.

Rules this tool keeps deliberately:
  * No measurements are drawn on the sheet. Numbers belong in the JSON, or the
    model just parrots them back instead of looking.
  * No cropping tricks, no aspect distortion, no sharpening. LANCZOS resize only.
  * Alpha is composited onto a flat mid-grey: Gemini has no alpha channel, and a
    transparent region read as black would be judged as a material fault.
  * The panel order and labels are fixed, so a model that reads left-to-right
    cannot mistake which side is the target.

Usage:
  sheet.py --reference ref.png --candidate out/render.png --out /tmp/sheet.png
  sheet.py --reference ref.png --candidate a.png --candidate b.png \
      --out /tmp/sheet.png --label "cinderborn_cinder_cultist"
  sheet.py ... --json          # emit {sheet, panels, size} for scripting

Exit 0 on success, 1 on a missing/unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (58, 58, 58)          # sheet background
PANEL = (74, 74, 74)       # panel plate
INK = (235, 235, 235)      # label ink
DIM = (170, 170, 170)      # secondary ink
ACCENT_REF = (120, 190, 255)
ACCENT_CAND = (255, 190, 120)

CAPTION_H = 34             # per-panel caption strip
HEADER_H = 30
PAD = 12
MAX_PANEL = 620            # longest panel edge, keeps the upload small


def _font(size: int):
    for name in ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Regular.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def load_panel(path: Path) -> Image.Image:
    """Open, composite alpha onto the plate colour, and cap the size."""
    im = Image.open(path)
    im.load()
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        plate = Image.new('RGBA', im.size, PANEL + (255,))
        plate.alpha_composite(im)
        im = plate.convert('RGB')
    else:
        im = im.convert('RGB')
    w, h = im.size
    scale = min(MAX_PANEL / max(w, h), 1.0)
    if scale < 1.0:
        im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    return im


def build(reference: Path, candidates: list[Path], label: str) -> Image.Image:
    panels = [(load_panel(reference), 'REFERENCE  (the target)', ACCENT_REF)]
    for i, c in enumerate(candidates):
        tag = 'RENDER  (the candidate)' if len(candidates) == 1 else \
              f'RENDER {i + 1}/{len(candidates)}  (the candidate)'
        panels.append((load_panel(c), tag, ACCENT_CAND))

    panel_w = max(p.width for p, _, _ in panels)
    panel_h = max(p.height for p, _, _ in panels)
    cell_w = panel_w + PAD * 2
    cell_h = panel_h + CAPTION_H + PAD * 2
    sheet = Image.new('RGB', (cell_w * len(panels), HEADER_H + cell_h), BG)
    d = ImageDraw.Draw(sheet)

    title = f'IoA asset review — {label}' if label else 'IoA asset review'
    d.text((PAD, 8), title, font=_font(17), fill=INK)
    d.text((sheet.width - PAD, 10), 'left = target   right = candidate',
           font=_font(13), fill=DIM, anchor='ra')

    for i, (im, caption, accent) in enumerate(panels):
        x0 = i * cell_w
        d.rectangle([x0 + 1, HEADER_H, x0 + cell_w - 1, HEADER_H + cell_h - 1],
                    outline=(96, 96, 96), width=1)
        d.text((x0 + PAD, HEADER_H + 8), caption, font=_font(14), fill=accent)
        d.rectangle([x0 + PAD, HEADER_H + CAPTION_H,
                     x0 + PAD + panel_w, HEADER_H + CAPTION_H + panel_h], fill=PANEL)
        sheet.paste(im, (x0 + PAD + (panel_w - im.width) // 2,
                         HEADER_H + CAPTION_H + (panel_h - im.height) // 2))
    return sheet


def main() -> int:
    p = argparse.ArgumentParser(description='build one reference-vs-render review sheet')
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--candidate', required=True, action='append', type=Path,
                   help='candidate render (repeatable)')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--label', default='', help='asset id shown in the header')
    p.add_argument('--json', action='store_true')
    a = p.parse_args()

    for path in [a.reference, *a.candidate]:
        if not path.exists():
            print(json.dumps({'error': f'no such image: {path}'}))
            return 1
    try:
        sheet = build(a.reference, a.candidate, a.label)
    except Exception as e:
        print(json.dumps({'error': f'{type(e).__name__}: {e}'}))
        return 1

    a.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.out)
    if a.json:
        print(json.dumps({'sheet': str(a.out), 'size': list(sheet.size),
                          'panels': 1 + len(a.candidate)}))
    else:
        print(a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
