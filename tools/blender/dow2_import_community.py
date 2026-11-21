"""dow2_import_community.py — build a DoW2 unit with the community toolchain, not our own assembly.

The DoW2 Tools add-on (`dow2-blender`, Santos Tools 2 lineage — the tooling the Elite mod is built
with) does the assembly the game does: it reads the model's own bone table, builds the skeleton with
its bone-axis adapter, binds the shipped weights and resolves the materials. This script uses that
importer for the body, the head/attachments and the weapon (merged onto the one armature), then
applies the shipped clips with the add-on's own pose maths (DirectX→Blender conversion, rest delta,
adapter conjugation) and exports a GLB.

Nothing here re-implements bone construction or pose conversion: the only code we supply is the clip
reader, because the add-on's reader is a Windows binary and ours produces the same data.

Run inside Blender:
  blender -b -P tools/blender/dow2_import_community.py -- \
      --id <unit> --out <dir> --manifest <actions.json> \
      --part <body.model> [--part <head.model> ...] [--weapon <weapon.model>]
"""
from __future__ import annotations

import argparse
import json
import struct
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "hkx"))
sys.path.insert(0, str(ROOT / "tools" / "dow2"))

from hkxread import Packfile  # noqa: E402
import skeleton as S  # noqa: E402

# the add-on's constants, copied verbatim from model/skeleton_space.py and utils.py
BONE_AXIS_ADAPTER = Matrix.Rotation(math.radians(-90.0), 4, "Z")
BONE_AXIS_ADAPTER_INV = BONE_AXIS_ADAPTER.inverted()
BLENDER_TO_DX = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)))
DX_TO_BLENDER = BLENDER_TO_DX.inverted()


def dx_to_blender(M):
    return DX_TO_BLENDER @ M @ BLENDER_TO_DX


def canonical_ci(name):
    hit = S.canonical(name)
    if hit:
        return hit
    low = name.lower()
    for k, v in S.BONE_MAP.items():
        if k.lower() == low:
            return v
    return name


_ap = argparse.ArgumentParser()
_ap.add_argument("--id", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--manifest", default="")
_ap.add_argument("--part", action="append", default=[])
_ap.add_argument("--weapon", default="")
_ap.add_argument("--stride", type=int, default=1)
_ap.add_argument("--height-m", type=float, default=0.0,
                 help="real-world height to scale the unit to (0 = leave the source scale)")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

# the timeline every action is baked onto (see apply_clip)
BAKED_FPS = 30

if "dow2_tools" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="dow2_tools")

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

# ------------------------------------------------------------------ assembly, by the add-on
#
# The add-on imports EVERY damage state and EVERY LoD of every mesh group (measured: the farseer's
# model carries a `healthy` and a `wreck` group, and its head arrives as two coincident 865-vertex
# copies — one per state — plus a third at LoD2). The game draws one state at one LoD, so exporting
# all of them stacks coincident copies on the mesh. Each part is therefore pruned as it arrives to
# its `healthy` group and to the LOWEST LoD that part ships — not to a global `lod0`: the LoD
# numbering is per model and some parts (the chaos sorcerer's head and backpack) are authored only
# at LoD2, so a global lod0 rule deletes them.
KEEP_GROUP = "healthy"


def prune_part(label, before):
    new = [o for o in bpy.data.objects if o.type == "MESH" and o not in before]
    if not new:
        print(f"PRUNE {label}: no new mesh objects")
        return
    keepable = [o for o in new if str(o.get("dow2_group", KEEP_GROUP)) == KEEP_GROUP]
    lowest = min((int(o.get("dow2_lod", 0)) for o in keepable), default=0)
    drop = [o for o in new
            if str(o.get("dow2_group", KEEP_GROUP)) != KEEP_GROUP
            or int(o.get("dow2_lod", 0)) != lowest]
    kept = len(new) - len(drop)
    for ob in drop:
        bpy.data.objects.remove(ob, do_unlink=True)
    print(f"PRUNE {label}: {len(new)} meshes -> {kept} (group {KEEP_GROUP}, lod {lowest}), "
          f"dropped {len(drop)}")


for i, part in enumerate(A.part):
    before = [o for o in bpy.data.objects]
    bpy.ops.import_scene.dow2_model(filepath=str(part), merge=(i > 0), reset_scene=False)
    print(f"IMPORTED part {Path(part).name} merge={i > 0}")
    prune_part(Path(part).name, before)
if A.weapon:
    before = [o for o in bpy.data.objects]
    bpy.ops.import_scene.dow2_model(filepath=str(A.weapon), merge=True, reset_scene=False)
    print(f"IMPORTED weapon {Path(A.weapon).name}")
    prune_part(Path(A.weapon).name, before)

arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("the add-on produced no armature")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print(f"ASSEMBLED armature={arm.name} bones={len(arm.data.bones)} meshes={len(meshes)} "
      f"verts={sum(len(m.data.vertices) for m in meshes)} "
      f"arm_scale={tuple(round(v, 4) for v in arm.matrix_world.to_scale())}")

# ---------------------------------------------------------------- materials, opaque by default
# The add-on wires every material's diffuse alpha into the Principled Alpha and sets the blend
# mode to HASHED. glTF has no hashed mode, so Blender's exporter writes `alphaMode: BLEND` for all
# of them — and a BLEND material in three.js is drawn without depth writes and sorted per object,
# which is why the lab units could be seen through and why parts vanished at an angle (the necron
# overlord's face among them). DoW2's own materials say what they are: `dow2_alphaTest` is the
# shipped cutout flag, and it is false on every unit material here (measured: necron body, cape,
# headdress, cadian head, ig armour, ig kit — their diffuse alpha is opaque apart from 0-3 % of
# unused atlas pixels). So the alpha is removed (OPAQUE) unless the source declares a cutout, in
# which case a ROUND node is inserted, which is the graph the exporter maps to MASK/cutoff 0.5.
# Backface culling is switched on to match the game: it draws these shells single-sided, and
# double-sided drawing is what lets interior faces show through a hole.
alpha_report = {"opaque": 0, "cutout": 0}
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.startswith("relic."):
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    alpha = bsdf.inputs["Alpha"]
    cutout = bool(mat.get("dow2_alphaTest", False))
    if cutout and alpha.is_linked:
        src = alpha.links[0].from_socket
        clip = nodes.new("ShaderNodeMath")
        clip.operation = "ROUND"
        clip.location = (bsdf.location.x - 320, bsdf.location.y - 620)
        links.new(src, clip.inputs[0])
        links.new(clip.outputs[0], alpha)
        alpha_report["cutout"] += 1
    else:
        for link in list(alpha.links):
            links.remove(link)
        alpha.default_value = 1.0
        alpha_report["opaque"] += 1
    mat.use_backface_culling = True
print(f"MATERIALS alpha: {alpha_report['opaque']} opaque, {alpha_report['cutout']} cutout "
      f"(dow2_alphaTest), backface culling on")

# ------------------------------------------------------------------ clips, by the add-on's maths
rest_world = {b.name.lower(): b.matrix_local @ BONE_AXIS_ADAPTER_INV for b in arm.data.bones}


def rest_local_for(pb, parent_pb):
    """Rest of `pb` relative to `parent_pb` (the add-on's get_rest_local_matrix).

    The parent comes from the CLIP's hierarchy, matched to the armature, not from the model's own
    parent: a clip whose hierarchy differs from the model's (the necron's) otherwise produces a
    delta against the wrong rest and the bones fly metres away.
    """
    w = rest_world.get(pb.name.lower())
    if w is None:
        return None
    if parent_pb is None:
        return w
    pw = rest_world.get(parent_pb.name.lower())
    return pw.inverted() @ w if pw is not None else w

for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

arm.animation_data_create()
for act in list(bpy.data.actions):
    bpy.data.actions.remove(act)


def layer_overrides(layers):
    """Track overrides from upper-body layer clips, keyed by the armature bone they drive.

    DoW2's layers are single-track clips and their track index is NOT a bone index: the file's own
    `hkAnimationBinding` says which bone each track drives (measured: `aim_stand_horiz` track 0 ->
    `Bip01 Spine1`, `aim_stand_virt` track 0 -> `Bip01 Spine2`). Reading a layer without its binding
    rotates the root bone instead of the spine. `blendHint` is 0 (Havok NORMAL, i.e. the track drives
    that bone), so the layer's local transform replaces the base clip's for that bone — the layer
    carries the same translation and unit scale as the base, so only the rotation changes.
    """
    out = {}
    for layer in layers or []:
        pf = Packfile.open(layer["file"])
        anim = pf.animation()
        sk = pf.skeleton()
        bindings = pf.animation_bindings()
        if anim is None or sk is None or not bindings:
            print(f"  LAYER {layer['clip']}: no animation or binding, skipped")
            continue
        frame = int(layer.get("frame", 0))
        frame = max(0, min(frame, anim["numberOfPoses"] - 1))
        mapping = bindings[0]["track_to_bone"]
        for track, bone_index in enumerate(mapping):
            if track >= len(anim["tracks"]) or not (0 <= bone_index < len(sk["bone_names"])):
                continue
            name = sk["bone_names"][bone_index]
            t = anim["tracks"][track]
            q = t["rotation"][frame]
            scale = [1.0, 1.0, 1.0] if not all(0.5 < v < 2.0 for v in t["scale"][frame]) \
                else list(t["scale"][frame])
            out[name.lower()] = dx_to_blender(Matrix.LocRotScale(
                Vector(t["translation"][frame]), Quaternion((q[3], q[0], q[1], q[2])),
                Vector(scale)))
            print(f"  LAYER {layer['clip']} frame {frame}: drives {name}")
    return out


def apply_clip(clip_path, action_name, fps, frames, layers=None):
    pf = Packfile.open(clip_path)
    sk = pf.skeleton()
    anim = pf.animation()
    if sk is None or anim is None:
        return None
    names = sk["bone_names"]
    parents = sk["parents"]
    # A clip's tracks are NOT automatically bone-indexed. Full-body clips ship an identity map, but a
    # PARTIAL clip maps its few tracks onto specific bones (measured: the Wartrukk's `chassis_idle_01`
    # has 3 tracks bound to bones 1, 41 and 42 — the chassis and two suspension bones). Applying track
    # i to bone i posed the vehicle onto the wrong bones and tipped it onto its side; 33 clips across
    # 8 units use a non-identity binding. Bones the clip does not track stay at the clip's own
    # reference pose, which is what a partial clip means.
    bindings = pf.animation_bindings()
    track_of_bone = {}
    if bindings:
        for track, bone_index in enumerate(bindings[0]["track_to_bone"]):
            if 0 <= bone_index < len(names):
                track_of_bone[bone_index] = track
    if not track_of_bone:
        track_of_bone = {i: i for i in range(len(names))}
    import numpy as _np
    _sc = _np.array([anim["tracks"][t]["scale"] for t in track_of_bone.values()
                     if t < len(anim["tracks"])])
    clip_scale_ok = bool(_sc.size == 0 or ((_sc > 0.5) & (_sc < 2.0)).all())
    # the add-on keeps the model's own bone names (`bip01 r thigh`), so the clip's bones are
    # matched against the armature's names case-insensitively -- NOT through our canonical
    # vocabulary, which would find nothing and leave every bone unkeyed.
    arm_bones = {b.name.lower(): b for b in arm.pose.bones}
    pb_by_index = {}
    for i, n in enumerate(names):
        pb = arm_bones.get(n.lower())
        if pb is not None:
            pb_by_index[i] = pb
    # Nearest MAPPED ancestor in the clip's hierarchy. A clip may carry bones the model does not
    # (the necron's cape chain, its arrow bone); a child of such a bone must be posed against the
    # nearest ancestor the model actually has, or its rest is the wrong bone and it flies away.
    parent_pb = {}
    parent_idx = {}
    for i in pb_by_index:
        p = parents[i]
        while p >= 0 and p not in pb_by_index:
            p = parents[p]
        if p >= 0:
            parent_pb[i] = pb_by_index[p]
            parent_idx[i] = p
    print(f"  mapped {len(pb_by_index)}/{len(names)} clip bones onto {arm.name}")
    overrides = layer_overrides(layers)

    act = bpy.data.actions.new(action_name)
    act.use_fake_user = True
    arm.animation_data.action = act
    try:
        if arm.animation_data.action_slot is None and act.slots:
            arm.animation_data.action_slot = act.slots[0]
    except AttributeError:
        pass

    # One timeline for every action. The glTF exporter converts keyframe numbers to seconds with a
    # SINGLE scene rate at export time, so a per-action `fps_base` is silently lost: whichever action
    # was keyed last set the rate for the whole file, and units whose last clip was slow exported
    # fast (measured: the eldar and lictor played 3.7-3.9x too fast, the Tau battlesuit 7.5x, and its
    # two-frame aim clip collapsed to 0.00 s). The bake is therefore at a fixed BAKED_FPS and each
    # clip's keys are placed at their true time on that timeline, so every action plays at the speed
    # the shipped clip was authored at.
    bpy.context.scene.render.fps = BAKED_FPS
    bpy.context.scene.render.fps_base = 1.0
    stride = max(1, A.stride)
    for f, key_frame in frames:
        bpy.context.scene.frame_set(key_frame)
        # clip locals in Blender space, composed to world
        local = []
        for i in range(len(names)):
            track = track_of_bone.get(i)
            if track is None or track >= len(anim["tracks"]):
                # untracked bone: the clip's own reference pose (its bind), not identity
                ref = sk["reference_pose"][i] if i < len(sk["reference_pose"]) else None
                if ref is None:
                    local.append(Matrix.Identity(4))
                    continue
                local.append(dx_to_blender(Matrix.LocRotScale(
                    Vector(ref["translation"]), Quaternion((ref["rotation"][3], ref["rotation"][0],
                                                           ref["rotation"][1], ref["rotation"][2])),
                    Vector([1.0, 1.0, 1.0]))))
                continue
            t = anim["tracks"][track]
            q = t["rotation"][f]
            # A clip's scale track is either sane (all components within ~+/-25% of 1, measured
            # across the corpus) or it is a decode artefact (the necron's run from -4951 to 699
            # while their translations are correct). Per-component clamping left the necron with
            # plausible-looking 0.38-3.13 values that pulsed the model; a clip is judged as a whole.
            scale = [1.0, 1.0, 1.0] if not clip_scale_ok else list(t["scale"][f])
            M = Matrix.LocRotScale(Vector(t["translation"][f]),
                                   Quaternion((q[3], q[0], q[1], q[2])),
                                   Vector(scale))
            local.append(dx_to_blender(M))
        # an upper-body layer replaces the local transform of the bone its binding names
        for i, n in enumerate(names):
            hit = overrides.get(n.lower())
            if hit is not None:
                local[i] = hit
        world = [None] * len(local)

        def resolve(i):
            if world[i] is not None:
                return world[i]
            p = parents[i]
            world[i] = local[i] if p < 0 else resolve(p) @ local[i]
            return world[i]

        for i in range(len(local)):
            resolve(i)
        # Place each bone at the clip's world pose, expressed in the armature's own convention
        # (rest = model world @ ADAPTER). Blender then derives the local transform against the
        # armature's real parent, so a clip whose hierarchy differs from the model's (the necron's)
        # still lands correctly, and a matching one gives the same result as the delta form.
        # the add-on's own sequence: rest^-1 @ (parent^-1 @ world), conjugated by the adapter
        for i, pb in pb_by_index.items():
            rl = rest_local_for(pb, parent_pb.get(i))
            if rl is None:
                continue
            pidx = parent_idx.get(i, -1)
            pw = world[pidx] if pidx >= 0 else Matrix.Identity(4)
            delta = rl.inverted() @ (pw.inverted() @ world[i])
            delta = BONE_AXIS_ADAPTER_INV @ delta @ BONE_AXIS_ADAPTER
            pb.location, pb.rotation_quaternion, pb.scale = delta.decompose()
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            pb.keyframe_insert("location", frame=key_frame)
            pb.keyframe_insert("rotation_quaternion", frame=key_frame)
            pb.keyframe_insert("scale", frame=key_frame)
    _fc = []
    try:
        _fc = list(act.fcurves)
    except Exception:
        pass
    if not _fc:
        for _l in getattr(act, "layers", []):
            for _st in getattr(_l, "strips", []):
                for _cb in getattr(_st, "channelbags", []):
                    _fc.extend(list(_cb.fcurves))
    print(f"  KEYED {action_name}: fcurves={len(_fc)} keys="
          f"{sum(len(fc.keyframe_points) for fc in _fc)} frames={len(frames)}")
    # Park the action on its own NLA track. With Blender 5.x slotted actions, exporting several
    # actions by assigning them one after another collapses them (the exporter evaluates the
    # armature with no action bound and writes two constant keys). NLA tracks are the supported
    # way to export a set of actions.
    arm.animation_data.action = None
    track = arm.animation_data.nla_tracks.new()
    track.name = action_name
    strip = track.strips.new(action_name, 1, act)
    strip.name = action_name
    track.mute = False
    return {"frames": len(frames), "fps": fps / stride, "source_fps": fps}


meta = {}
if A.manifest:
    manifest = json.loads(Path(A.manifest).read_text())
    for name, entry in manifest.get("actions", {}).items():
        clip = entry.get("clip")
        if not clip:
            continue
        path = Path(entry["file"])
        try:
            pf = Packfile.open(path)
            anim = pf.animation()
        except Exception as exc:
            print(f"SKIP {name}: {exc}")
            continue
        if anim is None:
            print(f"SKIP {name}: not a delta-compressed clip")
            continue
        # sample the clip at the baked rate over its own duration: a 15 fps clip gets every other
        # frame of a 30 fps timeline, a 32 fps clip is resampled to 30, and the duration is unchanged.
        # The key frame is the OUTPUT frame and the source frame is derived from its time, so no key
        # is ever re-derived from a quantised source frame (which collapsed repeated frames and made
        # a held 2-frame clip export as 0.27 s of a 0.5 s clip).
        stride = max(1, A.stride)
        src_fps = anim["frame_rate"]
        out_count = max(2, int(round(anim["duration"] * BAKED_FPS)) + 1)
        frames = []
        for k in range(0, out_count, stride):
            src = min(anim["numberOfPoses"] - 1, int(round(k * src_fps / BAKED_FPS)))
            frames.append((src, k + 1))
        info = apply_clip(path, name, src_fps, frames, entry.get("layers"))
        if info is None:
            continue
        info.update({"source_clip": clip, "duration": anim["duration"],
                     "baked_fps": BAKED_FPS, "baked_keys": len(frames),
                     "events": entry.get("events", []),
                     "acting_frame": entry.get("acting_frame", {})})
        if entry.get("layers"):
            info["layers"] = entry["layers"]
        meta[name] = info
        print(f"ACTION {name} <- {clip} {len(frames)} keys at {BAKED_FPS} fps")

arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()

# Real-world scale. The shipped models are authored at the game's own scale, which is not metres:
# measured, a guardsman imports 2.97 m tall and a Baneblade 10.55 m against a real 1.85 m and 5.3 m.
# The ratios are not constant either, so a single global factor is wrong — `--height-m` sets the
# unit's real height and the whole rig is scaled to it before export, which bakes the correction into
# the geometry and the skeleton together (a scale on the exported root would leave the animation
# translation tracks at the old scale).
def measured_height() -> float:
    """World-space height of the assembled unit, through the armature deformation.

    Two earlier measurements were wrong in the same direction. `evaluated_get(...).bound_box` reads the
    undeformed bounds of an armature-deformed mesh, and the raw `bound_box` is local space. Both
    under-read the hormagaunt at 0.886 m on a model that exports at 2.07 m, so the 1.69x factor
    produced a 3.51 m export against a 1.50 m target — the unit shipped twice its declared height.
    The geometry that will be exported is the evaluated mesh, so that is what gets measured.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lo, hi = 1e9, -1e9
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        matrix = evaluated.matrix_world
        for vertex in mesh.vertices:
            world = matrix @ vertex.co
            lo = min(lo, world.z)
            hi = max(hi, world.z)
        evaluated.to_mesh_clear()
    return hi - lo if hi > -1e8 else 0.0


out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}.glb"


def export_once() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                              export_animations=True, export_animation_mode="ACTIONS",
                              export_optimize_animation_size=False,
                              export_optimize_animation_keep_anim_armature=True)


def glb_height(path: Path):
    """Height of the exported file's own geometry, in metres."""
    data = path.read_bytes()
    off, js = 12, None
    while off < len(data):
        length, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8:off + 8 + length]
        if kind == 0x4E4F534A:
            js = json.loads(chunk.decode("utf8").rstrip("\x00 "))
        off += 8 + length
    if not js:
        return None
    lo, hi = 1e9, -1e9
    for mesh in js.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            accessor = js["accessors"][primitive["attributes"]["POSITION"]]
            if "min" in accessor and "max" in accessor:
                lo = min(lo, accessor["min"][1])
                hi = max(hi, accessor["max"][1])
    return hi - lo if hi > -1e8 else None


# Real-world scale, closed on the exported file.
#
# The shipped models are authored at the game's own scale, which is not metres: measured, a guardsman
# imports 2.97 m tall and a Baneblade 10.55 m against a real 1.85 m and 5.3 m, and the ratios are not
# constant. Scaling the scene and trusting it is not enough: measured on the hormagaunt, Blender's own
# scene query reported 1.500 m while the export was 3.508 m, because the exporter bakes a scale the
# scene query does not see. So the factor is applied, the file is exported, the FILE is measured, and
# the residual is corrected until it matches. A unit that does not match its declared height makes
# every cover read wrong, so this is a gate, not a best effort.
export_once()
if A.height_m and A.height_m > 0:
    for attempt in range(4):
        shipped = glb_height(dest)
        if shipped is None:
            break
        factor = A.height_m / shipped
        print(f"SCALE attempt {attempt + 1}: glb {shipped:.3f} m -> target {A.height_m:.3f} m (x{factor:.4f})")
        if abs(factor - 1.0) < 0.01:
            break
        for obj in list(bpy.context.scene.objects):
            if obj.parent is None:
                obj.scale = tuple(v * factor for v in obj.scale)
        bpy.context.view_layer.update()
        export_once()
    shipped = glb_height(dest)
    print(f"SCALE VERIFY declared {A.height_m:.3f} m glb {shipped if shipped is None else round(shipped, 3)} m")
    if shipped is None or abs(shipped - A.height_m) > 0.02 * A.height_m:
        raise SystemExit(f"{A.id}: exported {shipped} m, declared {A.height_m:.3f} m")
print(f"EXPORTED {dest} actions={len(bpy.data.actions)}")
if meta:
    (out / (A.id + ".actions.json")).write_text(json.dumps(
        {"unit": A.id, "source": A.manifest, "actions": meta}, indent=1))
    print(f"ACTIONS {out / (A.id + '.actions.json')}")
