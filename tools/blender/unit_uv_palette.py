"""unit_uv_palette.py — give an imported DoW2 body UVs and a palette atlas.

DoW2 `.model` geometry carries no TEXCOORD, so an imported body ships untextured and fails the
palette contract. This applies the pipeline's texel-grid unwrap and a flat faction-colour palette
atlas — the same treatment the weapons get — so the swapped units are contract-valid. The M2 PBR
rebuild replaces the flat colour with a real material.

Usage: blender -b -P unit_uv_palette.py -- --glb <unit.glb> --out <dir> --id <id> --colour 0xRRGGBB
"""
import argparse, sys
from pathlib import Path
import bpy

ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--id", required=True); ap.add_argument("--colour", default="0x6b6b6b")
ap.add_argument("--tones", help="comma-separated hex tones; fills the atlas in bands so the unit "
                "reads with the tonal range of its own DoW2 texture instead of one flat colour")
A = ap.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(Path(A.glb).resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import palette_uv

ATLAS = 512  # units are the hi class: the profile expects a 512 atlas
# Colour comes from the shipped palette, not an invented hex: an off-palette flat colour fails
# the palette contract (measured: 100% of atlas pixels off the grimdark_3d palette).
gpl = Path(__file__).resolve().parents[2] / "assets" / "palettes" / "grimdark_3d.gpl"
cols = []
if gpl.exists():
    for line in gpl.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            cols.append(tuple(int(x) / 255.0 for x in parts[:3]))
if cols:
    r, g, b = cols[sum(map(ord, A.colour)) % len(cols)]
else:
    hexv = A.colour.replace("0x", "").replace("#", "")
    r, g, b = (int(hexv[i:i+2], 16) / 255.0 for i in (0, 2, 4))
img = bpy.data.images.new("palette_atlas", width=ATLAS, height=ATLAS, alpha=False)
if A.tones:
    tones = []
    for t in A.tones.split(","):
        h = t.strip().replace("0x", "").replace("#", "")
        if len(h) == 6:
            tones.append(tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)))
    px = []
    for y in range(ATLAS):
        band = min(len(tones) - 1, y * len(tones) // ATLAS)
        px += [*tones[band], 1.0] * ATLAS
    img.pixels = px
else:
    img.pixels = [r, g, b, 1.0] * (ATLAS*ATLAS)
img.pack()

WEAPONS = ("lasgun","bolter","shuriken","shoota")
done = 0
for o in bpy.data.objects:
    if o.type != "MESH" or o.name.split(".")[0] in WEAPONS:
        continue
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True)
    # A large body (a 10 m2 marine) needs more texels than a 256 atlas packs, and the unwrap
    # raises SystemExit rather than returning. Escalate the atlas until the contract is met.
    for attempt in (ATLAS, 512, 1024):
        try:
            palette_uv.unwrap_and_grid(o, 0.02, attempt)
            if attempt != ATLAS:
                print(f"UV {o.name} needed a {attempt}px atlas")
            break
        except SystemExit as e:
            if attempt == 1024:
                print(f"UV {o.name} could not meet the density contract: {e}")
        except Exception as e:
            print("UV fail", o.name, e)
            break
    for slot in list(o.data.materials):
        o.data.materials.pop()
    mat = bpy.data.materials.new("palette_atlas"); mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
    tex.interpolation = "Closest"; tex.extension = "CLIP"
    if bsdf:
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.75
        bsdf.inputs["Metallic"].default_value = 0.0
    o.data.materials.append(mat)
    done += 1

arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm and arm.animation_data:
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1,0,0,0); pb.location = (0,0,0); pb.scale = (1,1,1)
out = Path(A.out); out.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=str(out/f"{A.id}.glb"), export_format="GLB",
                          use_selection=True, export_animations=True,
                          export_animation_mode="ACTIONS")
print(f"UV+PALETTE {A.id} bodies={done}")
