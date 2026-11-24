"""dow2_env_import.py — import one shipped DoW2 environment prop and export it as a static GLB.

The unit pipeline poses clips on an armature; a map prop is a static model. The assembly is still the
community add-on's (it builds the object, resolves the materials from the model's own `MTRL` chunks and
reads the shipped textures), and the same rules apply: prune the damage states and extra LoDs the
add-on imports, and export the materials opaque so a prop does not render see-through.

Run inside Blender:
  blender -b -P tools/blender/dow2_env_import.py -- --model <prop.model> --out <dest.glb> --name <id>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]

_ap = argparse.ArgumentParser()
_ap.add_argument("--model", required=True)
_ap.add_argument("--out", required=True)
_ap.add_argument("--name", required=True)
A = _ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

if "dow2_tools" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="dow2_tools")

for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob, do_unlink=True)

bpy.ops.import_scene.dow2_model(filepath=A.model, merge=False, reset_scene=False)

# the add-on imports every damage state and every LoD; the game draws one of each (see
# docs/DOW2_COMMUNITY_TOOLCHAIN.md — the same rule the units use)
groups, lods = {}, {}
keep_lod = 0
for ob in list(bpy.data.objects):
    if ob.type != "MESH":
        continue
    group = str(ob.get("dow2_group", "healthy"))
    level = int(ob.get("dow2_lod", 0))
    groups[group] = groups.get(group, 0) + 1
    lods[level] = lods.get(level, 0) + 1
keep_lod = min((int(o.get("dow2_lod", 0)) for o in bpy.data.objects
                if o.type == "MESH" and str(o.get("dow2_group", "healthy")) == "healthy"), default=0)
for ob in list(bpy.data.objects):
    if ob.type != "MESH":
        continue
    if str(ob.get("dow2_group", "healthy")) != "healthy" or int(ob.get("dow2_lod", 0)) != keep_lod:
        bpy.data.objects.remove(ob, do_unlink=True)
print(f"STATES {groups} LODS {lods} -> kept healthy/lod{keep_lod}")

# materials opaque unless the source declares a cutout (identical rule to the unit build)
alpha = {"opaque": 0, "cutout": 0}
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.startswith("relic."):
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    socket = bsdf.inputs["Alpha"]
    if bool(mat.get("dow2_alphaTest", False)) and socket.is_linked:
        clip = nodes.new("ShaderNodeMath")
        clip.operation = "ROUND"
        links.new(socket.links[0].from_socket, clip.inputs[0])
        links.new(clip.outputs[0], socket)
        alpha["cutout"] += 1
    else:
        for link in list(socket.links):
            links.remove(link)
        socket.default_value = 1.0
        alpha["opaque"] += 1
    mat.use_backface_culling = True
print(f"MATERIALS alpha: {alpha['opaque']} opaque, {alpha['cutout']} cutout")

# ---------------------------------------------------------------- a diffuse the add-on cannot find
# Some shipped pieces have no `_dif` of their own: the material names a shared atlas, or the only
# diffuse on disk belongs to a sibling build of the same geometry (`desert_building_sb_threeslot`
# ships its texture only as `desert_building_sb_threeslot_tarp_dif.dds`). The add-on then wires no
# image at all, the GLB carries `baseColorFactor 0.8` and no texture, and the piece renders as a
# cream slab in the middle of an otherwise textured place.
#
# The substitute is chosen by measurement, not by hope: the candidate whose file name shares the most
# tokens with the material's own name wins, and every substitution is printed so a wrong pick is
# visible in the build log rather than inferred from a render.
def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().replace("-", "_").split("_") if t and not t.isdigit()}


def _diffuse_candidates() -> list:
    model = Path(A.model)
    stem, parent = model.stem, model.parent
    found = [parent / f"{stem}_dif.dds"]
    found.extend(sorted(parent.glob(f"{stem}*_dif.dds")))
    # A sibling build of the same geometry sits beside the model's own directory, not inside it:
    # `buildings/desert_building_sb_threeslot_tarp/` next to `buildings/desert_building_sb_threeslot/`.
    # Globbing inside the model's directory found nothing and the fallback silently gave up.
    found.extend(sorted(parent.parent.glob(f"{stem}_*/{stem}_*_dif.dds")))
    found.extend(sorted(parent.parent.glob(f"{stem}_*/*_dif.dds")))
    # A shared atlas lives in one of the archive roots (`sga_art/000_data`, `000_extra`, ...), and a
    # model in one root reads the atlas from another. Walk the art root and take every shared atlas.
    roots = [parent, *parent.parents]
    # The archive roots (`sga_art/000_data`, `000_extra`, ...) sit above `DATA/art`, so the directory
    # that holds them is found by looking for `000_*` children -- not by looking for `world_objects`,
    # which is one level too deep and left a model in `000_extra` with no atlas at all.
    archive_root = next((a for a in roots if any(a.glob("000_*"))), None)
    if archive_root is not None:
        for archive in sorted(archive_root.glob("000_*")):
            shared = archive / "DATA" / "art" / "world_objects" / "shared_textures" / "base"
            if shared.is_dir():
                found.extend(sorted(shared.glob("*_dif.dds")))
    seen, out = set(), []
    for f in found:
        if f.is_file() and f not in seen:
            seen.add(f)
            out.append(f)
    return out


dif_fallback = {}
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.startswith("relic."):
        continue
    if any(n.type == "TEX_IMAGE" and n.image and "_dif" in (n.image.name or "").lower()
           for n in mat.node_tree.nodes):
        continue
    want = _tokens(mat.name)
    best, best_score = None, 0
    stem = Path(A.model).stem
    for cand in _diffuse_candidates():
        # A sibling build of the same geometry is the strongest evidence there is, whatever the
        # material is called: `desert_building_sb_threeslot` names its material `new_healthy`, which
        # shares no token with `desert_building_sb_threeslot_tarp_dif`, and the token score alone
        # rejected the only correct texture on disk.
        score = 10 if cand.parent.name.startswith(stem) else 0
        score += len(want & _tokens(cand.stem.replace("_dif", "")))
        if score > best_score:
            best, best_score = cand, score
    if best is None:
        print(f"DIF_FALLBACK {mat.name} -> none")
        continue
    image = bpy.data.images.load(str(best), check_existing=True)
    node = mat.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    dif_fallback[mat.name] = (best.name, best_score)
    print(f"DIF_FALLBACK {mat.name} -> {best.name} (shared tokens {best_score})")
print(f"DIF_FALLBACK_TOTAL {len(dif_fallback)}")

# ---------------------------------------------------------------- albedo and PBR
# The add-on's node graph for the *building/prop* shaders does not survive the glTF mapping: measured
# on `metal_wall_low_01`, the exported base colour pointed at a combined image with mean rgb (0,0,0) —
# every prop rendered black — and the metallic-roughness slot pointed at DoW2's `_spc` specular colour
# map, giving `metallicFactor` 1.04 with no environment to reflect. DoW2's `_spc` is a specular colour,
# not glTF's metal/rough pair, so it is not a faithful input. The albedo is wired from the shipped
# diffuse (`_dif`) and the surface is given a neutral dielectric response, which is what the shipped
# material's diffuse reads as.
fixed = {"albedo": 0, "flat": 0}
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.startswith("relic."):
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    dif = next((n for n in nodes
                if n.type == "TEX_IMAGE" and n.image and n.image.name.lower().endswith("_dif")), None)
    if dif is None:
        dif = next((n for n in nodes
                    if n.type == "TEX_IMAGE" and n.image and "_dif" in n.image.name.lower()), None)
    for link in list(bsdf.inputs["Base Color"].links):
        links.remove(link)
    if dif is not None:
        links.new(dif.outputs["Color"], bsdf.inputs["Base Color"])
        fixed["albedo"] += 1
    else:
        fixed["flat"] += 1
    for socket in ("Metallic", "Roughness"):
        for link in list(bsdf.inputs[socket].links):
            links.remove(link)
    bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Roughness"].default_value = 0.8
    # the normal map is a faithful input and is kept
print(f"PBR albedo from _dif: {fixed['albedo']}, flat colour: {fixed['flat']}")

# ---------------------------------------------------------------- shipped specular and occlusion
# The shipped material carries four maps per prop: `_dif` (albedo), `_nrm` (normal), `_spc` (specular
# colour) and `_ocl` (baked occlusion). Only the first two were exported and roughness was pinned at
# 0.8, so every prop rendered as matte cardboard next to the game it came from. The two missing maps
# are folded into the two slots a glTF dielectric can carry:
#   * `_ocl` is multiplied into the albedo. It is the shipped baked occlusion term, and baking it into
#     the diffuse is what gives a prop contact shading without needing a second UV set.
#   * `_spc` becomes the roughness map: bright specular is a smooth surface, dark specular is rough.
#     The shipped `_spc` is a specular *colour*, not glTF's metal/rough pair, so its luminance is the
#     honest input for roughness and metallic stays 0 (dielectric), which is what these surfaces are.
def find_image(suffix: str):
    """The image for this prop, preferring the one named after the model.

    A shipped material can carry a generic name (`08 - default`) that several props share, and the
    add-on then loads several props' textures into the same file. Taking the first match picked another
    prop's diffuse: measured on the city kit, `banner_post_01` rendered violet because it sampled a
    shared atlas instead of its own. The model's own stem is the evidence for which one is its own.
    """
    stem = Path(A.model).stem.lower()
    candidates = []
    for image in bpy.data.images:
        name = (image.name or "").lower()
        if not (name.endswith(suffix) or f"{suffix}." in name):
            continue
        candidates.append(image)
    if not candidates:
        return None
    for image in candidates:
        if (image.name or "").lower().startswith(stem):
            return image
    return candidates[0]


def combine_maps(diffuse, occlusion, specular, name: str, base_roughness: float = 0.7):
    """Return (albedo_image, roughness_image) as new Blender images, or None when there is nothing to do."""
    if diffuse is None:
        return None
    w, h = diffuse.size
    if not w or not h:
        return None
    dif_px = list(diffuse.pixels)
    ocl_px = list(occlusion.pixels) if occlusion is not None and tuple(occlusion.size) == (w, h) else None
    spc_px = list(specular.pixels) if specular is not None and tuple(specular.size) == (w, h) else None
    if ocl_px is None and spc_px is None:
        return None
    albedo = bpy.data.images.new(f"{name}_albedo_ao", width=w, height=h, alpha=True)
    rough = bpy.data.images.new(f"{name}_roughness", width=w, height=h, alpha=True)
    out_a = [0.0] * len(dif_px)
    out_r = [0.0] * len(dif_px)
    for i in range(0, len(dif_px), 4):
        r, g, b, a = dif_px[i], dif_px[i + 1], dif_px[i + 2], dif_px[i + 3]
        if ocl_px is not None:
            # The shipped occlusion map is an *ambient* term: the engine multiplies it into ambient
            # light, not into the diffuse texture. Baking it into the albedo double-darkens — measured
            # on the props the demo shows, `building_barricade_sb_block_01` shipped at 42/255 came out at
            # 26/255 and `wall_ruined_concrete_2story_04` at 40 -> 27, a 30% loss that crushed the
            # mid-tones into black patches. It is applied here at a quarter strength as a hint only.
            ao = 0.92 + 0.08 * ocl_px[i]
            r, g, b = r * ao, g * ao, b * ao
        out_a[i], out_a[i + 1], out_a[i + 2], out_a[i + 3] = r, g, b, a
        # roughness: 1 - luminance(specular), squeezed so a dielectric keeps a believable floor and the
        # brightest shipped specular (bare metal, glass) still reads as smooth rather than a mirror
        # The shipped specular map is mostly dark on diffuse surfaces, so roughness cannot be read
        # from it alone: the material's own gloss is the base (DoW2 ships glossValue, 0.3 for building
        # shaders) and a bright specular pixel pulls the surface smoother. Reading it the other way
        # round made every prop rougher than the 0.8 it replaced.
        if spc_px is not None:
            lum = 0.2126 * spc_px[i] + 0.7152 * spc_px[i + 1] + 0.0722 * spc_px[i + 2]
            value = max(0.12, min(0.95, base_roughness - lum * 0.6))
        else:
            value = base_roughness
        out_r[i] = value
        out_r[i + 1] = value
        out_r[i + 2] = value
        out_r[i + 3] = 1.0
    albedo.pixels = out_a
    rough.pixels = out_r
    for image in (albedo, rough):
        image.pack()
    return albedo, rough


spec_fixed = {"albedo_ao": 0, "roughness": 0}
for mat in bpy.data.materials:
    if not mat.use_nodes or not mat.name.startswith("relic."):
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    diffuse = find_image("_dif")
    occlusion = find_image("_ocl")
    specular = find_image("_spc")
    # DoW2's building shader ships glossValue (0.3 in the add-on's preset); its complement is the
    # surface's base roughness before the specular map is applied
    gloss = 0.3
    for node in nodes:
        if node.type == "BSDF_PRINCIPLED" and "Gloss" in node.name:
            gloss = float(node.get("glossValue", gloss))
    made = combine_maps(diffuse, occlusion, specular, mat.name.replace(".", "_"), 1.0 - gloss)
    if made is None:
        continue
    albedo_img, rough_img = made
    for link in list(bsdf.inputs["Base Color"].links):
        links.remove(link)
    albedo_node = nodes.new("ShaderNodeTexImage")
    albedo_node.image = albedo_img
    albedo_node.image.colorspace_settings.name = "sRGB"
    links.new(albedo_node.outputs["Color"], bsdf.inputs["Base Color"])
    rough_node = nodes.new("ShaderNodeTexImage")
    rough_node.image = rough_img
    rough_node.image.colorspace_settings.name = "Non-Color"
    links.new(rough_node.outputs["Color"], bsdf.inputs["Roughness"])
    if occlusion is not None:
        spec_fixed["albedo_ao"] += 1
    if specular is not None:
        spec_fixed["roughness"] += 1
print(f"SHIPPED MAPS baked: albedo x occlusion {spec_fixed['albedo_ao']}, roughness from specular {spec_fixed['roughness']}")

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit(f"{A.name}: the model imported no geometry")
lo = Vector((1e9, 1e9, 1e9))
hi = Vector((-1e9, -1e9, -1e9))
tris = 0
for ob in meshes:
    ob.data.calc_loop_triangles()
    tris += len(ob.data.loop_triangles)
    for corner in ob.bound_box:
        world = ob.matrix_world @ Vector(corner)
        for i in range(3):
            lo[i] = min(lo[i], world[i])
            hi[i] = max(hi[i], world[i])
size = hi - lo
print(f"SIZE {size.x:.2f},{size.y:.2f},{size.z:.2f}")
print(f"TRIS {tris}")
print(f"GROUND {lo.z:.2f}..{hi.z:.2f}")

# sit the prop on the ground plane: the map page places props by their base, so the origin is moved to
# the model's lowest point on Z (Blender is Z-up; the glTF export converts)
for ob in meshes:
    ob.location.z -= lo.z
bpy.context.view_layer.update()

dest = Path(A.out)
dest.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(dest), export_format="GLB", use_selection=True,
                          export_animations=False, export_yup=True)
print(f"EXPORTED {dest}")
