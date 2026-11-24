#!/usr/bin/env python3
"""Read an Unreal Engine 3 package (.umap/.upk) far enough to measure a tactical map.

Why this exists: the reference game's parcels are authored `.umap` files, and the question the board work
needs answered — how much cover a shipped parcel actually contains, how it is spaced, how big the piece is
— is only in that file. The config files give the grammar (parcel sizes, zones, entrances, road sets); the
geometry and the cover volumes are in the package.

What is parsed: the package header, the name/import/export tables, and the property stream of each
export. That is enough to list what a parcel contains (class names), where each actor sits (the `Location`
property, a Vector of three floats) and how it is scaled. No mesh data, no materials.

UE3 package format, from the shipped packages and the public format notes:
    header: tag(4)=0x9E2A83C1, version(2), licensee(2), size(4), cooked flags(4),
            name count(4), name offset(4), export count(4), export offset(4),
            import count(4), import offset(4), …
    name:   length-prefixed latin-1 string, then 4 bytes of flags
    export: class(4) super(4) outer(4) name(4) flags(4) serial size(4) serial offset(4) …
    import: class package(4) class name(4) outer(4) name(4)

Property stream, per property: name index, type, size, array index, then the payload. `Location` is a
StructProperty whose payload is three little-endian floats.

Usage:
    python3 tools/xcom2/read_umap.py <package.umap> [--limit N] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import struct
from collections import Counter
from pathlib import Path

TAG = 0x9E2A83C1


class Reader:
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.offset = offset

    def need(self, n: int) -> None:
        if self.offset + n > len(self.data):
            raise ValueError(f"read past the end: {n} bytes at {self.offset} of {len(self.data)}")

    def u8(self) -> int:
        self.need(1)
        v = self.data[self.offset]
        self.offset += 1
        return v

    def u16(self) -> int:
        self.need(2)
        v = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return v

    def i32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return v

    def u32(self) -> int:
        self.need(4)
        v = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return v

    def f32(self) -> float:
        self.need(4)
        v = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return v

    def bytes(self, n: int) -> bytes:
        self.need(n)
        v = self.data[self.offset:self.offset + n]
        self.offset += n
        return v

    def string(self) -> str:
        """A UE3 string: a length byte (or a negative int for UTF-16), then the characters."""
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            n = -n
            return self.bytes(n * 2).decode("utf-16-le", errors="replace").rstrip("\x00")
        return self.bytes(n).decode("latin-1", errors="replace").rstrip("\x00")


def read_names(r: Reader, count: int, offset: int) -> list[str]:
    """Scan the name table.

    A cooked package's entries are a length, the characters and a small flags field, but the flags field is
    not a constant width across packages (measured: the stride between entries changes after the first
    one). Rather than pin a layout, the table is scanned: a length that is plausible and a string that is
    printable and NUL-terminated is an entry, anything else is skipped a byte at a time. The table is then
    validated by its size -- a mis-scan does not produce a thousand plausible names.
    """
    data = r.data
    out: list[str] = []
    i = offset
    while i + 4 < len(data) and len(out) < count:
        n = struct.unpack_from("<i", data, i)[0]
        if 0 < n < 512:
            chunk = data[i + 4:i + 4 + n]
            if len(chunk) == n and chunk[-1] == 0 and all(32 <= b < 127 or b in (0, 9) for b in chunk):
                out.append(chunk[:-1].decode("latin-1", errors="replace"))
                i += 4 + n
                # the flags field: 4 zero bytes between entries in this package version
                if data[i:i + 4] == b"\x00\x00\x00\x00":
                    i += 4
                continue
        i += 1
    return out


def read_imports(r: Reader, count: int, offset: int) -> list[dict]:
    r.offset = offset
    out = []
    for _ in range(count):
        out.append({
            "class_package": r.i32(),
            "class_name": r.i32(),
            "outer": r.i32(),
            "name": r.i32(),
        })
    return out


def read_exports(r: Reader, count: int, offset: int) -> list[dict]:
    r.offset = offset
    out = []
    for _ in range(count):
        out.append({
            "class": r.i32(),
            "super": r.i32(),
            "outer": r.i32(),
            "name": r.i32(),
            "flags": r.u32(),
            "serial_size": r.i32(),
            "serial_offset": r.i32(),
        })
        # the rest of the export entry (archetype, object flags, generation, package flags) is not needed
        # for measurement, so the reader stops here and the next entry is read from its own offset when
        # the table is walked; the caller re-seeks per entry.
        break_after = 32
        r.offset += break_after - 28
    return out


def read_export_table(r: Reader, count: int, offset: int) -> list[dict]:
    """Read the export table.

    Measured on the SDK's plot packages (2026-11-24): the entry is 68 bytes and the serial fields sit at
    +32 (size) and +36 (offset), not at +20/+24 as the first version assumed. With the wrong offsets every
    export looked like an empty object and no actor could be placed, which is why the reference's plots
    could not be imported. The layout is: Class(+0) Super(+4) Outer(+8) Name(+12) Archetype(+16)
    ObjectFlags(+20, 8 bytes) ... SerialSize(+32) SerialOffset(+36).
    """
    r.offset = offset
    out = []
    for _ in range(count):
        base = r.offset
        r.offset = base
        cls = r.i32()
        sup = r.i32()
        outer = r.i32()
        name = r.i32()
        r.offset = base + 32
        size = r.i32()
        serial = r.i32()
        out.append({
            "class": cls,
            "super": sup,
            "outer": outer,
            "name": name,
            "serial_size": size,
            "serial_offset": serial,
        })
        r.offset = base + 68
    return out


PROPERTY_TYPES = {
    1: ("byte", 1), 2: ("int", 4), 3: ("bool", 1), 4: ("float", 4), 5: ("object", 4),
    6: ("name", 8), 7: ("string", None), 8: ("class", 4), 9: ("array", None),
    10: ("struct", None), 11: ("vector", 12), 12: ("rotator", 12), 13: ("str", None),
    14: ("map", None), 15: ("fixed_array", None),
}


def read_properties(r: Reader, names: list[str], limit: int = 4000) -> dict:
    """Walk an export's property stream for the values a measurement needs.

    The stream is self-describing: name index, type, size, array index. `None` means the property ends the
    stream. A StructProperty carries a struct name and then `size` bytes, which for `Location` is a Vector.
    """
    props: dict = {}
    seen = 0
    while seen < limit:
        start = r.offset
        try:
            name_index = r.i32()
        except ValueError:
            break
        if name_index == 0:
            break
        if not (0 <= name_index < len(names)):
            break
        name = names[name_index]
        type_index = r.u8() if False else None  # placeholder to keep the layout explicit
        # UE3 stores the type as a name index, not a byte
        r.offset = start + 4
        type_index = r.i32()
        size = r.i32()
        array_index = r.i32()
        seen += 1
        if not (0 <= type_index < len(names)):
            break
        ptype = names[type_index]
        payload = r.bytes(max(0, size))
        value = None
        if ptype in ("StructProperty", "Vector") and name == "Location" and len(payload) >= 12:
            value = list(struct.unpack_from("<fff", payload, 0))
        elif ptype == "FloatProperty" and len(payload) >= 4:
            value = struct.unpack_from("<f", payload, 0)[0]
        elif ptype == "IntProperty" and len(payload) >= 4:
            value = struct.unpack_from("<i", payload, 0)[0]
        elif ptype == "BoolProperty":
            value = bool(payload[0]) if payload else None
        elif ptype == "ByteProperty" and len(payload) >= 1:
            value = payload[0]
        if value is not None and array_index == 0:
            props[name] = value
        # an ArrayProperty's payload is the element count followed by the elements; not needed here
    return props


def parse_package(path: Path) -> dict:
    data = path.read_bytes()
    r = Reader(data)
    if r.u32() != TAG:
        raise ValueError(f"{path.name}: not an Unreal package")
    version = r.u16()
    licensee = r.u16()
    r.u32()  # package size
    # A cooked XCOM 2 package carries its summary immediately after the header, with a "None" string
    # between the size and the table (measured: the counts sit at 25/29/33/37/41/45). The exact field
    # order is: name count/offset, export count/offset, import count/offset.
    r.offset = 25
    name_count = r.i32()
    name_offset = r.i32()
    export_count = r.i32()
    export_offset = r.i32()
    import_count = r.i32()
    import_offset = r.i32()
    names = read_names(Reader(data), name_count, name_offset)
    imports = read_imports(Reader(data), import_count, import_offset)
    exports = read_export_table(Reader(data), export_count, export_offset)

    def name_of(index: int) -> str:
        if index == 0:
            return ""
        if index > 0 and index - 1 < len(names):
            return names[index - 1]
        if index < 0:
            i = -index - 1
            if i < len(imports):
                return names[imports[i]["name"]] if 0 <= imports[i]["name"] < len(names) else ""
        return ""

    def class_of(entry: dict) -> str:
        idx = entry["class"]
        if idx < 0:
            i = -idx - 1
            if i < len(imports):
                return names[imports[i]["name"]] if 0 <= imports[i]["name"] < len(names) else ""
            return ""
        if idx > 0 and idx - 1 < len(exports):
            return name_of(exports[idx - 1]["name"])
        return ""

    actors = []
    for entry in exports:
        cls = class_of(entry)
        if not cls:
            continue
        start = entry["serial_offset"]
        size = entry["serial_size"]
        if start <= 0 or size <= 0 or start + size > len(data):
            continue
        try:
            props = read_properties(Reader(data, start), names)
        except Exception:
            props = {}
        actors.append({
            "name": name_of(entry["name"]),
            "class": cls,
            "location": props.get("Location"),
            "scale": props.get("DrawScale"),
            "radius": props.get("CylinderComponent"),
        })
    return {
        "package": path.name,
        "version": version,
        "licensee": licensee,
        "names": len(names),
        "imports": len(imports),
        "exports": len(exports),
        "actors": actors,
    }


def summarise(pkg: dict) -> dict:
    classes = Counter(a["class"] for a in pkg["actors"])
    placed = [a for a in pkg["actors"] if a["location"]]
    xs = [a["location"][0] for a in placed]
    ys = [a["location"][1] for a in placed]
    zs = [a["location"][2] for a in placed]
    cover = [a for a in placed if "cover" in a["class"].lower()]
    cover_pts = [(a["location"][0], a["location"][1]) for a in cover]
    # nearest-neighbour spacing between cover volumes: the number the reference calls "cover density"
    spacing = []
    for i, (x, y) in enumerate(cover_pts):
        best = None
        for j, (x2, y2) in enumerate(cover_pts):
            if i == j:
                continue
            d = ((x - x2) ** 2 + (y - y2) ** 2) ** 0.5
            if best is None or d < best:
                best = d
        if best is not None:
            spacing.append(best)
    spacing.sort()
    extent = None
    if xs and ys:
        extent = (max(xs) - min(xs), max(ys) - min(ys))
    return {
        "package": pkg["package"],
        "actors": len(pkg["actors"]),
        "placed": len(placed),
        "classes": classes.most_common(12),
        "extent_uu": extent,
        "z_range": (min(zs), max(zs)) if zs else None,
        "cover_volumes": len(cover),
        "cover_spacing_uu_median": spacing[len(spacing) // 2] if spacing else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    ap.add_argument("--json", default=None)
    ap.add_argument("--actors", action="store_true")
    args = ap.parse_args()
    pkg = parse_package(Path(args.package))
    summary = summarise(pkg)
    print(json.dumps(summary, indent=1))
    if args.actors:
        for a in pkg["actors"][:40]:
            print(a)
    if args.json:
        Path(args.json).write_text(json.dumps(pkg, indent=1))


if __name__ == "__main__":
    main()
