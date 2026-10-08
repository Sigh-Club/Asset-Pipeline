#!/usr/bin/env python3
"""Build a capsule-mannequin bound to a DoW biped skeleton (proof asset for
the retarget pipeline).

Parts are rigid-bound to one bone each (the DoW way: boots/helm/plate are
single-bone meshes); capsules span parent->child joint positions in the BIND
pose.  Output JSON: {"bind": "rest", "parts": [{name, bone, verts, tris}]}
consumed by `pose_rig.py`.

    mannequin.py <rig.json> <out_parts.json> [scale]

Rig JSON = whm_animdata output (skeleton + animations); bind pose = the
skeleton rest (our own assets define their own bind - the frame0-bind quirk
is DoW-data-specific and handled inside pose_whm.py).
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import whm_v4_patch  # noqa: F401  (needed before pose_whm imports relic)

import pose_whm as P

SEGMENTS = [  # (part, bone it follows, parent joint bone, child joint bone, r0, r1)
    ("pelvis",   "bip01 pelvis",  "bip01 pelvis",  "bip01 spine",   0.16, 0.13),
    ("torso",    "bip01 spine1",  "bip01 spine",   "bip01 spine2",  0.15, 0.17),
    ("chest",    "bip01 spine2",  "bip01 spine1",  "bip01 neck",    0.19, 0.15),
    ("head",     "bip01 head",    "bip01 neck",    "bip01 head",    0.10, 0.13),
    ("l_uparm",  "bip01 l upperarm", "bip01 l upperarm", "bip01 l forearm", 0.07, 0.06),
    ("l_forearm","bip01 l forearm",  "bip01 l forearm",  "bip01 l hand",    0.06, 0.05),
    ("l_hand",   "bip01 l hand",     "bip01 l hand",     "bip01 l toe0",    0.05, 0.04),
    ("r_uparm",  "bip01 r upperarm", "bip01 r upperarm", "bip01 r forearm", 0.07, 0.06),
    ("r_forearm","bip01 r forearm",  "bip01 r forearm",  "bip01 r hand",    0.06, 0.05),
    ("r_hand",   "bip01 r hand",     "bip01 r hand",     "bip01 r toe0",    0.05, 0.04),
    ("l_thigh",  "bip01 l thigh", "bip01 l thigh", "bip01 l calf",  0.09, 0.08),
    ("l_calf",   "bip01 l calf",  "bip01 l calf",  "bip01 l foot",  0.08, 0.07),
    ("l_foot",   "bip01 l foot",  "bip01 l foot",  "bip01 l toe0",  0.07, 0.06),
    ("r_thigh",  "bip01 r thigh", "bip01 r thigh", "bip01 r calf",  0.09, 0.08),
    ("r_calf",   "bip01 r calf",  "bip01 r calf",  "bip01 r foot",  0.08, 0.07),
    ("r_foot",   "bip01 r foot",  "bip01 r foot",  "bip01 r toe0",  0.07, 0.06),
]
SIDES = 10


def capsule(a, b, r0, r1, sides=SIDES, rings=3):
    """Tapered capsule between points a,b; returns (verts(N,3), tris(M,3))."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    L = max(np.linalg.norm(d), 1e-6)
    axis = d / L
    tmp = np.array([0, 1, 0]) if abs(axis[1]) < 0.9 else np.array([1, 0, 0])
    x = np.cross(axis, tmp); x /= np.linalg.norm(x)
    y = np.cross(axis, x)
    t2 = np.linspace(0, 2 * np.pi, sides, endpoint=False)
    ang = np.stack([np.cos(t2), np.sin(t2)], 1)
    verts, ring_base = [a - axis * r0 * 0.6], []
    for i in range(rings + 1):
        t = i / rings
        r = np.interp(t, [0, 1], [r0, r1])
        centre = a + axis * (t * L)
        ring = centre + np.outer(ang[:, 0] * r, x) + np.outer(ang[:, 1] * r, y)
        ring_base.append(len(verts))
        verts += list(ring)
    cap = len(verts)
    verts.append(b + axis * r1 * 0.6)
    verts = np.asarray(verts)
    tris = []
    for ring_i in range(len(ring_base) - 1):
        base0, base1 = ring_base[ring_i], ring_base[ring_i + 1]
        for s in range(sides):
            s2 = (s + 1) % sides
            tris.append((base0 + s, base0 + s2, base1 + s2))
            tris.append((base0 + s, base1 + s2, base1 + s))
    last = ring_base[-1]
    for s in range(sides):
        s2 = (s + 1) % sides
        tris.append((last + s, last + s2, cap))
    return verts, [list(map(int, t)) for t in tris]


def main(argv):
    rig_path, out = argv[1], argv[2]
    doc = json.loads(Path(rig_path).read_text())
    bones = doc["skeleton"]
    names = [b["name"] for b in bones]
    chain = P.world_chain(bones, {})  # rest pose = our bind
    pos = {names[i]: chain[i][:3, 3] for i in range(len(bones))}
    parts = []
    for part, bone, jA, jB, r0, r1 in SEGMENTS:
        if jA not in pos or jB not in pos:
            continue
        if part == "head":
            a = pos["bip01 neck"]
            b = pos["bip01 head"] + (pos["bip01 head"] - pos["bip01 neck"]) * 1.4
        else:
            a, b = pos[jA], pos[jB]
        verts, tris = capsule(np.asarray(a), np.asarray(b), r0, r1)
        parts.append({"name": part, "bone": bone,
                      "verts": np.round(verts, 5).tolist(), "tris": tris})
    Path(out).write_text(json.dumps({"bind": "rest", "skeleton_source": str(rig_path),
                                     "parts": parts}))
    n = sum(len(p["verts"]) for p in parts)
    print(f"{out}: {len(parts)} parts, {n} verts, bind=rest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
