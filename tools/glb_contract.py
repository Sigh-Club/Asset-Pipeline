#!/usr/bin/env python3
"""glb_contract.py — enforce the IoA 3D asset contract on a GLB before it ships.

The 3D combat contract lives in docs/3D_COMBAT_MIGRATION.md §4 and
docs/ASSET_PIPELINE_ROADMAP.md §2. Nothing enforced it, so "proof" assets
(proof_clay material, no UVs, 3 of 9 clips) reached the game. This gate makes
the gap measurable and blocks regressions.

Usage:
    python3 tools/glb_contract.py <file.glb> [--kind unit|prop|tile|env]
    python3 tools/glb_contract.py --dir <dir> --kind unit [--json report.json]

Exit code 0 = PASS, 1 = FAIL (hard contract breach), 2 = usage error.
Warnings do not fail by themselves but are always reported.

No third-party dependencies: parses the GLB container and glTF JSON directly.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

REQUIRED_CLIPS = ["idle", "walk", "run", "aim", "fire", "reload", "hit", "death", "melee"]
PLACEHOLDER_MATERIALS = {"proof_clay", "material", "Material", "default", "Default-Material"}

# Contract values, per docs/ASSET_PIPELINE_ROADMAP.md §2 and §4.
LIMITS = {
    # min_tris exists to reject PLACEHOLDER primitives (a box mosaic). The imported DoW2 troop
    # corpus includes genuinely small real meshes — tau drone and suit shells are 791-863 tris —
    # so the floor sits below them while still rejecting a placeholder.
    "unit": {"max_tris": 25000, "min_tris": 700, "soft_tris": 4000, "max_mb": 10.0, "skinned": True,
             "need_uv": True, "need_texture": True, "need_clips": REQUIRED_CLIPS},
    "prop": {"max_tris": 12000, "min_tris": 100, "max_mb": 4.0, "skinned": False,
             "need_uv": True, "need_texture": True, "need_clips": []},
    "tile": {"max_tris": 3000, "min_tris": 4, "max_mb": 1.0, "skinned": False,
             "need_uv": True, "need_texture": True, "need_clips": []},
    # The environment kit is the shipped DoW2 map dressing (`build_env_kit.py`): walls, barricades,
    # barrels, rubble. Two properties of the source mean the unit/prop floors do not describe it:
    # a shipped low wall is 10-90 triangles (it is a plate, not a placeholder), and several props
    # carry a flat-colour material with no diffuse map at all. Both are the game's own look, and the
    # map forge renders every prop, so a wrong one is visible rather than silently accepted.
    "env":  {"max_tris": 60000, "min_tris": 8, "max_mb": 20.0, "skinned": False,
             "need_uv": True, "need_texture": False, "need_clips": []},
    # A standalone weapon is a small textured mesh with no armature of its own: it is parented to the
    # unit's hand bone at runtime, so `skinned` is false here. The shipped set is 157-1576 tris.
    "weapon": {"max_tris": 8000, "min_tris": 8, "max_mb": 4.0, "skinned": False,
               "need_uv": True, "need_texture": True, "need_clips": []},
}


def read_glb(path: Path):
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB (bad magic)")
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError(f"glTF version {version}, expected 2")
    gltf = None
    bin_chunk = b""
    off = 12
    while off + 8 <= len(data):
        length, ctype = struct.unpack_from("<II", data, off)
        off += 8
        chunk = data[off:off + length]
        off += length
        if ctype == 0x4E4F534A:  # JSON
            gltf = json.loads(chunk)
        elif ctype == 0x004E4942:  # BIN
            bin_chunk = chunk
    if gltf is None:
        raise ValueError("no JSON chunk")
    return gltf, bin_chunk, len(data)


def png_size(blob: bytes):
    if len(blob) > 24 and blob[:8] == b"\x89PNG\r\n\x1a\n" and blob[12:16] == b"IHDR":
        w, h = struct.unpack_from(">II", blob, 16)
        return w, h
    return None


def image_bytes(gltf, bin_chunk, index):
    img = gltf.get("images", [])[index]
    bv = img.get("bufferView")
    if bv is None:
        return b""
    view = gltf["bufferViews"][bv]
    start = view.get("byteOffset", 0)
    return bin_chunk[start:start + view["byteLength"]]


def analyse(path: Path, kind: str):
    gltf, bin_chunk, size = read_glb(path)
    limits = LIMITS[kind]
    report = {"file": str(path), "kind": kind, "bytes": size,
              "mb": round(size / 1_048_576, 2), "errors": [], "warnings": [], "info": {}}

    tris = 0
    prims = 0
    has_uv = has_joints = has_weights = has_normal = False
    materials = []
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            prims += 1
            attrs = prim.get("attributes", {})
            has_uv = has_uv or "TEXCOORD_0" in attrs
            has_joints = has_joints or "JOINTS_0" in attrs
            has_weights = has_weights or "WEIGHTS_0" in attrs
            has_normal = has_normal or "NORMAL" in attrs
            if "indices" in prim:
                tris += gltf["accessors"][prim["indices"]]["count"] // 3
            else:
                pos = attrs.get("POSITION")
                if pos is not None:
                    tris += gltf["accessors"][pos]["count"] // 3
            mat = prim.get("material")
            if mat is not None:
                materials.append(gltf["materials"][mat].get("name", f"material_{mat}"))

    clips = [a.get("name", "") for a in gltf.get("animations", [])]
    skins = gltf.get("skins", [])
    joints = max((len(s.get("joints", [])) for s in skins), default=0)
    textures = gltf.get("textures", [])
    images = gltf.get("images", [])
    tex_sizes = []
    for i in range(len(images)):
        dims = png_size(image_bytes(gltf, bin_chunk, i))
        if dims:
            tex_sizes.append({"index": i, "w": dims[0], "h": dims[1]})

    # Bounds from accessor min/max (required by spec for POSITION).
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            pos_idx = prim.get("attributes", {}).get("POSITION")
            accessors = gltf.get("accessors", [])
            acc = accessors[pos_idx] if isinstance(pos_idx, int) and 0 <= pos_idx < len(accessors) else None
            if not acc or "min" not in acc:
                continue
            for i in range(3):
                lo[i] = min(lo[i], acc["min"][i])
                hi[i] = max(hi[i], acc["max"][i])
    extents = [hi[i] - lo[i] for i in range(3)] if lo[0] < float("inf") else [0, 0, 0]

    report["info"] = {
        "meshes": len(gltf.get("meshes", [])),
        "primitives": prims,
        "tris": tris,
        "materials": sorted(set(materials)),
        "clips": clips,
        "skins": len(skins),
        "joints": joints,
        "textures": len(textures),
        "images": len(images),
        "image_sizes": tex_sizes,
        "uv": has_uv,
        "normals": has_normal,
        "skinned_attributes": has_joints and has_weights,
        "bounds_min": [round(v, 4) for v in lo] if lo[0] < float("inf") else None,
        "bounds_max": [round(v, 4) for v in hi] if hi[0] < float("inf") else None,
        "extents_xyz": [round(v, 4) for v in extents],
    }

    # --- hard checks -------------------------------------------------------
    if tris > limits["max_tris"]:
        report["errors"].append(f"{tris} tris exceeds {limits['max_tris']} LOD0 budget (decimate first)")
    if tris < limits["min_tris"]:
        report["errors"].append(f"{tris} tris is below the {limits['min_tris']} floor — placeholder, not an asset")
    elif limits.get("soft_tris") and tris < limits["soft_tris"]:
        # A coarse reference (DoW2 ork armour is ~2.1k tris) is a real asset, not a
        # placeholder: the pixel master renders at 256 px, where 2k reads the same as
        # 4k. Warn so a genuinely thin mesh still stands out, but do not reject it.
        report["warnings"].append(
            f"{tris} tris is a low-detail unit (soft floor {limits['soft_tris']}) — coarse source, accepted")
    if report["mb"] > limits["max_mb"]:
        report["errors"].append(f"{report['mb']} MB exceeds {limits['max_mb']} MB budget")
    if limits["need_uv"] and not has_uv:
        report["errors"].append("no TEXCOORD_0: mesh cannot carry a texture (run tools/blender/uv_prepare.py)")
    if not has_normal:
        report["errors"].append("no NORMAL attribute: lighting will be flat/incorrect")
    if limits["need_texture"] and not textures:
        report["errors"].append("no textures: material is untextured (clay/proof look)")
    if limits["skinned"] and not skins:
        report["errors"].append("not skinned: units need an armature + skin for animation")
    if limits["skinned"] and skins and not report["info"]["skinned_attributes"]:
        report["errors"].append("skinned mesh missing JOINTS_0/WEIGHTS_0")
    if limits["skinned"] and joints and joints < 18:
        report["errors"].append(f"only {joints} joints; the shared humanoid rig needs >=18")
    missing_clips = [c for c in limits["need_clips"] if c not in clips]
    if missing_clips:
        report["errors"].append("missing animation clips: " + ", ".join(missing_clips))
    placeholder = sorted(set(materials) & PLACEHOLDER_MATERIALS)
    if placeholder and limits["need_texture"]:
        report["errors"].append("placeholder material(s): " + ", ".join(placeholder))

    # --- soft checks -------------------------------------------------------
    if extents[1] > 0 and extents[2] > 0 and extents[1] < extents[2] * 1.2:
        report["warnings"].append(
            f"dominant axis is not +Y (extents {report['info']['extents_xyz']}) — check up-axis conversion")
    if lo[0] < float("inf"):
        if abs(lo[1]) > 0.05:
            report["warnings"].append(f"origin not at feet on Y (min Y {lo[1]:.3f}); expected ~0")
        if abs(lo[2]) > 0.25:
            report["warnings"].append(f"origin not centred on Z (min Z {lo[2]:.3f})")
    if kind == "unit" and extents[1] and not (1.2 <= extents[1] <= 3.2):
        report["warnings"].append(f"unit height {extents[1]:.2f} m outside 1.2-3.2 m — check metres scale")
    if tex_sizes and max(max(t["w"], t["h"]) for t in tex_sizes) > 2048:
        report["warnings"].append("texture larger than 2K")
    if len(set(materials)) > 4:
        report["warnings"].append(f"{len(set(materials))} materials; target is one atlas (<=2)")
    if len(clips) > len(set(clips)):
        report["warnings"].append("duplicate animation clip names")
    unknown = [c for c in clips if c not in REQUIRED_CLIPS and kind == "unit"]
    if unknown:
        report["warnings"].append("clips outside the contract: " + ", ".join(unknown))

    report["verdict"] = "PASS" if not report["errors"] else "FAIL"
    return report


def render_text(report):
    i = report["info"]
    lines = [
        f"{report['verdict']}  {report['file']}  ({report['kind']}, {report['mb']} MB)",
        f"  tris={i.get('tris', '?')} prims={i.get('primitives', '?')} joints={i.get('joints', '?')} "
        f"skins={i.get('skins', '?')} uv={i.get('uv', '?')} textures={i.get('textures', '?')}",
        f"  materials={i.get('materials', [])}",
        f"  clips={i.get('clips', [])}",
        f"  extents={i.get('extents_xyz')} min={i.get('bounds_min')}",
    ]
    for e in report["errors"]:
        lines.append(f"  ERROR   {e}")
    for w in report["warnings"]:
        lines.append(f"  warning {w}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a GLB against the IoA 3D asset contract")
    ap.add_argument("glb", nargs="?", help="path to .glb")
    ap.add_argument("--dir", help="validate every .glb under this directory")
    ap.add_argument("--kind", default="unit", choices=sorted(LIMITS))
    ap.add_argument("--json", help="write the full report to this path")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not args.glb and not args.dir:
        ap.print_usage()
        return 2

    paths = [Path(args.glb)] if args.glb else sorted(Path(args.dir).rglob("*.glb"))
    if not paths:
        print("no .glb files found", file=sys.stderr)
        return 2

    reports = []
    failed = 0
    for p in paths:
        try:
            r = analyse(p, args.kind)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the batch
            r = {"file": str(p), "kind": args.kind, "verdict": "FAIL",
                 "errors": [f"unreadable: {exc}"], "warnings": [], "info": {},
                 "bytes": p.stat().st_size if p.exists() else 0,
                 "mb": round(p.stat().st_size / 1_048_576, 2) if p.exists() else 0}
        reports.append(r)
        if r["verdict"] != "PASS":
            failed += 1
        if not args.quiet:
            print(render_text(r))
            print()

    summary = {"checked": len(reports), "failed": failed,
               "verdict": "PASS" if failed == 0 else "FAIL", "reports": reports}
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))
    print(f"{summary['verdict']}: {len(reports) - failed}/{len(reports)} GLB(s) meet the contract")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
