#!/usr/bin/env python3
"""
generate_status_icons.py
Generate 32x32 status effect icons for Imperium of Ash.
Method: Pillow vector-style drawing, snap to grimdark_64 palette, alpha transparency.
"""

import os
import math
from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# grimdark_64 palette (extracted from assets/palettes/grimdark_64.gpl)
# ---------------------------------------------------------------------------
PALETTE = [
    (10, 10, 10),       # Void Black
    (20, 20, 20),       # Soot
    (30, 30, 30),       # Gunmetal Dark
    (40, 40, 40),       # Gunmetal Mid
    (74, 74, 74),       # Battle Grey
    (70, 60, 50),       # Leather Dark
    (90, 74, 60),       # Leather Mid
    (110, 94, 76),      # Leather Light
    (139, 45, 45),      # Blood Red
    (166, 58, 58),      # Blood Mid
    (193, 71, 71),      # Blood Light
    (212, 160, 36),     # Imperial Gold
    (232, 200, 72),     # Gold Highlight
    (240, 232, 160),    # Gold Shine
    (140, 112, 56),     # Bronze Dark
    (168, 132, 72),     # Bronze Mid
    (196, 160, 88),     # Bronze Light
    (26, 47, 26),       # Deep Green
    (78, 120, 78),      # Fatigue Mid
    (96, 150, 96),      # Fatigue Light
    (42, 42, 60),       # Navy Dark
    (60, 60, 84),       # Navy Mid
    (78, 78, 108),      # Navy Light
    (92, 64, 52),       # Rust Dark
    (120, 84, 60),      # Rust Mid
    (148, 104, 72),     # Rust Light
    (176, 124, 84),     # Rust Highlight
    (232, 224, 212),    # Bone
    (200, 192, 180),    # Bone Shadow
    (168, 160, 148),    # Bone Dark
    (232, 208, 0),      # Hazard Yellow
    (184, 168, 0),      # Hazard Dark
    (76, 42, 92),       # Bruise Purple
    (100, 58, 120),     # Purple Mid
    (124, 74, 148),     # Purple Light
    (36, 58, 76),       # Steel Blue Dark
    (52, 90, 120),      # Steel Blue Mid
    (74, 122, 156),     # Steel Blue Light
    (92, 140, 176),     # Steel Blue Highlight
    (74, 56, 40),       # Dirt Dark
    (100, 80, 60),      # Dirt Mid
    (126, 104, 80),     # Dirt Light
    (152, 128, 112),    # Dirt Highlight
    (108, 108, 90),     # Concrete Dark
    (138, 138, 120),    # Concrete Mid
    (168, 168, 150),    # Concrete Highlight
    (198, 198, 180),    # Concrete Highlight 2
    (252, 76, 4),       # Plasma Orange
    (255, 120, 0),      # Plasma Mid
    (255, 164, 32),     # Plasma Light
    (0, 184, 0),        # Toxic Green
    (0, 224, 0),        # Toxic Mid
    (64, 255, 64),      # Toxic Light
    (26, 26, 36),       # Void Blue
    (46, 46, 62),       # Void Blue Mid
    (68, 68, 90),       # Void Blue Light
    (92, 92, 120),      # Void Blue Highlight
    (128, 0, 0),        # Gore Dark
    (160, 0, 0),        # Gore Mid
    (192, 32, 32),      # Gore Light
    (60, 42, 30),       # Wood Dark
    (92, 66, 48),       # Wood Mid
    (124, 90, 68),      # Wood Light
    (255, 0, 0),        # Pure Red
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def nearest_palette_color(r, g, b):
    best = 0
    best_d = 1e9
    for i, (pr, pg, pb) in enumerate(PALETTE):
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_d:
            best_d = d
            best = i
    return PALETTE[best]


def quantize_rgba_to_palette(img: Image.Image, alpha_thresh=30):
    """Snap every opaque pixel to nearest palette color; transparent if alpha low."""
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < alpha_thresh:
                px[x, y] = (0, 0, 0, 0)
            else:
                c = nearest_palette_color(r, g, b)
                px[x, y] = (*c, 255)
    return img


def save_indexed_png(img: Image.Image, path: str):
    """Convert RGBA → P (palette) with transparent index 0."""
    # Build a 256-entry palette with the grimdark colors; pad with black.
    flat = []
    for c in PALETTE:
        flat.extend(c)
    # ensure length 768
    while len(flat) < 768:
        flat.extend((0, 0, 0))
    flat = flat[:768]

    # Create palette image
    pimg = Image.new("P", (1, 1))
    pimg.putpalette(flat)

    # Convert RGBA to RGB with transparent pixels replaced by index 0 color
    # We'll map each pixel to nearest palette index.
    rgb = Image.new("RGB", img.size, (0, 0, 0))
    rgb_px = rgb.load()
    a_img = img.getchannel("A")
    a_px = a_img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            if a_px[x, y] < 128:
                rgb_px[x, y] = tuple(flat[:3])
            else:
                r, g, b = img.getpixel((x, y))[:3]
                rgb_px[x, y] = nearest_palette_color(r, g, b)

    # Now convert to palette mode
    out = rgb.quantize(colors=256, method=Image.Quantize.MEDIANCUT, palette=pimg)
    # Set transparent index to 0 (assuming index 0 is Void Black, close enough)
    out.info["transparency"] = 0
    out.save(path, "PNG")


# ---------------------------------------------------------------------------
# Icon drawing routines
# ---------------------------------------------------------------------------

def draw_glow_base(draw, cx, cy, radius, color, bg_rad=16):
    """Emission-style dark vignette + bright core."""
    # Dark outer halo (semi-transparent black / dark grey)
    for r in range(bg_rad, radius, -1):
        alpha = int(40 * (r - radius) / (bg_rad - radius))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*color, alpha))
    # Solid inner disc
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(*color, 200))


def icon_suppressed():
    """Red crosshair with shaking lines."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    # Dark red base glow
    draw_glow_base(d, cx, cy, 12, (139, 45, 45))

    # Crosshair lines
    bright = (212, 160, 36)  # Imperial Gold for contrast
    # Horizontal
    d.line([(4, cy), (28, cy)], fill=(*bright, 255), width=2)
    # Vertical
    d.line([(cx, 4), (cx, 28)], fill=(*bright, 255), width=2)
    # Centre dot
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(255, 0, 0, 255))

    # Shaking zigzags on ends
    def zig(ax, ay, bx, by, steps=3):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            if i % 2 == 1:
                x += 2 if bx > ax else (-2 if bx < ax else 0)
                y += 2 if by > ay else (-2 if by < ay else 0)
            pts.append((x, y))
        return pts

    d.line(zig(4, cy, 0, cy), fill=(255, 164, 32, 200), width=1)
    d.line(zig(28, cy, 32, cy), fill=(255, 164, 32, 200), width=1)
    d.line(zig(cx, 4, cx, 0), fill=(255, 164, 32, 200), width=1)
    d.line(zig(cx, 28, cx, 32), fill=(255, 164, 32, 200), width=1)

    return quantize_rgba_to_palette(img)


def icon_inspired():
    """Blue winged laurel."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    draw_glow_base(d, cx, cy, 12, (78, 78, 108))

    # Wings (curves)
    wing_color = (92, 140, 176, 255)
    for dx in [-1, 1]:
        pts = []
        for t in range(0, 11):
            x = cx + dx * (4 + t * 1.0)
            y = cy - 6 + math.sin(t * 0.4) * 4
            pts.append((x, y))
        if len(pts) > 1:
            d.line(pts, fill=wing_color, width=2)
        pts2 = []
        for t in range(0, 11):
            x = cx + dx * (4 + t * 1.0)
            y = cy + 2 + math.sin(t * 0.4) * 3
            pts2.append((x, y))
        if len(pts2) > 1:
            d.line(pts2, fill=wing_color, width=2)

    # Laurel circle
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=(232, 200, 72, 255), width=2)
    return quantize_rgba_to_palette(img)


def icon_fortified():
    """Green shield with cracks."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    draw_glow_base(d, cx, cy, 12, (78, 120, 78))

    # Shield body
    shield = [
        (cx - 8, cy - 8),
        (cx + 8, cy - 8),
        (cx + 8, cy - 2),
        (cx, cy + 8),
        (cx - 8, cy - 2),
    ]
    d.polygon(shield, fill=(96, 150, 96, 200), outline=(26, 47, 26, 255))

    # Cracks
    crack_color = (20, 20, 20, 255)
    d.line([(cx - 2, cy - 4), (cx + 1, cy - 1), (cx - 1, cy + 2)], fill=crack_color, width=1)
    d.line([(cx + 3, cy - 2), (cx + 3, cy + 1)], fill=crack_color, width=1)
    return quantize_rgba_to_palette(img)


def icon_smoke():
    """Grey smoke cloud."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    draw_glow_base(d, cx, cy, 12, (108, 108, 90))

    # Puffs
    puffs = [
        (cx - 6, cy + 2, 6),
        (cx + 2, cy - 3, 7),
        (cx + 5, cy + 4, 5),
        (cx - 2, cy - 6, 6),
    ]
    for x, y, r in puffs:
        d.ellipse([x - r, y - r, x + r, y + r], fill=(168, 168, 150, 180))
    return quantize_rgba_to_palette(img)


def icon_bleeding():
    """Blood droplet."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    draw_glow_base(d, cx, cy, 12, (139, 45, 45))

    # Droplet shape (teardrop polygon)
    drop = [
        (cx, cy - 10),
        (cx + 6, cy - 2),
        (cx + 4, cy + 4),
        (cx, cy + 8),
        (cx - 4, cy + 4),
        (cx - 6, cy - 2),
    ]
    d.polygon(drop, fill=(192, 32, 32, 220), outline=(139, 45, 45, 255))
    # Highlight
    d.ellipse([cx - 2, cy - 4, cx, cy - 2], fill=(255, 0, 0, 200))
    return quantize_rgba_to_palette(img)


def icon_stunned():
    """Yellow stars/sparkles."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    draw_glow_base(d, cx, cy, 12, (184, 168, 0))

    def star(x, y, size=4):
        s = size
        d.polygon([
            (x, y - s),
            (x + 1, y - 1),
            (x + s, y),
            (x + 1, y + 1),
            (x, y + s),
            (x - 1, y + 1),
            (x - s, y),
            (x - 1, y - 1),
        ], fill=(232, 208, 0, 240))

    star(cx, cy, 5)
    star(cx - 7, cy - 5, 2)
    star(cx + 7, cy - 4, 2)
    star(cx - 5, cy + 5, 2)
    star(cx + 6, cy + 5, 2)
    return quantize_rgba_to_palette(img)


def icon_overwatch():
    """Orange eye/target reticle."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = 16, 16

    draw_glow_base(d, cx, cy, 12, (255, 120, 0))

    # Outer arc reticles
    ret = (232, 208, 0, 255)
    d.arc([cx - 10, cy - 10, cx + 10, cy + 10], start=200, end=340, fill=ret, width=2)
    d.arc([cx - 10, cy - 10, cx + 10, cy + 10], start=20, end=160, fill=ret, width=2)

    # Eye shape
    eye = [
        (cx - 7, cy),
        (cx, cy - 5),
        (cx + 7, cy),
        (cx, cy + 5),
    ]
    d.polygon(eye, fill=(255, 164, 32, 200), outline=(252, 76, 4, 255))
    # Pupil
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(10, 10, 10, 255))
    return quantize_rgba_to_palette(img)


# ---------------------------------------------------------------------------
# Configuration — override with --output <path> CLI arg
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output", "ui", "status")

OUTPUT_DIR = DEFAULT_OUTPUT_DIR

ICONS = [
    ("status_suppressed.png", icon_suppressed),
    ("status_inspired.png", icon_inspired),
    ("status_fortified.png", icon_fortified),
    ("status_smoke.png", icon_smoke),
    ("status_bleeding.png", icon_bleeding),
    ("status_stunned.png", icon_stunned),
    ("status_overwatch.png", icon_overwatch),
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate grimdark status effect icons")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    global OUTPUT_DIR
    OUTPUT_DIR = args.output
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for fname, func in ICONS:
        img = func()
        path = os.path.join(OUTPUT_DIR, fname)
        save_indexed_png(img, path)
        print(f"Wrote {path}  ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
