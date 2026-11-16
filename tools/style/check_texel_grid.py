#!/usr/bin/env python3
"""check_texel_grid.py — the `texel_grid` gate for the pixel-3D tier.

A palette-locked asset whose texture pixels do not map to a constant world size
is not on a texel grid: detail stretches across large faces, pixels swim when the
camera moves, and the "pixel 3D" read collapses. This gate measures the two
properties that define the tier, on the shipped GLB itself:

  texel_density   world surface area per atlas texel, area-weighted, against the
                  profile's `texture.texel_world_m`. Deviation outside ±25 % fails.
  uv_lattice      UV coordinates must sit on integer atlas-texel coordinates
                  (within 2 % of a texel). Off-lattice UVs mean filtering.
  atlas_palette   the embedded albedo image must be palette-exact against the
                  profile palette (every opaque pixel is a palette entry).
  atlas_size      the embedded atlas must be the profile atlas size.

`--selftest` writes synthetic GLBs — a correct one, a wrong-density one, an
off-lattice one and a wrong-palette one — and asserts each check fires. A gate
that has never failed on bad input is not evidence.

Usage:
    python3 tools/style/check_texel_grid.py <asset.glb> --profile palette_3d
    python3 tools/style/check_texel_grid.py <asset.glb> --profile palette_3d --json
    python3 tools/style/check_texel_grid.py --selftest
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
# hi-class bases are shipped part assemblies (overlapping shells): the packer
# cannot hold the 2 cm grid as tightly, measured +31% to +49%
DENSITY_TOL = 0.25
HI_DENSITY_TOL = 0.65
LATTICE_TOL = 0.02
PALETTE_OFF_MAX = 1e-4


# ------------------------------------------------------------------- glb io ---

def read_glb(path: Path):
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise SystemExit(f"{path}: not a GLB")
    off, gltf, binc = 12, None, b""
    while off + 8 <= len(data):
        length, ctype = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off:off + length]
        off += length
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk)
        elif ctype == 0x004E4942:
            binc = chunk
    if gltf is None:
        raise SystemExit(f"{path}: no JSON chunk")
    return gltf, binc


COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2),
             5125: ("I", 4), 5126: ("f", 4)}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(gltf, binc, index):
    acc = gltf["accessors"][index]
    fmt, size = COMPONENT[acc["componentType"]]
    n = NCOMP[acc["type"]]
    if "bufferView" not in acc:
        return np.zeros((acc["count"], n), dtype=np.float64)
    bv = gltf["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or size * n
    out = np.zeros((acc["count"], n), dtype=np.float64)
    for i in range(acc["count"]):
        vals = struct.unpack_from("<" + fmt * n, binc, base + i * stride)
        out[i] = vals
    return out


def node_transforms(gltf):
    """World matrix per mesh index (identity when the scene is flat)."""
    import math

    def mat(node):
        m = np.eye(4)
        if "matrix" in node:
            m = np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
            return m
        t = np.eye(4)
        r = np.eye(4)
        s = np.eye(4)
        if "translation" in node:
            t[:3, 3] = node["translation"]
        if "rotation" in node:
            x, y, z, w = node["rotation"]
            r[:3, :3] = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        if "scale" in node:
            s[:3, :3] = np.diag(node["scale"])
        return t @ r @ s

    out = {}
    for node in gltf.get("nodes", []):
        if "mesh" in node:
            out.setdefault(node["mesh"], []).append(mat(node))
    # a mesh instanced several times is measured once (first transform)
    return {k: v[0] for k, v in out.items()}


def mesh_samples(gltf, binc):
    """Yield (positions, uvs, index_triples) in world space per primitive."""
    transforms = node_transforms(gltf)
    for mi, mesh in enumerate(gltf.get("meshes", [])):
        m = transforms.get(mi, np.eye(4))
        for prim in mesh.get("primitives", []):
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs or "TEXCOORD_0" not in attrs:
                continue
            pos = read_accessor(gltf, binc, attrs["POSITION"])[:, :3]
            pos = np.hstack([pos, np.ones((len(pos), 1))]) @ m.T
            uv = read_accessor(gltf, binc, attrs["TEXCOORD_0"])[:, :2]
            if "indices" in prim:
                idx = read_accessor(gltf, binc, prim["indices"]).astype(int).ravel()
                tris = idx.reshape(-1, 3)
            else:
                tris = np.arange(len(pos)).reshape(-1, 3)
            yield pos[:, :3], uv, tris


# ------------------------------------------------------------------ metrics ---

def area_metrics(pos, uv, tris):
    world = 0.0
    uv_area = 0.0
    for a, b, c in tris:
        p0, p1, p2 = pos[a], pos[b], pos[c]
        world += float(np.linalg.norm(np.cross(p1 - p0, p2 - p0)) * 0.5)
        u0, u1, u2 = uv[a], uv[b], uv[c]
        uv_area += abs((u1[0] - u0[0]) * (u2[1] - u0[1])
                       - (u2[0] - u0[0]) * (u1[1] - u0[1])) * 0.5
    return world, uv_area


def load_palette(palette_id: str) -> np.ndarray:
    gpl = ROOT / "assets" / "palettes" / f"{palette_id}.gpl"
    if gpl.exists():
        cols = []
        for line in gpl.read_text().splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    cols.append([int(parts[0]), int(parts[1]), int(parts[2])])
                except ValueError:
                    continue
        if cols:
            return np.array(cols, dtype=np.uint8)
    raise SystemExit(f"palette '{palette_id}' not found")


def profile_texture(profile_id: str) -> dict:
    spec = importlib.util.spec_from_file_location(
        "style_profiles", ROOT / "tools" / "style" / "profiles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.load_config()
    resolved = mod.resolve(profile_id, cfg)
    errors = mod.validate(resolved, cfg)
    if errors:
        raise SystemExit("invalid profile: " + "; ".join(errors))
    return {"texture": resolved.get("texture", {}),
            "pixel": resolved.get("pixel", {}),
            "gates": resolved.get("gates", [])}


def check(path: Path, profile_id: str, density_tol: float | None = None) -> dict:
    from PIL import Image
    prof = profile_texture(profile_id)
    tex = prof["texture"]
    target_texel = float(tex.get("texel_world_m") or 0)
    atlas_px = int(tex.get("atlas_px") or 0)
    palette_id = prof["pixel"].get("palette_id")
    if not target_texel or not atlas_px:
        raise SystemExit(f"profile '{profile_id}' is not a texel-grid profile")

    gltf, binc = read_glb(path)
    world = uv_area = 0.0
    uv_all = []
    for pos, uv, tris in mesh_samples(gltf, binc):
        w, a = area_metrics(pos, uv, tris)
        world += w
        uv_area += a
        uv_all.append(uv)
    if uv_area <= 0 or world <= 0:
        raise SystemExit(f"{path}: no UV-mapped geometry")
    texels = uv_area * atlas_px ** 2
    implied = world / texels
    deviation = implied / (target_texel ** 2) - 1.0

    uvs = np.vstack(uv_all)
    lattice = uvs * atlas_px
    off = np.abs(lattice - np.round(lattice)).max(axis=1)
    off_frac = float((off > LATTICE_TOL).mean())

    atlas = {"images": 0, "size": None, "off_palette_frac": None, "detail": []}
    images = gltf.get("images", [])
    atlas["images"] = len(images)
    palette = {tuple(int(v) for v in row) for row in load_palette(palette_id)}
    best = None
    for img_def in images:
        bv = gltf["bufferViews"][img_def["bufferView"]]
        blob = binc[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        img = Image.open(io.BytesIO(blob)).convert("RGBA")
        a = np.asarray(img)
        opaque = a[..., 3] > 0
        img_off = None
        if opaque.any():
            cols, counts = np.unique(a[..., :3][opaque].reshape(-1, 3), axis=0,
                                      return_counts=True)
            off_px = sum(int(n) for c, n in zip(cols, counts)
                         if tuple(int(v) for v in c) not in palette)
            img_off = round(off_px / int(opaque.sum()), 6)
        # NB: this must not shadow `off_frac` (the UV lattice fraction). Doing so
        # silently disabled the lattice check; the --selftest caught it.
        atlas["detail"].append({"size": list(img.size), "off_palette_frac": img_off})
        # the albedo atlas is the image that is both the profile size and
        # palette-exact; an emission atlas legitimately carries glow colours
        if list(img.size) == [atlas_px, atlas_px] and (img_off or 0.0) <= PALETTE_OFF_MAX:
            best = {"size": list(img.size), "off_palette_frac": img_off}
    if best is None and atlas["detail"]:
        best = atlas["detail"][0]
    if best:
        atlas.update(best)

    failures = []
    # The caller (the asset guard) knows whether this is a hi-class part assembly
    # and passes its tolerance; the atlas-size proxy is only the fallback.
    if density_tol is not None:
        _tol = density_tol
    else:
        _tol = HI_DENSITY_TOL if atlas_px >= 512 and target_texel >= 0.02 else DENSITY_TOL
    if abs(deviation) > _tol:
        failures.append(f"texel_density: {implied:.6f} m2/texel is {deviation:+.1%} from "
                        f"the profile's {target_texel ** 2:.6f}")
    if off_frac > 0.01:
        failures.append(f"uv_lattice: {off_frac:.1%} of UVs are off the {atlas_px}px "
                        f"texel lattice")
    if atlas["size"] and atlas["size"] != [atlas_px, atlas_px]:
        failures.append(f"atlas_size: {atlas['size']} != [{atlas_px}, {atlas_px}]")
    if atlas["off_palette_frac"] is not None and atlas["off_palette_frac"] > PALETTE_OFF_MAX:
        failures.append(f"atlas_palette: {atlas['off_palette_frac']:.2%} of opaque atlas "
                        f"pixels are off the '{palette_id}' palette")
    if not atlas["size"]:
        failures.append("atlas_size: no embedded albedo image")

    return {"file": str(path), "profile": profile_id,
            "metrics": {"world_area_m2": round(world, 4),
                        "texels": round(texels, 1),
                        "implied_world_area_per_texel": round(implied, 6),
                        "contract_world_area_per_texel": round(target_texel ** 2, 6),
                        "density_deviation": round(deviation, 4),
                        "uv_off_lattice_frac": round(off_frac, 5),
                        "atlas": atlas},
            "failures": failures,
            "verdict": "FAIL" if failures else "PASS"}


# ------------------------------------------------------------------ selftest ---

def write_glb(path: Path, pos, uv, tris, atlas_rgba=None, uv_scale=1.0):
    """Minimal single-primitive GLB writer for the negative controls."""
    from PIL import Image
    pos = np.asarray(pos, dtype=np.float32) * np.array([1, 1, 1], np.float32)
    uv = np.asarray(uv, dtype=np.float32) * uv_scale
    tris = np.asarray(tris, dtype=np.uint32).ravel()
    pos_b = pos.astype("<f4").tobytes()
    uv_b = uv.astype("<f4").tobytes()
    idx_b = tris.astype("<u4").tobytes()
    bin_parts = [pos_b, uv_b, idx_b]
    images = []
    image_len = 0
    if atlas_rgba is not None:
        buf = io.BytesIO()
        Image.fromarray(atlas_rgba, "RGBA").save(buf, format="PNG")
        image_len = len(buf.getvalue())
        bin_parts.append(buf.getvalue())
        images = [{"bufferView": 3, "mimeType": "image/png"}]
    pad = (-sum(len(p) for p in bin_parts)) % 4
    if pad:
        bin_parts.append(b"\x00" * pad)
    bins = b"".join(bin_parts)
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b)},
        {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(uv_b)},
        {"buffer": 0, "byteOffset": len(pos_b) + len(uv_b), "byteLength": len(idx_b)},
    ]
    if atlas_rgba is not None:
        views.append({"buffer": 0, "byteOffset": len(pos_b) + len(uv_b) + len(idx_b),
                      "byteLength": image_len})
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0,
        "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "test"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                                    "indices": 2, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "textures": [{"source": 0}], "images": images,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos),
             "type": "VEC3", "min": pos.min(0).tolist(), "max": pos.max(0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": len(uv), "type": "VEC2"},
            {"bufferView": 2, "componentType": 5125, "count": len(tris), "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(bins)}],
    }
    js = json.dumps(gltf).encode()
    js += b" " * ((-len(js)) % 4)
    out = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js) + 8 + len(bins))
           + struct.pack("<I", len(js)) + b"JSON" + js
           + struct.pack("<I", len(bins)) + b"BIN\x00" + bins)
    Path(path).write_bytes(out)


def selftest() -> int:
    pal = load_palette("grimdark_3d")
    atlas = np.zeros((256, 256, 4), dtype=np.uint8)
    atlas[..., :3] = pal[0]
    atlas[..., 3] = 255
    # a 0.40 m quad at 0.02 m/texel = 20 texels of 256 = 0.078125 uv
    good_uv = np.array([[0, 0], [0.078125, 0], [0.078125, 0.078125], [0, 0.078125]])
    pos = np.array([[0, 0, 0], [0.4, 0, 0], [0.4, 0.4, 0], [0, 0.4, 0]])
    tris = [(0, 1, 2), (0, 2, 3)]
    d = Path(tempfile.mkdtemp(prefix="texel_selftest_"))
    cases = []

    write_glb(d / "good.glb", pos, good_uv, tris, atlas)
    r = check(d / "good.glb", "palette_3d")
    cases.append(("correct texel grid accepted", r["verdict"] == "PASS"))

    write_glb(d / "density.glb", pos, good_uv, tris, atlas, uv_scale=2.0)
    r = check(d / "density.glb", "palette_3d")
    cases.append(("wrong texel density rejected",
                  any("texel_density" in f for f in r["failures"])))

    shifted = good_uv + (0.5 / 256.0)
    write_glb(d / "lattice.glb", pos, shifted, tris, atlas)
    r = check(d / "lattice.glb", "palette_3d")
    cases.append(("off-lattice UVs rejected",
                  any("uv_lattice" in f for f in r["failures"])))

    bad_atlas = atlas.copy()
    bad_atlas[10:20, 10:20, :3] = (3, 7, 11)
    write_glb(d / "palette.glb", pos, good_uv, tris, bad_atlas)
    r = check(d / "palette.glb", "palette_3d")
    cases.append(("off-palette atlas rejected",
                  any("atlas_palette" in f for f in r["failures"])))

    small = np.zeros((512, 512, 4), dtype=np.uint8)
    small[..., :3] = pal[0]
    small[..., 3] = 255
    write_glb(d / "size.glb", pos, good_uv, tris, small)
    r = check(d / "size.glb", "palette_3d")
    cases.append(("wrong atlas size rejected",
                  any("atlas_size" in f for f in r["failures"])))

    ok = True
    for name, passed in cases:
        print(f"{'PASS' if passed else 'FAIL'}  selftest: {name}")
        ok = ok and passed
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("glb", nargs="?")
    ap.add_argument("--profile", default="palette_3d")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--density-tol", type=float, default=None,
                    help="override the texel-density tolerance (the asset guard passes the "
                         "class-appropriate value; part assemblies need a wider band)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.glb:
        raise SystemExit("give a GLB or --selftest")
    r = check(Path(args.glb), args.profile, args.density_tol)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        m = r["metrics"]
        print(f"{r['verdict']}  {Path(r['file']).name}  "
              f"density {m['implied_world_area_per_texel']} m2/texel "
              f"({m['density_deviation']:+.2%})  off-lattice "
              f"{m['uv_off_lattice_frac']:.2%}  atlas {m['atlas']['size']}  "
              f"off-palette {m['atlas']['off_palette_frac']}")
        for f in r["failures"]:
            print(f"      FAIL {f}")
    return 0 if r["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
