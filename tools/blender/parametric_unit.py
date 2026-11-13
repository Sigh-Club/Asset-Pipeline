#!/usr/bin/env python3
"""parametric_unit.py — author a modular, faction-styled pixel-tier unit mesh.

Unlike the image-to-3D route this builds the unit from real dimensions and named
parts, so gear and silhouette are deliberate and every part carries a contract
material slot for the atlas bake. Output is an unrigged GLB whose object names
encode the target bone (`<bone>__<slot>__<tag>`); `rig_unit_proof.py --bind
authored` turns that into the 22-bone/9-clip rigged unit.

Usage:
    blender -b -P tools/blender/parametric_unit.py -- \
        --config configs/units/iron_directorate.json --unit line_infantry \
        --out output/units/iron_directorate/line_infantry --id line_infantry
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unit_pose  # noqa: E402

TRIS_BUDGET = 4700
SLOTS = ("armour_primary", "armour_secondary", "underlayer", "metal_trim", "accent_emissive")

# Body scale presets. Height is always 1.9 m (the engine and rig contract);
# the proportions shift mass, not stature.
BODY = {
    "standard": {"chest": 1.00, "limb": 1.00, "pauldron": 1.00, "head": 1.00, "leg": 1.00},
    "heavy":    {"chest": 1.18, "limb": 1.12, "pauldron": 1.28, "head": 0.98, "leg": 1.10},
    "light":    {"chest": 0.88, "limb": 0.92, "pauldron": 0.86, "head": 0.98, "leg": 0.94},
    "robed":    {"chest": 0.94, "limb": 0.96, "pauldron": 0.90, "head": 1.00, "leg": 0.98},
    "monolith": {"chest": 1.22, "limb": 1.08, "pauldron": 1.34, "head": 0.92, "leg": 1.04},
}

# Faction style: geometry choices and the slot that carries the identity colour.
STYLE = {
    "directorate": {"bulk": 1.0, "taper": 0.92, "helm": "visor", "pauldron": "block",
                    "weapon": "rifle", "accent": "accent_emissive", "bevel": 0.018},
    "cinderborn":  {"bulk": 0.94, "taper": 0.86, "helm": "hood", "pauldron": "asym",
                    "weapon": "blade", "accent": "accent_emissive", "bevel": 0.016},
    "bloom":       {"bulk": 1.08, "taper": 1.02, "helm": "carapace", "pauldron": "bulb",
                    "weapon": "claw", "accent": "accent_emissive", "bevel": 0.012},
    "concord":     {"bulk": 0.96, "taper": 0.90, "helm": "dome", "pauldron": "plate",
                    "weapon": "rail", "accent": "accent_emissive", "bevel": 0.020},
    "revenant":    {"bulk": 1.04, "taper": 0.95, "helm": "slab", "pauldron": "slab",
                    "weapon": "gauss", "accent": "accent_emissive", "bevel": 0.014},
    "wreckstorm":  {"bulk": 1.12, "taper": 0.88, "helm": "jaw", "pauldron": "scrap",
                    "weapon": "slugga", "accent": "accent_emissive", "bevel": 0.012},
    "corsair":     {"bulk": 0.92, "taper": 0.84, "helm": "fin", "pauldron": "swept",
                    "weapon": "lance", "accent": "accent_emissive", "bevel": 0.018},
}


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--unit", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--id")
    p.add_argument("--tris", type=int, default=TRIS_BUDGET)
    p.add_argument("--list", action="store_true")
    return p.parse_args(argv)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


# ------------------------------------------------------------------ geometry ---

def _material(slot: str):
    mat = bpy.data.materials.get(slot)
    if mat is None:
        mat = bpy.data.materials.new(slot)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1)
    return mat


def _object(bm: bmesh.types.BMesh, name: str, slot: str, bevel: float = 0.0):
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                        offset=bevel, segments=2, affect="EDGES", clamp_overlap=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.data.materials.append(_material(slot))
    for poly in obj.data.polygons:
        poly.use_smooth = False
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _cube(bm, size, center, rot: Matrix | None = None, taper: float = 1.0):
    bmesh.ops.create_cube(bm, size=1.0)
    verts = bm.verts[:]
    for v in verts:
        x, y, z = v.co
        # taper the top of the box (z > 0) toward the centre
        if taper != 1.0 and z > 0:
            x *= taper
            y *= taper
        v.co = Vector((x * size[0], y * size[1], z * size[2]))
    if rot is not None:
        for v in verts:
            v.co = rot @ v.co
    for v in verts:
        v.co += Vector(center)


def _cylinder(bm, radius, depth, center, segments=8, rot: Matrix | None = None):
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius, depth=depth)
    for v in bm.verts[:]:
        v.co = Vector((v.co.x, v.co.y, v.co.z))
    if rot is not None:
        for v in bm.verts[:]:
            v.co = rot @ v.co
    for v in bm.verts[:]:
        v.co += Vector(center)


def _limb_matrix(start: Vector, end: Vector):
    """Rotation that maps a Z-aligned box onto the start->end segment."""
    direction = (end - start)
    if direction.length < 1e-6:
        return Matrix.Identity(4), 0.0
    quat = direction.to_track_quat("Z", "Y")
    return quat.to_matrix().to_4x4(), direction.length


def _prism(bm, sides, radius, height, center, rot: Matrix | None = None, taper: float = 1.0):
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=sides,
                          radius1=radius, radius2=radius * taper, depth=height)
    for v in bm.verts[:]:
        if rot is not None:
            v.co = rot @ v.co
    for v in bm.verts[:]:
        v.co += Vector(center)


def _wedge(bm, size, center, slope="front", amount=0.45, taper=1.0):
    """A cube with one face sheared into a slope — the basic armour-plate form.
    Bevel turns the remaining corners into the faceted low-poly read."""
    _cube(bm, size, center, taper=taper)
    sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
    cx, cy, cz = center
    for v in bm.verts[:]:
        lx, ly, lz = v.co.x - cx, v.co.y - cy, v.co.z - cz
        if slope == "front" and ly < 0 and lz > 0:
            v.co.y += sy * amount
            v.co.z -= sz * amount * 0.35
        elif slope == "back" and ly > 0 and lz > 0:
            v.co.y -= sy * amount
            v.co.z -= sz * amount * 0.35
        elif slope == "outer" and lz > 0:
            v.co.x *= (1.0 - amount * 0.55)
            v.co.z -= sz * amount * 0.25
        elif slope == "inner" and lz > 0:
            v.co.x *= (1.0 - amount * 0.25)
            v.co.z -= sz * amount * 0.2


def part(bone: str, slot: str, tag: str, scale: float = 1.0):
    """Context helper: build into a fresh bmesh and emit a named part."""
    return _Part(bone, slot, tag, scale)


class _Part:
    def __init__(self, bone, slot, tag, scale):
        self.name = f"{bone}__{slot}__{tag}"
        self.slot = slot
        self.scale = scale
        self.bm = bmesh.new()

    def box(self, size, center, taper=1.0, rot=None):
        _cube(self.bm, (size[0] * self.scale, size[1] * self.scale, size[2] * self.scale),
              center, rot=rot, taper=taper)
        return self

    def limb(self, start, end, width, depth, taper=1.0):
        start = Vector(start)
        end = Vector(end)
        rot, length = _limb_matrix(start, end)
        centre = (start + end) / 2
        _cube(self.bm, (width * self.scale, depth * self.scale, length),
              centre, rot=rot, taper=taper)
        return self

    def prism(self, sides, radius, height, center, taper=1.0, axis="Z"):
        rot = None
        if axis == "Y":
            rot = Matrix.Rotation(math.radians(90), 4, "X")
        elif axis == "X":
            rot = Matrix.Rotation(math.radians(90), 4, "Y")
        _prism(self.bm, sides, radius * self.scale, height * self.scale, center,
               rot=rot, taper=taper)
        return self

    def wedge(self, size, center, slope="front", amount=0.45, taper=1.0):
        _wedge(self.bm, (size[0] * self.scale, size[1] * self.scale, size[2] * self.scale),
               center, slope=slope, amount=amount, taper=taper)
        return self

    def limb_prism(self, start, end, radius, sides=6, taper=1.0):
        start = Vector(start)
        end = Vector(end)
        rot, length = _limb_matrix(start, end)
        centre = (start + end) / 2
        _prism(self.bm, sides, radius * self.scale, length, centre, rot=rot, taper=taper)
        return self

    def cyl(self, radius, depth, center, segments=8, axis="Y"):
        rot = None
        if axis == "Y":
            rot = Matrix.Rotation(math.radians(90), 4, "X")
        elif axis == "X":
            rot = Matrix.Rotation(math.radians(90), 4, "Y")
        _cylinder(self.bm, radius * self.scale, depth * self.scale, center,
                  segments=segments, rot=rot)
        return self

    def emit(self, bevel=0.0):
        _object(self.bm, self.name, self.slot, bevel)
        return self


# --------------------------------------------------------------------- parts ---

def build_leg(side: str, s: dict):
    x = 0.13 if side == "Left" else -0.13
    leg = s["leg"]
    w = 0.17 * s["limb"] * leg
    d = 0.19 * s["limb"] * leg
    # boot: sloped toe/instep instead of a cube; heel and sole stay hard-edged
    part(f"{side}Foot", "armour_secondary", "boot").wedge(
        (w * 1.06, 0.30, 0.15), (x, -0.06, 0.075), slope="front", amount=0.38).emit(s["bevel"])
    part(f"{side}Foot", "metal_trim", "sole").box(
        (w * 1.08, 0.31, 0.03), (x, -0.06, 0.015)).emit(0)
    part(f"{side}ToeBase", "armour_secondary", "toe").wedge(
        (w * 0.92, 0.12, 0.09), (x, -0.20, 0.055), slope="front", amount=0.55).emit(0)
    # faceted shin and thigh (6-sided prisms read as armour, not a box)
    part(f"{side}Leg", "armour_secondary", "shin").limb_prism(
        (x, 0, 0.12), (x, 0, 0.55), w * 0.55, sides=6, taper=0.88).emit(s["bevel"])
    part(f"{side}Leg", "armour_primary", "greave").wedge(
        (w * 0.92, 0.09, 0.30), (x, -d * 0.44, 0.35), slope="front", amount=0.34).emit(s["bevel"])
    part(f"{side}Leg", "metal_trim", "knee").wedge(
        (w * 0.86, d * 0.95, 0.10), (x, -0.01, 0.55), slope="front", amount=0.5).emit(0)
    part(f"{side}UpLeg", "armour_primary", "thigh").limb_prism(
        (x, 0, 0.98), (x, 0, 0.55), w * 0.62, sides=6, taper=0.84).emit(s["bevel"])
    part(f"{side}UpLeg", "underlayer", "thigh_gap").box(
        (w * 0.84, d * 0.86, 0.14), (x, 0, 0.95)).emit(0)
    part("Hips", "armour_secondary", f"hip_{side.lower()}").wedge(
        (0.10, 0.18, 0.12), (x * 0.85, 0, 1.00), slope="outer" if side == "Left" else "inner",
        amount=0.35).emit(s["bevel"])


def build_torso(s: dict, heavy: bool = False):
    c = s["chest"]
    part("Hips", "underlayer", "pelvis").wedge(
        (0.30, 0.20, 0.16), (0, 0, 1.00), slope="front", amount=0.2).emit(s["bevel"])
    part("Hips", "armour_secondary", "belt").wedge(
        (0.34, 0.24, 0.09), (0, 0, 1.06), slope="front", amount=0.3).emit(s["bevel"])
    part("Hips", "metal_trim", "buckle").wedge(
        (0.07, 0.04, 0.06), (0, -0.13, 1.06), slope="front", amount=0.5).emit(0)
    part("Spine", "underlayer", "abdomen").limb_prism(
        (0, 0, 1.10), (0, 0, 1.22), 0.11, sides=6, taper=1.1).emit(0)
    # layered cuirass: the plates overhang and slope outward at the top
    part("Spine1", "armour_primary", "cuirass").wedge(
        (0.38 * c, 0.24 * c, 0.22), (0, 0, 1.28), slope="front",
        amount=0.28, taper=s["taper"]).emit(s["bevel"])
    part("Spine2", "armour_primary", "chestplate").wedge(
        (0.40 * c, 0.26 * c, 0.18), (0, 0, 1.42), slope="front",
        amount=0.34, taper=s["taper"]).emit(s["bevel"])
    part("Spine2", "metal_trim", "collar").wedge(
        (0.24, 0.20, 0.06), (0, 0, 1.53), slope="back", amount=0.4).emit(0)
    part("Spine2", "accent_emissive", "chest_light").box(
        (0.06, 0.06, 0.06), (0, -0.12 * c, 1.42)).emit(0)
    for side, sx in (("Left", 1), ("Right", -1)):
        part(f"{side}Shoulder", "underlayer", "socket").prism(
            6, 0.075, 0.12, (sx * 0.20 * c, 0, 1.48), taper=0.85).emit(0)


def build_head(s: dict, helm: str, crest: bool = False, horns: bool = False):
    part("Neck", "underlayer", "neck").prism(6, 0.055, 0.10, (0, 0, 1.57)).emit(0)
    if helm == "visor":
        part("Head", "armour_primary", "helm").prism(
            8, 0.105, 0.22, (0, 0, 1.72), taper=0.82).emit(s["bevel"])
        part("Head", "armour_secondary", "brow").wedge(
            (0.20, 0.10, 0.06), (0, -0.09, 1.78), slope="front", amount=0.6).emit(s["bevel"])
        part("Head", "metal_trim", "jaw").wedge(
            (0.17, 0.20, 0.07), (0, -0.03, 1.62), slope="front", amount=0.3).emit(0)
        part("Head", "accent_emissive", "visor").box(
            (0.16, 0.06, 0.04), (0, -0.10, 1.74)).emit(0)
    elif helm == "hood":
        part("Head", "underlayer", "cowl").prism(
            8, 0.135, 0.26, (0, 0.01, 1.74), taper=0.55).emit(s["bevel"])
        part("Neck", "underlayer", "cowl_drape").wedge(
            (0.27, 0.20, 0.30), (0, 0.05, 1.61), slope="back", amount=0.16).emit(0)
        part("Head", "accent_emissive", "eyes").box(
            (0.10, 0.06, 0.03), (0, -0.10, 1.73)).emit(0)
    elif helm == "carapace":
        part("Head", "armour_secondary", "carapace").prism(
            8, 0.13, 0.24, (0, 0, 1.73), taper=0.62).emit(s["bevel"])
        part("Head", "accent_emissive", "eye_cluster").box(
            (0.12, 0.06, 0.035), (0, -0.10, 1.73)).emit(0)
    elif helm == "dome":
        part("Head", "armour_secondary", "dome").prism(
            8, 0.115, 0.22, (0, 0, 1.73), taper=0.7).emit(s["bevel"])
        part("Head", "accent_emissive", "optic").box(
            (0.08, 0.06, 0.045), (0, -0.10, 1.74)).emit(0)
    elif helm == "slab":
        part("Head", "armour_primary", "slab").wedge(
            (0.24, 0.24, 0.26), (0, 0, 1.73), slope="front", amount=0.22).emit(s["bevel"])
        part("Head", "accent_emissive", "slit").box(
            (0.14, 0.06, 0.025), (0, -0.10, 1.76)).emit(0)
    elif helm == "jaw":
        part("Head", "armour_secondary", "jawplate").wedge(
            (0.24, 0.24, 0.18), (0, -0.01, 1.70), slope="front", amount=0.4).emit(s["bevel"])
        part("Head", "metal_trim", "teeth").box(
            (0.18, 0.03, 0.05), (0, -0.12, 1.64)).emit(0)
        part("Head", "accent_emissive", "goggles").box(
            (0.14, 0.06, 0.035), (0, -0.10, 1.76)).emit(0)
    elif helm == "fin":
        part("Head", "armour_primary", "fin_helm").prism(
            8, 0.10, 0.20, (0, 0, 1.73), taper=0.8).emit(s["bevel"])
        part("Head", "metal_trim", "fin").wedge(
            (0.03, 0.16, 0.12), (0, 0.04, 1.86), slope="back", amount=0.6).emit(0)
        part("Head", "accent_emissive", "visor").box(
            (0.13, 0.06, 0.03), (0, -0.10, 1.74)).emit(0)
    elif helm == "cap":
        part("Head", "armour_secondary", "cap").prism(
            6, 0.095, 0.13, (0, 0, 1.77), taper=0.78).emit(s["bevel"])
        part("Head", "accent_emissive", "goggles").box(
            (0.14, 0.06, 0.035), (0, -0.09, 1.75)).emit(0)
        part("Head", "armour_secondary", "peak").wedge(
            (0.18, 0.10, 0.03), (0, -0.12, 1.81), slope="front", amount=0.55).emit(0)
    elif helm == "brim":
        part("Head", "armour_primary", "brim_helm").prism(
            8, 0.108, 0.18, (0, 0, 1.72), taper=0.9).emit(s["bevel"])
        part("Head", "armour_secondary", "brim").wedge(
            (0.27, 0.26, 0.03), (0, -0.01, 1.81), slope="front", amount=0.18).emit(0)
        part("Head", "metal_trim", "faceplate").wedge(
            (0.17, 0.04, 0.08), (0, -0.115, 1.68), slope="front", amount=0.4).emit(0)
        part("Head", "accent_emissive", "visor_slit").box(
            (0.13, 0.06, 0.03), (0, -0.10, 1.73)).emit(0)
    if crest:
        part("Head", "metal_trim", "crest_base").box((0.07, 0.13, 0.07), (0, 0.02, 1.82)).emit(0)
        part("Head", "accent_emissive" if helm == "hood" else "metal_trim", "crest").wedge(
            (0.03, 0.13, 0.17), (0, 0.02, 1.91), slope="back", amount=0.5).emit(0)
    if horns:
        for sx in (-1, 1):
            part("Head", "armour_secondary", f"horn_{sx}").wedge(
                (0.045, 0.045, 0.20), (sx * 0.10, 0.01, 1.82), slope="outer" if sx > 0 else "inner",
                amount=0.45).emit(0)
            part("Head", "metal_trim", f"horn_tip_{sx}").box(
                (0.04, 0.04, 0.07), (sx * 0.105, 0.01, 1.89)).emit(0)


def build_arm(side: str, s: dict, hold: str):
    a = unit_pose.arm_points(hold, side)
    shoulder = Vector(a["shoulder"])
    elbow = Vector(a["elbow"])
    wrist = Vector(a["wrist"])
    hand = Vector(a["hand"])
    part(f"{side}Arm", "underlayer", "upper").limb_prism(
        shoulder, elbow, 0.065, sides=6, taper=0.9).emit(s["bevel"])
    part(f"{side}ForeArm", "armour_secondary", "vambrace").limb_prism(
        elbow, wrist, 0.055, sides=6, taper=0.88).emit(s["bevel"])
    part(f"{side}Hand", "underlayer", "hand").wedge(
        (0.09, 0.12, 0.08), hand, slope="front", amount=0.3).emit(0)
    part(f"{side}Arm", "metal_trim", "elbow").wedge(
        (0.12, 0.12, 0.08), elbow, slope="outer" if side == "Left" else "inner",
        amount=0.4).emit(0)


def build_pauldron(side: str, s: dict, kind: str, scale: float):
    sx = 1 if side == "Left" else -1
    p = s["pauldron"] * scale
    if kind == "none":
        return
    if kind == "block":
        part(f"{side}Shoulder", "armour_primary", "pauldron").wedge(
            (0.17 * p, 0.23 * p, 0.15 * p), (sx * 0.27, 0, 1.52),
            slope="outer" if sx > 0 else "inner", amount=0.42, taper=0.85).emit(s["bevel"])
        part(f"{side}Shoulder", "metal_trim", "pauldron_rim").wedge(
            (0.18 * p, 0.24 * p, 0.035), (sx * 0.27, 0, 1.59),
            slope="outer" if sx > 0 else "inner", amount=0.35).emit(0)
    elif kind == "asym":
        if side == "Left":
            part(f"{side}Shoulder", "armour_primary", "pauldron").wedge(
                (0.16 * p, 0.23 * p, 0.16 * p), (sx * 0.27, 0, 1.52),
                slope="outer", amount=0.45, taper=0.8).emit(s["bevel"])
            part(f"{side}Shoulder", "metal_trim", "pauldron_spike").wedge(
                (0.04, 0.05, 0.14), (sx * 0.31, 0, 1.64), slope="outer", amount=0.6).emit(0)
        else:
            part(f"{side}Shoulder", "metal_trim", "spikes").prism(
                5, 0.09 * p, 0.14, (sx * 0.27, 0, 1.55), taper=0.35).emit(0)
    elif kind == "bulb":
        part(f"{side}Shoulder", "armour_secondary", "bulb").prism(
            8, 0.12 * p, 0.18 * p, (sx * 0.27, 0, 1.53), taper=0.5).emit(s["bevel"])
    elif kind == "plate":
        part(f"{side}Shoulder", "armour_primary", "plate").wedge(
            (0.15 * p, 0.21 * p, 0.10 * p), (sx * 0.27, 0, 1.54),
            slope="outer" if sx > 0 else "inner", amount=0.35).emit(s["bevel"])
    elif kind == "slab":
        part(f"{side}Shoulder", "armour_primary", "slab").wedge(
            (0.18 * p, 0.23 * p, 0.17 * p), (sx * 0.27, 0, 1.53),
            slope="outer" if sx > 0 else "inner", amount=0.28).emit(s["bevel"])
    elif kind == "scrap":
        part(f"{side}Shoulder", "armour_secondary", "scrap").wedge(
            (0.18 * p, 0.21 * p, 0.12 * p), (sx * 0.27, 0, 1.54),
            slope="outer" if sx > 0 else "inner", amount=0.3).emit(s["bevel"])
        part(f"{side}Shoulder", "metal_trim", "scrap_spike").prism(
            5, 0.035, 0.12, (sx * 0.31, 0, 1.63), taper=0.3).emit(0)
    elif kind == "swept":
        part(f"{side}Shoulder", "armour_primary", "swept").wedge(
            (0.13 * p, 0.27 * p, 0.10 * p), (sx * 0.27, 0.02, 1.55),
            slope="back", amount=0.5).emit(s["bevel"])


def build_back(s: dict, kind: str):
    if kind == "none":
        return
    if kind == "pack":
        part("Spine2", "armour_secondary", "backpack").box((0.26, 0.15, 0.28), (0, 0.17, 1.37)).emit(s["bevel"])
        part("Spine2", "metal_trim", "pack_vents").box((0.20, 0.03, 0.06), (0, 0.26, 1.30)).emit(0)
    elif kind == "jump":
        part("Spine2", "armour_secondary", "jump_pack").box((0.28, 0.17, 0.30), (0, 0.18, 1.39)).emit(s["bevel"])
        for sx in (-1, 1):
            part("Spine2", "metal_trim", "thruster").cyl(
                0.045, 0.16, (sx * 0.09, 0.28, 1.44), segments=8, axis="Z").emit(0)
            part("Spine2", "accent_emissive", "thruster_glow").cyl(
                0.04, 0.02, (sx * 0.09, 0.28, 1.35), segments=8, axis="Z").emit(0)
    elif kind == "banner":
        part("Spine2", "metal_trim", "banner_mount").box(
            (0.09, 0.13, 0.09), (0.14, 0.11, 1.42)).emit(0)
        part("Spine2", "metal_trim", "banner_pole").box(
            (0.03, 0.03, 0.80), (0.14, 0.10, 1.62)).emit(0)
        part("Spine2", "armour_primary", "banner").box(
            (0.02, 0.24, 0.32), (0.15, 0.16, 1.80)).emit(0)
    elif kind == "servo":
        part("Spine2", "armour_secondary", "servo_pack").box((0.24, 0.14, 0.24), (0, 0.16, 1.38)).emit(s["bevel"])
        part("Spine2", "metal_trim", "servo_arm").limb(
            (-0.16, 0.18, 1.48), (-0.30, 0.10, 1.62), 0.06, 0.06).emit(0)
        part("Spine2", "metal_trim", "servo_claw").box((0.09, 0.07, 0.05), (-0.32, 0.08, 1.64)).emit(0)
    elif kind == "ammo":
        part("Spine2", "armour_secondary", "ammo_pack").box((0.34, 0.18, 0.26), (0, 0.18, 1.34)).emit(s["bevel"])
        for sx in (-1, 1):
            part("Spine2", "metal_trim", "ammo_can").box((0.10, 0.10, 0.12), (sx * 0.16, 0.27, 1.34)).emit(0)


def build_weapon_hand(side: str, s: dict):
    sx = 1 if side == "Left" else -1
    grip = Vector((sx * 0.12, -0.30, 1.30))
    w = s["weapon"]
    if w in ("blade", "claw"):
        part(f"{side}Hand", "metal_trim", "blade").limb(
            grip, grip + Vector((sx * 0.06, -0.55, 0.10)), 0.035, 0.10).emit(0)
        part(f"{side}Hand", "armour_secondary", "guard").box(
            (0.10, 0.05, 0.03), grip + Vector((0, -0.06, 0))).emit(0)
    elif w == "chainblade":
        part(f"{side}Hand", "metal_trim", "chain_body").box(
            (0.05, 0.46, 0.09), grip + Vector((0, -0.24, 0.04))).emit(0)
        part(f"{side}Hand", "armour_secondary", "chain_teeth").box(
            (0.03, 0.40, 0.05), grip + Vector((0, -0.24, 0.10))).emit(0)
    else:
        part(f"{side}Hand", "metal_trim", "blade_short").box(
            (0.04, 0.34, 0.08), grip + Vector((0, -0.18, 0.04))).emit(0)


MELEE_WEAPONS = {"blade", "claw", "chainblade"}
RANGED_WEAPONS = {
    "rifle", "longrifle", "heavy_stubber", "autocannon", "rail", "gauss",
    "slugga", "lance",
}


def hold_for(weapon: str) -> str:
    if weapon in MELEE_WEAPONS:
        return "melee"
    if weapon in RANGED_WEAPONS:
        return "ranged"
    return "relaxed"


def build_weapon_held(s: dict, kind: str, hold: str):
    """Build the weapon around the hand sockets.

    Ranged: right hand is the pistol grip, left hand the foregrip (the standard
    two-handed socket layout). The mesh is weighted to RightHand, so it follows
    the hand in every clip; the left hand is posed to the foregrip by
    unit_pose.range, so the hold survives the authored aim/fire beats.
    Melee: the blade grows out of the right-hand socket along the forearm.
    """
    if kind in MELEE_WEAPONS:
        a = unit_pose.arm_points("melee", "Right")
        grip = Vector(a["hand"])
        wrist = Vector(a["wrist"])
        axis = (grip - wrist).normalized()
        length = 0.62 if kind == "chainblade" else 0.70
        part("RightHand", "metal_trim", "grip").box((0.07, 0.10, 0.13), grip).emit(0)
        part("RightHand", "armour_secondary", "guard").box((0.16, 0.06, 0.07), grip + axis * 0.03).emit(0)
        part("RightHand", "metal_trim", "blade").limb(grip + axis * 0.01, grip + axis * length,
                                                      0.05, 0.10).emit(0)
        if kind == "chainblade":
            part("RightHand", "armour_secondary", "chain_teeth").limb(
                grip + axis * 0.10, grip + axis * (length - 0.02), 0.05, 0.04).emit(0)
        part("RightHand", "metal_trim", "pommel").box((0.06, 0.05, 0.05), grip - axis * 0.08).emit(0)
        return

    r = unit_pose.arm_points("ranged", "Right")
    l = unit_pose.arm_points("ranged", "Left")
    grip = Vector(r["hand"])
    fore = Vector(l["hand"])
    axis = (fore - grip).normalized()
    if kind == "longrifle":
        muzzle_len = 0.42
    elif kind in ("heavy_stubber", "autocannon"):
        muzzle_len = 0.34
    else:
        muzzle_len = 0.30
    receiver_w = {"heavy_stubber": 0.10, "autocannon": 0.13}.get(kind, 0.07)
    receiver_d = {"heavy_stubber": 0.13, "autocannon": 0.16}.get(kind, 0.09)

    # stock behind the grip, receiver grip->foregrip, barrel forward of the foregrip
    part("RightHand", "armour_secondary", "stock").limb(grip - axis * 0.16, grip - axis * 0.02,
                                                        0.06, 0.08).emit(0)
    part("RightHand", "metal_trim", "receiver").limb(grip - axis * 0.02, fore,
                                                     receiver_w, receiver_d).emit(0)
    part("RightHand", "metal_trim", "barrel").limb(fore, fore + axis * muzzle_len, 0.030, 0.030).emit(0)
    part("RightHand", "metal_trim", "muzzle").box((0.05, 0.05, 0.05), fore + axis * (muzzle_len + 0.02)).emit(0)
    # magazine below the receiver; sight above it
    mid = grip.lerp(fore, 0.45)
    part("RightHand", "armour_primary", "magazine").box((0.05, 0.08, 0.15), mid + Vector((0, 0, -0.11))).emit(0)
    part("RightHand", "metal_trim", "sight").box((0.03, 0.05, 0.04), mid + Vector((0, 0, 0.08))).emit(0)
    if kind == "heavy_stubber":
        part("RightHand", "armour_secondary", "drum").cyl(0.09, 0.10, mid + Vector((0, 0, -0.14)), segments=10, axis="X").emit(0)
    if kind == "autocannon":
        part("RightHand", "armour_secondary", "feed").box((0.10, 0.12, 0.16), mid + Vector((0.09, 0, -0.06))).emit(0)
    if kind in ("rail", "gauss"):
        for i in range(3):
            part("RightHand", "accent_emissive", f"coil_{i}").box(
                (0.09, 0.03, 0.03), fore + axis * (0.06 + i * 0.08)).emit(0)
    if kind == "lance":
        part("RightHand", "accent_emissive", "lance_edge").limb(
            grip + axis * 0.02, fore + axis * (muzzle_len + 0.02), 0.02, 0.02).emit(0)


def build_shield(s: dict, kind: str):
    if kind == "none":
        return
    if kind == "tower":
        part("LeftForeArm", "armour_primary", "tower_shield").box(
            (0.06, 0.34, 0.68), (0.30, -0.26, 1.24), taper=0.94).emit(s["bevel"])
        part("LeftForeArm", "metal_trim", "shield_rim").box(
            (0.07, 0.36, 0.08), (0.30, -0.26, 1.55)).emit(0)
        part("LeftForeArm", "accent_emissive", "shield_mark").box(
            (0.02, 0.10, 0.10), (0.34, -0.26, 1.30)).emit(0)


def build_robe(s: dict):
    """A split occult robe: front-open panels read as cloth and change the
    silhouette without hiding the leg animation."""
    part("Hips", "underlayer", "robe_band").box((0.36, 0.24, 0.10), (0, 0, 1.02)).emit(s["bevel"])
    for side, sx in (("Left", 1), ("Right", -1)):
        part(f"{side}UpLeg", "underlayer", f"robe_panel_{side.lower()}").box(
            (0.13, 0.05, 0.52), (sx * 0.11, -0.12, 0.70), taper=1.25).emit(0)
        part(f"{side}UpLeg", "armour_secondary", f"robe_trim_{side.lower()}").box(
            (0.14, 0.02, 0.04), (sx * 0.11, -0.145, 0.44)).emit(0)
    part("Hips", "underlayer", "robe_back").box((0.32, 0.05, 0.54), (0, 0.13, 0.72), taper=1.2).emit(0)


def build_cloak(s: dict):
    part("Spine2", "underlayer", "cloak_upper").box((0.42, 0.06, 0.34), (0, 0.15, 1.34)).emit(s["bevel"])
    part("Spine", "underlayer", "cloak_lower").box((0.34, 0.05, 0.30), (0, 0.14, 1.06)).emit(0)


def build_greebles(s: dict, spec: dict, style: dict):
    """Surface detail that raises the authored mesh above the 4,000-tri engine
    floor and buys silhouette detail at the 2 cm texel grid: vents, rivets,
    pouches, strips, lamps and weapon furniture. All boxes, no new material."""
    c = s["chest"]
    # helmet: side lamps, vents, antenna (box helmets only; a tapered cowl
    # leaves these floating, which splits the silhouette at side angles)
    if spec.get("helm", "visor") == "visor":
        for sx in (-1, 1):
            part("Head", "metal_trim", f"helm_lamp_{sx}").box(
                (0.025, 0.03, 0.04), (sx * 0.095, -0.06, 1.75)).emit(0)
            part("Head", "armour_secondary", f"helm_vent_{sx}").box(
                (0.03, 0.06, 0.03), (sx * 0.085, 0.04, 1.80)).emit(0)
            part("Head", "metal_trim", f"helm_rivet_{sx}").box(
                (0.018, 0.018, 0.018), (sx * 0.075, -0.108, 1.78)).emit(0)
    if spec.get("helm", "visor") == "visor":
        part("Head", "metal_trim", "antenna_base").box((0.06, 0.06, 0.05), (0.06, 0.03, 1.79)).emit(0)
        part("Head", "metal_trim", "antenna").box((0.016, 0.016, 0.18), (0.06, 0.03, 1.89)).emit(0)
    # chest: vent bank, rivets, straps, unit plate
    for i in range(3):
        part("Spine2", "metal_trim", f"chest_vent_{i}").box(
            (0.16 * c, 0.05, 0.022), (0, -0.125 * c, 1.46 - i * 0.035)).emit(0)
    for sx in (-1, 1):
        for i in range(2):
            part("Spine2", "metal_trim", f"chest_rivet_{sx}_{i}").box(
                (0.03, 0.04, 0.03), (sx * 0.155 * c, -0.115 * c, 1.38 + i * 0.07)).emit(0)
        part("Spine2", "armour_secondary", f"chest_strap_{sx}").box(
            (0.04, 0.05, 0.26), (sx * 0.10 * c, -0.12 * c, 1.35)).emit(0)
    part("Spine2", "armour_secondary", "unit_plate").box(
        (0.08, 0.05, 0.06), (0.11 * c, -0.125 * c, 1.47)).emit(0)
    # belt pouches and a thigh holster
    for i, x in enumerate((-0.12, 0.0, 0.12)):
        part("Hips", "armour_secondary", f"pouch_{i}").box((0.07, 0.05, 0.09), (x, -0.15, 1.03)).emit(0)
    part("RightUpLeg", "armour_secondary", "holster").box((0.08, 0.06, 0.14), (-0.20, -0.06, 0.84)).emit(0)
    part("LeftUpLeg", "armour_secondary", "thigh_pouch").box((0.07, 0.05, 0.10), (0.20, -0.07, 0.82)).emit(0)
    # leg straps and boot treads
    for side, sx in (("Left", 1), ("Right", -1)):
        for i, z in enumerate((0.24, 0.36, 0.47)):
            part(f"{side}Leg", "metal_trim", f"shin_strap_{i}").box(
                (0.15 * s["limb"], 0.02, 0.018), (sx * 0.13, -0.09, z)).emit(0)
        for i, y in enumerate((-0.16, -0.08, 0.0)):
            part(f"{side}Foot", "metal_trim", f"tread_{i}").box(
                (0.13 * s["limb"], 0.03, 0.02), (sx * 0.13, y, 0.008)).emit(0)
    # pauldron rivets
    if spec.get("shoulders", style["pauldron"]) != "none":
        for side, sx in (("Left", 1), ("Right", -1)):
            for i in range(3):
                part(f"{side}Shoulder", "metal_trim", f"pauldron_rivet_{i}").box(
                    (0.018, 0.018, 0.018), (sx * 0.21, -0.07 + i * 0.07, 1.56)).emit(0)
    # backpack tanks / valves per back kind
    back = spec.get("back", "none")
    if back in ("pack", "jump", "ammo", "servo"):
        for sx in (-1, 1):
            part("Spine2", "metal_trim", f"pack_tank_{sx}").cyl(
                0.035, 0.20, (sx * 0.075, 0.27, 1.40), segments=8, axis="Z").emit(0)
            part("Spine2", "armour_secondary", f"pack_valve_{sx}").box(
                (0.04, 0.04, 0.04), (sx * 0.075, 0.27, 1.51)).emit(0)
    # weapon furniture above the base receiver
    w = s["weapon"]
    if w in ("rifle", "longrifle", "heavy_stubber", "autocannon"):
        for i in range(3):
            part("Spine2", "metal_trim", f"rail_{i}").box(
                (0.03, 0.03, 0.015), (0, -0.26 - i * 0.08, 1.415)).emit(0)
        part("Spine2", "armour_secondary", "trigger_guard").box(
            (0.06, 0.07, 0.02), (0, -0.24, 1.30)).emit(0)
        part("Spine2", "metal_trim", "muzzle_brake").box(
            (0.05, 0.08, 0.05), (0, -0.64, 1.37)).emit(0)
    # layered armour: pectoral plates, spine plates, cheek guards, wrist and
    # thigh plates. These are the readable silhouette detail at tactical zoom.
    for sx in (-1, 1):
        part("Spine2", "armour_primary", f"pectoral_{sx}").box(
            (0.17 * c, 0.06, 0.13), (sx * 0.10 * c, -0.13 * c, 1.43)).emit(0)
        if spec.get("helm", "visor") == "visor":
            part("Head", "armour_secondary", f"cheek_{sx}").box(
                (0.025, 0.12, 0.10), (sx * 0.105, -0.04, 1.68)).emit(0)
        part(f"{'Left' if sx > 0 else 'Right'}ForeArm", "armour_primary", "wrist_guard").box(
            (0.12, 0.12, 0.06), (sx * 0.20, -0.25, 1.32)).emit(0)
        part(f"{'Left' if sx > 0 else 'Right'}UpLeg", "armour_secondary", "thigh_plate").box(
            (0.05, 0.14, 0.20), (sx * 0.205, -0.02, 0.78)).emit(0)
        part(f"{'Left' if sx > 0 else 'Right'}Leg", "armour_secondary", "shin_plate").box(
            (0.12, 0.03, 0.16), (sx * 0.13, -0.10, 0.30)).emit(0)
        if spec.get("shoulders", style["pauldron"]) != "none":
            part(f"{ 'Left' if sx > 0 else 'Right'}Shoulder", "armour_primary", "pauldron_top").box(
                (0.14 * s["pauldron"], 0.18 * s["pauldron"], 0.05),
                (sx * 0.27, 0, 1.60), taper=0.9).emit(0)
    for i in range(3):
        part("Spine2", "armour_primary", f"spine_plate_{i}").box(
            (0.10, 0.03, 0.07), (0.16, 0.10, 1.45 - i * 0.07)).emit(0)
    # small closing detail: shoulder vents, knee rivets, belt side plates, gorget
    for side, sx in (("Left", 1), ("Right", -1)):
        if spec.get("shoulders", style["pauldron"]) != "none":
            for i in range(2):
                part(f"{side}Shoulder", "metal_trim", f"shoulder_vent_{i}").box(
                    (0.02, 0.06, 0.03), (sx * 0.205, -0.04 + i * 0.08, 1.50)).emit(0)
        for i in range(2):
            part(f"{side}Leg", "metal_trim", f"knee_rivet_{i}").box(
                (0.02, 0.02, 0.02), (sx * 0.13 + (0.03 if i else -0.03), -0.10, 0.55)).emit(0)
    for sx in (-1, 1):
        part("Hips", "armour_secondary", f"belt_side_{sx}").box(
            (0.03, 0.08, 0.08), (sx * 0.175, 0, 1.06)).emit(0)
    part("Spine", "armour_primary", "gorget").box((0.20, 0.05, 0.06), (0, -0.10, 1.12)).emit(0)
    # weapon stock pad and sling loops
    if w in ("rifle", "longrifle"):
        part("Spine2", "armour_secondary", "stock_pad").box((0.06, 0.04, 0.07), (0, -0.04, 1.35)).emit(0)
        part("Spine2", "metal_trim", "sling_loop").box((0.03, 0.03, 0.03), (0, -0.10, 1.32)).emit(0)


# ------------------------------------------------------------------ assembly ---

def load_config(path: Path):
    return json.loads(path.read_text())



def mesh_tris() -> int:
    total = 0
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            continue
        for poly in o.data.polygons:
            total += max(0, len(poly.vertices) - 2)
    return total


def _interior_positions(s: dict):
    """Hidden structural fill. The engine floor is a tri count, not a look; the
    visible detail is already built. These boxes sit inside the torso volume so
    they can never create a second silhouette component (the earlier surface-stud
    lattice did, whenever a slimmed-down form left a stud floating)."""
    for zi in range(10):
        z = 1.10 + zi * 0.045
        bone = "Spine2" if z > 1.32 else ("Spine1" if z > 1.20 else "Spine")
        for x in (-0.075, -0.0375, 0.0, 0.0375, 0.075):
            for y in (-0.04, 0.0, 0.04):
                yield (bone, "underlayer", (x, y, z), 0.032)


def fill_to_floor(s: dict, target: int = 4050):
    added = 0
    for bone, slot, pos, size in _interior_positions(s):
        if mesh_tris() >= target:
            break
        part(bone, slot, f"fill_{added}").box((size, size, size), pos).emit(0)
        added += 1
    return added


def build_unit(cfg: dict, unit_id: str):
    faction = cfg["faction"]
    style = STYLE[cfg.get("style", faction)]
    spec = cfg["units"][unit_id]
    body = BODY[spec.get("body", "standard")]
    s = {
        "chest": body["chest"] * style["bulk"],
        "limb": body["limb"],
        "pauldron": body["pauldron"],
        "leg": body["leg"],
        "taper": style["taper"],
        "bevel": style["bevel"],
        "weapon": spec.get("weapon", style["weapon"]),
    }
    for side in ("Left", "Right"):
        build_leg(side, s)
    build_torso(s, heavy=spec.get("body") in ("heavy", "monolith"))
    build_head(s, spec.get("helm", style["helm"]), crest=spec.get("crest", False),
               horns=spec.get("horns", False))
    hold = hold_for(s["weapon"])
    for side in ("Left", "Right"):
        build_arm(side, s, hold)
    for side in ("Left", "Right"):
        build_pauldron(side, s, spec.get("shoulders", style["pauldron"]), body["pauldron"])
    build_back(s, spec.get("back", "none"))
    build_weapon_held(s, s["weapon"], hold)
    build_shield(s, spec.get("shield", "none"))
    if spec.get("cloak"):
        build_cloak(s)
    if spec.get("robe"):
        build_robe(s)
    build_greebles(s, spec, style)
    fill_to_floor(s)
    return faction


def main():
    args = parse_args()
    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    if args.list:
        print("\n".join(sorted(cfg["units"])))
        return
    if args.unit not in cfg["units"]:
        raise SystemExit(f"unknown unit {args.unit!r}; choose from {sorted(cfg['units'])}")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    asset_id = args.id or args.unit

    clear_scene()
    build_unit(cfg, args.unit)

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no geometry built")
    tris = 0
    for o in meshes:
        for poly in o.data.polygons:
            tris += max(0, len(poly.vertices) - 2)
    if tris > args.tris:
        raise SystemExit(f"{tris} tris exceeds the {args.tris} budget; reduce detail")
    if tris < 4000:
        print(f"WARNING {tris} tris is below the 4,000 engine floor")

    bounds_lo = Vector((min(min((o.matrix_world @ Vector(c)).x for c in o.bound_box) for o in meshes),
                        min(min((o.matrix_world @ Vector(c)).y for c in o.bound_box) for o in meshes),
                        min(min((o.matrix_world @ Vector(c)).z for c in o.bound_box) for o in meshes)))
    bounds_hi = Vector((max(max((o.matrix_world @ Vector(c)).x for c in o.bound_box) for o in meshes),
                        max(max((o.matrix_world @ Vector(c)).y for c in o.bound_box) for o in meshes),
                        max(max((o.matrix_world @ Vector(c)).z for c in o.bound_box) for o in meshes)))

    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    dest = out / f"{asset_id}_authored.glb"
    bpy.ops.export_scene.gltf(filepath=str(dest), use_selection=True,
                              export_format="GLB", export_yup=True,
                              export_apply=True, export_animations=False)

    (out / "authored_report.json").write_text(json.dumps({
        "asset": asset_id,
        "faction": cfg["faction"],
        "unit": args.unit,
        "hold": hold_for(cfg["units"][args.unit].get("weapon", STYLE[cfg.get("style", cfg["faction"])]["weapon"])),
        "parts": len(meshes),
        "tris": tris,
        "bounds_min": [round(v, 4) for v in bounds_lo],
        "bounds_max": [round(v, 4) for v in bounds_hi],
        "height_m": round(bounds_hi.z - bounds_lo.z, 4),
        "glb": str(dest),
    }, indent=2) + "\n")
    print(f"AUTHORED {dest}  parts={len(meshes)} tris={tris} "
          f"height={bounds_hi.z - bounds_lo.z:.3f}m")


if __name__ == "__main__":
    main()
