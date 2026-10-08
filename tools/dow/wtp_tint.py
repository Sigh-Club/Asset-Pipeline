#!/usr/bin/env python3
"""DoW team-colour compositor: WTP layer masks x .teamcolour RGB -> tinted atlas PNG.

WTP (TPAT) layout (verified on Definitive Edition, 2026-10-08):
  INFO  u32 h,u32 w (image dims of the layer masks)
  IMAG  the default atlas (ATTR fmt/w/h/mips + DATA raw DXT mip chain)
  PTLD  per layer: u8 layer code (0=Primary 1=Secondary 2=Trim 3=Weapon 4=Eyes
        5=Dirt) + raw W*H single-byte mask (soft 0..255 blend weight, UV-aligned
        to the atlas, NOT axis-flipped)
  PTBD  4 floats - badge placement rect on the atlas (x,y,w,h uv px)
  PTBN  4 floats - banner rect (rare)

.teamcolour (lua): UnitCustomization table with per-layer r/g/b 0..255 plus
badge/banner names; per-race defaults in teamcolourdefaults.lua.

Blend (empirical, matches the classic DoW team shader): the diffuse is
multiplied toward the layer colour inside the mask:
    out = diff*(1-m) + diff*colour*m

Usage:
    wtp_tint.py atlas.rsh|atlas_from_sga:path out.png \
        --primary 255,0,0 [--secondary .. --trim .. --weapon .. --eyes ..]
"""
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import whm_v4_patch  # noqa: F401

from relic.chunky.serializer import read_chunky
from relic.chunky_formats.dow.wtp.wtp import WtpChunky, PtldLayer
import rsh_extract as R

LAYERS = {"primary": PtldLayer.Primary, "secondary": PtldLayer.Secondary,
          "trim": PtldLayer.Trim, "weapon": PtldLayer.Weapon,
          "eyes": PtldLayer.Eyes, "dirt": PtldLayer.Dirt}


def atlas_from_rsh_bytes(raw):
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".rsh", delete=False) as f:
        f.write(raw); p = f.name
    try:
        name, fmt, w, h, payload, mips = R.rsh_images(p)[0]
        dds = R.dxt_payload_to_dds(w, h, mips, payload, fmt)
        img = Image.open(io.BytesIO(dds))
        img.load()
        return img.convert("RGB"), (w, h)
    finally:
        os.unlink(p)


def parse_wtp(raw):
    return WtpChunky.convert(read_chunky(io.BytesIO(raw)))


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = [a for a in argv[1:] if a.startswith("--")]
    src, out = args[0], args[1]
    colours = {}
    for i, f in enumerate(flags):
        name = f[2:].lstrip("-=:")
        if name in LAYERS and i + 1 < len(argv) - 1:
            colours[name] = tuple(int(c) for c in argv[argv.index(f) + 1].split(","))
    if src.endswith(".rsh"):
        atlas, (w, h) = atlas_from_rsh_bytes(Path(src).read_bytes())
        wtp = None
        # convention: <stem>_default.wtp next to the rsh
        wtp_path = Path(src).with_name(Path(src).stem + "_default.wtp")
        if wtp_path.exists():
            wtp = parse_wtp(wtp_path.read_bytes())
    else:
        wtp = parse_wtp(Path(src).read_bytes())
        raise SystemExit("TODO: wtp-only (uses embedded IMAG atlas)")

    diff = np.asarray(atlas, np.float32) / 255.0
    H, W = diff.shape[:2]
    if wtp is None:
        print("no wtp beside atlas; nothing to do")
        return 1
    mask_h, mask_w = wtp.tpat.info.height, wtp.tpat.info.width
    out_img = diff.copy()
    for name, layer in sorted(LAYERS.items()):
        if name not in colours:
            continue
        ptld = next((p for p in wtp.tpat.ptld if p.layer == layer), None)
        if ptld is None:
            continue
        m = np.frombuffer(ptld.image, np.uint8).reshape(mask_h, mask_w)
        if (mask_h, mask_w) != (H, W):
            m = np.asarray(Image.fromarray(m).resize((W, H), Image.BILINEAR), np.float32) / 255.
        else:
            m = m.astype(np.float32) / 255.
        col = np.array(colours[name], np.float32) / 255.
        tinted = diff * col
        out_img = out_img * (1 - m[..., None]) + tinted * m[..., None]
    Image.fromarray((np.clip(out_img, 0, 1) * 255).astype(np.uint8)).save(out)
    print(f"{out}: tinted with {sorted(colours)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
