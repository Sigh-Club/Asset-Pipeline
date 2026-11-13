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
