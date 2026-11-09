#!/usr/bin/env python3
"""build_blender_library.py — assemble the generated material library into a
Blender .blend that artists and agents can link or append into any scene.

Reads every built item under assets/materials/grimdark_scifi/<id>/ (albedo,
normal, roughness, metallic, emissive produced by tools/pbr/derive_maps.py) and
creates a material with:

  * Principled BSDF wired to the PBR maps (non-colour data flagged correctly)
  * BOX (triplanar) projection so it works on image-to-3D meshes with no or
    coarse UVs — no manual unwrap needed to get a textured read
  * faction-tagged collection per material, so linking the .blend gives a clean
    per-faction palette

Output: assets/materials/grimdark_scifi/grimdark_scifi.blend

Usage:
    blender -b -P tools/pbr/build_blender_library.py
    blender -b -P tools/pbr/build_blender_library.py -- --scale 0.5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "assets" / "materials" / "grimdark_scifi"
PREFIX = "IOA_"


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0,
                    help="box-projection scale; 1.0 = one tile per metre")
    ap.add_argument("--only", help="build only items whose id contains this")
    ap.add_argument("--library", default=str(LIB),
                    help="library tree to build from (default: the shipped library)")
    return ap.parse_args(argv)


def clear_materials():
    for coll in (bpy.data.materials, bpy.data.images, bpy.data.node_groups):
        for item in list(coll):
            if item.users == 0:
                coll.remove(item)


def load_image(path: Path, non_colour: bool):
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = "Non-Color" if non_colour else "sRGB"
    return img


def build_material(item_dir: Path, meta: dict, scale: float):
    # one texture tile spans tile_m metres on the model; mapping scale is the
    # reciprocal, so the material has a real-world physical size
    tile_m = float(meta.get("tile_m") or 1.0)
    scale = scale / max(tile_m, 1e-3)
    name = PREFIX + item_dir.name
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    coord = nt.nodes.new("ShaderNodeTexCoord")
    coord.location = (-900, 0)
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (-700, 0)
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    def tex_node(filename, non_colour, y):
        path = item_dir / filename
        if not path.exists():
            return None
        node = nt.nodes.new("ShaderNodeTexImage")
        node.location = (-450, y)
        node.image = load_image(path, non_colour)
        node.projection = "BOX"
        node.projection_blend = 0.35
        nt.links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    albedo = tex_node("albedo.png", False, 300)
    if albedo:
        nt.links.new(albedo.outputs["Color"], bsdf.inputs["Base Color"])
    normal = tex_node("normal.png", True, 60)
    if normal:
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-150, 60)
        nt.links.new(normal.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    rough = tex_node("roughness.png", True, -180)
    if rough:
        nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])
    metal = tex_node("metallic.png", True, -420)
    if metal:
        nt.links.new(metal.outputs["Color"], bsdf.inputs["Metallic"])
    emissive = tex_node("emissive.png", False, -660)
    if emissive:
        nt.links.new(emissive.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 2.0

    if meta.get("kind") == "decal":
        mat.blend_method = "BLEND"
        mat.show_transparent_back = False

    # a library material has no object users; without a fake user Blender drops
    # zero-user datablocks on save and the .blend ships empty
    mat.use_fake_user = True

    # provenance for whoever opens the file later
    mat["ioa_id"] = meta.get("id", item_dir.name)
    mat["ioa_kind"] = meta.get("kind", "material")
    mat["ioa_faction"] = meta.get("faction", "shared")
    mat["ioa_source_prompt"] = meta.get("prompt", "")
    return mat


def main():
    args = parse_args()
    lib = Path(args.library)
    clear_materials()
    if not lib.exists():
        raise SystemExit(f"no library at {lib} — run tools/pbr/derive_maps.py first")

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"

    built = 0
    for item_dir in sorted(p for p in lib.iterdir() if p.is_dir() and (p / "albedo.png").exists()):
        if args.only and args.only not in item_dir.name:
            continue
        meta_path = item_dir / "meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        mat = build_material(item_dir, meta, args.scale)
        built += 1
        print(f"  {mat.name}")

    out = lib / "grimdark_scifi.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    # now that the file has a location, relative image paths resolve on any box
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=str(out), compress=True)
    print(f"built {built} material(s) -> {out}")


if __name__ == "__main__":
    main()
