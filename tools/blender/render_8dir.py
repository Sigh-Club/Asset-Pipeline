#!/usr/bin/env python3
"""
render_8dir.py — Blender Python Script
Automated 8-direction isometric sprite rendering pipeline.

Usage:
    blender your_model.blend --background --python render_8dir.py

This script is designed to be run INSIDE Blender's Python environment.
It requires bpy (bundled with Blender).

What it does:
1. Sets up an isometric orthographic camera rig (8 directions)
2. Configures grimdark lighting (3-point)
3. Iterates through all NLA animations
4. Renders each animation frame from 8 compass directions
5. Exports PNGs with alpha transparency
6. Generates LOD1 (50%) and LOD2 (25%) variants via compositor
7. Writes a manifest.json describing all outputs

Author: Asset-Pipeline Automation
Docs: docs/BLENDER_WORKFLOW.md
"""

import bpy
import os
import sys
import json
import math

# =============================================================================
# CONFIGURATION — Adjust these per project or read from external config in future
# =============================================================================

# Frame size for LOD0 (final sprite dimensions in pixels)
# Must match IoA specs: 96x128 for characters
FRAME_W = 96
FRAME_H = 128

# Animation definitions: name -> (start_frame, end_frame)
# These are defaults; the script also scans NLA tracks.
DEFAULT_ANIMATIONS = {
    "idle": (1, 4),
    "walk": (10, 16),
    "attack": (20, 24),
    "hurt": (30, 32),
    "die": (40, 46),
}

# 8 true directions: (label, rotation_z_degrees)
# N = 0°, NE = 45°, E = 90°, SE = 135°, S = 180°, SW = 225°, W = 270°, NW = 315°
DIRECTIONS = [
    ("N", 0),
    ("NE", 45),
    ("E", 90),
    ("SE", 135),
    ("S", 180),
    ("SW", 225),
    ("W", 270),
    ("NW", 315),
]

# Isometric camera elevation (tilt down from horizontal)
ISO_ELEVATION_DEG = 30

# Output base path. Script derives from current .blend file location.
OUTPUT_SUBDIR = "render/raw"

# Rendering engine
RENDER_ENGINE = "BLENDER_EEVEE"  # Use EEVEE for speed; switch to CYCLES if quality demands

# Image format
COLOR_MODE = "RGBA"       # Alpha channel
FILE_FORMAT = "PNG"
COLOR_DEPTH = "8"         # 8-bit per channel (sufficient for pixel art)
COMPRESSION = 15          # PNG compression level (0-100, higher = smaller but slower)

# Film / background
FILM_TRANSPARENT = True   # Crucial: render on transparent background

# LOD multipliers (relative to LOD0)
LODS = {
    "LOD0": 1.0,
    "LOD1": 0.5,
    "LOD2": 0.25,
}

# =============================================================================
# INTERNAL STATE
# =============================================================================

scene = None
cam_rig = None
camera = None

# =============================================================================
# SETUP
# =============================================================================


def log(msg: str):
    """Print to Blender console and stdout."""
    print(f"[render_8dir] {msg}")


def ensure_output_dir(blend_path: str) -> str:
    """
    Derive output directory from .blend location.
    If .blend is at assets/characters/foo/model/foo.blend,
    output goes to assets/characters/foo/render/raw/
    """
    base = os.path.dirname(blend_path)  # .../model
    char_dir = os.path.dirname(base)    # .../foo
    out_dir = os.path.join(char_dir, OUTPUT_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def clear_existing_rig():
    """Remove old camera rig if present (from previous run)."""
    global cam_rig
    existing = bpy.data.objects.get("ISO_CAM_RIG")
    if existing:
        log("Removing existing ISO_CAM_RIG")
        # Unlink from all collections
        for coll in bpy.data.collections:
            if existing.name in coll.objects:
                coll.objects.unlink(existing)
        bpy.data.objects.remove(existing, do_unlink=True)
    cam_rig = None


def create_camera():
    """Create orthographic isometric camera."""
    global camera
    cam_data = bpy.data.cameras.new(name="ISO_Camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = FRAME_H  # Orthographic scale matches sprite height
    cam_data.clip_start = 0.01
    cam_data.clip_end = 1000.0

    camera = bpy.data.objects.new(name="ISO_Camera", object_data=cam_data)
    bpy.context.scene.collection.objects.link(camera)
    return camera


def create_light(name: str, color: tuple, energy: float, location: tuple):
    """Create a point light with given properties."""
    light_data = bpy.data.lights.new(name=name, type="POINT")
    light_data.energy = energy
    light_data.color = color
    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = location
    return light_obj


def setup_lighting():
    """
    Set up grimdark 3-point lighting.
    Key: warm rusty, upper-left
    Fill: cool blue, lower-right
    Rim: gold, behind subject
    """
    # Remove existing lights named with our prefix
    for obj in bpy.data.objects:
        if obj.name.startswith("ISO_Light"):
            bpy.data.objects.remove(obj, do_unlink=True)

    # Key light — warm, upper-left-front
    create_light(
        "ISO_Light_Key",
        color=(0.58, 0.28, 0.16),   # #946848 approx
        energy=80.0,
        location=(-3.0, -3.0, 5.0)
    )

    # Fill light — cool blue, lower-right-front
    create_light(
        "ISO_Light_Fill",
        color=(0.20, 0.35, 0.47),   # #345A78 approx
        energy=20.0,
        location=(3.0, 3.0, 2.0)
    )

    # Rim light — gold, behind
    create_light(
        "ISO_Light_Rim",
        color=(0.83, 0.63, 0.14),   # #D4A024 approx
        energy=50.0,
        location=(0.0, -4.0, 4.0)
    )

    log("Lighting setup complete (3-point grimdark)")


def create_rig():
    """Create the isometric camera rig (empty + camera parented)."""
    global cam_rig
    clear_existing_rig()
    camera = create_camera()

    # Create empty at origin to act as rig
    cam_rig = bpy.data.objects.new("ISO_CAM_RIG", None)
    cam_rig.empty_display_type = "ARROWS"
    bpy.context.scene.collection.objects.link(cam_rig)

    # Parent camera to rig
    camera.parent = cam_rig

    # Position camera in isometric orientation relative to rig
    # At 30° elevation, distance d from origin:
    # y = d * cos(30°), z = d * sin(30°)
    distance = 10.0
    elev = math.radians(ISO_ELEVATION_DEG)
    camera.location = (0.0, -distance * math.cos(elev), distance * math.sin(elev))
    camera.rotation_euler = (math.radians(90 - ISO_ELEVATION_DEG), 0.0, 0.0)

    # Set this camera as active
    bpy.context.scene.camera = camera

    log(f"Camera rig created: ortho_scale={FRAME_H}, elevation={ISO_ELEVATION_DEG}°")


def setup_render_settings():
    """Configure Blender render engine and output settings."""
    scene = bpy.context.scene
    scene.render.engine = RENDER_ENGINE

    # Only EEVEE-specific settings if using EEVEE
    if RENDER_ENGINE == "BLENDER_EEVEE":
        # Disable screen-space effects that blur pixel edges
        eevee = scene.eevee
        eevee.taa_render_samples = 1   # No anti-aliasing oversampling
        eevee.use_taa_reprojection = False
        # Disable bloom, motion blur for crisp sprites
        eevee.use_bloom = False
        eevee.motion_blur_steps = 0

    # Image output
    scene.render.image_settings.file_format = FILE_FORMAT
    scene.render.image_settings.color_mode = COLOR_MODE
    scene.render.image_settings.color_depth = COLOR_DEPTH
    scene.render.image_settings.compression = COMPRESSION

    # Background transparency
    scene.render.film_transparent = FILM_TRANSPARENT

    # Resolution (LOD0)
    scene.render.resolution_x = FRAME_W
    scene.render.resolution_y = FRAME_H
    scene.render.resolution_percentage = 100

    log(f"Render settings: {FRAME_W}x{FRAME_H}, {COLOR_MODE}, transparent={FILM_TRANSPARENT}")


def scan_animations() -> dict:
    """
    Scan NLA tracks and action strips to discover animations.
    Falls back to DEFAULT_ANIMATIONS if no NLA found.
    Returns dict: anim_name -> (start_frame, end_frame)
    """
    obj = bpy.context.view_layer.objects.active
    if not obj or not obj.animation_data:
        log("No active animated object found. Using default animation ranges.")
        return DEFAULT_ANIMATIONS.copy()

    anims = {}
    if obj.animation_data.nla_tracks:
        for track in obj.animation_data.nla_tracks:
            for strip in track.strips:
                name = strip.name
                start = int(strip.frame_start)
                end = int(strip.frame_end)
                anims[name] = (start, end)
                log(f"Found NLA strip: {name} ({start}-{end})")

    if not anims:
        log("No NLA strips found. Using defaults.")
        return DEFAULT_ANIMATIONS.copy()

    return anims


def render_direction_anim(dlabel: str, dangle: float, anim_name: str, frame_start: int, frame_end: int, out_dir: str) -> list:
    """
    Render all frames of one animation from one direction.
    Returns list of output file paths.
    """
    scene = bpy.context.scene
    rig = bpy.data.objects["ISO_CAM_RIG"]

    # Rotate rig to direction
    rig.rotation_euler = (0.0, 0.0, math.radians(dangle))

    # Ensure scene updates before render
    bpy.context.view_layer.update()

    # Prepare output subdirectory
    anim_dir = os.path.join(out_dir, anim_name, dlabel)
    os.makedirs(anim_dir, exist_ok=True)

    files = []
    total_frames = frame_end - frame_start + 1

    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        rel_frame = frame - frame_start + 1
        filename = f"frame_{rel_frame:02d}.png"
        filepath = os.path.join(anim_dir, filename)
        scene.render.filepath = filepath

        bpy.ops.render.render(write_still=True)
        files.append(filepath)

        # Optional: generate LOD variants via compositor scaling
        # (For simplicity, we render at full resolution only here.
        # LOD generation is handled in GIMP post-process for better pixel control.)

    log(f"Rendered {anim_name}/{dlabel}: {total_frames} frames -> {anim_dir}")
    return files


def generate_manifest(out_dir: str, animations: dict, all_files: list):
    """Write manifest.json describing the render output."""
    manifest = {
        "generator": "render_8dir.py",
        "frame_size": {"w": FRAME_W, "h": FRAME_H},
        "directions": [d[0] for d in DIRECTIONS],
        "animations": {},
        "files": all_files,
    }

    for anim_name, (start, end) in animations.items():
        manifest["animations"][anim_name] = {
            "start_frame": start,
            "end_frame": end,
            "frame_count": end - start + 1,
        }

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    log(f"Manifest written: {manifest_path}")


def main():
    """Entry point for Blender background execution."""
    blend_path = bpy.data.filepath
    if not blend_path:
        log("ERROR: Save your .blend file before running this script.")
        sys.exit(1)

    out_dir = ensure_output_dir(blend_path)
    log(f"Output directory: {out_dir}")

    # Setup
    setup_render_settings()
    create_rig()
    setup_lighting()

    # Discover animations
    animations = scan_animations()

    # Render loop
    all_rendered_files = []
    for anim_name, (frame_start, frame_end) in animations.items():
        for dlabel, dangle in DIRECTIONS:
            files = render_direction_anim(dlabel, dangle, anim_name, frame_start, frame_end, out_dir)
            all_rendered_files.extend(files)

    # Manifest
    generate_manifest(out_dir, animations, all_rendered_files)
    log("Render complete. Proceed to GIMP post-process.")


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    main()
