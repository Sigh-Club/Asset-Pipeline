#!/usr/bin/env python3
"""
paint_unit_diffuse.py — Generate per-unit painted diffuse + team-colour mask atlases.

DoW1-style texture detail: panel lines, rivets, aquila, chapter insignia and edge-wear
PAINTED into a per-unit diffuse texture, plus an RGBA team-colour mask for runtime
faction/player tinting. Large detail lives in the texture (survives LANCZOS downscale),
NOT in geometry (which blurs away at sprite scale).

Outputs (per unit), into the unit's model/ dir:
  <unit_name>_diffuse.png   — painted diffuse atlas (RGBA, sRGB)
  <unit_name>_teammask.png  — team-colour mask (RGBA):
      R = primary armour (tintable)
      G = secondary armour (tintable)
      B = accent/trim tintable
      A = emissive/lens mask
      0 = fixed colour (not tintable, e.g. gold trim, dark lenses)

Atlas layout: 1024x1024, 4x4 grid of 256x256 tiles, one tile per body part:
  row 0: torso, helmet, pauldron, upper_arm
  row 1: forearm, thigh, shin, boot
  row 2: belt, backpack, weapon, codpiece
  row 3: (spare)

Usage:
  python3 paint_unit_diffuse.py --config configs/iron_directorate/iron_directorate_line_infantry.json
  python3 paint_unit_diffuse.py --batch configs/
"""

import os
import sys
import json
import math
import random
from PIL import Image, ImageDraw, ImageFilter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))

ATLAS_SIZE = 1024
TILE = 256          # 4x4 grid
TILES_PER_ROW = 4
MARGIN = 8          # intra-tile margin so detail doesn't bleed across tile borders

# Tile (row, col) per body part. Single source of truth: atlas_layout.py
# (also imported by the geometry generator so UVs match the painted atlas).
from atlas_layout import TILE_LAYOUT

# =============================================================================
# FACTION PALETTES  (primary, secondary, trim, dark, lens)
# =============================================================================
# primary  = main armour (tintable team colour 1)
# secondary= under-armour / secondary plates (tintable team colour 2)
# trim     = faction metal trim (fixed gold/brass)
# dark     = dark lining/lenses (fixed)
# lens     = emissive eye/lens (fixed)
FACTION_PALETTE = {
    "iron_directorate": {
        "primary":   (96, 110, 128),   # blue-grey steel
        "secondary": (54, 60, 66),      # dark gunmetal under-armour
        "trim":      (212, 160, 36),    # imperial gold
        "dark":      (28, 30, 34),      # visor / panel-line dark
        "lens":      (90, 120, 150),    # cool blue lens
    },
    "cinderborn": {
        "primary":   (74, 48, 92),      # deep purple
        "secondary": (40, 30, 40),
        "trim":      (180, 110, 40),    # brass/orange
        "dark":      (20, 16, 22),
        "lens":      (220, 110, 40),    # magma orange
    },
    "parasitic_bloom": {
        "primary":   (96, 130, 70),
        "secondary": (130, 80, 96),
        "trim":      (200, 188, 160),   # bone
        "dark":      (30, 36, 26),
        "lens":      (160, 220, 120),
    },
    "wreckstorm_clans": {
        "primary":   (120, 60, 36),     # rust red
        "secondary": (74, 56, 40),      # scrap brown
        "trim":      (214, 176, 48),    # hazard yellow
        "dark":      (30, 22, 18),
        "lens":      (220, 120, 40),
    },
    "harmonic_collective": {
        "primary":   (200, 204, 210),   # clean white
        "secondary": (70, 110, 200),    # bright blue
        "trim":      (180, 184, 192),   # silver
        "dark":      (40, 44, 52),
        "lens":      (110, 200, 255),
    },
    "chrono_revenants": {
        "primary":   (120, 96, 52),     # aged bronze
        "secondary": (48, 96, 96),      # teal
        "trim":      (150, 140, 60),    # gold-green
        "dark":      (30, 32, 28),
        "lens":      (90, 220, 200),
    },
    "void_corsairs": {
        "primary":   (60, 44, 92),      # dark purple
        "secondary": (44, 56, 96),      # deep blue
        "trim":      (170, 176, 190),   # silver
        "dark":      (20, 22, 30),
        "lens":      (130, 110, 230),
    },
}
FACTION_DEFAULT = "iron_directorate"


# =============================================================================
# DRAWING HELPERS
# =============================================================================

def tile_rect(row, col):
    """Pixel rect (x0,y0,x1,y1) for a tile, with intra-tile margin."""
    x0 = col * TILE + MARGIN
    y0 = row * TILE + MARGIN
    x1 = (col + 1) * TILE - MARGIN
    y1 = (row + 1) * TILE - MARGIN
    return x0, y0, x1, y1


def fill_tile(draw, row, col, colour):
    x0, y0, x1, y1 = tile_rect(row, col)
    draw.rectangle([x0, y0, x1, y1], fill=colour)


def shade(colour, amt):
    """Lighten (amt>0) or darken (amt<0) a colour, amt in -1..1."""
    r, g, b = colour[:3]
    if amt >= 0:
        return (int(r + (255 - r) * amt), int(g + (255 - g) * amt), int(b + (255 - b) * amt))
    f = 1 + amt
    return (int(r * f), int(g * f), int(b * f))


def panel_line_h(draw, row, col, y_frac, thickness, colour):
    """Horizontal panel line across a tile at fractional y (0=top,1=bottom)."""
    x0, y0, x1, y1 = tile_rect(row, col)
    y = int(y0 + (y1 - y0) * y_frac)
    draw.rectangle([x0, y, x1, y + thickness], fill=colour)


def panel_line_v(draw, row, col, x_frac, thickness, colour):
    x0, y0, x1, y1 = tile_rect(row, col)
    x = int(x0 + (x1 - x0) * x_frac)
    draw.rectangle([x, y0, x + thickness, y1], fill=colour)


def rivet_row_h(draw, row, col, y_frac, count, radius, colour):
    """A horizontal row of rivets across a tile."""
    x0, y0, x1, y1 = tile_rect(row, col)
    y = int(y0 + (y1 - y0) * y_frac)
    step = (x1 - x0) / (count + 1)
    for i in range(count):
        cx = int(x0 + step * (i + 1))
        draw.ellipse([cx - radius, y - radius, cx + radius, y + radius], fill=colour)


def rivet_row_v(draw, row, col, x_frac, count, radius, colour):
    x0, y0, x1, y1 = tile_rect(row, col)
    x = int(x0 + (x1 - x0) * x_frac)
    step = (y1 - y0) / (count + 1)
    for i in range(count):
        cy = int(y0 + step * (i + 1))
        draw.ellipse([x - radius, cy - radius, x + radius, cy + radius], fill=colour)


def edge_highlight(draw, row, col, inset, colour):
    """Paint a lighter edge band around the tile (bevel/highlight)."""
    x0, y0, x1, y1 = tile_rect(row, col)
    draw.rectangle([x0, y0, x1, y0 + inset], fill=colour)        # top
    draw.rectangle([x0, y1 - inset, x1, y1], fill=shade(colour, -0.15))  # bottom (shadow)
    draw.rectangle([x0, y0, x0 + inset, y1], fill=colour)        # left
    draw.rectangle([x1 - inset, y0, x1, y1], fill=shade(colour, -0.15))  # right


def aquila(draw, row, col, colour):
    """Stylised imperial aquila/eagle in the centre of a tile (two wings + body).
    Drawn BOLD so it reads at sprite scale (the chest decal is only ~50px)."""
    x0, y0, x1, y1 = tile_rect(row, col)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    span = (x1 - x0) * 0.40
    # Body (vertical diamond) — bold
    bw = int(span * 0.22)
    draw.polygon([(cx, cy - int(span * 0.55)), (cx + bw, cy), (cx, cy + int(span * 0.35)), (cx - bw, cy)], fill=colour)
    # Wings — two thick angled polygons spreading out and up
    for sgn in (-1, 1):
        draw.polygon([
            (cx + sgn * bw, cy - int(span * 0.18)),
            (cx + sgn * int(span * 1.05), cy - int(span * 0.35)),
            (cx + sgn * int(span * 0.60), cy - int(span * 0.08)),
            (cx + sgn * int(span * 0.40), cy + int(span * 0.08)),
            (cx + sgn * bw, cy + int(span * 0.08)),
        ], fill=colour)
        # bold feather lines
        for fi in range(3):
            fy = cy - int(span * 0.08) - fi * 6
            draw.line([(cx + sgn * int(span * 0.45 + fi * 8), fy),
                       (cx + sgn * int(span * 1.0), cy - int(span * 0.35) + fi * 4)],
                      fill=shade(colour, -0.25), width=3)
    # Head dot above the body
    draw.ellipse([cx - 5, cy - int(span * 0.65), cx + 5, cy - int(span * 0.45)], fill=colour)


def chapter_insignia(draw, row, col, faction, colour):
    """A simple faction insignia in the tile centre (chapter marking)."""
    x0, y0, x1, y1 = tile_rect(row, col)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    r = int((x1 - x0) * 0.16)
    if faction == "iron_directorate":
        # Winged skull-ish: circle + two angled bars
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=3)
        for sgn in (-1, 1):
            draw.line([(cx + sgn * r, cy), (cx + sgn * r * 2, cy - r)], fill=colour, width=3)
    elif faction == "cinderborn":
        # Flame/triangle
        draw.polygon([(cx, cy - r), (cx + r, cy + r), (cx - r, cy + r)], fill=colour)
    else:
        # Default: ring
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=3)


def add_wear(draw, row, col, seed, amount=0.10):
    """Sprinkle edge-wear specks (lighter + darker) for weathering."""
    rng = random.Random(seed)
    x0, y0, x1, y1 = tile_rect(row, col)
    n = int((x1 - x0) * (y1 - y0) * amount / 400)
    for _ in range(n):
        x = rng.randint(x0, x1)
        y = rng.randint(y0, y1)
        r = rng.randint(1, 2)
        if rng.random() < 0.5:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(60, 56, 50))
        else:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(180, 176, 168))


# =============================================================================
# PER-PART PAINTERS  (diffuse, team-mask)
# =============================================================================

def paint_torso(d, m, pal, faction):
    row, col = TILE_LAYOUT["torso"]
    fill_tile(d, row, col, pal["primary"])
    fill_tile(m, row, col, (255, 0, 0, 255))  # primary tintable
    # Panel lines: chest divide + abdominal bands
    pl = pal["dark"]
    panel_line_h(d, row, col, 0.45, 3, pl)
    panel_line_h(d, row, col, 0.62, 2, pl)
    panel_line_h(d, row, col, 0.78, 3, pl)
    panel_line_v(d, row, col, 0.5, 2, pl)
    # (Chest aquila lives on its own dedicated decal tile/object, not the torso tile,
    # so the back face doesn't inherit an eagle.)
    # Rivets along top edge (shoulder line)
    rivet_row_h(d, row, col, 0.08, 6, 3, pal["trim"])
    rivet_row_h(d, row, col, 0.08, 6, 1, shade(pal["trim"], -0.3))
    edge_highlight(d, row, col, 3, shade(pal["primary"], 0.18))
    add_wear(d, row, col, 11)


def paint_helmet(d, m, pal, faction):
    row, col = TILE_LAYOUT["helmet"]
    fill_tile(d, row, col, pal["primary"])
    fill_tile(m, row, col, (255, 0, 0, 255))
    # Visor band (dark lens) across upper-middle
    x0, y0, x1, y1 = tile_rect(row, col)
    vy0 = int(y0 + (y1 - y0) * 0.32)
    vy1 = int(y0 + (y1 - y0) * 0.50)
    d.rectangle([x0, vy0, x1, vy1], fill=pal["dark"])
    m.rectangle([x0, vy0, x1, vy1], fill=(0, 0, 0, 255))  # lens fixed (emissive on A)
    # small emissive dots within visor
    d.rectangle([int(x0 + (x1-x0)*0.25), vy0+3, int(x0 + (x1-x0)*0.75), vy0+6], fill=pal["lens"])
    # Crest base strip (gold) up the centre
    panel_line_v(d, row, col, 0.5, 5, pal["trim"])
    m.rectangle([int(x0 + (x1-x0)*0.5)-2, y0, int(x0 + (x1-x0)*0.5)+2, y1], fill=(0, 0, 0, 255))
    # Brow ridge + chin line
    panel_line_h(d, row, col, 0.28, 2, shade(pal["primary"], -0.25))
    panel_line_h(d, row, col, 0.85, 3, pal["dark"])
    # Chapter icon on forehead
    chapter_insignia(d, row, col, faction, pal["trim"])
    edge_highlight(d, row, col, 3, shade(pal["primary"], 0.18))
    add_wear(d, row, col, 22)


def paint_pauldron(d, m, pal, faction):
    row, col = TILE_LAYOUT["pauldron"]
    fill_tile(d, row, col, pal["primary"])
    fill_tile(m, row, col, (255, 0, 0, 255))
    x0, y0, x1, y1 = tile_rect(row, col)
    # Trim ring around the edge (gold) — thick border
    inset = 10
    d.rectangle([x0, y0, x1, y0 + inset], fill=pal["trim"])
    d.rectangle([x0, y1 - inset, x1, y1], fill=pal["trim"])
    d.rectangle([x0, y0, x0 + inset, y1], fill=pal["trim"])
    d.rectangle([x1 - inset, y0, x1, y1], fill=pal["trim"])
    m.rectangle([x0, y0, x1, y0 + inset], fill=(0, 0, 0, 255))
    m.rectangle([x0, y1 - inset, x1, y1], fill=(0, 0, 0, 255))
    m.rectangle([x0, y0, x0 + inset, y1], fill=(0, 0, 0, 255))
    m.rectangle([x1 - inset, y0, x1, y1], fill=(0, 0, 0, 255))
    # Chapter insignia centred
    chapter_insignia(d, row, col, faction, pal["trim"])
    # Inner panel line + rivets
    panel_line_h(d, row, col, 0.5, 2, shade(pal["primary"], -0.3))
    rivet_row_h(d, row, col, 0.18, 5, 2, shade(pal["trim"], -0.2))
    add_wear(d, row, col, 33)


def paint_limb(d, m, pal, seg_colour_mask, bands, rivets=True):
    """Generic segmented limb painter (upper_arm/forearm/thigh/shin)."""
    row, col = seg_colour_mask[0]
    fill_tile(d, row, col, seg_colour_mask[1])
    fill_tile(m, row, col, seg_colour_mask[2])
    # Segmented vambrace/greave bands
    for bf in bands:
        panel_line_h(d, row, col, bf, 3, pal["dark"])
        panel_line_h(d, row, col, bf + 0.04, 1, shade(pal["primary"], 0.2))
    if rivets:
        rivet_row_v(d, row, col, 0.5, 3, 2, pal["trim"])
    edge_highlight(d, row, col, 3, shade(seg_colour_mask[1], 0.18))
    add_wear(d, row, col, 44 + row * 4 + col)


def paint_boot(d, m, pal):
    row, col = TILE_LAYOUT["boot"]
    fill_tile(d, row, col, (74, 60, 48))   # leather brown
    fill_tile(m, row, col, (0, 0, 0, 255))  # fixed
    # Toe cap darker
    panel_line_h(d, row, col, 0.65, 4, (40, 32, 26))
    # Sole line
    panel_line_h(d, row, col, 0.92, 4, (30, 24, 20))
    # Gold ankle trim
    panel_line_h(d, row, col, 0.30, 3, pal["trim"])
    add_wear(d, row, col, 55)


def paint_belt(d, m, pal):
    row, col = TILE_LAYOUT["belt"]
    fill_tile(d, row, col, (74, 60, 48))
    fill_tile(m, row, col, (0, 0, 0, 255))
    x0, y0, x1, y1 = tile_rect(row, col)
    # Buckle (gold) centre
    bw = int((x1 - x0) * 0.18)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    d.rectangle([cx - bw, cy - bw // 2, cx + bw, cy + bw // 2], fill=pal["trim"])
    d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=shade(pal["trim"], -0.3))
    # Pouch seam lines
    panel_line_v(d, row, col, 0.3, 2, (50, 40, 32))
    panel_line_v(d, row, col, 0.7, 2, (50, 40, 32))
    add_wear(d, row, col, 66)


def paint_backpack(d, m, pal):
    row, col = TILE_LAYOUT["backpack"]
    fill_tile(d, row, col, pal["primary"])
    fill_tile(m, row, col, (255, 0, 0, 255))
    # Vent slats (dark horizontal lines)
    for bf in (0.30, 0.40, 0.50, 0.60):
        panel_line_h(d, row, col, bf, 3, pal["dark"])
    # Rivets around vents
    rivet_row_h(d, row, col, 0.22, 4, 2, pal["trim"])
    rivet_row_h(d, row, col, 0.72, 4, 2, pal["trim"])
    # Top cap plate
    panel_line_h(d, row, col, 0.12, 4, shade(pal["primary"], 0.2))
    edge_highlight(d, row, col, 3, shade(pal["primary"], 0.18))
    add_wear(d, row, col, 77)


def paint_weapon(d, m, pal):
    row, col = TILE_LAYOUT["weapon"]
    fill_tile(d, row, col, (70, 72, 78))   # weapon steel
    fill_tile(m, row, col, (0, 0, 0, 255))
    x0, y0, x1, y1 = tile_rect(row, col)
    # Barrel band lines
    panel_line_h(d, row, col, 0.20, 3, pal["dark"])
    panel_line_h(d, row, col, 0.75, 3, pal["dark"])
    # Magazine (darker block)
    d.rectangle([x0 + (x1-x0)//2 - 24, y0 + (y1-y0)//2 - 30, x0 + (x1-x0)//2 + 24, y0 + (y1-y0)//2 + 20], fill=(44, 44, 48))
    # Scope (dark) top
    d.rectangle([x0 + 20, y0 + 18, x1 - 20, y0 + 40], fill=pal["dark"])
    d.ellipse([x0 + 30, y0 + 22, x0 + 50, y0 + 36], fill=pal["lens"])
    # Gold accents
    panel_line_h(d, row, col, 0.5, 2, pal["trim"])
    add_wear(d, row, col, 88)


def paint_codpiece(d, m, pal):
    row, col = TILE_LAYOUT["codpiece"]
    fill_tile(d, row, col, pal["primary"])
    fill_tile(m, row, col, (255, 0, 0, 255))
    # Gold trim border
    inset = 6
    x0, y0, x1, y1 = tile_rect(row, col)
    d.rectangle([x0, y0, x1, y0 + inset], fill=pal["trim"])
    d.rectangle([x0, y1 - inset, x1, y1], fill=pal["trim"])
    panel_line_v(d, row, col, 0.5, 2, pal["dark"])
    add_wear(d, row, col, 99)


def paint_aquila(d, m, pal):
    """Dedicated aquila tile — a clean gold imperial eagle on a TRANSPARENT background,
    mapped onto a flat chest decal. Transparent bg means the chest armour shows through
    around the eagle, so the decal reads as an eagle (not a dark square plate)."""
    row, col = TILE_LAYOUT["aquila"]
    gold = pal["trim"] + (255,)
    # Transparent tile (only the eagle is opaque) — overwrite the default atlas fill.
    x0, y0, x1, y1 = tile_rect(row, col)
    d.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 0))
    m.rectangle([x0, y0, x1, y1], fill=(0, 0, 0, 255))
    aquila(d, row, col, gold)


# =============================================================================
# ATLAS BUILD
# =============================================================================

def build_atlases(config):
    faction = config.get("faction", FACTION_DEFAULT)
    pal = FACTION_PALETTE.get(faction, FACTION_PALETTE[FACTION_DEFAULT])
    eq = config.get("equipment", {})

    diffuse = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (*pal["secondary"], 255))
    mask = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 255))
    d = ImageDraw.Draw(diffuse)
    m = ImageDraw.Draw(mask)

    paint_torso(d, m, pal, faction)
    paint_helmet(d, m, pal, faction)
    if eq.get("pauldrons", True):
        paint_pauldron(d, m, pal, faction)

    # Limbs — secondary for under-armour upper arms/thighs, primary for plated forearms/shins
    paint_limb(d, m, pal, (TILE_LAYOUT["upper_arm"], pal["secondary"], (0, 255, 0, 255)), [0.30, 0.62])
    paint_limb(d, m, pal, (TILE_LAYOUT["forearm"],  pal["primary"],   (255, 0, 0, 255)), [0.30, 0.70])
    paint_limb(d, m, pal, (TILE_LAYOUT["thigh"],    pal["secondary"], (0, 255, 0, 255)), [0.35, 0.68])
    paint_limb(d, m, pal, (TILE_LAYOUT["shin"],     pal["primary"],   (255, 0, 0, 255)), [0.30, 0.72])
    paint_boot(d, m, pal)
    paint_belt(d, m, pal)
    if eq.get("backpack", True):
        paint_backpack(d, m, pal)
    if config.get("weapon", {}).get("type", "rifle") != "none":
        paint_weapon(d, m, pal)
    paint_codpiece(d, m, pal)
    paint_aquila(d, m, pal)

    # Slight blur to avoid harsh aliasing on painted lines (helps LANCZOS downscale)
    diffuse = diffuse.filter(ImageFilter.GaussianBlur(0.6))
    return diffuse, mask


def output_paths(config):
    unit = config["unit_name"]
    out_blend = config.get("output_blend", "")
    if not out_blend:
        return None, None
    if not os.path.isabs(out_blend):
        out_blend = os.path.join(PROJECT_ROOT, out_blend)
    model_dir = os.path.dirname(out_blend)
    return os.path.join(model_dir, f"{unit}_diffuse.png"), os.path.join(model_dir, f"{unit}_teammask.png")


def process_config(config_path):
    with open(config_path) as f:
        config = json.load(f)
    diffuse, mask = build_atlases(config)
    dp, mp = output_paths(config)
    if not dp:
        print(f"  ERROR: no output_blend in {config_path}")
        return None, None
    diffuse.save(dp)
    mask.save(mp)
    print(f"  Diffuse: {dp}")
    print(f"  Team mask: {mp}")
    return dp, mp


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    config_path = None
    batch_dir = None
    i = 0
    while i < len(sys.argv):
        if sys.argv[i] == "--config" and i + 1 < len(sys.argv):
            config_path = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--batch" and i + 1 < len(sys.argv):
            batch_dir = sys.argv[i + 1]; i += 2
        else:
            i += 1
    if batch_dir:
        for f in sorted(os.listdir(batch_dir)):
            if f.endswith(".json"):
                print(f"Painting {f}")
                process_config(os.path.join(batch_dir, f))
    elif config_path:
        process_config(config_path)
    else:
        print("Usage: --config <path.json> | --batch <configs_dir>")
        sys.exit(1)


if __name__ == "__main__":
    main()