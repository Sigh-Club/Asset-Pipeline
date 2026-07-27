#!/usr/bin/env python3
"""
parametric_unit_generator.py — Generate rigged humanoid Blender models from JSON config.

Usage:
    blender --background --python parametric_unit_generator.py -- --config configs/iron_directorate_line_infantry.json
    blender --background --python parametric_unit_generator.py -- --batch configs/

JSON config schema:
{
    "unit_name": "iron_directorate_line_infantry",
    "faction": "iron_directorate",
    "output_blend": "assets/units/iron_directorate_line_infantry/model/line_infantry_v2.blend",
    
    "proportions": {
        "height": 1.22,        // total height in Blender units
        "build": 1.0,          // body width multiplier (1.0 = standard, 1.2 = bulky)
        "leg_ratio": 0.42,     // legs as fraction of total height
        "arm_ratio": 0.34,     // arms as fraction of total height
        "head_ratio": 0.14     // head as fraction of total height
    },
    
    "materials": {
        "helmet": "MAT_GrimdarkMetal",
        "torso": "MAT_GrimdarkMetal",
        "shoulders": "MAT_GrimdarkMetal",
        "upper_arms": "MAT_GrimdarkFabric",
        "forearms": "MAT_GrimdarkLeather",
        "thighs": "MAT_GrimdarkFabric",
        "shins": "MAT_GrimdarkMetal",
        "boots": "MAT_GrimdarkLeather",
        "weapon_body": "MAT_GrimdarkMetal",
        "weapon_stock": "MAT_GrimdarkLeather",
        "accent": "MAT_ImperialGold"
    },
    
    "weapon": {
        "type": "rifle",        // rifle | pistol | melee | heavy | none
        "position": "right_hand"
    },
    
    "equipment": {
        "backpack": true,
        "pauldrons": true,
        "crest": true,
        "visor": true,
        "aquila": true
    },
    
    "animation_params": {
        "idle_intensity": 0.3,    // breathing amplitude
        "walk_stride": 0.15,      // step length
        "attack_speed": 1.0       // attack speed multiplier
    }
}
"""

import bpy
import os
import sys
import json
import math
import mathutils

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
MATERIAL_BLEND = os.path.join(PROJECT_ROOT, "assets", "materials", "grimdark_materials.blend")

# Import non-humanoid templates if available
try:
    sys.path.insert(0, SCRIPT_DIR)
    from parametric_vehicle_generator import (
        generate_vehicle, create_vehicle_armature,
        generate_creature, create_creature_armature,
        generate_insectoid, create_insectoid_armature,
        get_nonhumanoid_animations,
    )
    NONHUMANOID_AVAILABLE = True
except ImportError:
    NONHUMANOID_AVAILABLE = False
    print("[generator] Non-humanoid templates not available (parametric_vehicle_generator.py not found)")

# =============================================================================
# ARG PARSING
# =============================================================================

def parse_args():
    args = []
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
    
    config_path = None
    batch_dir = None
    i = 0
    while i < len(args):
        if args[i] == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        elif args[i] == "--batch" and i + 1 < len(args):
            batch_dir = args[i + 1]
            i += 2
        else:
            i += 1
    return config_path, batch_dir

# =============================================================================
# MATERIAL LOADING
# =============================================================================

def load_materials():
    if not os.path.exists(MATERIAL_BLEND):
        print(f"ERROR: Material library not found at {MATERIAL_BLEND}")
        print("Run create_material_library.py first.")
        sys.exit(1)
    
    with bpy.data.libraries.load(MATERIAL_BLEND) as (data_from, _):
        mat_names = list(data_from.materials)
    
    for name in mat_names:
        bpy.ops.wm.append(
            filepath=os.path.join(MATERIAL_BLEND, "Material", name),
            directory=os.path.join(MATERIAL_BLEND, "Material"),
            filename=name,
        )
    
    mats = {m.name: m for m in bpy.data.materials}
    print(f"Loaded {len(mats)} materials")
    return mats


def assign_material(obj, mats, mat_name):
    if mat_name in mats:
        obj.data.materials.clear()
        obj.data.materials.append(mats[mat_name])

# =============================================================================
# GEOMETRY HELPERS
# =============================================================================

def add_subsurf(obj, levels=3, render_levels=4):
    """Add subdivision surface modifier for organic/smooth parts (head, cloth)."""
    mod = obj.modifiers.new(name="Subsurf", type='SUBSURF')
    mod.levels = levels
    mod.render_levels = render_levels
    mod.subdivision_type = 'CATMULL_CLARK'

def add_hard_surface(obj, bevel_width=0.008, bevel_segments=2):
    """Hard-surface armour finish: edge split + limited bevel.

    For DoW1-style chunky armour. Keeps sharp edges where surfaces meet
    while slightly bevelling the most exposed vertices. No subsurf smoothing.
    """
    # Edge split — creates sharp creases at angle boundaries
    edge_split = obj.modifiers.new(name="EdgeSplit", type='EDGE_SPLIT')
    edge_split.split_angle = math.radians(30)
    # Limited bevel — only bevells the sharpest edges
    bevel = obj.modifiers.new(name="Bevel", type='BEVEL')
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(30)
    bevel.width = bevel_width
    bevel.segments = bevel_segments
    bevel.loop_slide = True

def add_bevel(obj, width=0.005, segments=3):
    """Add bevel modifier with higher segment count for smooth edges."""
    mod = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(30)
    mod.width = width
    mod.segments = segments

def shade_flat(obj):
    """Flat shading for hard-surface armour look — facets catch light."""
    for poly in obj.data.polygons:
        poly.use_smooth = False

def shade_smooth(obj):
    for poly in obj.data.polygons:
        poly.use_smooth = True

def simple_uv_unwrap(obj):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.select_set(False)


# =============================================================================
# ATLAS UV ASSIGNMENT — map each part's UVs into a tile of the per-unit diffuse atlas
# (matches tools/pbr/paint_unit_diffuse.py TILE_LAYOUT). DoW1 detail lives in the
# painted diffuse texture, not geometry, so parts must sample predictable atlas tiles.
# =============================================================================

try:
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "pbr"))
    from atlas_layout import TILE_LAYOUT as _ATLAS_TILE_LAYOUT
    _ATLAS_TILES_PER_ROW = 4
    _ATLAS_TILE_FRAC = 1.0 / _ATLAS_TILES_PER_ROW
    _ATLAS_MARGIN_FRAC = 0.02
except ImportError:
    _ATLAS_TILE_LAYOUT = None

# Object name prefix (lowercased, underscores stripped) -> atlas tile key.
_ANCHOR_NAME_MAP = [
    ("torso", "torso"),
    ("helmet", "helmet"), ("visor", "helmet"), ("crest", "helmet"),
    ("pauldron", "pauldron"),
    ("upperarm", "upper_arm"),
    ("forearm", "forearm"), ("elbowguard", "forearm"),
    ("thigh", "thigh"), ("hipplate", "thigh"),
    ("shin", "shin"), ("kneepad", "shin"), ("kneespike", "shin"),
    ("boot", "boot"),
    ("beltring", "belt"), ("beltbuckle", "belt"), ("pouch", "belt"), ("belt", "belt"),
    ("codpiece", "codpiece"), ("tabard", "codpiece"),
    ("backpack", "backpack"), ("vent", "backpack"),
    ("rifle", "weapon"), ("pistol", "weapon"), ("weapon", "weapon"),
    ("scope", "weapon"), ("magazine", "weapon"), ("barrel", "weapon"), ("sight", "weapon"),
]


def _anchor_key_for(obj):
    name = obj.name.lower().replace("_", "")
    for prefix, key in _ANCHOR_NAME_MAP:
        if name.startswith(prefix):
            return key
    return None


def _tile_uv_rect(row, col):
    u0 = col * _ATLAS_TILE_FRAC + _ATLAS_MARGIN_FRAC
    u1 = (col + 1) * _ATLAS_TILE_FRAC - _ATLAS_MARGIN_FRAC
    v0 = (_ATLAS_TILES_PER_ROW - 1 - row) * _ATLAS_TILE_FRAC + _ATLAS_MARGIN_FRAC
    v1 = (_ATLAS_TILES_PER_ROW - row) * _ATLAS_TILE_FRAC - _ATLAS_MARGIN_FRAC
    return u0, v0, u1, v1


def _remap_obj_uv_to_tile(obj, row, col):
    """Box-project each face into its atlas tile based on face normal (deterministic).

    For each face, the dominant normal axis selects which two object-space axes drive
    the UV (+Y front -> X,Z; +X side -> Y,Z; +Z top -> X,Y). This is a deterministic
    cube/cylinder-style unwrap that always places each face inside its tile, unlike
    smart_project whose arbitrary orientation scatters faces across tiles.
    """
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    uv_layer = obj.data.uv_layers.active
    verts = [v.co for v in obj.data.vertices]
    minc = [min(v[i] for v in verts) for i in range(3)]
    maxc = [max(v[i] for v in verts) for i in range(3)]
    span = [max(maxc[i] - minc[i], 1e-6) for i in range(3)]
    u0, v0, u1, v1 = _tile_uv_rect(row, col)
    tw, th = u1 - u0, v1 - v0
    for poly in obj.data.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 0:      ua, va = 1, 2    # X-dominant face -> use Y,Z
        elif ax == 1:    ua, va = 0, 2    # Y-dominant face -> use X,Z
        else:            ua, va = 0, 1    # Z-dominant face -> use X,Y
        for li in poly.loop_indices:
            co = obj.data.vertices[obj.data.loops[li].vertex_index].co
            uu = (co[ua] - minc[ua]) / span[ua]
            vv = (co[va] - minc[va]) / span[va]
            uv_layer.data[li].uv = (u0 + uu * tw, v0 + vv * th)


def remap_uvs_to_atlas(all_parts):
    """Remap every part's UVs into its atlas tile. Anchor parts by name; small greebles
    inherit the tile of the nearest anchor by object-origin distance (so rivets/trim/vents
    sample the same tile as their parent body part)."""
    if _ATLAS_TILE_LAYOUT is None:
        print("  [atlas] paint_unit_diffuse unavailable, skipping UV remap")
        return
    anchors = [(o, _anchor_key_for(o)) for o in all_parts if _anchor_key_for(o)]
    for o in all_parts:
        if o.get("atlas_uv_manual"):
            continue   # UVs set explicitly (e.g. chest aquila decal)
        k = _anchor_key_for(o)
        if k is None and anchors:
            oc = o.matrix_world.translation
            best = min(anchors, key=lambda a: (a[0].matrix_world.translation - oc).length_squared)
            k = best[1]
        if k is None or k not in _ATLAS_TILE_LAYOUT:
            continue
        row, col = _ATLAS_TILE_LAYOUT[k]
        _remap_obj_uv_to_tile(o, row, col)


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for arm in list(bpy.data.armatures):
        bpy.data.armatures.remove(arm)

# =============================================================================
# PARAMETRIC BODY PARTS
# =============================================================================

def create_head(config, mats, z_top):
    """Create helmet/head."""
    props = config["proportions"]
    head_h = props["height"] * props["head_ratio"]
    head_r = head_h * 0.45 * props.get("build", 1.0)
    head_z = z_top - head_h * 0.5
    
    parts = []
    eq = config.get("equipment", {})
    mat_helm = config["materials"].get("helmet", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
    # Dark lens material for the visor eye-slit — falls back to leather if unavailable
    mat_lens = config["materials"].get("visor_lens", "MAT_GrimdarkLeather")
    
    # Main helmet — faceted flat-faced helmet (NOT a sphere). A cube reads as a helmet at
    # sprite scale; a sphere reads as a bare head. Bevelled + flat-shaded for hard-surface edges.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, head_z))
    helm = bpy.context.active_object
    helm.name = "Helmet"
    for v in helm.data.vertices:
        v.co.x *= head_r * 1.05   # full width — slightly wider than the old sphere
        v.co.y *= head_r * 1.15   # full depth — front-to-back helmet
        v.co.z *= head_r * 1.10   # full height — tall dome
        if v.co.z < 0:
            v.co.z *= 0.7         # taper the jaw/chin narrower than the crown
        if v.co.y < 0:
            v.co.y *= 0.85        # slight rear taper
    assign_material(helm, mats, mat_helm)
    add_hard_surface(helm, bevel_width=0.004, bevel_segments=2)
    shade_flat(helm)
    simple_uv_unwrap(helm)
    parts.append(helm)
    
    if eq.get("visor", True):
        # Dark eye-slit slab on the flat front face of the helmet. Cube vertices are at ±0.5,
        # so factors give FULL extents of ~2*0.5*factor. Uses a distinct dark-lens material so
        # it reads as an eye slit, not a patch of the same helmet colour.
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, head_r * 1.05, head_z - head_h * 0.04))
        visor = bpy.context.active_object
        visor.name = "Visor"
        for v in visor.data.vertices:
            v.co.x *= head_r * 1.80   # full width ~0.9*head_r — spans most of the face
            v.co.y *= head_r * 0.50   # full depth ~0.5*head_r — recessed into the flat face
            v.co.z *= head_r * 0.45   # full height ~0.45*head_r — horizontal eye band
        assign_material(visor, mats, mat_lens)
        shade_flat(visor)
        parts.append(visor)

    if eq.get("crest", True):
        # Pronounced dorsal fin sitting ON TOP of the helmet (head top at z ~= head_z +
        # head_r*0.85). Base embeds into the helmet, fin rises clearly above the crown.
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -head_r * 0.05, head_z + head_r * 1.0))
        crest = bpy.context.active_object
        crest.name = "Crest"
        for v in crest.data.vertices:
            v.co.x *= head_r * 0.50   # thin sideways
            v.co.y *= head_r * 1.50   # long front-to-back
            v.co.z *= head_r * 0.90   # tall fin, rises well above the helmet
        assign_material(crest, mats, mat_accent)
        add_hard_surface(crest, bevel_width=0.002, bevel_segments=1)
        shade_flat(crest)
        simple_uv_unwrap(crest)
        parts.append(crest)
    
    return parts, head_z, head_h, head_r


def create_tabard(config, mats, torso_z, torso_h, leg_x):
    """Create a tabard/codpiece that extends below the torso belt area.
    
    Adds side-profile volume visible from E/W views, improving direction variance.
    Iron Directorate = armoured plate, Cinderborn = tattered cloth.
    """
    parts = []
    faction = config.get("faction", "iron_directorate")
    eq = config.get("equipment", {})
    
    if faction == "cinderborn":
        # Tattered cloth tabard — thinner, irregular
        mat_tabard = config["materials"].get("thighs", "MAT_GrimdarkFabric")
        torso_bottom = torso_z - torso_h * 0.5
        tabard_h = 0.14 * config["proportions"].get("build", 1.0)
        
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, torso_bottom - tabard_h * 0.5))
        tabard = bpy.context.active_object
        tabard.name = "Tabard"
        for v in tabard.data.vertices:
            v.co.x *= leg_x * 0.8
            v.co.y *= 0.06 * config["proportions"].get("build", 1.0)
            v.co.z *= tabard_h * 0.5
            # Taper: wider at bottom for cloth look
            if v.co.z < 0:
                v.co.x *= 1.3
        assign_material(tabard, mats, mat_tabard)
        add_subsurf(tabard, levels=1, render_levels=2)
        shade_smooth(tabard)
        simple_uv_unwrap(tabard)
        parts.append(tabard)
    else:
        # Armoured codpiece plate (Iron Directorate)
        mat_plate = config["materials"].get("torso", "MAT_GrimdarkMetal")
        mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
        torso_bottom = torso_z - torso_h * 0.5
        plate_h = 0.08 * config["proportions"].get("build", 1.0)
        
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.04 * config["proportions"].get("build", 1.0), torso_bottom - plate_h * 0.5))
        plate = bpy.context.active_object
        plate.name = "Codpiece"
        for v in plate.data.vertices:
            v.co.x *= leg_x * 0.9
            v.co.y *= 0.05 * config["proportions"].get("build", 1.0)
            v.co.z *= plate_h * 0.5
            if v.co.z < 0:
                v.co.y *= 0.7  # Taper to crotch
        assign_material(plate, mats, mat_plate)
        add_hard_surface(plate, bevel_width=0.005, bevel_segments=2)
        shade_flat(plate)
        simple_uv_unwrap(plate)
        parts.append(plate)
        
        # Gold trim on codpiece edge
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.05 * config["proportions"].get("build", 1.0), torso_bottom - plate_h))
        trim = bpy.context.active_object
        trim.name = "CodpieceTrim"
        for v in trim.data.vertices:
            v.co.x *= leg_x * 0.8
            v.co.y *= 0.005
            v.co.z *= 0.01
        assign_material(trim, mats, mat_accent)
        parts.append(trim)
    
    return parts


def create_torso(config, mats, z_top, head_h):
    """Create torso/chest armor."""
    props = config["proportions"]
    build = props.get("build", 1.0)
    torso_h = props["height"] * (1.0 - props["leg_ratio"] - props["head_ratio"] - 0.02)
    torso_z = z_top - head_h - torso_h * 0.5
    
    parts = []
    mat_torso = config["materials"].get("torso", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
    eq = config.get("equipment", {})
    
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, torso_z))
    torso = bpy.context.active_object
    torso.name = "Torso"
    for v in torso.data.vertices:
        v.co.x *= 0.22 * build
        v.co.y *= 0.14 * build
        v.co.z *= torso_h * 0.5
        if v.co.z < 0:
            v.co.x *= 0.85
            v.co.y *= 0.80
    assign_material(torso, mats, mat_torso)
    add_hard_surface(torso, bevel_width=0.008, bevel_segments=2)
    shade_flat(torso)
    simple_uv_unwrap(torso)
    parts.append(torso)
    
    if eq.get("aquila", True):
        # Chest aquila as a FLAT DECAL plate facing +Y, with UVs mapped exactly to the
        # dedicated "aquila" atlas tile — so the painted imperial eagle always lands
        # centred on the chest front (not at the mercy of smart-project orientation).
        bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0.150 * build, torso_z + torso_h * 0.10))
        aquila = bpy.context.active_object
        aquila.name = "Aquila"
        aquila.rotation_euler = (math.radians(90), 0.0, 0.0)  # face +Y
        aquila.scale = (0.20 * build, 0.17 * build, 1.0)
        # Set UVs to the aquila tile rect directly (single quad)
        if _ATLAS_TILE_LAYOUT is not None and "aquila" in _ATLAS_TILE_LAYOUT:
            arow, acol = _ATLAS_TILE_LAYOUT["aquila"]
            u0, v0, u1, v1 = _tile_uv_rect(arow, acol)
        else:
            u0, v0, u1, v1 = 0.0, 0.0, 1.0, 1.0
        uv = aquila.data.uv_layers.active.data
        # plane loops in order: (0,0)->(1,0)->(1,1)->(0,1) after rotate; map to tile corners
        corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
        for li, corner in enumerate(corners):
            uv[li].uv = (corner[0], corner[1])
        aquila["atlas_uv_manual"] = True   # skip general atlas remap (UVs set explicitly)
        assign_material(aquila, mats, mat_accent)
        shade_flat(aquila)
        parts.append(aquila)
    
    return parts, torso_z, torso_h


def create_belt(config, mats, torso_z, torso_h, leg_x):
    """Create belt/webbing detail at the waist.
    
    Adds a belt ring with pouches at the waistline for silhouette depth,
    particularly improving E/W side-profile visibility.
    """
    build = config["proportions"].get("build", 1.0)
    eq = config.get("equipment", {})
    mat_armour = config["materials"].get("torso", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
    mat_leather = config["materials"].get("boots", "MAT_GrimdarkLeather")
    
    torso_bottom = torso_z - torso_h * 0.5
    
    parts = []
    
    # Belt ring — thin strip around waist
    bpy.ops.mesh.primitive_torus_add(
        location=(0, 0, torso_bottom),
        major_radius=0.18 * build,
        minor_radius=0.015 * build,
        major_segments=32,
        minor_segments=6,
    )
    belt = bpy.context.active_object
    belt.name = "BeltRing"
    # Flatten slightly
    for v in belt.data.vertices:
        v.co.z *= 0.4
        v.co.y *= 0.8  # Oval shape (wider front-to-back)
    assign_material(belt, mats, mat_leather)
    parts.append(belt)
    
    # Belt buckle (front centre)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.16 * build, torso_bottom))
    buckle = bpy.context.active_object
    buckle.name = "BeltBuckle"
    for v in buckle.data.vertices:
        v.co.x *= 0.04 * build
        v.co.y *= 0.02 * build
        v.co.z *= 0.03 * build
    assign_material(buckle, mats, mat_accent)
    add_hard_surface(buckle, bevel_width=0.002, bevel_segments=1)
    shade_flat(buckle)
    parts.append(buckle)
    
    # Pouches on right hip
    for i, (side_label, side_x, sign) in enumerate([("R", 0.12 * build, -1), ("L", -0.12 * build, 1)]):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(side_x, 0.10 * build * (i * 0.5 + 0.5), torso_bottom - 0.02 * build))
        pouch = bpy.context.active_object
        pouch.name = f"Pouch_{side_label}"
        for v in pouch.data.vertices:
            v.co.x *= 0.025 * build
            v.co.y *= 0.03 * build
            v.co.z *= 0.04 * build
        assign_material(pouch, mats, mat_leather)
        add_hard_surface(pouch, bevel_width=0.002, bevel_segments=1)
        shade_flat(pouch)
        parts.append(pouch)
    
    return parts


def create_shoulders(config, mats, torso_z, torso_h):
    props = config["proportions"]
    build = props.get("build", 1.0)
    pauldron_r = 0.13 * build  # was 0.07 — dominant overhanging pauldron (heroic +30%+)
    shoulder_z = torso_z + torso_h * 0.40   # sit pauldrons atop the shoulder, not flush with arm
    shoulder_x = 0.30 * build  # widened for better side-view coverage (was 0.26)
    
    parts = []
    mat_shoulder = config["materials"].get("shoulders", "MAT_GrimdarkMetal")
    eq = config.get("equipment", {})
    
    if not eq.get("pauldrons", True):
        return parts, shoulder_z, shoulder_x
    
    for side, x in [("L", -shoulder_x), ("R", shoulder_x)]:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=pauldron_r, location=(x, 0, shoulder_z))
        pauldron = bpy.context.active_object
        pauldron.name = f"Pauldron_{side}"
        for v in pauldron.data.vertices:
            v.co.z *= 0.6
            # Flatten inner face slightly for armour plate look
            if abs(v.co.x) < 0.1:
                v.co.x *= 0.8
        assign_material(pauldron, mats, mat_shoulder)
        add_hard_surface(pauldron, bevel_width=0.005, bevel_segments=2)
        shade_flat(pauldron)
        simple_uv_unwrap(pauldron)
        parts.append(pauldron)
        
        # Trim ring around pauldron edge (accent colour)
        mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
        trim_r = pauldron_r * 0.85
        bpy.ops.mesh.primitive_torus_add(
            location=(x, 0, shoulder_z),
            major_radius=trim_r,
            minor_radius=0.008,
            major_segments=32,
            minor_segments=8,
        )
        trim_ring = bpy.context.active_object
        trim_ring.name = f"PauldronTrim_{side}"
        # Flatten the torus to match the pauldron shape
        for v in trim_ring.data.vertices:
            v.co.z *= 0.6
        # Scale outward to sit on pauldron rim
        for v in trim_ring.data.vertices:
            # Scale only horizontal components
            v.co.x *= 1.15
            v.co.y *= 1.15
        assign_material(trim_ring, mats, mat_accent)
        parts.append(trim_ring)
    
    return parts, shoulder_z, shoulder_x


def create_arms(config, mats, shoulder_z, shoulder_x):
    """Create upper arms, forearms, and hands."""
    props = config["proportions"]
    build = props.get("build", 1.0)
    arm_h = props["height"] * props["arm_ratio"]
    upper_h = arm_h * 0.5
    lower_h = arm_h * 0.5
    
    parts = []
    mat_upper = config["materials"].get("upper_arms", "MAT_GrimdarkFabric")
    mat_lower = config["materials"].get("forearms", "MAT_GrimdarkLeather")
    
    for side, x in [("L", -shoulder_x), ("R", shoulder_x)]:
        upper_z = shoulder_z - upper_h * 0.5
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.04 * build, depth=upper_h, location=(x, 0, upper_z))
        upper = bpy.context.active_object
        upper.name = f"UpperArm_{side}"
        assign_material(upper, mats, mat_upper)
        add_hard_surface(upper, bevel_width=0.005, bevel_segments=1)
        shade_flat(upper)
        simple_uv_unwrap(upper)
        parts.append(upper)
        
        lower_z = upper_z - upper_h * 0.5 - lower_h * 0.5
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.035 * build, depth=lower_h, location=(x, 0, lower_z))
        lower = bpy.context.active_object
        lower.name = f"Forearm_{side}"
        assign_material(lower, mats, mat_lower)
        add_hard_surface(lower, bevel_width=0.005, bevel_segments=1)
        shade_flat(lower)
        simple_uv_unwrap(lower)
        parts.append(lower)
    
    # Return arm joint positions for rigging
    arm_joints = {
        "shoulder_l": (-shoulder_x, 0, shoulder_z),
        "shoulder_r": (shoulder_x, 0, shoulder_z),
        "elbow_l": (-shoulder_x * 0.75, 0, upper_z - upper_h * 0.5),
        "elbow_r": (shoulder_x * 0.75, 0, upper_z - upper_h * 0.5),
        "wrist_l": (-shoulder_x * 0.75, 0, lower_z),
        "wrist_r": (shoulder_x * 0.75, 0, lower_z),
    }
    return parts, arm_joints


def create_legs(config, mats, torso_z, torso_h):
    """Create thighs, shins, and boots."""
    props = config["proportions"]
    build = props.get("build", 1.0)
    leg_h = props["height"] * props["leg_ratio"]
    thigh_h = leg_h * 0.5
    shin_h = leg_h * 0.5
    leg_x = 0.10 * build  # widened for stable stance + side-view coverage (was 0.08)
    
    torso_bottom = torso_z - torso_h * 0.5
    
    parts = []
    mat_thigh = config["materials"].get("thighs", "MAT_GrimdarkFabric")
    mat_shin = config["materials"].get("shins", "MAT_GrimdarkMetal")
    mat_boot = config["materials"].get("boots", "MAT_GrimdarkLeather")
    
    for side, x in [("L", -leg_x), ("R", leg_x)]:
        thigh_z = torso_bottom - thigh_h * 0.5
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.05 * build, depth=thigh_h, location=(x, 0, thigh_z))
        thigh = bpy.context.active_object
        thigh.name = f"Thigh_{side}"
        assign_material(thigh, mats, mat_thigh)
        add_hard_surface(thigh, bevel_width=0.005, bevel_segments=2)
        shade_flat(thigh)
        simple_uv_unwrap(thigh)
        parts.append(thigh)
        
        shin_z = thigh_z - thigh_h * 0.5 - shin_h * 0.5
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.045 * build, depth=shin_h, location=(x, 0, shin_z))
        shin = bpy.context.active_object
        shin.name = f"Shin_{side}"
        assign_material(shin, mats, mat_shin)
        add_hard_surface(shin, bevel_width=0.005, bevel_segments=2)
        shade_flat(shin)
        simple_uv_unwrap(shin)
        parts.append(shin)
        
        boot_z = shin_z - shin_h * 0.5 - 0.03 * build
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0.02 * build, boot_z))
        boot = bpy.context.active_object
        boot.name = f"Boot_{side}"
        for v in boot.data.vertices:
            v.co.x *= 0.05 * build
            v.co.y *= 0.09 * build
            v.co.z *= 0.06 * build
        assign_material(boot, mats, mat_boot)
        add_hard_surface(boot, bevel_width=0.005, bevel_segments=2)
        shade_flat(boot)
        simple_uv_unwrap(boot)
        parts.append(boot)
        
        # --- Kneepad (hard-surface armour plate) ---
        mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
        kneepad_z = shin_z + shin_h * 0.35
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0.055 * build, kneepad_z))
        kneepad = bpy.context.active_object
        kneepad.name = f"Kneepad_{side}"
        for v in kneepad.data.vertices:
            v.co.x *= 0.035 * build
            v.co.y *= 0.005
            v.co.z *= 0.025 * build
            # Round front face
            if v.co.y > 0:
                v.co.x *= 1.2
        assign_material(kneepad, mats, mat_shin)
        add_hard_surface(kneepad, bevel_width=0.003, bevel_segments=2)
        shade_flat(kneepad)
        simple_uv_unwrap(kneepad)
        parts.append(kneepad)
        
        # Kneepad gold trim edge
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, 0.058 * build, kneepad_z))
        trim = bpy.context.active_object
        trim.name = f"KneepadTrim_{side}"
        for v in trim.data.vertices:
            v.co.x *= 0.038 * build
            v.co.y *= 0.002
            v.co.z *= 0.002
        assign_material(trim, mats, mat_accent)
        parts.append(trim)
    
    leg_joints = {
        "hip_l": (-leg_x, 0, torso_bottom),
        "hip_r": (leg_x, 0, torso_bottom),
        "knee_l": (-leg_x, 0, thigh_z - thigh_h * 0.5),
        "knee_r": (leg_x, 0, thigh_z - thigh_h * 0.5),
        "ankle_l": (-leg_x, 0, shin_z - shin_h * 0.5),
        "ankle_r": (leg_x, 0, shin_z - shin_h * 0.5),
        "foot_l": (-leg_x, 0.02 * build, boot_z),
        "foot_r": (leg_x, 0.02 * build, boot_z),
    }
    return parts, leg_joints


def create_weapon(config, mats, arm_joints):
    """Create weapon based on type."""
    weapon_type = config.get("weapon", {}).get("type", "none")
    if weapon_type == "none":
        return []
    
    mat_body = config["materials"].get("weapon_body", "MAT_GrimdarkMetal")
    mat_stock = config["materials"].get("weapon_stock", "MAT_GrimdarkLeather")
    
    parts = []
    wrist_r = arm_joints.get("wrist_r", (0.17, 0, 1.32))
    
    if weapon_type == "rifle":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] + 0.10, wrist_r[2]))
        body = bpy.context.active_object
        body.name = "WeaponBody"
        for v in body.data.vertices:
            v.co.x *= 0.025
            v.co.y *= 0.15
            v.co.z *= 0.035
        assign_material(body, mats, mat_body)
        parts.append(body)
        
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.012, depth=0.12, location=(wrist_r[0], wrist_r[1] + 0.22, wrist_r[2]))
        barrel = bpy.context.active_object
        barrel.name = "WeaponBarrel"
        barrel.rotation_euler = (math.radians(90), 0, 0)
        assign_material(barrel, mats, mat_body)
        parts.append(barrel)
        
        # Scope (mounted on top of weapon body)
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.008, depth=0.04, location=(wrist_r[0], wrist_r[1] + 0.12, wrist_r[2] + 0.04))
        scope = bpy.context.active_object
        scope.name = "WeaponScope"
        scope.rotation_euler = (math.radians(90), 0, 0)
        assign_material(scope, mats, mat_body)
        parts.append(scope)
        
        # Scope lens (small disc on front)
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.006, depth=0.002, location=(wrist_r[0], wrist_r[1] + 0.14, wrist_r[2] + 0.04))
        lens = bpy.context.active_object
        lens.name = "WeaponLens"
        lens.rotation_euler = (math.radians(90), 0, 0)
        mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
        assign_material(lens, mats, mat_accent)
        parts.append(lens)
        
        # Magazine (curved box under barrel)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] + 0.10, wrist_r[2] - 0.04))
        magazine = bpy.context.active_object
        magazine.name = "WeaponMagazine"
        for v in magazine.data.vertices:
            v.co.x *= 0.02
            v.co.y *= 0.04
            v.co.z *= 0.06
        assign_material(magazine, mats, mat_body)
        add_hard_surface(magazine, bevel_width=0.002, bevel_segments=1)
        shade_flat(magazine)
        parts.append(magazine)
        
        # Front grip/foregrip
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] + 0.16, wrist_r[2] - 0.01))
        foregrip = bpy.context.active_object
        foregrip.name = "WeaponForegrip"
        for v in foregrip.data.vertices:
            v.co.x *= 0.015
            v.co.y *= 0.02
            v.co.z *= 0.03
        assign_material(foregrip, mats, mat_stock)
        parts.append(foregrip)
        
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] - 0.02, wrist_r[2] - 0.02))
        stock = bpy.context.active_object
        stock.name = "WeaponStock"
        for v in stock.data.vertices:
            v.co.x *= 0.03
            v.co.y *= 0.04
            v.co.z *= 0.06
        assign_material(stock, mats, mat_stock)
        parts.append(stock)
        
        # --- Muzzle detail: barrel tip ring ---
        barrel_tip_y = wrist_r[1] + 0.28
        mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
        
        bpy.ops.mesh.primitive_torus_add(
            location=(wrist_r[0], barrel_tip_y, wrist_r[2]),
            major_radius=0.016,
            minor_radius=0.003,
            major_segments=24,
            minor_segments=6,
        )
        tip_ring = bpy.context.active_object
        tip_ring.name = "MuzzleTipRing"
        tip_ring.rotation_euler = (math.radians(90), 0, 0)
        assign_material(tip_ring, mats, mat_accent)
        parts.append(tip_ring)
        
        # --- Muzzle detail: sight post (front blade sight) ---
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], barrel_tip_y - 0.02, wrist_r[2] + 0.02))
        sight = bpy.context.active_object
        sight.name = "SightPost"
        for v in sight.data.vertices:
            v.co.x *= 0.004
            v.co.y *= 0.004
            v.co.z *= 0.02
        assign_material(sight, mats, mat_body)
        add_hard_surface(sight, bevel_width=0.001, bevel_segments=1)
        shade_flat(sight)
        parts.append(sight)
    
    elif weapon_type == "pistol":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] + 0.05, wrist_r[2]))
        body = bpy.context.active_object
        body.name = "WeaponBody"
        for v in body.data.vertices:
            v.co.x *= 0.03
            v.co.y *= 0.06
            v.co.z *= 0.04
        assign_material(body, mats, mat_body)
        parts.append(body)
    
    elif weapon_type == "melee":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.015, depth=0.18, location=(wrist_r[0], wrist_r[1] + 0.09, wrist_r[2]))
        blade = bpy.context.active_object
        blade.name = "WeaponBlade"
        blade.rotation_euler = (math.radians(90), 0, 0)
        assign_material(blade, mats, mat_body)
        parts.append(blade)
    
    elif weapon_type == "heavy":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] + 0.12, wrist_r[2]))
        body = bpy.context.active_object
        body.name = "WeaponBody"
        for v in body.data.vertices:
            v.co.x *= 0.04
            v.co.y *= 0.18
            v.co.z *= 0.06
        assign_material(body, mats, mat_body)
        parts.append(body)
        
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.03, depth=0.08, location=(wrist_r[0], wrist_r[1] - 0.05, wrist_r[2] - 0.04))
        drum = bpy.context.active_object
        drum.name = "WeaponDrum"
        drum.rotation_euler = (0, math.radians(90), 0)
        assign_material(drum, mats, mat_body)
        parts.append(drum)
    
    return parts


def create_backpack(config, mats, torso_z, torso_h):
    eq = config.get("equipment", {})
    if not eq.get("backpack", True):
        return []
    
    build = config["proportions"].get("build", 1.0)
    mat_pack = config["materials"].get("torso", "MAT_GrimdarkMetal")
    
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.16 * build, torso_z + torso_h * 0.05))
    pack = bpy.context.active_object
    pack.name = "Backpack"
    for v in pack.data.vertices:
        v.co.x *= 0.10 * build
        v.co.y *= 0.06 * build
        v.co.z *= 0.14 * build
    assign_material(pack, mats, mat_pack)
    add_bevel(pack, width=0.004, segments=3)
    add_subsurf(pack, levels=3, render_levels=4)
    shade_smooth(pack)
    simple_uv_unwrap(pack)
    return [pack]


# =============================================================================
# DETAIL ELEMENTS — Hard-Surface Armour Greebles
# =============================================================================

def create_torso_panel_lines(config, mats, torso_z, torso_h):
    """Add thin inset panel line strips along torso chest plate edges.

    Creates geometry strips simulating armour plate seams for DoW1-style
    hard-surface detail. Each strip uses add_hard_surface + shade_flat.
    """
    build = config["proportions"].get("build", 1.0)
    mat_armour = config["materials"].get("torso", "MAT_GrimdarkMetal")

    parts = []
    panel_w = 0.003 * build   # Width of each panel line
    panel_d = 0.003 * build   # Depth (protrusion from surface)
    side_off = 0.16 * build   # Side offset for vertical lines
    front_off = 0.10 * build  # Front surface offset

    torso_mid = torso_z

    # 1. Left and right vertical panel lines (chest plate edge seams)
    for sign in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(sign * side_off, front_off, torso_mid))
        outer = bpy.context.active_object
        outer.name = f"PanelLine_Torso_Vert_{'L' if sign < 0 else 'R'}"
        for v in outer.data.vertices:
            v.co.x *= panel_w * 0.5
            v.co.y *= panel_d * 0.5
            v.co.z *= torso_h * 0.55
        assign_material(outer, mats, mat_armour)
        add_hard_surface(outer, bevel_width=0.001, bevel_segments=1)
        shade_flat(outer)
        parts.append(outer)

    # 2. Top horizontal panel line (upper chest seam)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, front_off, torso_mid + torso_h * 0.42))
    top_line = bpy.context.active_object
    top_line.name = "PanelLine_Torso_Top"
    for v in top_line.data.vertices:
        v.co.x *= side_off * 0.8
        v.co.y *= panel_d * 0.5
        v.co.z *= panel_w * 0.5
    assign_material(top_line, mats, mat_armour)
    add_hard_surface(top_line, bevel_width=0.001, bevel_segments=1)
    shade_flat(top_line)
    parts.append(top_line)

    # 3. Center vertical panel line (chest centre seam / chest plate divide)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, front_off + 0.02 * build, torso_mid))
    center_line = bpy.context.active_object
    center_line.name = "PanelLine_Torso_Center"
    for v in center_line.data.vertices:
        v.co.x *= panel_w * 0.5
        v.co.y *= panel_d * 0.5
        v.co.z *= torso_h * 0.35
    assign_material(center_line, mats, mat_armour)
    add_hard_surface(center_line, bevel_width=0.001, bevel_segments=1)
    shade_flat(center_line)
    parts.append(center_line)

    # 4. Horizontal abdominal panel line (below chest plate divide)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, front_off * 0.8, torso_mid - torso_h * 0.15))
    mid_line = bpy.context.active_object
    mid_line.name = "PanelLine_Torso_Abdominal"
    for v in mid_line.data.vertices:
        v.co.x *= side_off * 0.65
        v.co.y *= panel_d * 0.5
        v.co.z *= panel_w * 0.5
    assign_material(mid_line, mats, mat_armour)
    add_hard_surface(mid_line, bevel_width=0.001, bevel_segments=1)
    shade_flat(mid_line)
    parts.append(mid_line)

    return parts


def create_helmet_panel_lines(config, mats, head_z, head_h, head_r):
    """Add panel lines and ridge details to the helmet.

    Creates brow ridge, cheek plate edge strips, and neck guard ring.
    All use hard-surface modelling approach.
    """
    build = config["proportions"].get("build", 1.0)
    mat_helm = config["materials"].get("helmet", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")

    parts = []
    panel_d = 0.003 * build

    # 1. Brow ridge — horizontal ridge above visor area
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -head_r * 0.3, head_z + head_h * 0.2))
    brow = bpy.context.active_object
    brow.name = "Helmet_BrowRidge"
    for v in brow.data.vertices:
        v.co.x *= head_r * 0.7
        v.co.y *= panel_d * 0.5
        v.co.z *= 0.015 * build
    assign_material(brow, mats, mat_helm)
    add_hard_surface(brow, bevel_width=0.001, bevel_segments=1)
    shade_flat(brow)
    parts.append(brow)

    # 2. Cheek plate edges — vertical strips on helmet sides
    for sign in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(sign * head_r * 0.7, head_r * 0.2, head_z - head_h * 0.05))
        cheek = bpy.context.active_object
        cheek.name = f"Helmet_CheekPlate_{'L' if sign < 0 else 'R'}"
        for v in cheek.data.vertices:
            v.co.x *= panel_d * 0.5
            v.co.y *= panel_d * 0.5
            v.co.z *= head_h * 0.2
        assign_material(cheek, mats, mat_helm)
        add_hard_surface(cheek, bevel_width=0.001, bevel_segments=1)
        shade_flat(cheek)
        parts.append(cheek)

    # 3. Neck guard ring — partial torus at helmet base
    bpy.ops.mesh.primitive_torus_add(
        location=(0, 0, head_z - head_h * 0.35),
        major_radius=head_r * 0.9,
        minor_radius=0.012 * build,
        major_segments=32,
        minor_segments=6,
    )
    neck_ring = bpy.context.active_object
    neck_ring.name = "Helmet_NeckGuard"
    for v in neck_ring.data.vertices:
        v.co.z *= 0.35
    assign_material(neck_ring, mats, mat_accent)
    add_hard_surface(neck_ring, bevel_width=0.001, bevel_segments=1)
    shade_flat(neck_ring)
    parts.append(neck_ring)

    # 4. Visor frame line — thin strip outlining the visor
    eq = config.get("equipment", {})
    if eq.get("visor", True):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, head_r * 0.7, head_z - head_h * 0.05))
        visor_frame = bpy.context.active_object
        visor_frame.name = "Helmet_VisorFrame"
        for v in visor_frame.data.vertices:
            v.co.x *= head_r * 0.55
            v.co.y *= panel_d * 0.5
            v.co.z *= panel_d * 0.5
        assign_material(visor_frame, mats, mat_accent)
        shade_flat(visor_frame)
        parts.append(visor_frame)

    return parts


def create_outer_chest_plate(config, mats, torso_z, torso_h):
    """Create an outer chest armour plate layered over the torso with gap.

    The outer plate sits forward of the torso with a 0.005-0.01 unit gap,
    simulating layered armour plates on DoW1-style power armour.
    """
    build = config["proportions"].get("build", 1.0)
    mat_armour = config["materials"].get("torso", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")

    parts = []
    gap = 0.008 * build  # Visible gap between plates

    # Outer chest plate — wider and slightly forward of inner torso
    plate_w = 0.20 * build
    plate_h = torso_h * 0.55
    plate_d = 0.03 * build  # Thickness of outer plate
    plate_y = 0.06 * build + gap

    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, plate_y, torso_z + torso_h * 0.05))
    outer = bpy.context.active_object
    outer.name = "OuterChestPlate"
    for v in outer.data.vertices:
        v.co.x *= plate_w
        v.co.y *= plate_d
        v.co.z *= plate_h
        # Slight dome curve
        if v.co.z > 0:
            radius_val = math.sqrt(v.co.x * v.co.x + v.co.z * v.co.z)
            if radius_val > 0:
                v.co.y += 0.005 * (v.co.z / plate_h)
    assign_material(outer, mats, mat_armour)
    add_hard_surface(outer, bevel_width=0.005, bevel_segments=2)
    shade_flat(outer)
    simple_uv_unwrap(outer)
    parts.append(outer)

    # Gold trim along outer plate upper edge
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, plate_y + plate_d + 0.001, torso_z + torso_h * 0.05 + plate_h))
    trim = bpy.context.active_object
    trim.name = "OuterChestPlate_Trim"
    for v in trim.data.vertices:
        v.co.x *= plate_w * 0.85
        v.co.y *= 0.002 * build
        v.co.z *= 0.003 * build
    assign_material(trim, mats, mat_accent)
    shade_flat(trim)
    parts.append(trim)

    return parts


def create_rivets(config, mats, shoulder_z, shoulder_x, torso_z, torso_h):
    """Add small sphere clusters along pauldron edges and torso plate seams.

    Rivets are small hard-surface spheres (radius 0.003-0.005) placed at
    regular intervals along armour edges. Uses MAT_ImperialGold material.
    """
    build = config["proportions"].get("build", 1.0)
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")

    parts = []
    rivet_r = 0.004 * build
    rivet_segments = 8

    # Pauldron rivets — placed around the trim ring perimeter (front half)
    for side_sign in (-1, 1):
        pauldron_center_z = shoulder_z
        pauldron_r = 0.07 * build * 0.85  # Inside trim ring radius
        rivet_count = 5
        for i in range(rivet_count):
            angle = -math.radians(60) + (i / (rivet_count - 1)) * math.radians(120)
            rx = pauldron_r * math.cos(angle)
            ry = pauldron_r * math.sin(angle)
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=rivet_segments,
                ring_count=rivet_segments // 2,
                radius=rivet_r,
                location=(side_sign * shoulder_x + rx, ry, pauldron_center_z),
            )
            rivet = bpy.context.active_object
            rivet.name = f"Rivet_Pauldron_{'L' if side_sign < 0 else 'R'}_{i}"
            for v in rivet.data.vertices:
                v.co.z *= 0.6
            assign_material(rivet, mats, mat_accent)
            shade_flat(rivet)
            parts.append(rivet)

    # Torso rivets — placed along the abdominal panel line
    torso_front = 0.10 * build
    rivet_count = 4
    for i in range(rivet_count):
        x_off = -0.12 * build + (i / (rivet_count - 1)) * 0.24 * build
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=rivet_segments,
            ring_count=rivet_segments // 2,
            radius=rivet_r,
            location=(x_off, torso_front * 0.8, torso_z - torso_h * 0.15),
        )
        rivet = bpy.context.active_object
        rivet.name = f"Rivet_Torso_{i}"
        for v in rivet.data.vertices:
            v.co.z *= 0.6
        assign_material(rivet, mats, mat_accent)
        shade_flat(rivet)
        parts.append(rivet)

    return parts


def create_vent_greebles(config, mats, torso_z, torso_h):
    """Add vent slat greebles to the backpack.

    Creates 3-5 thin rectangular slots per backpack side (left/right faces),
    with internal dark geometry for depth illusion.
    """
    build = config["proportions"].get("build", 1.0)
    mat_armour = config["materials"].get("torso", "MAT_GrimdarkMetal")
    mat_dark = config["materials"].get("boots", "MAT_GrimdarkLeather")

    parts = []
    pack_z = torso_z + torso_h * 0.05
    pack_w = 0.10 * build
    pack_d = 0.06 * build
    pack_h = 0.14 * build

    slat_count = 4
    slat_spacing = pack_h * 0.7 / (slat_count + 1)
    slat_w = pack_w * 0.85
    slat_h = 0.01 * build
    slat_d = 0.003 * build

    # Vents on left and right faces of backpack
    for side_sign in (-1, 1):
        for i in range(slat_count):
            z_offset = -pack_h * 0.35 + (i + 1) * slat_spacing

            # Vent frame (lighter metal)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(
                side_sign * (pack_w + slat_d),
                -pack_d * 0.2,
                pack_z + z_offset,
            ))
            vent = bpy.context.active_object
            vent.name = f"Vent_{'L' if side_sign < 0 else 'R'}_{i}"
            for v in vent.data.vertices:
                v.co.x *= slat_d
                v.co.y *= slat_w * 0.5
                v.co.z *= slat_h * 0.5
            assign_material(vent, mats, mat_armour)
            add_hard_surface(vent, bevel_width=0.001, bevel_segments=1)
            shade_flat(vent)
            parts.append(vent)

            # Vent interior (dark recess)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(
                side_sign * (pack_w - slat_d * 0.5),
                -pack_d * 0.2,
                pack_z + z_offset,
            ))
            interior = bpy.context.active_object
            interior.name = f"VentInterior_{'L' if side_sign < 0 else 'R'}_{i}"
            for v in interior.data.vertices:
                v.co.x *= slat_d * 0.5
                v.co.y *= slat_w * 0.4
                v.co.z *= slat_h * 0.3
            assign_material(interior, mats, mat_dark)
            shade_flat(interior)
            parts.append(interior)

    # Vents on back face of backpack
    for i in range(slat_count):
        z_offset = -pack_h * 0.35 + (i + 1) * slat_spacing
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            0,
            -(pack_d + slat_d),
            pack_z + z_offset,
        ))
        vent_b = bpy.context.active_object
        vent_b.name = f"Vent_Back_{i}"
        for v in vent_b.data.vertices:
            v.co.x *= slat_w * 0.5
            v.co.y *= slat_d
            v.co.z *= slat_h * 0.5
        assign_material(vent_b, mats, mat_armour)
        add_hard_surface(vent_b, bevel_width=0.001, bevel_segments=1)
        shade_flat(vent_b)
        parts.append(vent_b)

    return parts


def create_elbow_guards(config, mats, arm_joints):
    """Add small armour plates on forearms at elbow height.

    Creates hard-surface armour plates around the elbow/forearm area,
    similar to kneepad design. Uses shin/armour material.
    """
    build = config["proportions"].get("build", 1.0)
    mat_armour = config["materials"].get("shins", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")

    parts = []

    for side, side_label in [("l", "L"), ("r", "R")]:
        elbow_key = f"elbow_{side}"
        if elbow_key not in arm_joints:
            continue

        elbow_pos = arm_joints[elbow_key]
        guard_w = 0.03 * build
        guard_h = 0.04 * build
        guard_d = 0.005 * build

        # Armour plate at elbow (outer side of arm)
        arm_side = -1 if side == "l" else 1
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            elbow_pos[0] + arm_side * 0.02 * build,
            elbow_pos[1],
            elbow_pos[2] - guard_h * 0.3,
        ))
        guard = bpy.context.active_object
        guard.name = f"ElbowGuard_{side_label}"
        for v in guard.data.vertices:
            v.co.x *= guard_w
            v.co.y *= guard_d
            v.co.z *= guard_h
            # Slight curve on outer face
            if (side == "l" and v.co.x < 0) or (side == "r" and v.co.x > 0):
                v.co.z *= 1.1
        assign_material(guard, mats, mat_armour)
        add_hard_surface(guard, bevel_width=0.003, bevel_segments=2)
        shade_flat(guard)
        simple_uv_unwrap(guard)
        parts.append(guard)

        # Gold trim line on elbow guard
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            elbow_pos[0] + arm_side * 0.024 * build,
            elbow_pos[1],
            elbow_pos[2] - guard_h * 0.3 + guard_h * 0.8,
        ))
        trim = bpy.context.active_object
        trim.name = f"ElbowGuardTrim_{side_label}"
        for v in trim.data.vertices:
            v.co.x *= guard_w * 0.8
            v.co.y *= 0.002 * build
            v.co.z *= 0.002 * build
        assign_material(trim, mats, mat_accent)
        shade_flat(trim)
        parts.append(trim)

    return parts


def create_side_profile_elements(config, mats, torso_z, torso_h, shoulder_z, shoulder_x, arm_joints, leg_joints):
    """Add CHUNKY hard-surface geometry visible from E/W side profiles.

    E/W edge density is the weakest at 2.5% vs N/S at 4.2%. The issue is
    that thin ridges (< 0.008 BU) are only 1-3 pixels at 384×512 after
    LANCZOS downscale — they blur into smooth area instead of creating edges.

    Solution: use CHUNKY elements (0.02-0.08 BU thick) that actually CHANGE
    THE SILHOUETTE from side views. Each element is a blocky hard-surface
    shape with NO bevel — maximises edge sharpness at low resolution.

    Added:
      - Side torso armour blocks (0.02 BU thick, visible silhouette change)
      - Chunky pauldron blades (0.015 BU thick, projects past shoulder)
      - Backpack side pods (cylinders on backpack sides)
      - Knee side spikes (small pyramids on outer knee)
      - Belt side armour plates (0.02 BU thick hip plates)
    """
    build = config["proportions"].get("build", 1.0)
    mat_armour = config["materials"].get("torso", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
    mat_shin = config["materials"].get("shins", "MAT_GrimdarkMetal")

    parts = []

    # ========================================================================
    # 1. SIDE TORSO ARMOUR BLOCKS — thick armour blocks on torso sides
    #    These project outward by 0.02 BU (~8 px at 384×512) to create a
    #    visible side silhouette change.
    # ========================================================================
    for side_sign in (-1, 1):
        x_pos = side_sign * 0.215 * build
        block_h = torso_h * 0.55
        block_w = 0.02 * build      # Thick enough to survive LANCZOS downscale
        block_d = 0.08 * build      # Front-to-back depth for contrast

        bpy.ops.mesh.primitive_cube_add(size=1, location=(x_pos + side_sign * block_w * 0.5, 0, torso_z))
        block = bpy.context.active_object
        block.name = f"SideTorsoBlock_{'L' if side_sign < 0 else 'R'}"
        for v in block.data.vertices:
            v.co.x *= block_w * 0.5
            v.co.y *= block_d * 0.5
            v.co.z *= block_h * 0.5
        assign_material(block, mats, mat_armour)
        shade_flat(block)        # NO bevel — maximises edge sharpness
        parts.append(block)

        # Gold accent strip on outer face — wider for edge detection
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x_pos + side_sign * block_w * 0.3, 0, torso_z))
        accent = bpy.context.active_object
        accent.name = f"SideTorsoAccent_{'L' if side_sign < 0 else 'R'}"
        for v in accent.data.vertices:
            v.co.x *= 0.003 * build
            v.co.y *= block_d * 0.6
            v.co.z *= block_h * 0.7
        assign_material(accent, mats, mat_accent)
        shade_flat(accent)
        parts.append(accent)

    # ========================================================================
    # 2. CHUNKY PAULDRON BLADES — thick blade/spur projecting sideways
    #    Creates a visible shoulder width increase from E/W views.
    # ========================================================================
    for side_sign in (-1, 1):
        outer_x = side_sign * (shoulder_x + 0.04 * build)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(outer_x, 0, shoulder_z))
        blade = bpy.context.active_object
        blade.name = f"PauldronBlade_{'L' if side_sign < 0 else 'R'}"
        for v in blade.data.vertices:
            v.co.x *= 0.015 * build
            v.co.y *= 0.07 * build
            v.co.z *= 0.05 * build
        assign_material(blade, mats, mat_armour)
        shade_flat(blade)
        parts.append(blade)

        # Gold accent on blade tip
        bpy.ops.mesh.primitive_cube_add(size=1, location=(side_sign * (shoulder_x + 0.053 * build), 0, shoulder_z))
        tip = bpy.context.active_object
        tip.name = f"PauldronBladeTip_{'L' if side_sign < 0 else 'R'}"
        for v in tip.data.vertices:
            v.co.x *= 0.004 * build
            v.co.y *= 0.05 * build
            v.co.z *= 0.03 * build
        assign_material(tip, mats, mat_accent)
        shade_flat(tip)
        parts.append(tip)

    # ========================================================================
    # 3. BACKPACK SIDE PODS — cylinders on backpack sides visible from E/W
    #    The backpack itself is behind the body; these pods project sideways.
    # ========================================================================
    pack_z = torso_z + torso_h * 0.05
    for side_sign in (-1, 1):
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=16, radius=0.025 * build, depth=0.03 * build,
            location=(side_sign * 0.11 * build, -0.12 * build, pack_z)
        )
        pod = bpy.context.active_object
        pod.name = f"BackpackPod_{'L' if side_sign < 0 else 'R'}"
        pod.rotation_euler = (0, math.radians(90), 0)
        assign_material(pod, mats, mat_armour)
        shade_flat(pod)
        parts.append(pod)

    # ========================================================================
    # 4. KNEE SIDE SPIKES — small pyramid spikes on outer knee
    #    Creates visible knee width from side views.
    # ========================================================================
    knee_l = leg_joints.get("knee_l", (-0.10, 0, 0.55))
    knee_r = leg_joints.get("knee_r", (0.10, 0, 0.55))

    for side, knee, sign in [("L", knee_l, -1), ("R", knee_r, 1)]:
        spike_x = knee[0] + sign * 0.02 * build
        bpy.ops.mesh.primitive_cone_add(
            vertices=6, radius1=0.012 * build, radius2=0.002 * build,
            depth=0.025 * build,
            location=(spike_x, knee[1], knee[2])
        )
        spike = bpy.context.active_object
        spike.name = f"KneeSpike_{side}"
        spike.rotation_euler = (0, math.radians(90), 0)
        assign_material(spike, mats, mat_accent)
        shade_flat(spike)
        parts.append(spike)

    # ========================================================================
    # 5. BELT SIDE ARMOUR — thick hip plates on belt sides
    # ========================================================================
    torso_bottom = torso_z - torso_h * 0.5
    hip_z = torso_bottom - 0.02 * build

    for side_sign in (-1, 1):
        x_pos = side_sign * 0.19 * build
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x_pos, 0, hip_z))
        hip = bpy.context.active_object
        hip.name = f"HipArmour_{'L' if side_sign < 0 else 'R'}"
        for v in hip.data.vertices:
            v.co.x *= 0.015 * build
            v.co.y *= 0.06 * build
            v.co.z *= 0.09 * build
        assign_material(hip, mats, mat_armour)
        shade_flat(hip)
        parts.append(hip)

        # Gold trim
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x_pos, 0, hip_z - 0.045 * build))
        trim = bpy.context.active_object
        trim.name = f"HipArmourTrim_{'L' if side_sign < 0 else 'R'}"
        for v in trim.data.vertices:
            v.co.x *= 0.015 * build
            v.co.y *= 0.06 * build
            v.co.z *= 0.003 * build
        assign_material(trim, mats, mat_accent)
        shade_flat(trim)
        parts.append(trim)

    # ========================================================================
    # 6. BACKPACK TOP EXTENSION — extends upward to break side silhouette
    # ========================================================================
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.17 * build, pack_z + 0.08 * build))
    top_ext = bpy.context.active_object
    top_ext.name = "BackpackTopExtension"
    for v in top_ext.data.vertices:
        v.co.x *= 0.03 * build
        v.co.y *= 0.02 * build
        v.co.z *= 0.02 * build
    assign_material(top_ext, mats, mat_armour)
    shade_flat(top_ext)
    parts.append(top_ext)

    return parts


# =============================================================================
# AUTO-RIGGING
# =============================================================================

def create_armature(joints):
    """Create a basic humanoid armature from joint positions."""
    arm_data = bpy.data.armatures.new("UnitArmature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Helper to create a bone
    def make_bone(name, head, tail, parent=None):
        bone = arm_data.edit_bones.new(name)
        bone.head = mathutils.Vector(head)
        bone.tail = mathutils.Vector(tail)
        if parent:
            bone.parent = parent
        return bone
    
    # Hips (root)
    hip_l_pos = joints["hip_l"]
    hip_r_pos = joints["hip_r"]
    hip_center = ((hip_l_pos[0]+hip_r_pos[0])/2, 0, hip_l_pos[2])
    spine_head = hip_center
    
    # Spine -> chest -> neck -> head
    chest_z = (hip_center[2] + joints.get("shoulder_l", (0,0,0))[2]) / 2
    neck_z = joints.get("shoulder_l", (0,0,0))[2] + 0.02
    head_top_z = neck_z + 0.1
    
    spine = make_bone("Hips", hip_center, (hip_center[0], 0, chest_z))
    chest = make_bone("Chest", (hip_center[0], 0, chest_z), (hip_center[0], 0, neck_z), spine)
    neck = make_bone("Neck", (hip_center[0], 0, neck_z), (hip_center[0], 0, head_top_z), chest)
    head = make_bone("Head", (hip_center[0], 0, head_top_z), (hip_center[0], 0, head_top_z + 0.08), neck)
    
    # Left leg
    thigh_l = make_bone("Thigh_L", hip_l_pos, joints["knee_l"], spine)
    shin_l = make_bone("Shin_L", joints["knee_l"], joints["ankle_l"], thigh_l)
    foot_l = make_bone("Foot_L", joints["ankle_l"], joints["foot_l"], shin_l)
    
    # Right leg
    thigh_r = make_bone("Thigh_R", hip_r_pos, joints["knee_r"], spine)
    shin_r = make_bone("Shin_R", joints["knee_r"], joints["ankle_r"], thigh_r)
    foot_r = make_bone("Foot_R", joints["ankle_r"], joints["foot_r"], shin_r)
    
    # Arms
    for side, suffix in [("L", "_L"), ("R", "_R")]:
        shoulder = joints[f"shoulder_{side.lower()}"]
        elbow = joints[f"elbow_{side.lower()}"]
        wrist = joints[f"wrist_{side.lower()}"]
        
        upper_arm = make_bone(f"UpperArm{suffix}", shoulder, elbow, chest)
        forearm = make_bone(f"Forearm{suffix}", elbow, wrist, upper_arm)
        hand = make_bone(f"Hand{suffix}", wrist, (wrist[0], wrist[1]+0.03, wrist[2]-0.02), forearm)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    
    return arm_obj


def parent_to_armature(mesh_objects, armature):
    """Parent all mesh objects to the armature with automatic weights."""
    bpy.ops.object.select_all(action='DESELECT')
    
    for obj in mesh_objects:
        obj.select_set(True)
    
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    
    # Parent with automatic weights
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    
    print(f"  Parented {len(mesh_objects)} meshes to armature with auto weights")


# =============================================================================
# PROCEDURAL ANIMATION
# =============================================================================

def create_animations(armature, config):
    """Create procedural animations as NLA actions on the armature.
    
    Blender 5.1 uses layered actions: Action → Layer → Strip → ChannelBag → FCurves.
    Supports humanoid, vehicle, creature, and insectoid body types.
    """
    params = config.get("animation_params", {})
    idle_intensity = params.get("idle_intensity", 1.0)
    walk_stride = params.get("walk_stride", 0.4)
    attack_speed = params.get("attack_speed", 1.5)
    
    # Use body-type-specific animation frames
    body_type = config.get("body_type", "humanoid")
    animations = _get_animation_frames(config)
    
    bpy.context.view_layer.objects.active = armature
    
    for anim_name, (start, end) in animations.items():
        action = bpy.data.actions.new(name=anim_name)
        action.use_fake_user = True
        
        # Set up layered action structure: layer → strip → channelbag(slot)
        layer = action.layers.new(name="Layer")
        strip = layer.strips.new(type='KEYFRAME')
        slot = action.slots.new(id_type='OBJECT', name=armature.name)
        channelbag = strip.channelbags.new(slot)
        
        # Create keyframes for each bone
        for frame in range(start, end + 1):
            t = (frame - start) / max(1, end - start)  # 0 to 1
            
            if anim_name == "idle":
                animate_idle(armature, channelbag, frame, t, idle_intensity)
            elif anim_name == "walk":
                animate_walk(armature, channelbag, frame, t, walk_stride)
            elif anim_name == "attack":
                animate_attack(armature, channelbag, frame, t, attack_speed)
            elif anim_name == "hurt":
                animate_hurt(armature, channelbag, frame, t)
            elif anim_name == "die":
                animate_die(armature, channelbag, frame, t)
        
        # Add as NLA strip
        if armature.animation_data is None:
            armature.animation_data_create()
        
        track = armature.animation_data.nla_tracks.new()
        track.name = anim_name
        strip = track.strips.new(name=anim_name, start=start, action=action)
        strip.action_frame_start = start
        strip.action_frame_end = end + 1
        
        print(f"  Created action: {anim_name} [{start}-{end}]")


def set_keyframe(channelbag, bone_name, frame, loc=None, rot=None, scale=None):
    """Insert keyframes for a bone into a channelbag via fcurves.
    Reuses existing fcurves if already created (same bone+property+index)."""
    def get_or_create_fcurve(data_path, index):
        # Find existing fcurve
        for fc in channelbag.fcurves:
            if fc.data_path == data_path and fc.array_index == index:
                return fc
        # Create new
        fc = channelbag.fcurves.new(data_path=data_path, index=index)
        return fc
    
    if loc is not None:
        dp = f'pose.bones["{bone_name}"].location'
        for i, val in enumerate(loc):
            fc = get_or_create_fcurve(dp, i)
            fc.keyframe_points.insert(frame, val)
    if rot is not None:
        dp = f'pose.bones["{bone_name}"].rotation_euler'
        for i, val in enumerate(rot):
            fc = get_or_create_fcurve(dp, i)
            fc.keyframe_points.insert(frame, val)

def animate_idle(armature, channelbag, frame, t, intensity):
    """Idle breathing + weapon sway — exaggerated for visibility at 96×128.
    
    At default intensity 1.0: chest rises ~8px, arms sway ~15px at tip.
    """
    # Chest rises and falls — increased from 0.01 to 0.10 BU
    breath = math.sin(t * 2 * math.pi) * 0.10 * intensity
    set_keyframe(channelbag, "Chest", frame, loc=(0, 0, breath))
    # Head bob — increased from 0.005 to 0.04 BU
    head_bob = math.sin(t * 2 * math.pi) * 0.04 * intensity
    set_keyframe(channelbag, "Head", frame, loc=(0, 0, head_bob))
    # Arms sway — increased from 0.02 to 0.25 rad
    arm_sway = math.sin(t * 2 * math.pi) * 0.25 * intensity
    set_keyframe(channelbag, "UpperArm_L", frame, rot=(0, 0, -arm_sway))
    set_keyframe(channelbag, "UpperArm_R", frame, rot=(0, 0, arm_sway))
    # Weapon drift — slight rotation on right forearm to move gun
    weapon_drift = math.sin(t * 2 * math.pi + 0.5) * 0.15 * intensity
    set_keyframe(channelbag, "Forearm_R", frame, rot=(0, weapon_drift, 0))


def animate_walk(armature, channelbag, frame, t, stride):
    """Walk cycle — exaggerated for readability at 96×128.
    
    At stride 0.4: legs swing ~12px at foot, arms counter-swing ~20px.
    Torso bobs ~4px. Side-to-side weight shift ~2px.
    """
    phase = t * 2 * math.pi
    # Legs alternate — increased stride contribution: sin(phase) * stride * 1.5
    leg_swing = math.sin(phase) * stride * 1.5
    set_keyframe(channelbag, "Thigh_L", frame, rot=(leg_swing, 0, 0))
    set_keyframe(channelbag, "Thigh_R", frame, rot=(-leg_swing, 0, 0))
    # Knee bend — increased from 0.5 to 1.0 multiplier
    set_keyframe(channelbag, "Shin_L", frame, rot=(max(0, -leg_swing) * 1.0, 0, 0))
    set_keyframe(channelbag, "Shin_R", frame, rot=(max(0, leg_swing) * 1.0, 0, 0))
    # Arms counter-swing — increased from 0.3 to 0.8
    arm_swing = math.sin(phase) * 0.8
    set_keyframe(channelbag, "UpperArm_L", frame, rot=(-arm_swing, 0, 0))
    set_keyframe(channelbag, "UpperArm_R", frame, rot=(arm_swing, 0, 0))
    # Forearms swing naturally
    fore_swing = math.sin(phase) * 0.4
    set_keyframe(channelbag, "Forearm_L", frame, rot=(fore_swing, 0, 0))
    set_keyframe(channelbag, "Forearm_R", frame, rot=(-fore_swing, 0, 0))
    # Torso bobs — increased from 0.01 to 0.05 BU
    bob = abs(math.sin(phase * 2)) * 0.05
    set_keyframe(channelbag, "Hips", frame, loc=(0, 0, bob))
    # Side-to-side sway for natural weight shift
    sway = math.sin(phase) * 0.02
    set_keyframe(channelbag, "Chest", frame, rot=(0, 0, sway))


def animate_attack(armature, channelbag, frame, t, speed):
    """Attack — wind up, strike, recover. Exaggerated for readability at 96×128.
    
    3-phase attack with weapon swing. Speed multiplier accelerates timing.
    """
    if t < 0.3:
        # Wind up — pull back hard
        pullback = t / 0.3
        set_keyframe(channelbag, "UpperArm_R", frame, rot=(-0.8 * pullback, 0, -1.2 * pullback))
        set_keyframe(channelbag, "Forearm_R", frame, rot=(1.2 * pullback, 0, 0))
        # Upper body rotates back
        set_keyframe(channelbag, "Chest", frame, rot=(-0.3 * pullback, 0, 0.2 * pullback))
    elif t < 0.6:
        # Strike — thrust forward with power
        strike = (t - 0.3) / 0.3
        set_keyframe(channelbag, "UpperArm_R", frame, rot=(1.2 + 1.5 * strike, 0, -1.2 + 1.8 * strike))
        set_keyframe(channelbag, "Forearm_R", frame, rot=(1.2 - 1.8 * strike, 0, 0))
        # Body follows through
        set_keyframe(channelbag, "Chest", frame, rot=(-0.3 * (1 - strike), 0, 0.2 * (1 - strike)))
    else:
        # Recover — slow return to neutral
        recover = (t - 0.6) / 0.4
        set_keyframe(channelbag, "UpperArm_R", frame, rot=(2.7 - 2.7 * recover, 0, 0.6 - 0.6 * recover))
        set_keyframe(channelbag, "Forearm_R", frame, rot=(-0.6 + 0.6 * recover, 0, 0))
        set_keyframe(channelbag, "Chest", frame, rot=(0, 0, 0))


def animate_hurt(armature, channelbag, frame, t):
    """Hurt — snap recoil backwards. Must be visible as a flinch at 96×128."""
    # Sharp initial recoil, then settle
    recoil = math.sin(t * math.pi) * 0.8
    set_keyframe(channelbag, "Chest", frame, rot=(-recoil, 0, 0))
    set_keyframe(channelbag, "Head", frame, rot=(-recoil * 0.6, 0, 0))
    # Arms fling out
    set_keyframe(channelbag, "UpperArm_L", frame, rot=(0, 0, -recoil * 0.6))
    set_keyframe(channelbag, "UpperArm_R", frame, rot=(0, 0, recoil * 0.6))
    # Step back
    step_back = math.sin(t * math.pi) * 0.04
    set_keyframe(channelbag, "Hips", frame, loc=(0, step_back, 0))


def animate_die(armature, channelbag, frame, t):
    """Die — dramatic collapse forward, then go limp.
    
    Two-phase: fast collapse (t<0.4), then slow settling (t>=0.4).
    """
    if t < 0.4:
        fall = t / 0.4
        # Chest collapses forward — increased from 1.2 to 1.8
        set_keyframe(channelbag, "Chest", frame, rot=(fall * 1.8, 0, fall * 0.2))
        # Hips drop
        set_keyframe(channelbag, "Hips", frame, loc=(0, fall * 0.1, -fall * 0.5))
        # Legs give out
        set_keyframe(channelbag, "Thigh_L", frame, rot=(fall * 1.0, 0, fall * 0.3))
        set_keyframe(channelbag, "Thigh_R", frame, rot=(fall * 1.0, 0, -fall * 0.3))
        # Arms flail
        set_keyframe(channelbag, "UpperArm_L", frame, rot=(0, 0, -fall * 0.8))
        set_keyframe(channelbag, "UpperArm_R", frame, rot=(0, 0, fall * 0.8))
    else:
        # Limp settle
        settle = (t - 0.4) / 0.6
        set_keyframe(channelbag, "Chest", frame, rot=(1.8 * (1 - settle * 0.3), 0, 0.2 * (1 - settle)))
        set_keyframe(channelbag, "Hips", frame, loc=(0, 0.1 * (1 - settle), -0.5))
        set_keyframe(channelbag, "Thigh_L", frame, rot=(1.0 * (1 - settle * 0.2), 0, 0.3 * (1 - settle)))
        set_keyframe(channelbag, "Thigh_R", frame, rot=(1.0 * (1 - settle * 0.2), 0, -0.3 * (1 - settle)))
        set_keyframe(channelbag, "UpperArm_L", frame, rot=(0, 0, -0.8 * (1 - settle)))
        set_keyframe(channelbag, "UpperArm_R", frame, rot=(0, 0, 0.8 * (1 - settle)))


# =============================================================================
# MAIN
# =============================================================================

def load_promoted_config(config, config_path):
    """Load promoted config if specified."""
    if 'promoted_from' in config and config['promoted_from']:
        base_name = config['promoted_from']
        # Find base config
        base_path = None
        for root, dirs, files in os.walk(os.path.dirname(config_path)):
            for f in files:
                if f.startswith(base_name) and f.endswith('.json'):
                    base_path = os.path.join(root, f)
                    break
            if base_path:
                break
        if base_path:
            with open(base_path) as f:
                base_config = json.load(f)
            # Merge base config with current
            for key in ['materials', 'equipment', 'proportions', 'weapon', 'animation_params']:
                if key in base_config and key in config:
                    config[key].update(base_config[key])
    
    return config


# =============================================================================
# BODY TYPE DISPATCH HELPERS
# =============================================================================

def _build_humanoid(config, mats):
    """Build a humanoid unit: head, torso, shoulders, arms, legs, weapon, backpack."""
    props = config["proportions"]
    total_h = props["height"]
    head_h = total_h * props["head_ratio"]
    z_top = total_h
    
    all_parts = []
    
    head_parts, head_z, head_h, head_r = create_head(config, mats, z_top)
    all_parts.extend(head_parts)
    
    torso_parts, torso_z, torso_h = create_torso(config, mats, z_top, head_h)
    all_parts.extend(torso_parts)
    
    shoulder_parts, shoulder_z, shoulder_x = create_shoulders(config, mats, torso_z, torso_h)
    all_parts.extend(shoulder_parts)
    
    arm_parts, arm_joints = create_arms(config, mats, shoulder_z, shoulder_x)
    all_parts.extend(arm_parts)
    
    leg_parts, leg_joints = create_legs(config, mats, torso_z, torso_h)
    all_parts.extend(leg_parts)

    tabard_parts = create_tabard(config, mats, torso_z, torso_h, 0.10)
    all_parts.extend(tabard_parts)

    belt_parts = create_belt(config, mats, torso_z, torso_h, 0.10)
    all_parts.extend(belt_parts)

    weapon_parts = create_weapon(config, mats, arm_joints)
    all_parts.extend(weapon_parts)
    
    backpack_parts = create_backpack(config, mats, torso_z, torso_h)
    all_parts.extend(backpack_parts)

    # --- Detail elements (hard-surface armour greebles) ---
    torso_panel_parts = create_torso_panel_lines(config, mats, torso_z, torso_h)
    all_parts.extend(torso_panel_parts)

    helmet_panel_parts = create_helmet_panel_lines(config, mats, head_z, head_h, head_r)
    all_parts.extend(helmet_panel_parts)

    outer_plate_parts = create_outer_chest_plate(config, mats, torso_z, torso_h)
    all_parts.extend(outer_plate_parts)

    rivet_parts = create_rivets(config, mats, shoulder_z, shoulder_x, torso_z, torso_h)
    all_parts.extend(rivet_parts)

    vent_parts = create_vent_greebles(config, mats, torso_z, torso_h)
    all_parts.extend(vent_parts)

    elbow_guard_parts = create_elbow_guards(config, mats, arm_joints)
    all_parts.extend(elbow_guard_parts)

    # --- Side-profile improvements (boosts E/W edge density) ---
    side_profile_parts = create_side_profile_elements(
        config, mats, torso_z, torso_h, shoulder_z, shoulder_x, arm_joints, leg_joints
    )
    all_parts.extend(side_profile_parts)
    
    joints = {**arm_joints, **leg_joints}
    return all_parts, joints


def _build_vehicle(config, mats):
    """Build a vehicle unit using the non-humanoid template."""
    all_parts, joints = generate_vehicle(config, mats)
    return all_parts, joints


def _build_creature(config, mats):
    """Build a creature unit using the non-humanoid template."""
    all_parts, joints = generate_creature(config, mats)
    return all_parts, joints


def _build_quadruped(config, mats):
    """Build a quadruped creature with hard-surface carapace plates.
    
    Follows the same pattern as _build_creature but explicitly uses
    hard-surface modelling on all carapace/armour parts and subsurf
    only on flesh/membrane areas (wings, soft tissue).
    Delegates to generate_creature which has hard-surface carapace profiles.
    """
    all_parts, joints = generate_creature(config, mats)
    return all_parts, joints


def _build_insectoid(config, mats):
    """Build an insectoid unit using the non-humanoid template.
    
    Uses hard-surface modelling on body segments, head, mandibles, and legs.
    Subsurf/smooth only on eyes and wings (soft/fleshy parts).
    """
    all_parts, joints = generate_insectoid(config, mats)
    return all_parts, joints


def _create_body_armature(joints, config):
    """Route armature creation based on body_type."""
    body_type = config.get("body_type", "humanoid")
    
    if body_type == "humanoid":
        return create_armature(joints)
    elif body_type in ("quadruped", "creature") and NONHUMANOID_AVAILABLE:
        return create_creature_armature(joints, config)
    elif body_type == "vehicle" and NONHUMANOID_AVAILABLE:
        return create_vehicle_armature(joints, config)
    elif body_type == "insectoid" and NONHUMANOID_AVAILABLE:
        return create_insectoid_armature(joints, config)
    else:
        return create_armature(joints)


def _get_animation_frames(config):
    """Return correct animation frames based on body_type."""
    body_type = config.get("body_type", "humanoid")
    
    if body_type == "humanoid":
        return {
            "idle": (1, 4),
            "walk": (10, 16),
            "attack": (20, 24),
            "hurt": (30, 32),
            "die": (40, 46),
        }
    elif NONHUMANOID_AVAILABLE:
        return get_nonhumanoid_animations(body_type)
    else:
        return {
            "idle": (1, 4),
            "walk": (10, 16),
            "attack": (20, 24),
            "hurt": (30, 32),
            "die": (40, 46),
        }


def generate_unit(config_path):
    """Generate a single unit from a JSON config file.
    
    Supports promoted_from inheritance:
    - Base units have promoted_from = null
    - Promoted units inherit from base, adding unique headgear/armor
    - Highest level units have all unique items
    """
    with open(config_path) as f:
        config = json.load(f)
    
    # Load promoted config if specified
    config = load_promoted_config(config, config_path)
    
    print(f"\n{'='*60}")
    print(f"Generating: {config['unit_name']}")
    if 'promoted_from' in config and config['promoted_from']:
        print(f"  Promoted from: {config['promoted_from']}")
    print(f"{'='*60}")
    
    clear_scene()
    mats = load_materials()
    
    # Determine body type and route to appropriate generator
    body_type = config.get("body_type", "humanoid")
    
    if body_type == "humanoid":
        all_parts, joints = _build_humanoid(config, mats)
    elif body_type == "vehicle" and NONHUMANOID_AVAILABLE:
        all_parts, joints = _build_vehicle(config, mats)
    elif body_type in ("quadruped", "creature") and NONHUMANOID_AVAILABLE:
        all_parts, joints = _build_quadruped(config, mats)
    elif body_type == "insectoid" and NONHUMANOID_AVAILABLE:
        all_parts, joints = _build_insectoid(config, mats)
    else:
        print(f"  Unknown body_type '{body_type}', falling back to humanoid")
        all_parts, joints = _build_humanoid(config, mats)
    
    # Remap every part's UVs into its atlas tile (matches paint_unit_diffuse.py layout),
    # so the per-unit painted diffuse + team mask map correctly onto the model.
    remap_uvs_to_atlas(all_parts)

    # Join all meshes into one
    bpy.ops.object.select_all(action='DESELECT')
    for p in all_parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = all_parts[0]
    bpy.ops.object.join()
    body_mesh = bpy.context.active_object
    body_mesh.name = config["unit_name"]
    
    # Set origin to ground level
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
    body_mesh.location.z = 0
    
    print(f"  Mesh: {len(body_mesh.data.vertices)} vertices, {len(body_mesh.data.materials)} materials")
    
    # Create armature and rig (routed by body_type)
    if body_type == "humanoid":
        # Humanoid armature is created from joint positions
        armature = create_armature(joints)
    else:
        armature = _create_body_armature(joints, config)
    parent_to_armature([body_mesh], armature)
    
    # Create procedural animations
    create_animations(armature, config)
    
    # Save
    output_path = config.get("output_blend")
    if output_path:
        if not os.path.isabs(output_path):
            output_path = os.path.join(PROJECT_ROOT, output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=output_path)
        print(f"  Saved: {output_path}")
    
    return body_mesh


def main():
    config_path, batch_dir = parse_args()
    
    if batch_dir:
        # Batch mode — process all JSON configs in directory
        configs = sorted([f for f in os.listdir(batch_dir) if f.endswith(".json")])
        print(f"Batch mode: {len(configs)} configs in {batch_dir}")
        for cfg in configs:
            generate_unit(os.path.join(batch_dir, cfg))
    elif config_path:
        generate_unit(config_path)
    else:
        print("Usage: --config <path.json> or --batch <configs_dir>")
        sys.exit(1)


if __name__ == "__main__":
    main()