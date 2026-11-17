#!/usr/bin/env python3
"""dds_to_png.py — convert shipped DoW2 textures to PNG for the Blender stage.

DoW2 ships its materials as DDS (`<material>_dif.dds`, 512x512 DXT1). Blender's bundled image
loader is unreliable for DDS in this environment, and the glTF exporter cannot embed DDS anyway, so
the textures are converted once, with the source colour untouched, into a cache directory the build
tool reads.

Usage:
  python3 tools/dow2/dds_to_png.py <out-dir> <dds> [<dds> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def convert(src: Path, out_dir: Path) -> Path | None:
    try:
        im = Image.open(src)
    except Exception as exc:
        print(f"SKIP {src.name}: {exc}")
        return None
    im = im.convert("RGB")
    dest = out_dir / f"{src.stem}.png"
    im.save(dest)
    print(f"PNG {src.name} -> {dest.name} {im.size[0]}x{im.size[1]}")
    return dest


def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: dds_to_png.py <out-dir> <dds> [...]")
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in argv[1:]:
        convert(Path(a), out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
