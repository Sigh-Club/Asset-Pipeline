# Import the extracted DoW ork OBJ into Blender, texture it with the authentic
# atlases, render orthographic front (facing us), for the pixel pipeline.
#
#   blender -b -P blender_ork_import.py -- --obj ork_models/boyz/boyz.obj \
#           --out render_boyz_authentic.png [--tint "0.55,0.10,0.08"]
import argparse
import glob
import os
import sys

import bpy
from math import radians
from mathutils import Euler

ATLAS_DIR = os.environ.get("DOW_ATLAS_DIR",
                           "/home/talzanar/Downloads/mtcde_masters/w40k/ork_pngs")


def find_atlas(stem):
    hits = glob.glob(ATLAS_DIR + "/%s__*mip0.png" % stem)
    return sorted(hits)[0] if hits else None  # page 0 = diffuse


def texture_material(mat, atlas_path):
    mat.use_nodes = True
    mat.blend_method = "OPAQUE"
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(atlas_path)
    tex.interpolation = "Closest"  # keep texels crisp for the pixel look
    tex.image.alpha_mode = "NONE"  # DXT1 1-bit alpha would blank the render
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Alpha"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.9
    bsdf.inputs["Specular IOR Level"].default_value = 0.1


def tint_object(obj, colour):
    """Klan tint: multiply the material's base colour (team-colour pass)."""
    for slot in obj.material_slots:
        m = slot.material
        if not m or not m.use_nodes:
            continue
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        mix = m.node_tree.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 0.45
        mix.inputs["B"].default_value = (*colour, 1.0)
        # base color texel * klan colour
        links = m.node_tree.links
        for l in list(links):
            if l.to_node == bsdf and l.to_socket.name == "Base Color":
                links.new(l.from_socket, mix.inputs["A"])
        links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--obj", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tint", default=None, help="klan tint r,g,b 0..1")
    ap.add_argument("--res", type=int, default=512)
    a = ap.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    bpy.ops.wm.obj_import(filepath=a.obj)
    # texture every material from the matching extracted atlas
    for mat in bpy.data.materials:
        stem = mat.name.strip()
        atlas = find_atlas(stem)
        if atlas:
            texture_material(mat, atlas)
        else:
            print("no atlas for material:", stem)

    TINT_PARTS = {"boyz_legs", "ork_flag", "ork_flag_pole"}  # cloth/banner
    if a.tint:
        r, g, b = [float(x) for x in a.tint.split(",")]
        for ob in bpy.context.scene.objects:
            if ob.type == "MESH" and ob.name in TINT_PARTS:
                tint_object(ob, (r, g, b))

    # lights + camera (front, facing us)
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = a.res
    scene.render.resolution_y = a.res
    scene.view_settings.view_transform = "Standard"
    scene.world = bpy.data.worlds.new("W")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (1, 1, 1, 1)
    bg.inputs[1].default_value = 0.6

    def light(name, loc, energy, colour=(1, 1, 1)):
        bpy.ops.object.light_add(type="AREA", location=loc)
        lo = bpy.context.active_object
        lo.name = name
        lo.data.energy = energy
        lo.data.color = colour
        lo.data.size = 2.0
        return lo

    key = light("key", (1.2, -2.4, 2.6), 240)
    key.rotation_euler = Euler((radians(52), 0, radians(28)))
    fill = light("fill", (-2.0, -1.6, 1.4), 90, (0.85, 0.90, 1.0))
    fill.rotation_euler = Euler((radians(65), 0, radians(-55)))
    rim = light("rim", (0.4, 2.2, 2.4), 140, (1.0, 0.95, 0.85))
    rim.rotation_euler = Euler((radians(-35), 0, radians(180)))

    # frame the model bounds
    bpy.context.view_layer.update()
    import mathutils
    mn = mathutils.Vector((1e9, 1e9, 1e9))
    mx = mathutils.Vector((-1e9, -1e9, -1e9))
    for ob in scene.objects:
        if ob.type == "MESH":
            for corner in ob.bound_box:
                wc = ob.matrix_world @ mathutils.Vector(corner)
                mn = mathutils.Vector(map(min, mn, wc))
                mx = mathutils.Vector(map(max, mx, wc))
    centre = (mn + mx) / 2
    size = max((mx - mn).x, (mx - mn).z) * 1.25

    bpy.ops.object.camera_add(location=(centre.x, centre.y - 6.0, centre.z),
                              rotation=Euler((radians(90), 0, 0)))
    cam = bpy.context.active_object
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(1.0, size)
    scene.camera = cam

    scene.render.filepath = a.out
    bpy.ops.render.render(write_still=True)
    print("wrote", a.out)


main()
