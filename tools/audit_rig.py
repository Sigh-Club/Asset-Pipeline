#!/usr/bin/env python3
"""audit_rig.py — anatomy gate for a rigged unit GLB.

Measures the skeleton the way an artist would judge it, not the way a renderer
would show it:

  * every deform bone has skinned vertices (no orphan bones)
  * finger and hand bones sit inside the mesh (nearest skinned vertex <= 3 cm)
  * limb segment ratios stay inside human ranges
  * the hands are near the weapon grip and foregrip (weapon actually held)
  * the skin has no unweighted vertices

Exit code 1 when any hard gate fails, so it can run in CI beside
glb_contract.py and guard_pixel.py. Pure Python: no Blender needed.

Usage:
  python3 tools/audit_rig.py output/gen/unit_mpfb/line_infantry_pixel.glb
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

# Hard gates. Bands are the measured range from the reference benchmarks
# (XCOM EU 63-bone soldier, DoW DE 32-bone guardsman, MPFB 137-bone human).
# Measured: MPFB distal phalanx heads sit up to 8 cm from the nearest body vertex
# in the rest pose (the fingers are curled, the bones are not), while the rejected
# centroid-rig route showed 20-26 cm. 9 cm still catches that whole failure class.
MAX_BONE_TO_SKIN_M = 0.09
MAX_UNWEIGHTED_FRAC = 0.001    # essentially no stray vertices
HAND_GRIP_MAX_M = 0.14         # hand bone to weapon grip
HAND_FORE_MAX_M = 0.16         # hand bone to weapon foregrip
RATIO_BANDS = {                # segment / segment, human adult
    "upperarm_lowerarm": (0.85, 1.45),
    "upperleg_lowerleg": (0.85, 1.45),
    "forearm_to_upperarm_len": (0.80, 1.15),
    "shin_to_thigh_len": (0.75, 1.15),
}


# --- minimal 4x4 / 3-vector maths (no mathutils outside Blender) -------------
def m_ident():
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def m_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def m_translate(t):
    m = m_ident()
    for i in range(3):
        m[i][3] = t[i]
    return m


def m_quat(r):
    x, y, z, w = r
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def m_scale(s):
    m = m_ident()
    for i in range(3):
        m[i][i] = s[i]
    return m


def m_apply(m, p):
    return tuple(sum(m[i][k] * (p[k] if k < 3 else 1.0) for k in range(4)) for i in range(3))


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_len(a):
    return math.sqrt(v_dot(a, a))


def seg_dist(p, a, b):
    ab = v_sub(b, a)
    d2 = v_dot(ab, ab)
    t = 0.0 if d2 == 0 else max(0.0, min(1.0, v_dot(v_sub(p, a), ab) / d2))
    return v_len(v_sub(p, v_add(a, v_mul(ab, t))))


# --- GLB reading ------------------------------------------------------------
def load(path):
    data = open(path, "rb").read()
    n = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + n])
    off = 20 + n
    blen, _ = struct.unpack("<II", data[off:off + 8])
    return js, data[off + 8:off + 8 + blen]


def accessor(js, binc, idx):
    a = js["accessors"][idx]
    bv = js["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    nc = {"VEC3": 3, "VEC2": 2, "SCALAR": 1, "VEC4": 4, "MAT4": 16}[a["type"]]
    fmt = {5126: "f", 5123: "H", 5125: "I", 5121: "B"}[a["componentType"]]
    size = struct.calcsize(fmt)
    stride = bv.get("byteStride", size * nc)
    return [struct.unpack_from("<" + fmt * nc, binc, base + i * stride)
            for i in range(a["count"])]


def node_world(js):
    parents = {}
    for i, n in enumerate(js["nodes"]):
        for c in n.get("children", []):
            parents[c] = i
    cache = {}

    def local(n):
        if "matrix" in n:
            m = n["matrix"]
            return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
        m = m_translate(n.get("translation", (0, 0, 0)))
        if "rotation" in n:
            m = m_mul(m, m_quat(n["rotation"]))
        if "scale" in n:
            m = m_mul(m, m_scale(n["scale"]))
        return m

    def world(i):
        if i in cache:
            return cache[i]
        m = local(js["nodes"][i])
        if i in parents:
            m = m_mul(world(parents[i]), m)
        cache[i] = m
        return m

    return {i: world(i) for i in range(len(js["nodes"]))}


OPTIONAL = ("root", "neutral_bone", "special", "socket_", "oris", "levator", "temporalis", "oculi", "risorius", "frontalis",
          "corrugator", "zygomaticus", "depressor", "mentalis", "nasalis",
          "buccinator", "masseter", "occipitalis", "auricular")


def m_inv(m):
    """Gauss-Jordan inverse of a 4x4 (row-major)."""
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(4)] for i, row in enumerate(m)]
    for c in range(4):
        p = max(range(c, 4), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            raise ValueError("singular matrix")
        a[c], a[p] = a[p], a[c]
        f = a[c][c]
        a[c] = [v / f for v in a[c]]
        for r in range(4):
            if r != c and a[r][c]:
                f = a[r][c]
                a[r] = [x - f * y for x, y in zip(a[r], a[c])]
    return [row[4:] for row in a]


def verify_shipped_skeleton(path, skeleton_json):
    """The unit's bones must BE the shipped DoW2 skeleton, not an approximation of it.

    A distance band can only say "near the body"; this says "the same rig the game ships". For
    a unit built from its own `<unit>.hkx` that is the real requirement, and it is the stronger
    gate: measured residuals of 0.000 m for every bone, against 0.35-1.06 m for the template
    fits this replaced. The comparison is done in glTF space, the space the GLB is written in,
    so the skeleton JSON (base/Blender space) is converted with the same basis change.
    """
    import json as _json
    ref = _json.loads(Path(skeleton_json).read_text())
    want = {b["name"]: b["head"] for b in ref["bones"]}
    js, _binc = load(path)
    skin = js["skins"][0]
    world = node_world(js)
    got = {}
    for i, n in enumerate(skin["joints"]):
        name = js["nodes"][n].get("name", "")
        got[name] = m_apply(world[n], (0, 0, 0))
    missing = [n for n in want if n not in got]
    if missing:
        return [f"shipped-skeleton bones absent from the GLB: {missing[:6]}"]
    worst = []
    for name, p in want.items():
        # base space (x, y, z) -> glTF (x, z, -y): the inverse of Mesh.from_glb's basis change
        q = (p[0], p[2], -p[1])
        d = math.dist(q, got[name])
        if d > 0.01:
            worst.append(f"{name} differs from the shipped skeleton by {d*100:.1f} cm")
    return worst


def main(path, skeleton_json=None):
    js, binc = load(path)
    # every primitive: gear and body are separate materials, and the hands are
    # covered by the gauntlet primitives, not the body primitive.
    pos, joints, weights = [], [], []
    # A GLB may carry more than one mesh node: a unit can hold a weapon bone-parented to the
    # rig. Positions must be taken through THEIR OWN node's world matrix — the previous code
    # applied the first mesh node's matrix to every vertex, which scrambled the body as soon as
    # a second mesh existed (hand bones then appeared 40-90 cm "outside the mesh").
    node_of_mesh = {}
    for i, n in enumerate(js["nodes"]):
        if "mesh" in n:
            node_of_mesh.setdefault(n["mesh"], []).append(i)
    world_nodes = node_world(js)
    for mi, mesh in enumerate(js["meshes"]):
        node_ids = node_of_mesh.get(mi, [])
        mtx = world_nodes[node_ids[0]] if node_ids else None
        for prim in mesh["primitives"]:
            attrs = prim["attributes"]
            verts = accessor(js, binc, attrs["POSITION"])
            if mtx is not None:
                verts = [m_apply(mtx, v) for v in verts]
            pos += verts
            # A unit may carry STATIC props bone-parented to the rig (the baked weapon). Those
            # primitives have no JOINTS_0/WEIGHTS_0 by design, and assuming every primitive is
            # skinned crashed the audit on every weapon-bearing unit.
            if "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
                joints += accessor(js, binc, attrs["JOINTS_0"])
                weights += accessor(js, binc, attrs["WEIGHTS_0"])

    if not js.get("skins"):
        print("FAIL\n  ERROR the GLB has no skin (the mesh was never bound to the rig)")
        return 1
    skin = js["skins"][0]
    world_nodes = node_world(js)
    # put the vertices in world space: the mesh node may carry a transform, and
    # comparing node-space vertices with world-space bones produces false
    # "bone outside mesh" failures (measured on the DoW2 carnifex base).
    # (positions were already transformed per mesh node above)
    joint_nodes = skin["joints"]
    names = {i: js["nodes"][n].get("name", f"node{n}") for i, n in enumerate(joint_nodes)}
    world = node_world(js)

    # skin the vertices exactly as a renderer would: M_global * inverseBind. The
    # file may store rest vertices with a posed skeleton (or vice versa), so the
    # only meaningful comparison is against the skinned result.
    ibm_raw = accessor(js, binc, skin["inverseBindMatrices"])
    skin_mat = []
    for k, m16 in enumerate(ibm_raw):
        ibm = [[m16[c * 4 + r] for c in range(4)] for r in range(4)]
        skin_mat.append(m_mul(world[joint_nodes[k]], ibm))
    skinned = []
    for v, jt, wt in zip(pos, joints, weights):
        acc = [0.0, 0.0, 0.0]
        total = sum(wt)
        if total < 1e-4:
            skinned.append(tuple(v))
            continue
        for j, w in zip(jt, wt):
            if w <= 1e-4:
                continue
            p3 = m_apply(skin_mat[j], v)
            acc = [acc[0] + p3[0] * w, acc[1] + p3[1] * w, acc[2] + p3[2] * w]
        skinned.append(tuple(acc))
    pos = skinned

    # thumbs/fingers are the humanoid marker: creature frames end at the wrist
    humanoid = any(n.startswith(("thumb", "finger")) or n in ("wrist.L", "wrist.R")
                   for n in names.values())

    weighted = {i: 0 for i in range(len(joint_nodes))}
    unweighted = 0
    for jt, wt in zip(joints, weights):
        if sum(wt) < 1e-4:
            unweighted += 1
            continue
        for j, w in zip(jt, wt):
            if w > 1e-4:
                weighted[j] += 1

    failures, warnings = [], []
    report = {"bones": len(joint_nodes), "verts": len(pos), "unweighted": unweighted}
    # A verified shipped skeleton is authoritative: the game placed those bones, so a
    # distance band calibrated on our template rigs must not override it. The band stays
    # live for template-rigged units, and the measured distance is still reported.
    shipped = bool(skeleton_json)

    # geometry sanity: a broken index decode or a bad merge produces triangles
    # spanning the model. The silhouette and contract gates cannot see this (a
    # jumble still renders as one blob), so it is measured directly.
    if len(pos) > 3:
        span = max(max(p[i] for p in pos) - min(p[i] for p in pos) for i in range(3)) or 1.0
        worst = 0.0
        # indices are local to each primitive's POSITION accessor, so the edge
        # check must run per primitive (a shared array produced false 1.4 m edges
        # on multi-material assets)
        # Only the body primitive: a weapon is legitimately as long as the model, and measuring
        # the gun's own barrel against the whole model's span flagged every armed eldar unit
        # (measured: a 0.73 m shuriken catapult = 37% of a 1.95 m autarch). The check exists to
        # catch a broken index decode in the body mesh, so that is what it measures.
        prims = [pr for m2 in js["meshes"] for pr in m2["primitives"] if "indices" in pr]
        prims.sort(key=lambda pr: -len(accessor(js, binc, pr["attributes"]["POSITION"])))
        for prim2 in prims[:1]:
            local = accessor(js, binc, prim2["attributes"]["POSITION"])
            flat = [x[0] for x in accessor(js, binc, prim2["indices"])]
            edges = []
            for k in range(0, len(flat) - 2, 3):
                a, b, c = flat[k], flat[k + 1], flat[k + 2]
                if max(a, b, c) >= len(local):
                    continue
                for u, v in ((a, b), (b, c), (c, a)):
                    d = sum((local[u][i] - local[v][i]) ** 2 for i in range(3)) ** 0.5
                    edges.append(d)
                    worst = max(worst, d)
        if worst and edges:
            edges.sort()
            median = edges[len(edges) // 2] or 1e-6
            long_frac = sum(1 for e in edges if e > 0.35 * span) / len(edges)
            report["max_edge_frac"] = round(worst / span, 3)
            report["long_edge_frac"] = round(long_frac, 3)
            # A broken index decode makes most edges span the model. A legitimate long part (a
            # rifle barrel, a shield, a tail) has a few long edges and the rest short -- measured
            # on the tau burst cannon, one 0.83 m edge in a mesh whose median edge is 2 cm.
            if worst / span > 0.35 and long_frac > 0.25:
                failures.append(f"geometry has an edge {worst:.2f} m long "
                                f"({worst / span:.0%} of the model, {long_frac:.0%} of edges) "
                                f"- broken mesh")

    weighted = {i: 0 for i in range(len(joint_nodes))}
    unweighted = 0
    for jt, wt in zip(joints, weights):
        if sum(wt) < 1e-4:
            unweighted += 1
            continue
        for j, w in zip(jt, wt):
            if w > 1e-4:
                weighted[j] += 1

    orphan = [names[i] for i, c in weighted.items() if c == 0]
    facial_orphan = [n for n in orphan
                     if any(n.startswith(p) or n.split(".")[0].rstrip("0123456789") == p
                            for p in OPTIONAL)]
    body_orphan = [n for n in orphan if n not in facial_orphan]
    if body_orphan:
        # a creature built from a part assembly may legitimately have no geometry
        # for a bone (head/weapon sockets); a humanoid rig may not
        if humanoid:
            failures.append(f"{len(body_orphan)} body bones have no skinned vertices: {body_orphan[:8]}")
        else:
            warnings.append(f"{len(body_orphan)} bones unweighted (part assembly): {body_orphan[:6]}")
    if facial_orphan:
        warnings.append(f"{len(facial_orphan)} optional/facial bones unweighted (decimated face)")

    def head_of(name):
        """bone origin. The mesh node carries no transform in this export, so the
        joint world position is already in the vertex space (verified against the
        MPFB landmarks: shoulder 0.209,1.545; wrist 0.545,1.189)."""
        for i, n in names.items():
            if n == name:
                return m_apply(world[joint_nodes[i]], (0, 0, 0))
        return None

    def cloud_dist(p):
        return min(v_len(v_sub(p, v)) for v in pos) if pos else 9.9

    finger_bones = [n for n in names.values() if n.startswith("finger")] if humanoid else []
    hand_bones = ([n for n in names.values()
                   if n.startswith("hand") or n in ("wrist.L", "wrist.R")] if humanoid else [])
    inside = {}
    for name in finger_bones + hand_bones:
        h = head_of(name)
        if h is None:
            continue
        d = cloud_dist(h)
        inside[name] = d
        # a fingerless frame (shipped-mesh humanoid) cannot sit inside fingertips
        limit = MAX_BONE_TO_SKIN_M if finger_bones else 0.15
        if d > limit:
            msg = f"{name} head is {d*100:.1f} cm outside the mesh"
            (warnings if shipped else failures).append(msg)

    # segment lengths from the real joints: shoulder->elbow, elbow->wrist,
    # hip->knee, knee->ankle (no twist-bone children, which are short and lie).
    # creature rigs: every deform bone must be near the body it deforms
    if not humanoid:
        deform = [n for n in names.values()
                  if not n.startswith(("root", "special", "neutral_bone"))]
        far = []
        for name in deform:
            h = head_of(name)
            if h is None:
                continue
            d = cloud_dist(h)
            if d > 0.12:
                far.append(f"{name} {d*100:.0f}cm")
        if far:
            warnings.append(f"{len(far)} bones >12 cm from the mesh: {far[:6]}")
        report["humanoid"] = False
    else:
        report["humanoid"] = True

    ratios, seg = {}, {}
    for key, a, b in (("upperarm", "upperarm01.L", "lowerarm01.L"),
                      ("lowerarm", "lowerarm01.L", "wrist.L"),
                      ("upperleg", "upperleg01.L", "lowerleg01.L"),
                      ("lowerleg", "lowerleg01.L", "foot.L")):
        ha, hb = head_of(a), head_of(b)
        if ha and hb:
            seg[key] = v_len(v_sub(hb, ha))
    if "upperarm" in seg and "lowerarm" in seg and seg["upperarm"] > 1e-6:
        ratios["forearm_to_upperarm_len"] = seg["lowerarm"] / seg["upperarm"]
    if "upperleg" in seg and "lowerleg" in seg and seg["upperleg"] > 1e-6:
        ratios["shin_to_thigh_len"] = seg["lowerleg"] / seg["upperleg"]
    if "upperarm" in seg and "lowerarm" in seg and seg["lowerarm"] > 1e-6:
        ratios["upperarm_lowerarm"] = seg["upperarm"] / seg["lowerarm"]
    if "upperleg" in seg and "lowerleg" in seg and seg["lowerleg"] > 1e-6:
        ratios["upperleg_lowerleg"] = seg["upperleg"] / seg["lowerleg"]
    for k, (lo, hi) in RATIO_BANDS.items():
        if k in ratios and not (lo <= ratios[k] <= hi):
            failures.append(f"{k}={ratios[k]:.2f} outside human band {lo}-{hi}")

    weapon = [i for i, n in enumerate(js["nodes"]) if n.get("name", "").startswith("w_")]
    if weapon:
        wpos = [m_apply(world[i], (0, 0, 0)) for i in weapon]
        for hand in ("wrist.L", "wrist.R"):
            h = head_of(hand)
            if h is None:
                continue
            d = min(v_len(v_sub(h, w)) for w in wpos)
            report[f"{hand}_to_weapon_m"] = round(d, 3)
            if d > HAND_FORE_MAX_M:
                warnings.append(f"{hand} is {d*100:.1f} cm from the weapon")

    report["bone_to_skin_m"] = {k: round(v, 4) for k, v in sorted(inside.items())}
    report["ratios"] = {k: round(v, 3) for k, v in sorted(ratios.items())}
    report["segment_m"] = {k: round(v, 3) for k, v in sorted(seg.items())}
    report["orphan_bones"] = orphan

    if skeleton_json:
        diff = verify_shipped_skeleton(path, skeleton_json)
        report["shipped_skeleton"] = "MATCH" if not diff else diff[:8]
        failures.extend(diff)

    print(json.dumps(report, indent=2))
    if failures:
        print("FAIL")
        for f in failures:
            print("  ERROR", f)
        for w in warnings:
            print("  WARN ", w)
        return 1
    print("PASS")
    for w in warnings:
        print("  WARN ", w)
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    skeleton = None
    if "--skeleton" in argv:
        i = argv.index("--skeleton")
        skeleton = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("-")]
    sys.exit(main(args[-1], skeleton))
