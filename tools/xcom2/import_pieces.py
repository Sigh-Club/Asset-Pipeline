#!/usr/bin/env python3
"""Import the reference game's own environment pieces into our kit.

Why this exists: the board work kept reproducing the reference's *numbers* while its *parts* were
missing, so every street was built from another game's props and read as a different place. This tool
takes the reference's shipped pieces (the ones its own plots are assembled from), exports them with UE
Viewer, converts them to glTF-binary with Blender, and writes kit entries with the reference's own
metadata: its cover class (`locov` / `hicov` in the file name is its cover system, not our invention) and
its footprint (`1x1`, `2x1` tiles).

Requirements, both already on this machine:
  * UE Viewer at `~/tools/umodel/umodel` (Linux build; it needs a 32-bit libpng12, which `run_umodel`
    below supplies from `~/tools/umodel/lib`)
  * `blender` on PATH for the glTF -> GLB conversion and the bounds measurement

Usage:
    python3 tools/xcom2/import_pieces.py --list                      # what is available
    python3 tools/xcom2/import_pieces.py --export citycbench_locov_2x1_a --export citycenteratm_locov_1x1a
    python3 tools/xcom2/import_pieces.py --export-matching 'locov' --limit 20
    python3 tools/xcom2/import_pieces.py --write-kit                 # merge what is imported into the kit

The pieces land in `<game>/frontend/public/assets/models/xcom/<name>.glb` with a sidecar JSON, and
`--write-kit` adds them to `env_kit.json` under the biome they were filed in.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GAME = ROOT.parent / "Imperium-of-Ash"
ASSETS = GAME / "frontend/public/assets"
OUT_DIR = ASSETS / "models/xcom"
UMODEL = Path.home() / "tools/umodel/umodel"
UMODEL_LIB = Path.home() / "tools/umodel/lib"

# The reference's own cover vocabulary, in its own file names. `locov`/`hicov` is its low/high cover
# classification and `NxM` is the footprint in tiles; both come from the asset name, not from us.
COVER_RE = re.compile(r"(lo|hi|cov)cov", re.I)
FOOT_RE = re.compile(r"(\d)x(\d)")

# Where the shipped pieces live, per game. The cooked console content is one package per piece.
CANDIDATE_ROOTS = [
    Path("/run/media/talzanar/games/SteamLibrary/steamapps/common/XCOM 2/share/data/xcomgame/cookedpcconsole"),
    Path("/run/media/talzanar/games/SteamLibrary/steamapps/common/XCOM 2 SDK/XComGame/Content"),
]


def game_root() -> Path | None:
    for root in CANDIDATE_ROOTS:
        if root.exists():
            return root
    return None


def run_umodel(args: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{UMODEL_LIB}:{env.get('LD_LIBRARY_PATH', '')}"
    return subprocess.run([str(UMODEL), *args], capture_output=True, text=True, env=env)


def packages(pattern: str | None, limit: int) -> list[Path]:
    root = game_root()
    if root is None:
        return []
    found = []
    for path in sorted(root.rglob("*.upk")):
        if pattern and not re.search(pattern, path.stem, re.I):
            continue
        found.append(path)
        if len(found) >= limit:
            break
    return found


def cover_of(name: str) -> str | None:
    m = COVER_RE.search(name)
    if not m:
        return None
    return {"lo": "low", "hi": "high"}.get(m.group(1).lower())


def footprint_of(name: str) -> tuple[int, int] | None:
    m = FOOT_RE.search(name)
    return (int(m.group(1)), int(m.group(2))) if m else None


BLENDER_SCRIPT = r"""
import bpy, json, sys, glob
from pathlib import Path
src_list, dst, side, tex_root = sys.argv[-5], sys.argv[-4], sys.argv[-3], sys.argv[-2]
limit = int(sys.argv[-1]) if sys.argv[-1].isdigit() else 256
bpy.ops.wm.read_factory_settings(use_empty=True)
# A shipped piece is a *package*, and a package holds several meshes (a road module carries its surface,
# kerbs and markings as separate meshes). Exporting only the biggest one produced a 0.94 m "road" where
# the module is 24 m: every mesh in the package is part of the piece.
for src in [p for p in src_list.split('|') if p]:
    bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs:
    sys.exit('no mesh in ' + src)
import mathutils
lo = mathutils.Vector((1e9, 1e9, 1e9)); hi = mathutils.Vector((-1e9, -1e9, -1e9)); tris = 0
for o in objs:
    o.data.calc_loop_triangles(); tris += len(o.data.loop_triangles)
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        lo = mathutils.Vector((min(lo[i], w[i]) for i in range(3)))
        hi = mathutils.Vector((max(hi[i], w[i]) for i in range(3)))
# UE Viewer writes the piece's textures beside the mesh but its glTF writer drops them, so the piece
# arrives as grey geometry. The albedo is the shipped DIF texture: relink it here, and the GLB carries
# the piece's own look rather than a placeholder.
# UE Viewer's glTF writer drops textures, so a piece arrives as grey geometry. It does write each
# material as a `.mat` beside the meshes, and that file names the exact diffuse the material uses:
#   Diffuse=CharredDrywalll_DIF
# Guessing by file name instead (the first version did) put a UV-helper atlas on every wall, which is why
# an imported kit rendered as a rainbow.
tex_root_path = Path(tex_root)
mats = {p.stem: p for p in tex_root_path.rglob('*.mat')}
tex = {p.stem: p for p in tex_root_path.rglob('*.png')}

def albedo_for(mat_name):
    # Blender renames duplicate materials with a numeric suffix (`WLD_BrickA_Brown.001`); the shipped
    # material is the unsuffixed one.
    import re as _re
    mat = mats.get(_re.sub(r'\.\d+$', '', mat_name or ''))
    if mat is None:
        return None
    diffuse = ''
    for line in mat.read_text(errors='ignore').splitlines():
        if line.startswith('Diffuse='):
            diffuse = line.split('=', 1)[1].strip()
            break
    if not diffuse or diffuse.lower().startswith('uv_mapping'):
        return None
    return tex.get(diffuse)

def material_for(mat_name, img):
    mat = bpy.data.materials.new(mat_name or 'piece')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if img is not None:
        if max(img.size) > limit:
            img.scale(min(limit, img.size[0]), min(limit, img.size[1]))
        node = mat.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = img
        mat.node_tree.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
    else:
        bsdf.inputs['Base Color'].default_value = (0.45, 0.45, 0.47, 1)
    return mat

for o in objs:
    slots = [m for m in o.data.materials if m]
    built = []
    for m in slots:
        img = bpy.data.images.load(str(albedo_for(m.name))) if albedo_for(m.name) else None
        built.append(material_for(m.name, img))
    if built:
        o.data.materials.clear()
        for m in built:
            o.data.materials.append(m)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', use_selection=True)
size = [round(hi[i]-lo[i], 3) for i in range(3)]
Path(side).write_text(json.dumps({'size': size, 'tris': tris, 'min': [round(v,3) for v in lo]}))
"""


def convert(files: list[Path], dst: Path, tex_root: Path, tex: int = 256) -> dict | None:
    side = dst.with_suffix('.json')
    script = Path(tempfile.mkdtemp()) / "conv.py"
    script.write_text("import json\nfrom pathlib import Path\n" + BLENDER_SCRIPT)
    proc = subprocess.run(
        ["blender", "-b", "--python", str(script), "--", "|".join(str(f) for f in files), str(dst),
         str(side), str(tex_root), str(tex)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not dst.exists():
        return None
    try:
        return json.loads(side.read_text())
    except Exception:
        return None


def export_split(pkg: Path, biome: str, match: str | None = None, tex: int = 256) -> list[dict]:
    """Export every mesh in a *kit* package as its own piece.

    A kit package is a sheet: `bldgkit_citycenter_sf` holds dozens of walls, doors and windows laid out
    side by side, so merging it gives one 13 m slab. Each mesh in it is a part, and a part is what a plot
    is assembled from.
    """
    root = game_root()
    if root is None:
        return []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        rel = pkg.relative_to(root.parent.parent)
        run_umodel([f"-path={root.parent.parent}", "-game=xcom2", "-gltf", "-png", "-export",
                    f"-out={tmp}", str(rel)])
        for g in sorted(Path(tmp).rglob("*.gltf")):
            if match and not re.search(match, g.stem, re.I):
                continue
            name = f"{pkg.stem}__{g.stem}"
            entry = convert([g], OUT_DIR / f"{name}.glb", Path(tmp), tex)
            if entry is None:
                continue
            meta = {
                "name": name, "source": "xcom2", "package": str(pkg),
                "url": f"/assets/models/xcom/{name}.glb", "biome": biome,
                "cover": cover_of(g.stem), "footprint_tiles": footprint_of(g.stem),
                "size": entry["size"], "tris": entry["tris"],
            }
            (OUT_DIR / f"{name}.json").write_text(json.dumps(meta, indent=1))
            made.append(meta)
    return made


def export_piece(pkg: Path, biome: str) -> dict | None:
    root = game_root()
    if root is None:
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rel = pkg.relative_to(root.parent.parent)
        proc = run_umodel([
            f"-path={root.parent.parent}", "-game=xcom2", "-gltf", "-png", "-export",
            f"-out={tmp}", str(rel),
        ])
        gltfs = sorted(Path(tmp).rglob("*.gltf"))
        if not gltfs:
            return None
        # the whole package is the piece
        best = convert(sorted(Path(tmp).rglob("*.gltf")), OUT_DIR / f"{pkg.stem}.glb", Path(tmp))
        if best is None:
            return None
        meta = {
            "name": pkg.stem,
            "source": "xcom2",
            "package": str(pkg),
            "url": f"/assets/models/xcom/{pkg.stem}.glb",
            "biome": biome,
            "cover": cover_of(pkg.stem),
            "footprint_tiles": footprint_of(pkg.stem),
            "size": best["size"],
            "tris": best["tris"],
        }
        (OUT_DIR / f"{pkg.stem}.json").write_text(json.dumps(meta, indent=1))
        return meta


def write_kit() -> int:
    kit_path = ASSETS / "models/env/env_kit.json"
    kit = json.loads(kit_path.read_text())
    known = {p["name"] for p in kit["props"]}
    added = 0
    for side in sorted(OUT_DIR.glob("*.json")):
        meta = json.loads(side.read_text())
        if meta["name"] in known:
            continue
        kit["props"].append({
            "name": meta["name"],
            "biome": meta.get("biome") or "urban",
            "placements": 0,
            "model": meta.get("package", ""),
            "url": meta["url"],
            "size": meta["size"],
            "tris": meta["tris"],
            "textured": True,
            "source": "xcom2",
            "cover": meta.get("cover"),
            "footprint_tiles": meta.get("footprint_tiles"),
        })
        added += 1
    if added:
        kit_path.write_text(json.dumps(kit, indent=1))
    return added


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--export", action="append", default=[])
    ap.add_argument("--export-matching", default=None)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--biome", default="urban")
    ap.add_argument("--write-kit", action="store_true")
    ap.add_argument("--split", action="store_true", help="export each mesh in a kit package as its own piece")
    ap.add_argument("--match", default=None, help="with --split, only meshes whose name matches this pattern")
    ap.add_argument("--tex", type=int, default=256, help="albedo size limit in pixels")
    args = ap.parse_args()

    if not UMODEL.exists():
        sys.exit(f"UE Viewer not found at {UMODEL}")
    root = game_root()
    if root is None:
        sys.exit("no reference-game content directory found")

    if args.list:
        for p in packages(args.export_matching, args.limit):
            print(f"{p.stem:52s} cover={cover_of(p.stem) or '-':5s} tiles={footprint_of(p.stem)}")
        return

    names = list(args.export)
    if args.export_matching:
        names += [p.stem for p in packages(args.export_matching, args.limit)]
    if not names and not args.write_kit:
        sys.exit("nothing to do: pass --export NAME, --export-matching PATTERN or --write-kit")

    for name in names:
        pkg = next(root.rglob(f"{name}.upk"), None) or next(root.rglob(f"{name}.umap"), None)
        if pkg is None:
            print(f"  {name}: not found")
            continue
        if args.split:
            made = export_split(pkg, args.biome, args.match, args.tex)
            if not made:
                print(f"  {name}: export failed")
            for meta in made:
                print(f"  {meta['name']}: {meta['size']} tris={meta['tris']}")
            continue
        meta = export_piece(pkg, args.biome)
        if meta is None:
            print(f"  {name}: export failed")
        else:
            print(f"  {name}: {meta['size']} tris={meta['tris']} cover={meta['cover']}")

    if args.write_kit:
        print(f"kit: {write_kit()} pieces added")


if __name__ == "__main__":
    main()
