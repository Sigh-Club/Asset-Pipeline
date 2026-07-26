#!/usr/bin/env python3
"""
render_8dir_v2.py — Blender Python Script (v2)
Automated 8-direction isometric sprite rendering with PBR materials.

Improvements over v1:
- Renders at 4× supersample (384×512), downscales to 96×128 nearest-neighbor
- Supports Cycles and Eevee render engines (Cycles for PBR, Eevee for speed)
- Outputs depth and normal passes alongside RGBA
- Proper NLA action handling: evaluates and renders each action in isolation
- PBR lighting setup tuned for Principled BSDF materials
- Color management enabled for proper material response

Usage:
    blender model.blend --background --python render_8dir_v2.py
    blender model.blend --background --python render_8dir_v2.py -- --engine CYCLES --no-depth
"""

import bpy
import os
import sys
import json
import math
import mathutils

# =============================================================================
# CONFIGURATION
# =============================================================================

FRAME_W = 96
FRAME_H = 128
SUPER_SAMPLE = 4  # render at 4× then downscale
RENDER_W = FRAME_W * SUPER_SAMPLE  # 384
RENDER_H = FRAME_H * SUPER_SAMPLE  # 512

DEFAULT_SAMPLES = 32  # reduced from 64 for reasonable render times
RENDER_ENGINE = "CYCLES"
COLOR_MODE = "RGBA"
FILE_FORMAT = "PNG"
COLOR_DEPTH = "8"
COMPRESSION = 15
FILM_TRANSPARENT = True

# Output passes
OUTPUT_DEPTH = True
OUTPUT_NORMAL = True

OUTPUT_SUBDIR = "render/raw"

DIRECTIONS = [
    ("N", 0), ("NE", 45), ("E", 90), ("SE", 135),
    ("S", 180), ("SW", 225), ("W", 270), ("NW", 315),
]

ISO_ELEVATION_DEG = 30

# =============================================================================
# ARG PARSING
# =============================================================================

def parse_args():
    """Parse --engine, --no-depth, --no-normal, --fast, --samples from sys.argv after --"""
    args = []
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
    
    global RENDER_ENGINE, OUTPUT_DEPTH, OUTPUT_NORMAL, DEFAULT_SAMPLES
    i = 0
    while i < len(args):
        if args[i] == "--engine" and i + 1 < len(args):
            RENDER_ENGINE = args[i + 1].upper()
            i += 2
        elif args[i] == "--no-depth":
            OUTPUT_DEPTH = False
            i += 1
        elif args[i] == "--no-normal":
            OUTPUT_NORMAL = False
            i += 1
        elif args[i] == "--fast":
            DEFAULT_SAMPLES = 16
            i += 1
        elif args[i] == "--samples" and i + 1 < len(args):
            DEFAULT_SAMPLES = int(args[i + 1])
            i += 2
        else:
            i += 1

parse_args()

# =============================================================================
# LOGGING
# =============================================================================

def log(msg: str):
    print(f"[render_8dir_v2] {msg}")

# =============================================================================
# OUTPUT DIRECTORY
# =============================================================================

def ensure_output_dir(blend_path: str) -> str:
    base = os.path.dirname(blend_path)
    out_dir = os.path.join(base, OUTPUT_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

# =============================================================================
# CAMERA & RIG
# =============================================================================

def clear_existing_rig():
    for name in ("ISO_CAM_RIG", "ISO_Camera"):
        existing = bpy.data.objects.get(name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)

def compute_scene_bounds():
    """Compute bounding box of all mesh objects in the scene."""
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ mathutils.Vector(corner)
            min_x = min(min_x, world_corner.x)
            max_x = max(max_x, world_corner.x)
            min_y = min(min_y, world_corner.y)
            max_y = max(max_y, world_corner.y)
            min_z = min(min_z, world_corner.z)
            max_z = max(max_z, world_corner.z)
    
    if min_x == float('inf'):
        return (-50, 50, -50, 50, 0, 100)
    
    return (min_x, max_x, min_y, max_y, min_z, max_z)

def create_camera(ortho_scale: float):
    cam_data = bpy.data.cameras.new(name="ISO_Camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale  # NO supersample multiply — resolution handles that
    cam_data.clip_start = 0.01
    cam_data.clip_end = 5000.0
    
    camera = bpy.data.objects.new(name="ISO_Camera", object_data=cam_data)
    bpy.context.scene.collection.objects.link(camera)
    return camera

def create_rig(ortho_scale: float, target_z: float, bbox_diagonal: float):
    """Create the isometric camera rig centered on model midpoint."""
    clear_existing_rig()
    camera = create_camera(ortho_scale)
    
    cam_rig = bpy.data.objects.new("ISO_CAM_RIG", None)
    cam_rig.empty_display_type = "ARROWS"
    bpy.context.scene.collection.objects.link(cam_rig)
    
    cam_rig.location = (0.0, 0.0, target_z)
    
    camera.parent = cam_rig
    
    distance = max(10.0, bbox_diagonal * 3.0)
    elev = math.radians(ISO_ELEVATION_DEG)
    camera.location = (0.0, -distance * math.cos(elev), distance * math.sin(elev))
    camera.rotation_euler = (math.radians(90 - ISO_ELEVATION_DEG), 0.0, 0.0)
    
    bpy.context.scene.camera = camera
    log(f"Camera rig: ortho_scale={ortho_scale:.1f}, target_z={target_z:.1f}, distance={distance:.1f}")

# =============================================================================
# LIGHTING — PBR TUNED
# =============================================================================

def setup_lighting():
    """3-point grimdark lighting tuned for Principled BSDF (not emission)."""
    # Remove existing lights
    for obj in list(bpy.data.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
    
    # Key light — warm rusty (warm 3500K), upper-left, strong
    key = create_light("KEY", color=(1.0, 0.85, 0.65), energy=1000,
                       location=(-3, -2, 5))
    
    # Fill light — cool blue (7500K), lower-right, moderate
    fill = create_light("FILL", color=(0.6, 0.7, 1.0), energy=400,
                        location=(3, 1, 3))
    
    # Rim light — gold, behind subject, catches edges
    rim = create_light("RIM", color=(1.0, 0.82, 0.3), energy=600,
                        location=(0, 4, 4))
    
    log("Lighting: 3-point grimdark (key=warm 1000W, fill=cool 400W, rim=gold 600W)")

def create_light(name: str, color: tuple, energy: float, location: tuple):
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.color = color
    light_data.energy = energy
    light_data.size = 3.0  # Area light for soft shadows
    
    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = location
    # Point at origin
    direction = mathutils.Vector((0, 0, 0)) - mathutils.Vector(location)
    light_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return light_obj

# =============================================================================
# RENDER SETTINGS
# =============================================================================

def setup_render_settings():
    scene = bpy.context.scene
    scene.render.engine = RENDER_ENGINE
    
    # Resolution: supersampled
    scene.render.resolution_x = RENDER_W
    scene.render.resolution_y = RENDER_H
    scene.render.resolution_percentage = 100
    
    # Format
    scene.render.image_settings.file_format = FILE_FORMAT
    scene.render.image_settings.color_mode = COLOR_MODE
    scene.render.image_settings.color_depth = COLOR_DEPTH
    scene.render.image_settings.compression = COMPRESSION
    scene.render.film_transparent = FILM_TRANSPARENT
    
    if RENDER_ENGINE == "CYCLES":
        # Cycles settings for quality + reasonable speed
        scene.cycles.samples = DEFAULT_SAMPLES
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        # Try GPU, fall back to CPU if no compute device available
        try:
            preferences = bpy.context.preferences.addons['cycles'].preferences
            preferences.get_devices()
            # Check whether any GPU device is available
            has_gpu = any(
                d.type in ('CUDA', 'OPTIX', 'HIP', 'ONEAPI', 'METAL')
                and d.use
                for d in preferences.devices
            )
            if has_gpu:
                scene.cycles.device = 'GPU'
                log("Cycles device: GPU (CUDA/OptiX)")
            else:
                scene.cycles.device = 'CPU'
                log("Cycles device: CPU (no GPU compute device found)")
        except Exception:
            scene.cycles.device = 'CPU'
            log("Cycles device: CPU (fallback)")
        # Enable passes
        view_layer = scene.view_layers[0]
        if OUTPUT_DEPTH:
            view_layer.use_pass_z = True
        if OUTPUT_NORMAL:
            view_layer.use_pass_normal = True
    elif RENDER_ENGINE in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        eevee = scene.eevee
        try:
            eevee.taa_render_samples = 16
        except AttributeError:
            pass
        try:
            eevee.use_taa_reprojection = False
        except AttributeError:
            pass
        if hasattr(eevee, 'use_bloom'):
            eevee.use_bloom = False
        try:
            eevee.motion_blur_steps = 0
        except AttributeError:
            pass
        # Eevee doesn't support depth/normal passes the same way
        # Skip pass output for Eevee
    
    # Color management: ENABLED for PBR materials
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look = 'Medium High Contrast'
    scene.display_settings.display_device = 'sRGB'
    
    log(f"Render: {RENDER_W}x{RENDER_H} ({SUPER_SAMPLE}x supersample), engine={RENDER_ENGINE}")
    log(f"Output size: {FRAME_W}x{FRAME_H} after {SUPER_SAMPLE}x nearest-neighbor downscale")

# =============================================================================
# ANIMATION HANDLING — PROPER NLA ACTION EVALUATION
# =============================================================================

def get_all_actions():
    """Get all action data-blocks in the file."""
    actions = []
    for action in bpy.data.actions:
        actions.append(action.name)
    log(f"Found {len(actions)} actions: {actions}")
    return actions

def scan_animations() -> dict:
    """
    Scan for animations. Returns dict: {anim_name: {
        "frames": (start, end),
        "armature": armature_obj or None,
        "action": action_data_block or None,
        "nla_strip": strip_obj or None,
    }}
    
    Priority:
    1. NLA strips on armature (each strip = one animation, solo'd at render time)
    2. Named actions in bpy.data.actions matched to default anim names
    3. Fallback to DEFAULT_ANIMATIONS (static, frame ranges only)
    """
    DEFAULT_ANIMATIONS = {
        "idle": (1, 4),
        "walk": (10, 16),
        "attack": (20, 24),
        "hurt": (30, 32),
        "die": (40, 46),
    }
    
    obj = bpy.context.view_layer.objects.active
    
    # Find the armature (active obj, its parent, or any armature in scene)
    armature = None
    if obj and obj.type == 'ARMATURE':
        armature = obj
    elif obj and obj.parent and obj.parent.type == 'ARMATURE':
        armature = obj.parent
    else:
        for o in bpy.context.scene.objects:
            if o.type == 'ARMATURE':
                armature = o
                break
    
    # 1. Try NLA strips on the armature
    if armature and armature.animation_data and armature.animation_data.nla_tracks:
        anims = {}
        for track in armature.animation_data.nla_tracks:
            for strip in track.strips:
                name = strip.name
                start = int(strip.frame_start)
                end = int(strip.frame_end)
                anims[name] = {
                    "frames": (start, end),
                    "armature": armature,
                    "action": strip.action,
                    "nla_strip": strip,
                }
                log(f"  NLA strip: {name} [{start}-{end}] action={strip.action.name if strip.action else 'none'}")
        if anims:
            return anims
    
    # 2. Try named actions matched to default anim names
    action_names = [a.name for a in bpy.data.actions]
    if action_names:
        anims = {}
        for name, (default_start, default_end) in DEFAULT_ANIMATIONS.items():
            matching = [a for a in action_names if name.lower() in a.lower()]
            if matching:
                action = bpy.data.actions[matching[0]]
                frame_range = action.frame_range
                start = int(frame_range[0])
                end = int(frame_range[1])
                anims[name] = {
                    "frames": (start, end),
                    "armature": armature,
                    "action": action,
                    "nla_strip": None,
                }
                log(f"  Action match: {name} -> {matching[0]} [{start}-{end}]")
        if anims:
            return anims
    
    # 3. Fallback: static frame ranges
    log("  No NLA/action data found. Using DEFAULT_ANIMATIONS (static).")
    anims = {}
    for name, (start, end) in DEFAULT_ANIMATIONS.items():
        anims[name] = {
            "frames": (start, end),
            "armature": armature,
            "action": None,
            "nla_strip": None,
        }
    return anims

# =============================================================================
# RENDERING
# =============================================================================

def render_direction_anim(dlabel: str, dangle: float, anim_name: str, 
                          frame_start: int, frame_end: int, out_dir: str,
                          armature_obj=None, action=None, nla_strip=None) -> list:
    """Render one animation in one direction.
    
    If action is provided, set it as the armature's active action before rendering.
    If nla_strip is provided, solo that strip and mute all others.
    Otherwise, just advance frames (static or pre-baked animation).
    """
    scene = bpy.context.scene
    rig = bpy.data.objects["ISO_CAM_RIG"]
    rig.rotation_euler = (0.0, 0.0, math.radians(dangle))
    bpy.context.view_layer.update()
    
    # --- Animation setup: apply the right action/strip BEFORE rendering ---
    if armature_obj and armature_obj.animation_data:
        anim_data = armature_obj.animation_data
        
        if nla_strip:
            # Solo the target strip, mute all others on all tracks
            for track in anim_data.nla_tracks:
                for strip in track.strips:
                    strip.mute = (strip != nla_strip)
            # Disable the active action so NLA strips drive the animation
            anim_data.action = None
            # Enable NLA evaluation
            anim_data.use_nla = True
            log(f"  NLA solo: {nla_strip.name} on {armature_obj.name}")
        elif action:
            # Set this action as the active action
            # Mute all NLA strips so only the active action plays
            for track in anim_data.nla_tracks:
                for strip in track.strips:
                    strip.mute = True
            anim_data.action = action
            anim_data.use_nla = False
            log(f"  Action active: {action.name} on {armature_obj.name}")
    
    anim_dir = os.path.join(out_dir, anim_name, dlabel)
    os.makedirs(anim_dir, exist_ok=True)
    
    files = []
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        rel_frame = frame - frame_start + 1
        filename = f"frame_{rel_frame:02d}.png"
        filepath = os.path.join(anim_dir, filename)
        scene.render.filepath = filepath
        
        bpy.ops.render.render(write_still=True)
        files.append(filepath)
    
    total = frame_end - frame_start + 1
    log(f"Rendered {anim_name}/{dlabel}: {total} frames @ {RENDER_W}x{RENDER_H} -> {anim_dir}")
    return files

# =============================================================================
# DOWNSCALE + POST-PROCESS (runs in Blender's Python, not standalone)
# =============================================================================

def downscale_all_renders(out_dir: str):
    """Downscale all rendered PNGs from RENDER_WxRENDER_H to FRAME_WxFRAME_H
    using nearest-neighbor. Done in-place (replaces high-res with final-res)."""
    try:
        from PIL import Image
    except ImportError:
        log("WARNING: PIL not available in Blender Python. Skipping downscale.")
        log("Run batch_pixelate.py separately to downscale + quantize.")
        return
    
    raw_dir = os.path.join(out_dir, "raw")
    if not os.path.exists(raw_dir):
        raw_dir = out_dir  # files might be directly in out_dir
    
    count = 0
    for root, dirs, files in os.walk(out_dir):
        for f in files:
            if not f.endswith(".png"):
                continue
            filepath = os.path.join(root, f)
            img = Image.open(filepath)
            if img.size == (RENDER_W, RENDER_H):
                # Downscale with nearest-neighbor
                small = img.resize((FRAME_W, FRAME_H), Image.NEAREST)
                small.save(filepath, "PNG")
                count += 1
    
    log(f"Downscaled {count} frames from {RENDER_W}x{RENDER_H} to {FRAME_W}x{FRAME_H} (nearest-neighbor)")

# =============================================================================
# MANIFEST
# =============================================================================

def generate_manifest(out_dir: str, animations: dict, all_files: list):
    manifest = {
        "generator": "render_8dir_v2.py",
        "version": "2.0",
        "frame_size": {"w": FRAME_W, "h": FRAME_H},
        "render_size": {"w": RENDER_W, "h": RENDER_H},
        "super_sample": SUPER_SAMPLE,
        "engine": RENDER_ENGINE,
        "directions": [d[0] for d in DIRECTIONS],
        "animations": {},
        "files": all_files,
    }
    for anim_name, (start, end) in animations.items():
        manifest["animations"][anim_name] = {
            "start_frame": start, "end_frame": end, "frame_count": end - start + 1,
        }
    
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"Manifest written: {manifest_path}")

# =============================================================================
# MAIN
# =============================================================================

def main():
    blend_path = bpy.data.filepath
    if not blend_path:
        log("ERROR: Save your .blend file before running this script.")
        sys.exit(1)
    
    out_dir = ensure_output_dir(blend_path)
    log(f"Output directory: {out_dir}")
    
    # Compute model bounds
    min_x, max_x, min_y, max_y, min_z, max_z = compute_scene_bounds()
    bbox_width = max_x - min_x
    bbox_height = max_z - min_z
    bbox_depth = max_y - min_y
    bbox_diagonal = math.sqrt(bbox_width**2 + bbox_height**2 + bbox_depth**2)
    
    log(f"Scene bounds: W={bbox_width:.1f} H={bbox_height:.1f} D={bbox_depth:.1f} diag={bbox_diagonal:.1f}")
    
    ortho_scale = max(bbox_height / 0.80, 1.0)  # Fill 80% of frame, min 1.0
    target_z = min_z + bbox_height / 2.0
    
    setup_render_settings()
    create_rig(ortho_scale, target_z, bbox_diagonal)
    setup_lighting()
    
    animations = scan_animations()
    all_rendered_files = []
    for anim_name, anim_info in animations.items():
        frame_start, frame_end = anim_info["frames"]
        armature = anim_info.get("armature")
        action = anim_info.get("action")
        nla_strip = anim_info.get("nla_strip")
        for dlabel, dangle in DIRECTIONS:
            files = render_direction_anim(dlabel, dangle, anim_name, 
                                          frame_start, frame_end, out_dir,
                                          armature_obj=armature, action=action,
                                          nla_strip=nla_strip)
            all_rendered_files.extend(files)
    
    # Downscale in-place (if PIL available in Blender's Python)
    downscale_all_renders(out_dir)
    
    # Build simple frames dict for manifest
    manifest_anims = {name: info["frames"] for name, info in animations.items()}
    generate_manifest(out_dir, manifest_anims, all_rendered_files)
    log("Render complete. Proceed to palette quantization (batch_pixelate.py).")

if __name__ == "__main__":
    main()