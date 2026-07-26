#!/usr/bin/env python3
"""
generate_ui_elements.py — Grimdark UI element generation for IoA.

Generates game-ready UI elements: buttons, panels, frames, and dividers.
All elements use the grimdark_64 palette, support multiple interaction states,
and are faction-themeable.

Usage:
    python generate_ui_elements.py --theme iron_directorate --output output/ui/
    python generate_ui_elements.py --theme cinderborn --output output/ui/
    python generate_ui_elements.py --all --output output/ui/
    python generate_ui_elements.py --list-themes

Output structure:
    output/ui/<version>/<theme>/
        buttons/
            button_primary_default.png
            button_primary_hover.png
            button_primary_active.png
            button_primary_disabled.png
            ...
        panels/
            panel_frame_corner.png
            panel_border_h.png
            panel_border_v.png
            panel_bg.png
            ...
        icons/
            (status icons from generate_status_icons.py are copied here)
        dividers/
            divider_h.png
            divider_v.png
"""

import os
import sys
import json
import argparse
import math
from pathlib import Path
from PIL import Image, ImageDraw

# =============================================================================
# PATHS
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# =============================================================================
# PALETTE — grimdark_64 colours (subset used for UI)
# =============================================================================

C = {
    "void_black":      (10, 10, 10),
    "soot":            (20, 20, 20),
    "gunmetal_dark":   (30, 30, 30),
    "gunmetal_mid":    (40, 40, 40),
    "battle_grey":     (74, 74, 74),
    "imperial_gold":   (212, 160, 36),
    "gold_highlight":   (232, 200, 72),
    "gold_shine":      (240, 232, 160),
    "bone":            (232, 224, 212),
    "bone_shadow":     (200, 192, 180),
    "blood_red":       (139, 45, 45),
    "blood_mid":       (166, 58, 58),
    "hazard_yellow":   (232, 208, 0),
    "hazard_dark":     (184, 168, 0),
    "void_blue":       (26, 26, 36),
    "void_blue_mid":   (46, 46, 62),
    "navy_dark":       (42, 42, 60),
    "navy_mid":        (60, 60, 84),
    "navy_light":      (78, 78, 108),
    "steel_blue":      (52, 90, 120),
    "steel_blue_light": (92, 140, 176),
    "bruise_purple":   (76, 42, 92),
    "purple_mid":      (100, 58, 120),
    "plasma_orange":   (252, 76, 4),
    "plasma_mid":      (255, 120, 0),
    "pure_red":        (255, 0, 0),
    "white":           (255, 255, 255),
}

# =============================================================================
# THEME DEFINITIONS
# =============================================================================

THEMES = {
    "iron_directorate": {
        "name": "Iron Directorate — Order & Tech",
        "panel_bg": C["gunmetal_dark"],
        "panel_border": C["gunmetal_mid"],
        "panel_accent": C["imperial_gold"],
        "button_default": C["gunmetal_dark"],
        "button_hover": C["gunmetal_mid"],
        "button_active": C["navy_dark"],
        "button_disabled": C["soot"],
        "text": C["bone"],
        "highlight": C["gold_highlight"],
        "accent": C["steel_blue"],
        "danger": C["blood_red"],
        "border_light": C["battle_grey"],
        "border_dark": C["void_black"],
    },
    "cinderborn": {
        "name": "Cinderborn — Occult & Sacrifice",
        "panel_bg": C["void_black"],
        "panel_border": C["bruise_purple"],
        "panel_accent": C["plasma_orange"],
        "button_default": C["gunmetal_dark"],
        "button_hover": C["bruise_purple"],
        "button_active": C["purple_mid"],
        "button_disabled": C["soot"],
        "text": C["bone_shadow"],
        "highlight": C["plasma_orange"],
        "accent": C["plasma_mid"],
        "danger": C["blood_red"],
        "border_light": C["purple_mid"],
        "border_dark": C["void_black"],
    },
    "default": {
        "name": "Default — Grimdark Industrial",
        "panel_bg": C["gunmetal_dark"],
        "panel_border": C["gunmetal_mid"],
        "panel_accent": C["hazard_yellow"],
        "button_default": C["gunmetal_dark"],
        "button_hover": C["gunmetal_mid"],
        "button_active": C["navy_dark"],
        "button_disabled": C["soot"],
        "text": C["bone"],
        "highlight": C["hazard_yellow"],
        "accent": C["steel_blue"],
        "danger": C["blood_red"],
        "border_light": C["battle_grey"],
        "border_dark": C["void_black"],
    },
}

# =============================================================================
# DRAWING HELPERS
# =============================================================================

def _draw_inset_border(draw, rect, theme, width=2):
    """Draw an inset 3D border (lighter top/left, darker bottom/right)."""
    x, y, x2, y2 = rect
    # Top + left (light = highlight)
    draw.rectangle([x, y, x2, y + width], fill=theme["border_light"])
    draw.rectangle([x, y, x + width, y2], fill=theme["border_light"])
    # Bottom + right (dark = shadow)
    draw.rectangle([x, y2 - width, x2, y2], fill=theme["border_dark"])
    draw.rectangle([x2 - width, y, x2, y2], fill=theme["border_dark"])


def _draw_outset_border(draw, rect, theme, width=2):
    """Draw an outset 3D border (darker top/left, lighter bottom/right)."""
    x, y, x2, y2 = rect
    # Top + left (dark = shadow)
    draw.rectangle([x, y, x2, y + width], fill=theme["border_dark"])
    draw.rectangle([x, y, x + width, y2], fill=theme["border_dark"])
    # Bottom + right (light = highlight)
    draw.rectangle([x, y2 - width, x2, y2], fill=theme["border_light"])
    draw.rectangle([x2 - width, y, x2, y2], fill=theme["border_light"])


def _draw_accent_corners(draw, rect, theme, size=6):
    """Draw small accent triangles at each corner (gold/purple)."""
    x, y, x2, y2 = rect
    c = theme["panel_accent"]
    # Top-left
    draw.polygon([(x, y), (x + size, y), (x, y + size)], fill=c)
    # Top-right
    draw.polygon([(x2 - size, y), (x2, y), (x2, y + size)], fill=c)
    # Bottom-left
    draw.polygon([(x, y2 - size), (x, y2), (x + size, y2)], fill=c)
    # Bottom-right
    draw.polygon([(x2 - size, y2), (x2, y2 - size), (x2, y2)], fill=c)


# =============================================================================
# BUTTON GENERATORS
# =============================================================================

BUTTON_SIZES = {
    "small": (48, 24),
    "medium": (96, 32),
    "large": (160, 40),
}


def generate_button(theme: dict, width: int, height: int, state: str) -> Image.Image:
    """Generate a single button in the given interaction state."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if state == "default":
        fill = theme["button_default"]
        draw.rectangle([0, 0, width - 1, height - 1], fill=fill)
        _draw_outset_border(draw, (0, 0, width - 1, height - 1), theme, width=1)
        _draw_accent_corners(draw, (1, 1, width - 2, height - 2), theme, size=4)

    elif state == "hover":
        fill = theme["button_hover"]
        draw.rectangle([0, 0, width - 1, height - 1], fill=fill)
        _draw_outset_border(draw, (0, 0, width - 1, height - 1), theme, width=2)
        _draw_accent_corners(draw, (1, 1, width - 2, height - 2), theme, size=5)
        # Glow line on top edge
        draw.rectangle([2, 0, width - 3, 1], fill=theme["highlight"])

    elif state == "active":
        fill = theme["button_active"]
        draw.rectangle([0, 0, width - 1, height - 1], fill=fill)
        _draw_inset_border(draw, (0, 0, width - 1, height - 1), theme, width=2)
        _draw_accent_corners(draw, (1, 1, width - 2, height - 2), theme, size=4)

    elif state == "disabled":
        fill = theme["button_disabled"]
        draw.rectangle([0, 0, width - 1, height - 1], fill=fill)
        draw.rectangle([0, 0, width - 1, 1], fill=theme["border_light"])
        draw.rectangle([width - 1, 0, width - 1, height - 1], fill=theme["border_dark"])
        draw.rectangle([0, height - 1, width - 1, height - 1], fill=theme["border_dark"])
        draw.rectangle([0, 0, 1, height - 1], fill=theme["border_dark"])

    return img


def generate_button_set(theme: dict, theme_name: str, output_dir: str):
    """Generate all button sizes and states for a theme."""
    states = ["default", "hover", "active", "disabled"]
    for size_name, (w, h) in BUTTON_SIZES.items():
        for state in states:
            name = f"button_{size_name}_{state}.png"
            path = os.path.join(output_dir, "buttons", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            img = generate_button(theme, w, h, state)
            img.save(path)
            print(f"  {name}")


# =============================================================================
# PANEL GENERATORS
# =============================================================================

PANEL_PART_SIZE = 16  # modular panel grid size


def generate_panel_bg(theme: dict, output_dir: str):
    """Generate a seamless panel background tile."""
    img = Image.new("RGBA", (PANEL_PART_SIZE, PANEL_PART_SIZE), theme["panel_bg"])
    path = os.path.join(output_dir, "panels", "panel_bg.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("  panel_bg.png")


def generate_panel_corner(theme: dict, output_dir: str):
    """Generate a panel corner piece with accent."""
    size = PANEL_PART_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background
    draw.rectangle([2, 2, size - 3, size - 3], fill=theme["panel_bg"])
    # Outer border half
    draw.rectangle([0, 0, size - 1, 1], fill=theme["panel_border"])
    draw.rectangle([0, 0, 1, size - 1], fill=theme["panel_border"])
    # Inner border half
    draw.rectangle([2, 2, size - 3, 2], fill=theme["border_light"])
    draw.rectangle([2, 2, 2, size - 3], fill=theme["border_light"])
    # Accent triangle
    c = theme["panel_accent"]
    draw.polygon([(0, 0), (6, 0), (0, 6)], fill=c)

    path = os.path.join(output_dir, "panels", "panel_corner.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("  panel_corner.png")


def generate_panel_border_h(theme: dict, output_dir: str):
    """Generate a horizontal panel border segment."""
    size = PANEL_PART_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, size - 1, 1], fill=theme["panel_border"])
    draw.rectangle([2, 2, size - 3, 2], fill=theme["border_light"])
    draw.rectangle([0, size - 2, size - 1, size - 2], fill=theme["border_dark"])

    path = os.path.join(output_dir, "panels", "panel_border_h.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("  panel_border_h.png")


def generate_panel_border_v(theme: dict, output_dir: str):
    """Generate a vertical panel border segment."""
    size = PANEL_PART_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, 1, size - 1], fill=theme["panel_border"])
    draw.rectangle([2, 2, 2, size - 3], fill=theme["border_light"])
    draw.rectangle([size - 2, 0, size - 2, size - 1], fill=theme["border_dark"])

    path = os.path.join(output_dir, "panels", "panel_border_v.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("  panel_border_v.png")


def generate_panel_set(theme: dict, theme_name: str, output_dir: str):
    """Generate all panel pieces for a theme."""
    generate_panel_bg(theme, output_dir)
    generate_panel_corner(theme, output_dir)
    generate_panel_border_h(theme, output_dir)
    generate_panel_border_v(theme, output_dir)


# =============================================================================
# DIVIDER GENERATORS
# =============================================================================

def generate_dividers(theme: dict, output_dir: str):
    """Generate horizontal and vertical dividers."""
    # Horizontal divider — 96×2 px
    h = Image.new("RGBA", (96, 2), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(h)
    h_draw.rectangle([0, 0, 95, 0], fill=theme["border_dark"])
    h_draw.rectangle([0, 1, 95, 1], fill=theme["panel_accent"])
    h_path = os.path.join(output_dir, "dividers", "divider_h.png")
    os.makedirs(os.path.dirname(h_path), exist_ok=True)
    h.save(h_path)
    print("  divider_h.png")

    # Vertical divider — 2×96 px
    v = Image.new("RGBA", (2, 96), (0, 0, 0, 0))
    v_draw = ImageDraw.Draw(v)
    v_draw.rectangle([0, 0, 0, 95], fill=theme["border_dark"])
    v_draw.rectangle([1, 0, 1, 95], fill=theme["panel_accent"])
    v_path = os.path.join(output_dir, "dividers", "divider_v.png")
    v.save(v_path)
    print("  divider_v.png")

    # Section header divider — 96×4 px with accent dots
    sh = Image.new("RGBA", (96, 4), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(sh)
    sh_draw.rectangle([0, 0, 95, 0], fill=theme["panel_border"])
    sh_draw.rectangle([0, 3, 95, 3], fill=theme["panel_border"])
    # Accent dots at each end
    sh_draw.rectangle([2, 1, 2, 2], fill=theme["panel_accent"])
    sh_draw.rectangle([93, 1, 93, 2], fill=theme["panel_accent"])
    sh_path = os.path.join(output_dir, "dividers", "divider_section_header.png")
    sh.save(sh_path)
    print("  divider_section_header.png")


# =============================================================================
# ICON FRAMES (augmented status icons with themed borders)
# =============================================================================

def generate_icon_frames(theme: dict, output_dir: str):
    """Generate themed icon borders for status effect icons."""
    frame_size = 32
    img = Image.new("RGBA", (frame_size, frame_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Border
    draw.rectangle([0, 0, frame_size - 1, frame_size - 1],
                   outline=theme["panel_accent"], width=1)
    # Corner accents
    c = theme["panel_accent"]
    size = 4
    draw.polygon([(0, 0), (size, 0), (0, size)], fill=c)
    draw.polygon([(frame_size - 1, 0), (frame_size - 1 - size, 0),
                  (frame_size - 1, size)], fill=c)
    draw.polygon([(0, frame_size - 1), (size, frame_size - 1),
                  (0, frame_size - 1 - size)], fill=c)
    draw.polygon([(frame_size - 1, frame_size - 1),
                  (frame_size - 1 - size, frame_size - 1),
                  (frame_size - 1, frame_size - 1 - size)], fill=c)

    path = os.path.join(output_dir, "icons", "icon_frame.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("  icon_frame.png")


# =============================================================================
# MAIN
# =============================================================================

def generate_all(theme: dict, theme_name: str, output_dir: str):
    """Generate all UI elements for a theme."""
    print(f"\n{'='*50}")
    print(f"Generating UI elements: {theme['name']}")
    print(f"Output: {output_dir}")
    print(f"{'='*50}")

    print("\nButtons:")
    generate_button_set(theme, theme_name, output_dir)

    print("\nPanels:")
    generate_panel_set(theme, theme_name, output_dir)

    print("\nDividers:")
    generate_dividers(theme, output_dir)

    print("\nIcon frames:")
    generate_icon_frames(theme, output_dir)

    # Write manifest
    manifest = {
        "theme": theme_name,
        "theme_name": theme["name"],
        "output_dir": output_dir,
        "generated_elements": [
            "buttons/*.png",
            "panels/*.png",
            "dividers/*.png",
            "icons/*.png",
        ],
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest: {manifest_path}")
    print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Generate grimdark UI elements for IoA")
    parser.add_argument("--theme", "-t", default="default",
                        choices=list(THEMES.keys()) + ["all"],
                        help="Theme to generate")
    parser.add_argument("--output", "-o", default=None,
                        help="Output directory (default: output/ui/<version>/<theme>)")
    parser.add_argument("--all", action="store_true",
                        help="Generate all themes")
    parser.add_argument("--list-themes", action="store_true",
                        help="List available themes and exit")
    parser.add_argument("--version", default="v0.4.0",
                        help="Version tag for output path")

    args = parser.parse_args()

    if args.list_themes:
        print("Available UI themes:")
        for name, theme in THEMES.items():
            print(f"  {name}: {theme['name']}")
        return 0

    themes_to_generate = []
    if args.theme == "all" or args.all:
        themes_to_generate = list(THEMES.keys())
    elif args.theme in THEMES:
        themes_to_generate = [args.theme]
    else:
        print(f"Unknown theme '{args.theme}'", file=sys.stderr)
        return 1

    for theme_name in themes_to_generate:
        theme = THEMES[theme_name]
        theme_output = args.output or os.path.join(
            PROJECT_ROOT, "output", args.version, "ui", theme_name
        )
        generate_all(theme, theme_name, theme_output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
