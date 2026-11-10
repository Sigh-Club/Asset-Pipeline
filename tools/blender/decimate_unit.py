#!/usr/bin/env python3
"""decimate_unit.py — bring a rigged unit down to the pixel tier's triangle budget
without losing the armature, the skin or the clip set.

`inspect_mesh.py` joins meshes and exports the object alone, which drops the
armature and every clip. This keeps the whole scene: the decimate modifier is
applied to the skinned mesh (vertex groups survive collapse decimation) and the
armature with its actions is exported with it.

    tools/blender_run.sh --job decimate -- -b -P tools/blender/decimate_unit.py -- \
        --glb <unit_textured.glb> --out output/gen/<unit> --tris 4000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--id")
    ap.add_argument("--tris", type=int, required=True)
    ap.add_argument("--profile", help="take geometry.tris_max from a style profile")
    ap.add_argument("--no-clean", action="store_true",
                    help="skip the pre-decimate weld/loose/degenerate cleanup")
    return ap.parse_args(argv)


def tris_of(obj) -> int:
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def profile_tris(profile_id: str | None) -> int | None:
    if not profile_id:
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "style_profiles", ROOT / "tools" / "style" / "profiles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    resolved = mod.resolve(profile_id)
    errors = mod.validate(resolved)
    if errors:
        raise SystemExit("invalid profile: " + "; ".join(errors))
    return int(resolved.get("geometry", {}).get("tris_max", 0)) or None


def main():
    args = parse_args()
    target = profile_tris(args.profile) or args.tris
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.glb).resolve()))
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh in the unit GLB")
    obj = max(meshes, key=lambda o: len(o.data.polygons))
    before = tris_of(obj)

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    # Clean the image-to-3D shell before decimating. img23d output arrives with
    # coincident/duplicated faces and loose geometry (measured on the Cinder Cultist:
    # 8 components, 429k faces); collapsing that directly leaves overlapping shells
    # whose renders speckle into hundreds of alpha components, which the pixel
    # master gate correctly rejects. Weld, drop loose/degenerate geometry first.
    if not args.no_clean:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=1e-4)
        bpy.ops.mesh.delete_loose()
        bpy.ops.mesh.dissolve_degenerate()
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        # Floating debris goes before decimation, at full resolution where the
        # cutoff is meaningful: a scrap under 2 % of the body cannot read at 256 px
        # and only costs silhouette integrity (the Cinder Cultist's detached scraps
        # broke its master into 2-4 alpha components). Legitimate armour plates are
        # far above that.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.separate(type="LOOSE")
        bpy.ops.object.mode_set(mode="OBJECT")
        parts = [o for o in bpy.data.objects if o.type == "MESH"]
        if len(parts) > 1:
            largest = max(parts, key=lambda o: len(o.data.polygons))
            cutoff = max(16, int(len(largest.data.polygons) * 0.02))
            for part in parts:
                if part is not largest and len(part.data.polygons) < cutoff:
                    bpy.data.objects.remove(part, do_unlink=True)
            parts = [o for o in bpy.data.objects if o.type == "MESH"]
            for part in parts:
                part.select_set(True)
            bpy.context.view_layer.objects.active = largest
            bpy.ops.object.join()
            obj = bpy.context.view_layer.objects.active
        before = tris_of(obj)
    # collapse decimation undershoots the requested ratio by a face or two, and
    # the unit contract has a hard 4000-tri floor: retry upward until it clears
    snapshot = obj.data.copy()
    ratio = 0.0
    after = 0
    for bump in (1.00, 1.02, 1.05, 1.10, 1.20):
        obj.data = snapshot.copy()
        ratio = min(1.0, target * bump / max(before, 1))
        mod = obj.modifiers.new("pixel_lod", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = ratio
        mod.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        after = tris_of(obj)
        if after >= target:
            break
    if after < target:
        raise SystemExit(f"decimation undershot: {after} < {target}")

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    asset_id = args.id or Path(args.glb).stem.replace("_texel", "").replace("_pixel", "")
    dest = out / f"{asset_id}_lod.glb"
    bpy.ops.object.select_all(action="SELECT")
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    bpy.context.view_layer.objects.active = armatures[0] if armatures else obj
    bpy.ops.export_scene.gltf(filepath=str(dest), use_selection=True,
                              export_format="GLB", export_yup=True,
                              export_animations=True,
                              export_animation_mode="ACTIONS",
                              export_anim_slide_to_zero=True)
    (out / "decimate_report.json").write_text(json.dumps({
        "source": str(Path(args.glb).resolve()), "tris_before": before,
        "tris_after": after, "target": target, "ratio": round(ratio, 4),
        "armatures": [a.name for a in armatures], "glb": str(dest),
    }, indent=2) + "\n")
    print(f"DECIMATED {before} -> {after} tris (target {target}) -> {dest}")


main()
