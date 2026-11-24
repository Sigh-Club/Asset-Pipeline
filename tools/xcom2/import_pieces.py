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
src, dst, side = sys.argv[-4], sys.argv[-3], sys.argv[-2]
tex_root = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs:
    sys.exit('no mesh in ' + src)
# UE Viewer writes the piece's textures beside the mesh but its glTF writer drops them, so the piece
# arrives as grey geometry. The albedo is the shipped DIF texture: relink it here, and the GLB carries
# the piece's own look rather than a placeholder.
albedo = None
piece = Path(src).parent.name.lower()
cands = [p for p in glob.glob(tex_root + '/**/*.png', recursive=True)
         if 'dif' in Path(p).stem.lower() and 'msk' not in Path(p).stem.lower()]
def score(p):
    stem = Path(p).stem.lower()
    shared = len(set(piece.split('_')) & set(stem.split('_')))
    return (shared, Path(p).stat().st_size)
if cands:
    albedo = max(cands, key=score)
if albedo:
    img = bpy.data.images.load(albedo)
    # a piece does not need a 4k atlas: 512 is enough at the tactical camera and keeps the GLB small
    if max(img.size) > 512:
        img.scale(min(512, img.size[0]), min(512, img.size[1]))
    mat = bpy.data.materials.new('piece_albedo')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = img
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    for o in objs:
        o.data.materials.clear()
        o.data.materials.append(mat)
import mathutils
lo = mathutils.Vector((1e9, 1e9, 1e9)); hi = mathutils.Vector((-1e9, -1e9, -1e9)); tris = 0
for o in objs:
    o.data.calc_loop_triangles(); tris += len(o.data.loop_triangles)
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        lo = mathutils.Vector((min(lo[i], w[i]) for i in range(3)))
        hi = mathutils.Vector((max(hi[i], w[i]) for i in range(3)))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', use_selection=True)
size = [round(hi[i]-lo[i], 3) for i in range(3)]
Path(side).write_text(json.dumps({'size': size, 'tris': tris, 'min': [round(v,3) for v in lo]}))
"""


def convert(gltf: Path, dst: Path, tex_root: Path) -> dict | None:
    side = dst.with_suffix('.json')
    script = Path(tempfile.mkdtemp()) / "conv.py"
    script.write_text("import json\nfrom pathlib import Path\n" + BLENDER_SCRIPT)
    proc = subprocess.run(
        ["blender", "-b", "--python", str(script), "--", str(gltf), str(dst), str(side), str(tex_root)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not dst.exists():
        return None
    try:
        return json.loads(side.read_text())
    except Exception:
        return None


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
        # the piece is the biggest mesh in the package (a package can carry several sub-meshes)
        best, best_tris = None, -1
        for g in gltfs:
            entry = convert(g, OUT_DIR / f"{pkg.stem}.glb", Path(tmp))
            if entry is None:
                continue
            if entry["tris"] > best_tris:
                best, best_tris = entry, entry["tris"]
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
        meta = export_piece(pkg, args.biome)
        if meta is None:
            print(f"  {name}: export failed")
        else:
            print(f"  {name}: {meta['size']} tris={meta['tris']} cover={meta['cover']}")

    if args.write_kit:
        print(f"kit: {write_kit()} pieces added")


if __name__ == "__main__":
    main()
