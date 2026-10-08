#!/usr/bin/env python3
"""Extract skeleton, animations, markers and cameras from a DoW WHM (RSGM v4/v3).

WHM chunk anatomy (verified on Definitive Edition binaries, 2026-10-08):

    RSGM
     ├─ STXT*            empty folders (texture-list stubs, v4 only)
     ├─ SHDR*            material: INFO + CHAN v3 per channel
     │    └─ CHAN        {u32 index, u32 flags, rgba tint, u32 len, path}
     │                   tint 0x808080ff = untouched; path = atlas stem
     ├─ SKEL             u32 n, per bone: u32 len,name,i32 parent,
     │                   f32 pos[3], f32 quat[x,y,z,w]   (local to parent)
     ├─ MSGR → MSLC*     meshes; DATA v2 = header + bone refs (name,index) +
     │                   verts 48B {pos3f, w3f+idx4B, n3f, uv2f} (48=skinned,
     │                   32=static {pos,n,uv}) + submesh tris + trailing tables
     ├─ DATA DATA/BVOL   message-group fallback mesh + bounds
     ├─ MARK             u32 n, per marker: u32 len,name, 48B transform
     │                   (3x3 rows + pos; row-major, column vectors) + optional
     │                   bone-name ref (sync/weapon markers). Best-effort parse.
     ├─ CAMS             u32 n, per cam: name + 9 f32 (pos3, aim3, fov/unk3?)
     └─ ANIM v3*         named chunks (header.name = animation name)
          ├─ DATA v1/v2  u32 frames, f32 unk(rate?), u32 bones,
          │              per bone: name + pos keys {u32 frame, xyz} +
          │              rot keys {u32 frame, xyzw} + stale flag (v2 bones)
          │              then meshes: name, mode{0,2}, vis keys {u32 frame,f32}
          │              v2 adds marker/cam tracks after meshes (same encoding)
          └─ ANBV        24B bounding volume (centre+extent, usually zeroed)

Animation keys are LOCAL to the parent bone, same parameterisation as SKEL
rest pose -> world transform = chain product; skinning = Σ w_i M_i(f) M_i(rest)⁻¹ v.

Usage:
    whm_animdata.py model.whm out.json [anim_substr ...]
"""
import io
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import whm_v4_patch

whm_v4_patch.patch()  # before any relic whm conversion

from relic.chunky.serializer import read_chunky
from relic.chunky.chunk.chunk import FolderChunk, GenericDataChunk
from relic.chunky.chunk.header import ChunkType
from relic.chunky_formats.dow.whm.animation import AnimDataChunk, AnimDataBoneFrameInfo


def _walk(node):
    for child in node.chunks:
        yield child
        if isinstance(child, FolderChunk):
            yield from _walk(child)


def load_whm(path_or_bytes):
    raw = path_or_bytes if isinstance((raw := path_or_bytes), bytes) else Path(path_or_bytes).read_bytes()
    return read_chunky(io.BytesIO(raw))


def parse_skel(rsgm):
    chunk = next(c for c in rsgm.chunks
                 if c.header.id == "SKEL" and c.header.type == ChunkType.Data)
    data = chunk.raw_bytes
    (count,) = struct.unpack_from("<I", data, 0)
    off = 4
    bones = []
    for _ in range(count):
        (name_len,) = struct.unpack_from("<I", data, off); off += 4
        name = data[off:off + name_len].decode("ascii"); off += name_len
        parent, px, py, pz, qx, qy, qz, qw = struct.unpack_from("<i3f4f", data, off); off += 4 + 28
        pos, rot = (px, py, pz), (qx, qy, qz, qw)
        bones.append({"name": name, "parent": parent,
                      "pos": list(pos), "rot": list(rot)})
    assert off == len(data), (off, len(data))
    return bones


def parse_anims(rsgm, filters):
    out = {}
    for node in rsgm.chunks:
        if not (isinstance(node, FolderChunk) and node.header.id == "ANIM"):
            continue
        name = node.header.name
        if filters and not any(f in str(name) for f in filters):
            continue
        data = next(c for c in node.chunks
                    if isinstance(c, GenericDataChunk) and c.header.id == "DATA")
        anim = AnimDataChunk.convert(data)
        out[name] = {
            "frames": anim.key_frames,
            "bones": {
                b.name: {
                    # dict keyed by frame index -> [x,y,z] / [x,y,z,w]
                    "pos": {str(round(float(k), 4)): list(v[1:]) for k, v in b.positions.items()},
                    "rot": {str(round(float(k), 4)): list(v[1:]) for k, v in b.rotations.items()},
                    "stale": b.stale,
                } for b in anim.bones
            },
            "meshes": [
                {
                    "name": m.name, "mode": m.mode,
                    "visibility": {str(round(float(k), 4)): v for k, v in
                                   ((f, val) for f, val in
                                    ((int(k), v[1]) for k, v in m.visibility.items()))},
                } for m in anim.meshes
            ],
            "tracks": [] if not anim.unks else [
                {
                    "name": u.name,
                    "pos": {str(round(float(k), 4)): list(v[1:]) for k, v in u.positions.items()},
                    "rot": {str(round(float(k), 4)): list(v[1:]) for k, v in u.rotations.items()},
                } for u in anim.unks
            ],
        }
    return out


def parse_markers(rsgm):
    """Best-effort: markers are transform nodes, some carry a trailing bone name."""
    chunk = next((c for c in rsgm.chunks
                  if c.header.id == "MARK" and c.header.type == ChunkType.Data), None)
    if chunk is None:
        return []
    data = chunk.raw_bytes
    (count,) = struct.unpack_from("<I", data, 0)
    off = 4
    markers = []
    for _ in range(count):
        (name_len,) = struct.unpack_from("<I", data, off); off += 4
        name = data[off:off + name_len].decode("ascii"); off += name_len
        # u32 ref-length slot (0 = none) + optional parent-bone name, then
        # 48B transform (3x3 basis rows + pos).
        bone = None
        (ref_len,) = struct.unpack_from("<I", data, off); off += 4
        if ref_len:
            ref = data[off:off + ref_len]
            if all(32 <= c < 127 for c in ref):
                bone = ref.decode()
            off += ref_len
        mat = struct.unpack_from("<12f", data, off); off += 48
        markers.append({"name": name, "bone": bone,
                        "basis": [list(mat[0:3]), list(mat[3:6]), list(mat[6:9])],
                        "pos": list(mat[9:12])})
    assert off == len(data), (off, len(data))
    return markers


def parse_cams(rsgm):
    chunk = next((c for c in rsgm.chunks
                  if c.header.id == "CAMS" and c.header.type == ChunkType.Data), None)
    if chunk is None:
        return []
    data = chunk.raw_bytes
    (count,) = struct.unpack_from("<I", data, 0)
    off = 4
    cams = []
    for _ in range(count):
        (name_len,) = struct.unpack_from("<I", data, off); off += 4
        name = data[off:off + name_len].decode("ascii"); off += name_len
        flag = struct.unpack_from("<I", data, off); off += 4
        mat = struct.unpack_from("<12f", data, off); off += 48
        cams.append({"name": name, "flag": flag,
                     "basis": [list(mat[0:3]), list(mat[3:6]), list(mat[6:9])],
                     "pos": list(mat[9:12])})
    assert off == len(data), (off, len(data))
    return cams


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    src, dst = argv[1], argv[2]
    filters = argv[3:]
    root = load_whm(src)
    rsgm = root.chunks[0]
    doc = {
        "source": str(src),
        "skeleton": parse_skel(rsgm),
        "animations": parse_anims(rsgm, filters),
        "markers": parse_markers(rsgm),
        "cameras": parse_cams(rsgm),
    }
    Path(dst).write_text(json.dumps(doc, indent=1))
    print(f"{dst}: {len(doc['skeleton'])} bones, {len(doc['animations'])} anims "
          f"({', '.join(sorted(doc['animations']))[:400]}), "
          f"{len(doc['markers'])} markers, {len(doc['cameras'])} cams")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
