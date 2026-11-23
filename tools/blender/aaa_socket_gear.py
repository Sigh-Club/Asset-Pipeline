#!/usr/bin/env python3
"""aaa_socket_gear.py — extract rigidly-attached gear and parent it to its socket.

Step 2 of docs/ASSEMBLY_MODEL.md §7.3. The classifier is measured, not guessed: a
face whose every vertex is weighted >=0.95 to a single bone moves rigidly with that
bone, so it *is* rigid gear and does not need a skin. Measured on line infantry
(2026-11-23), the rigid clusters are:

    Head        4,026 faces (helmet)      RightUpLeg  3,706 (thigh plate)
    LeftFoot    3,330 (boot)              RightFoot   2,736 (boot)
    RightToeBase/LeftUpLeg/RightLeg/LeftToeBase  462-1,020 each

There is **no hand cluster**, because the rifle was skinned into the body rather than
attached — so the weapon is not yet separable, and that is recorded rather than faked.
Step 3 (real shipped wargear) is what fixes it.

For each cluster above the size floor this script:
  1. separates the faces into their own object
  2. records the rest transform, parents the object to the socket bone
     (parent_type='BONE') and restores the world matrix, so it does not move
  3. drops the armature modifier and the vertex groups — it is rigid now
  4. exports it as gear/<id>_gear_<bone>.glb
  5. VERIFIES by posing the rig from a clip at two frames and checking that the
     part's transform relative to its bone is unchanged (the falsifier from §7.3:
     drift means the offset was computed in the wrong space)

Usage:
  blender -b -P tools/blender/aaa_socket_gear.py -- \
      --glb output/aaa/line_infantry/line_infantry_aaa.glb \
      --out output/aaa/line_infantry --id line_infantry --min-faces 400
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

_ap = argparse.ArgumentParser()
_ap.add_argument('--glb', required=True)
_ap.add_argument('--out', required=True)
_ap.add_argument('--id', required=True)
_ap.add_argument('--min-faces', type=int, default=400,
                 help='minimum faces for a rigid cluster to count as a gear piece')
_ap.add_argument('--rigid-weight', type=float, default=0.95)
a = _ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])

OUT = Path(a.out).resolve()
GEAR = OUT / 'gear'
GEAR.mkdir(parents=True, exist_ok=True)

# which socket a bone's gear hangs from (sockets are created by aaa_assemble.py)
# must match the SOCKETS table in aaa_assemble.py (one source of truth would be
# better; until then this is the mirror and it is checked by the manifest)
BONE_TO_SOCKET = {
    'Head': 'SOCKET_head', 'Spine2': 'SOCKET_back', 'Hips': 'SOCKET_hips',
    'RightHand': 'SOCKET_weapon_r', 'LeftHand': 'SOCKET_weapon_l',
    'RightUpLeg': 'SOCKET_thigh_r', 'LeftUpLeg': 'SOCKET_thigh_l',
    'RightLeg': 'SOCKET_knee_r',
    'RightFoot': 'SOCKET_boot_r', 'LeftFoot': 'SOCKET_boot_l',
    'RightToeBase': 'SOCKET_toe_r', 'LeftToeBase': 'SOCKET_toe_l',
}


def log(m: str) -> None:
    print(f'[aaa_socket_gear] {m}', flush=True)


def rigid_clusters(body) -> dict[str, list[int]]:
    """Faces whose vertices are all >= threshold on one bone, grouped by that bone."""
    gname = {g.index: g.name for g in body.vertex_groups}
    dom: dict[int, tuple[str, float]] = {}
    for v in body.data.vertices:
        if not v.groups:
            continue
        g = max(v.groups, key=lambda x: x.weight)
        dom[v.index] = (gname.get(g.group, '?'), g.weight)
    clusters: dict[str, list[int]] = {}
    for p in body.data.polygons:
        bones = [dom.get(i) for i in p.vertices]
        if any(b is None or w < a.rigid_weight for b, w in bones):
            continue
        names = {b for b, _ in bones}
        if len(names) != 1:
            continue
        clusters.setdefault(names.pop(), []).append(p.index)
    return clusters


def separate_faces(body, face_indices: list[int], name: str):
    """Duplicate the body, keep only these faces, return the new object."""
    dup = body.copy()
    dup.data = body.data.copy()
    dup.name = name
    bpy.context.collection.objects.link(dup)
    bpy.context.view_layer.objects.active = dup
    for o in bpy.data.objects:
        o.select_set(o is dup)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.object.mode_set(mode='OBJECT')
    keep = set(face_indices)
    for i, p in enumerate(dup.data.polygons):
        p.select = i in keep
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    # the SELECTED split leaves the wanted geometry in a sibling object
    siblings = [o for o in bpy.data.objects
                if o.name.startswith(dup.name + '.') and o.type == 'MESH']
    if not siblings:
        bpy.data.objects.remove(dup, do_unlink=True)
        return None
    part = max(siblings, key=lambda o: len(o.data.polygons))
    part.name = name
    bpy.data.objects.remove(dup, do_unlink=True)
    for s in siblings:
        if s is not part and s.name in bpy.data.objects:
            bpy.data.objects.remove(s, do_unlink=True)
    return part


def attach_to_socket(part, arm, bone: str, socket: str) -> bool:
    """Parent the part to the socket bone without moving it, then make it rigid."""
    rest = part.matrix_world.copy()
    part.parent = arm
    part.parent_type = 'BONE'
    part.parent_bone = bone
    part.matrix_world = rest                     # keep the rest pose position
    for m in list(part.modifiers):
        if m.type == 'ARMATURE':
            part.modifiers.remove(m)
    part.vertex_groups.clear()
    return True


def relative_matrix(part, arm, bone: str) -> Matrix:
    """Part transform expressed in the POSE bone's space.

    Using the rest matrix (matrix_local) here was wrong: it does not move when the rig
    is posed, so a correctly attached part appeared to drift. The pose matrix is the
    only correct frame for this test.
    """
    pb = arm.pose.bones.get(bone)
    bone_world = arm.matrix_world @ (pb.matrix if pb else arm.data.bones[bone].matrix_local)
    return bone_world.inverted() @ part.matrix_world


def verify_follow(part, arm, bone: str) -> dict:
    """Pose the rig from a clip and check the part stays fixed relative to its bone."""
    if not arm.animation_data or not arm.animation_data.action:
        arm.animation_data_create()
        acts = [a for a in bpy.data.actions if 'idle' in a.name.lower()] or list(bpy.data.actions)
        if not acts:
            return {'checked': False, 'reason': 'no actions'}
        arm.animation_data.action = acts[0]
    scene = bpy.context.scene
    scene.frame_set(scene.frame_start)
    bpy.context.view_layer.update()
    m0 = relative_matrix(part, arm, bone).copy()
    scene.frame_set(max(scene.frame_start + 10, scene.frame_end // 2))
    bpy.context.view_layer.update()
    m1 = relative_matrix(part, arm, bone)
    drift = max(abs(m0[r][c] - m1[r][c]) for r in range(4) for c in range(4))
    return {'checked': True, 'drift': round(drift, 6), 'follows_bone': drift < 1e-4}


def main() -> int:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(a.glb).resolve()))
    body = max((o for o in bpy.data.objects if o.type == 'MESH'), key=lambda o: len(o.data.polygons))
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    log(f'source: {body.name} {len(body.data.polygons)} faces, rig {arm.name}')

    # sockets are defined on the SKELETON asset (skeleton.glb), not in this mesh file,
    # so existence is checked against the manifest's socket list rather than the scene
    man_path = OUT / 'unit.manifest.json'
    known_sockets = set()
    if man_path.exists():
        try:
            known_sockets = {s['name'] for s in json.loads(man_path.read_text())
                             .get('skeleton', {}).get('sockets', [])}
        except Exception:
            known_sockets = set()
    log(f'sockets declared on the skeleton: {sorted(known_sockets)}')

    clusters = rigid_clusters(body)
    chosen = {b: f for b, f in clusters.items() if len(f) >= a.min_faces}
    log(f'rigid clusters >= {a.min_faces} faces: '
        + ', '.join(f'{b}={len(f)}' for b, f in sorted(chosen.items(), key=lambda kv: -len(kv[1]))))

    gear = []
    for bone, faces in sorted(chosen.items(), key=lambda kv: -len(kv[1])):
        socket = BONE_TO_SOCKET.get(bone, f'SOCKET_{bone}')
        part = separate_faces(body, faces, f'{a.id}_gear_{bone}')
        if part is None:
            log(f'{bone}: separation produced nothing')
            continue
        tris = len(part.data.polygons)
        attach_to_socket(part, arm, bone, socket)
        follow = verify_follow(part, arm, bone)
        path = GEAR / f'{a.id}_gear_{bone}.glb'
        for o in bpy.data.objects:
            o.select_set(o in (part, arm))
        bpy.context.view_layer.objects.active = part
        bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB',
                                  use_selection=True, export_apply=False,
                                  export_image_format='AUTO')
        socket_exists = socket in known_sockets
        if not socket_exists:
            log(f'note: {socket} not declared on the skeleton; attaching to bone {bone}')
        gear.append({'part': f'gear_{bone}', 'attach_bone': bone,
                     'socket': socket if socket_exists else None,
                     'attachment': 'socket' if socket_exists else 'bone',
                     'faces': tris, 'path': str(path),
                     'mb': round(path.stat().st_size / 1e6, 2), 'follow': follow})
        log(f'{bone} -> {socket}: {tris} faces, follows_bone={follow.get("follows_bone")} '
            f'drift={follow.get("drift")}')
        bpy.data.objects.remove(part, do_unlink=True)

    # The gear was COPIED out of the body, so the body still contains it. A correct
    # assembly is body + gear, not body-with-gear + gear: delete the rigid faces from
    # the body and export it as the body part of the set.
    if chosen:
        rigid_faces = {i for faces in chosen.values() for i in faces}
        bpy.context.view_layer.objects.active = body
        for o in bpy.data.objects:
            o.select_set(o is body)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        for i, poly in enumerate(body.data.polygons):
            poly.select = i in rigid_faces
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.delete(type='FACE')
        bpy.ops.object.mode_set(mode='OBJECT')
        body_path = OUT / f'{a.id}_body.glb'
        for o in bpy.data.objects:
            o.select_set(o in (body, arm))
        bpy.ops.export_scene.gltf(filepath=str(body_path), export_format='GLB',
                                  use_selection=True, export_apply=False,
                                  export_image_format='AUTO')
        log(f'body without rigid gear: {len(body.data.polygons)} faces -> {body_path.name}')

    manifest_path = OUT / 'unit.manifest.json'
    if manifest_path.exists():
        man = json.loads(manifest_path.read_text())
    else:
        man = {'id': a.id, 'parts': []}
    man['rigid_gear'] = gear
    man['body_without_gear'] = {'path': str(OUT / f'{a.id}_body.glb'),
                                'faces': len(body.data.polygons) if chosen else None,
                                'note': 'body + rigid_gear + parts is the assembly; the combined '
                                        f'{a.id}_aaa.glb remains the contract-checked reference'}
    man['rigid_gear_note'] = ('Rigid pieces are parented to their socket bone and carry no skin. '
                              'The weapon is NOT among them: it was skinned into the body, so it is '
                              'not separable by weight — see docs/ASSEMBLY_MODEL.md §7.3 step 3.')
    manifest_path.write_text(json.dumps(man, indent=2))
    log(f'{len(gear)} gear piece(s) -> unit.manifest.json')
    return 0


sys.exit(main())
