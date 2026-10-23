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
    blender model.blend --background --python render_8dir_v2.py -- --faction iron_directorate --fast
    blender model.blend --background --python render_8dir_v2.py -- --faction cinderborn --samples 128
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

FRAME_W = 384
FRAME_H = 512
SUPER_SAMPLE = 3  # render at 3× (1152×1536) → LANCZOS → 384×512
RENDER_W = FRAME_W * SUPER_SAMPLE  # 1152
RENDER_H = FRAME_H * SUPER_SAMPLE  # 1536

DEFAULT_SAMPLES = 128  # high-quality Cycles PBR samples
MAX_SAMPLES = 256      # absolute max for final renders
FAST_SAMPLES = 64      # fast iteration mode
RENDER_ENGINE = "CYCLES"

# =============================================================================
# VRAM GOVERNOR (review 2026-10-23): shared-desktop courtesy -- renders adapt to
# whatever the desktop leaves free instead of fighting the compositor.
VRAM_RESERVE_MIB = 2048
RENDER_META = {}  # reproducibility fingerprint (standards D4), written to the manifest
COLOR_MODE = "RGBA"
FILE_FORMAT = "PNG"
COLOR_DEPTH = "16"    # 16-bit for full PBR material depth
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
# FACTION LIGHTING PROFILES
# =============================================================================

FACTION_LIGHTING = {
    "iron_directorate": {
        "key": {"color": (0.85, 0.90, 1.0), "type": "SUN", "energy": 2.5, "size": 0.08, "location": (-4, -3, 6)},    # SUN key — softer angle (0.08 rad) for midtone gradient ramp, not a hard stencil
        "fill": {"color": (0.75, 0.80, 0.85), "energy": 600, "size": 1.2, "location": (3, 2, 2)},       # AREA fill — lifts shadow side off the black background
        "rim": {"color": (0.80, 0.70, 0.50), "type": "SUN", "energy": 2.5, "size": 0.02, "location": (1, 6, 3)},        # SUN rim — stronger, carves shadow-side silhouette
        "specular": {"color": (0.95, 0.95, 1.0), "energy": 400, "size": 0.2, "location": (0, 0, 8)},    # Top sparkle
    },
    "cinderborn": {
        "key": {"color": (1.0, 0.40, 0.70), "type": "SUN", "energy": 2.5, "size": 0.08, "location": (-4, -3, 6)},    # Warm magenta SUN key — corrupted ritual
        "fill": {"color": (0.60, 0.30, 0.80), "energy": 600, "size": 1.2, "location": (3, 2, 2)},       # Deep purple AREA fill
        "rim": {"color": (1.0, 0.60, 0.20), "type": "SUN", "energy": 2.5, "size": 0.02, "location": (1, 6, 3)},        # Orange magma SUN rim
        "specular": {"color": (1.0, 0.80, 0.90), "energy": 400, "size": 0.2, "location": (0, 0, 8)},    # Pink-white top
    },
    "parasitic_bloom": {
        "key": {"color": (0.65, 0.95, 0.60), "energy": 3000, "size": 0.5, "location": (-4, -3, 6)},     # Sickly green-white
        "fill": {"color": (0.90, 0.55, 0.65), "energy": 500, "size": 1.0, "location": (3, 2, 2)},       # Pinkish fill
        "rim": {"color": (0.85, 0.75, 0.60), "energy": 2000, "size": 0.3, "location": (1, 6, 3)},       # Bone-coloured rim
        "specular": {"color": (0.80, 0.95, 0.70), "energy": 800, "size": 0.2, "location": (0, 0, 8)},   # Green-white top
    },
    "wreckstorm_clans": {
        "key": {"color": (1.0, 0.60, 0.20), "energy": 4000, "size": 0.5, "location": (-4, -3, 6)},      # Orange-red — hot scrap
        "fill": {"color": (0.50, 0.35, 0.25), "energy": 300, "size": 1.0, "location": (3, 2, 2)},       # Dark brown fill (minimal)
        "rim": {"color": (1.0, 0.85, 0.30), "energy": 2500, "size": 0.3, "location": (1, 6, 3)},        # Yellow rim — welding spark
        "specular": {"color": (1.0, 0.90, 0.70), "energy": 600, "size": 0.2, "location": (0, 0, 8)},    # Warm white top
    },
    "harmonic_collective": {
        "key": {"color": (0.50, 0.70, 1.0), "energy": 3000, "size": 0.5, "location": (-4, -3, 6)},      # Cool blue — sleek machine
        "fill": {"color": (0.85, 0.87, 0.90), "energy": 700, "size": 1.0, "location": (3, 2, 2)},       # Clean white fill
        "rim": {"color": (0.65, 0.75, 0.95), "energy": 2500, "size": 0.3, "location": (1, 6, 3)},       # Silver-blue rim
        "specular": {"color": (0.90, 0.92, 1.0), "energy": 1000, "size": 0.2, "location": (0, 0, 8)},   # Bright white top
    },
    "chrono_revenants": {
        "key": {"color": (1.0, 0.80, 0.40), "energy": 3000, "size": 0.5, "location": (-4, -3, 6)},      # Warm gold — aged bronze
        "fill": {"color": (0.30, 0.75, 0.75), "energy": 500, "size": 1.0, "location": (3, 2, 2)},       # Teal fill — temporal decay
        "rim": {"color": (0.85, 0.90, 0.45), "energy": 2500, "size": 0.3, "location": (1, 6, 3)},       # Gold-green rim
        "specular": {"color": (1.0, 0.95, 0.80), "energy": 800, "size": 0.2, "location": (0, 0, 8)},    # Warm white top
    },
    "void_corsairs": {
        "key": {"color": (0.50, 0.40, 0.90), "energy": 3500, "size": 0.5, "location": (-4, -3, 6)},     # Purple-blue — stealth void
        "fill": {"color": (0.80, 0.82, 0.95), "energy": 400, "size": 1.0, "location": (3, 2, 2)},       # Cool white fill (minimal)
        "rim": {"color": (0.55, 0.65, 0.95), "energy": 2200, "size": 0.3, "location": (1, 6, 3)},       # Silver rim — edge catch
        "specular": {"color": (0.80, 0.75, 1.0), "energy": 700, "size": 0.2, "location": (0, 0, 8)},    # Lavender top
    },
}

FACTION_DEFAULT = "iron_directorate"

# =============================================================================
# ARG PARSING
# =============================================================================

def parse_args():
    """Parse --engine, --no-depth, --no-normal, --fast, --samples, --faction, --anim from sys.argv after --"""
    args = []
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1:]
    
    global RENDER_ENGINE, OUTPUT_DEPTH, OUTPUT_NORMAL, DEFAULT_SAMPLES, CURRENT_FACTION
    global FACTION_DEFAULT, ANIM_FILTER
    
    selected_faction = FACTION_DEFAULT
    ANIM_FILTER = None  # None = all; comma-separated names to limit (e.g. "idle,walk")
    
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
        elif args[i] == "--faction" and i + 1 < len(args):
            val = args[i + 1].lower()
            if val in FACTION_LIGHTING:
                selected_faction = val
                log(f"Faction lighting: {val}")
            else:
                log(f"WARNING: Unknown faction '{val}', using default ({FACTION_DEFAULT})")
            i += 2
        elif args[i] == "--anim" and i + 1 < len(args):
            ANIM_FILTER = set(a.strip() for a in args[i + 1].split(","))
            log(f"Animation filter: {sorted(ANIM_FILTER)}")
            i += 2
        else:
            i += 1
    
    return selected_faction

# =============================================================================
# LOGGING
# =============================================================================


def _query_free_vram_mib():
    """Best-effort free VRAM probe (NVIDIA via nvidia-smi). None = unknown."""
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return int(out.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def adaptive_samples(requested: int) -> int:
    """Halve samples while the desktop headroom is tight (VRAM governor)."""
    free = _query_free_vram_mib()
    if free is None:
        return requested
    need = VRAM_RESERVE_MIB + 1024  # working set estimate for these small scenes
    samples = requested
    while free < need and samples > 32:
        samples = max(32, samples // 2)
        need -= 512
    if samples != requested:
        log(f"VRAM governor: free={free}MiB reserve={VRAM_RESERVE_MIB}MiB -> samples {requested} -> {samples}")
    else:
        log(f"VRAM governor: free={free}MiB reserve={VRAM_RESERVE_MIB}MiB -> samples {requested} unchanged")
    return samples


def log(msg: str):
    print(f"[render_8dir_v2] {msg}")

# Parse args and set faction (must be after log() definition)
CURRENT_FACTION = parse_args()

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
    # Lock sensor fit to HORIZONTAL so ortho_scale is always the world WIDTH shown and
    # the world height = ortho_scale * (RENDER_H/RENDER_W). The default AUTO makes
    # ortho_scale the height in portrait frames, which inverted our framing math.
    cam_data.sensor_fit = 'HORIZONTAL'
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
# LIGHTING — PBR TUNED, FACTION-AWARE
# =============================================================================

def setup_lighting(faction="iron_directorate", size_factor=1.0):
    """Miniature-style 4-point grimdark lighting with hard shadows.

    Accepts a faction parameter to apply faction-specific colour temperatures
    and energy levels. Falls back to iron_directorate (default) for unknown
    factions.

    Tuned for Warhammer 40K miniature photography:
    - Small, bright lights create sharp shadow lines (not soft/gradient)
    - Strong rim light picks out armour edge details
    - High key-to-fill ratio for dramatic contrast (10:1)
    - Per-faction colour temperatures enforce visual identity (see FACTION_LIGHTING)
    """
    faction = faction.lower()
    if faction not in FACTION_LIGHTING:
        log(f"WARNING: Unknown faction '{faction}', using default ({FACTION_DEFAULT})")
        faction = FACTION_DEFAULT
    
    profile = FACTION_LIGHTING[faction]
    
    # Remove existing lights
    for obj in list(bpy.data.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)
    
    key_cfg = profile["key"]
    fill_cfg = profile["fill"]
    rim_cfg = profile["rim"]
    spec_cfg = profile["specular"]

    # Model-scale-invariant lighting: scale light positions by size_factor and energies by
    # size_factor^2 (inverse-square) so any mesh at any unit scale is lit correctly. The
    # fixed locations/energies are tuned for a ~1.5-diagonal reference model; a 16-unit
    # base mesh gets lights pushed out and powered up proportionally.
    sf = size_factor
    e2 = sf * sf
    def _loc(c): return (c[0]*sf, c[1]*sf, c[2]*sf)

    # SUN lights use irradiance (W/m^2) — distance-invariant, so NO size-factor energy
    # scaling. AREA lights use watts and need e2 scaling for inverse-square at distance.
    def _en(cfg):
        return cfg["energy"] if cfg.get("type", "AREA") == "SUN" else cfg["energy"] * e2

    key = create_light("KEY", color=key_cfg["color"], energy=_en(key_cfg),
                       location=_loc(key_cfg["location"]), size=key_cfg["size"],
                       light_type=key_cfg.get("type", "AREA"))
    fill = create_light("FILL", color=fill_cfg["color"], energy=_en(fill_cfg),
                        location=_loc(fill_cfg["location"]), size=fill_cfg["size"],
                        light_type=fill_cfg.get("type", "AREA"))
    rim = create_light("RIM", color=rim_cfg["color"], energy=_en(rim_cfg),
                       location=_loc(rim_cfg["location"]), size=rim_cfg["size"],
                       light_type=rim_cfg.get("type", "AREA"))
    spec = create_light("SPECULAR", color=spec_cfg["color"], energy=_en(spec_cfg),
                        location=_loc(spec_cfg["location"]), size=spec_cfg["size"],
                        light_type=spec_cfg.get("type", "AREA"))

    # Camera-relative lighting: store each light's base world location so render_direction_anim
    # can orbit them around Z with the rig and re-aim at the origin. This keeps every
    # direction evenly lit (Dawn-of-War style) instead of the model's front being back-lit
    # in some directions. Lights stay in world space (no parenting) to avoid local-rotation
    # complications.
    _store_light_base_transforms([key, fill, rim, spec])

    log(f"Lighting: {faction} (key={key_cfg['energy']}W {key_cfg['color']}, "
        f"fill={fill_cfg['energy']}W, rim={rim_cfg['energy']}W, specular={spec_cfg['energy']}W)")


_LIGHT_BASE = None
def _store_light_base_transforms(lights):
    global _LIGHT_BASE
    _LIGHT_BASE = [(lt, lt.matrix_world.copy()) for lt in lights]


def _orbit_lights_for_direction(dangle_deg: float):
    """Rotate every stored light around world Z by the direction angle, then re-aim at the
    origin. Called once per direction so the model is lit from the same camera-relative
    angles in all 8 views."""
    if not _LIGHT_BASE:
        return
    ang = math.radians(dangle_deg)
    rot = mathutils.Matrix.Rotation(ang, 4, 'Z')
    origin = mathutils.Vector((0, 0, 0))
    for lt, base in _LIGHT_BASE:
        m = rot @ base
        lt.matrix_world = m
        direction = origin - lt.matrix_world.translation
        if direction.length > 1e-6:
            lt.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

def create_light(name: str, color: tuple, energy: float, location: tuple, size: float = 0.5, light_type: str = "AREA"):
    light_data = bpy.data.lights.new(name=name, type=light_type)
    light_data.color = color
    light_data.energy = energy
    if light_type == "AREA":
        light_data.size = size  # Small size = hard shadows for miniature look
    elif light_type == "SUN":
        light_data.angle = size  # sun angular size (radians); small = hard shadows

    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = location
    # Point at origin (for SUN, this sets the direction; location distance is irrelevant)
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

    # Colour management: force a consistent view transform regardless of the input
    # blend (the CC0 base mesh ships with view_transform=Standard/Filmic which renders
    # mids dark/flat; our generated units use AgX which is brighter with readable mids).
    try:
        scene.view_settings.view_transform = 'AgX'
    except Exception:
        scene.view_settings.view_transform = 'Filmic'  # fallback if AgX unavailable
    scene.view_settings.exposure = 1.0
    scene.view_settings.look = 'None'
    scene.view_settings.use_curve_mapping = False
    scene.sequencer_colorspace_settings.name = 'sRGB'
    log(f"Colour mgmt: view_transform={scene.view_settings.view_transform} exposure={scene.view_settings.exposure} device={scene.display_settings.display_device}")

    # Dark world background so the input blend's own world (which can be a bright ambient
    # that flattens contrast) doesn't lift shadows. With film_transparent, the background
    # renders transparent for the sprite alpha, but the world shader still contributes
    # ambient illumination to surfaces — a near-black world means only the 4 rigged
    # lights define shading, so the key:fill ratio actually reads as tonal contrast.
    world = scene.world or bpy.data.worlds.new("IsoWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background") or world.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.05, 0.055, 0.065, 1.0)
    bg.inputs["Strength"].default_value = 0.25   # ambient lifts the shadow side so the silhouette reads against the black BG
    if RENDER_ENGINE == "CYCLES":
        scene.cycles.sample_clamp_indirect = 0.0  # don't clamp the key
    
    if RENDER_ENGINE == "CYCLES":
        # Cycles settings for quality + reasonable speed
        _req = DEFAULT_SAMPLES
        if os.environ.get("IOA_VRAM_RESERVE_MIB"):
            try: globals()['VRAM_RESERVE_MIB'] = int(os.environ["IOA_VRAM_RESERVE_MIB"])
            except ValueError: pass
        scene.cycles.samples = adaptive_samples(DEFAULT_SAMPLES)
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        RENDER_META["view_transform"] = scene.view_settings.view_transform
        RENDER_META["samples"] = scene.cycles.samples
        RENDER_META["denoiser"] = "OPENIMAGEDENOISE"
        # Try GPU (OptiX preferred for RTX, fall back to CUDA then CPU).
        try:
            preferences = bpy.context.preferences.addons['cycles'].preferences
            # Pick the best available compute backend.
            for ctype in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
                try:
                    preferences.compute_device_type = ctype
                    preferences.get_devices()
                    if any(d.type in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL') for d in preferences.devices):
                        break
                except Exception:
                    continue
            # Enable GPU devices, disable CPU (pure GPU render for speed).
            has_gpu = False
            for d in preferences.devices:
                if d.type in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI', 'METAL'):
                    d.use = True
                    has_gpu = True
                else:
                    d.use = False
            if has_gpu:
                scene.cycles.device = 'GPU'
                log(f"Cycles device: GPU ({preferences.compute_device_type})")
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
    _orbit_lights_for_direction(dangle)
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
    total_frames = frame_end - frame_start + 1
    import time as _time
    import sys as _sys
    dir_start = _time.time()
    for frame in range(frame_start, frame_end + 1):
        # Pause mechanism: check for a pause file between frames. Create it with
        # `touch /tmp/render_pause` to reclaim GPU; remove it to resume.
        pause_file = "/tmp/render_pause"
        if os.path.exists(pause_file):
            _sys.stderr.write(f"  [PAUSED] touch {pause_file} created — waiting (rm to resume)...\n")
            _sys.stderr.flush()
            while os.path.exists(pause_file):
                _time.sleep(3)
            _sys.stderr.write(f"  [RESUMED]\n")
            _sys.stderr.flush()
        
        scene.frame_set(frame)
        rel_frame = frame - frame_start + 1
        filename = f"frame_{rel_frame:02d}.png"
        filepath = os.path.join(anim_dir, filename)
        scene.render.filepath = filepath
        
        # Print BEFORE render so user sees what's happening during the (blocking) render
        _sys.stderr.write(f"  [{rel_frame}/{total_frames}] Rendering {anim_name}/{dlabel} {filename}...\n")
        _sys.stderr.flush()
        
        frame_start_time = _time.time()
        try:
            bpy.ops.render.render(write_still=True)
        except RuntimeError as rend_err:
            # Transient desktop VRM spikes (browser, video) -- retry once at half
            # samples before giving up; recorded in the log for the QC trail.
            log(f"Render failed ({rendErr}); retrying at half samples")
            scene.cycles.samples = max(32, scene.cycles.samples // 2)
            bpy.ops.render.render(write_still=True)
        frame_elapsed = _time.time() - frame_start_time
        files.append(filepath)
        
        # Print AFTER render with timing
        dir_elapsed = _time.time() - dir_start
        _sys.stderr.write(f"  [{rel_frame}/{total_frames}] DONE {filename} in {frame_elapsed:.1f}s "
                          f"(dir: {dir_elapsed:.0f}s total)\n")
        _sys.stderr.flush()
    
    total = frame_end - frame_start + 1
    dir_total = _time.time() - dir_start
    log(f"Rendered {anim_name}/{dlabel}: {total} frames in {dir_total:.0f}s @ {RENDER_W}x{RENDER_H} -> {anim_dir}")
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
                # Bilinear (not Lanczos) preserves hard painted lines across the 3x
                # downscale; Lanczos interpolates 1px panel lines into muddy gradients.
                # Then an unsharp mask restores high-frequency Sobel boundaries.
                small = img.resize((FRAME_W, FRAME_H), Image.BILINEAR)
                small = small.filter(ImageFilter.UnsharpMask(radius=1.0, percent=150, threshold=3))
                small.save(filepath, "PNG")
                count += 1

    log(f"Downscaled {count} frames from {RENDER_W}x{RENDER_H} to {FRAME_W}x{FRAME_H} (bilinear + unsharp mask)")

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
        # Reproducibility contract (rendering standards D4): the exact look/tech
        # fingerprint of this run. A manifest without these is not re-runnable.
        "vram_reserve_mib": VRAM_RESERVE_MIB,
        "render_meta": dict(RENDER_META),
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
    
    # Auto-launch the web dashboard on port 8083 if not already running
    import socket as _socket
    import subprocess as _subproc
    _dash_port = 8083
    _dash_running = False
    try:
        _s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _s.settimeout(0.5)
        _s.connect(("127.0.0.1", _dash_port))
        _s.close()
        _dash_running = True
    except:
        _dash_running = False
    if not _dash_running:
        _dash_script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "queue_dashboard.py")
        if os.path.exists(_dash_script):
            _subproc.Popen(["python3", _dash_script, "--port", str(_dash_port)],
                          stdout=_subproc.DEVNULL, stderr=_subproc.DEVNULL)
            log(f"Dashboard launched on http://localhost:{_dash_port}")
    
    out_dir = ensure_output_dir(blend_path)
    log(f"Output directory: {out_dir}")
    
    # Compute model bounds
    min_x, max_x, min_y, max_y, min_z, max_z = compute_scene_bounds()
    bbox_width = max_x - min_x
    bbox_height = max_z - min_z
    bbox_depth = max_y - min_y
    bbox_diagonal = math.sqrt(bbox_width**2 + bbox_height**2 + bbox_depth**2)

    log(f"Scene bounds: W={bbox_width:.1f} H={bbox_height:.1f} D={bbox_depth:.1f} diag={bbox_diagonal:.1f}")

    # Lock framing across all 8 directions. The ortho frame is portrait (RENDER_H/RENDER_W
    # tall), so the world-height shown = ortho_scale * aspect. The model's projected
    # width varies as it orbits (max = the horizontal diagonal sqrt(W^2+D^2)); using that
    # guarantees no direction clips horizontally, and bbox_height/aspect guarantees no
    # vertical clip. Fill ~85% of the tightest dimension for a consistent, non-jumping
    # frame across N/NE/E/.../NW.
    aspect = RENDER_H / RENDER_W  # 1.333 for 1152x1536 / 384x512
    max_proj_width = math.sqrt(bbox_width**2 + bbox_depth**2)
    ortho_scale = max(max_proj_width, bbox_height / aspect) / 0.85
    ortho_scale = max(ortho_scale, 0.01)  # min clamp (was 1.0 — made small meshes render as specks)
    target_z = min_z + bbox_height / 2.0
    
    setup_render_settings()
    create_rig(ortho_scale, target_z, bbox_diagonal)
    setup_lighting(faction=CURRENT_FACTION, size_factor=bbox_diagonal / 1.5)
    
    animations = scan_animations()
    
    # Calculate total frames for progress reporting
    total_render_frames = 0
    for anim_name, anim_info in animations.items():
        if ANIM_FILTER and anim_name not in ANIM_FILTER:
            continue
        fs, fe = anim_info["frames"]
        total_render_frames += (fe - fs + 1) * len(DIRECTIONS)
    active_anims = [n for n in animations if (not ANIM_FILTER or n in ANIM_FILTER)]
    log(f"Render queue: {len(active_anims)} anims × {len(DIRECTIONS)} dirs = {total_render_frames} frames total")
    log(f"Pause mechanism: touch /tmp/render_pause to pause, rm to resume")
    
    import time as _time
    render_start = _time.time()
    frame_counter = 0
    all_rendered_files = []
    for anim_name, anim_info in animations.items():
        if ANIM_FILTER and anim_name not in ANIM_FILTER:
            log(f"Skipping anim '{anim_name}' (filter)")
            continue
        frame_start, frame_end = anim_info["frames"]
        armature = anim_info.get("armature")
        action = anim_info.get("action")
        nla_strip = anim_info.get("nla_strip")
        anim_frame_count = (frame_end - frame_start + 1) * len(DIRECTIONS)
        log(f"Starting anim '{anim_name}': {anim_frame_count} frames across {len(DIRECTIONS)} directions")
        for dlabel, dangle in DIRECTIONS:
            files = render_direction_anim(dlabel, dangle, anim_name, 
                                          frame_start, frame_end, out_dir,
                                          armature_obj=armature, action=action,
                                          nla_strip=nla_strip)
            all_rendered_files.extend(files)
            frame_counter += len(files)
            elapsed = _time.time() - render_start
            remaining_frames = total_render_frames - frame_counter
            est_per_frame = elapsed / max(frame_counter, 1)
            est_remaining = est_per_frame * remaining_frames
            log(f"Progress: {frame_counter}/{total_render_frames} frames done "
                f"({frame_counter*100//max(total_render_frames,1)}%) — "
                f"elapsed: {elapsed:.0f}s, est remaining: {est_remaining:.0f}s")
    
    total_elapsed = _time.time() - render_start
    log(f"All rendering complete: {frame_counter} frames in {total_elapsed:.0f}s "
        f"({total_elapsed/max(frame_counter,1):.1f}s/frame average)")
    
    # Downscale in-place (if PIL available in Blender's Python)
    downscale_all_renders(out_dir)
    
    # Build simple frames dict for manifest
    manifest_anims = {name: info["frames"] for name, info in animations.items()}
    generate_manifest(out_dir, manifest_anims, all_rendered_files)
    log("Render complete. Proceed to palette quantization (batch_pixelate.py).")

if __name__ == "__main__":
    main()