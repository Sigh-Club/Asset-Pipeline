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

def add_subsurf(obj, levels=2, render_levels=3):
    mod = obj.modifiers.new(name="Subsurf", type='SUBSURF')
    mod.levels = levels
    mod.render_levels = render_levels
    mod.subdivision_type = 'CATMULL_CLARK'

def add_bevel(obj, width=0.005, segments=2):
    mod = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(30)
    mod.width = width
    mod.segments = segments

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
    
    # Main helmet
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=head_r, location=(0, 0, head_z))
    helm = bpy.context.active_object
    helm.name = "Helmet"
    for v in helm.data.vertices:
        v.co.x *= 0.95
        v.co.y *= 1.1
        v.co.z *= 0.85
    assign_material(helm, mats, mat_helm)
    add_bevel(helm, width=0.003, segments=2)
    add_subsurf(helm, levels=2, render_levels=3)
    shade_smooth(helm)
    simple_uv_unwrap(helm)
    parts.append(helm)
    
    if eq.get("visor", True):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, head_r * 0.85, head_z - head_h * 0.05))
        visor = bpy.context.active_object
        visor.name = "Visor"
        for v in visor.data.vertices:
            v.co.x *= head_r * 0.45
            v.co.y *= head_r * 0.15
            v.co.z *= head_r * 0.2
        assign_material(visor, mats, mat_helm)
        parts.append(visor)
    
    if eq.get("crest", True):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -head_r * 0.35, head_z + head_h * 0.35))
        crest = bpy.context.active_object
        crest.name = "Crest"
        for v in crest.data.vertices:
            v.co.x *= head_r * 0.15
            v.co.y *= head_r * 0.85
            v.co.z *= head_r * 0.2
        assign_material(crest, mats, mat_accent)
        parts.append(crest)
    
    return parts, head_z, head_h


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
        add_subsurf(plate, levels=1, render_levels=2)
        shade_smooth(plate)
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
    add_bevel(torso, width=0.005, segments=2)
    add_subsurf(torso, levels=2, render_levels=3)
    shade_smooth(torso)
    simple_uv_unwrap(torso)
    parts.append(torso)
    
    if eq.get("aquila", True):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.135 * build, torso_z + torso_h * 0.1))
        aquila = bpy.context.active_object
        aquila.name = "Aquila"
        for v in aquila.data.vertices:
            v.co.x *= 0.05
            v.co.y *= 0.01
            v.co.z *= 0.06
        assign_material(aquila, mats, mat_accent)
        parts.append(aquila)
    
    return parts, torso_z, torso_h


def create_shoulders(config, mats, torso_z, torso_h):
    props = config["proportions"]
    build = props.get("build", 1.0)
    pauldron_r = 0.07 * build
    shoulder_z = torso_z + torso_h * 0.35
    shoulder_x = 0.30 * build  # widened for better side-view coverage (was 0.26)
    
    parts = []
    mat_shoulder = config["materials"].get("shoulders", "MAT_GrimdarkMetal")
    eq = config.get("equipment", {})
    
    if not eq.get("pauldrons", True):
        return parts, shoulder_z, shoulder_x
    
    for side, x in [("L", -shoulder_x), ("R", shoulder_x)]:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=pauldron_r, location=(x, 0, shoulder_z))
        pauldron = bpy.context.active_object
        pauldron.name = f"Pauldron_{side}"
        for v in pauldron.data.vertices:
            v.co.z *= 0.6
        assign_material(pauldron, mats, mat_shoulder)
        add_bevel(pauldron, width=0.003, segments=2)
        add_subsurf(pauldron, levels=1, render_levels=2)
        shade_smooth(pauldron)
        simple_uv_unwrap(pauldron)
        parts.append(pauldron)
    
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
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.04 * build, depth=upper_h, location=(x, 0, upper_z))
        upper = bpy.context.active_object
        upper.name = f"UpperArm_{side}"
        assign_material(upper, mats, mat_upper)
        add_subsurf(upper, levels=1, render_levels=2)
        shade_smooth(upper)
        simple_uv_unwrap(upper)
        parts.append(upper)
        
        lower_z = upper_z - upper_h * 0.5 - lower_h * 0.5
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.035 * build, depth=lower_h, location=(x, 0, lower_z))
        lower = bpy.context.active_object
        lower.name = f"Forearm_{side}"
        assign_material(lower, mats, mat_lower)
        add_subsurf(lower, levels=1, render_levels=2)
        shade_smooth(lower)
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
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.05 * build, depth=thigh_h, location=(x, 0, thigh_z))
        thigh = bpy.context.active_object
        thigh.name = f"Thigh_{side}"
        assign_material(thigh, mats, mat_thigh)
        add_subsurf(thigh, levels=1, render_levels=2)
        shade_smooth(thigh)
        simple_uv_unwrap(thigh)
        parts.append(thigh)
        
        shin_z = thigh_z - thigh_h * 0.5 - shin_h * 0.5
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.045 * build, depth=shin_h, location=(x, 0, shin_z))
        shin = bpy.context.active_object
        shin.name = f"Shin_{side}"
        assign_material(shin, mats, mat_shin)
        add_bevel(shin, width=0.003, segments=1)
        add_subsurf(shin, levels=1, render_levels=2)
        shade_smooth(shin)
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
        add_bevel(boot, width=0.004, segments=2)
        add_subsurf(boot, levels=1, render_levels=2)
        shade_smooth(boot)
        simple_uv_unwrap(boot)
        parts.append(boot)
    
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
        
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.012, depth=0.12, location=(wrist_r[0], wrist_r[1] + 0.22, wrist_r[2]))
        barrel = bpy.context.active_object
        barrel.name = "WeaponBarrel"
        barrel.rotation_euler = (math.radians(90), 0, 0)
        assign_material(barrel, mats, mat_body)
        parts.append(barrel)
        
        bpy.ops.mesh.primitive_cube_add(size=1, location=(wrist_r[0], wrist_r[1] - 0.02, wrist_r[2] - 0.02))
        stock = bpy.context.active_object
        stock.name = "WeaponStock"
        for v in stock.data.vertices:
            v.co.x *= 0.03
            v.co.y *= 0.04
            v.co.z *= 0.06
        assign_material(stock, mats, mat_stock)
        parts.append(stock)
    
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
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.015, depth=0.18, location=(wrist_r[0], wrist_r[1] + 0.09, wrist_r[2]))
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
        
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.03, depth=0.08, location=(wrist_r[0], wrist_r[1] - 0.05, wrist_r[2] - 0.04))
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
    add_bevel(pack, width=0.004, segments=2)
    add_subsurf(pack, levels=2, render_levels=3)
    shade_smooth(pack)
    simple_uv_unwrap(pack)
    return [pack]


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
    
    head_parts, head_z, head_h = create_head(config, mats, z_top)
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
    
    weapon_parts = create_weapon(config, mats, arm_joints)
    all_parts.extend(weapon_parts)
    
    backpack_parts = create_backpack(config, mats, torso_z, torso_h)
    all_parts.extend(backpack_parts)
    
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


def _build_insectoid(config, mats):
    """Build an insectoid unit using the non-humanoid template."""
    all_parts, joints = generate_insectoid(config, mats)
    return all_parts, joints


def _create_body_armature(joints, config):
    """Route armature creation based on body_type."""
    body_type = config.get("body_type", "humanoid")
    
    if body_type == "humanoid":
        return create_armature(joints)
    elif body_type == "vehicle" and NONHUMANOID_AVAILABLE:
        return create_vehicle_armature(joints, config)
    elif body_type == "creature" and NONHUMANOID_AVAILABLE:
        return create_creature_armature(joints, config)
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
    elif body_type == "creature" and NONHUMANOID_AVAILABLE:
        all_parts, joints = _build_creature(config, mats)
    elif body_type == "insectoid" and NONHUMANOID_AVAILABLE:
        all_parts, joints = _build_insectoid(config, mats)
    else:
        print(f"  Unknown body_type '{body_type}', falling back to humanoid")
        all_parts, joints = _build_humanoid(config, mats)
    
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