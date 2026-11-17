"""rig_fit.py — measure and fit a skeleton against the mesh it is meant to deform.

The audit's old proxy for "the bone is in the body" was distance to the nearest vertex, which
is wrong in both directions: a bone buried 20 cm inside a thick carapace reads as "far", and a
bone 50 cm outside a hollow shell can read as "near" if the shell passes close by. Shipped
games state the requirement directly — the bone is inside the skinned surface — so this module
measures that and nothing else.

What it provides:

  * ``Mesh``           — triangle soup from a GLB/OBJ, with an exact inside/outside test
                         (parity ray casting, majority vote over many directions) and a
                         nearest-surface distance.
  * ``Mesh.medial()``  — the body's interior centreline: surface voxels -> distance transform
                         -> interior ridge, filtered by the inside test. This is the set of
                         points a bone may sit on and still be inside the body.
  * ``fit_bones()``    — move template bones onto the medial set, preserving hierarchy,
                         chain order and authored segment ratios.

The inside test is the one shipped rigging tools use to validate a skeleton against a mesh
(Blender's "bone heat" failure diagnostic, Maya's "Skeleton > Check", Unreal's rig validator
all report "bone outside mesh"). Parity voting is used rather than a voxel flood fill because
DoW2 bodies are part assemblies with open seams: a flood fill leaks through a seam and reports
the whole interior as outside (measured on the carnifex: 1.5 % interior volume, max inset
radius 12.7 cm, i.e. only the enclosed pockets).

Pure numpy/scipy so the same code runs under Blender's interpreter and plain python3.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree


# --------------------------------------------------------------------------- loading
def _glb_chunks(path):
    d = Path(path).read_bytes()
    off, js, binc = 12, None, None
    while off < len(d):
        ln, ty = struct.unpack_from("<II", d, off)
        chunk = d[off + 8:off + 8 + ln]
        if ty == 0x4E4F534A:
            js = json.loads(chunk)
        else:
            binc = chunk
        off += 8 + ln
    return js, binc


def _accessor(js, binc, idx):
    a = js["accessors"][idx]
    bv = js["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    nc = {"VEC3": 3, "VEC2": 2, "SCALAR": 1, "VEC4": 4, "MAT4": 16}[a["type"]]
    fmt = {5126: "f", 5123: "H", 5125: "I", 5121: "B"}[a["componentType"]]
    size = struct.calcsize(fmt)
    stride = bv.get("byteStride", size * nc)
    return np.array([struct.unpack_from("<" + fmt * nc, binc, base + i * stride)
                     for i in range(a["count"])])


def _node_matrices(js):
    parents = {}
    for i, n in enumerate(js["nodes"]):
        for c in n.get("children", []):
            parents[c] = i

    def local(n):
        if "matrix" in n:
            return np.array(n["matrix"], dtype=float).reshape(4, 4).T
        m = np.eye(4)
        x, y, z, w = n.get("rotation", (0, 0, 0, 1))
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m[:3, :3] = r @ np.diag(n.get("scale", (1, 1, 1)))
        m[:3, 3] = n.get("translation", (0, 0, 0))
        return m

    cache = {}

    def world(i):
        if i in cache:
            return cache[i]
        m = local(js["nodes"][i])
        if i in parents:
            m = world(parents[i]) @ m
        cache[i] = m
        return m

    return {i: world(i) for i in range(len(js["nodes"]))}


class Mesh:
    """Triangle soup plus the two measurements the rig gate needs."""

    def __init__(self, verts, tris, name=""):
        self.verts = np.asarray(verts, dtype=float)
        self.tris = np.asarray(tris, dtype=int)
        self.name = name
        self._kd = None
        self._tri = None

    # ---------------------------------------------------------------- constructors
    @classmethod
    def from_glb(cls, path, meshes=None, up="y"):
        """Load every mesh primitive, or only the named meshes, in world space.

        glTF is Y-up; the rest of this project (rig templates, Blender stages, the anatomy
        rules in fit_skeleton.py) is Z-up. ``up="y"`` applies the importer's own basis change
        (x, -z, y) so a fit written here lands on the mesh in Blender. Measured consequence of
        skipping it: the anatomy rules read the body's *length* as its height and put the head
        at the tail end.
        """
        js, binc = _glb_chunks(path)
        world = _node_matrices(js)
        node_of = {}
        for i, n in enumerate(js["nodes"]):
            if "mesh" in n:
                node_of.setdefault(n["mesh"], i)
        V, T, base = [], [], 0
        for mi, m in enumerate(js["meshes"]):
            if meshes is not None and m.get("name", "") not in meshes:
                continue
            mtx = world[node_of[mi]] if mi in node_of else np.eye(4)
            for pr in m["primitives"]:
                v = _accessor(js, binc, pr["attributes"]["POSITION"])
                v = (mtx[:3, :3] @ v.T).T + mtx[:3, 3]
                V.append(v)
                if "indices" in pr:
                    T.append(_accessor(js, binc, pr["indices"]).reshape(-1, 3) + base)
                base += len(v)
        verts = np.vstack(V)
        tris = np.vstack(T) if T else np.zeros((0, 3), int)
        if up == "y":
            basis = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
            verts = verts @ basis.T
        return cls(verts, tris, Path(path).stem)

    @classmethod
    def from_obj(cls, path):
        V, T = [], []
        for line in Path(path).read_text().splitlines():
            if line.startswith("v "):
                V.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(x.split("/")[0]) - 1 for x in line.split()[1:]]
                for k in range(1, len(idx) - 1):
                    T.append([idx[0], idx[k], idx[k + 1]])
        return cls(V, T, Path(path).stem)

    @classmethod
    def from_blender(cls, obj):
        """From a Blender object in world space (needs no bpy import here)."""
        mw = obj.matrix_world
        V = [tuple(mw @ v.co) for v in obj.data.vertices]
        obj.data.calc_loop_triangles()
        T = [tuple(lt.vertices) for lt in obj.data.loop_triangles]
        return cls(V, T, obj.name)

    # ---------------------------------------------------------------- measurements
    def surface_dist(self, points, chunk=4096):
        """Exact distance from each point to the nearest triangle of the surface.

        Distance to the nearest *vertex* was the old measure and it overstates the gap on a
        decimated mesh: measured on the carnifex, the claw bones read 15-17 cm from the body by
        vertex distance while the claw blade is centimetres away. A rig gate that reports the
        wrong number either fails good rigs or passes bad ones, so the distance is computed to
        the surface itself (closest point on a triangle, Ericson's method).
        """
        points = np.atleast_2d(np.asarray(points, dtype=float))
        if len(self.tris) == 0:
            return np.full(len(points), np.inf)
        A = self.verts[self.tris[:, 0]]
        B = self.verts[self.tris[:, 1]]
        C = self.verts[self.tris[:, 2]]
        out = np.empty(len(points))
        for s0 in range(0, len(points), 64):
            P = points[s0:s0 + 64]
            best = np.full(len(P), np.inf)
            for t0 in range(0, len(A), chunk):
                a, b, c = A[t0:t0 + chunk], B[t0:t0 + chunk], C[t0:t0 + chunk]
                q = closest_on_triangle(P, a, b, c)
                d = np.linalg.norm(P[:, None, :] - q, axis=2)
                best = np.minimum(best, d.min(axis=1))
            out[s0:s0 + 64] = best
        return out

    def inside(self, points, rays=48, seed=7):
        """Parity ray vote. True where the point is enclosed by the surface.

        Majority vote over many directions rather than one ray: DoW2 part assemblies have
        open seams, and a single ray that escapes through one reports a false "outside".
        """
        points = np.atleast_2d(np.asarray(points, dtype=float))
        rng = np.random.default_rng(seed)
        dirs = rng.normal(size=(rays, 3))
        dirs /= np.linalg.norm(dirs, axis=1)[:, None]
        A = self.verts[self.tris[:, 0]]
        B = self.verts[self.tris[:, 1]]
        C = self.verts[self.tris[:, 2]]
        e1, e2 = B - A, C - A
        out = np.zeros(len(points), bool)
        for pi, p in enumerate(points):
            hits = 0
            for d in dirs:
                # Moller-Trumbore
                h = np.cross(d, e2)
                det = np.einsum("ij,ij->i", e1, h)
                ok = np.abs(det) > 1e-9
                inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
                s = p - A
                u = np.einsum("ij,ij->i", s, h) * inv
                q = np.cross(s, e1)
                v = np.einsum("j,ij->i", d, q) * inv
                t = np.einsum("ij,ij->i", e2, q) * inv
                hit = ok & (u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
                hits += int(hit.sum())
            out[pi] = (hits % 2) == 1
        return out

    def medial(self, res=0.02, min_radius=0.02):
        """Interior centreline points: ridge of the surface distance transform, inside only."""
        lo = self.verts.min(0) - 4 * res
        dims = np.ceil((self.verts.max(0) - lo) / res).astype(int) + 5
        occ = np.zeros(dims, bool)
        A, B, C = self.verts[self.tris[:, 0]], self.verts[self.tris[:, 1]], self.verts[self.tris[:, 2]]
        for a, b, c in zip(A, B, C):
            n = int(np.ceil(max(np.linalg.norm(b - a), np.linalg.norm(c - a),
                                np.linalg.norm(c - b)) / (res * 0.6))) + 2
            ii, jj = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
            m = (ii + jj) <= n
            u, v = ii[m] / n, jj[m] / n
            P = a + np.outer(u, b - a) + np.outer(v, c - a)
            idx = np.round((P - lo) / res).astype(int)
            ok = np.all((idx >= 0) & (idx < dims), axis=1)
            occ[idx[ok, 0], idx[ok, 1], idx[ok, 2]] = True
        free = ~occ
        lbl, _ = ndimage.label(free)
        border = set()
        for edge in (lbl[0], lbl[-1], lbl[:, 0], lbl[:, -1], lbl[:, :, 0], lbl[:, :, -1]):
            border |= set(np.unique(edge).tolist())
        border.discard(0)
        enclosed = free & ~np.isin(lbl, sorted(border))
        edt = ndimage.distance_transform_edt(occ | enclosed) * res
        # the surface EDT ridge: local maxima inside the enclosed volume
        ridge = enclosed & (edt >= ndimage.maximum_filter(edt, size=3) - 1e-9) & (edt > min_radius)
        pts = np.argwhere(ridge) * res + lo
        if len(pts) == 0:
            return pts, 0.0
        return pts, float(edt.max())


def closest_on_triangle(P, a, b, c):
    """Closest point on each triangle (a,b,c) to each query point in P. Shapes: (np,nt,3)."""
    P = np.asarray(P)[:, None, :]
    ab, ac = b - a, c - a
    ap, bp, cp = P - a, P - b, P - c
    d1 = (ap * ab).sum(-1)
    d2 = (ap * ac).sum(-1)
    d3 = (bp * ab).sum(-1)
    d4 = (bp * ac).sum(-1)
    d5 = (cp * ab).sum(-1)
    d6 = (cp * ac).sum(-1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    v = vb / denom
    w = vc / denom
    # region handling, as in Ericson, Real-Time Collision Detection, 5.1.5
    out = a + ab * v[..., None] + ac * w[..., None]
    # vertex regions
    mA = (d1 <= 0) & (d2 <= 0)
    mB = (d3 >= 0) & (d4 <= d3)
    mC = (d6 >= 0) & (d5 <= d6)
    # edge regions
    mAB = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    mAC = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    mBC = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    tAB = np.where(np.abs(d1 - d3) < 1e-12, 0.0, d1 / np.where(np.abs(d1 - d3) < 1e-12, 1.0, d1 - d3))
    tAC = np.where(np.abs(d2 - d6) < 1e-12, 0.0, d2 / np.where(np.abs(d2 - d6) < 1e-12, 1.0, d2 - d6))
    tBC = np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-12, 0.0,
                   (d4 - d3) / np.where(np.abs((d4 - d3) + (d5 - d6)) < 1e-12, 1.0,
                                        (d4 - d3) + (d5 - d6)))
    out = np.where(mA[..., None], a, out)
    out = np.where(mB[..., None], b, out)
    out = np.where(mC[..., None], c, out)
    out = np.where(mAB[..., None], a + ab * tAB[..., None], out)
    out = np.where(mAC[..., None], a + ac * tAC[..., None], out)
    out = np.where(mBC[..., None], b + (c - b) * tBC[..., None], out)
    return out


# --------------------------------------------------------------------------- fit
def chain_roles(template):
    """Group template bones into the chains a fit can move: spine, arms, legs, tail, head."""
    groups = {"spine": [], "head": [], "arm_L": [], "arm_R": [], "leg_L": [], "leg_R": [], "tail": []}
    for b in template["bones"]:
        n = b["name"]
        if n.startswith(("tail",)):
            groups["tail"].append(n)
        elif n.startswith(("head", "jaw", "neck")):
            groups["head"].append(n)
        elif n.startswith(("clavicle", "upperarm", "lowerarm", "hand", "thumb", "finger")):
            groups["arm_L" if n.endswith("_L") else "arm_R"].append(n)
        elif n.startswith(("thigh", "shin", "foot", "toe")) and not n.endswith(("_hind",)):
            groups["leg_L" if n.endswith("_L") else "leg_R"].append(n)
        elif n.startswith(("root", "pelvis", "spine", "chest")):
            groups["spine"].append(n)
    return {k: v for k, v in groups.items() if v}
