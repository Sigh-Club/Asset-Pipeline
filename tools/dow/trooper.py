#!/usr/bin/env python3
"""IoA trooper exemplar: parts bound to the DoW biped, from the Gemini
turnaround (~/Downloads/id.jpeg, 178cm, silver plate / gold trim / blue cloth).

Same parts schema as mannequin.py -> pose_rig.py -> render_parts.py.
Geometry is positioned in the rig REST pose (our bind); `mat` is resolved to
a PBR material by render_parts.py.

    trooper.py <rig.json> <out_parts.json>
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import whm_v4_patch  # noqa: F401

import pose_whm as P
from mannequin import capsule

SIDES = 12
MAT = {  # name -> (base colour, roughness, metallic, emissive)
    "silver":   (0.82, 0.83, 0.85, 0.35, 1.0, None),
    "gold":     (0.83, 0.64, 0.21, 0.30, 1.0, None),
    "blue":     (0.16, 0.32, 0.55, 0.65, 0.0, None),
    "black":    (0.05, 0.05, 0.06, 0.55, 0.3, None),
    "gunmetal": (0.20, 0.21, 0.23, 0.45, 1.0, None),
    "lens":     (0.10, 0.55, 0.25, 0.25, 0.0, (0.2, 1.4, 0.6)),
}


def frame_of(a, b):
    d = np.asarray(b, float) - np.asarray(a, float)
    L = max(np.linalg.norm(d), 1e-6)
    axis = d / L
    tmp = np.array([0, 1, 0]) if abs(axis[1]) < 0.9 else np.array([1, 0, 0])
    x = np.cross(axis, tmp); x /= np.linalg.norm(x)
    return axis, x, np.cross(axis, x)


def box_between(a, b, w0, d0, w1=None, d1=None):
    """Tapered box a->b; w across `x`, d across the third axis."""
    w1 = w0 if w1 is None else w1
    d1 = d0 if d1 is None else d1
    axis, x, y = frame_of(a, b)
    L = np.linalg.norm(np.asarray(b) - np.asarray(a))
    verts, faces = [], []
    for t, (w, dd) in zip((0, 1), ((w0, d0), (w1, d1))):
        c = np.asarray(a) + axis * (t * L)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            verts.append(c + x * (sx * w / 2) + y * (sy * dd / 2))
    for i in range(4):
        j = (i + 1) % 4
        faces.append([i, j, 4 + j]); faces.append([i, 4 + j, 4 + i])
    return np.asarray(verts), faces


def sphere(c, r, squash=1.0, rings=6):
    c = np.asarray(c, float)
    verts, faces = [], []
    for i in range(rings + 1):
        phi = np.pi * i / rings
        for j in range(SIDES):
            th = 2 * np.pi * j / SIDES
            verts.append(c + r * np.array([np.sin(phi) * np.cos(th),
                                           np.cos(phi) * squash,
                                           np.sin(phi) * np.sin(th)]))
    for i in range(rings):
        for j in range(SIDES):
            a_ = i * SIDES + j
            b_ = i * SIDES + (j + 1) % SIDES
            c_ = (i + 1) * SIDES + (j + 1) % SIDES
            d_ = (i + 1) * SIDES + j
            faces.append([a_, b_, c_]); faces.append([a_, c_, d_])
    return np.asarray(verts), faces


def main(argv):
    rig_path, out = argv[1], argv[2]
    doc = json.loads(Path(rig_path).read_text())
    bones = doc["skeleton"]
    names = [b["name"] for b in bones]
    chain = P.world_chain(bones, {})
    X = {names[i]: chain[i][:3, 3].copy() for i in range(len(bones))}

    foot_y = min(X["bip01 l foot"][1], X["bip01 r foot"][1])
    s = 1.78 / max(X["bip01 head"][1] - foot_y, 1e-6)
    for k in X:
        X[k] = (X[k] - np.array([0, foot_y, 0])) * s

    parts = []

    def add(name, bone, geom, mat):
        verts, faces = geom
        parts.append({"name": name, "bone": bone, "mat": mat,
                      "verts": np.round(np.asarray(verts, float), 5).tolist(),
                      "tris": [list(map(int, f)) for f in faces]})

    pel, sp1, sp2 = X["bip01 pelvis"], X["bip01 spine1"], X["bip01 spine2"]
    head, neck = X["bip01 head"], X["bip01 spine2"]

    add("pelvis", "bip01 pelvis", box_between(sp1, pel, 0.30, 0.20, 0.26, 0.18), "black")
    add("abdomen", "bip01 spine1", box_between(sp1, sp1 + (sp2 - sp1) * 0.5, 0.30, 0.20), "silver")
    add("chest", "bip01 spine2", box_between(sp1 + (sp2 - sp1) * 0.5, sp2, 0.34, 0.22, 0.38, 0.20), "silver")
    cz = sp2 + np.array([0, 0.02, 0.11])
    add("chest_eagle", "bip01 spine2", box_between(cz, cz + np.array([0, 0.05, 0]), 0.13, 0.02), "gold")
    add("belt", "bip01 pelvis", box_between(sp1 - np.array([0, 0.02, 0]), sp1 + np.array([0, 0.02, 0]), 0.32, 0.22), "gold")
    tab_f = pel + np.array([0, -0.02, 0.10])
    tab_b = pel + np.array([0, -0.02, -0.10])
    add("tabard_front", "bip01 pelvis", box_between(tab_f, tab_f + np.array([0, -0.42, 0.01]), 0.20, 0.03, 0.24, 0.03), "blue")
    add("tabard_back", "bip01 pelvis", box_between(tab_b, tab_b + np.array([0, -0.30, -0.01]), 0.20, 0.03, 0.22, 0.03), "blue")
    bp = sp1 + np.array([0, 0.06, -0.17])
    add("pack", "bip01 spine1", box_between(bp, bp + np.array([0, 0.30, -0.07]), 0.26, 0.16), "gunmetal")
    for dz, nm in ((-0.06, "l"), (0.06, "r")):
        v0 = bp + np.array([dz, 0.03, -0.11])
        add(f"pack_vent_{nm}", "bip01 spine1",
            capsule(v0, v0 + np.array([0, 0.22, -0.02]), 0.035, 0.035, sides=8, rings=1), "gunmetal")
    add("helmet", "bip01 head", sphere((head + neck) / 2 + np.array([0, 0.05, 0]), 0.115, 1.15), "silver")
    vz = head + np.array([0, 0.02, 0.07])
    add("visor", "bip01 head", box_between(vz - np.array([0.07, 0, 0]), vz + np.array([0.07, 0.04, 0]), 0.10, 0.02), "lens")
    for side, tag in ((" l ", "l"), (" r ", "r")):
        ua, fa, ha = X[f"bip01{side}upperarm"], X[f"bip01{side}forearm"], X[f"bip01{side}hand"]
        sh = sp2 + (ua - sp2) * 0.4
        pc = (sh + ua) / 2 + np.array([0, 0.03, 0])
        add(f"{tag}_pauldron", f"bip01{side}upperarm", sphere(pc, 0.115, 0.6), "silver")
        add(f"{tag}_pad_rim", f"bip01{side}upperarm", sphere(pc, 0.119, 0.62), "gold")
        add(f"{tag}_uparm", f"bip01{side}upperarm", capsule(sh, fa, 0.055, 0.05), "silver")
        add(f"{tag}_forearm", f"bip01{side}forearm", capsule(fa, ha, 0.05, 0.045), "silver")
        add(f"{tag}_glove", f"bip01{side}hand", sphere(ha, 0.05, 0.8), "black")
    for side, tag in ((" l ", "l"), (" r ", "r")):
        th, ca, fo = X[f"bip01{side}thigh"], X[f"bip01{side}calf"], X[f"bip01{side}foot"]
        toe = X[f"bip01{side}toe0"]
        hip = pel + (th - pel) * 0.3
        add(f"{tag}_thigh", f"bip01{side}thigh", capsule(hip, th, 0.085, 0.075), "silver")
        add(f"{tag}_knee", f"bip01{side}calf", sphere((th + ca) / 2, 0.075, 0.9), "gold")
        add(f"{tag}_shin", f"bip01{side}calf", capsule(ca, fo + np.array([0, 0.05, 0]), 0.07, 0.06), "silver")
        boot_f = fo + (toe - fo) * 0.8 + np.array([0, 0.02, 0])
        add(f"{tag}_boot", f"bip01{side}foot", box_between(fo - np.array([0.05, 0.05, 0]), boot_f, 0.11, 0.20), "black")
    gr = X["bip01 r hand"]
    g0 = gr + np.array([-0.03, 0.02, 0.10])
    add("gun_body", "bip01 r hand", box_between(g0, g0 + np.array([0.06, 0.10, -0.34]), 0.07, 0.16), "gunmetal")
    add("gun_barrel", "bip01 r hand", capsule(g0 + np.array([0.03, 0.06, -0.30]),
                                              g0 + np.array([0.03, 0.06, -0.55]), 0.025, 0.025, sides=8, rings=1), "gunmetal")
    add("gun_mag", "bip01 r hand", box_between(g0 + np.array([0, -0.06, -0.10]),
                                               g0 + np.array([0.05, -0.16, -0.02]), 0.05, 0.08), "gunmetal")

    Path(out).write_text(json.dumps({"bind": "rest", "skeleton_source": str(rig_path),
                                     "scale": s, "mats": MAT, "parts": parts}))
    print(f"{out}: {len(parts)} parts, {sum(len(p['verts']) for p in parts)} verts, scale {s:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
