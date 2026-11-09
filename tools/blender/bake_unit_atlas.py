#!/usr/bin/env python3
"""bake_unit_atlas.py — bake the box-projected slot materials into a UV atlas.

The rigged unit has slot-named materials and a real UV layout, but a GLB cannot
carry Blender's object-coordinate box projection: it needs UV-mapped images. This
script bakes the four slot materials from the material library into one atlas on
the unit's own UVs, then (second pass) rebuilds the materials with the atlas and
exports a textured GLB.

Two passes because normal/roughness/metallic are derived with `derive_maps.py`
outside Blender (Blender's bundled PIL is not dependable):

  # pass 1 — bake the albedo atlas (Cycles, lights off: colour only)
  blender -b -P tools/blender/bake_unit_atlas.py -- \
      --glb <unit_rigged.glb> --library <library.blend> --out <dir> --stage albedo

  # derive maps (system python)
  python3 tools/pbr/derive_maps.py --atlas <dir>/atlas_albedo.png --out <dir>

  # pass 2 — build final materials, embed textures, export
  blender -b -P tools/blender/bake_unit_atlas.py -- \
      --glb <unit_rigged.glb> --out <dir> --stage final --atlas-size 2048

Result: <dir>/unit_textured.glb with albedo + normal + roughness/metallic and one
material per slot.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
import bmesh

ROOT = Path(__file__).resolve().parents[2]
SLOTS = ["armour_primary", "armour_secondary", "metal_trim", "underlayer"]
FACTION = "iron_directorate"
LIB_PREFIX = f"IOA_{FACTION}__"


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stage", required=True, choices=("albedo", "final"))
    ap.add_argument("--library", help="library .blend (stage albedo)")
    ap.add_argument("--atlas-size", type=int, default=2048)
    ap.add_argument("--samples", type=int, default=16)
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_unit(path: Path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    if not objs:
        raise SystemExit(f"no mesh in {path}")
    obj = max(objs, key=lambda o: len(o.data.polygons))
    bpy.context.view_layer.objects.active = obj
    return obj


def slot_of(material_name: str) -> str | None:
    for slot in SLOTS:
        if material_name == slot or material_name == f"{LIB_PREFIX}{slot}":
            return slot
    return None


def stage_albedo(args):
    unit = import_unit(Path(args.glb).resolve())
    lib = Path(args.library).resolve()
    with bpy.data.libraries.load(str(lib), link=False) as (src, dst):
        wanted = [n for n in src.materials if n.startswith(LIB_PREFIX)]
        dst.materials = wanted
    lib_mats = {m.name.replace(LIB_PREFIX, ""): m for m in dst.materials if m}
    missing = [s for s in SLOTS if s not in lib_mats]
    if missing:
        raise SystemExit(f"library has no material for slots: {missing}")

    # replace the slot materials with the box-projected library versions
    name_to_index = {m.name: i for i, m in enumerate(unit.data.materials) if m}
    atlas = bpy.data.images.new("unit_atlas", args.atlas_size, args.atlas_size, alpha=False)
    for i, m in enumerate(list(unit.data.materials)):
        slot = slot_of(m.name)
        if slot:
            unit.data.materials[i] = lib_mats[slot]

    # an image node in every source material is the bake target
    for mat in lib_mats.values():
        nodes = mat.node_tree.nodes
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = atlas
        nodes.active = tex

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.margin = 6

    bpy.ops.object.select_all(action="DESELECT")
    unit.select_set(True)
    bpy.context.view_layer.objects.active = unit
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"})

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    atlas.filepath_raw = str(out / "atlas_albedo.png")
    atlas.file_format = "PNG"
    atlas.save()
    (out / "atlas_meta.json").write_text(json.dumps({
        "unit": str(Path(args.glb).resolve()), "library": str(lib),
        "slots": sorted(lib_mats), "size": args.atlas_size,
        "bake": "DIFFUSE/COLOR only (no lighting)",
    }, indent=2) + "\n")
    print(f"BAKED atlas -> {out / 'atlas_albedo.png'}")


def stage_final(args):
    unit = import_unit(Path(args.glb).resolve())
    out = Path(args.out).resolve()
    albedo_path = out / "atlas_albedo.png"
    normal_path = out / "atlas_normal.png"
    rough_path = out / "atlas_roughness.png"
    metal_path = out / "atlas_metallic.png"
    if not albedo_path.exists():
        raise SystemExit(f"missing {albedo_path}; run --stage albedo first")

    def image(path: Path, non_colour: bool):
        if not path.exists():
            return None
        img = bpy.data.images.load(str(path), check_existing=True)
        img.colorspace_settings.name = "Non-Color" if non_colour else "sRGB"
        return img

    albedo = image(albedo_path, False)
    normal = image(normal_path, True)
    rough = image(rough_path, True)
    metal = image(metal_path, True)

    # slot factors: painted armour is dielectric; trim is metal
    # painted/enamelled armour is dielectric; trim is metal but not a mirror —
    # full metalness renders black without an environment map, which the review
    # render does not have and the Three.js scene may not have either.
    factors = {
        "armour_primary": (0.10, 0.55), "armour_secondary": (0.18, 0.50),
        "metal_trim": (0.55, 0.45), "underlayer": (0.02, 0.78),
    }

    old = [m.name for m in unit.data.materials]
    old_slot = {i: slot_of(n) for i, n in enumerate(old)}
    old_per_poly = [p.material_index for p in unit.data.polygons]
    unit.data.materials.clear()
    for m in list(bpy.data.materials):
        if m.users == 0:
            bpy.data.materials.remove(m)
    index = {}
    for slot in SLOTS:
        mat = bpy.data.materials.new(slot)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = albedo
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if normal:
            nm = nt.nodes.new("ShaderNodeTexImage")
            nm.image = normal
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(nm.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        metallic, roughness = factors.get(slot, (0.0, 0.6))
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        index[slot] = len(unit.data.materials)
        unit.data.materials.append(mat)

    # remap faces by the slot name they carried before the rebuild: the material
    # order is not guaranteed to match SLOTS.
    remap = {i: index[slot] for i, slot in old_slot.items() if slot in index}
    for poly, old_idx in zip(unit.data.polygons, old_per_poly):
        poly.material_index = remap.get(old_idx, 0)

    (out / "final_meta.json").write_text(json.dumps({
        "slots": SLOTS, "textures": [p.name for p in
                                     (albedo_path, normal_path, rough_path, metal_path) if p.exists()],
    }, indent=2) + "\n")

    bpy.ops.object.select_all(action="DESELECT")
    unit.select_set(True)
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    for a in armatures:
        a.select_set(True)
    bpy.context.view_layer.objects.active = armatures[0] if armatures else unit
    dest = out / "unit_textured.glb"
    bpy.ops.export_scene.gltf(filepath=str(dest), use_selection=True,
                              export_format="GLB", export_yup=True,
                              export_image_format="AUTO",
                              export_animations=True,
                              export_animation_mode="ACTIONS",
                              export_anim_slide_to_zero=True)
    print(f"EXPORTED {dest}")


def main():
    args = parse_args()
    clear_scene()
    if args.stage == "albedo":
        if not args.library:
            raise SystemExit("--library is required for --stage albedo")
        stage_albedo(args)
    else:
        stage_final(args)


main()
