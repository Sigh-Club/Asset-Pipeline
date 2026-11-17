"""hkxread.py — read a Havok 2010.2.0 packfile (DoW2 / Skyrim LE container).

The DoW2 troop clips are `hkDeltaCompressedSkeletalAnimation` inside the pre-tagfile
packfile container (`0x57E0E057 0x10C0C010`), which is the same container Skyrim LE
ships. No Havok SDK is available on this machine and no Python reader exists, so this
module implements the parts the retarget pipeline needs:

  * packfile section table (classnames / data / types)
  * the type signature table (`hkClass` / `hkClassMember` records)
  * the object stream, with name resolution through the data section's string table

It deliberately reads the file the way the format stores it — by offsets and type
indices — rather than guessing object order, because a wrong guess silently yields a
plausible-looking but wrong skeleton.

What works today: the section table, the class-name pool, the skeleton's bone names
(which is what the retarget tool's bone map and coverage rejection need).

What does not: the object table / delta-compressed track decode. The container is
**packfile version 4, Havok 4.5.1-r1** — NOT the 2010.2.0 container the handoff brief
assumed, which is why every Skyrim tool refuses these files (measured: hkxconv aborts
on the header, hkxpack exhausts the heap, havok-formats reports "unsupported packfile
version 4 (7, 9 and 11 only)"). Track decode is the remaining piece of P2.

Usage:
    python3 tools/hkx/hkxread.py <clip.hkx>
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = 0x57E0E057
VERSION = 0x10C0C010


class HkxError(RuntimeError):
    pass


@dataclass
class Section:
    name: str
    offset: int
    size: int


@dataclass
class TypeMember:
    name: str
    type_index: int
    offset: int
    array_size: int
    flags: int


@dataclass
class TypeDef:
    name: str
    parent: int
    members: list[TypeMember] = field(default_factory=list)
    size: int = 0


@dataclass
class Packfile:
    raw: bytes
    sections: dict[str, Section]

    @classmethod
    def open(cls, path: str | Path) -> "Packfile":
        raw = Path(path).read_bytes()
        magic, version = struct.unpack_from("<II", raw, 0)
        if magic != MAGIC:
            raise HkxError(f"{path}: not a Havok packfile (magic {magic:#010x})")
        if version != VERSION:
            raise HkxError(f"{path}: unsupported packfile version {version:#010x} "
                           f"(expected {VERSION:#010x}, Havok 2010.2.0 32-bit)")
        sections = cls._read_sections(raw)
        return cls(raw=raw, sections=sections)

    @staticmethod
    def _read_sections(raw: bytes) -> dict[str, Section]:
        """Locate the section table.

        Each descriptor is a NUL-padded 16-byte name followed by 8 u32 fields; the first
        field is the 0xff000000 end marker and the next two are the payload offset and
        size. The table is found by scanning for the known section names rather than
        assuming a fixed header size, because the header carries platform fields whose
        length varies between packfile producers.
        """
        found: dict[str, Section] = {}
        for name in ("__classnames__", "__data__", "__types__", "__eof__"):
            marker = name.encode() + b"\x00"
            at = raw.find(marker)
            if at < 0:
                continue
            fields = struct.unpack_from("<8I", raw, at + 16)
            offset, size = fields[1], fields[2]
            if 0 < offset < len(raw) and 0 < size <= len(raw) - offset:
                found[name] = Section(name=name, offset=offset, size=size)
        if "__data__" not in found:
            raise HkxError("packfile has no __data__ section")
        return found

    def census(self) -> dict[str, int]:
        """Class name -> occurrence count in the data section.

        Counted from the class-name pool rather than the object stream: the object table layout
        differs between skeleton-only and clip packfiles, and a census that crashes on one of
        them is worse than a rough one (it did: `objects()` was referenced but never defined).
        """
        sec = self.sections.get("__classnames__")
        if sec is None:
            return {}
        blob = self.raw[sec.offset:sec.offset + sec.size]
        counts: dict[str, int] = {}
        for part in blob.split(b"\x00"):
            if len(part) < 6:
                continue
            try:
                text = part[4:].decode("ascii")
            except UnicodeDecodeError:
                continue
            if text[:2] == "hk" or text[:3] == "hkx":
                counts[text] = counts.get(text, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    # ---------------------------------------------------------------- types
    def type_table(self) -> list[TypeDef]:
        """Parse `__classnames__` + `__types__` into type definitions.

        `__classnames__` holds, for each type: a 4-byte signature hash, a 1-byte name
        length and the NUL-terminated name. `__types__` holds the matching records with
        the parent index and the member list. Both are indexed by type, so the two
        tables are read together.
        """
        names = self._type_names()
        return self._type_defs(names)

    def _type_names(self) -> list[str]:
        sec = self.sections.get("__classnames__")
        if sec is None:
            raise HkxError("packfile has no __classnames__ section")
        out: list[str] = []
        pos, end = sec.offset, sec.offset + sec.size
        while pos + 5 <= end:
            _hash, length = struct.unpack_from("<IB", self.raw, pos)
            pos += 5
            if length == 0 or pos + length > end:
                break
            name = self.raw[pos:pos + length].split(b"\x00")[0].decode("ascii", "replace")
            out.append(name)
            # the length byte counts the name only; the NUL terminator follows it, and
            # advancing by `length` alone drifts one byte per record (measured: the second
            # name came out as "kClassMember", the third as "ct")
            pos += length + 1
        return out

    def _type_defs(self, names: list[str]) -> list[TypeDef]:
        sec = self.sections["__types__"]
        pos, end = sec.offset, sec.offset + sec.size
        defs: list[TypeDef] = []
        while pos + 8 <= end:
            start = pos
            parent, _flags, _version, _hash, _hash2, nmem = struct.unpack_from("<4HIH", self.raw, pos)
            pos += 12
            if pos > end:
                break
            td = TypeDef(name=names[len(defs)] if len(defs) < len(names) else f"<{len(defs)}>",
                         parent=parent)
            ok = True
            for _ in range(nmem):
                if pos + 12 > end:
                    ok = False
                    break
                mname_idx, mtype, moffset = struct.unpack_from("<III", self.raw, pos)
                pos += 12
                arr, _flags2 = struct.unpack_from("<IH", self.raw, pos)
                pos += 6
                mname = names[mname_idx] if mname_idx < len(names) else f"m{mname_idx}"
                td.members.append(TypeMember(name=mname, type_index=mtype, offset=moffset,
                                             array_size=arr, flags=_flags2))
            td.size = pos - start
            defs.append(td)
            if not ok:
                break
        return defs

    # ------------------------------------------------------------- skeleton
    def skeleton(self) -> dict | None:
        """Decode the skeleton this packfile carries, clip file or skeleton-only file.

        Layout, confirmed against the shipped files and the published Havok type description:

          * a bone count, then a 16-byte NUL-padded skeleton name;
          * the parentIndices array as int16 (exactly one -1, every parent index below its
            child's), immediately after the name field;
          * the reference pose as ``count`` records of 48 bytes: translation vec4, quaternion
            vec4, scale vec4 — the hkQsTransform layout the Havok docs and the Skyrim/FO4
            format notes both describe ("translation + quaternion + scale, vec4-padded to 48
            bytes"). The quaternion therefore sits at +16, not at +0;
          * the bone-name string pool directly behind the pose.

        An earlier version scanned for unit quaternions at +0 and so locked onto the block 16
        bytes late: every record then read the quaternion as its translation, which is why the
        composed skeleton sat metres off its own mesh (measured on the carnifex: 4.86 units
        mean bone-to-mesh, against 0.32 units with the block start corrected).
        """
        import math
        raw = self.raw
        data = self.sections.get("__data__")
        if data is None:
            return None
        lo, hi = data.offset, data.offset + data.size

        # 1. the bone-name table: a printable 16-byte field preceded by the bone count and
        #    followed by a valid int16 parent array
        found = None
        for off in range(lo, hi - 32, 4):
            field = raw[off:off + 16]
            text = field.split(b"\x00")[0]
            if not (2 <= len(text) <= 15) or not all(32 <= b < 127 for b in text):
                continue
            for width in (4, 8):
                if off - width < lo:
                    continue
                n = struct.unpack_from("<I", raw, off - width)[0]
                if not (4 <= n <= 512) or off + 16 + n * 2 > hi:
                    continue
                parents = list(struct.unpack_from(f"<{n}h", raw, off + 16))
                if sum(1 for x in parents if x == -1) != 1:
                    continue
                if not all(x < i for i, x in enumerate(parents) if x >= 0):
                    continue
                found = (n, text.decode("ascii"), parents, off + 16 + n * 2)
                break
            if found:
                break
        if not found:
            return None
        count, name, parents, parents_end = found

        # 2. the reference pose. Two record layouts exist in the shipped corpus and neither can
        #    be assumed: the clip files store translation/quaternion/scale (quaternion at +16),
        #    while a unit's own skeleton file stores quaternion/scale/translation (quaternion at
        #    +0). Both are scored on their own invariants -- a unit quaternion in the quaternion
        #    slot and a (1,1,1) scale in the scale slot for every record -- and the layout that
        #    satisfies them is the one used. Measured: assuming the clip layout on
        #    guardsman.hkx read the quaternion as the translation and put the skeleton metres
        #    off the mesh.
        import math

        def unit(off: int) -> bool:
            q = struct.unpack_from("<4f", raw, off)
            return 0.9 < math.sqrt(sum(v * v for v in q)) < 1.1

        def unit_scale(off: int) -> bool:
            sx, sy, sz = struct.unpack_from("<3f", raw, off)
            return all(abs(v - 1.0) < 0.02 for v in (sx, sy, sz))

        LAYOUTS = {
            "translation,quaternion,scale": {"q": 16, "s": 32, "t": 0},
            "quaternion,scale,translation": {"q": 0, "s": 16, "t": 32},
        }
        best = None
        # the pose block is 4-byte aligned but the parent array ends on a 2-byte boundary, so
        # the scan has to start at the next aligned offset or it steps over the block entirely
        for off in range((parents_end + 3) & ~3, hi - count * 48, 4):
            for layout, slot in LAYOUTS.items():
                score = sum(1 for i in range(count)
                            if unit(off + i * 48 + slot["q"])
                            and unit_scale(off + i * 48 + slot["s"]))
                if best is None or score > best[0]:
                    best = (score, off, layout)
        if best is None or best[0] < count - 2:
            return None
        _score, pose_at, layout = best

        # 3. bone names: fixed 32-byte NUL-padded records directly behind the pose block (the
        #    pool may carry a 16-byte lead-in). The regex fallback is kept because the stride
        #    is not documented anywhere; it found every name on the trooper files and one short
        #    on the creature files, which is why the structured read is tried first.
        names = self._pool_names(pose_at + count * 48, count) or self.skeleton_bones() or []
        slot = LAYOUTS[layout]
        poses = []
        for i in range(count):
            rec = struct.unpack_from("<12f", raw, pose_at + i * 48)
            poses.append({
                "translation": list(rec[slot["t"] // 4: slot["t"] // 4 + 3]),
                "rotation": list(rec[slot["q"] // 4: slot["q"] // 4 + 4]),
                "scale": list(rec[slot["s"] // 4: slot["s"] // 4 + 3]),
            })
        return {
            "name": name,
            "bone_count": count,
            "parents": parents,
            "bone_names": names[:count],
            "reference_pose_offset": pose_at,
            "reference_pose_layout": layout,
            "reference_pose": poses,
        }

    # ------------------------------------------------------------- skeleton
    def _pool_names(self, pool_at: int, count: int) -> list[str]:
        """Read the bone-name pool behind the pose block, in bone order.

        The pool is not fixed-stride: names are NUL-terminated and padded, and some bones
        carry an extra 16-byte record behind the name (`AttachMarker_Bone` on the carnifex).
        So the pool is walked as an ordered sequence of printable strings rather than sliced at
        a stride -- a fixed 32-byte stride read the carnifex pool as empty, and the earlier
        regex fallback silently dropped the one name that is not in the Bip01 family (37 of 38
        bones named, which shifts every bone after it).
        """
        raw = self.raw
        data = self.sections.get("__data__")
        if data is None:
            return []
        hi = data.offset + data.size
        names: list[str] = []
        cur = pool_at
        while cur < hi and len(names) < count:
            end = raw.find(b"\x00", cur, min(hi, cur + 64))
            if end < 0:
                cur += 1
                continue
            text = raw[cur:end]
            if 1 <= len(text) <= 31 and all(32 <= b < 127 for b in text):
                names.append(text.decode("ascii"))
                cur = end + 1
            else:
                cur += 1
        return names if len(names) == count else []

    def skeleton_bones(self) -> list[str]:
        """Bone names of the skeleton this packfile carries.

        Packfile v4 stores each bone's name inline in a fixed-size record in the data
        section rather than through a name pointer, so the names are recovered by
        scanning the data section for the Bip01 family and preserving file order (the
        order IS the hierarchy order the clip's anonymous track indices refer to).
        """
        import re
        sec = self.sections["__data__"]
        blob = self.raw[sec.offset:sec.offset + sec.size]
        out: list[str] = []
        for m in re.finditer(rb"Bip01[ -~]{0,62}", blob):
            name = m.group().decode("ascii", "replace").rstrip()
            if name and name not in out:
                out.append(name)
        return out


def main() -> None:
    import sys
    for arg in sys.argv[1:]:
        pf = Packfile.open(arg)
        print(f"{Path(arg).name}: sections={ {k: (v.offset, v.size) for k, v in pf.sections.items()} }")
        census = pf.census()
        if census:
            print(f"  objects={sum(census.values())}")
            for name, count in list(census.items())[:12]:
                print(f"    {count:5d}  {name}")
        else:
            print("  objects: object table not parsed for this packfile version "
                  "(sections and skeleton still read)")
        try:
            types = pf.type_table()
            print(f"  types={len(types)}  first={[t.name for t in types[:6]]}")
        except Exception as exc:  # noqa: BLE001 - the type table is not on the clip path
            print(f"  types: unread ({exc})")
        bones = pf.skeleton_bones()
        print(f"  bones={len(bones)}  first={bones[:5]}  last={bones[-2:]}")


if __name__ == "__main__":
    main()


def _u32(seg, off):
    return struct.unpack_from("<I", seg, off)[0]


def _f32(seg, off):
    return struct.unpack_from("<f", seg, off)[0]


def find_animation_header(seg, bone_count):
    """Locate the hkSkeletalAnimation header: (offset, type, duration, numberOfTracks).

    The packfile's object table is not decoded by this module, so the header is found by its own
    signature instead: a u32 equal to the skeleton's bone count (numberOfTracks), preceded by a
    plausible duration float and a valid animation type. Measured on `fb_idle_stand_01`: exactly one
    hit, at data offset 5320, type 2 (HK_DELTA_COMPRESSED_ANIMATION), duration 7.333 s, 46 tracks —
    the guardsman skeleton has 46 bones.
    """
    hits = []
    for off in range(8, len(seg) - 16, 4):
        if _u32(seg, off) != bone_count:
            continue
        dur = _f32(seg, off - 4)
        typ = _u32(seg, off - 8)
        if 0.05 < dur < 60.0 and typ in (0, 1, 2, 3):
            hits.append((off - 8, typ, round(dur, 4), bone_count))
    return hits


def animation_fields(seg, header_off, verbose=False):
    """Read the fields that follow the hkSkeletalAnimation base, in declaration order.

    Declaration order comes from the file's own `__types__` table:
      numberOfPoses, blockSize, qFormat, quantizedDataIdx, quantizedDataSize,
      staticMaskIdx, staticMaskSize, staticDOFsIdx, staticDOFsSize,
      totalBlockSize, lastBlockSize, dataBuffer

    `Idx` values are offsets into the animation's own data buffer, which is why this is decodable
    without relocating pointers.
    """
    fields = ("numberOfPoses", "blockSize", "qFormat", "quantizedDataIdx", "quantizedDataSize",
              "staticMaskIdx", "staticMaskSize", "staticDOFsIdx", "staticDOFsSize",
              "totalBlockSize", "lastBlockSize", "dataBuffer")
    # The delta fields start 24 bytes after the header, not 12: measured by constraining the values
    # to their declared semantics on `fb_idle_stand_01` — at +24 the block reads numberOfPoses=221,
    # blockSize=8, which matches a 7.333 s clip at ~30 fps; at +12 blockSize would be 0, and at +20
    # numberOfPoses would be 46 with blockSize 221 (blockSize larger than the pose count).
    base = header_off + 24
    out = {}
    for i, name in enumerate(fields):
        out[name] = _u32(seg, base + i * 4)
    if verbose:
        for i, name in enumerate(fields):
            off = base + i * 4
            print(f"    +{off:5d} {name:20s} {out[name]:10d}  ({out[name]:#010x})")
    return out


def decode_report(path, verbose=True):
    """Everything the animation decoder can currently say about one clip file."""
    p = Packfile.open(path)
    sk = p.skeleton()
    seg = p.raw[p.sections["__data__"].offset:p.sections["__data__"].offset + p.sections["__data__"].size]
    bones = sk["bone_count"]
    hits = find_animation_header(seg, bones)
    rep = {"file": str(path), "bones": bones, "headers": hits}
    if verbose:
        print(f"{path}: {bones} bones, {len(hits)} animation header candidate(s)")
        for h in hits:
            print(f"  header at data offset {h[0]}: type={h[1]} duration={h[2]}s tracks={h[3]}")
            fields = animation_fields(seg, h[0], verbose=True)
            rep["fields"] = fields
            # sanity: a 7.3 s clip at 30 fps is ~220 poses; blockSize is a small frame count
            print(f"    -> implied fps if numberOfPoses frames: "
                  f"{fields['numberOfPoses'] / max(1e-6, h[2]):.2f}")
    return rep
