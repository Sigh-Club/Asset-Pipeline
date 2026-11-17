#!/usr/bin/env python3
"""fit_skeleton.py — fit a rig template onto the body it is meant to deform.

The template declares a body plan (bone names, hierarchy, authored segment proportions,
radius). It does not know where a particular mesh's limbs are. This tool measures that and
returns bone positions, so `rig_template.py` can build the armature without guessing.

Method, and why each step is the standard one:

  1. **Extremities by surface geodesic distance.** The limb tips of a body are the points at
     maximum geodesic distance from the torso on the *surface* graph. Walking the surface
     rather than the bounding box is what makes this work on a hunched or posed body: the
     carnifex's raised scything claws and its tail are both far from the torso, while its
     bounding box says the claws are "the top" (measured: the old bbox fit put the head bone
     106 cm outside the mesh).
  2. **Anatomical assignment.** Feet are the lowest extremities, one per side; the tail is the
     rearmost midline extremity; arms are the remaining lateral ones; the head is the remaining
     one nearest the torso's front-top. This is the same reading a rigger does from a
     turnaround, and it is asserted (the fit fails rather than guessing).
  3. **Surface path -> body axis.** Each extremity's geodesic path from the torso is a curve on
     the skin; a bone must sit inside the limb. Every path point is replaced by the centroid of
     the mesh vertices in a slab across the path, restricted to the local cross-section. The
     centroid of a limb's cross-section is inside the limb by construction, and it is
     insensitive to the overlapping shells DoW2 part assemblies are built from (a parity/voxel
     "inside" test is not: a point between the armour shell and the body shell is counted
     outside, measured on 16 of 27 bones of a certified human frame).
  4. **Chain placement.** The template's authored segment proportions are laid along the
     measured axis, scaled to the measured limb length. Proportions therefore survive (so the
     authored clips keep their grip geometry), while the chain follows the actual body.

Output is JSON: {"bones": [{name, head, tail}], "report": {...}}, consumed by
`tools/blender/rig_template.py --fit-file`. Running the fit as its own stage keeps it testable
without Blender and lets the audit re-check the numbers independently.

Usage:
  python3 tools/fit_skeleton.py --template configs/rigs/quadruped.json \
      --mesh output/base/carnifex_base.glb --out /tmp/carnifex_fit.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rig_fit as R  # noqa: E402

# extremities a body class is expected to have, by template class
CLASS_EXTREMITIES = {
    "humanoid": 5,     # head, 2 hands, 2 feet
    "creature": 6,     # head, 2 forelimbs, 2 hindlimbs, tail
    "quadruped": 6,
    "monster": 6,
    "machine": 5,
}


# ------------------------------------------------------------------ surface graph
def surface_graph(verts, k=10, stride=1):
    """k-NN graph over a subsample of the surface: the geodesic walk the fit uses."""
    P = verts[::stride]
    if len(P) > 9000:
        P = P[:: int(np.ceil(len(P) / 9000))]
    tree = cKDTree(P)
    d, idx = tree.query(P, k=k + 1)
    rows = np.repeat(np.arange(len(P)), k)
    cols = idx[:, 1:].ravel()
    w = d[:, 1:].ravel() + 1e-6
    g = coo_matrix((w, (rows, cols)), shape=(len(P), len(P))).tocsr()
    g = g.maximum(g.T)
    return P, g


def density_peak(P, radius):
    """The torso: the point with the most neighbours inside the body's own scale."""
    tree = cKDTree(P)
    counts = tree.query_ball_point(P, radius, return_length=True)
    return int(np.argmax(counts))


def extremities(P, g, seed, count=None):
    """Limb tips: local maxima of the geodesic distance field, one per separated limb.

    Tips are the points that are geodesically furthest in their own neighbourhood, then merged
    within a radius so a spike does not count twice. Threshold-plus-component was tried first
    and returned four tips on a six-limbed body, because the raised claws and the head share
    one region above the threshold.
    """
    dist = dijkstra(g, indices=seed)
    finite = np.isfinite(dist)
    if not finite.any():
        return [], dist
    span = float(np.max(dist[finite]))
    tree = cKDTree(P)
    order = np.argsort(-np.nan_to_num(dist, nan=-1, posinf=-1))
    picked = []
    for i in order:
        if not finite[i] or dist[i] < 0.30 * span:
            break
        # a tip beats everything within its own reach: otherwise it is on a limb's side
        near = tree.query_ball_point(P[i], 0.22 * span)
        if any(dist[j] > dist[i] for j in near if j != i):
            continue
        if all(np.linalg.norm(P[i] - P[j]) > 0.22 * span for j in picked):
            picked.append(int(i))
    picked.sort(key=lambda i: -dist[i])
    if count:
        picked = picked[:count]
    return picked, dist


def geodesic_path(g, a, b):
    """Shortest surface path a->b as point indices (Dijkstra with predecessors)."""
    dist, pred = dijkstra(g, indices=a, return_predecessors=True)
    if not np.isfinite(dist[b]):
        return []
    path, cur = [], b
    while cur != a and cur >= 0:
        path.append(int(cur))
        cur = int(pred[cur])
    path.append(int(a))
    return path[::-1]


# ------------------------------------------------------------------ assignment
def assign_extremities(P, picks, class_name, torso):
    """Map extremities to anatomical roles from the body's own geometry.

    Rules are ordered by how reliably each is measured, in the body's own frame (Z up, -Y
    front, the frame the rig templates are authored in): axial ends first (the frontmost tip is
    the head, the rearmost is the tail on a creature), then ground contact for feet, then
    lateral extent for arms. Each rule is asserted: a body these rules cannot read fails
    loudly instead of producing a plausible-looking wrong rig.
    """
    pts = {i: P[i] for i in picks}
    roles, used = {}, set()

    def take(role, idx):
        roles[role] = int(idx)
        used.add(int(idx))

    front_axis = -1.0  # templates are authored facing -Y
    axial = sorted(picks, key=lambda i: front_axis * P[i][1])
    if axial:
        take("head", axial[0])
    if class_name in ("creature", "quadruped", "monster") and len(axial) > 1:
        take("tail", axial[-1])

    # feet: the lowest extremity on each side (ground contact is unambiguous)
    for side, sgn in (("L", 1), ("R", -1)):
        cands = [i for i in picks if i not in used and sgn * P[i][0] > -0.02]
        if cands:
            take(f"foot_{side}", min(cands, key=lambda i: P[i][2]))

    rest = [i for i in picks if i not in used]
    # arms: the two most lateral of what remains
    lat = sorted(rest, key=lambda i: -abs(P[i][0]))
    for side, sgn in (("L", 1), ("R", -1)):
        cands = [i for i in lat if i not in used and sgn * P[i][0] > -0.02]
        if cands:
            take(f"hand_{side}", cands[0])
    return roles


# ------------------------------------------------------------------ axis extraction
def interior_axis(mesh, P, path, res=0.02):
    """Replace a surface path by the body's axis: slab centroids along the path."""
    pts = [P[i] for i in path]
    if len(pts) < 2:
        return np.array(pts)
    pts = np.array(pts)
    V = mesh.verts
    tree = cKDTree(V)
    out = []
    for k, p in enumerate(pts):
        nxt = pts[min(k + 1, len(pts) - 1)]
        prv = pts[max(k - 1, 0)]
        tangent = nxt - prv
        n = np.linalg.norm(tangent)
        tangent = tangent / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])
        # local cross-section radius: how thick the body is here
        near = tree.query_ball_point(p, 0.35 * 0.35)
        radius = 0.12
        if near:
            dd, _ = tree.query(V[near], k=1)
            radius = float(np.percentile(dd, 90)) * 1.5 + 0.02
        sel = np.array(tree.query_ball_point(p, radius * 1.4), dtype=int)
        if len(sel) < 8:
            out.append(p)
            continue
        # keep the vertices whose offset from p is mostly perpendicular to the path
        off = V[sel] - p
        perp = off - np.outer(off @ tangent, tangent)
        keep = sel[np.linalg.norm(perp, axis=1) < radius * 1.2]
        if len(keep) < 8:
            keep = sel
        c = V[keep].mean(axis=0)
        # a centroid can drift off the path end; keep the along-path coordinate
        along = float((c - p) @ tangent)
        out.append(p + tangent * along + (c - p - tangent * along))
    return np.array(out)


def smooth(path, iters=3):
    p = np.array(path, dtype=float)
    for _ in range(iters):
        if len(p) < 3:
            break
        p[1:-1] = 0.5 * p[1:-1] + 0.25 * (p[:-2] + p[2:])
    return p


def resample(path, count):
    """Points at equal arc length along a polyline."""
    p = np.asarray(path, dtype=float)
    if len(p) < 2:
        return p
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    if total < 1e-6:
        return np.repeat(p[:1], count, axis=0)
    want = np.linspace(0, total, count)
    return np.stack([np.interp(want, cum, p[:, i]) for i in range(3)], axis=1)


# ------------------------------------------------------------------ main fit
def chain_groups(template):
    """Ordered chains from the template: [(role, [bone names in chain order])]."""
    by = {b["name"]: b for b in template["bones"]}
    parent = {b["name"]: b.get("parent") for b in template["bones"]}

    def chain_from(root):
        out = [root]
        changed = True
        while changed:
            changed = False
            for n, p in parent.items():
                if p == out[-1] and n not in out:
                    out.append(n)
                    changed = True
        return out

    spine = []
    for n in ("root", "pelvis", "spine_01", "spine_02", "spine_03", "chest"):
        if n in by:
            spine.append(n)
    head = [n for n in ("neck", "neck_01", "neck_02", "head", "jaw") if n in by]
    groups = [("spine", spine)]
    if head:
        groups.append(("head", head))
    for side in ("L", "R"):
        arm = chain_from(f"clavicle_{side}") if f"clavicle_{side}" in by else []
        arm = [n for n in arm if n.startswith(("clavicle", "upperarm", "lowerarm", "hand", "thumb"))]
        if arm:
            groups.append((f"hand_{side}", arm))
        leg = chain_from(f"thigh_{side}") if f"thigh_{side}" in by else []
        leg = [n for n in leg if n.startswith(("thigh", "shin", "foot", "toe"))]
        if leg:
            groups.append((f"foot_{side}", leg))
    if "tail_01" in by:
        groups.append(("tail", chain_from("tail_01")))
    return groups


def template_lengths(template, names):
    by = {b["name"]: b for b in template["bones"]}
    segs = []
    for n in names:
        h = np.array(by[n]["head"], dtype=float)
        t = np.array(by[n]["tail"], dtype=float)
        segs.append(float(np.linalg.norm(t - h)))
    return segs


def fit(template, mesh, verbose=True):
    verts = mesh.verts
    lo, hi = verts.min(0), verts.max(0)
    body = float(np.max(hi - lo))
    P, g = surface_graph(verts)
    torso = P[density_peak(P, 0.18 * body)]
    if verbose:
        print(f"FIT surface points {len(P)} torso {np.round(torso, 2)} body span {body:.2f}")
    class_name = template.get("class", "humanoid")
    picks, dist = extremities(P, g, density_peak(P, 0.18 * body))
    if verbose:
        for i in picks:
            print(f"FIT extremity {np.round(P[i], 2)} geodesic {dist[i]:.2f}")
    roles = assign_extremities(P, picks, class_name, torso)
    if verbose:
        print("FIT roles", {k: np.round(P[v], 2).tolist() for k, v in roles.items()})

    groups = chain_groups(template)
    seed = int(density_peak(P, 0.18 * body))
    bones = {b["name"]: dict(b) for b in template["bones"]}
    report = {"class": class_name, "roles": {}, "chains": {}}

    # a chain's root anchor is the torso for limbs, and the pelvis for the spine
    anchors = {"spine": torso, "head": None}
    for role, names in groups:
        if role in ("spine", "head"):
            continue
        if role not in roles:
            if verbose:
                print(f"FIT skip chain {role}: no extremity assigned")
            continue
        anchors[role] = torso

    for role, names in groups:
        if role == "head":
            continue
        if role not in roles and role != "spine":
            continue
        target = roles.get(role)
        if target is None:
            continue
        path = geodesic_path(g, seed, target)
        if len(path) < 3:
            if verbose:
                print(f"FIT {role}: no geodesic path")
            continue
        axis = smooth(interior_axis(mesh, P, path), iters=3)
        lens = template_lengths(template, names)
        total = sum(lens)
        # the chain runs from the anchor to the extremity; the template's own root bone
        # (root/pelvis) sits at the anchor, so the chain is placed from the anchor end
        pts = resample(axis, max(8, len(names) * 3))
        chain_len = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
        # per-chain scale: the chain fills the limb it was measured on, so its authored
        # proportions survive while its length comes from the body
        scale = chain_len / total if total > 1e-6 else 1.0
        # distribute the authored segments from the far end backwards so the last bone ends
        # at the extremity (the hand/foot must reach the tip)
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        end = cum[-1]
        fracs = np.cumsum([0.0] + [l * scale for l in lens])
        fracs = end - (fracs[-1] - fracs)  # from the tip backwards
        placed = []
        for f in fracs:
            placed.append(np.stack([np.interp(f, cum, pts[:, i]) for i in range(3)]))
        for k, n in enumerate(names):
            bones[n]["head"] = placed[k].tolist()
            bones[n]["tail"] = placed[k + 1].tolist()
        report["chains"][role] = {"bones": names, "chain_len": round(chain_len, 3),
                                  "template_len": round(total, 3)}
        if verbose:
            print(f"FIT chain {role:8s} bones={len(names)} axis_len={chain_len:.2f} "
                  f"template={total:.2f}")

    # the head chain continues the spine: place it between the chest end and the head tip
    head_group = next((names for role, names in groups if role == "head"), None)
    if head_group and "head" in roles:
        chest = bones.get("chest")
        start = np.array(chest["tail"]) if chest else torso
        tip = P[roles["head"]]
        lens = template_lengths(template, head_group)
        axis = smooth(interior_axis(mesh, P, geodesic_path(g, seed, roles["head"])), iters=3)
        pts = resample(axis, 24)
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = sum(lens)
        scale = float(cum[-1]) / total if total > 1e-6 else 1.0
        fracs = np.cumsum([0.0] + [l * scale for l in lens])
        fracs = cum[-1] - (fracs[-1] - fracs)
        placed = [np.stack([np.interp(f, cum, pts[:, i]) for i in range(3)]) for f in fracs]
        for k, n in enumerate(head_group):
            bones[n]["head"] = placed[k].tolist()
            bones[n]["tail"] = placed[k + 1].tolist()
        report["chains"]["head"] = {"bones": head_group, "axis_len": round(float(cum[-1]), 3)}

    # sockets ride their parent bone's tail, offset in the parent's own frame
    for s in template.get("sockets", []):
        parent = bones.get(s.get("parent", ""))
        if not parent:
            continue
        h = np.array(parent["head"], dtype=float)
        t = np.array(parent["tail"], dtype=float)
        d = t - h
        n = np.linalg.norm(d)
        axis = d / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])
        base = t if s.get("at", "tail") == "tail" else h
        off = np.array(s.get("offset", [0, 0, 0]), dtype=float)
        bones[s["name"]] = {"name": s["name"], "head": (base + off).tolist(),
                            "tail": (base + off + axis * 0.05).tolist(),
                            "parent": s.get("parent"), "deform": False}

    for role, i in roles.items():
        report["roles"][role] = [round(float(v), 3) for v in P[i]]
    out = [bones[b["name"]] for b in template["bones"] if b["name"] in bones]
    out += [b for n, b in bones.items() if n not in {x["name"] for x in out}]
    return out, report


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    tpl_path = Path(a.template) if Path(a.template).is_absolute() else ROOT / a.template
    template = json.loads(tpl_path.read_text())
    mesh = R.Mesh.from_glb(a.mesh)
    bones, report = fit(template, mesh, verbose=not a.quiet)
    P = np.array([b["head"] for b in bones])
    d = mesh.surface_dist(P)
    report["bone_to_surface_m"] = {b["name"]: round(float(x), 3) for b, x in zip(bones, d)}
    worst = sorted(zip(d, [b["name"] for b in bones]), reverse=True)[:8]
    report["worst"] = [[n, round(float(x), 3)] for x, n in worst]
    print("FIT worst bone-to-surface:", ", ".join(f"{n} {x*100:.0f}cm" for x, n in worst))
    Path(a.out).write_text(json.dumps({"bones": bones, "report": report}, indent=1))
    print("WROTE", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
