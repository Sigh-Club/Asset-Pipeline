#!/usr/bin/env python3
"""Skin a DoW WHM mesh into an arbitrary animation frame -> Wavefront OBJ.

WHM MSLC vertices are stored in model-space bind pose; each vertex carries
3 weights + 4 bone indices (4th weight implicit).  World matrices come from
the bone hierarchy (SKEL rest / ANIM per-frame local pos+quat):

    M_i(f) = prod(parents) L_i(f),   L = trans(pos) * rot(quat)
    v'(f)  = sum_k w_k * M_k(f) * M_k(rest)^-1 * v

Output OBJ has one object per submesh (names match obj_writer convention, so
tools/dow/blender_ork_import.py textures them from the atlases unchanged).

Usage:
    pose_whm.py model.whm anims.json ANIM_NAME FRAME out.obj [--rest]
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import whm_v4_patch

whm_v4_patch.patch()

from whm_animdata import load_whm
from relic.chunky.chunk.chunk import FolderChunk
from relic.chunky_formats.dow.whm.whm import MsgrChunk


def quat_to_mat(q):
    x, y, z, w = (float(c) for c in q)
    n = np.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def local_matrix(pos, rot):
    m = np.eye(4)
    m[:3, :3] = quat_to_mat(rot)
    m[:3, 3] = pos
    return m


def world_chain(bones, overrides):
    """overrides: name -> (pos, rot); bones missing from it use rest pose."""
    world = {}
    for i, bone in enumerate(bones):
        name = bone["name"]
        pos, rot = overrides.get(name, (bone["pos"], bone["rot"]))
        local = local_matrix(np.asarray(pos, float), np.asarray(rot, float))
        parent = bone["parent"]
        world[i] = world[parent] @ local if parent >= 0 else local
    return world


def pose_overrides(anim, frame):
    """Nearest-keyed local pos/quat per bone at `frame`."""
    pose = {}
    for name, track in anim["bones"].items():
        pos = _nearest(track["pos"], frame)
        rot = _nearest(track["rot"], frame)
        if pos and rot:
            pose[name] = (pos, rot)
    return pose


def _nearest(keys, frame):
    if not keys:
        return None
    best = min((int(k) for k in keys), key=lambda f: abs(f - frame))
    return keys[str(best)]


def _walk(node):
    for child in node.chunks:
        yield child
        if isinstance(child, FolderChunk):
            yield from _walk(child)


def mesh_parts(whm_root):
    """[(global bone names, positions, weights(N,4), idx(N,4), submeshes, normals, uvs)]"""
    rsgm = whm_root.chunks[0]
    msgr = next(n for n in _walk(rsgm)
                if getattr(n.header, "id", "") == "MSGR" and isinstance(n, FolderChunk))
    meshes = MsgrChunk.convert(msgr).mslc
    parts = []
    for mslc in meshes:
        data = mslc.data
        v = data.vertex_data
        n = len(v.positions)
        # global skeleton indices via the mesh's bone-ref table
        global_of_slot = [b.index for b in (data.bones or [])]
        if v.bone_weights:
            w = np.zeros((n, 4), np.float32)
            idx = np.zeros((n, 4), np.int32)
            for i, (ww, ii) in enumerate(v.bone_weights):
                w[i, :3] = ww
                idx[i] = ii
                w[i, 3] = max(0.0, 1.0 - float(np.sum(ww)))
            s = w.sum(axis=1, keepdims=True)
            s[s == 0] = 1
            w /= s
        else:
            w = idx = None
        parts.append((global_of_slot, np.asarray(v.positions, np.float32), w, idx,
                      [(sm.texture_path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                        np.asarray(sm.triangles, np.int32))
                       for sm in data.sub_meshes],
                      np.asarray(v.normals, np.float32), np.asarray(v.uvs, np.float32)))
    return parts


def skin(parts, bones, world_rest, world_pose):
    """{submesh: (verts, tris, normals, uvs)} posed into world space."""
    n_bones = len(bones)
    delta = {}
    for g in range(n_bones):
        m = world_pose[g] @ np.linalg.inv(world_rest[g])
        delta[g] = (m[:3, :3], m[:3, 3])
    out = {}
    for mi, (slots, pos, w, idx, subs, normals, uvs) in enumerate(parts):
        if w is None:
            for si, (sub, tris) in enumerate(subs):
                out[f"{mi:02d}{si:02d}_{sub}"] = (pos, tris, normals, uvs)
            continue
        # vertex bone indices are GLOBAL skeleton ids; 255 = unweighted pad
        gidx = np.where(idx >= n_bones, 0, idx)
        acc = np.zeros_like(pos)
        nacc = np.zeros_like(normals)
        for k in range(4):
            gcol, wcol = gidx[:, k], w[:, k]
            R = np.zeros((len(pos), 3, 3), np.float32)
            t = np.zeros((len(pos), 3), np.float32)
            for g in np.unique(gcol):
                mask = gcol == g
                Rg, tg = delta[int(g)]
                R[mask] = Rg
                t[mask] = tg
            acc += (np.einsum('nj,njk->nk', pos, R) + t) * wcol[:, None]
            nacc += np.einsum('nj,njk->nk', normals, R) * wcol[:, None]
        for si, (sub, tris) in enumerate(subs):
            out[f"{mi:02d}{si:02d}_{sub}"] = (acc, tris, nacc, uvs)
    return out


def write_obj(path, posed):
    lines, v_base = [], 1  # OBJ indices are cumulative across objects
    for key, (v, tris, nrm, uv) in posed.items():
        name, material = key.split("_", 1) if "_" in key else (key, key)
        lines.append(f"o {key}")
        lines += [f"v {a:.6f} {b:.6f} {c:.6f}" for a, b, c in v]
        lines += [f"vn {a:.4f} {b:.4f} {c:.4f}" for a, b, c in nrm]
        lines += [f"vt {a:.6f} {b:.6f}" for a, b in uv]
        lines.append(f"usemtl {material}")
        lines += [f"f {a+v_base}/{a+v_base}/{a+v_base} "
                  f"{b+v_base}/{b+v_base}/{b+v_base} "
                  f"{c+v_base}/{c+v_base}/{c+v_base}" for a, b, c in tris]
        v_base += len(v)
    Path(path).write_text("\n".join(lines) + "\n")


def main(argv):
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv[1:] if not a.startswith("--")]
    whm_path, anim_json, anim_name, frame, out = args[:5]
    rest_bind = "--bind-rest" in flags
    doc = json.loads(Path(anim_json).read_text())
    bones = doc["skeleton"]
    root = load_whm(whm_path)
    parts = mesh_parts(root)
    if rest_bind or anim_name not in doc["animations"]:
        # SKEL-rest bind: exact only when the engine bind == skel (not true for
        # Definitive assets - see docs); kept for debugging.
        bind = world_chain(bones, {})
        if rest_bind:
            posed = skin(parts, bones, bind, bind)
            write_obj(out, posed)
            print(f"{out}: rest bind")
            return 0
    anim = doc["animations"][anim_name]
    # EMPIRICAL: the mesh bind == the animation's frame 0 (frame 0 skinning is
    # the identity, later frames stay coherent); SKEL-rest bind tears limbs off.
    bind = world_chain(bones, pose_overrides(anim, 0))
    world_pose = world_chain(bones, pose_overrides(anim, int(frame)))
    posed = skin(parts, bones, bind, world_pose)
    write_obj(out, posed)
    n_verts = sum(len(v) for v, _, _, _ in posed.values())
    print(f"{out}: {len(posed)} submeshes, {n_verts} verts "
          f"({'rest' if rest_bind else f'{anim_name} f{frame}'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
