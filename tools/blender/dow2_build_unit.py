"""dow2_build_unit.py — build a unit from DoW2's own data, end to end.

Every previous route invented something: a T-pose template fitted to an A-posed body, a distance
weight field, procedural clips, a weapon bind solved for one frame. Each of those is where the
tearing came from. This tool invents nothing:

  geometry      decoded from the shipped `.model` (Relic Chunky DATADATA v7)
  skin weights  decoded from the same payload — DoW2 stores two bone indices and a u16 weight per
                vertex, so a plate is rigid (weight 0.996) and cloth is blended (0.50-0.90), which
                is exactly the distinction a solver has to guess and gets wrong
  skeleton      the unit's own `.hkx` (3ds Max Biped, `Bip01 L/R Weapon` on the hands)
  poses         each DoW2 clip file carries its skeleton in the pose that clip was authored in, so
                the clip set comes from the shipped animation files rather than from authored angles
  weapon        bound to the skeleton's own weapon bone, which sits at the hand

Usage:
  blender -b -P tools/blender/dow2_build_unit.py -- \
      --model <part.model> [<part.model> ...] --hkx <unit.hkx> \
      --anim-dir <unit>/animations --out <dir> --id <id> \
      [--height 1.85] [--limit N] [--filter substr] [--weapon <weapon.glb>]
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/hkx"))
sys.path.insert(0, str(ROOT / "tools/dow2"))

import chunky_mesh as CM  # noqa: E402

# ---------------------------------------------------------------- how each weapon is held
#
# This is DATA, not a rule, and that is the whole point. A weapon is not "a barrel pointing along
# the hand": a rifle is carried horizontally with the barrel forward, a staff is carried vertically
# in one hand, a blade points up or forward. One universal rule cannot express all three — measured
# on the shipped lab assets, a single "weapon +Y follows the hand +Y" rule put the lasgun at 83 deg
# from vertical (right) and the staff at 29 deg (wrong; it should stand upright).
#
# `up` is the world direction the weapon's own +Y axis is authored to point in the BIND pose:
#   forward  rifle, pistol, bolter   (carried low, muzzle forward-down)
#   vertical staff, spear, banner    (shaft upright, one hand)
#   blade    sword, axe, choppa      (blade up and forward)
# The grip is then a CONSTANT transform in the hand's space, so it holds in bind pose and in every
# clip: the animation poses the arm, and the weapon follows the hand. Nothing is solved at runtime
# and nothing reaches for the weapon.
# Blender space (z up). Measured: both weapon assets carry their long axis on Blender +Z after
# import, so `up` is the direction that axis must point in the bind pose.
WEAPON_HOLD = {
    "lasgun":   {"up": (0.0, -1.0, -0.25), "two_handed": True},
    "bolter":   {"up": (0.0, -1.0, -0.20), "two_handed": True},
    "shuriken": {"up": (0.0, -1.0, -0.20), "two_handed": True},
    "shoota":   {"up": (0.0, -1.0, -0.30), "two_handed": True},
    "rokkit":   {"up": (0.0, -1.0, -0.15), "two_handed": True},
    "burna":    {"up": (0.0, -1.0, -0.30), "two_handed": True},
    "staff":    {"up": (0.0,  0.0,  1.0),  "two_handed": False},
    "horns":    {"up": (0.0,  0.0,  1.0),  "two_handed": False},
}


def hold_for(weapon_path):
    key = Path(weapon_path).stem.split(".")[0]
    return WEAPON_HOLD.get(key, {"up": (0.0, -1.0, -0.25), "two_handed": True})

import skeleton as S  # noqa: E402
from hkxread import Packfile  # noqa: E402

_ap = argparse.ArgumentParser()
_ap.add_argument("--model", nargs="+", required=True)
_ap.add_argument("--hkx", required=True)
_ap.add_argument("--anim-dir", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--id", required=True)
_ap.add_argument("--height", type=float, default=1.85)
_ap.add_argument("--up-axis", default="y")
_ap.add_argument("--limit", type=int, default=0)
_ap.add_argument("--filter", default="")
_ap.add_argument("--weapon", default="")
_ap.add_argument("--texture-root", action="append", default=[],
                help="directory searched for the source textures; repeatable. Each material is "
                     "resolved by name: 'relic.material.<stem>' -> '<stem>_dif.dds'.")
_ap.add_argument("--no-align", action="store_true",
                help="do not fit the skeleton onto the mesh (only for a body whose skeleton is "
                     "already in the mesh's own space)")
_ap.add_argument("--chain-weights", action="store_true", default=True,
                help="derive the blend from the shipped bone ASSIGNMENT plus the joint geometry, "
                     "instead of trusting the shipped weight column")
_ap.add_argument("--rigid-weights", action="store_true",
                help="bind every vertex 100%% to its index bone. Diagnostic: isolates a wrong weight "
                     "field from a wrong bone assignment.")
_ap.add_argument("--no-poses", action="store_true",
                help="export the rig only; another tool authors the clip set")
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

# ------------------------------------------------------------------ 1. geometry + shipped skin
verts, faces, skins, groups, uvs = [], [], [], [], []
for model_path in A.model:
    blob = Path(model_path).read_bytes()
    root = CM.parse(blob)
    models = []
    CM.collect(root, blob, models)
    if not models:
        raise SystemExit(f"no FOLDMODL in {model_path}")
    mats = CM.material_names(models[0], blob)

    def walk(node, out):
        if node.type == "DATADATA" and node.version == 7:
            out.append(node)
        for k in node.children:
            walk(k, out)

    nodes = []
    walk(models[0], nodes)
    for node in nodes:
        pay = blob[node.data_offset:node.file_offset + node.size]
        dec = CM.decode_geometry(pay)
        if not dec:
            continue
        pos, subs = dec
        skin = CM.decode_skin(pay)
        uv = CM.decode_uv(pay)
        base = len(verts)
        verts.extend(pos)
        if uv and len(uv) == len(pos):
            uvs.extend(uv)
        else:
            uvs.extend([(0.0, 0.0)] * len(pos))
        if skin and len(skin) == len(pos):
            skins.extend(skin)
        else:
            skins.extend([(0, 0, 1.0)] * len(pos))
        for s in subs:
            idx = s["indices"]
            mat = mats[s["material"]] if s["material"] < len(mats) else f"mat{s['material']}"
            for k in range(0, len(idx) - 2, 3):
                faces.append((idx[k] + base, idx[k + 1] + base, idx[k + 2] + base))
            groups.append(mat)
print(f"GEOMETRY verts={len(verts)} tris={len(faces)} materials={len(set(groups))}")
if not verts:
    raise SystemExit("no geometry decoded")

V = np.array(verts, dtype=float)


def find_source_texture(material_name, roots):
    """The shipped texture for a shipped material, by name.

    DoW2 declares its materials as `relic.material.<stem>` and ships `<stem>_dif.dds` beside the part
    (verified: `relic.material.catachan_trooper` -> `catachan_trooper_dif.dds`). That is a direct
    name mapping, so the source colour scheme can be used as-is instead of being repainted into our
    palette.
    """
    stem = material_name.split(".")[-1]
    for root in roots:
        for suffix in ("_dif", "_dif1", ""):
            for ext in ("dds", "png"):
                hits = sorted(Path(root).rglob(f"{stem}{suffix}.{ext}"))
                if hits:
                    return hits[0]
    return None


def source_textures_in(folder):
    """The `_dif` textures shipped beside a part, in name order.

    Used as the positional fallback: the submesh material index in the geometry payload does not
    index the FOLDMTRL list we can read (measured: a model with two declared materials carries
    submesh material index 3), so when the name lookup fails the submesh takes the corresponding
    shipped texture in the part's own folder rather than an invented colour.
    """
    out = []
    for ext in ("dds", "png"):
        out.extend(sorted(Path(folder).glob(f"*_dif*.{ext}")))
    return out


def make_material(name, texture_path):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if texture_path is not None:
        img = bpy.data.images.load(str(texture_path), check_existing=True)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.location = (-400, 200)
        if bsdf:
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            bsdf.inputs["Roughness"].default_value = 0.85
            bsdf.inputs["Metallic"].default_value = 0.0
        print(f"MATERIAL {name} <- {texture_path.name}")
    else:
        print(f"MATERIAL {name} (no source texture found)")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.45, 0.45, 0.48, 1.0)
    return mat


def read_glb_mesh(path):
    """Vertices and triangles of a GLB, in world space, plus its image-free material name.

    The weapon is merged into the body mesh rather than kept as a second skinned object: a second
    skinned object needs its own skin and joint list, and a non-deform attachment bone is dropped
    from that list on export, which left the rifle behind while the body moved (measured twice).
    One mesh, one skin, one weight on the hand — nothing to get wrong.
    """
    import json
    import struct

    data = Path(path).read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + n])
    off = 20 + n
    blen, _ = struct.unpack("<II", data[off:off + 8])
    binc = data[off + 8:off + 8 + blen]
    NC = {"VEC3": 3, "VEC2": 2, "SCALAR": 1, "VEC4": 4, "MAT4": 16}
    FMT = {5126: "f", 5123: "H", 5125: "I", 5121: "B", 5122: "h", 5120: "b"}

    def acc(idx):
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

    def local(node):
        m = np.eye(4)
        if "matrix" in node:
            return np.array(node["matrix"], dtype=float).reshape(4, 4).T
        if "rotation" in node:
            x, y, z, w = node["rotation"]
            nn = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
            x, y, z, w = x / nn, y / nn, z / nn, w / nn
            m[:3, :3] = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        if "scale" in node:
            for i in range(3):
                m[:3, i] *= node["scale"][i]
        if "translation" in node:
            m[:3, 3] = node["translation"]
        return m

    parents = {}
    for i, node in enumerate(js["nodes"]):
        for c in node.get("children", []):
            parents[c] = i
    cache = {}

    def world(i):
        if i in cache:
            return cache[i]
        m = local(js["nodes"][i])
        if i in parents:
            m = world(parents[i]) @ m
        cache[i] = m
        return m

    verts, faces = [], []
    for i, node in enumerate(js["nodes"]):
        if "mesh" not in node:
            continue
        mtx = world(i)
        for prim in js["meshes"][node["mesh"]]["primitives"]:
            if "POSITION" not in prim["attributes"]:
                continue
            v = acc(prim["attributes"]["POSITION"])
            vh = np.concatenate([v, np.ones((len(v), 1))], axis=1)
            vw = (mtx @ vh.T).T[:, :3]
            base = len(verts)
            verts.extend(vw.tolist())
            if "indices" in prim:
                idx = acc(prim["indices"]).astype(int).ravel()
                for k in range(0, len(idx) - 2, 3):
                    faces.append((idx[k] + base, idx[k + 1] + base, idx[k + 2] + base))
    return verts, faces


# ------------------------------------------------------------------ 2. source -> base
R = S.euler_matrix(S.UP_AXIS_TO_Z[A.up_axis])
rot = V @ R.T
lo, hi = rot.min(0), rot.max(0)
height = float(hi[2] - lo[2])
if height <= 1e-9:
    raise SystemExit("decoded geometry has no height")
scale = A.height / height
offset = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]) * scale
BASE = np.eye(4)
BASE[:3, :3] = R * scale
BASE[:3, 3] = offset
Vb = (V @ BASE[:3, :3].T) + BASE[:3, 3]
force_bone = [None] * len(Vb)
if A.weapon:
    # weapon space: grip at the origin, barrel along +Y (weapon_glb.py). The hand bone's own frame
    # is the aim, so the weapon is placed by the hand's rest matrix scaled into base space.
    wv, wf = read_glb_mesh(A.weapon)
    wv = np.array(wv, dtype=float)
    # source-scale the weapon with the body so it matches the unit's proportions
    wv = wv * scale
    wv = wv + np.array([0.0, 0.0, 0.0])
    base_index = len(Vb)
    Vb = np.concatenate([Vb, wv], axis=0)
    faces.extend([(a + base_index, b + base_index, c + base_index) for a, b, c in wf])
    force_bone.extend(["hand_R"] * len(wv))
    groups.extend(["weapon"] * len(wf))
    uvs.extend([(0.0, 0.0)] * len(wf))
    print(f"WEAPON merged verts={len(wv)} tris={len(wf)}")
print(f"BASE source_height={height:.3f} scale={scale:.4f} bbox z={Vb[:,2].min():.3f}..{Vb[:,2].max():.3f}")

# ------------------------------------------------------------------ 3. skeleton
def _load_skeleton(path):
    try:
        sk = Packfile.open(path).skeleton()
        if sk:
            return sk
    except Exception:
        pass
    return None


src = _load_skeleton(A.hkx)
if src is None:
    # Some races ship clips in a container hkxread cannot open (measured: the necron overlord's
    # `fb_stand_idle_01.hkx` reports magic 0x0003da78). Any decodable file in the unit's own
    # animation set carries the same skeleton, so use the first one that opens rather than failing.
    print(f"SKELETON {Path(A.hkx).name} not a packfile — searching the unit's animation set")
    for cand in sorted(Path(A.anim_dir).rglob("*.hkx")):
        src = _load_skeleton(cand)
        if src is not None:
            print(f"SKELETON using {cand.name}")
            break
    if src is None:
        raise SystemExit("no decodable skeleton in the animation set")
srcW = S.compose(src)
src_names = src["bone_names"]

# ------------------------------------------------------------------ 3a. align the skeleton to the MESH
#
# The skeleton file and the armour model are NOT in the same space: measured on the Imperial Guard
# body, `guardsman.hkx` has its pelvis at y 1.46 and a 2.54 total height, while `ig_armour.model`
# spans y 0.01-2.39. Matching mesh vertices against bones in a different frame produces a garbage
# assignment — that was the real cause of the tearing, not the weights (a 100 %-rigid bind on the
# same assignment still tore 16 %).
#
# So the skeleton is fitted onto the mesh explicitly: uniform scale to the mesh's height, centred and
# grounded like the geometry. The fit residual is printed and must be small; a large one means the
# skeleton does not belong to this body.
ALIGN = np.eye(4)
if not A.no_align:
    sk_pts = np.array([srcW[i][:3, 3] for i in range(len(src_names))])
    m_lo, m_hi = V.min(0), V.max(0)
    s_lo, s_hi = sk_pts.min(0), sk_pts.max(0)
    a_scale = float((m_hi[1] - m_lo[1]) / max(1e-6, s_hi[1] - s_lo[1]))
    a_off = np.array([(m_lo[0] + m_hi[0]) / 2 - a_scale * (s_lo[0] + s_hi[0]) / 2,
                      m_lo[1] - a_scale * s_lo[1],
                      (m_lo[2] + m_hi[2]) / 2 - a_scale * (s_lo[2] + s_hi[2]) / 2])
    ALIGN[:3, :3] *= a_scale
    ALIGN[:3, 3] = a_off
    print(f"ALIGN skeleton->mesh scale={a_scale:.4f} offset={tuple(round(v,3) for v in a_off)}")
srcW = [ALIGN @ w for w in srcW]

segs = []
for i, n in enumerate(src_names):
    kids = [j for j, p in enumerate(src["parents"]) if p == i]
    h = srcW[i][:3, 3]
    t = srcW[kids[0]][:3, 3] if kids else h + srcW[i][:3, 2] * 0.05
    segs.append((n, np.array(h, dtype=float), np.array(t, dtype=float)))
# how far the fitted skeleton sits from the surface it must deform: the fit's own report
_d = [min(float(np.linalg.norm(p - (h + np.clip(((p - h) @ (t - h)) / max(1e-9, float((t - h) @ (t - h))), 0, 1)) * (t - h)))
          for p in V[::max(1, len(V) // 200)]) for _n, h, t in segs]
print(f"SKELETON bones={len(src_names)} bone->mesh median={np.median(_d):.3f} m max={max(_d):.3f} m")
# The rest pose MUST be looked up by bone NAME. The clip's embedded skeleton and the unit's have
# different bone lists and orders, so `srcW[i]` with the clip's index pairs unrelated bones and the
# delta comes out as noise — that is what shattered every posed unit while its bind pose was perfect.
REST_BY_NAME = {n: srcW[i] for i, n in enumerate(src_names)}

# ------------------------------------------------------------------ 4. resolve the skin indices
# DoW2's indices address the model's own bone table, so each is resolved by majority vote of the
# nearest skeleton bone over the vertices carrying it. Measured: 44 indices, each resolving to a
# body part, 1,412 rigid vertices and 2,144 blended — a realistic split for an armoured body.
# The resolver returns the SHIPPED bone names; the armature is built from the mapped vocabulary
# (`Bip01 L UpperArm` -> `upperarm_L`). A vertex group whose name does not match a bone deforms
# nothing, so the mapping has to be applied here too — measured: the body barely moved (1.7 cm)
# while the arm bones travelled 1.2 m.
index_to_name = {k: (S.canonical(v) or v) for k, v in
                 CM.resolve_skin_indices(skins, verts, segs).items()}
print(f"SKIN indices={len(index_to_name)} rigid={sum(1 for b0,b1,w in skins if w>0.99)} "
      f"blended={sum(1 for b0,b1,w in skins if w<=0.99)}")

# the weapon geometry arrives in its own space; move it into the hand's rest frame
if A.weapon:
    hand_bone_src = next((i for i, n in enumerate(src_names)
                          if (S.canonical(n) or n) == "hand_R"), None)
    if hand_bone_src is None:
        raise SystemExit("no hand_R in the shipped skeleton")
    hand_m = BASE @ srcW[hand_bone_src]
    hand_pos = hand_m[:3, 3]
    hold = hold_for(A.weapon)
    # The authored hold direction, expressed in base space, is the target for the weapon's own +Y.
    barrel_target = np.array(hold["up"], dtype=float)
    barrel_target /= np.linalg.norm(barrel_target)
    local_barrel = np.array([0.0, 0.0, 1.0])   # measured: the weapon's long axis in Blender space
    print(f"WEAPON hold={hold['up']} two_handed={hold['two_handed']}")
    axis = np.cross(local_barrel, barrel_target)
    dot = float(local_barrel @ barrel_target)
    if np.linalg.norm(axis) < 1e-9:
        rot = np.eye(3) if dot > 0 else -np.eye(3)
    else:
        axis = axis / np.linalg.norm(axis)
        ang = math.acos(max(-1.0, min(1.0, dot)))
        K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        rot = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)
    weapon_from = len(Vb) - sum(1 for b in force_bone if b == "hand_R")
    Vb[weapon_from:] = (Vb[weapon_from:] @ rot.T) + hand_pos
    print(f"WEAPON placed at hand {tuple(round(v,3) for v in hand_pos)} "
          f"barrel {tuple(round(v,3) for v in barrel_target)}")

# ------------------------------------------------------------------ 5. mesh
bpy.ops.wm.read_factory_settings(use_empty=True)
me = bpy.data.meshes.new(f"{A.id}_mesh")
me.from_pydata([tuple(v) for v in Vb], [], [tuple(f) for f in faces])
me.update()
# UVs from the shipped stream, so the shipped textures land where the artist put them
# pad or trim to the vertex count: a chunk whose attribute layout differs must not cost the whole
# body its UVs (measured: 340 of 4,114 vertices came back without a UV pair)
if len(uvs) < len(Vb):
    print(f"UVS short by {len(Vb) - len(uvs)} vertices — padding those with (0,0)")
    uvs.extend([(0.0, 0.0)] * (len(Vb) - len(uvs)))
elif len(uvs) > len(Vb):
    uvs = uvs[: len(Vb)]
layer = me.uv_layers.new(name="UVMap")
for li, loop in enumerate(me.loops):
    layer.data[li].uv = uvs[loop.vertex_index]
print(f"UVS {len(uvs)} coordinates written")
body = bpy.data.objects.new(A.id, me)
bpy.context.collection.objects.link(body)
# one material slot per shipped material, textured from the source where it exists
slot_of = {}
part_textures = source_textures_in(Path(A.model[0]).parent)
print(f"PART TEXTURES {[t.name for t in part_textures]}")
for poly, mat_name in zip(me.polygons, groups):
    slot = slot_of.get(mat_name)
    if slot is None:
        tex = find_source_texture(mat_name, A.texture_root)
        if tex is None and not mat_name.startswith("weapon"):
            # DoW2 shares armour textures: `ig_armour_common_a` carries no DDS of its own and uses
            # `shared_textures/ig_armour_dif.dds`. Match the part's family prefix, not just its exact
            # name, or a whole body imports untextured and the source colour scheme is lost.
            def _family_hits(prefix):
                pngs, dds = [], []
                for root in A.texture_root:
                    pngs.extend(sorted(Path(root).rglob(f"{prefix}*_dif*.png")))
                    dds.extend(sorted(Path(root).rglob(f"{prefix}*_dif*.dds")))
                return pngs or dds

            # NOTE: `gen or gen` is always truthy — a generator object is truthy whatever it would
            # yield — so the first version of this loop never stripped a suffix and matched nothing.
            # Materialise the results before testing them.
            fam = Path(A.model[0]).stem
            hits = _family_hits(fam)
            while not hits and "_" in fam:
                fam = fam.rsplit("_", 1)[0]
                hits = _family_hits(fam)
            if hits:
                tex = hits[0]
        if tex is None and part_textures and not mat_name.startswith("weapon"):
            chosen = part_textures[min(len(slot_of), len(part_textures) - 1)]
            # prefer the converted PNG: Blender's DDS loading is unreliable here and glTF cannot
            # embed DDS anyway
            for root in A.texture_root:
                png = sorted(Path(root).rglob(f"{chosen.stem}.png"))
                if png:
                    chosen = png[0]
                    break
            tex = chosen
        slot = len(me.materials)
        me.materials.append(make_material(mat_name, tex))
        slot_of[mat_name] = slot
    poly.material_index = slot
print(f"MATERIALS slots={len(me.materials)} from {len(set(groups))} shipped material name(s)")

# ------------------------------------------------------------------ 6. armature
arm_data = bpy.data.armatures.new(f"{A.id}_rig")
arm = bpy.data.objects.new(f"{A.id}_rig", arm_data)
bpy.context.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
made = {}
for i, n in enumerate(src_names):
    mapped = S.canonical(n) or n
    b = arm_data.edit_bones.new(mapped)
    h = BASE @ np.append(srcW[i][:3, 3], 1.0)
    kids = [j for j, p in enumerate(src["parents"]) if p == i]
    if kids:
        t = BASE @ np.append(srcW[kids[0]][:3, 3], 1.0)
    else:
        t = BASE @ np.append(srcW[i][:3, 3] + srcW[i][:3, 2] * 0.05, 1.0)
    if np.linalg.norm(t[:3] - h[:3]) < 1e-4:
        t = h + np.array([0, 0, 0.05, 0])
    b.head = Vector(h[:3])
    b.tail = Vector(t[:3])
    b.use_deform = not mapped.startswith("socket")
    made[i] = b
for i, n in enumerate(src_names):
    p = src["parents"][i]
    if p >= 0:
        made[i].parent = made[p]
        made[i].use_connect = False

bpy.ops.object.mode_set(mode="OBJECT")

# verify: our rest must now equal the shipped rest, transformed into base space
worst = 0.0
for i, n in enumerate(src_names):
    want = BASE @ srcW[i]
    got = np.array(arm.data.bones[S.canonical(n) or n].matrix_local)
    worst = max(worst, float(np.abs(got - want).max()))
print(f"REST matches the shipped skeleton: worst |diff| = {worst:.2e}")
if worst > 1e-3:
    print("  WARN rig rest does not match the source; pose transfer will twist")

# ------------------------------------------------------------------ 7. shipped weights
group_cache = {}
def group_for(name):
    g = group_cache.get(name)
    if g is None:
        g = body.vertex_groups.get(name) or body.vertex_groups.new(name=name)
        group_cache[name] = g
    return g

skipped = 0
for (b0, b1, w0), vi in zip(skins, range(len(Vb))):
    forced = force_bone[vi]
    if forced:
        group_for(forced).add([vi], 1.0, "REPLACE")
        continue
    n0 = index_to_name.get(b0)
    n1 = index_to_name.get(b1) if b1 != 0 else None
    if n0 is None:
        skipped += 1
        continue
    w0 = min(1.0, max(0.0, w0))
    if A.chain_weights and not A.rigid_weights:
        # The shipped assignment (which index is which bone) is authoritative and checks out
        # anatomically. The shipped WEIGHT column is not usable as-is: a blended bind measured WORSE
        # than a fully rigid one (23.7 % vs 16.4 % torn edges), which means it is mixing bones that
        # are not neighbours. So the blend is derived from the geometry instead: a vertex belongs to
        # its assigned bone, and within `BLEND` metres of that bone's head it blends toward the
        # parent, which is how a joint actually deforms. Two influences, normalised.
        BLEND = 0.10
        bone = n0
        parent = None
        for spec_name, head, _tail in segs:
            if spec_name == bone:
                break
        pb = arm.data.bones.get(bone)
        parent = S.canonical(pb.parent.name) or pb.parent.name if (pb and pb.parent) else None
        if parent is None:
            group_for(bone).add([vi], 1.0, "REPLACE")
            continue
        head = np.array(arm.data.bones[bone].head_local)
        d = float(np.linalg.norm(Vb[vi] - head))
        t = max(0.0, min(1.0, 1.0 - d / BLEND)) * 0.5
        group_for(bone).add([vi], 1.0 - t, "REPLACE")
        group_for(parent).add([vi], t, "REPLACE")
        continue
    if A.rigid_weights:
        group_for(n0).add([vi], 1.0, "REPLACE")
        continue
    if n1 is None or n1 == n0:
        group_for(n0).add([vi], 1.0, "REPLACE")
    else:
        group_for(n0).add([vi], w0, "REPLACE")
        group_for(n1).add([vi], 1.0 - w0, "REPLACE")
# the merged weapon sits past the body's vertices; the zip above stops at the shorter list, so
# those vertices were left unweighted and stayed at their bind position while the body moved
for vi in range(len(skins), len(Vb)):
    bone = force_bone[vi] or "hand_R"
    group_for(bone).add([vi], 1.0, "REPLACE")
print(f"WEIGHTS groups={len(group_cache)} vertices_without_a_bone={skipped} "
      f"weapon_vertices={max(0, len(Vb) - len(skins))}")

mod = body.modifiers.new("armature", "ARMATURE")
mod.object = arm
body.parent = arm
body.matrix_parent_inverse = Matrix.Identity(4)

# ------------------------------------------------------------------ 9. poses from the shipped clips
clips = [] if A.no_poses else sorted(Path(A.anim_dir).rglob("*.hkx"))
if A.filter:
    clips = [c for c in clips if A.filter in c.stem]
if A.limit:
    clips = clips[:A.limit]
depth = {}
for b in arm.data.bones:
    d, cur = 0, b
    while cur.parent:
        d += 1
        cur = cur.parent
    depth[b.name] = d
ordered = sorted(arm.pose.bones, key=lambda pb: depth.get(pb.name, 0))
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"

arm.animation_data_create()
for act in list(bpy.data.actions):
    bpy.data.actions.remove(act)

applied, skipped_clips = 0, []
for path in clips:
    try:
        sk = Packfile.open(path).skeleton()
    except Exception as exc:
        skipped_clips.append((path.stem, f"decode {exc}"))
        continue
    if not sk:
        skipped_clips.append((path.stem, "no skeleton"))
        continue
    W = S.compose(sk)
    names = sk["bone_names"]
    if len(names) != sk["bone_count"]:
        skipped_clips.append((path.stem, "name count"))
        continue
    # Retargeting is a DELTA from the rest pose, not an absolute matrix copy. Copying the source's
    # armature-space matrices bakes the source bone roll into the pose, and Blender's edit bones
    # carry a different roll (they are built from head/tail with roll 0), so every bone picks up a
    # spurious twist — "limbs rotating incorrectly / rest pose mismatch" is the standard retargeting
    # failure (Unreal: "store the reference pose rotation, then get the delta between that and its
    # current rotation"; UE5 IK Retargeter docs make the same point). The delta below is the
    # world-space rotation the source bone underwent, applied to our own rest matrix, so the result
    # is independent of either rig's roll convention.
    # FRAME CORRECTION. Measured: for a standing idle every bone in `fb_idle_stand_01` showed a
    # ~180 deg delta against the unit skeleton — a constant flip between the two skeletons' frames,
    # not a pose. Applying it flips the body and any per-bone deviation tears the mesh. The
    # correction is recovered from the root bones (the only bones whose frames are not inherited
    # from a parent) and applied to every delta, which is what a retargeter's "retarget pose" step
    # does explicitly.
    root_i = next((i for i, n in enumerate(names) if n in ("Bip01", "skeleton_root")), 0)
    root_name = names[root_i]
    unit_root = arm.data.bones.get(S.canonical(root_name) or root_name)
    frame_fix = np.eye(4)
    if unit_root is not None and root_name in REST_BY_NAME:
        r_unit = np.array(unit_root.matrix_local)[:3, :3]
        r_clip = W[root_i][:3, :3]
        try:
            frame_fix[:3, :3] = r_unit @ np.linalg.inv(r_clip)
        except np.linalg.LinAlgError:
            pass
    frame_fix_inv = np.linalg.inv(frame_fix)
    print(f"FRAME fix from {root_name}")

    pose = {}
    BASE_INV = np.linalg.inv(BASE)
    for i, n in enumerate(names):
        mapped = S.canonical(n) or n
        if mapped not in arm.data.bones:
            continue
        rest = REST_BY_NAME.get(n)
        if rest is None:
            continue
        try:
            delta = W[i] @ np.linalg.inv(rest)
        except np.linalg.LinAlgError:
            continue
        delta = frame_fix_inv @ delta @ frame_fix
        delta_base = BASE @ delta @ BASE_INV
        ours = np.array(arm.data.bones[mapped].matrix_local)
        pose[mapped] = Matrix([[float((delta_base @ ours)[r][c]) for c in range(4)]
                               for r in range(4)])
    if len(pose) < 12:
        skipped_clips.append((path.stem, f"{len(pose)} bones"))
        continue
    act = bpy.data.actions.new(path.stem)
    act.use_fake_user = True
    arm.animation_data.action = act
    try:
        if arm.animation_data.action_slot is None and act.slots:
            arm.animation_data.action_slot = act.slots[0]
    except AttributeError:
        pass
    for frame in (1, 2):
        bpy.context.scene.frame_set(frame)
        for pb in ordered:
            M = pose.get(pb.name)
            if M is None:
                continue
            pb.matrix = M
            bpy.context.view_layer.update()
        for pb in arm.pose.bones:
            pb.keyframe_insert("rotation_quaternion", frame=frame)
            pb.keyframe_insert("location", frame=frame)
    applied += 1

arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)
    pb.scale = (1, 1, 1)
bpy.context.view_layer.update()
print(f"POSES applied={applied} skipped={len(skipped_clips)}")
for s in skipped_clips[:6]:
    print("   skip", s)

out = Path(A.out)
out.mkdir(parents=True, exist_ok=True)
dest = out / f"{A.id}.glb"
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=True, export_animation_mode="ACTIONS")
print(f"EXPORTED {dest} actions={len(bpy.data.actions)}")
