#!/usr/bin/env python3
"""Extract textures from Relic .rsh (chunky) containers into PNGs.

RSH layout (decoded from DoW1 SharedTextures samples):
  "Relic Chunky\\r\\n\\x1a\\x00" magic, u32 format_version, u32 header_version
  then chunks: type[8] + u32 version + u32 length + u32 name_len + name bytes
  FOLDSHRF -> FOLDTXTR -> DATAHEAD {fmt, width, height, mips}
           -> FOLDIMAG -> DATAATTR {fmt, width, height, mips}
                       -> DATADATA (raw DXT payload, mip chain)

The DATADATA payload is wrapped in a synthetic DDS header (DXT1/DXT5 by the
ATTR format code) and decoded with Pillow.
"""
import os
import struct
import sys

import numpy as np
from PIL import Image

DDS_MAGIC = b"DDS "
DDS_HEADER_SIZE = 124  # 4 magic + 124 header (incl. 32-byte reserved)


def parse_chunks(buf, pos, end, out, path):
    """Recursive v0101/v0301 chunk walker."""
    while pos + 20 <= end:
        ctype = buf[pos:pos + 8].decode("ascii", "replace").rstrip("\x00")
        ver, length, name_len = struct.unpack_from("<III", buf, pos + 8)
        name_start = pos + 20
        name = buf[name_start:name_start + name_len].split(b"\x00")[0].decode(
            "ascii", "replace")
        body = name_start + name_len
        if ctype.startswith("FOLD"):
            out.append((path + "/" + name, ctype, None, None, None))
            parse_chunks(buf, body, body + length, out,
                         path + "/" + name)
        else:
            out.append((path + "/" + name, ctype, buf[body:body + length],
                        None, None))
        pos = body + length


def rsh_images(path):
    """Returns [(name, fmt, width, height, payload_bytes), ...]."""
    buf = open(path, "rb").read()
    if not buf.startswith(b"Relic Chunky"):
        raise ValueError("not a Relic Chunky file: " + path)
    chunks = []
    # header: 16 magic + u32 + u32, first chunk at 0x18
    parse_chunks(buf, 0x18, len(buf), chunks, "")
    images = []
    i = 0
    while i < len(chunks):
        p, ctype, data, _, _ = chunks[i]
        if ctype == "DATAATTR":
            fmt, w, h, mips = struct.unpack("<IIII", data)
            # find following DATADATA
            if i + 1 < len(chunks) and chunks[i + 1][1] == "DATADATA":
                payload = chunks[i + 1][2]
                images.append((os.path.basename(p) + ".dds", fmt, w, h, payload,
                               mips))
                i += 2
                continue
        i += 1
    return images


def dxt_payload_to_dds(w, h, mips, payload, fmt):
    """Wrap a raw DXT mip chain in a minimal DDS header Pillow can decode."""
    # fmt 8 empirically = DXT1-style 1bpp-ish block compression (see DATAATTR);
    # block sizes: DXT1 = 8 bytes/block, DXT3/5 = 16
    fourcc = b"DXT1" if fmt == 8 else b"DXT5"
    bpp_block = 8 if fmt == 8 else 16

    linear = 0
    mw, mh = w, h
    for _ in range(max(1, mips)):
        linear += max(1, (mw + 3) // 4) * max(1, (mh + 3) // 4) * bpp_block
        mw, mh = max(1, mw // 2), max(1, mh // 2)

    flags = 0x00021007  # CAPS | HEIGHT | WIDTH | PIXELFORMAT | MIPMAPCOUNT
    pixflags = 0x00000004  # DDPF_FOURCC
    header = b"".join([
        struct.pack("<7I", DDS_HEADER_SIZE, flags, h, w, linear, 0, mips),
        b"\x00" * 44,                                   # reserved[11]
        struct.pack("<2I4s5I", 32, pixflags, fourcc, 0, 0, 0, 0, 0),  # ddspf
        struct.pack("<5I", 0x00001000, 0, 0, 0, 0),     # caps: TEXTURE
    ])
    return b"DDS " + header + payload


def rsh_to_pngs(rsh_path, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, fmt, w, h, payload, mips in rsh_images(rsh_path):
        try:
            dds = dxt_payload_to_dds(w, h, mips, payload, fmt)
            import io
            img = Image.open(io.BytesIO(dds))
            img.load()
        except Exception as e:
            print("  decode fail %s fmt=%d: %s" % (name, fmt, e), file=sys.stderr)
            continue
        base = os.path.splitext(os.path.basename(rsh_path))[0]
        out = os.path.join(out_dir, "%s__%s_mip0.png" % (base, name))
        img.convert("RGBA").save(out)
        written.append(out)
    return written


def main():
    src = sys.argv[1]
    out_dir = sys.argv[2]
    for f in os.listdir(src):
        if f.endswith(".rsh"):
            for p in rsh_to_pngs(os.path.join(src, f), out_dir):
                print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
