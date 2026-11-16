#!/usr/bin/env python3
"""bake_pixel_atlas.py — texel-grid UV, baked atlas and palette-locked material
build for the `pixel_3d` profile.

Three stages, because the palette lock must run in system Python (Blender's
bundled PIL is not dependable) and because baking must be a separate GPU job:

    # 1. texel grid: uniform world-size texels, lattice-snapped UVs
    tools/blender_run.sh --job uv -- -b -P tools/blender/bake_pixel_atlas.py -- \
        --stage texel --glb <asset>.glb --out output/gen/<asset> --profile pixel_3d

    # 2. bake the box-projected library materials into that atlas (Cycles, colour only)
    tools/blender_run.sh --job bake -- -b -P tools/blender/bake_pixel_atlas.py -- \
        --stage albedo --glb <asset>_texel.glb --out ... --library <library.blend> \
        --faction iron_directorate --profile pixel_3d

    # 3. lock the atlas to the profile palette (system python)
    python3 tools/style/palette_lock.py <out>/atlas/atlas_albedo.png --profile pixel_3d \
        --dither bayer4 --out-dir <out>/atlas --suffix _pixel

    # 4. build palette-locked materials and export the GLB
    tools/blender_run.sh --job script -- -b -P tools/blender/bake_pixel_atlas.py -- \
        --stage final --glb <asset>_texel.glb --out ... --profile pixel_3d

The GLB that leaves stage 4 carries a 256 px palette atlas with nearest filtering
and no PBR maps — the pixel tier's material model (STYLE_RESEARCH §6).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "blender"))
import pixel_uv  # noqa: E402


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=("texel", "albedo", "final"))
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--id", help="asset id (default: glb stem)")
    ap.add_argument("--profile")
    ap.add_argument("--library", help="material library .blend (stage albedo)")
    ap.add_argument("--faction", default="iron_directorate",
                    help="faction prefix used to resolve bare slot names")
    ap.add_argument("--material-map", help="JSON {mesh material: library item id}")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--no-emission", action="store_true",
                    help="skip the emission atlas even if an emissive map exists")
    return ap.parse_args(argv)


def profile_block(profile_id: str | None) -> dict:
    if not profile_id:
        return {}
    spec = importlib.util.spec_from_file_location(
        "style_profiles", ROOT / "tools" / "style" / "profiles.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.load_config()
    resolved = mod.resolve(profile_id, cfg)
    errors = mod.validate(resolved, cfg)
    if errors:
        raise SystemExit("invalid profile: " + "; ".join(errors))
    return resolved


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_mesh(path: Path):
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    if not objs:
        raise SystemExit(f"no mesh in {path}")
    obj = max(objs, key=lambda o: len(o.data.polygons))
    bpy.context.view_layer.objects.active = obj
    return obj


def library_items_from(names, faction: str, mapping: dict | None) -> dict:
    """Mesh material name -> library item id."""
    out = {}
    for name in names:
        if mapping and name in mapping:
            out[name] = mapping[name]
        elif name.startswith("IOA_"):
            out[name] = name[4:]
        else:
            out[name] = f"{faction}__{name}"
    return out


def stage_texel(args, prof):
    obj = import_mesh(Path(args.glb).resolve())
    tex = prof.get("texture", {})
    report = pixel_uv.unwrap_and_grid(
        obj, float(tex.get("texel_world_m", 0.02)), int(tex.get("atlas_px", 256)))
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{args.id or Path(args.glb).stem}_texel.glb"
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.data.objects:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(dest), use_selection=True,
                              export_format="GLB", export_yup=True,
                              export_animations=True, export_animation_mode="ACTIONS",
                              export_anim_slide_to_zero=True)
    pixel_uv.write_report(out, report, {"source": str(Path(args.glb).resolve()),
                                        "texel_glb": str(dest)})
    print(f"TEXEL {dest}  density {report['implied_world_area_per_texel']} m2/texel "
          f"util {report['utilisation']:.1%} islands {report['islands']}")


PIXEL_SCALE = ROOT / "configs" / "materials" / "pixel_scale.json"


def apply_pixel_scale(mats: dict) -> dict:
    """Scale each library material's box projection for the pixel tier.

    A physically correct 30 cm buckle panel puts its features at ~3 texels on a
    2 cm grid, which locks to camouflage; at the pixel tier the same surface is
    read as larger panels (Boltgun's "impression of the object"). The multiplier
    is recorded data, not a code path.
    """
    if not PIXEL_SCALE.exists():
        return {}
    cfg = json.loads(PIXEL_SCALE.read_text()).get("materials", {})
    applied = {}
    for item_id, mat in mats.items():
        mult = float((cfg.get(item_id) or {}).get("world_size_multiplier", 1.0))
        if mult == 1.0:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "MAPPING":
                v = node.inputs["Scale"].default_value
                node.inputs["Scale"].default_value = (v[0] / mult, v[1] / mult, v[2] / mult)
                applied[item_id] = mult
                break
    return applied


def _load_library_materials(library: Path, item_ids: list[str]):
    prefix = "IOA_"
    with bpy.data.libraries.load(str(library), link=False) as (src, dst):
        wanted = [n for n in src.materials if any(n == prefix + i for i in item_ids)]
        dst.materials = wanted
    mats = {m.name.replace(prefix, ""): m for m in dst.materials if m}
    missing = [i for i in item_ids if i not in mats]
    if missing:
        raise SystemExit(f"library has no material for: {missing}")
    return mats


def _route_base_colour_to_emission(mat):
    """Temporarily wire the Principled base colour into an emission shader and
    return a function that restores the original surface link."""
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if bsdf is None or out is None:
        return lambda: None
    base = bsdf.inputs["Base Color"]
    src = base.links[0].from_socket if base.is_linked else None
    original = out.inputs["Surface"].links[0].from_socket \
        if out.inputs["Surface"].is_linked else None
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.0
    if src is not None:
        nt.links.new(src, em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = tuple(base.default_value)

    def restore():
        nt.links.new(original if original is not None else bsdf.outputs["BSDF"],
                     out.inputs["Surface"])
        nt.nodes.remove(em)

    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return restore


def _atlas_image(name: str, size: int):
    img = bpy.data.images.new(name, size, size, alpha=False)
    img.colorspace_settings.name = "sRGB"
    return img


def stage_albedo(args, prof):
    obj = import_mesh(Path(args.glb).resolve())
    out = Path(args.out).resolve()
    atlas_dir = out / "atlas"
    atlas_dir.mkdir(parents=True, exist_ok=True)
    size = int(prof.get("texture", {}).get("atlas_px", 256))
    mapping = json.loads(Path(args.material_map).read_text()) if args.material_map else None
    old_slots = [m.name if m else "" for m in obj.data.materials]
    items = library_items_from(old_slots, args.faction, mapping)
    # a GLB round-trip carries its own copies of the library materials under the
    # same names; loading the library would then append them as "name.001" and the
    # slot map would miss. Rename the imported placeholders out of the way first.
    for m in obj.data.materials:
        if m:
            m.name = "IMP_" + m.name
    lib = _load_library_materials(Path(args.library).resolve(), sorted(set(items.values())))
    scaled = apply_pixel_scale(lib)

    for i, name in enumerate(old_slots):
        if name in items:
            obj.data.materials[i] = lib[items[name]]

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = False
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    scene.render.bake.margin = max(2, size // 128)

    def bake(image, path: Path, albedo_pass: bool):
        restore = []
        for mat in lib.values():
            nodes = mat.node_tree.nodes
            tex = nodes.new("ShaderNodeTexImage")
            tex.image = image
            nodes.active = tex
            if albedo_pass:
                restore.append(_route_base_colour_to_emission(mat))
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        # an albedo bake must not be a DIFFUSE pass: every material in this
        # library is authored metallic, and a metal has no diffuse component, so
        # a DIFFUSE/COLOR bake writes black. Route base colour through emission
        # instead and bake EMIT (the exact albedo, independent of PBR response).
        bpy.ops.object.bake(type="EMIT")
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        for mat in lib.values():
            nodes = mat.node_tree.nodes
            for node in [n for n in nodes if n.type == "TEX_IMAGE" and n.image is image]:
                nodes.remove(node)
        for fn in restore:
            fn()

    albedo = _atlas_image("pixel_atlas_albedo", size)
    bake(albedo, atlas_dir / "atlas_albedo.png", albedo_pass=True)
    wrote = ["atlas_albedo.png"]

    has_emissive = not args.no_emission and any(
        any(n.type == "TEX_IMAGE" and n.image and
            ("emissiv" in n.image.name.lower() or "emission" in n.image.name.lower())
            for n in m.node_tree.nodes)
        for m in lib.values())
    if has_emissive:
        emit = _atlas_image("pixel_atlas_emission", size)
        bake(emit, atlas_dir / "atlas_emission.png", albedo_pass=False)
        wrote.append("atlas_emission.png")

    (atlas_dir / "atlas_meta.json").write_text(json.dumps({
        "asset": args.id, "atlas_px": size,
        "sources": {k: v for k, v in items.items()},
        "pixel_world_size_multiplier": scaled,
        "files": wrote,
        "bake": "DIFFUSE/COLOR (+EMIT) only, lights off",
    }, indent=2) + "\n")
    print(f"BAKED {', '.join(wrote)} -> {atlas_dir}")


def _image_node(nt, image, non_colour=False, y=0):
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.interpolation = "Closest"   # a palette atlas must not be filtered
    node.extension = "EXTEND"
    node.location = (-450, y)
    if non_colour:
        image.colorspace_settings.name = "Non-Color"
    return node


def stage_final(args, prof):
    obj = import_mesh(Path(args.glb).resolve())
    out = Path(args.out).resolve()
    atlas_dir = out / "atlas"
    albedo_path = atlas_dir / "atlas_albedo_pixel.png"
    if not albedo_path.exists():
        raise SystemExit(f"missing {albedo_path}; lock the atlas with "
                         f"tools/style/palette_lock.py first")
    emission_path = atlas_dir / "atlas_emission_pixel.png"
    if not emission_path.exists():
        emission_path = atlas_dir / "atlas_emission.png"

    albedo = bpy.data.images.load(str(albedo_path), check_existing=True)
    emission = bpy.data.images.load(str(emission_path), check_existing=True) \
        if emission_path.exists() else None

    # one material for the whole pixel tier: palette albedo, optional emission
    mat = bpy.data.materials.new("pixel_palette")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Metallic"].default_value = 0.0
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    tex = _image_node(nt, albedo, y=200)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if emission:
        etex = _image_node(nt, emission, y=-150)
        nt.links.new(etex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0

    old_slots = [m.name if m else "" for m in obj.data.materials]
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0
    for poly in obj.data.polygons:
        poly.use_smooth = False

    dest = out / f"{args.id or Path(args.glb).stem}_pixel.glb"
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.data.objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=str(dest), use_selection=True,
                              export_format="GLB", export_yup=True,
                              export_image_format="AUTO",
                              export_animations=True,
                              export_animation_mode="ACTIONS",
                              export_anim_slide_to_zero=True)
    (out / "pixel_final_meta.json").write_text(json.dumps({
        "asset": args.id, "profile": args.profile,
        "materials": ["pixel_palette"], "replaced_slots": old_slots,
        "albedo": str(albedo_path), "emission": str(emission_path)
        if emission_path.exists() else None,
        "interpolation": "Closest", "shading": "flat",
    }, indent=2) + "\n")
    print(f"EXPORTED {dest}")


def main():
    args = parse_args()
    prof = profile_block(args.profile)
    clear_scene()
    if args.stage == "texel":
        stage_texel(args, prof)
    elif args.stage == "albedo":
        if not args.library:
            raise SystemExit("--library is required for --stage albedo")
        stage_albedo(args, prof)
    else:
        stage_final(args, prof)


main()
