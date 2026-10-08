#!/usr/bin/env python3
"""Skin arbitrary bound-meshes ("our" assets) with DoW animation data.

The bridge that lets original models play the entire decompressed DoW clip
library: bind parts to `bip01`-named bones (rigid per part, like DoW's own
props, or weighted), then replay any whm_animdata clip:

    pose_rig.py parts.json rig.json ANIM FRAME out.obj

parts.json = mannequin.py output {"parts":[{name,bone,verts,tris}]} (rigid);
extend per part with "weights": [{"bone":..,"w":..}] for smooth skinning.
Our bind pose = the rig's rest (skeleton) pose; DoW's frame0-bind quirk is
internal to their data and handled in pose_whm.py.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import whm_v4_patch  # noqa: F401

import pose_whm as P


def load_parts(path):
    doc = json.loads(Path(path).read_text())
    for p in doc["parts"]:
        p["verts"] = np.asarray(p["verts"], np.float32)
        p["tris"] = np.asarray(p["tris"], np.int32)
    return doc


NAMES = {}


def pose_part(verts, binding, world_bind, world_pose):
    """binding: bone-name string (rigid) or [{"bone":..,"w":..}] weighted."""
    if isinstance(binding, str):
        binding = [{"bone": binding, "w": 1.0}]
    acc = np.zeros_like(verts)
    for b in binding:
        g = NAMES.get(b["bone"])
        if g is None:
            continue
        m = world_pose[g] @ np.linalg.inv(world_bind[g])
        acc += float(b["w"]) * (verts @ m[:3, :3].T + m[:3, 3])
    return acc


def main(argv):
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv[1:] if not a.startswith("--")]
    parts_path, rig_path, anim, frame, out = args[:5]
    skip_stale = "--respect-stale" in flags
    parts_doc = load_parts(parts_path)
    rig = json.loads(Path(rig_path).read_text())
    bones = rig["skeleton"]
    NAMES.clear()
    NAMES.update({b["name"]: i for i, b in enumerate(bones)})
    if anim not in rig["animations"]:
        print(f"anim {anim!r} not in rig animations")
        return 2
    world_bind = P.world_chain(bones, {})  # our bind = rest
    world_pose = P.world_chain(bones, P.sample(rig["animations"][anim], int(frame), skip_stale))

    lines, base = [], 1  # OBJ indices cumulative across objects
    for part in parts_doc["parts"]:
        v = pose_part(part["verts"], part["bone"], world_bind, world_pose)
        lines.append(f"o {part['name']}")
        lines += [f"v {a:.6f} {b:.6f} {c:.6f}" for a, b, c in v]
        lines.append(f"usemtl {part['name']}")
        lines += [f"f {a+base} {b+base} {c+base}" for a, b, c in part["tris"]]
        base += len(v)
    Path(out).write_text("\n".join(lines) + "\n")
    print(f"{out}: {len(parts_doc['parts'])} parts posed ({anim} f{frame})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
