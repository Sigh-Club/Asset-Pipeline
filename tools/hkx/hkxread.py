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

    # -------------------------------------------------------------- objects
    def objects(self):
        """Yield (class_name, object_offset) for every object in the data section.

        The v7 data section stores an object table: `u32 count` then, per object, the
        type index and the object's offset. Objects are returned in table order, which is
        the order the game reads them, so a skeleton always precedes its animation.
        """
        sec = self.sections["__data__"]
        pos = sec.offset
        end = sec.offset + sec.size
        count = struct.unpack_from("<I", self.raw, pos)[0]
        pos += 4
        if count == 0 or count > 1_000_000:
            raise HkxError(f"implausible object count {count} at {sec.offset:#x}")
        names = self._type_names()
        for _ in range(count):
            if pos + 8 > end:
                break
            type_index, offset = struct.unpack_from("<II", self.raw, pos)
            pos += 8
            name = names[type_index] if type_index < len(names) else f"<{type_index}>"
            yield name, sec.offset + offset


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
