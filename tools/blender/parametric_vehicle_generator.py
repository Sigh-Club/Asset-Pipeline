#!/usr/bin/env python3
"""
parametric_vehicle_generator.py — Non-humanoid body type templates.
Adds vehicle, creature, and insectoid generation support to the parametric pipeline.

Imported by parametric_unit_generator.py when config specifies body_type.

Usage: body_type is set in the JSON config:
    "body_type": "vehicle" | "creature" | "insectoid" | "humanoid" (default)

Each template defines its own body parts, armature, animations, and render requirements.
"""

import bpy
import math
import mathutils
from typing import Dict, List, Tuple, Optional, Any

# =============================================================================
# SHARED HELPERS (duplicated from main generator for standalone use)
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

def assign_material(obj, mats, mat_name):
    if mat_name in mats:
        obj.data.materials.clear()
        obj.data.materials.append(mats[mat_name])

def add_hard_surface(obj, bevel_width=0.008, bevel_segments=2):
    """Hard-surface armour finish: edge split + limited bevel.
    
    For chitinous carapace/armour plates on creatures and insectoids.
    """
    edge_split = obj.modifiers.new(name="EdgeSplit", type='EDGE_SPLIT')
    edge_split.split_angle = math.radians(30)
    bevel = obj.modifiers.new(name="Bevel", type='BEVEL')
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(30)
    bevel.width = bevel_width
    bevel.segments = bevel_segments
    bevel.loop_slide = True

def shade_flat(obj):
    """Flat shading for hard-surface/carapace look."""
    for poly in obj.data.polygons:
        poly.use_smooth = False

# =============================================================================
# VEHICLE TEMPLATE
# =============================================================================

def generate_vehicle(config: dict, mats: dict) -> tuple:
    """
    Generate a vehicle: tracked/wheeled chassis with turret and weapon mount.
    
    Config additions:
        "vehicle": {
            "type": "tank" | "transport" | "gun_emplacement",
            "track_width": 0.16,
            "hull_length": 0.4,
            "turret": true
        }
    """
    props = config["proportions"]
    vehicle_cfg = config.get("vehicle", {})
    vtype = vehicle_cfg.get("type", "tank")
    build = props.get("build", 1.0)
    total_h = props.get("height", 0.6)
    
    mat_hull = config["materials"].get("hull", "MAT_GrimdarkMetal")
    mat_track = config["materials"].get("track", "MAT_GrimdarkMetal")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
    
    parts = []
    joints = {}
    
    if vtype == "tank":
        # === Main hull ===
        hull_w = 0.30 * build
        hull_l = 0.45 * build
        hull_h = total_h * 0.6
        
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, hull_h / 2))
        hull = bpy.context.active_object
        hull.name = "Hull"
        for v in hull.data.vertices:
            v.co.x *= hull_w / 2
            v.co.y *= hull_l / 2
            v.co.z *= hull_h / 2
            # Slight taper forward
            if v.co.y > 0:
                v.co.x *= 0.85
        assign_material(hull, mats, mat_hull)
        add_bevel(hull, width=0.008, segments=3)
        add_subsurf(hull, levels=1, render_levels=2)
        shade_smooth(hull)
        simple_uv_unwrap(hull)
        parts.append(hull)
        
        # === Tracks (left + right) ===
        for side, sign in [("L", -1), ("R", 1)]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(sign * hull_w * 0.55, 0, hull_h * 0.25))
            track = bpy.context.active_object
            track.name = f"Track_{side}"
            for v in track.data.vertices:
                v.co.x *= 0.06 * build
                v.co.y *= hull_l * 0.8
                v.co.z *= hull_h * 0.35
            assign_material(track, mats, mat_track)
            add_bevel(track, width=0.005, segments=2)
            add_subsurf(track, levels=1, render_levels=2)
            shade_smooth(track)
            simple_uv_unwrap(track)
            parts.append(track)
        
        # === Turret ===
        if vehicle_cfg.get("turret", True):
            turret_h = total_h * 0.3
            turret_r = hull_w * 0.35
            
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=turret_r, location=(0, 0, hull_h + turret_h * 0.5))
            turret = bpy.context.active_object
            turret.name = "Turret"
            for v in turret.data.vertices:
                v.co.z *= 0.6  # Flatten
            assign_material(turret, mats, mat_hull)
            add_bevel(turret, width=0.004, segments=2)
            add_subsurf(turret, levels=2, render_levels=3)
            shade_smooth(turret)
            simple_uv_unwrap(turret)
            parts.append(turret)
            
            # === Barrel ===
            bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.02, depth=0.25, location=(0, hull_l * 0.25 + 0.12, hull_h + turret_h * 0.5))
            barrel = bpy.context.active_object
            barrel.name = "Barrel"
            barrel.rotation_euler = (math.radians(90), 0, 0)
            assign_material(barrel, mats, mat_track)
            add_subsurf(barrel, levels=1, render_levels=2)
            shade_smooth(barrel)
            simple_uv_unwrap(barrel)
            parts.append(barrel)
            
            # === Muzzle brake ===
            bpy.ops.mesh.primitive_cube_add(size=1, location=(0, hull_l * 0.25 + 0.24, hull_h + turret_h * 0.5))
            muzzle = bpy.context.active_object
            muzzle.name = "MuzzleBrake"
            for v in muzzle.data.vertices:
                v.co.x *= 0.025
                v.co.y *= 0.015
                v.co.z *= 0.035
            assign_material(muzzle, mats, mat_accent)
            parts.append(muzzle)
        
        # === Armour plates (side skirts) ===
        for side, sign in [("L", -1), ("R", 1)]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(sign * (hull_w * 0.5 + 0.04), 0, hull_h * 0.3))
            skirt = bpy.context.active_object
            skirt.name = f"ArmourSkirt_{side}"
            for v in skirt.data.vertices:
                v.co.x *= 0.01
                v.co.y *= hull_l * 0.7
                v.co.z *= hull_h * 0.5
            assign_material(skirt, mats, mat_hull)
            parts.append(skirt)
        
        # Joints for camera centering (dummy — vehicles don't rig)
        joints = {
            "hip_l": (-hull_w * 0.3, 0, 0),
            "hip_r": (hull_w * 0.3, 0, 0),
            "shoulder_l": (-hull_w * 0.3, 0, hull_h),
            "shoulder_r": (hull_w * 0.3, 0, hull_h),
        }
    
    elif vtype == "gun_emplacement":
        # Static weapon platform — simpler geometry
        base_h = 0.08
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.15 * build, depth=base_h, location=(0, 0, base_h / 2))
        base = bpy.context.active_object
        base.name = "Base"
        assign_material(base, mats, mat_hull)
        add_bevel(base, width=0.005, segments=2)
        shade_smooth(base)
        simple_uv_unwrap(base)
        parts.append(base)
        
        # Shield
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -0.08, 0.15))
        shield = bpy.context.active_object
        shield.name = "Shield"
        for v in shield.data.vertices:
            v.co.x *= 0.12 * build
            v.co.y *= 0.02
            v.co.z *= 0.15
        assign_material(shield, mats, mat_hull)
        add_bevel(shield, width=0.004, segments=2)
        shade_smooth(shield)
        parts.append(shield)
        
        # Gun
        bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.015, depth=0.2, location=(0, 0.1, 0.15))
        gun = bpy.context.active_object
        gun.name = "Gun"
        gun.rotation_euler = (math.radians(90), 0, 0)
        assign_material(gun, mats, mat_track)
        parts.append(gun)
        
        joints = {"hip_l": (-0.1, 0, 0), "hip_r": (0.1, 0, 0), "shoulder_l": (0, 0, 0.2), "shoulder_r": (0, 0, 0.2)}
    
    return parts, joints


def create_vehicle_armature(joints, config) -> bpy.types.Object:
    """Simple vehicle armature (chassis root only — no bone animation needed)."""
    arm_data = bpy.data.armatures.new("VehicleArmature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Single root bone for the whole vehicle
    bone = arm_data.edit_bones.new("Chassis")
    bone.head = (0, 0, 0)
    bone.tail = (0, 0.1, 0)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj


# =============================================================================
# CREATURE TEMPLATE (quadruped)
# =============================================================================

def generate_creature(config: dict, mats: dict) -> tuple:
    """
    Generate a quadruped creature: body, head, 4 legs, tail.
    
    Config additions:
        "creature": {
            "type": "quadruped" | "biped",
            "tail": true,
            "horn": true,
            "wing": false
        }
    """
    props = config["proportions"]
    build = props.get("build", 1.0)
    total_h = props.get("height", 0.8)
    leg_ratio = props.get("leg_ratio", 0.45)
    creature_cfg = config.get("creature", {})
    
    mat_body = config["materials"].get("torso", "MAT_GrimdarkMetal")
    mat_leather = config["materials"].get("boots", "MAT_GrimdarkLeather")
    mat_accent = config["materials"].get("accent", "MAT_ImperialGold")
    
    parts = []
    joints = {}
    
    leg_h = total_h * leg_ratio
    body_h = total_h * 0.4
    body_w = 0.20 * build
    body_l = 0.30 * build
    
    # === Body (torso) — hard-surface carapace ===
    body_z = leg_h + body_h / 2
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, body_z))
    body = bpy.context.active_object
    body.name = "Body"
    for v in body.data.vertices:
        v.co.x *= body_w / 2
        v.co.y *= body_l / 2
        v.co.z *= body_h / 2
        # Taper: wider at front, narrower at rear
        if v.co.y < 0:
            v.co.x *= 0.6
            v.co.z *= 0.7
        # Flatten top into carapace plates
        if v.co.z > 0 and v.co.z < 0.2:
            v.co.x *= 1.1  # Widen at carapace ridge
    assign_material(body, mats, mat_body)
    add_hard_surface(body, bevel_width=0.006, bevel_segments=2)
    shade_flat(body)
    simple_uv_unwrap(body)
    parts.append(body)
    
    # === Head — hard-surface carapace ===
    head_r = 0.06 * build
    head_z = body_z + body_h / 2 + head_r * 0.5
    head_y = body_l / 2 + head_r * 0.5
    
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=head_r, location=(0, head_y, head_z))
    head = bpy.context.active_object
    head.name = "Head"
    for v in head.data.vertices:
        v.co.y *= 1.2  # Snout elongation
    assign_material(head, mats, mat_body)
    add_hard_surface(head, bevel_width=0.003, bevel_segments=2)
    shade_flat(head)
    simple_uv_unwrap(head)
    parts.append(head)
    
    # === Horns — hard-surface chitin ===
    if creature_cfg.get("horn", True):
        for side, sign in [("L", -1), ("R", 1)]:
            bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.015, radius2=0.005, depth=0.06, location=(sign * head_r * 0.4, head_y, head_z + head_r * 0.5))
            horn = bpy.context.active_object
            horn.name = f"Horn_{side}"
            horn.rotation_euler = (math.radians(-30), 0, sign * 0.2)
            assign_material(horn, mats, mat_accent)
            add_hard_surface(horn, bevel_width=0.002, bevel_segments=1)
            shade_flat(horn)
            parts.append(horn)
    
    # === Legs (4) — hard-surface carapace ===
    leg_positions = [
        ("FL", -body_w * 0.35, body_l * 0.3),  # Front-left
        ("FR", body_w * 0.35, body_l * 0.3),   # Front-right
        ("BL", -body_w * 0.35, -body_l * 0.3), # Back-left
        ("BR", body_w * 0.35, -body_l * 0.3),  # Back-right
    ]
    
    for label, lx, ly in leg_positions:
        leg_z = leg_h / 2
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.025 * build, depth=leg_h, location=(lx, ly, leg_z))
        leg = bpy.context.active_object
        leg.name = f"Leg_{label}"
        assign_material(leg, mats, mat_body if "F" in label else mat_leather)
        add_hard_surface(leg, bevel_width=0.004, bevel_segments=2)
        shade_flat(leg)
        simple_uv_unwrap(leg)
        parts.append(leg)
        
        # Foot/claw — hard-surface
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.02 * build, location=(lx, ly, 0.01))
        foot = bpy.context.active_object
        foot.name = f"Foot_{label}"
        for v in foot.data.vertices:
            v.co.z *= 0.4
            v.co.z *= 0.4
        assign_material(foot, mats, mat_leather)
        add_hard_surface(foot, bevel_width=0.002, bevel_segments=1)
        shade_flat(foot)
        parts.append(foot)
        
        joints[f"leg_{label.lower()}"] = (lx, ly, leg_z)
    
    # === Tail — hard-surface carapace plates ===
    if creature_cfg.get("tail", True):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -body_l / 2 - 0.05, body_z * 0.8))
        tail = bpy.context.active_object
        tail.name = "Tail"
        for v in tail.data.vertices:
            v.co.x *= 0.02 * build
            v.co.y *= 0.08
            v.co.z *= 0.06 * build
            if v.co.y < 0:
                v.co.x *= 1.5  # Flatten at tip
                v.co.z *= 0.5
        assign_material(tail, mats, mat_body)
        add_hard_surface(tail, bevel_width=0.003, bevel_segments=2)
        shade_flat(tail)
        simple_uv_unwrap(tail)
        parts.append(tail)
    
    # === Wings — soft membrane (keep subsurf) ===
    if creature_cfg.get("wing", False):
        for side, sign in [("L", -1), ("R", 1)]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(sign * (body_w / 2 + 0.02), 0, body_z + body_h * 0.3))
            wing = bpy.context.active_object
            wing.name = f"Wing_{side}"
            for v in wing.data.vertices:
                v.co.x *= sign * 0.12 * build
                v.co.y *= 0.04
                v.co.z *= 0.06 * build
            assign_material(wing, mats, mat_leather)
            add_subsurf(wing, levels=1, render_levels=2)
            shade_smooth(wing)
            parts.append(wing)
    
    joints.update({
        "hip_l": (-body_w * 0.3, 0, 0),
        "hip_r": (body_w * 0.3, 0, 0),
        "shoulder_l": (-body_w * 0.3, 0, body_z),
        "shoulder_r": (body_w * 0.3, 0, body_z),
    })
    
    return parts, joints


def create_creature_armature(joints, config) -> bpy.types.Object:
    """Quadruped armature: spine → neck → head, 4 legs."""
    arm_data = bpy.data.armatures.new("CreatureArmature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    def make_bone(name, head, tail, parent=None):
        bone = arm_data.edit_bones.new(name)
        bone.head = mathutils.Vector(head)
        bone.tail = mathutils.Vector(tail)
        if parent:
            bone.parent = parent
        return bone
    
    # Spine
    hip_center = (0, 0, 0.1)
    chest = (0, 0.3, 0.2)
    neck = (0, 0.4, 0.3)
    head_top = (0, 0.45, 0.35)
    
    spine = make_bone("Spine", hip_center, chest)
    neck_bone = make_bone("Neck", chest, neck, spine)
    head_bone = make_bone("Head", neck, head_top, neck_bone)
    
    # Legs
    for label, key in [("FL", "leg_fl"), ("FR", "leg_fr"), ("BL", "leg_bl"), ("BR", "leg_br")]:
        pos = joints.get(key, (0, 0, 0.1))
        knee = (pos[0], pos[1], pos[2] * 0.6)
        foot = (pos[0], pos[1], 0)
        thigh = make_bone(f"Thigh_{label}", pos, knee, spine)
        shin = make_bone(f"Shin_{label}", knee, foot, thigh)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj


# =============================================================================
# INSECTOID TEMPLATE
# =============================================================================

def generate_insectoid(config: dict, mats: dict) -> tuple:
    """
    Generate an insectoid creature: segmented body, 6+ legs, mandibles.
    
    Config additions:
        "insectoid": {
            "leg_count": 6,
            "wings": false,
            "segments": 3
        }
    """
    props = config["proportions"]
    build = props.get("build", 1.0)
    total_h = props.get("height", 0.5)
    insect_cfg = config.get("insectoid", {})
    leg_count = insect_cfg.get("leg_count", 6)
    segments = insect_cfg.get("segments", 3)
    
    mat_carapace = config["materials"].get("torso", "MAT_ChaosRust")
    mat_joint = config["materials"].get("boots", "MAT_GrimdarkLeather")
    mat_accent = config["materials"].get("accent", "MAT_BioFlesh")
    
    parts = []
    joints = {}
    
    body_w = 0.16 * build
    body_h = total_h * 0.6
    seg_length = 0.20 * build
    total_length = seg_length * segments
    
    # === Segmented body — hard-surface carapace plates ===
    for i in range(segments):
        seg_y = (i - (segments - 1) / 2) * seg_length
        seg_h = body_h * (1.0 - i * 0.15)  # Taper toward rear
        seg_r = body_w * (1.0 - i * 0.1)
        
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=seg_r, location=(0, seg_y, body_h / 2))
        seg = bpy.context.active_object
        seg.name = f"Segment_{i}"
        for v in seg.data.vertices:
            v.co.z *= 0.6  # Flatten
            if i > 0:
                v.co.y *= 0.9  # Taper
        assign_material(seg, mats, mat_carapace if i % 2 == 0 else mat_joint)
        add_hard_surface(seg, bevel_width=0.004, bevel_segments=2)
        shade_flat(seg)
        simple_uv_unwrap(seg)
        parts.append(seg)
    
    # === Head — hard-surface carapace ===
    head_y = total_length / 2 + 0.05
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=body_w * 0.4, location=(0, head_y, body_h * 0.5))
    head = bpy.context.active_object
    head.name = "InsectHead"
    for v in head.data.vertices:
        v.co.y *= 1.3  # Elongated
        v.co.z *= 0.5
    assign_material(head, mats, mat_carapace)
    add_hard_surface(head, bevel_width=0.003, bevel_segments=2)
    shade_flat(head)
    simple_uv_unwrap(head)
    parts.append(head)
    
    # === Mandibles — hard-surface chitin ===
    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.01, radius2=0.003, depth=0.05, location=(sign * body_w * 0.25, head_y + 0.05, body_h * 0.3))
        mandible = bpy.context.active_object
        mandible.name = f"Mandible_{side}"
        assign_material(mandible, mats, mat_accent)
        add_hard_surface(mandible, bevel_width=0.002, bevel_segments=1)
        shade_flat(mandible)
        parts.append(mandible)
    
    # === Eyes (glowing) — keep smooth/organic ===
    for side, sign in [("L", -1), ("R", 1)]:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.012, location=(sign * body_w * 0.3, head_y + 0.02, body_h * 0.55))
        eye = bpy.context.active_object
        eye.name = f"Eye_{side}"
        for v in eye.data.vertices:
            v.co.z *= 0.5
        assign_material(eye, mats, mat_accent)
        parts.append(eye)
    
    # === Legs — hard-surface carapace ===
    for leg_idx in range(leg_count):
        side_mult = -1 if leg_idx % 2 == 0 else 1
        seg_idx = leg_idx // 2
        leg_y = (seg_idx - (segments - 1) / 2) * seg_length
        
        leg_len = 0.12 * build
        leg_z = body_h * 0.3
        
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.012, depth=leg_len, location=(side_mult * body_w * 0.6, leg_y, leg_z))
        leg = bpy.context.active_object
        leg.name = f"Leg_{leg_idx}"
        leg.rotation_euler = (0, 0, side_mult * math.radians(30))
        assign_material(leg, mats, mat_carapace)
        add_hard_surface(leg, bevel_width=0.003, bevel_segments=2)
        shade_flat(leg)
        parts.append(leg)
        
        # Joint/Claw — hard-surface
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.008, location=(side_mult * (body_w * 0.6 + leg_len * 0.5), leg_y, leg_z))
        claw = bpy.context.active_object
        claw.name = f"Claw_{leg_idx}"
        assign_material(claw, mats, mat_joint)
        add_hard_surface(claw, bevel_width=0.001, bevel_segments=1)
        shade_flat(claw)
        parts.append(claw)
        
        joints[f"leg_{leg_idx}"] = (side_mult * body_w * 0.6, leg_y, leg_z)
    
    # === Wings — soft membrane (keep smooth) ===
    if insect_cfg.get("wings", False):
        for side, sign in [("L", -1), ("R", 1)]:
            bpy.ops.mesh.primitive_cube_add(size=1, location=(sign * (body_w * 0.5 + 0.01), -seg_length * 0.3, body_h * 0.8))
            wing = bpy.context.active_object
            wing.name = f"Wing_{side}"
            for v in wing.data.vertices:
                v.co.x *= sign * 0.15 * build
                v.co.y *= 0.04
                v.co.z *= 0.002
            assign_material(wing, mats, mat_accent)
            shade_smooth(wing)
            parts.append(wing)
    
    joints.update({
        "hip_l": (-body_w * 0.3, 0, 0),
        "hip_r": (body_w * 0.3, 0, 0),
        "shoulder_l": (-body_w * 0.3, 0, body_h),
        "shoulder_r": (body_w * 0.3, 0, body_h),
    })
    
    return parts, joints


def create_insectoid_armature(joints, config) -> bpy.types.Object:
    """Insectoid armature: body chain + legs."""
    arm_data = bpy.data.armatures.new("InsectArmature")
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    
    def make_bone(name, head, tail, parent=None):
        bone = arm_data.edit_bones.new(name)
        bone.head = mathutils.Vector(head)
        bone.tail = mathutils.Vector(tail)
        if parent:
            bone.parent = parent
        return bone
    
    # Simple spine chain
    root = make_bone("Root", (0, -0.1, 0.1), (0, 0, 0.15))
    body = make_bone("Body", (0, 0, 0.15), (0, 0.1, 0.2), root)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj


# =============================================================================
# DISPATCH
# =============================================================================

def get_nonhumanoid_animations(body_type: str = "vehicle"):
    """Return appropriate animation skeleton for non-humanoid types."""
    if body_type == "vehicle":
        return {
            "idle": (1, 3),
            "move": (10, 16),
            "attack": (20, 24),
            "destroy": (40, 44),
        }
    elif body_type in ("creature", "quadruped"):
        return {
            "idle": (1, 5),
            "walk": (10, 18),
            "attack": (20, 26),
            "hurt": (30, 33),
            "die": (40, 48),
        }
    elif body_type == "insectoid":
        return {
            "idle": (1, 4),
            "scuttle": (10, 16),
            "attack": (20, 24),
            "hurt": (30, 32),
            "die": (40, 46),
        }
    return {}
