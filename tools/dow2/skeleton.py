"""dow2_skeleton.py — a DoW2 unit's own skeleton, in the space of the mesh it deforms.

DoW2 ships a rig per troop: `<race>/troops/<unit>/<unit>.hkx` carries the unit's Bip01
skeleton, its hierarchy and its reference pose, and the bone list names the game's own
attachment points (`Bip01 L Weapon`, `Bip01 R Weapon`, `Bip01 L ShoulderPad`, `Bip01 L
KneePad`, ...). That is the authoritative rig for these bodies: the mesh was authored against
it, so bone placement is a lookup rather than an inference.

Two things this module does that the old pipeline did not:

  * it converts the skeleton into the *same* space the base mesh is built in, by replaying
    exactly the transform `dow2_base.py` applies to the geometry (declared up axis, uniform
    scale to the class height, ground and centre). Measured on `guardsman.hkx`: bones land
    0.10 units mean from the guardsman mesh, max 0.24, on a 2.9-unit body — i.e. inside it.
  * it maps DoW2 bone names onto the rig vocabulary the engine, the clips and the weapon code
    already use, so a DoW2 skeleton is a drop-in for a template skeleton.

No scipy here: this module is imported by the Blender stage as well as by plain python3.

Usage:
  python3 tools/dow2/skeleton.py --hkx <unit.hkx> --obj <unit.obj> --height 1.9 \
      --out /tmp/guardsman_skeleton.json
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/hkx"))

UP_AXIS_TO_Z = {  # must match tools/blender/dow2_base.py
    "x": (0.0, -math.pi / 2, 0.0),
    "y": (math.pi / 2, 0.0, 0.0),
    "z": (0.0, 0.0, 0.0),
}

# DoW2 Bip01 -> our rig vocabulary. The left column is what the shipped skeleton calls a
# bone; the right column is what ThreeCombatEngine, animate_frames.py and the weapon code
# look up. Unmapped bones are kept under their DoW2 name so gear can still attach to them.
BONE_MAP = {
    "Bip01": "root",
    "Bip01 Pelvis": "pelvis",
    "Bip01 Spine": "spine_01",
    "Bip01 Spine1": "spine_02",
    "Bip01 Spine2": "spine_03",
    "Bip01 Spine3": "chest",
    "Bip01 Neck": "neck",
    "Bip01 Neck1": "neck_01",
    "Bip01 Neck2": "neck_02",
    "Bip01 Head": "head",
    "Bip01 Jaw": "jaw",
    "Bip01 L Clavicle": "clavicle_L",
    "Bip01 R Clavicle": "clavicle_R",
    "Bip01 L UpperArm": "upperarm_L",
    "Bip01 R UpperArm": "upperarm_R",
    "Bip01 L Forearm": "lowerarm_L",
    "Bip01 R Forearm": "lowerarm_R",
    "Bip01 L Hand": "hand_L",
    "Bip01 R Hand": "hand_R",
    # Creature rigs carry a second limb pair: L/R UpperArm..Hand are the forelimbs, and UL/UR
    # ("upper limb") are the scything claws. Mapping both onto upperarm_L/R collided and
    # silently overwrote the forelimb chain, so the claws get their own names.
    "Bip01 UL UpperArm": "upperarm_02_L",
    "Bip01 UR UpperArm": "upperarm_02_R",
    "Bip01 UL LowerArm": "lowerarm_02_L",
    "Bip01 UR LowerArm": "lowerarm_02_R",
    "Bip01 UL Hand": "hand_02_L",
    "Bip01 UR Hand": "hand_02_R",
    "AttachMarker_Bone": "socket_attach",
    "Bip01 L Thigh": "thigh_L",
    "Bip01 R Thigh": "thigh_R",
    "Bip01 L Calf": "shin_L",
    "Bip01 R Calf": "shin_R",
    "Bip01 L Foot": "foot_L",
    "Bip01 R Foot": "foot_R",
    "Bip01 L Toe0": "toe_L",
    "Bip01 R Toe0": "toe_R",
    "Bip01 Tail": "tail_01",
    "Bip01 Tail1": "tail_02",
    "Bip01 Tail2": "tail_03",
    "Bip01 Tail3": "tail_04",
    "Bip01 Tail4": "tail_05",
    "Bip01 L Weapon": "socket_weapon_L",
    "Bip01 R Weapon": "socket_weapon_R",
    "Bip01 L ShoulderPad": "socket_shoulder_L",
    "Bip01 R ShoulderPad": "socket_shoulder_R",
    "Bip01 L KneePad": "socket_knee_L",
    "Bip01 R KneePad": "socket_knee_R",
    "Bip01 Back": "socket_back",
    "Bip01 L Finger0": "finger_index_L",
    "Bip01 L Finger1": "finger_middle_L",
    "Bip01 L Finger2": "finger_ring_L",
    "Bip01 R Finger0": "finger_index_R",
    "Bip01 R Finger1": "finger_middle_R",
    "Bip01 R Finger2": "finger_ring_R",
}
# finger segments are suffixed in the shipped rig (Finger0, Finger01, Finger11, ...)
FINGER_ALIAS = {
    "Bip01 L Finger01": "finger_index_01_L",
    "Bip01 L Finger11": "finger_middle_01_L",
    "Bip01 L Finger21": "finger_ring_01_L",
    "Bip01 R Finger01": "finger_index_01_R",
    "Bip01 R Finger11": "finger_middle_01_R",
    "Bip01 R Finger21": "finger_ring_01_R",
}
SOCKET_PREFIX = "socket_"


def quat_matrix(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def euler_matrix(e):
    """Blender's XYZ euler order, the convention dow2_base.py sets on the object."""
    rx, ry, rz = e
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


def compose(skeleton):
    """World transforms of every bone from the reference pose (parent-relative records)."""
    n = skeleton["bone_count"]
    parents = skeleton["parents"]
    W = [None] * n
    for i in range(n):
        pose = skeleton["reference_pose"][i]
        M = np.eye(4)
        M[:3, :3] = quat_matrix(pose["rotation"])
        M[:3, 3] = pose["translation"]
        p = parents[i]
        W[i] = M if p < 0 else W[p] @ M
    return W


def obj_bbox(path):
    lo = np.array([1e30] * 3)
    hi = np.array([-1e30] * 3)
    for line in Path(path).read_text().splitlines():
        if line.startswith("v "):
            v = np.array([float(x) for x in line.split()[1:4]])
            lo = np.minimum(lo, v)
            hi = np.maximum(hi, v)
    return lo, hi


def source_to_base(bones, source_lo, source_hi, up_axis, target_height):
    """Replay dow2_base.py's transform: declared up axis -> scale to height -> ground/centre.

    The mesh this rig deforms went through exactly these steps, so applying them to the
    skeleton is what makes the bones land on the body rather than near it.
    """
    R = euler_matrix(UP_AXIS_TO_Z[up_axis])
    # bbox after rotation
    corners = np.array([[x, y, z] for x in (source_lo[0], source_hi[0])
                        for y in (source_lo[1], source_hi[1])
                        for z in (source_lo[2], source_hi[2])])
    rot = corners @ R.T
    lo, hi = rot.min(0), rot.max(0)
    height = hi[2] - lo[2]
    if height <= 1e-9:
        raise SystemExit("source bbox has no height after the declared axis rotation")
    s = target_height / height
    # dow2_base scales the mesh first and grounds/centres the SCALED bbox, so the offset is in
    # scaled units. Computing it on the unscaled bbox put the skeleton 0.87 m off along the
    # body axis on the carnifex (measured: 42 cm mean bone-to-mesh instead of 10 cm).
    offset = s * np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    out = []
    for b in bones:
        p = R @ np.array(b["head"]) * s + offset
        t = R @ np.array(b["tail"]) * s + offset
        out.append({**b, "head": p.tolist(), "tail": t.tolist()})
    return out, {"scale": s, "offset": offset.tolist(), "up_axis": up_axis,
                 "source_height": height, "target_height": target_height}


def canonical(name):
    return BONE_MAP.get(name) or FINGER_ALIAS.get(name)


def find_skeleton_file(unit_dir):
    """A unit's own skeleton: `<unit>.hkx`, else the first clip that carries one.

    Creature units ship only their animation set (the carnifex has `carnifex_physics.hkx`
    but no `carnifex.hkx`), and every clip in the unit's own animation folder carries that
    unit's skeleton. Measured: the carnifex clips decode to its 38-bone rig, 0.32 units mean
    from the carnifex mesh.
    """
    from hkxread import Packfile

    unit_dir = Path(unit_dir)
    # the file is named after the unit, but DoW2's directory names contain typos
    # (`gaurdsman/guardsman.hkx`), so take any skeleton-bearing .hkx sitting in the unit dir
    for own in sorted(unit_dir.glob("*.hkx")):
        if "physics" in own.name.lower():
            continue
        try:
            if Packfile.open(own).skeleton():
                return own
        except Exception:
            continue
    for clip in sorted(unit_dir.rglob("animations/**/*.hkx")):
        try:
            if Packfile.open(clip).skeleton():
                return clip
        except Exception:
            continue
    return None


# Per-race canonical troop directory. A race's bodies share one Bip01 body plan (the shipped
# game rigs every guardsman variant with the guardsman skeleton), so an armour part with no
# same-named troop directory takes the race's canonical rig. Tyranid bodies are per-creature
# and are matched by name instead -- a hormagaunt must not be rigged with the carnifex.
RACE_CANONICAL = {
    "race_ig": "gaurdsman",
    "race_chaos": "chaos_marine",
    "race_eldar": "guardian",
    "race_ork": "boy",
}


def resolve_unit_skeleton(art_dir, race, part_stem):
    """Candidate skeletons for this body part, best-guess first.

    A body part is not always accompanied by a same-named troop directory (the eldar farseer
    has no `farseer.hkx`, only clips), and a clip's reference pose is whatever the animator
    posed it in. So this returns a *list*: the unit's own directory first, then the race's
    other troop rigs, and the caller scores them against the body.
    """
    art_dir = Path(art_dir)
    troops = art_dir / race / "troops"
    if not troops.is_dir():
        return []
    stem = part_stem.lower()
    out = []
    for d in sorted(troops.iterdir()):
        if not d.is_dir():
            continue
        n = d.name.lower()
        if stem == n or stem.startswith(n) or n.startswith(stem):
            f = find_skeleton_file(d)
            if f:
                out.append(f)
    canon = RACE_CANONICAL.get(race)
    if canon and (troops / canon).is_dir():
        f = find_skeleton_file(troops / canon)
        if f:
            out.append(f)
    for d in sorted(troops.iterdir()):
        if d.is_dir():
            f = find_skeleton_file(d)
            if f and f not in out:
                out.append(f)
    return out


def _mean_bone_distance(bones, verts):
    """Mean distance from bone heads to the nearest body vertex (numpy, chunked)."""
    P = np.array([b["head"] for b in bones])
    V = np.asarray(verts, dtype=float)
    if len(V) > 4000:
        V = V[:: int(np.ceil(len(V) / 4000))]
    best = np.full(len(P), np.inf)
    for i in range(0, len(P), 8):
        chunk = P[i:i + 8]
        d = np.linalg.norm(chunk[:, None, :] - V[None, :, :], axis=2).min(axis=1)
        best[i:i + 8] = d
    return float(np.mean(best))


def obj_verts(path):
    out = []
    for line in Path(path).read_text().splitlines():
        if line.startswith("v "):
            out.append([float(x) for x in line.split()[1:4]])
    return np.array(out)


def pick_skeleton(unit_dir, obj_path, height, up_axis="y", limit=6):
    """The skeleton from this unit's files that actually fits this body.

    A troop directory without its own `<unit>.hkx` only has animation clips, and a clip's
    reference pose is whatever the animator authored against — an aim clip's is an aim pose.
    Measured on the eldar autarch: the first clip found put its bones 18 cm mean off the body,
    while the unit's own skeleton files sit at 5 cm. So the candidates are scored against the
    body and the best one is used, instead of taking the first that decodes.
    """
    unit_dir = Path(unit_dir)
    own = []
    for f in sorted(unit_dir.glob("*.hkx")):
        if "physics" not in f.name.lower():
            own.append(f)
    clips = sorted(unit_dir.rglob("animations/**/*.hkx"))
    best = None
    verts = obj_verts(obj_path)
    for f in (own + clips)[: max(limit, len(own))]:
        try:
            data = load(f, obj_path, height, up_axis)
        except Exception:
            continue
        d = _mean_bone_distance(data["bones"], verts)
        if best is None or d < best[0]:
            best = (d, f, data)
        if own and f in own and d < 0.08 * height:
            break
    if best is None:
        return None
    return best[1], best[2], best[0]


def load(hkx_path, obj_path, height, up_axis="y"):
    """Return {bones:[{name, head, tail, parent, deform}], sockets, transform} in base space."""
    from hkxread import Packfile  # tools/hkx

    sk = Packfile.open(hkx_path).skeleton()
    if not sk:
        raise SystemExit(f"no skeleton in {hkx_path}")
    W = compose(sk)
    names = sk["bone_names"]
    if len(names) < sk["bone_count"]:
        raise SystemExit(f"{hkx_path}: {sk['bone_count']} bones but only {len(names)} names")
    # tail = the child's head where a child exists, else a short stub along the bone's own axis
    children = {}
    for i, p in enumerate(sk["parents"]):
        if p >= 0:
            children.setdefault(p, []).append(i)
    bones = []
    for i in range(sk["bone_count"]):
        head = W[i][:3, 3]
        if children.get(i):
            tail = W[children[i][0]][:3, 3]
        else:
            axis = W[i][:3, 2]
            n = np.linalg.norm(axis) or 1.0
            tail = head + axis / n * 0.05
        if np.linalg.norm(tail - head) < 1e-4:
            tail = head + np.array([0.0, 0.0, 0.05])
        name = canonical(names[i]) or names[i]
        parent = canonical(names[sk["parents"][i]]) if sk["parents"][i] >= 0 else None
        bones.append({"name": name, "head": head.tolist(), "tail": tail.tolist(),
                      "parent": parent, "deform": not name.startswith(SOCKET_PREFIX),
                      "dow2_name": names[i]})
    lo, hi = obj_bbox(obj_path)
    bones, xform = source_to_base(bones, lo, hi, up_axis, height)
    sockets = [b["name"] for b in bones if b["name"].startswith(SOCKET_PREFIX)]
    return {"bones": bones, "sockets": sockets, "transform": xform,
            "source": {"hkx": str(hkx_path), "obj": str(obj_path),
                       "bones": sk["bone_count"], "layout": sk["reference_pose_layout"]}}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hkx", help="the unit's own skeleton/clip file")
    ap.add_argument("--find", action="store_true",
                    help="resolve the skeleton from --art/--race/--part instead of --hkx")
    ap.add_argument("--art", help="the DoW2 art root (contains race_*/troops)")
    ap.add_argument("--race", help="race_ig, race_ork, ...")
    ap.add_argument("--part", help="the body part stem, e.g. carnifex_armour_common")
    ap.add_argument("--obj", required=True, help="the source OBJ the base mesh was built from")
    ap.add_argument("--height", type=float, required=True, help="the base mesh's height in metres")
    ap.add_argument("--up-axis", default="y", choices=("x", "y", "z"))
    ap.add_argument("--out", default="-")
    ap.add_argument("--max-dist-frac", type=float, default=0.12,
                    help="reject a skeleton whose bones sit further than this fraction of the "
                         "body height from the mesh (exit 3), so the caller can fall back")
    ap.add_argument("--strict", action="store_true", help="exit 3 when no skeleton fits")
    a = ap.parse_args(argv)
    if a.find:
        cands = resolve_unit_skeleton(a.art, a.race, a.part)
        if not cands:
            raise SystemExit(f"no DoW2 skeleton for {a.race}/{a.part}")
        verts = obj_verts(a.obj)
        scored = []
        for f in cands:
            try:
                d = load(f, a.obj, a.height, a.up_axis)
            except Exception:
                continue
            scored.append((_mean_bone_distance(d["bones"], verts), f, d))
        if not scored:
            raise SystemExit(f"no decodable skeleton for {a.race}/{a.part}")
        scored.sort(key=lambda t: t[0])
        dist, best, data = scored[0]
        print(f"SKELETON best {best.name} bone-to-body {dist:.3f} m "
              f"(of {len(scored)} candidates; next {scored[1][0]:.3f} m)" if len(scored) > 1
              else f"SKELETON {best.name} bone-to-body {dist:.3f} m")
        if not a.out or a.out == "-":
            print(str(best))
            return 0
        a.hkx = str(best)
        if dist > a.max_dist_frac * a.height:
            print(f"WARN no skeleton fits {a.part} within {a.max_dist_frac:.0%} of its height "
                  f"(best {best.name}: {dist:.3f} m)")
            if a.strict:
                return 3
    data = load(a.hkx, a.obj, a.height, a.up_axis)
    Path(a.out).write_text(json.dumps(data, indent=1))
    print(f"SKELETON {a.hkx}: {len(data['bones'])} bones, sockets {data['sockets']}")
    print(f"SKELETON transform {data['transform']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
