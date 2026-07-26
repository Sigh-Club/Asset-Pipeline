#!/usr/bin/env python3
"""
tile_generator.py — Procedural isometric tile generation for IoA.

Generates Blender models for isometric ground tiles, walls, and props.
Each tile is a 96×48 (width × depth) isometric footprint at 96×128 canvas.

Tile types:
  - ground: Floor tiles (concrete, dirt, metal grating, etc.)
  - wall: Vertical walls (straight, corner, T-junction, end cap)
  - elevation: Raised platforms (+24px per level)
  - debris: Rubble, cover objects, crates
  - decoration: Pipes, vents, cables, signs

Usage:
    blender --background --python tile_generator.py -- --tile-set urban_concrete --output assets/units/tiles/urban_concrete/
    blender --background --python tile_generator.py -- --tile-set industrial_metal --output assets/units/tiles/industrial_metal/ --all

Output:
    assets/units/tiles/<tile_set>/model/<tile_set>.blend (single file with all tile variations)
    assets/units/tiles/<tile_set>/model/render/raw/ (per-tile renders after render step)
"""

import bpy
import os
import sys
import math
import json

# =============================================================================
# CONFIGURATION
# =============================================================================

TILE_FOOTPRINT_W = 0.48  # Blender units (matches 96px at 200px/BU scale)
TILE_FOOTPRINT_D = 0.24  # Blender units (matches 48px)
TILE_HEIGHT = 0.24       # Base tile height
ELEVATION_STEP = 0.12    # +24px per elevation level
WALL_HEIGHT = 0.48       # 96px wall height (matches character frame)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
MATERIAL_BLEND = os.path.join(PROJECT_ROOT, "assets", "materials", "grimdark_materials.blend")


# =============================================================================
# MATERIALS
# =============================================================================

def load_materials():
    """Load grimdark materials from the material library."""
    if not os.path.exists(MATERIAL_BLEND):
        print(f"WARNING: Material library not found at {MATERIAL_BLEND}")
        print("Run 'pipeline materials generate' first.")
        return {}

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


# =============================================================================
# TILE GEOMETRY
# =============================================================================

def create_tile_base(name, mats, mat_name, width=TILE_FOOTPRINT_W, depth=TILE_FOOTPRINT_D, height=TILE_HEIGHT):
    """Create a base tile platform with bevel + subsurf."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, height / 2))
    tile = bpy.context.active_object
    tile.name = name
    for v in tile.data.vertices:
        v.co.x *= width / 2
        v.co.y *= depth / 2
        v.co.z *= height / 2

    if mat_name in mats:
        tile.data.materials.clear()
        tile.data.materials.append(mats[mat_name])

    # Bevel for edge detail
    bevel = tile.modifiers.new(name="Bevel", type='BEVEL')
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(30)
    bevel.width = 0.005
    bevel.segments = 2

    # Subsurf for smooth appearance
    subsurf = tile.modifiers.new(name="Subsurf", type='SUBSURF')
    subsurf.levels = 1
    subsurf.render_levels = 2

    simple_uv_unwrap(tile)
    return tile


def create_wall_straight(name, mats, mat_name, length=TILE_FOOTPRINT_W):
    """Create a straight wall segment."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, WALL_HEIGHT / 2))
    wall = bpy.context.active_object
    wall.name = name
    for v in wall.data.vertices:
        v.co.x *= length / 2
        v.co.y *= 0.04  # thin wall
        v.co.z *= WALL_HEIGHT / 2

    if mat_name in mats:
        wall.data.materials.clear()
        wall.data.materials.append(mats[mat_name])

    bevel = wall.modifiers.new(name="Bevel", type='BEVEL')
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(30)
    bevel.width = 0.003
    bevel.segments = 2
    simple_uv_unwrap(wall)
    return wall


def create_crate(name, mats, mat_name, size=0.12):
    """Create a destructible crate prop."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, size / 2))
    crate = bpy.context.active_object
    crate.name = name
    for v in crate.data.vertices:
        v.co.x *= size
        v.co.y *= size
        v.co.z *= size

    if mat_name in mats:
        crate.data.materials.clear()
        crate.data.materials.append(mats[mat_name])

    bevel = crate.modifiers.new(name="Bevel", type='BEVEL')
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(30)
    bevel.width = 0.008
    bevel.segments = 2
    simple_uv_unwrap(crate)
    return crate


def create_barrel(name, mats, mat_name, radius=0.06, height=0.10):
    """Create a cylindrical barrel prop."""
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=height, location=(0, 0, height / 2))
    barrel = bpy.context.active_object
    barrel.name = name

    if mat_name in mats:
        barrel.data.materials.clear()
        barrel.data.materials.append(mats[mat_name])

    bevel = barrel.modifiers.new(name="Bevel", type='BEVEL')
    bevel.limit_method = 'ANGLE'
    bevel.angle_limit = math.radians(30)
    bevel.width = 0.003
    bevel.segments = 2
    simple_uv_unwrap(barrel)
    return barrel


def create_elevated_platform(name, mats, mat_name, levels=1):
    """Create a raised platform (+24px per level)."""
    h = TILE_HEIGHT + ELEVATION_STEP * levels
    return create_tile_base(name, mats, mat_name, height=h)


# =============================================================================
# TILE SET DEFINITIONS
# =============================================================================

TILE_SETS = {
    "urban_concrete": {
        "description": "Urban concrete tiles — cracked pavement, manholes, gutters",
        "ground": [
            {"name": "concrete_base", "material": "MAT_GrimdarkMetal"},
            {"name": "concrete_cracked", "material": "MAT_ChaosRust"},
            {"name": "concrete_manhole", "material": "MAT_GrimdarkMetal"},
        ],
        "walls": [
            {"name": "concrete_wall_straight", "material": "MAT_GrimdarkMetal"},
            {"name": "concrete_wall_corner", "material": "MAT_GrimdarkMetal"},
        ],
        "props": [
            {"name": "concrete_barricade", "material": "MAT_GrimdarkMetal", "type": "crate"},
            {"name": "concrete_barrel", "material": "MAT_ChaosRust", "type": "barrel"},
        ],
    },
    "industrial_metal": {
        "description": "Industrial metal — grating, pipes, riveted plates",
        "ground": [
            {"name": "metal_plate", "material": "MAT_GrimdarkMetal"},
            {"name": "metal_grating", "material": "MAT_GrimdarkMetal"},
            {"name": "metal_rusty", "material": "MAT_ChaosRust"},
        ],
        "walls": [
            {"name": "metal_wall_straight", "material": "MAT_GrimdarkMetal"},
            {"name": "metal_wall_corner", "material": "MAT_GrimdarkMetal"},
        ],
        "props": [
            {"name": "metal_crate", "material": "MAT_GrimdarkMetal", "type": "crate"},
            {"name": "metal_drum", "material": "MAT_ChaosRust", "type": "barrel"},
        ],
    },
    "cinderborn_ruin": {
        "description": "Cinderborn ruins — blasted stone, ritual markings, warp corrosion",
        "ground": [
            {"name": "ruin_stone", "material": "MAT_ChaosRust"},
            {"name": "ruin_ash", "material": "MAT_GrimdarkLeather"},
            {"name": "ruin_ritual_circle", "material": "MAT_ChaosRust"},
        ],
        "walls": [
            {"name": "ruin_wall", "material": "MAT_ChaosRust"},
        ],
        "props": [
            {"name": "ruin_pillar", "material": "MAT_ChaosRust", "type": "crate"},
        ],
    },
}


# =============================================================================
# UV HELPERS
# =============================================================================

def simple_uv_unwrap(obj):
    """Smart UV project for tile geometry."""
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.select_set(False)


def clear_scene():
    """Remove all objects and data from scene."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)


# =============================================================================
# RENDER SETUP (simple top-down isometric for tiles)
# =============================================================================

def setup_tile_camera():
    """Set up an orthographic isometric camera for tile rendering."""
    # Remove existing cameras
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            bpy.data.objects.remove(obj, do_unlink=True)

    cam_data = bpy.data.cameras.new(name="TileCamera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 0.6  # Fill frame with one tile
    cam_data.clip_start = 0.01
    cam_data.clip_end = 100.0

    camera = bpy.data.objects.new(name="TileCamera", object_data=cam_data)
    bpy.context.scene.collection.objects.link(camera)

    # Isometric angle: 30° elevation, looking at origin
    camera.location = (0.5, -1.0, 1.0)
    camera.rotation_euler = (math.radians(60), 0, math.radians(45))

    bpy.context.scene.camera = camera
    return camera


def setup_tile_lighting():
    """Lighting for tile renders — flat, even, with slight directional emphasis."""
    for obj in list(bpy.data.objects):
        if obj.type == 'LIGHT':
            bpy.data.objects.remove(obj, do_unlink=True)

    # Overhead key — bright, slightly warm
    key = bpy.data.lights.new(name="TileKey", type="SUN")
    key.energy = 5.0
    key.angle = math.radians(5)
    key_obj = bpy.data.objects.new(name="TileKey", object_data=key)
    key_obj.rotation_euler = (math.radians(60), 0, math.radians(45))
    bpy.context.scene.collection.objects.link(key_obj)

    # Fill — cool blue from opposite side
    fill = bpy.data.lights.new(name="TileFill", type="SUN")
    fill.energy = 2.0
    fill.angle = math.radians(5)
    fill_obj = bpy.data.objects.new(name="TileFill", object_data=fill)
    fill_obj.rotation_euler = (math.radians(40), 0, math.radians(225))
    bpy.context.scene.collection.objects.link(fill_obj)


# =============================================================================
# MAIN
# =============================================================================

def parse_args():
    args = {}
    if "--" in sys.argv:
        idx = sys.argv.index("--")
        for i in range(idx + 1, len(sys.argv), 2):
            if i + 1 < len(sys.argv):
                key = sys.argv[i].lstrip("-")
                args[key] = sys.argv[i + 1]
    return args


def generate_tile_set(tile_set_name, output_dir):
    """Generate all tiles for a named tile set."""
    if tile_set_name not in TILE_SETS:
        print(f"Unknown tile set '{tile_set_name}'. Available: {list(TILE_SETS.keys())}")
        return False

    tile_set = TILE_SETS[tile_set_name]
    print(f"Generating tile set: {tile_set_name} — {tile_set['description']}")

    clear_scene()
    mats = load_materials()

    all_objects = []
    mat_name = "MAT_GrimdarkMetal"  # default fallback

    # Ground tiles
    print(f"  Ground tiles ({len(tile_set['ground'])}):")
    for tile_def in tile_set["ground"]:
        tile = create_tile_base(tile_def["name"], mats, tile_def["material"])
        tile.location.x = 0.6 * (len(all_objects) % 5)  # spread out
        tile.location.y = 0.6 * (len(all_objects) // 5)
        all_objects.append(tile)
        print(f"    {tile_def['name']} ({tile_def['material']})")

    # Walls
    print(f"  Walls ({len(tile_set['walls'])}):")
    for wall_def in tile_set["walls"]:
        wall = create_wall_straight(wall_def["name"], mats, wall_def["material"])
        wall.location.x = 0.6 * (len(all_objects) % 5)
        wall.location.y = 0.6 * (len(all_objects) // 5)
        all_objects.append(wall)
        print(f"    {wall_def['name']} ({wall_def['material']})")

    # Props
    print(f"  Props ({len(tile_set['props'])}):")
    for prop_def in tile_set["props"]:
        if prop_def["type"] == "crate":
            prop = create_crate(prop_def["name"], mats, prop_def["material"])
        elif prop_def["type"] == "barrel":
            prop = create_barrel(prop_def["name"], mats, prop_def["material"])
        else:
            continue
        prop.location.x = 0.6 * (len(all_objects) % 5)
        prop.location.y = 0.6 * (len(all_objects) // 5)
        all_objects.append(prop)
        print(f"    {prop_def['name']} ({prop_def['material']})")

    # Set up render
    setup_tile_camera()
    setup_tile_lighting()

    # Set render settings
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.render.resolution_x = 384
    scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True

    # Save blend
    os.makedirs(output_dir, exist_ok=True)
    blend_path = os.path.join(output_dir, f"{tile_set_name}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"\nSaved: {blend_path}")
    print(f"Objects: {len(all_objects)}")

    return True


def main():
    args = parse_args()
    tile_set = args.get("tile-set", "urban_concrete")
    output = args.get("output", os.path.join(PROJECT_ROOT, "assets", "units", "tiles", tile_set, "model"))

    success = generate_tile_set(tile_set, output)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
