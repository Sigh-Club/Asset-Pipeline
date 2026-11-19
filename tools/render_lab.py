#!/usr/bin/env python3
"""render_lab.py — render lab units in named poses, so the result is looked at, not inferred.

The numeric gates measure deformation from a bind; they cannot tell a shard pile from a body. This
renders each unit's bind pose and named action frames with a fixed camera, three-point light and
the unit's own materials, into `output/source_lab/renders/`.

Run inside Blender:
  blender -b -P tools/render_lab.py -- <lab dir> <out dir> [<action>:<frame>[:<view>] ...]

`<view>` is `full` (default, the whole body), `head` (close-up on the head bone), `weapon`
(close-up on the weapon bone) or `upper` (chest up). The close-ups are part of the gate: a head
that renders black and a weapon that is missing entirely both pass every numeric check.
"""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
lab = Path(argv[0])
out = Path(argv[1])
args = argv[2:]
only = []
while args and args[0].startswith("--unit="):
    only.append(args.pop(0).split("=", 1)[1])
shots = [s.split(":") for s in args] or [["idle", "1"]]
out.mkdir(parents=True, exist_ok=True)

# view -> (bone name substrings, frame height as a fraction of the body's bounding box)
VIEWS = {
    "full": ((), 1.0),
    "upper": (("spine", "pelvis"), 0.6),
    "head": (("head",), 0.32),
    "weapon": (("r weapon", "weapon", "r hand"), 0.3),
}


def weapon_box(dg):
    """Bounding box of the posed meshes that carry a weapon bone's weights, or None.

    Framing the weapon on its *bone* put the camera on the hand and cut the lasgun off at the
    muzzle: the weapon model is authored around the bone, not at it. The shipped weapon mesh is
    the one with a vertex group named after a weapon bone, so that mesh's own box is what the
    close-up frames.
    """
    import numpy as np
    points = []
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        # every mesh carries a vertex group for every bone (the add-on creates them all), so the
        # test is which bone the mesh's WEIGHT sits on, not which groups exist.
        weapon_groups = {g.index for g in ob.vertex_groups if "weapon" in g.name.lower()}
        if not weapon_groups:
            continue
        total = weapon_share = 0.0
        for v in ob.data.vertices:
            for g in v.groups:
                total += g.weight
                if g.group in weapon_groups:
                    weapon_share += g.weight
        if total <= 0 or weapon_share / total < 0.5:
            continue
        ev = ob.evaluated_get(dg)
        for v in ev.data.vertices:
            points.append(ev.matrix_world @ v.co)
    if not points:
        return None
    arr = np.array([list(p) for p in points])
    return arr.min(axis=0), arr.max(axis=0)


def clear():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def bone_point(arm, needles):
    """World position of the first pose bone whose name contains one of `needles`."""
    for needle in needles:
        for pb in arm.pose.bones:
            if needle in pb.name.lower():
                return arm.matrix_world @ pb.matrix.translation
    return None


def render(glb, action, frame, view, dest):
    clear()
    bpy.ops.object.empty_add(location=(0, 0, 0))
    bpy.context.view_layer.objects.active = bpy.context.object
    bpy.ops.import_scene.gltf(filepath=str(glb))
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None:
        print(f"RENDER {glb.name}: no armature")
        return
    if arm.animation_data is None:
        arm.animation_data_create()
    act = next((a for a in bpy.data.actions if a.name == action), None)
    if act is not None:
        arm.animation_data.action = act
        try:
            if arm.animation_data.action_slot is None and act.slots:
                arm.animation_data.action_slot = act.slots[0]
        except AttributeError:
            pass
    else:
        print(f"RENDER {glb.name}: no action {action!r} (actions: "
              f"{[a.name for a in bpy.data.actions]})")
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    # A robust bounding box: the shipped rigs carry single plates and robe hems that reach well
    # past the body, and a raw min/max frame puts the unit in a corner of the image (measured on
    # the chaos sorcerer, whose robe swings the box ~40 % past the figure). The 2nd-98th percentile
    # per axis frames the figure.
    points = []
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        ev = ob.evaluated_get(dg)
        for v in ev.data.vertices:
            points.append(ev.matrix_world @ v.co)
    if not points:
        print(f"RENDER {glb.name}: no geometry")
        return
    import numpy as np
    arr = np.array([list(p) for p in points])
    lo = np.percentile(arr, 2, axis=0)
    hi = np.percentile(arr, 98, axis=0)
    mn, mx = Vector(lo), Vector(hi)
    centre = (mn + mx) / 2
    size = max(mx - mn)
    needles, scale = VIEWS.get(view, VIEWS["full"])
    focus = bone_point(arm, needles) if needles else None
    box = weapon_box(dg) if view == "weapon" else None
    if box is not None:
        lo, hi = box
        centre = Vector(((lo + hi) / 2).tolist())
        size = float(max(hi - lo)) * 1.2
        needles, scale = (), 1.0
        focus = centre
    elif focus is not None:
        # the close-ups frame the bone, not the body: the head sits at the top of the box and the
        # weapon at hand height, so a body-framed camera renders both as a few pixels.
        centre = focus + Vector((0, 0, size * 0.04))
        size = size * scale
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    # Frame by geometry, not by a fixed multiple: the 50 mm lens on a 36 mm sensor covers
    # tan(18/50) = 0.36 of the distance either side, so the object's largest dimension needs a
    # distance of 2.0 x its size to sit inside the frame with a margin. A fixed offset put the
    # camera inside the figure (the head was cropped out of every full-body render).
    direction = Vector((0.9, -1.1, 0.35)).normalized()
    cam.location = centre + direction * (size * 2.0)
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    for name, loc, energy in (("key", (3, -4, 5), 3000), ("fill", (-4, -2, 3), 1200),
                              ("rim", (0, 5, 4), 2000)):
        light = bpy.data.lights.new(name, "AREA")
        light.energy = energy
        light.size = 4
        ob = bpy.data.objects.new(name, light)
        ob.location = Vector(loc) + centre
        bpy.context.scene.collection.objects.link(ob)
    bpy.context.scene.render.engine = "BLENDER_EEVEE"
    bpy.context.scene.render.resolution_x = 720
    bpy.context.scene.render.resolution_y = 720
    bpy.context.scene.render.filepath = str(dest)
    bpy.ops.render.render(write_still=True)
    print(f"RENDER {dest}")


for glb in sorted(lab.glob("*.glb")):
    if only and glb.stem not in only:
        continue
    for shot in shots:
        action, frame = shot[0], shot[1]
        view = shot[2] if len(shot) > 2 else "full"
        suffix = "" if view == "full" else f"_{view}"
        render(glb, action, int(frame), view,
               out / f"{glb.stem}_{action}_{frame}{suffix}.png")
