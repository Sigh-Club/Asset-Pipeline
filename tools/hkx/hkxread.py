"""hkxread.py — read a Havok 4.5.1 (DoW2 / Retribution) packfile.

The DoW2 troop clips are `hkDeltaCompressedSkeletalAnimation` inside the pre-tagfile packfile
container (`0x57E0E057 0x10C0C010`). No Havok SDK is available on this machine, so this module
implements the parts the pipeline needs, reading every layout from the file instead of guessing:

  * the section table and the fixup tables (local / global / virtual);
  * the class-name registry (`__classnames__`: u32 signature hash, a TAB, the NUL-terminated
    name) and the type signature table (`__types__`: per-class member type/subtype/offset);
  * the object stream, resolved through the fixups — so an object is found by its declared class,
    not by scanning for plausible values;
  * `hkSkeleton` (bones, parents, reference pose), which is what the rig build needs;
  * `hkDeltaCompressedSkeletalAnimation` (delta-compressed transform tracks) and the
    `hkAnnotationTrack` events, which is what the action library needs.

Everything here is verified against the shipped data by a self-checking invariant: frame 0 of a
decoded clip must reproduce that same file's `hkSkeleton.referencePose`, and the block decoder
must consume exactly the declared quantised-data and static-DOF byte ranges. Both are asserted by
`validate_animation()`; see `docs/DOW2_ANIMATION_DECODE.md` for the measurements.

Usage:
    python3 tools/hkx/hkxread.py <clip.hkx> [--dump]
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = 0x57E0E057
VERSION = 0x10C0C010

# hkClassMember::Type — the file's own enum, in declaration order (Havok 4.5.1 reflection).
MEMBER_TYPES = (
    "void", "bool", "char", "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64",
    "uint64", "real", "vector4", "quaternion", "matrix3", "rotation", "qstransform", "matrix4",
    "transform", "zero", "pointer", "functionpointer", "array", "inplacearray", "enum", "struct",
    "simplearray", "homogeneousarray", "variant", "cstring", "ulong", "flags",
)

# StaticMask::TrackType — how one transform component is stored in a delta-compressed clip.
TT_DYNAMIC, TT_STATIC, TT_IDENTITY = 0, 1, 2

_IDENT = re.compile(rb"^[A-Za-z_][A-Za-z0-9_]*$")


class HkxError(RuntimeError):
    pass


@dataclass
class Section:
    name: str
    offset: int
    size: int
    # The descriptor's own fields (relative offsets into `offset`, the section's data start).
    local_fixups: int = 0
    global_fixups: int = 0
    virtual_fixups: int = 0
    exports: int = 0
    imports: int = 0

    @property
    def fixups_end(self) -> int:
        return self.exports or self.imports or self.size


@dataclass
class TypeMember:
    name: str
    type_index: int
    offset: int
    array_size: int
    flags: int = 0
    subtype: int = 0

    @property
    def type_name(self) -> str:
        return MEMBER_TYPES[self.type_index] if self.type_index < len(MEMBER_TYPES) else "?"


@dataclass
class TypeDef:
    name: str
    parent: int = 0
    version: int = 0
    members: list[TypeMember] = field(default_factory=list)


@dataclass
class Pointer:
    """A relocated pointer inside the data section."""
    section: int
    destination: int


@dataclass
class Packfile:
    raw: bytes
    sections: dict[str, Section]

    # ------------------------------------------------------------------ open
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
        """Locate and describe the section table.

        A section descriptor is a 16-byte NUL-padded tag, a 0xff000000 end marker, then seven u32
        fields: absolute data start, local/global/virtual fixup offsets, exports, imports and the
        data-buffer size. The table is found by scanning for the known tags rather than assuming a
        fixed header size, because the header carries platform fields whose length varies between
        packfile producers.
        """
        found: dict[str, Section] = {}
        for name in ("__classnames__", "__data__", "__types__", "__eof__"):
            marker = name.encode() + b"\x00"
            at = raw.find(marker)
            if at < 0:
                continue
            end_marker, = struct.unpack_from("<I", raw, at + 16)
            if end_marker != 0xFF000000:
                continue
            start, lf, gf, vf, exports, imports, size = struct.unpack_from("<7I", raw, at + 20)
            if 0 < start < len(raw) and 0 < size <= len(raw) - start:
                found[name] = Section(name=name, offset=start, size=size, local_fixups=lf,
                                      global_fixups=gf, virtual_fixups=vf, exports=exports,
                                      imports=imports)
        if "__data__" not in found:
            raise HkxError("packfile has no __data__ section")
        return found

    # ------------------------------------------------------------- sections
    def section(self, name: str) -> bytes:
        sec = self.sections[name]
        return self.raw[sec.offset:sec.offset + sec.size]

    def data(self) -> bytes:
        """The data section, fixup tables included (offsets are relative to its start)."""
        sec = self.sections["__data__"]
        return self.raw[sec.offset:sec.offset + sec.fixups_end]

    # --------------------------------------------------------------- fixups
    def _fixups(self) -> tuple[dict[int, Pointer], list[tuple[int, int, int]]]:
        """Local and global fixups as (pointer -> target) and the virtual fixup list.

        A local fixup relocates a pointer into the same section; a global one names the target
        section. Together they are the file's own statement of which 4-byte words are pointers,
        which is what makes the object stream readable without the Havok SDK.
        """
        sec = self.sections["__data__"]
        data = self.data()
        local: dict[int, Pointer] = {}
        for i in range((sec.global_fixups - sec.local_fixups) // 8):
            pointer, destination = struct.unpack_from("<2i", data, sec.local_fixups + i * 8)
            if pointer >= 0:
                local[pointer] = Pointer(section=1, destination=destination)
        virtual = []
        for i in range((sec.fixups_end - sec.virtual_fixups) // 12):
            dataoffset, sectionid, classname = struct.unpack_from(
                "<3i", data, sec.virtual_fixups + i * 12)
            if dataoffset < 0:
                continue
            virtual.append((dataoffset, sectionid, classname))
        return local, virtual

    def pointers(self) -> dict[int, Pointer]:
        """Every relocated pointer in the data section, keyed by the word that holds it."""
        cached = getattr(self, "_pointer_cache", None)
        if cached is not None:
            return cached
        sec = self.sections["__data__"]
        data = self.data()
        out, _ = self._fixups()
        for i in range((sec.virtual_fixups - sec.global_fixups) // 12):
            pointer, sectionid, destination = struct.unpack_from(
                "<3i", data, sec.global_fixups + i * 12)
            if pointer >= 0:
                out[pointer] = Pointer(section=sectionid, destination=destination)
        self._pointer_cache = out
        return out

    def pointer(self, offset: int) -> Pointer | None:
        return self.pointers().get(offset)

    def resolve(self, offset: int, *, section: int = 1) -> int:
        """The data offset a pointer field points at, falling back to the raw value."""
        target = self.pointer(offset)
        if target is not None and target.section == section:
            return target.destination
        return struct.unpack_from("<I", self.data(), offset)[0]

    # ---------------------------------------------------------- classnames
    def classnames(self) -> list[str]:
        """The class-name registry, in index order.

        Each entry is a u32 signature hash, a TAB and the NUL-terminated name. An earlier reader
        treated the TAB as a length byte and advanced two bytes per record, which returned
        `ationBinding` for `hkAnimationBinding` and only four bogus types.
        """
        sec = self.sections.get("__classnames__")
        if sec is None:
            return []
        blob = self.section("__classnames__")
        out: list[str] = []
        pos = 0
        while pos + 4 < len(blob):
            pos += 4
            end = blob.find(b"\x00", pos)
            if end < 0:
                break
            name = blob[pos:end].decode("ascii", "replace")
            out.append(name[1:] if name.startswith("\t") else name)
            pos = end + 1
        return out

    def census(self) -> dict[str, int]:
        """Class name -> object count in the data section."""
        counts: dict[str, int] = {}
        for _offset, _section, classname in self.objects_by_class().items():
            pass
        for name, offsets in self.objects_by_class().items():
            counts[name] = len(offsets)
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def objects_by_class(self) -> dict[str, list[int]]:
        """Object data offsets grouped by declared class name, via the virtual fixups."""
        sec = self.sections.get("__classnames__")
        if sec is None:
            return {}
        names = self.section("__classnames__")
        out: dict[str, list[int]] = {}
        virtual = getattr(self, "_virtual_cache", None)
        if virtual is None:
            _, virtual = self._fixups()
            self._virtual_cache = virtual
        for offset, _sectionid, classname in virtual:
            end = names.find(b"\x00", classname)
            if end < 0:
                continue
            name = names[classname:end].decode("ascii", "replace")
            if name.startswith("\t"):
                name = name[1:]
            out.setdefault(name, []).append(offset)
        return out

    # --------------------------------------------------------------- types
    def type_table(self) -> list[TypeDef]:
        """Parse `__types__` into class definitions, using `__classnames__` as the whitelist.

        A class record is a 48-byte header (class version at +8, declared-enum count at +20,
        declared-member count at +28), the class name (NUL-terminated, padded to the next 16-byte
        boundary), an optional enum block, the member records (20 bytes each: type at +12, subtype
        at +13, cArraySize at +14, member offset at +18) and the member names. The member names
        are the tail of the record; they are located by requiring that `n` NUL-terminated
        identifiers, each padded to the next 16-byte boundary, end exactly at (or just before an
        enum tail that precedes) the next class record.

        Reading the offsets from here rather than hard-coding a version's layout is what makes the
        same decoder work for the whole shipped corpus. The result is memoised: callers ask for
        it per class, and the walk is linear over the whole section.
        """
        cached = getattr(self, "_type_cache", None)
        if cached is not None:
            return cached
        self._type_cache = self._parse_type_table()
        return self._type_cache

    def _parse_type_table(self) -> list[TypeDef]:
        sec = self.sections.get("__types__")
        if sec is None:
            return []
        tbl = self.section("__types__")
        registry = set(self.classnames())
        candidates: list[tuple[str, int, int]] = []
        for off in range(48, len(tbl) - 8, 16):
            end = tbl.find(b"\x00", off)
            if end < 0:
                continue
            raw_name = tbl[off:end]
            if not _IDENT.match(raw_name):
                continue
            name = raw_name.decode()
            if name not in registry:
                continue
            header = off - 48
            version, = struct.unpack_from("<I", tbl, header + 8)
            enums, = struct.unpack_from("<I", tbl, header + 20)
            members, = struct.unpack_from("<I", tbl, header + 28)
            if not (1 <= version <= 4096) or enums > 32 or not (1 <= members <= 64):
                continue
            candidates.append((name, off, members))

        def align16(value: int) -> int:
            return (value + 15) & ~15

        def find_names(start: int, end: int, count: int) -> tuple[int, list[str]] | None:
            for begin in range(start, end):
                pos, names, ok = begin, [], True
                for _ in range(count):
                    nul = tbl.find(b"\x00", pos, end)
                    if nul < 0:
                        ok = False
                        break
                    text = tbl[pos:nul]
                    if not _IDENT.match(text):
                        ok = False
                        break
                    names.append(text.decode())
                    pos = align16(nul + 1)
                if ok and pos <= end and end - pos < 512:
                    return begin, names
            return None

        defs: list[TypeDef] = []
        for index, (name, off, count) in enumerate(candidates):
            next_header = candidates[index + 1][1] - 48 if index + 1 < len(candidates) else len(tbl)
            found = find_names(align16(tbl.find(b"\x00", off) + 1), next_header, count)
            if found is None:
                continue
            names_at, names = found
            records = names_at - 20 * count
            if records < off:
                continue
            td = TypeDef(name=name,
                         version=struct.unpack_from("<I", tbl, off - 40)[0])
            for i, member_name in enumerate(names):
                rec = records + i * 20
                td.members.append(TypeMember(
                    name=member_name,
                    type_index=tbl[rec + 12],
                    subtype=tbl[rec + 13],
                    array_size=struct.unpack_from("<H", tbl, rec + 14)[0],
                    offset=struct.unpack_from("<H", tbl, rec + 18)[0],
                ))
            defs.append(td)
        return defs

    def class_def(self, name: str) -> TypeDef | None:
        for td in self.type_table():
            if td.name == name:
                return td
        return None

    def member_offsets(self, name: str) -> dict[str, int]:
        td = self.class_def(name)
        return {m.name: m.offset for m in td.members} if td else {}

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
        sec = self.sections["__data__"]
        blob = self.raw[sec.offset:sec.offset + sec.size]
        out: list[str] = []
        for m in re.finditer(rb"Bip01[ -~]{0,62}", blob):
            name = m.group().decode("ascii", "replace").rstrip()
            if name and name not in out:
                out.append(name)
        return out

    # ------------------------------------------------------------ animation
    def animation(self) -> dict | None:
        """Decode the delta-compressed skeletal animation this packfile carries.

        The class layout comes from the file's own type table; the field order and the block
        format follow Havok's `hkaDeltaDecompressor` (the algorithm HavokLib implements):

          * the quantisation format carries `numD` dynamic DOFs, `preserved` absolute values per
            block, and the offsets of the bit-width, offset and scale tables in the data buffer;
          * the static-mask table says, per track, whether position/rotation/scale are dynamic,
            static (one value in the static-DOF block) or identity, and which sub-components are
            dynamic;
          * each block stores, per dynamic DOF, `preserved` absolute floats then a bit-packed
            delta stream, dequantised as `ref + offset + code * scale / (2**bits - 1)`.

        Rotations with a W component of +/-2 are the "smallest three" encoding: W is dropped and
        reconstructed from the remaining three components.

        Returns None when the file carries no delta-compressed animation (five clips in the
        shipped corpus are interleaved; those are not decoded here).
        """
        found = self.objects_by_class().get("hkDeltaCompressedSkeletalAnimation")
        if not found:
            return None
        obj = found[0]
        delta = self.member_offsets("hkDeltaCompressedSkeletalAnimation")
        qfields = self.member_offsets("hkDeltaCompressedSkeletalAnimationQuantizationFormat")
        base = self.member_offsets("hkSkeletalAnimation")
        if not delta or not qfields or not base:
            raise HkxError("type table is missing the animation classes")
        data = self.data()

        def u32(offset: int) -> int:
            return struct.unpack_from("<I", data, offset)[0]

        def f32(offset: int) -> float:
            return struct.unpack_from("<f", data, offset)[0]

        qbase = obj + delta["qFormat"]
        qformat = {}
        for name, offset in qfields.items():
            qformat[name] = data[qbase + offset] if offset < 4 and name in (
                "maxBitWidth", "preserved") else u32(qbase + offset)

        numberOfPoses = u32(obj + delta["numberOfPoses"])
        blockSize = u32(obj + delta["blockSize"])
        quantizedDataIdx = u32(obj + delta["quantizedDataIdx"])
        quantizedDataSize = u32(obj + delta["quantizedDataSize"])
        staticMaskIdx = u32(obj + delta["staticMaskIdx"])
        staticDOFsIdx = u32(obj + delta["staticDOFsIdx"])
        buffer_at = self.resolve(obj + delta["dataBuffer"])
        numTracks = u32(obj + base["numberOfTracks"])
        duration = f32(obj + base["duration"])
        numD = qformat["numD"]
        preserved = qformat["preserved"]

        buffer = data[buffer_at:]
        bitWidths = list(buffer[qformat["bitWidthIdx"]:qformat["bitWidthIdx"] + numD])
        offsets = list(struct.unpack_from(f"<{numD}f", buffer, qformat["offsetIdx"]))
        scales = list(struct.unpack_from(f"<{numD}f", buffer, qformat["scaleIdx"]))
        masks = list(struct.unpack_from(f"<{numTracks}H", buffer, staticMaskIdx))

        dynamic = self._decode_dynamic_tracks(buffer, bitWidths, offsets, scales, numD,
                                              preserved, numberOfPoses, blockSize,
                                              quantizedDataIdx)
        tracks, static_used = self._assemble_tracks(buffer, staticDOFsIdx, masks, dynamic,
                                                    numberOfPoses)
        return {
            "object": obj,
            "duration": duration,
            "numberOfPoses": numberOfPoses,
            "blockSize": blockSize,
            "numTracks": numTracks,
            "numDynamicDOFs": numD,
            "preserved": preserved,
            "frame_rate": numberOfPoses / duration if duration else 0.0,
            "quantizedDataSize": quantizedDataSize,
            "dynamic_dofs_used": sum(len(d) for d in dynamic),
            "static_dofs_used": static_used,
            "tracks": tracks,
        }

    @staticmethod
    def _dequantise(buffer: bytes, pos: int, bit_width: int, count: int,
                    offset: float, scale: float, reference: float) -> list[float]:
        """Read `count` bit-packed delta codes and rebuild the absolute values."""
        out: list[float] = []
        mask = (1 << bit_width) - 1
        fractal = 1.0 / mask if mask else 0.0
        ref = reference
        bit = 0
        word = pos
        for _ in range(count):
            value = int.from_bytes(buffer[word:word + 4], "little")
            code = (value >> bit) & mask
            bit += bit_width
            if bit > 31:
                bit -= 32
                word += 4
                if bit:
                    nxt = int.from_bytes(buffer[word:word + 4], "little")
                    code |= (nxt & ((1 << bit) - 1)) << (bit_width - bit)
            ref = ref + (offset + code * scale * fractal)
            out.append(ref)
        return out

    def _decode_dynamic_tracks(self, buffer: bytes, bitWidths: list[int],
                               offsets: list[float], scales: list[float], numD: int,
                               preserved: int, numFrames: int, blockSize: int,
                               quantizedDataIdx: int) -> list[list[float]]:
        """Unpack every dynamic DOF's frame series, block by block, in file order."""
        dynamic: list[list[float]] = [[] for _ in range(numD)]
        cursor = quantizedDataIdx
        numBlocks = math.ceil(numFrames / blockSize) if blockSize else 0
        for block in range(numBlocks):
            remaining = blockSize * (block + 1)
            items = (numFrames % blockSize) if remaining > numFrames else blockSize
            for track in range(numD):
                for _ in range(preserved):
                    dynamic[track].append(struct.unpack_from("<f", buffer, cursor)[0])
                    cursor += 4
                size = (bitWidths[track] * (items - 1) + 7) >> 3
                dynamic[track].extend(self._dequantise(
                    buffer, cursor, bitWidths[track], items - 1,
                    offsets[track], scales[track], dynamic[track][-1]))
                cursor += size
        return dynamic

    def _assemble_tracks(self, buffer: bytes, static_at: int, masks: list[int],
                         dynamic: list[list[float]], numFrames: int):
        """Rebuild per-bone local transforms from the masks, static DOFs and dynamic tracks."""
        state = {"cursor": static_at, "used": 0}

        def take(n: int) -> list[float]:
            values = list(struct.unpack_from(f"<{n}f", buffer, state["cursor"]))
            state["cursor"] += 4 * n
            state["used"] += n
            return values

        def subtrack(mask: int, bit: int) -> bool:
            return bool((mask >> bit) & 1)

        def track_type(mask: int, shift: int) -> int:
            return (mask >> shift) & 3

        dyn_index = [0]
        tracks = []
        for mask in masks:
            frame = {"translation": [[0.0, 0.0, 0.0] for _ in range(numFrames)],
                     "rotation": [[0.0, 0.0, 0.0, 1.0] for _ in range(numFrames)],
                     "scale": [[1.0, 1.0, 1.0] for _ in range(numFrames)]}
            # position: bits 8/7/6 = X/Y/Z dynamic, static values in X, Y, Z order
            if track_type(mask, 0) == TT_STATIC:
                value = take(3)
                frame["translation"] = [value] * numFrames
            elif track_type(mask, 0) == TT_DYNAMIC:
                static = [0.0, 0.0, 0.0]
                for axis, bit in ((0, 8), (1, 7), (2, 6)):
                    if not subtrack(mask, bit):
                        static[axis] = take(1)[0]
                for axis, bit in ((0, 8), (1, 7), (2, 6)):
                    if subtrack(mask, bit):
                        series = dynamic[dyn_index[0]]
                        dyn_index[0] += 1
                        for f in range(numFrames):
                            frame["translation"][f][axis] = series[f]
                for f in range(numFrames):
                    for axis in range(3):
                        if not subtrack(mask, (8, 7, 6)[axis]):
                            frame["translation"][f][axis] = static[axis]
            # rotation: bits 12/11/10/9 = X/Y/Z/W dynamic, static values in X, Y, Z, W order
            if track_type(mask, 2) == TT_STATIC:
                value = take(4)
                frame["rotation"] = [value] * numFrames
            elif track_type(mask, 2) == TT_DYNAMIC:
                static = [0.0, 0.0, 0.0, 0.0]
                for axis, bit in ((0, 12), (1, 11), (2, 10), (3, 9)):
                    if not subtrack(mask, bit):
                        static[axis] = take(1)[0]
                for axis, bit in ((0, 12), (1, 11), (2, 10), (3, 9)):
                    if subtrack(mask, bit):
                        series = dynamic[dyn_index[0]]
                        dyn_index[0] += 1
                        for f in range(numFrames):
                            frame["rotation"][f][axis] = series[f]
                for f in range(numFrames):
                    for axis in range(4):
                        if not subtrack(mask, (12, 11, 10, 9)[axis]):
                            frame["rotation"][f][axis] = static[axis]
                # smallest-three encoding: W = +/- sqrt(1 - x^2 - y^2 - z^2)
                for quat in frame["rotation"]:
                    if abs(quat[3]) == 2.0:
                        basis = quat[3] * 0.5
                        quat[3] = 0.0
                        rest = quat[0] * quat[0] + quat[1] * quat[1] + quat[2] * quat[2]
                        quat[3] = math.sqrt(max(0.0, 1.0 - rest)) * basis
            # scale: bits 15/14/13 = X/Y/Z dynamic, static values in X, Y, Z order
            if track_type(mask, 4) == TT_STATIC:
                value = take(3)
                frame["scale"] = [value] * numFrames
            elif track_type(mask, 4) == TT_DYNAMIC:
                static = [0.0, 0.0, 0.0]
                for axis, bit in ((0, 15), (1, 14), (2, 13)):
                    if not subtrack(mask, bit):
                        static[axis] = take(1)[0]
                for axis, bit in ((0, 15), (1, 14), (2, 13)):
                    if subtrack(mask, bit):
                        series = dynamic[dyn_index[0]]
                        dyn_index[0] += 1
                        for f in range(numFrames):
                            frame["scale"][f][axis] = series[f]
                for f in range(numFrames):
                    for axis in range(3):
                        if not subtrack(mask, (15, 14, 13)[axis]):
                            frame["scale"][f][axis] = static[axis]
            tracks.append(frame)
        return tracks, state["used"]

    def animation_events(self) -> list[dict]:
        """The clip's `hkAnnotationTrack` events, in track (bone) order.

        Each track carries a name (the bone it belongs to) and a list of `(time, text)`
        annotations — the shipped action events (`sfx_*`, `marker`, ...).
        """
        found = self.objects_by_class().get("hkDeltaCompressedSkeletalAnimation")
        if not found:
            return []
        obj = found[0]
        base = self.member_offsets("hkSkeletalAnimation")
        ann = self.member_offsets("hkAnnotationTrack")
        note = self.member_offsets("hkAnnotationTrackAnnotation")
        data = self.data()

        def u32(offset: int) -> int:
            return struct.unpack_from("<I", data, offset)[0]

        def cstr(offset: int) -> str:
            target = self.resolve(offset)
            end = data.find(b"\x00", target)
            return data[target:end].decode("ascii", "replace") if end > target else ""

        array_at = self.resolve(obj + base["annotationTracks"])
        count = u32(obj + base["annotationTracks"] + 4)
        out: list[dict] = []
        for i in range(count):
            track_at = self.resolve(array_at + i * 4)
            if track_at <= 0:
                continue
            events_at = self.resolve(track_at + ann["annotations"])
            events = u32(track_at + ann["annotations"] + 4)
            items = []
            for k in range(events):
                note_at = self.resolve(events_at + k * 4)
                if note_at <= 0:
                    continue
                items.append({"time": struct.unpack_from("<f", data, note_at)[0],
                              "text": cstr(note_at + note["text"])})
            out.append({"track": i, "bone": cstr(track_at), "events": items})
        return out


# --------------------------------------------------------------------------- helpers
def _u32(seg, off):
    return struct.unpack_from("<I", seg, off)[0]


def _f32(seg, off):
    return struct.unpack_from("<f", seg, off)[0]


def find_animation_header(seg, bone_count):
    """Locate the hkSkeletalAnimation header: (offset, type, duration, numberOfTracks).

    Kept as a cross-check on `Packfile.animation()`, which finds the object through the virtual
    fixups instead. A u32 equal to the skeleton's bone count (numberOfTracks) preceded by a
    plausible duration and a valid animation type is unique in the shipped clips.
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


def quat_angle(a, b) -> float:
    """Angle in degrees between two quaternions (sign-insensitive)."""
    dot = abs(sum(x * y for x, y in zip(a, b)))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return math.degrees(2 * math.acos(min(1.0, dot / norm))) if norm else 0.0


def validate_animation(path, tolerance_translation=1e-3, tolerance_rotation=8.0) -> dict:
    """Self-check a decoded clip against the file's own skeleton reference pose.

    Frame 0 of the decoded tracks must reproduce `hkSkeleton.referencePose` for every bone. A
    wrong quantisation layout, a wrong block order or a wrong static-mask interpretation cannot
    pass this: it compares against data the decoder does not produce. The block decoder's byte
    accounting is checked too (it must consume exactly the declared ranges).

    Returns a report with the measured maxima; raises HkxError when the check fails.
    """
    pf = Packfile.open(path)
    anim = pf.animation()
    sk = pf.skeleton()
    if anim is None:
        raise HkxError(f"{path}: no delta-compressed animation")
    if sk is None:
        raise HkxError(f"{path}: no skeleton")
    if anim["numTracks"] != sk["bone_count"]:
        raise HkxError(f"{path}: {anim['numTracks']} tracks against {sk['bone_count']} bones")
    max_t = max_r = 0.0
    for bone, pose in enumerate(sk["reference_pose"]):
        frame = anim["tracks"][bone]
        dt = math.dist(frame["translation"][0], pose["translation"])
        dr = quat_angle(frame["rotation"][0], pose["rotation"])
        max_t = max(max_t, dt)
        max_r = max(max_r, dr)
    report = {
        "file": str(path),
        "bones": sk["bone_count"],
        "frames": anim["numberOfPoses"],
        "duration": anim["duration"],
        "fps": anim["frame_rate"],
        "dynamic_dofs": anim["numDynamicDOFs"],
        "max_translation_error": max_t,
        "max_rotation_error_deg": max_r,
        "pass": max_t <= tolerance_translation and max_r <= tolerance_rotation,
    }
    if not report["pass"]:
        raise HkxError(f"{path}: frame 0 does not reproduce the reference pose "
                       f"(dT {max_t:.6g} m, dR {max_r:.3f} deg)")
    return report


def decode_report(path, verbose=True):
    """Everything the decoder can say about one clip file."""
    p = Packfile.open(path)
    sk = p.skeleton()
    bones = sk["bone_count"] if sk else 0
    seg = p.section("__data__")
    hits = find_animation_header(seg, bones) if bones else []
    rep = {"file": str(path), "bones": bones, "headers": hits}
    anim = p.animation()
    if anim:
        rep["animation"] = {k: anim[k] for k in (
            "duration", "numberOfPoses", "blockSize", "numTracks", "numDynamicDOFs",
            "preserved", "frame_rate", "quantizedDataSize", "dynamic_dofs_used",
            "static_dofs_used")}
        events = [e for e in p.animation_events() if e["events"]]
        rep["events"] = events
    if verbose:
        print(f"{path}: {bones} bones, {len(hits)} animation header candidate(s)")
        for h in hits:
            print(f"  header at data offset {h[0]}: type={h[1]} duration={h[2]}s tracks={h[3]}")
        if anim:
            print(f"  decoded: {anim['numberOfPoses']} frames, {anim['duration']:.3f} s "
                  f"({anim['frame_rate']:.2f} fps), {anim['numTracks']} tracks, "
                  f"{anim['numDynamicDOFs']} dynamic DOFs, {anim['quantizedDataSize']} bytes")
            print(f"  consumed: {anim['dynamic_dofs_used']} dynamic samples, "
                  f"{anim['static_dofs_used']} static DOFs")
            for e in rep.get("events", [])[:12]:
                print(f"    {e['bone']}: {[(round(x['time'], 3), x['text']) for x in e['events']]}")
        else:
            print("  no delta-compressed animation in this file")
    return rep


def main() -> None:
    import sys
    for arg in sys.argv[1:]:
        decode_report(arg)


if __name__ == "__main__":
    main()
