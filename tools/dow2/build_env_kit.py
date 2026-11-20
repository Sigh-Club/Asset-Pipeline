#!/usr/bin/env python3
"""build_env_kit.py — build the environment kit: shipped props and structures as GLBs for map making.

The unit pipeline builds a unit from its blueprint. A map prop is simpler: one shipped `.model`, no
rig, no clips. This resolves each prop to its model file, imports it with the community add-on (the
same assembly the units use, so the materials resolve the same way), prunes to the shipped healthy/LoD0
set, exports opaque and records the model's real footprint plus its shipped `.coverbox` volume — the
numbers a map generator needs to place cover deliberately instead of at random.

The selection is measured, not invented: `scenario_decode.py --aggregate` counts which props the
shipped maps actually place, per biome, so the kit is the props the game's own maps use most.

Usage:
  python3 tools/dow2/build_env_kit.py --art <sga root> --palette output/source_lab/biome_palette.json \
      --per-biome 8 --out ../Imperium-of-Ash/frontend/public/assets/models/env
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART_ENV = "DOW2_RETRIB"
# biomes whose props are actual map dressing (skies are backdrops, gameplay are markers, props are
# corpses, other is units and wrecks placed as scenery)
BUILD_BIOMES = ("desert", "ice", "jungle", "urban", "volcanic", "spacehulk", "military",
                "industrial", "ork", "tyranid", "chaos", "ruins")

# Structures are not in the biome palette (they are placed by the game's build rules, not as scenery),
# but a map needs them: bunkers, turrets, generators, bases. These are the shipped ones, by faction.
STRUCTURES = {
    "ig": ["ig_bunker", "ig_multilaser_turret", "ig_heavy_bolter_turret", "ig_plasma_generator",
           "ig_turret_emplacement", "ig_deployable_cover", "ig_heavy_missile_turret_emp"],
    "chaos": ["chaos_heavy_bolter_turret", "chaos_las_cannon_turret", "chaos_generator",
              "chaos_missile_launcher_turret", "chaos_shrine_khorne"],
    "ork": ["orky_turret", "orky_turret_base", "ork_generator", "waggh_banner"],
    "eldar": ["warp_generator", "webway_portal_beacon"],
    "tyranid": ["brood_nest_01", "hive_node", "cap_point_generators_tyranid", "mycetic_spore_land"],
    "marine": ["tarantula_heavy_bolter", "tarantula_missile_launcher", "sm_beacon"],
}
# Vista pieces: the horizon-scale props a combat board cannot hold (a 29 m tree, a cliff face). They
# are a separate layer so a map can be dressed at both scales.
VISTA = {
    "jungle": ["hedges", "tree_sb_huge_vines_01", "rock_pile_long_01", "plant_fern_01"],
    "desert": ["high_wall_03", "cliff_edge_01"],
    "volcanic": ["uplifted_rock_wall_01", "volcanic_edge_basaltcolumns_02"],
    "ice": ["rock_cover_03", "urban_supportwall_5m_01"],
    "spacehulk": ["viz_floor_panel_02"],
    "ruins": ["u_twisted_metal_01", "u_concrete_rubble_large_02"],
}


def art_root() -> Path:
    base = os.environ.get(ART_ENV)
    if not base:
        raise SystemExit(f"set {ART_ENV} to the unpacked DoW2 data")
    root = Path(base).expanduser()
    return root / "sga_art" if (root / "sga_art").is_dir() else root


_MODEL_INDEX: dict[str, list[Path]] = {}


def _model_index(root: Path) -> dict[str, list[Path]]:
    """Every shipped model keyed by a normalised stem, built once.

    A blueprint's name is not its model's file name: `lab_wall_02a` ships as
    `sh_labwall_02a.model` (measured, 1520 placements — the most-placed wall in the corpus), so an
    exact filename lookup silently drops the most useful props. Normalising to alphanumerics and
    matching by containment finds them.
    """
    key = str(root)
    if key not in _MODEL_INDEX:
        index: dict[str, list[Path]] = {}
        for model in root.rglob("*.model"):
            norm = "".join(ch for ch in model.stem.lower() if ch.isalnum())
            index.setdefault(norm, []).append(model)
        _MODEL_INDEX[key] = index
    return _MODEL_INDEX[key]


def model_for(root: Path, name: str) -> Path | None:
    hits = sorted(root.rglob(f"{name}.model"))
    if not hits:
        norm = "".join(ch for ch in name.lower() if ch.isalnum())
        index = _model_index(root)
        candidates = [m for stem, paths in index.items() if norm in stem for m in paths]
        if not candidates:
            return None
        hits = sorted(candidates, key=lambda p: (len(p.stem), len(str(p))))
    # prefer the model that is not a wreck/submit variant
    hits.sort(key=lambda p: ("wreck" in p.stem, "_submit" in p.stem, len(str(p))))
    return hits[0]


def coverbox_for(model: Path) -> dict | None:
    """The shipped cover volume beside a model: `offset` + `scale`, in metres.

    The file is plain text (`coverbox = { offset = {x,y,z}, scale = {x,y,z} }`). A prop without one
    provides no cover; a prop with one is a cover object and the box is the extent the game uses.
    """
    path = model.with_suffix(".coverbox")
    if not path.exists():
        return None
    text = path.read_text(errors="replace")
    out = {}
    for key in ("offset", "scale"):
        m = re.search(rf"{key}\s*=\s*\{{([^}}]*)\}}", text)
        if not m:
            continue
        values = {}
        for axis in ("x", "y", "z"):
            a = re.search(rf"{axis}\s*=\s*(-?[\d.]+)", m.group(1))
            if a:
                values[axis] = round(float(a.group(1)), 3)
        if values:
            out[key] = values
    return out or None


def model_size(model: Path) -> list[float] | None:
    """The model's own bounding box in metres, read from its geometry without importing it.

    The kit is a palette for a 2 m-tile combat grid, so a prop is chosen for its footprint as well as
    its frequency: a DoW2 map is hundreds of metres across and places 29 m trees, while a 15x12 combat
    board is 30x24 m. Reading the vertex stream directly is seconds faster than a Blender import and
    gives the number the palette needs.
    """
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "tools" / "dow2"))
        from chunky_mesh import extract_model
        models = extract_model(model)
    except Exception:
        return None
    points = [v for m in models for v in m["verts"]]
    if not points:
        return None
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return [round(hi[i] - lo[i], 2) for i in range(3)]


def board_scale(size: list[float], max_size: float) -> bool:
    """Is this model a board prop, or is it scenery?

    `size` is the model's own bounding box in its authored space, where the **third component is
    height** (measured: `roadside_marker_sb_healthy_02` is [1.34, 1.3, 6.24] and imports as a 6.24 m
    post). A flat `max(dimension)` test is wrong in both directions: it rejects a 10 m wall segment
    that is 0.5 m thick and would accept a 7 m boulder. The rule that matches a 48x40 m board:

      * height at most `max_size` — a board prop is not a tower;
      * a thin axis at most 3 m — walls, plates, barriers and fences belong on a board however long
        they are, and their length is capped at 2x the height;
      * otherwise every dimension at most `max_size`.
    """
    width, depth, height = (float(v) for v in size[:3])
    if min(width, depth, height) < 0.2:
        return False
    if height > max_size:
        return False
    # a wall is long by nature: `stone_support_wall_10m` measures 6.0 x 12.2 m on the ground and is
    # 3.6 m tall, and it is the wall a map is built from. Footprint is capped at 2.5x the height
    # budget, which keeps a 12 m wall and rejects a 27 m rock ridge.
    return max(width, depth) <= max_size * 2.5


# The gameplay art is the map's functional identity: capture points, resource drops, generators. They
# are placed by the game's own rules rather than as scenery, which is why they are not in the biome
# palettes — but they are the landmarks a board is built around (16 per map, measured).
# Proxies and spawn markers are invisible helper meshes in the engine, not landmarks: rendering them
# puts little boxes on the board where nothing should be.
GAMEPLAY_SKIP = ("invisible_", "move_blocker", "proxy", "starting_point")


def gameplay_entries(root: Path) -> list[dict]:
    """The shipped gameplay markers that are visible: capture points, drops, generators."""
    # the art root is a tree of archive extracts (`000_data/DATA/art/...`), not a single DATA folder
    # only `art/world_objects/gameplay` — the biome folders have their own `gameplay` subfolders full
    # of that biome's props, and taking those would pull in 1,500 entries instead of 20
    bases = sorted({p for p in root.rglob("gameplay")
                    if p.is_dir() and p.parent.name == "world_objects"})
    if not bases:
        return []
    entries = []
    seen: set[str] = set()
    models = sorted({m for base in bases for m in base.rglob("*.model")})
    for model in models:
        name = model.stem
        if name in seen or any(skip in name for skip in GAMEPLAY_SKIP):
            continue
        seen.add(name)
        entries.append({"name": name, "biome": "gameplay", "placements": 0})
    return entries


def structure_entries(root: Path) -> list[dict]:
    """The shipped structures, resolved to their models."""
    out = []
    for faction, names in STRUCTURES.items():
        for name in names:
            model = model_for(root, name)
            if model is None:
                print(f"  MISSING structure {faction}/{name}")
                continue
            out.append({"name": name, "biome": f"structure_{faction}", "placements": 0})
    return out


def vista_entries(root: Path) -> list[dict]:
    """The horizon-scale props, resolved to their models (their own layer, no size limit)."""
    out = []
    for biome, names in VISTA.items():
        for name in names:
            model = model_for(root, name)
            if model is None:
                print(f"  MISSING vista {biome}/{name}")
                continue
            out.append({"name": name, "biome": f"vista_{biome}", "placements": 0})
    return out


def select(palette: dict, per_biome: int, root: Path | None = None,
           max_size: float = 0.0, min_placements: int = 0) -> list[dict]:
    """Biome props for the kit. `per_biome` of 0 selects none, so the extra groups can be built
    alone (`--per-biome 0 --include-gameplay`)."""
    """The kit's prop list: the most-placed props per biome that fit a combat board.

    The scan walks the biome's frequency-ordered list rather than its head, because the top of a DoW2
    map's prop list is cliffs and 29 m trees — a 15x12 board at 2 m tiles is 30x24 m, so those are
    vista pieces, not cover. A prop is taken when its own bounding box fits `max_size`.
    """
    chosen = []
    if per_biome <= 0 and min_placements <= 0:
        return chosen
    if min_placements > 0:
        # Frequency-driven rather than rank-driven: a wall placed 27 times matters more than the
        # 9th most common bush, and a per-biome cap cannot express that.
        for biome in BUILD_BIOMES:
            props = palette.get("props_per_biome", {}).get(biome, {})
            for name, count in props.items():
                if count < min_placements:
                    continue
                if root is not None and max_size > 0:
                    model = model_for(root, name)
                    if model is None:
                        continue
                    size = model_size(model)
                    if size and not board_scale(size, max_size):
                        continue
                chosen.append({"name": name, "biome": biome, "placements": count})
        return chosen
    for biome in BUILD_BIOMES:
        props = palette.get("props_per_biome", {}).get(biome, {})
        taken = 0
        for name, count in props.items():
            if taken >= per_biome:
                break
            if root is not None and max_size > 0:
                model = model_for(root, name)
                if model is None:
                    continue
                size = model_size(model)
                if size and not board_scale(size, max_size):
                    continue
            chosen.append({"name": name, "biome": biome, "placements": count})
            taken += 1
    return chosen


def build_one(root: Path, entry: dict, out_dir: Path, log_dir: Path) -> dict | None:
    model = model_for(root, entry["name"])
    if model is None:
        print(f"  MISSING {entry['name']}")
        return None
    dest_dir = out_dir / entry["biome"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{entry['name']}.glb"
    log = log_dir / f"{entry['name']}.log"
    cmd = ["blender", "-b", "-P", str(ROOT / "tools/blender/dow2_env_import.py"), "--",
           "--model", str(model), "--out", str(dest), "--name", entry["name"]]
    with log.open("w") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    text = log.read_text(errors="replace")
    if "EXPORTED" not in text:
        print(f"  FAILED {entry['name']} (see {log.name})")
        return None
    size = re.search(r"SIZE ([-\d., ]+)", text)
    tris = re.search(r"TRIS (\d+)", text)
    out = dict(entry)
    out["model"] = str(model)
    out["url"] = f"/assets/models/env/{entry['biome']}/{entry['name']}.glb"
    out["cover"] = coverbox_for(model)
    if size:
        out["size"] = [round(float(v), 2) for v in size.group(1).split(",")]
    if tris:
        out["tris"] = int(tris.group(1))
    # record whether the shipped material actually carries a diffuse map: a prop without one needs a
    # fallback tint, and the manifest is where that fact belongs
    out["textured"] = glb_has_texture(dest)
    return out


def ground_tints(out_dir: Path) -> dict[str, list[float]]:
    """Per-biome ground colour, measured from the ground kit's own tiles.

    A shipped prop with no diffuse map has no colour of its own to recover. The measured colour of the
    ground it stands on is the honest fallback — and it is a measurement, not an invention.
    """
    manifest = Path(out_dir).parents[1] / "terrain" / "ground_kit.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text())
    except json.JSONDecodeError:
        return {}
    tints: dict[str, list[float]] = {}
    for biome, entry in data.get("biomes", {}).items():
        tiles = entry.get("tiles") or []
        if not tiles:
            continue
        rgb = [sum(t["rgb"][i] for t in tiles) / len(tiles) for i in range(3)]
        tints[biome] = [round(min(1.0, c / 255.0 * 1.35), 3) for c in rgb]
    return tints


def glb_has_texture(path: Path) -> bool:
    """Does this GLB carry an image? Read from the container, not from the importer's log."""
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if data[:4] != b"glTF":
        return False
    offset = 12
    while offset + 8 <= len(data):
        length, ctype = struct.unpack_from("<II", data, offset)
        offset += 8
        if ctype == 0x4E4F534A:  # JSON chunk
            try:
                gltf = json.loads(data[offset:offset + length])
            except json.JSONDecodeError:
                return False
            return bool(gltf.get("images"))
        offset += length
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", type=Path, default=None)
    ap.add_argument("--palette", type=Path,
                    default=ROOT / "output/source_lab/biome_palette.json")
    ap.add_argument("--per-biome", type=int, default=8)
    ap.add_argument("--refresh-tints", action="store_true",
                    help="re-read the existing kit's GLBs to record which props carry a diffuse map, "
                         "and give the rest the measured ground colour of their biome (no rebuild)")
    ap.add_argument("--min-placements", type=int, default=0,
                    help="select by frequency instead of rank: take every board-scale prop placed at "
                         "least this many times in the corpus")
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/models/env")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="kit manifest (default <out>/env_kit.json)")
    ap.add_argument("--only", action="append", default=[], help="one prop name (repeatable)")
    ap.add_argument("--max-size", type=float, default=8.0,
                    help="skip props whose largest dimension exceeds this (metres; default 8)")
    ap.add_argument("--include-structures", action="store_true",
                    help="also build the shipped structures (bunkers, turrets, generators)")
    ap.add_argument("--max-vista-height", type=float, default=40.0,
                    help="vista pieces taller than this are skyline, not horizon scenery (default 40 m)")
    ap.add_argument("--include-gameplay", action="store_true",
                    help="also build the visible gameplay markers (capture points, drops, generators)")
    ap.add_argument("--include-vista", action="store_true",
                    help="also build the horizon-scale props (big trees, cliffs) as their own layer")
    a = ap.parse_args(argv)
    if a.refresh_tints:
        manifest = a.manifest or (a.out / "env_kit.json")
        data = json.loads(manifest.read_text())
        ground = ground_tints(Path(a.out))
        updated = 0
        for prop in data.get("props", []):
            path = Path(a.out) / prop["url"].replace("/assets/models/env/", "")
            prop["textured"] = glb_has_texture(path)
            if prop["textured"]:
                prop.pop("tint", None)
            elif prop.get("biome") in ground:
                prop["tint"] = ground[prop["biome"]]
                updated += 1
        manifest.write_text(json.dumps(data, indent=1))
        print(f"{updated} untextured props tinted from their biome's measured ground colour")
        return 0
    root = a.art or art_root()
    palette = json.loads(a.palette.read_text())
    entries = select(palette, a.per_biome, None if a.only else root, a.max_size, a.min_placements)
    if a.include_structures:
        entries.extend(structure_entries(root))
    if a.include_vista:
        entries.extend(vista_entries(root))
    if a.include_gameplay:
        entries.extend(gameplay_entries(root))
    if not a.only:
        print(f"{len(entries)} props within {a.max_size} m")
    if a.only:
        wanted = set(a.only)
        entries = [e for e in entries if e["name"] in wanted] or \
            [{"name": n, "biome": "misc", "placements": 0} for n in a.only]
    log_dir = ROOT / "output/source_lab/env_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for entry in entries:
        print(f"== {entry['biome']}/{entry['name']}")
        result = build_one(root, entry, a.out, log_dir)
        if result:
            built.append(result)
            print(f"  ok  size {result.get('size')} cover {'yes' if result['cover'] else 'no'}")
    # a prop whose exported size still exceeds the limit is a vista piece, not cover (measured: the
    # tyranid `capillary_tower_epic` reads 336 m because its own model is the horizon-scale variant)
    if a.max_size > 0:
        before = len(built)
        # a vista backdrop is a 4-triangle plate, not map dressing (`viz_black_wall_bg`).
        # The built size is Y-up, so the board test is applied to (width, depth, height) in that order
        # — the same rule the selection uses on the authored model, not a flat max() that would drop
        # a 12 m wall for being long.
        def built_board_scale(size):
            width, height, depth = (float(v) for v in size[:3])
            if min(width, height, depth) < 0.2 or height > a.max_size:
                return False
            return max(width, depth) <= a.max_size * 2.5

        built = [b for b in built
                 if (b["biome"].startswith(("structure_", "vista_"))
                     or (not b.get("size") or built_board_scale(b["size"])))
                 and (b.get("tris") or 0) >= 8]
        if len(built) != before:
            print(f"dropped {before - len(built)} prop(s) larger than {a.max_size} m after build")
    manifest = a.manifest or (a.out / "env_kit.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if manifest.exists():
        try:
            existing = json.loads(manifest.read_text()).get("props", [])
        except json.JSONDecodeError:
            existing = []
    # A prop whose shipped material carries no diffuse map renders as bare grey in our viewer. Its own
    # source has no colour to recover, so the honest fallback is the *measured* colour of the ground it
    # stands on: a desert rock is the colour of the desert. `ground_kit.json` holds those means.
    ground = ground_tints(Path(a.out))
    for prop in built:
        if not prop.get("textured", True) and prop.get("biome") in ground:
            prop["tint"] = ground[prop["biome"]]

    merged = {(p["biome"], p["name"]): p for p in existing}
    for prop in built:
        merged[(prop["biome"], prop["name"])] = prop
    built = sorted(merged.values(), key=lambda p: (p["biome"], p["name"]))
    manifest.write_text(json.dumps({
        "generated_by": "asset-pipeline/tools/dow2/build_env_kit.py",
        "note": ("Shipped DoW2 environment props built as static GLBs. The selection is the props the "
                 "shipped maps place most often in each biome; `size` is the model's own bounding box "
                 "in metres and `cover` is the shipped .coverbox volume beside the model."),
        "props": built,
    }, indent=1))
    print(f"\n{len(built)} props -> {manifest}")
    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
