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
        """Class name -> object count, read from the object stream."""
        counts: dict[str, int] = {}
        try:
            for name, _offset in self.objects():
                counts[name] = counts.get(name, 0) + 1
        except HkxError:
            return {}
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
        """Decode the skeleton this packfile carries.

        Verified layout for packfile v4 (Havok 4.5.1), measured on
        fb_crouch_idle_01.hkx: a u32 bone count, then the skeleton name, then the
        parentIndices array as int16 (one -1 root, every parent index < its child index),
        then the referencePose as 70 records of 48 bytes (rotation quaternion, scale,
        translation), then the bone-name string pool. The offsets are found by structure
        rather than assumed, because the object table layout differs from later packfile
        versions and guessing it is what stalled the first attempt.
        """
        import math
        raw = self.raw
        data = self.sections.get("__data__")
        if data is None:
            return None
        lo, hi = data.offset, data.offset + data.size

        # bone count + skeleton name: a u32 count followed by a printable NUL-padded name
        count = name = None
        for off in range(lo, hi - 32, 4):
            n = struct.unpack_from("<I", raw, off)[0]
            if not (4 <= n <= 512):
                continue
            field = raw[off + 0x10:off + 0x20]
            if len(field) < 16:
                continue
            text = field.split(b"\x00")[0]
            if not (2 <= len(text) <= 15) or not all(32 <= b < 127 for b in text):
                continue
            # parents must follow: int16 array with exactly one -1 and every parent < index
            pstart = off + 0x20
            try:
                parents = list(struct.unpack_from(f"<{n}h", raw, pstart))
            except struct.error:
                continue
            if sum(1 for p in parents if p == -1) != 1:
                continue
            if not all(p < i for i, p in enumerate(parents) if p >= 0):
                continue
            count, name, parents_at = n, text.decode("ascii"), pstart
            break
        if count is None:
            return None

        # reference pose: `count` consecutive 48-byte records whose first four floats are a
        # unit quaternion. Scanning for the structure beats assuming the offset.
        def unit(off: int) -> bool:
            q = struct.unpack_from("<4f", raw, off)
            return 0.9 < math.sqrt(sum(v * v for v in q)) < 1.1

        # A candidate only counts if the bytes immediately after the pose open a printable
        # string: the bone-name pool sits directly behind the reference pose, and that is what
        # rejects the false candidates the quaternion test alone accepts (measured: an earlier
        # run locked onto a zeroed run and reported every pose as 0,0,0).
        def opens_string(off: int) -> bool:
            chunk = raw[off:off + 8]
            return len(chunk) >= 4 and all(32 <= b < 127 for b in chunk[:4])

        pose_at = None
        for off in range(parents_at + count * 2, hi - count * 48, 4):
            if sum(1 for i in range(count) if unit(off + i * 48)) < count - 2:
                continue
            if opens_string(off + count * 48):
                pose_at = off
                break
        if pose_at is None:
            return None

        # bone names: the string pool after the pose
        pool_at = pose_at + count * 48
        names = []
        cursor = pool_at
        while cursor < hi and len(names) < count:
            end = raw.find(b"\x00", cursor)
            if end < 0:
                break
            text = raw[cursor:end].decode("ascii", "replace")
            if 1 <= len(text) <= 31 and all(32 <= ord(c) < 127 for c in text):
                names.append(text)
                cursor = end + 1 + ((32 - ((end + 1 - cursor) % 32)) % 32 if False else 0)
                cursor = end + 1
            else:
                cursor += 1
        return {
            "name": name,
            "bone_count": count,
            "parents": parents,
            "bone_names": self.skeleton_bones() or names[:count],
            "reference_pose_offset": pose_at,
            "reference_pose": [
                struct.unpack_from("<12f", raw, pose_at + i * 48) for i in range(count)
            ],
        }

    # ------------------------------------------------------------- skeleton
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
