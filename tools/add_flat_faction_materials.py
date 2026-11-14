"""add_flat_faction_materials.py — flat faction colours for the large-coverage slots.

The base-mesh units map their three large-coverage material slots (`armour_primary`,
`armour_secondary`, `underlayer`) to *flat* library colours: the textured per-faction
materials palette-lock to a static speckle on curved organic surfaces at the 2 cm
texel grid. The library only carried a blue-grey generic set and a Cinder set, so an
Iron Directorate trooper baked blue instead of the faction's gold — the palette read
was wrong while every gate passed (off-palette 0).

This script adds `IOA_flat_<faction>_<slot>` materials derived from the faction spec
(`configs/factions/<faction>.json`) so the bake has the right colour to sample. It is
additive and idempotent: existing materials are updated in place, never duplicated.

    blender -b assets/materials/grimdark_scifi/grimdark_scifi_pixel.blend \
        -P tools/add_flat_faction_materials.py -- --faction iron_directorate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
_ap = argparse.ArgumentParser()
_ap.add_argument("--faction", required=True)
_ap.add_argument("--library", default="assets/materials/grimdark_scifi/grimdark_scifi_pixel.blend")
_ap.add_argument("--save", action="store_true")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

spec = json.loads((ROOT / f"configs/factions/{A.faction}.json").read_text())
palette = spec["palette"]


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return tuple(srgb_to_linear(c) for c in srgb)


# Which palette entry each slot takes: the armour takes the mid ramp step (the base
# colour a texture bake should average), the underlayer the darkest.
SLOT_SOURCE = {
    "armour_primary": ("armour_primary", 1),
    "armour_secondary": ("armour_primary", 0),
    "underlayer": ("underlayer", 0),
}

template = bpy.data.materials.get("IOA_flat_armour_primary")
if template is None:
    raise SystemExit("library has no IOA_flat_armour_primary to clone")

for slot, (ramp, index) in SLOT_SOURCE.items():
    ramp_colours = palette.get(ramp) or []
    if len(ramp_colours) <= index:
        print(f"SKIP {slot}: palette has no {ramp}[{index}]")
        continue
    rgb = hex_to_linear(ramp_colours[index])
    name = f"IOA_flat_{A.faction}_{slot}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = template.copy()
        mat.name = name
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        raise SystemExit(f"{name} has no Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    # A copied material has no users in the .blend, and Blender drops user-less
    # datablocks on save — the first run reported the colours and saved nothing.
    mat.use_fake_user = True
    print(f"FLAT {name} <- {ramp}[{index}] {ramp_colours[index]}")

if A.save:
    bpy.ops.wm.save_mainfile(filepath=str((ROOT / A.library).resolve()))
    print("SAVED", A.library)
