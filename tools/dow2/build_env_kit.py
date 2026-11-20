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


def model_for(root: Path, name: str) -> Path | None:
    hits = sorted(root.rglob(f"{name}.model"))
    if not hits:
        return None
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
           max_size: float = 0.0) -> list[dict]:
    """The kit's prop list: the most-placed props per biome that fit a combat board.

    The scan walks the biome's frequency-ordered list rather than its head, because the top of a DoW2
    map's prop list is cliffs and 29 m trees — a 15x12 board at 2 m tiles is 30x24 m, so those are
    vista pieces, not cover. A prop is taken when its own bounding box fits `max_size`.
    """
    chosen = []
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
                if size and (max(size) > max_size or max(size) < 0.3):
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
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", type=Path, default=None)
    ap.add_argument("--palette", type=Path,
                    default=ROOT / "output/source_lab/biome_palette.json")
    ap.add_argument("--per-biome", type=int, default=8)
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/models/env")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="kit manifest (default <out>/env_kit.json)")
    ap.add_argument("--only", action="append", default=[], help="one prop name (repeatable)")
    ap.add_argument("--max-size", type=float, default=8.0,
                    help="skip props whose largest dimension exceeds this (metres; default 8)")
    ap.add_argument("--include-structures", action="store_true",
                    help="also build the shipped structures (bunkers, turrets, generators)")
    ap.add_argument("--include-vista", action="store_true",
                    help="also build the horizon-scale props (big trees, cliffs) as their own layer")
    a = ap.parse_args(argv)
    root = a.art or art_root()
    palette = json.loads(a.palette.read_text())
    entries = select(palette, a.per_biome, None if a.only else root, a.max_size)
    if a.include_structures:
        entries.extend(structure_entries(root))
    if a.include_vista:
        entries.extend(vista_entries(root))
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
        # a vista backdrop is a 4-triangle plate, not map dressing (`viz_black_wall_bg`)
        built = [b for b in built
                 if (b["biome"].startswith(("structure_", "vista_"))
                     or (not b.get("size") or max(b["size"]) <= a.max_size))
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
