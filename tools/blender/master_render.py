"""master_render.py — 8-direction pixel-master capture with per-view framing,
masks and no antialiasing.

Framing is the part that was wrong in the first masters: the camera aimed at the
world origin and the ortho scale was a guess, so a barrel was cut off and a rifle
filled a third of the canvas. Here the ortho extent is *derived* from the actual
projected geometry for every direction, one constant scale is used across the
whole set (a sprite set whose asset changes size between directions reads as
flicker), and the asset is anchored instead of guessed at.

Masks are rendered through `pass_materials.py`: Raw view transform, uint8
thresholds, the two bugs documented there.

Shared by `parametric_prop.py` (build-then-render) and
`render_pixel_master.py` (render an already-baked GLB).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pass_materials  # noqa: E402

ELEVATION_DEG = 35.0
MARGIN = 1.06
EDGE_FRAC = 0.03


def _mesh_objects(objs):
    return [o for o in objs if o.type == "MESH"]


def evaluated_points(objs) -> list[Vector]:
    """World-space vertex positions after modifiers and pose deformation."""
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for obj in _mesh_objects(objs):
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
        mw = ev.matrix_world
        pts.extend(mw @ v.co for v in me.vertices)
        ev.to_mesh_clear()
    if not pts:
        raise SystemExit("no mesh vertices to frame")
    return pts


def setup_studio(size, samples: int, key_energy: float = 800.0,
                 fill_energy: float = 170.0):
    if isinstance(size, int):
        size = (size, size)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.eevee.taa_render_samples = max(1, samples)
    scene.render.filter_size = 0.01 if samples <= 1 else 1.5
    # the studio is calibrated so a lit facet lands on the palette's 74-120 steel
    # steps, not on 138+ (measured: a lighter exposure made gunmetal read as
    # pale plastic against the Boltgun reference)
    scene.view_settings.exposure = -0.65
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.023, 0.03, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.45
    scene.world = world

    def area(name, energy, loc, rot, size_m):
        light = bpy.data.lights.new(name, "AREA")
        light.energy = energy
        light.size = size_m
        ob = bpy.data.objects.new(name, light)
        ob.location = loc
        ob.rotation_euler = rot
        scene.collection.objects.link(ob)

    # 10:1 key-to-fill, the miniature-photography separation the palette ramp
    # needs in order to posterise into distinct bands
    area("key", key_energy, (3.0, -3.4, 4.6),
         (math.radians(45), 0, math.radians(38)), 3.0)
    area("fill", fill_energy, (-3.6, -2.4, 2.0),
         (math.radians(72), 0, math.radians(-58)), 5.0)

    # rim light: Boltgun's readability comes from a hard edge highlight on the
    # silhouette. It has to follow the camera, or it only works from one
    # direction; place_camera() re-aims it per view.
    rim = bpy.data.lights.new("rim", "SUN")
    rim.energy = 6.0
    rim.angle = math.radians(6.0)
    rim_ob = bpy.data.objects.new("rim", rim)
    rim_ob.location = (0, 4, 4)
    scene.collection.objects.link(rim_ob)

    cam_data = bpy.data.cameras.new("master_cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("master_cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def _direction_vector(az_deg: float, el_deg: float) -> Vector:
    az, el = math.radians(az_deg), math.radians(el_deg)
    return Vector((math.cos(el) * math.sin(az),
                   -math.cos(el) * math.cos(az),
                   math.sin(el)))


def _project(points, cam, target: Vector, dirv: Vector):
    cam.location = target + dirv * (max((p - target).length for p in points) * 2.0 + 10.0)
    cam.rotation_euler = (-dirv).to_track_quat("-Z", "Y").to_euler()
    rot = cam.rotation_euler.to_matrix()
    inv = rot.transposed()
    return [inv @ (p - cam.location) for p in points]


def plan_views(points, directions: int, anchor: str) -> list[dict]:
    """Compute one constant scale and a per-direction camera offset.

    Global scale = the largest projected extent any direction needs, so no view
    clips and the asset does not pulse in size between frames.
    """
    centre = sum(points, Vector()) / len(points)
    target = centre
    az_list = [0.0 if directions == 1 else i * 360.0 / directions
               for i in range(max(1, directions))]
    raw = []
    for az in az_list:
        pts = _project(points, bpy.data.objects["master_cam"], target,
                       _direction_vector(az, ELEVATION_DEG))
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        raw.append((az, min(xs), max(xs), min(ys), max(ys)))
    span = max(max(r[2] - r[1], r[4] - r[3]) for r in raw)
    scale = span * MARGIN
    plans = []
    for az, xmin, xmax, ymin, ymax in raw:
        cx = (xmin + xmax) / 2.0
        if anchor == "bottom":
            dy = ymin + (0.5 - EDGE_FRAC) * scale
        else:
            dy = (ymin + ymax) / 2.0
        plans.append({"azimuth_deg": az, "ortho_scale": round(scale, 4),
                      "offset": [round(cx, 4), round(dy, 4)],
                      "projected": [round(xmax - xmin, 4), round(ymax - ymin, 4)],
                      "anchor": anchor})
    return plans


def place_camera(cam, target, plan):
    dirv = _direction_vector(plan["azimuth_deg"], ELEVATION_DEG)
    rim = bpy.data.objects.get("rim")
    if rim is not None:
        # a hard side-back key, 55 deg off the camera axis and 45 deg up: it
        # lights the visible side planes and grazes the silhouette, which is
        # what produces Boltgun's edge highlight. Directly behind the camera
        # does nothing on a faceted, orthographically viewed asset.
        rim_dir = _direction_vector(plan["azimuth_deg"] - 55.0, 45.0)
        rim.location = target + rim_dir * 6.0
        rim.rotation_euler = (target - rim.location).to_track_quat("-Z", "Y").to_euler()
    cam.location = target + dirv * 50.0
    cam.rotation_euler = (-dirv).to_track_quat("-Z", "Y").to_euler()
    rot = cam.rotation_euler.to_matrix()
    cam.location = cam.location + rot @ Vector((plan["offset"][0], plan["offset"][1], 0.0))
    cam.data.ortho_scale = plan["ortho_scale"]


def render_master_set(objs, out_dir: Path, asset_id: str, size, directions: int,
                      masks: bool, anchor: str = "centre", samples: int = 1,
                      emission_atlas=None, framing_objs=None) -> dict:
    cam = bpy.data.objects.get("master_cam")
    if cam is None:
        cam = setup_studio(size, samples)
    points = evaluated_points(framing_objs if framing_objs is not None else objs)
    centre = sum(points, Vector()) / len(points)
    plans = plan_views(points, directions, anchor)

    out_dir = Path(out_dir)
    (out_dir / "render").mkdir(parents=True, exist_ok=True)
    beauty, mask_paths = [], []
    for plan in plans:
        place_camera(cam, centre, plan)
        suffix = f"_az{int(plan['azimuth_deg']):03d}" if directions > 1 else "_3q"
        path = out_dir / "render" / f"{asset_id}{suffix}.png"
        bpy.context.scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        beauty.append(str(path))
        if masks:
            (out_dir / "masks").mkdir(exist_ok=True)
            for kind in ("normal", "ao", "emission"):
                mp = out_dir / "masks" / f"{asset_id}{suffix}_{kind}.png"
                pass_materials.render_mask(objs, kind, mp,
                                           fallback_atlas=emission_atlas)
                mask_paths.append(str(mp))
    return {"directions": len(plans), "plans": plans, "beauty": beauty,
            "masks": mask_paths}
