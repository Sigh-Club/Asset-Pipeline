"""Blender (EEVEE) 8-direction renderer for a posed DoW WHM OBJ.

The DoW chain (whm_animdata -> pose_whm) exports a posed, coherent OBJ; this
renders the IoA sprite contract: 8 directions, 384x512, transparent, ortho,
3-point miniature lighting. Re-skin via recolour_atlas.py.

blender -b --python tools/dow/render_dow_unit.py -- \
  --obj /tmp/sm_idle.obj --atlas /tmp/space_marine_unit_iron.png \
  --out /tmp/sm_8dir --hide banner --res 512
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Euler, Vector


def args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument('--obj', required=True)
    ap.add_argument('--atlas', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--hide', default='', help='comma-separated object-name substrings to hide')
    ap.add_argument('--res', type=int, default=512)
    ap.add_argument('--width', type=int, default=384)
    ap.add_argument('--height', type=int, default=512)
    ap.add_argument('--tint', default=None, help='r,g,b multiply tint')
    return ap.parse_args(argv)


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    bpy.ops.wm.obj_import(filepath=a.obj)
    meshes = [o for o in scene.objects if o.type == 'MESH']
    hidden = [s for s in a.hide.split(',') if s]
    for o in meshes:
        if any(s in o.name for s in hidden):
            o.hide_render = True
        o.rotation_euler = Euler((math.radians(90), 0, 0))

    img = bpy.data.images.load(a.atlas)
    for m in bpy.data.materials:
        m.use_nodes = True
        nt = m.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf:
            continue
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        tex.interpolation = 'Linear'
        if a.tint:
            r, g, b = (float(x) for x in a.tint.split(','))
            mix = nt.nodes.new('ShaderNodeMix')
            mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'
            mix.inputs['Factor'].default_value = 0.35
            mix.inputs['B'].default_value = (r, g, b, 1)
            nt.links.new(tex.outputs['Color'], mix.inputs['A'])
            nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])
        else:
            nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        bsdf.inputs['Roughness'].default_value = 0.62
        bsdf.inputs['Metallic'].default_value = 0.15

    bpy.context.view_layer.update()
    mn = Vector((1e9, 1e9, 1e9)); mx = Vector((-1e9, -1e9, -1e9))
    for o in meshes:
        if o.hide_render:
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mn = Vector(map(min, mn, w)); mx = Vector(map(max, mx, w))
    center = (mn + mx) / 2
    height = mx.z - mn.z

    cam_data = bpy.data.cameras.new('cam'); cam_data.type = 'ORTHO'
    cam_data.ortho_scale = height * 1.12
    cam = bpy.data.objects.new('cam', cam_data); scene.collection.objects.link(cam)
    cam.location = (center.x, center.y - 10, center.z)
    cam.rotation_euler = Euler((math.radians(90), 0, 0))
    scene.camera = cam

    def area(name, loc, energy, size, colour=(1, 1, 1)):
        d = bpy.data.lights.new(name, 'AREA'); d.energy = energy; d.size = size; d.color = colour
        o = bpy.data.objects.new(name, d); scene.collection.objects.link(o)
        o.location = Vector(loc)
        o.rotation_euler = (center - o.location).to_track_quat('-Z', 'Y').to_euler()

    area('key', (center.x - 2.5, center.y - 4, center.z + 3.5), 900, 3.0, (1.0, 0.95, 0.88))
    area('fill', (center.x + 3.5, center.y - 3, center.z + 1.5), 300, 4.0, (0.75, 0.82, 1.0))
    area('rim', (center.x + 2.0, center.y + 4, center.z + 3.0), 700, 2.0, (0.9, 0.95, 1.0))

    scene.world = bpy.data.worlds.new('W'); scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 0.12
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = a.width
    scene.render.resolution_y = a.height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.view_settings.view_transform = 'Standard'

    # Direction labels match the game atlas: S = facing the camera.
    DIRS = [('S', 0), ('SE', 45), ('E', 90), ('NE', 135), ('N', 180), ('NW', 225), ('W', 270), ('SW', 315)]
    for label, deg in DIRS:
        for o in meshes:
            o.rotation_euler = Euler((math.radians(90), 0, math.radians(deg)))
        bpy.context.view_layer.update()
        scene.render.filepath = os.path.join(a.out, f'{label}.png')
        bpy.ops.render.render(write_still=True)
        print('WROTE', scene.render.filepath)
    print('BOUNDS', tuple(round(v, 2) for v in mn), tuple(round(v, 2) for v in mx), 'H', round(height, 2))


main()
