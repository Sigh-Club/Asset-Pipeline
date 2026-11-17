#!/usr/bin/env python3
"""rig_fidelity.py — the gate that says a posed unit still looks like a unit.

A green edge-stretch number does not mean the mesh is intact: a limb driven through the
torso keeps every edge length, so an arm can fold into the chest while every "deformation"
metric stays happy. This tool measures the four things that actually decide whether a
posed character reads as a character:

  * tear        — triangle edges stretched or collapsed by the pose
  * inversion   — triangles whose posed normal opposes the normal their own bone would give
                  (an inside-out/folded surface)
  * penetration — limb vertices that are inside the torso volume when posed but outside it
                  in the bind pose (the arm through the chest)
  * collapse    — a body part whose posed bounding box shrinks far below its bind box

Every metric is differential against the bind pose, so a unit that is simply shaped
differently is not penalised; only what the *pose* does is measured.

Usage:
  python3 tools/rig_fidelity.py <unit.glb> [--clip idle] [--frame 1] [--json]
  python3 tools/rig_fidelity.py --corpus ../Imperium-of-Ash/frontend/public/assets/models/units \
      --clip idle --out reports/rig_fidelity.json

Exit code 1 when a hard threshold is crossed, so it can sit in CI beside audit_rig.py.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

# Hard thresholds. Derived from the measured spread in the shipped corpus and from what a
# correct solve reaches: weld + bone heat measures 0.19-0.87 % torn edges and 0 % inverted
# triangles on every humanoid body tested; the shipped field measures 4.2-23.6 % torn and
# up to 1.8 % inverted. The bands sit an order of magnitude above a correct rig and well
# below the current state, so the gate cannot be passed by tuning.
LIMITS = {
    "tear_edges_gt_1_5": 0.030,      # fraction of edges stretched > 1.5x
    "tear_area_gt_0_5": 0.100,       # fraction of triangles with > 50 % area change
    "inverted_tris": 0.025,          # fraction of triangles whose normal is inside-out
    "penetration_frac": 0.030,       # new limb-through-torso triangle pairs / limb triangles
    "collapse_ratio": 0.550,         # posed/bind bbox diagonal, per body part (catastrophic only)
}
# Calibration, measured on `iron_directorate_ig_human` idle@1 / aim@1 / cover_low_l_idle@1:
#                            shipped field      re-bound (this pipeline)
#   tear_edges_gt_1_5         0.145 / 0.184        0.008 / 0.018
#   tear_area_gt_0_5          0.201 / 0.254        0.025 / 0.034
#   inverted_tris             0.087 / 0.116        0.004 / 0.014
#   penetration_frac          0.043 / 0.062        0.020 / 0.031
#   collapse_ratio            0.817                0.766
# Every band sits between the two builds with a factor of 4-18 of margin. They are a failure-class
# detector, not a quality grade: they separate "the mesh is folding" from "the mesh is a character".
# The render is the authority; these numbers decide whether a build is worth rendering.

NC = {"VEC3": 3, "VEC2": 2, "SCALAR": 1, "VEC4": 4, "MAT4": 16}
FMT = {5126: "f", 5123: "H", 5125: "I", 5121: "B", 5122: "h", 5120: "b"}

TORSO = ("pelvis", "spine_01", "spine_02", "spine_03", "chest", "neck", "head", "jaw",
         "neck_01", "neck_02", "Bip01 Pelvis", "Bip01 Spine", "Bip01 Spine1", "Bip01 Spine2",
         "Bip01 Spine3", "Bip01 Neck", "Bip01 Head", "Bip01 Jaw")
ARM_L = ("clavicle_L", "upperarm_L", "lowerarm_L", "hand_L", "thumb_L", "finger_index_L",
         "finger_middle_L", "finger_ring_L")
ARM_R = ("clavicle_R", "upperarm_R", "lowerarm_R", "hand_R", "thumb_R", "finger_index_R",
         "finger_middle_R", "finger_ring_R")
LEG_L = ("thigh_L", "shin_L", "foot_L", "toe_L")
LEG_R = ("thigh_R", "shin_R", "foot_R", "toe_R")


# ---------------------------------------------------------------- glTF reading
def load_glb(path):
    data = Path(path).read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + n])
    off = 20 + n
    blen, _ = struct.unpack("<II", data[off:off + 8])
    return js, data[off + 8:off + 8 + blen]


def accessor(js, binc, idx):
    a = js["accessors"][idx]
    bv = js["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    nc = NC[a["type"]]
    fmt = FMT[a["componentType"]]
    size = struct.calcsize(fmt)
    stride = bv.get("byteStride", size * nc)
    out = np.zeros((a["count"], nc), dtype=np.float64)
    for i in range(a["count"]):
        out[i] = struct.unpack_from("<" + fmt * nc, binc, base + i * stride)
    return out


def quat_matrix(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
        [0.0, 0.0, 0.0, 1.0]])


def node_local(node, override=None):
    if "matrix" in node and not override:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    tr = override.get("translation", node.get("translation", (0, 0, 0)))
    rot = override.get("rotation", node.get("rotation", (0, 0, 0, 1)))
    sc = override.get("scale", node.get("scale", (1, 1, 1)))
    m = quat_matrix(rot)
    s = np.eye(4)
    s[0, 0], s[1, 1], s[2, 2] = sc
    t = np.eye(4)
    t[:3, 3] = tr
    return t @ m @ s


def node_worlds(js, overrides=None):
    overrides = overrides or {}
    parents = {}
    for i, n in enumerate(js["nodes"]):
        for c in n.get("children", []):
            parents[c] = i
    cache = {}

    def world(i):
        if i in cache:
            return cache[i]
        m = node_local(js["nodes"][i], overrides.get(i, {}))
        if i in parents:
            m = world(parents[i]) @ m
        cache[i] = m
        return m

    return {i: world(i) for i in range(len(js["nodes"]))}


def slerp(a, b, t):
    a = a / (np.linalg.norm(a) or 1.0)
    b = b / (np.linalg.norm(b) or 1.0)
    d = float(np.dot(a, b))
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        return a + (b - a) * t
    th = math.acos(max(-1.0, min(1.0, d)))
    return (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / math.sin(th)


def sample_clip(js, binc, clip, time):
    anim = next((a for a in js.get("animations", []) if a.get("name") == clip), None)
    if anim is None:
        raise KeyError(f"clip {clip!r} not in {[a.get('name') for a in js.get('animations', [])]}")
    out = {}
    for ch in anim["channels"]:
        s = anim["samplers"][ch["sampler"]]
        tin = accessor(js, binc, s["input"]).ravel()
        vout = accessor(js, binc, s["output"])
        path = ch["target"]["path"]
        node = ch["target"]["node"]
        if time <= tin[0]:
            v = vout[0]
        elif time >= tin[-1]:
            v = vout[-1]
        else:
            k = int(np.searchsorted(tin, time) - 1)
            t = (time - tin[k]) / max(1e-9, tin[k + 1] - tin[k])
            v = slerp(vout[k], vout[k + 1], t) if path == "rotation" else vout[k] + (vout[k + 1] - vout[k]) * t
        out.setdefault(node, {})[path] = np.asarray(v, dtype=float)
    return out


# ---------------------------------------------------------------- skinning
def skin_parts(js, binc, worlds):
    """Skin every primitive with the given node world matrices. Returns parts in world space."""
    skin = js["skins"][0]
    joints = skin["joints"]
    names = [js["nodes"][n].get("name", f"node{n}") for n in joints]
    ibm = accessor(js, binc, skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    skin_mats = np.stack([worlds[joints[k]] @ ibm[k] for k in range(len(joints))])
    node_of_mesh = {}
    for i, n in enumerate(js["nodes"]):
        if "mesh" in n:
            node_of_mesh.setdefault(n["mesh"], []).append(i)
    parts = []
    for mi, mesh in enumerate(js["meshes"]):
        nids = node_of_mesh.get(mi, [])
        node_mtx = worlds[nids[0]] if nids else np.eye(4)
        for pi, prim in enumerate(mesh["primitives"]):
            attrs = prim["attributes"]
            if "POSITION" not in attrs:
                continue
            verts = accessor(js, binc, attrs["POSITION"])
            vh = np.concatenate([verts, np.ones((len(verts), 1))], axis=1)
            world_verts = (node_mtx @ vh.T).T[:, :3]
            rec = {"name": f"{mesh.get('name', f'm{mi}')}/{pi}",
                   "rest": world_verts, "skinned": world_verts.copy(),
                   "dominant": np.full(len(verts), -1), "skin_mats": skin_mats,
                   "joint_names": names, "indices": None}
            if "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
                j = accessor(js, binc, attrs["JOINTS_0"]).astype(int)
                w = accessor(js, binc, attrs["WEIGHTS_0"])
                total = w.sum(axis=1)
                out = np.zeros_like(world_verts)
                for slot in range(j.shape[1]):
                    ws = w[:, slot]
                    mask = ws > 1e-5
                    if not mask.any():
                        continue
                    vv = world_verts[mask]
                    vv_h = np.concatenate([vv, np.ones((len(vv), 1))], axis=1)
                    out[mask] += np.einsum("nij,nj->ni", skin_mats[j[mask, slot]], vv_h)[:, :3] * ws[mask, None]
                out[total < 1e-5] = world_verts[total < 1e-5]
                rec["skinned"] = out
                rec["dominant"] = j[np.arange(len(j)), w.argmax(axis=1)]
            if "indices" in prim:
                rec["indices"] = accessor(js, binc, prim["indices"]).astype(int).ravel()
            parts.append(rec)
    return parts


def body_part(parts):
    """The body mesh is the largest skinned primitive (a weapon is smaller and rigid)."""
    skinned = [p for p in parts if p["dominant"].max() >= 0]
    return max(skinned, key=lambda p: len(p["rest"])) if skinned else None


def group_mask(dominant, names, group):
    idx = {names[i] for i in range(len(names)) if names[i] in group}
    want = {i for i, n in enumerate(names) if n in idx}
    return np.isin(dominant, list(want))


def segment_triangle_hit(p, q, tris, eps=1e-9):
    """Boolean mask of triangles crossed by segment p->q (Moller-Trumbore, t in (0,1))."""
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    d = q - p
    pv = np.cross(d[None, :], e2)
    det = np.einsum("ij,ij->i", e1, pv)
    ok = np.abs(det) > eps
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = p[None, :] - v0
    u = np.einsum("ij,ij->i", tv, pv) * inv
    qv = np.cross(tv, e1)
    v = (qv @ d) * inv
    t = np.einsum("ij,ij->i", e2, qv) * inv
    return ok & (u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-6) & (t < 1 - 1e-6)


def segment_triangle_hit_pairs(p, q, tris, eps=1e-9):
    """Pairwise segment-vs-triangle test: p, q are (n,3) segments, tris is (n,3,3)."""
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    d = q - p
    pv = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, pv)
    ok = np.abs(det) > eps
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tv = p - v0
    u = np.einsum("ij,ij->i", tv, pv) * inv
    qv = np.cross(tv, e1)
    v = np.einsum("ij,ij->i", qv, d) * inv
    t = np.einsum("ij,ij->i", e2, qv) * inv
    return ok & (u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-6) & (t < 1 - 1e-6)


def self_intersections(verts, tri, group_a, group_b, cell=0.05, limit=40000, min_depth=0.02):
    """Count triangle pairs from two body-part groups that pass through each other.

    A convex-hull containment test cannot see this: an arm held in front of the chest is
    inside the torso's hull while touching nothing. Two triangles that cross are the actual
    defect, so this is the test that decides whether a pose folds a unit into itself.
    """
    a_idx = np.array([i for i, t in enumerate(tri) if all(group_a[v] for v in t)], dtype=int)
    b_idx = np.array([i for i, t in enumerate(tri) if all(group_b[v] for v in t)], dtype=int)
    if len(a_idx) == 0 or len(b_idx) == 0:
        return 0, 0
    A = verts[tri[a_idx]]
    B = verts[tri[b_idx]]
    # broad phase: bucket B triangles by the cells their bounding boxes touch
    blo = B.min(axis=1)
    bhi = B.max(axis=1)
    grid = {}
    for k in range(len(B)):
        lo = np.floor(blo[k] / cell).astype(int)
        hi = np.floor(bhi[k] / cell).astype(int)
        for ix in range(lo[0], hi[0] + 1):
            for iy in range(lo[1], hi[1] + 1):
                for iz in range(lo[2], hi[2] + 1):
                    grid.setdefault((ix, iy, iz), []).append(k)
    hits = 0
    pairs = 0
    tested = 0
    for i in range(len(A)):
        lo = np.floor(A[i].min(axis=0) / cell).astype(int)
        hi = np.floor(A[i].max(axis=0) / cell).astype(int)
        cand = set()
        for ix in range(lo[0], hi[0] + 1):
            for iy in range(lo[1], hi[1] + 1):
                for iz in range(lo[2], hi[2] + 1):
                    cand.update(grid.get((ix, iy, iz), ()))
        if not cand:
            continue
        cb = np.fromiter(cand, dtype=int)
        sub = B[cb]
        tested += len(cb)
        if tested > limit * 40:
            break
        hit = np.zeros(len(cb), dtype=bool)
        tri_a = np.broadcast_to(A[i][None, :, :], sub.shape)
        for e in range(3):
            hit |= segment_triangle_hit_pairs(
                np.broadcast_to(A[i][e][None, :], sub[:, 0].shape),
                np.broadcast_to(A[i][(e + 1) % 3][None, :], sub[:, 0].shape), sub)
        for e in range(3):
            hit |= segment_triangle_hit_pairs(sub[:, e], sub[:, (e + 1) % 3], tri_a)
        if hit.any():
            # A grazing contact at the armpit is not a fold. Require the crossing triangle's
            # centroid to be more than `min_depth` off the other triangle's plane, so only a
            # real penetration counts.
            n_b = np.cross(sub[:, 1] - sub[:, 0], sub[:, 2] - sub[:, 0])
            ln = np.linalg.norm(n_b, axis=1)
            ok = ln > 1e-9
            depth = np.zeros(len(sub))
            depth[ok] = np.abs(
                np.einsum("ij,ij->i", A[i].mean(axis=0)[None, :] - sub[ok, 0], n_b[ok])) / ln[ok]
            hit &= depth > min_depth
        if hit.any():
            hits += int(hit.sum())
            pairs += 1
    return pairs, len(a_idx)


def convex_inside(points, cloud):
    """Boolean mask of `points` inside the convex hull of `cloud` (None if degenerate)."""
    if len(cloud) < 8 or len(points) == 0:
        return None
    try:
        from scipy.spatial import ConvexHull, Delaunay
        hull = ConvexHull(cloud)
        return Delaunay(cloud[hull.vertices]).find_simplex(points) >= 0
    except Exception:
        return None


# ---------------------------------------------------------------- metrics
def measure(glb, clip, frame, fps=24.0):
    js, binc = load_glb(glb)
    if not js.get("skins") or not js.get("animations"):
        return {"file": str(glb), "error": "no skin or no animation"}
    bind_parts = skin_parts(js, binc, node_worlds(js))
    body = body_part(bind_parts)
    if body is None:
        return {"file": str(glb), "error": "no skinned primitive"}

    overrides = sample_clip(js, binc, clip, frame / fps)
    posed_parts = skin_parts(js, binc, node_worlds(js, overrides))
    posed = next(p for p in posed_parts if p["name"] == body["name"])

    rest, posed_v = body["rest"], posed["skinned"]
    disp = np.linalg.norm(posed_v - rest, axis=1)
    report = {"file": str(glb), "clip": clip, "frame": frame,
              "vertices": int(len(rest)), "clip_present": True,
              "disp_max": round(float(disp.max()), 4),
              "disp_p99": round(float(np.percentile(disp, 99)), 4)}

    idx = body["indices"]
    if idx is not None:
        tri = idx.reshape(-1, 3)
        tri = tri[(tri < len(rest)).all(axis=1)]
        if len(tri):
            p0, p1 = rest[tri], posed_v[tri]
            e0 = np.stack([np.linalg.norm(p0[:, i] - p0[:, (i + 1) % 3], axis=1) for i in range(3)], 1)
            e1 = np.stack([np.linalg.norm(p1[:, i] - p1[:, (i + 1) % 3], axis=1) for i in range(3)], 1)
            keep = e0 > 1e-3
            ratio = e1[keep] / e0[keep]
            report["tear_edges_gt_1_5"] = round(float((ratio > 1.5).mean()), 4)
            a0 = 0.5 * np.linalg.norm(np.cross(p0[:, 1] - p0[:, 0], p0[:, 2] - p0[:, 0]), axis=1)
            a1 = 0.5 * np.linalg.norm(np.cross(p1[:, 1] - p1[:, 0], p1[:, 2] - p1[:, 0]), axis=1)
            report["tear_area_gt_0_5"] = round(float((np.abs(a1 - a0) / np.maximum(a0, 1e-9) > 0.5).mean()), 4)

            # inversion: compare the posed normal with the normal the triangle's own dominant
            # bone would produce for it. A folded surface fails this; a rotating limb does not.
            n0 = np.cross(p0[:, 1] - p0[:, 0], p0[:, 2] - p0[:, 0])
            n1 = np.cross(p1[:, 1] - p1[:, 0], p1[:, 2] - p1[:, 0])
            ln0 = np.linalg.norm(n0, axis=1)
            ln1 = np.linalg.norm(n1, axis=1)
            good = (ln0 > 1e-9) & (ln1 > 1e-9)
            expected = np.zeros_like(n0)
            dom = body["dominant"]
            if dom.max() >= 0:
                tri_dom = np.array([np.bincount(dom[t]).argmax() if len(t) else 0 for t in tri])
                rot = posed["skin_mats"][tri_dom][:, :3, :3]
                expected = np.einsum("nij,nj->ni", rot, n0)
            dot = np.einsum("ij,ij->i", expected[good], n1[good])
            report["inverted_tris"] = round(float((dot < 0).mean()), 4) if dot.size else 0.0

            # penetration: limb triangles that pass through torso triangles. Counted as a
            # differential against the bind pose, because the parts legitimately overlap at the
            # shoulder and hip by design.
            names = body["joint_names"]
            torso_mask = group_mask(dom, names, TORSO)
            bind_pairs = 0
            pose_pairs = 0
            for group in (ARM_L, ARM_R, LEG_L, LEG_R):
                limb_mask = group_mask(dom, names, group)
                if limb_mask.sum() < 8 or torso_mask.sum() < 8:
                    continue
                bind_pairs += self_intersections(rest, tri, limb_mask, torso_mask)[0]
                pose_pairs += self_intersections(posed_v, tri, limb_mask, torso_mask)[0]
            report["interpenetrating_pairs_bind"] = bind_pairs
            report["interpenetrating_pairs_posed"] = pose_pairs
            # a fold adds intersections; a correct pose adds none beyond the bind's own
            report["penetration_new"] = max(0, pose_pairs - bind_pairs)
            limb_tris = sum(
                len([t for t in tri if all(group_mask(dom, names, g)[v] for v in t)])
                for g in (ARM_L, ARM_R, LEG_L, LEG_R))
            report["penetration_frac"] = round(
                report["penetration_new"] / max(1, limb_tris), 4)
            report["limb_tris"] = limb_tris

            # collapse: a body part whose posed extent shrinks far below its bind extent
            worst = 1.0
            worst_part = ""
            for label, group in (("arm_L", ARM_L), ("arm_R", ARM_R), ("leg_L", LEG_L),
                                 ("leg_R", LEG_R), ("torso", TORSO)):
                m = group_mask(dom, names, group)
                if m.sum() < 8:
                    continue
                d0 = float(np.linalg.norm(np.ptp(rest[m], axis=0)))
                d1 = float(np.linalg.norm(np.ptp(posed_v[m], axis=0)))
                if d0 > 1e-6 and d1 / d0 < worst:
                    worst = d1 / d0
                    worst_part = label
            report["collapse_ratio"] = round(worst, 3)
            report["collapse_part"] = worst_part

    fails = []
    # A rigid mesh measures perfect on every deformation metric, so "0 % torn" can mean "not
    # animating at all". That is how three rebuilt units passed this gate with no weights on
    # them; the displacement floor is what makes the other numbers mean anything.
    if report.get("disp_max") is not None and report["disp_max"] < 0.02:
        fails.append(f"disp_max={report['disp_max']} m — the clip does not deform the mesh")
    for key, limit in LIMITS.items():
        value = report.get(key)
        if value is None:
            continue
        if key == "collapse_ratio":
            if value < limit:
                fails.append(f"{key}={value} below {limit}")
        elif value > limit:
            fails.append(f"{key}={value} above {limit}")
    report["verdict"] = "FAIL" if fails else "PASS"
    report["failures"] = fails
    return report


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("glb", nargs="?")
    ap.add_argument("--clip", default="idle")
    ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--corpus", help="directory tree of GLBs to measure")
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--json", action="store_true", help="print JSON")
    a = ap.parse_args(argv)

    if a.corpus:
        files = sorted(Path(a.corpus).rglob("*.glb"))
        rows = []
        for f in files:
            try:
                rows.append(measure(f, a.clip, a.frame))
            except Exception as exc:  # a missing clip is data, not a crash
                rows.append({"file": str(f), "error": str(exc)})
        summary = {
            "clip": a.clip, "frame": a.frame, "units": len(rows),
            "pass": sum(1 for r in rows if r.get("verdict") == "PASS"),
            "fail": sum(1 for r in rows if r.get("verdict") == "FAIL"),
            "error": sum(1 for r in rows if "error" in r),
            "results": rows,
        }
        text = json.dumps(summary, indent=1)
        if a.out:
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(text)
            print(f"{a.out}: {summary['units']} units, {summary['pass']} PASS, "
                  f"{summary['fail']} FAIL, {summary['error']} error")
        else:
            print(text)
        return 0 if summary["fail"] == 0 and summary["error"] == 0 else 1

    if not a.glb:
        raise SystemExit("usage: rig_fidelity.py <unit.glb> | --corpus <dir>")
    report = measure(a.glb, a.clip, a.frame)
    print(json.dumps(report, indent=1) if a.json else _human(report))
    return 0 if report.get("verdict") == "PASS" else 1


def _human(r):
    if "error" in r:
        return f"ERROR {r['file']}: {r['error']}"
    keys = ("tear_edges_gt_1_5", "tear_area_gt_0_5", "inverted_tris", "penetration_frac",
            "collapse_ratio")
    body = "  ".join(f"{k}={r.get(k)}" for k in keys)
    return f"{r['verdict']} {Path(r['file']).name} [{r['clip']}@{r['frame']}]\n  {body}"


if __name__ == "__main__":
    sys.exit(main())
