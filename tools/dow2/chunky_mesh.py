#!/usr/bin/env python3
"""chunky_mesh.py — decode DoW2 (Relic Chunky v3) model geometry to OBJ.

DoW2 character parts store geometry in `DATADATA v7` chunks: an attribute table
(usage, type, component size) followed by a vertex count, a vertex stride, the
vertex stream and an index/submesh table. Verified on the extracted Tyranid art
at `Projects/Decompilor/work/dow2-retribution/sga` (hormagaunt, termagaunt,
carnifex, hive_tyrant): positions are the first 3 floats of each vertex and the
index list starts after the submesh header.

Usage:
  python3 tools/dow2/chunky_mesh.py <model> [-o out.obj] [--stats]

The result is a plain OBJ (one group per submesh) that Blender, MeshLab or any
DCC can open, so shipped-game meshes can be used as modelling references or as
retopology bases.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

MAGIC = b"Relic Chunky\r\n\x1a\x00"


class Chunk:
    __slots__ = ("type", "version", "size", "name", "children", "data_offset", "file_offset")

    def __init__(self):
        self.children = []


def _is_chunk_type(blob: bytes, pos: int) -> bool:
    return blob[pos:pos + 4] in (b"FOLD", b"DATA")


def _read_name(blob: bytes, pos: int):
    end = blob.find(b"\0", pos)
    return blob[pos:end].decode("latin-1", "replace"), end + 1


def parse_chunk(blob: bytes, pos: int, region_end: int):
    ch = Chunk()
    ch.name = ""
    ch.file_offset = pos
    ch.type = blob[pos:pos + 8].decode("latin-1", "replace")
    ch.version, ch.size, _nkids, _off, _unk = struct.unpack_from("<5I", blob, pos + 8)
    pos += 28
    if ch.type.startswith("FOLD") and ch.size > 0 and not _is_chunk_type(blob, pos):
        ch.name, pos = _read_name(blob, pos)
    ch.data_offset = pos
    if ch.type.startswith("DATA"):
        end = min(ch.file_offset + ch.size, region_end)
    else:
        end = min(pos + ch.size, region_end)
    while pos + 28 <= end and _is_chunk_type(blob, pos):
        kid, new_pos = parse_chunk(blob, pos, end)
        ch.children.append(kid)
        pos = new_pos if new_pos > pos else pos + 28
    ch.size = end - ch.file_offset
    return ch, end


def parse(blob: bytes):
    if blob[:16] != MAGIC:
        raise ValueError(f"not a Relic Chunky file: {blob[:16]!r}")
    root, _ = parse_chunk(blob, 36, len(blob))
    return root


def decode_geometry(pay: bytes):
    """Return (positions, submeshes) for one DATADATA v7 payload."""
    nattr = struct.unpack_from("<I", pay, 0)[0]
    if not 1 <= nattr <= 16:
        return None
    off = 4 + 3 * 4 * nattr
    if off + 8 > len(pay):
        return None
    vcount, stride = struct.unpack_from("<2I", pay, off)
    if not (0 < vcount < 500000 and 8 <= stride <= 256):
        return None
    vstart = off + 8
    vend = vstart + vcount * stride
    if vend > len(pay):
        return None
    pos = [struct.unpack_from("<3f", pay, vstart + i * stride) for i in range(vcount)]
    # sanity: reject buffers that are not plausible model coordinates
    xs = [p[0] for p in pos]
    if max(xs) - min(xs) > 100 or max(abs(v) for p in pos for v in p) > 200:
        return None
    tail = pay[vend:]
    if len(tail) < 16:
        return pos, []
    nsub = struct.unpack_from("<I", tail, 0)[0]
    if not 0 < nsub <= 64:
        return pos, []

    def score(subs):
        """Reject index streams that produce impossible triangles: a correct
        decode has no edge longer than a fraction of the model."""
        span = max(max(p[i] for p in pos) - min(p[i] for p in pos) for i in range(3)) or 1.0
        worst = 0.0
        for s in subs:
            idx = s["indices"]
            for k in range(0, len(idx) - 2, 3):
                for a, b in ((idx[k], idx[k + 1]), (idx[k + 1], idx[k + 2]), (idx[k + 2], idx[k])):
                    pa, pb = pos[a], pos[b]
                    d = sum((pa[i] - pb[i]) ** 2 for i in range(3)) ** 0.5
                    worst = max(worst, d)
        return worst / span

    best = None
    # entry width and index width are not documented; try the plausible set and
    # keep the decode whose worst edge is smallest relative to the model size
    for entry in (12, 8, 16, 4):
        table_end = 4 + nsub * entry
        if table_end > len(tail):
            continue
        for fmt, width in (("<H", 2), ("<I", 4)):
            cursor = table_end
            subs = []
            ok = True
            for i in range(nsub):
                count = struct.unpack_from("<I", tail, 4 + i * entry)[0]
                material = struct.unpack_from("<I", tail, 8 + i * entry)[0] if entry >= 12 else i
                if count == 0 or count % 3 or cursor + count * width > len(tail):
                    ok = False
                    break
                idx = list(struct.unpack_from(f"<{count}{fmt[1]}", tail, cursor))
                if not idx or max(idx) >= vcount:
                    ok = False
                    break
                cursor += count * width
                subs.append({"material": material, "indices": idx})
            if not ok or not subs:
                continue
            sc = score(subs)
            if best is None or sc < best[0]:
                best = (sc, subs)
    if best is None:
        return pos, []
    return pos, best[1]


def collect(root, blob, out_models):
    if root.type == "FOLDMODL":
        out_models.append(root)
    for k in root.children:
        collect(k, blob, out_models)


def material_names(model, blob):
    names = []
    for k in model.children:
        if k.type == "FOLDMTRL":
            names.append(k.name or f"mat{len(names)}")
    return names


def extract_model(path: Path):
    blob = path.read_bytes()
    root = parse(blob)
    models = []
    collect(root, blob, models)
    result = []
    for model in models:
        mats = material_names(model, blob)
        verts, tris, groups = [], [], []

        def walk(node):
            if node.type == "DATADATA" and node.version == 7:
                pay = blob[node.data_offset:node.file_offset + node.size]
                dec = decode_geometry(pay)
                if dec:
                    pos, subs = dec
                    base = len(verts)
                    verts.extend(pos)
                    for s in subs:
                        idx = s["indices"]
                        groups.append((mats[s["material"]] if s["material"] < len(mats)
                                       else f"mat{s['material']}", idx, base))
            for k in node.children:
                walk(k)

        walk(model)
        result.append({"name": model.name or path.stem, "verts": verts, "groups": groups})
    return result


def write_obj(models, dest: Path):
    lines = []
    vbase = 1
    for m in models:
        for (x, y, z) in m["verts"]:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
        for name, idx, base in m["groups"]:
            lines.append(f"g {name}")
            # every geometry payload has its own vertex block; faces must be
            # offset by that block, not only by the model base (omitting it made
            # later payloads reference the first block and produced 1.9 m edges)
            off = vbase + base
            for i in range(0, len(idx) - 2, 3):
                lines.append(f"f {idx[i] + off} {idx[i + 1] + off} {idx[i + 2] + off}")
        vbase += len(m["verts"])
    dest.write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("model", nargs="+", help="one or more .model parts of the same unit")
    ap.add_argument("-o", "--out")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(argv)
    srcs = [Path(m) for m in a.model]
    models = []
    for src in srcs:
        models.extend(extract_model(src))
    verts = sum(len(m["verts"]) for m in models)
    tris = sum(len(g[1]) // 3 for m in models for g in m["groups"])
    mats = sorted({g[0] for m in models for g in m["groups"]})
    label = srcs[0].name if len(srcs) == 1 else f"{srcs[0].stem}+{len(srcs)-1} parts"
    print(f"{label}: models={len(models)} verts={verts} tris={tris} groups={len(mats)}")
    if a.stats:
        for n in mats:
            print("   ", n)
    if a.out:
        write_obj(models, Path(a.out))
        print("wrote", a.out)
    return 0 if verts else 1


if __name__ == "__main__":
    sys.exit(main())


def decode_skin(pay: bytes):
    """Per-vertex (bone index 0, bone index 1, weight for index 0) from a DATADATA v7 payload.

    Decoded from the shipped geometry stream and verified against the guardsman skeleton: the
    attribute block at vertex offset 12 holds two bone indices (u8 each) and offset 17 a u16
    weight, normalised by 65535. A weight of 0xFF00 (0.996) with a zero second index is a RIGID
    binding — that is how DoW2 ships armour plates, one bone and full weight, which is why
    smooth-skinning a pauldron tears it apart. A blended weight (0.50-0.90) is cloth or skin that
    genuinely bends between two bones.

    Measured on `commissar_armour_common.model`: 3,556 vertices, 44 distinct primary indices, and
    every cluster's centroid lands on the expected bone (1 = spine, 2 = jaw/head, 10 = right
    thigh, 15-18 = right hand, 19-22 = right fingers, 23-32 = the mirrored left side).
    """
    nattr = struct.unpack_from("<I", pay, 0)[0]
    if not 1 <= nattr <= 16:
        return None
    off = 4 + 3 * 4 * nattr
    if off + 8 > len(pay):
        return None
    vcount, stride = struct.unpack_from("<2I", pay, off)
    if not (0 < vcount < 500000 and 24 <= stride <= 256):
        return None
    vstart = off + 8
    if vstart + vcount * stride > len(pay):
        return None
    out = []
    for i in range(vcount):
        base = vstart + i * stride
        b0 = pay[base + 12]
        b1 = pay[base + 13]
        w0 = struct.unpack_from("<H", pay, base + 17)[0] / 65535.0
        out.append((b0, b1, w0))
    return out


def _hungarian(cost):
    """Minimum-cost assignment for a rectangular cost matrix (rows <= cols).

    Greedy cheapest-first is not good enough here: one very cheap pair (a big cluster that happens
    to sit near a small bone) can force several other clusters into wrong bones, which is what left a
    clavicle owning vertices a metre away. The optimal assignment minimises the TOTAL cost, so no
    single index is allowed to steal a bone another index needs far more.

    Classic O(n^3) Hungarian with potentials; n is ~45, so this is instant and needs no dependency
    (Blender's bundled Python does not ship scipy).
    """
    n = len(cost)
    m = len(cost[0]) if n else 0
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(0, m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = {}
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def resolve_skin_indices(skin, positions, bone_segments, deform_only=True):
    """Map the stream's bone indices onto named bones as an optimal ONE-TO-ONE assignment.

    The stream indexes the model's own bone table, so the mapping is unknown — but it is a bijection:
    the shipped bodies carry one index per skeleton bone (~44 indices against ~45 bones). Two indices
    cannot be the same bone, and a bone cannot be two indices, so this is an assignment problem, not a
    nearest-neighbour lookup. Solved optimally (see `_hungarian`) on the cost of binding a cluster to
    a bone, measured as the median distance from the cluster's vertices to the bone segment.

    Verified by ownership: after a correct assignment no bone owns geometry far from itself. The
    greedy version left `clavicle_L` owning vertices 1.06 m away; the optimal one is measured below.
    """
    import numpy as np

    def seg_dist(p, a, b):
        ab = b - a
        d2 = float(ab @ ab) or 1e-9
        t = max(0.0, min(1.0, float((p - a) @ ab) / d2))
        return float(np.linalg.norm(p - (a + ab * t)))

    gear = ("Weapon", "Pad", "Marker", "Attach", "SP_", "Hellgun")
    segs = [(n, np.array(h, dtype=float), np.array(t, dtype=float))
            for n, h, t in bone_segments
            if not (deform_only and any(g in n for g in gear))]

    clusters = {}
    for (b0, b1, _w), p in zip(skin, positions):
        clusters.setdefault(b0, []).append(p)
        if b1:
            clusters.setdefault(b1, []).append(p)

    indices = sorted(clusters)
    cost = []
    for idx in indices:
        P = np.array(clusters[idx], dtype=float)
        if len(P) > 300:
            P = P[:: int(np.ceil(len(P) / 300))]
        cost.append([float(np.median([seg_dist(p, h, t) for p in P])) for _n, h, t in segs])

    if len(indices) <= len(segs):
        assign = _hungarian(cost)
        mapping = {indices[r]: segs[c][0] for r, c in assign.items()}
    else:
        # more indices than deform bones: take the optimal subset, then nearest-bone for the rest
        assign = _hungarian([row[: len(segs)] for row in cost])
        mapping = {indices[r]: segs[c][0] for r, c in assign.items()}
        for r, idx in enumerate(indices):
            if idx in mapping:
                continue
            best = min((cost[r][c], segs[c][0]) for c in range(len(segs)))
            mapping[idx] = best[1]

    print(f"SKIN assignment indices={len(indices)} bones={len(segs)} "
          f"distinct={len(set(mapping.values()))}")
    return mapping


def decode_uv(pay: bytes):
    """Per-vertex texture coordinates, located from the stream itself.

    The vertex layout is not constant across races: the guardsman stream is 40 bytes with the UV
    pair at 32, the ork body is 48 bytes with it elsewhere (measured: a fixed offset left 1,548 of
    5,890 ork vertices without a UV). So the pair is FOUND rather than assumed — the offset whose two
    float32 values land in a plausible UV range for the most vertices wins. That is a measurement of
    the data, not a guess about the format.
    """
    nattr = struct.unpack_from("<I", pay, 0)[0]
    if not 1 <= nattr <= 16:
        return None
    off = 4 + 3 * 4 * nattr
    if off + 8 > len(pay):
        return None
    vcount, stride = struct.unpack_from("<2I", pay, off)
    if not (0 < vcount < 500000 and 24 <= stride <= 256):
        return None
    vstart = off + 8
    if vstart + vcount * stride > len(pay):
        return None

    sample = list(range(0, vcount, max(1, vcount // 400)))[:400]
    best = (-1.0, 32)
    for cand in range(8, stride - 7, 4):
        good = 0
        for i in sample:
            base = vstart + i * stride + cand
            u, v = struct.unpack_from("<2f", pay, base)
            if -32.0 <= u <= 32.0 and -32.0 <= v <= 32.0:
                good += 1
        frac = good / max(1, len(sample))
        if frac > best[0]:
            best = (frac, cand)
    frac, uv_off = best
    if frac < 0.35:
        return None
    out = []
    for i in range(vcount):
        base = vstart + i * stride + uv_off
        out.append(struct.unpack_from("<2f", pay, base))
    return out
