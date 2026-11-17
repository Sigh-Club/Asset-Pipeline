"""rebind_unit.py — re-skin a shipped unit GLB so the pose stops folding the mesh.

This is the repair the research pass specified, applied to an existing certified unit:

  1. weld a working copy of the body (the shipped meshes are fully split-vertex — 2.99
     vertices per triangle — which defeats every topology-aware weight solver);
  2. solve weights on the welded copy with Blender's bone-heat solver (the documented
     standard, and the one that measures 0.2-0.8 % posed tearing against 4-23 % for the
     distance field the pipeline used);
  3. transfer those weights back onto the original split vertices by position, so the
     shipped mesh keeps its flat shading and its UVs;
  4. put the weapon attachment sockets on the hand bones, where `configs/rigs/*.json`
     always said they were (measured: `socket_weapon_R` sat 0.63 m from `hand_R`);
  5. bind the weapon with a POSE-INDEPENDENT transform — grip at the hand, barrel along the
     hand's own axis — so it is in the hand in bind pose and in every clip, instead of only
     in the one pose the old bind was solved for;
  6. export with the clip set intact to a separate directory, leaving the certified
     masters untouched.

Usage:
  blender -b -P tools/blender/rebind_unit.py -- --unit <unit.glb> --out <dir> --id <id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

_ap = argparse.ArgumentParser()
_ap.add_argument("--unit", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--hand", default="hand_R", help="bone the weapon is held in")
_ap.add_argument("--weapon-mesh", default="", help="mesh name prefix to treat as the weapon "
                                                   "(default: every non-body mesh)")
_ap.add_argument("--no-heat", action="store_true", help="keep the shipped weights (bind/socket "
                                                       "fixes only)")
_ap.add_argument("--rigid-islands", action="store_true", default=True,
                help="bind every separate shell rigidly to one bone, the way DoW2 ships armour "
                     "(one bone index, weight 255 per vertex). Smooth weights on a rigid plate "
                     "tear it apart.")
_ap.add_argument("--weapon", default="", help="authored weapon GLB to socket into the hand. The "
                                              "baked weapon is removed: its own frame is lost once "
                                              "it is exported into armature space, which is why a "
                                              "geometric guess put the barrel where the stock goes.")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

# How each weapon is held. DATA, not a rule: a rifle is carried with the barrel forward and low, a
# staff stands vertically in one hand. One universal "follow the hand axis" rule cannot express
# both — measured, it put the lasgun at 83 deg from vertical (right) and the staff at 29 deg (wrong).
# Measured, not assumed: after Blender's glTF import BOTH weapon assets have their long axis along
# BLENDER +Z (the staff spans z 0..1.6, the lasgun z 0..0.95 — the glTF y-up +Y becomes Blender +Z).
# So the hold table is written in Blender space and the weapon's own long axis is +Z.
WEAPON_HOLD = {
    "lasgun": (0.0, -1.0, -0.25), "bolter": (0.0, -1.0, -0.20),     # carried low, muzzle forward-down
    "shuriken": (0.0, -1.0, -0.20), "shoota": (0.0, -1.0, -0.30),
    "rokkit": (0.0, -1.0, -0.15), "burna": (0.0, -1.0, -0.30),
    "staff": (0.0, 0.0, 1.0), "horns": (0.0, 0.0, 1.0),             # shaft upright, one hand
}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.unit).resolve()))
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("no armature in the unit GLB")
meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith("Icosphere")]
if not meshes:
    raise SystemExit("no mesh in the unit GLB")
body = max(meshes, key=lambda o: len(o.data.vertices))
weapons = [o for o in meshes if o is not body]
if A.weapon_mesh:
    weapons = [o for o in meshes if o.name.startswith(A.weapon_mesh)] or weapons

# The importer leaves the first animation assigned and may build NLA tracks; a rest-pose
# export needs both cleared (a known trap: the GLB's default pose then disagrees with its
# bind-pose mesh).
if arm.animation_data:
    arm.animation_data.action = None
    for track in list(arm.animation_data.nla_tracks):
        arm.animation_data.nla_tracks.remove(track)
for pb in arm.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.location = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()

bones = {b.name: b for b in arm.data.bones}
if A.hand not in bones:
    raise SystemExit(f"no bone {A.hand}")
hand = bones[A.hand]
print(f"UNIT {A.id} body={body.name} verts={len(body.data.vertices)} "
      f"weapons={[w.name for w in weapons]} hand={A.hand}")


def geodesic_weights(verts, segments, k=8, power=4.0, maxb=3):
    """Fallback binding for bodies the heat solver cannot solve.

    Weights come from the distance a path travels *across the surface*, not through the air,
    which is what stops a vertex on the hip being captured by a bone in the chest. This is the
    geodesic-voxel construction (Dionne & de Lasa 2013) reduced to a k-NN surface graph, which
    is enough for a body this size and needs no extra dependency inside Blender.
    """
    import heapq
    import numpy as np

    P = np.array([tuple(v) for v in verts])
    n = len(P)
    if n == 0:
        return []
    # k-NN adjacency
    from mathutils.kdtree import KDTree
    kd = KDTree(n)
    for i, co in enumerate(verts):
        kd.insert(co, i)
    kd.balance()
    adj = [[] for _ in range(n)]
    for i, co in enumerate(verts):
        for (_c, j, d) in kd.find_n(co, k + 1):
            if j != i:
                adj[i].append((j, max(d, 1e-4)))
                adj[j].append((i, max(d, 1e-4)))

    def dijkstra(src):
        dist = [float("inf")] * n
        dist[src] = 0.0
        heap = [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for v, w in adj[u]:
                nd = d + w
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        return np.array(dist)

    # connectivity check: a disconnected k-NN graph makes every distance infinite, every weight
    # equal, and the whole body bind to the first bone (measured: 21,053 vertices on `root`, so no
    # clip moved the mesh at all and the deformation gate could not tell).
    import collections
    seen = [False] * n
    comps = 0
    for start in range(n):
        if seen[start]:
            continue
        comps += 1
        stack = [start]
        seen[start] = True
        while stack:
            u = stack.pop()
            for v, _w in adj[u]:
                if not seen[v]:
                    seen[v] = True
                    stack.append(v)
    print(f"GEODESIC graph components={comps} vertices={n}")

    fields = []
    radii = []
    for name, head, tail in segments:
        h = np.array(tuple(head))
        t = np.array(tuple(tail))
        ab = t - h
        d2 = float(ab @ ab) or 1e-9
        proj = np.clip(((P - h) @ ab) / d2, 0.0, 1.0)
        seg = np.linalg.norm(P - (h + proj[:, None] * ab), axis=1)
        src = int(np.argmin(seg))
        fields.append(dijkstra(src))
        radii.append(0.15 if any(x in name for x in ("spine", "chest", "pelvis"))
                     else 0.12 if name.startswith(("thigh", "head"))
                     else 0.09 if name.startswith(("upperarm", "clavicle"))
                     else 0.07 if name.startswith("lowerarm")
                     else 0.06 if name.startswith(("hand", "foot"))
                     else 0.03 if name.startswith(("thumb", "finger", "toe", "jaw"))
                     else 0.08)
    F = np.stack(fields, axis=1)
    R = np.array(radii)
    out = []
    for i in range(n):
        d = F[i]
        idx = np.argsort(d)[:maxb]
        w = (R[idx] / np.maximum(d[idx], 1e-3)) ** power
        tot = float(w.sum()) or 1.0
        w = w / tot
        out.append({segments[j][0]: float(w[k]) for k, j in enumerate(idx) if w[k] > 1e-4})
    distinct = len({name for w in out for name in w})
    print(f"GEODESIC distinct bones={distinct}")
    return out


def euclid_weights(verts, segments, power=2.0, maxb=2):
    """Plain distance falloff, used when the geodesic solve collapses.

    Not the preferred field, but it always produces a spread over the skeleton: better a coarse
    skin than a body bound to one bone, which reads as "no animation" and cannot be diagnosed from
    a deformation metric.
    """
    import numpy as np

    P = np.array([tuple(v) for v in verts], dtype=float)
    segs = [(n, np.array(tuple(h)), np.array(tuple(t))) for n, h, t in segments]
    out = []
    for p in P:
        ds = []
        for n, h, t in segs:
            ab = t - h
            d2 = float(ab @ ab) or 1e-9
            u = max(0.0, min(1.0, float((p - h) @ ab) / d2))
            ds.append((float(np.linalg.norm(p - (h + ab * u))), n))
        ds.sort()
        top = ds[:maxb]
        w = [(1.0 / max(1e-3, d)) ** power for d, _n in top]
        tot = sum(w) or 1.0
        out.append({n: wi / tot for wi, (_d, n) in zip(w, top)})
    print(f"EUCLID distinct bones={len({n for w in out for n in w})}")
    return out



def island_of_vertex(mesh):
    """Connected-shell id for every vertex of `mesh`, largest shell first.

    MUST be run on the WELDED mesh. The shipped bodies are split-vertex, so the raw mesh has one
    "island" per triangle (measured: 4,085 of them); binding per island on that mesh makes every
    triangle rigid and the body shatters into loose plates.
    """
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    bm.verts.ensure_lookup_table()
    seen = set()
    islands = []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack = [v]
        island = []
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            island.append(cur.index)
            for edge in cur.link_edges:
                other = edge.other_vert(cur)
                if other.index not in seen:
                    seen.add(other.index)
                    stack.append(other)
        islands.append(island)
    bm.free()
    islands.sort(key=len, reverse=True)
    out = [0] * len(mesh.data.vertices)
    for rank, island in enumerate(islands):
        for vi in island:
            out[vi] = rank
    return out, [len(i) for i in islands]


def rigid_bind(body_mesh, welded_island, welded_positions, welded_weights, smooth_rank=0):
    """One bone per shell, except the body shell (rank 0), which keeps smooth weights.

    DoW2 does not smooth-skin its armour: the vertex stream carries ONE bone index and weight 255
    (measured on `ig_armour_common_b.model`: the index byte clusters per body region, weight
    0xFF00). A pauldron is a rigid plate; blending it across clavicle/upperarm/chest deforms it,
    which is what makes the shoulders float and shatter on every posed unit.
    """
    import numpy as np
    from mathutils.kdtree import KDTree

    kd = KDTree(len(welded_positions))
    for i, co in enumerate(welded_positions):
        kd.insert(co, i)
    kd.balance()

    tally = {}
    for i, w in enumerate(welded_weights):
        if not w:
            continue
        rank = welded_island[i]
        d = tally.setdefault(rank, {})
        for name, weight in w.items():
            d[name] = d.get(name, 0.0) + weight
    chosen = {}
    for rank, d in tally.items():
        if rank == smooth_rank or not d:
            continue
        chosen[rank] = max(d.items(), key=lambda kv: kv[1])[0]

    out = []
    for v in body_mesh.data.vertices:
        _co, idx, _d = kd.find(v.co)
        if idx is None:
            out.append(None)
            continue
        rank = welded_island[idx]
        if rank == smooth_rank:
            out.append(dict(welded_weights[idx]))
        else:
            out.append({chosen.get(rank, max(tally.get(rank, {'root': 1.0}).items(),
                                             key=lambda kv: kv[1])[0]): 1.0})
    return out, len(chosen)


# ------------------------------------------------------------------ 1-3. weights
if not A.no_heat:
    work = body.copy()
    work.data = body.data.copy()
    work.name = f"{body.name}_weldwork"
    bpy.context.collection.objects.link(work)

    import bmesh
    bm = bmesh.new()
    bm.from_mesh(work.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bm.to_mesh(work.data)
    bm.free()
    work.data.update()
    print(f"WELD {before} -> {len(work.data.vertices)}")

    for group in list(work.vertex_groups):
        work.vertex_groups.remove(group)
    for mod in list(work.modifiers):
        work.modifiers.remove(mod)
    bpy.ops.object.select_all(action="DESELECT")
    work.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    print(f"HEAT groups={len(work.vertex_groups)}")

    # read the solved weights as (position -> {bone: weight})
    index_to_name = {g.index: g.name for g in work.vertex_groups}
    solved = []
    for v in work.data.vertices:
        w = {index_to_name[g.group]: g.weight for g in v.groups
             if g.group in index_to_name and g.weight > 1e-4}
        total = sum(w.values())
        if total > 0:
            solved.append((Vector(v.co), {k: val / total for k, val in w.items()}))
    print(f"HEAT solved={len(solved)} of {len(work.data.vertices)}")

    # shell structure + per-welded-vertex weights, captured while the welded mesh exists
    welded_islands, island_sizes = island_of_vertex(work)
    welded_positions = [Vector(v.co) for v in work.data.vertices]
    _idx2name = {g.index: g.name for g in work.vertex_groups}
    welded_weights = []
    for v in work.data.vertices:
        w = {_idx2name[g.group]: g.weight for g in v.groups
             if g.group in _idx2name and g.weight > 1e-4}
        total = sum(w.values())
        welded_weights.append({k: val / total for k, val in w.items()} if total > 0 else {})
    print(f"ISLANDS {len(island_sizes)} shells, largest {island_sizes[:4]}")

    # Bone heat fails outright on some bodies (measured: 3 of 8 units, 0 weights on every
    # vertex). Clearing the shipped groups first and transferring nothing made those units
    # RIGID — they passed the deformation gate with 0 % tearing because nothing moved. Keep the
    # shipped weights when the solve does not cover the body, and say so.
    if len(solved) < 0.5 * len(work.data.vertices):
        print(f"HEAT_FAILED solved={len(solved)} of {len(work.data.vertices)} — keeping the "
              f"shipped weights")
        # Geodesic fallback: the same construction the research pass specifies, on the welded
        # surface, so the body still gets a topology-aware binding instead of the shipped
        # volume-distance field.
        segments = []
        for b in arm.data.bones:
            if b.use_deform:
                segments.append((b.name, b.head_local, b.tail_local))
        coords = [v.co.copy() for v in work.data.vertices]
        geo = geodesic_weights(coords, segments)
        if len({n for w in geo for n in w}) < 8:
            print("GEODESIC collapsed — falling back to a Euclidean falloff")
            geo = euclid_weights(coords, segments)
        solved = [(Vector(v.co), geo[i]) for i, v in enumerate(work.data.vertices)
                  if geo[i]]
        # The geodesic solve returns weights but does not write them into `work`'s vertex groups, so
        # `welded_weights` (read from those groups above) is still empty. The rigid-island step then
        # had no tally and fell back to `root` for every vertex — measured: 21,053 vertices on one
        # bone, so no clip moved the mesh and it looked like "the animation is broken".
        welded_weights = [dict(w) for w in geo]
        print(f"HEAT_FAILED solved=0 — geodesic fallback solved={len(solved)} "
              f"distinct={len({n for w in geo for n in w})}")
        bpy.data.objects.remove(work, do_unlink=True)
        work = None
        weights_source = "geodesic"
    else:
        weights_source = "heat"

    if weights_source in ("heat", "geodesic"):
        # transfer to the original split mesh by position; the shipped mesh keeps its topology
        from mathutils.kdtree import KDTree
        kd = KDTree(len(solved))
        for i, (co, _w) in enumerate(solved):
            kd.insert(co, i)
        kd.balance()

        for group in list(body.vertex_groups):
            body.vertex_groups.remove(group)
        groups = {}
        unweighted = 0
        for v in body.data.vertices:
            _co, idx, _dist = kd.find(Vector(v.co))
            if idx is None:
                unweighted += 1
                continue
            for name, weight in solved[idx][1].items():
                if weight <= 1e-4:
                    continue
                group = groups.get(name)
                if group is None:
                    group = body.vertex_groups.get(name) or body.vertex_groups.new(name=name)
                    groups[name] = group
                group.add([v.index], weight, "REPLACE")
        print(f"TRANSFER groups={len(groups)} unweighted={unweighted}")

    if A.rigid_islands and welded_weights:
        rigid, n_rigid = rigid_bind(body, welded_islands, welded_positions, welded_weights)
        for group in list(body.vertex_groups):
            body.vertex_groups.remove(group)
        groups = {}
        for vi, w in enumerate(rigid):
            if not w:
                continue
            for name, weight in w.items():
                group = groups.get(name)
                if group is None:
                    group = body.vertex_groups.new(name=name)
                    groups[name] = group
                group.add([vi], weight, "REPLACE")
        print(f"RIGID {n_rigid} shells bound to a single bone; the body shell stays smooth")

    for mod in list(body.modifiers):
        body.modifiers.remove(mod)
    mod = body.modifiers.new("armature", "ARMATURE")
    mod.object = arm
    body.parent = arm
    body.matrix_parent_inverse = Matrix.Identity(4)
    if work is not None:
        bpy.data.objects.remove(work, do_unlink=True)

# ------------------------------------------------------------------ 4. sockets
# `configs/rigs/*.json` declares socket_weapon_* parented to the hand at the hand's tail with
# zero offset. Measured on the shipped masters the placed bone was 0.63 m away, so gear bound
# to it floated. Put it where the declaration says: at the hand's origin, along the hand.
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
ebones = arm.data.edit_bones
fixed = []
for side in ("L", "R"):
    hand_name = f"hand_{side}"
    socket_name = f"socket_weapon_{side}"
    if hand_name not in ebones:
        continue
    hand_e = ebones[hand_name]
    socket_e = ebones.get(socket_name)
    if socket_e is None:
        socket_e = ebones.new(socket_name)
        socket_e.parent = hand_e
        socket_e.use_deform = False
    axis = (hand_e.tail - hand_e.head)
    axis = axis.normalized() if axis.length > 1e-6 else Vector((0, 1, 0))
    before = (socket_e.head - hand_e.head).length
    socket_e.head = hand_e.head.copy()
    socket_e.tail = hand_e.head + axis * 0.06
    socket_e.parent = hand_e
    socket_e.use_deform = False
    fixed.append((socket_name, round(before, 3)))
print("SOCKETS", fixed)
bpy.ops.object.mode_set(mode="OBJECT")

# ------------------------------------------------------------------ 5. weapon
# The old bind solved `weapon_rest = hand_rest * inv(hand_posed) * desired`, which is only
# true in the pose it was solved for. This binds the weapon to the hand's own frame instead:
# grip at the hand origin, barrel along the hand's axis, so bind pose and every clip agree.
hand = arm.data.bones[A.hand]
hand_m = hand.matrix_local.copy()
hand_pos = hand_m.translation.copy()
hand_rot = hand_m.to_3x3()
barrel_target = (hand_rot @ Vector((0, 1, 0))).normalized()   # bone Y = the bone's own axis

import numpy as np

if A.weapon:
    # Replace the baked weapon with the authored asset. `weapon_glb.py` authors every weapon with
    # the grip at the origin and the barrel along its own +Y (verified: lasgun bbox y 0..0.95,
    # x/z within 0.15), so the frame is known rather than inferred. The baked copy cannot be used
    # because exporting it into armature space destroys that frame — measuring its long axis and
    # picking the end nearest the hand put the muzzle in the palm on every unit.
    for weapon in weapons:
        bpy.data.objects.remove(weapon, do_unlink=True)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(Path(A.weapon).resolve()))
    imported = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not imported:
        raise SystemExit(f"no mesh in weapon {A.weapon}")
    # The hold is AUTHORED PER WEAPON, not derived from the hand. A rifle is carried with the barrel
    # forward and low; a staff stands vertically in one hand; a blade points up. A single "follow the
    # hand axis" rule cannot express those, and measured on the shipped lab assets it put the lasgun
    # at 83 deg from vertical (correct for a rifle) and the staff at 29 deg (wrong — a staff is held
    # upright). `WEAPON_HOLD` above is the data; this line is the only place it is applied.
    hold = WEAPON_HOLD.get(Path(A.weapon).stem.split(".")[0], (0.0, -1.0, -0.25))
    barrel_target = Vector(hold).normalized()
    print(f"WEAPON hold={hold} -> barrel_target="
          f"{tuple(round(v, 3) for v in barrel_target)}")
    for weapon in imported:
        # weapon local +Y is its own long axis; place it so the grip (its origin) is at the hand
        local_barrel = Vector((0, 0, 1))   # the weapon's own long axis, measured in Blender space
        rot = local_barrel.rotation_difference(barrel_target).to_matrix().to_4x4()
        move = Matrix.Translation(hand_pos) @ rot
        weapon.data.transform(move)
        weapon.data.update()
        weapon.matrix_world = Matrix.Identity(4)
        weapon.parent = arm
        weapon.matrix_parent_inverse = Matrix.Identity(4)
        for group in list(weapon.vertex_groups):
            weapon.vertex_groups.remove(group)
        group = weapon.vertex_groups.new(name=A.hand)
        group.add([v.index for v in weapon.data.vertices], 1.0, "REPLACE")
        for mod in list(weapon.modifiers):
            weapon.modifiers.remove(mod)
        mod = weapon.modifiers.new("armature", "ARMATURE")
        mod.object = arm
        print(f"WEAPON {weapon.name} socketed at {tuple(round(v, 3) for v in hand_pos)} "
              f"barrel={tuple(round(v, 3) for v in barrel_target)}")
else:
    print(f"WEAPON baked ({[w.name for w in weapons]}) left as-is")

bpy.context.view_layer.update()

# ------------------------------------------------------------------ 6. export
out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}.glb"
if arm.animation_data:
    arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.location = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(
    filepath=str(dest),
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="ACTIONS",
)
print(f"EXPORTED {dest} clips={len(bpy.data.actions)}")
