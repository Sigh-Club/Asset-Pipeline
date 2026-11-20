#!/usr/bin/env python3
"""ground_kit.py — the ground materials a biome recipe is painted from, as web-ready textures.

`ground_library.py` indexes every terrain material the game ships. A map forge needs a handful per
biome: the tile that is the ground itself and the splats that dress it (cobbles, cracks, snow, basalt,
concrete). This picks them by the shipped name prefixes — the game names a biome's ground after the
biome (`d_` desert, `u_` urban, `sh_` spacehulk, `jungle_*`, `snow_*`, `volcanic_*`, `basalt_*`,
`concrete_*`) — copies the PNGs into the game's public assets and writes a manifest the page reads.

Nothing is invented: each entry is a shipped texture, and the manifest records its source path, size
and measured mean colour so a recipe can be checked against the game's own ground.

Usage:
  python3 tools/dow2/ground_kit.py --library output/source_lab/ground_library.json \
      --out ../Imperium-of-Ash/frontend/public/assets/terrain
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Per biome: the prefixes its ground materials are named with, most specific first. These are the
# shipped naming conventions, not a taste choice — `d_ground_*` is desert ground, `u_cobble_*` urban.
BIOME_PREFIXES: dict[str, dict[str, tuple[str, ...]]] = {
    "desert": {"tile": ("d_ground", "desert_", "d_"), "splat": ("desert_", "d_", "sand_")},
    "ice": {"tile": ("ice_", "snow_", "glacier"), "splat": ("snow_", "ice_", "dirty_snow")},
    "jungle": {"tile": ("jungle_", "j_"), "splat": ("jungle_", "fern", "vine", "flora")},
    "urban": {"tile": ("u_", "concrete_", "cobble"), "splat": ("u_", "cobble", "concrete")},
    "volcanic": {"tile": ("volcanic_", "basalt_", "v_"), "splat": ("volcanic_", "basalt_", "sulphur")},
    "spacehulk": {"tile": ("sh_", "spacehulk_", "steel_"), "splat": ("sh_", "metal", "steel")},
    "military": {"tile": ("dirt", "grass", "cement"), "splat": ("dirt", "grass", "rubble")},
    "industrial": {"tile": ("steel_", "metal", "cement"), "splat": ("metal", "concrete", "stain")},
    "ruins": {"tile": ("rock", "rubble", "concrete"), "splat": ("rubble", "concrete", "brick", "crack")},
    "tyranid": {"tile": ("tyr", "slime", "organic"), "splat": ("tyr", "slime", "organic")},
    "chaos": {"tile": ("chaos_", "black"), "splat": ("chaos_", "symbol")},
}
PER_KIND = 4


# A ground tile should be ground: the shipped tile set also contains wall and cliff faces, which read
# as vertical surfaces when tiled flat (measured: the first urban tile alphabetically was
# `u_building_wall`, and the board looked like a brick wall).
AVOID_TILES = ("wall", "cliff", "ledge", "roof", "brick", "pillar", "column")
PREFER_TILES = ("ground", "cobble", "concrete", "floor", "dirt", "sand", "snow", "rock", "basalt",
                "steel", "metal", "grass", "gravel", "asphalt", "tile")


def pick(materials: dict, kind: str, prefixes: tuple[str, ...], limit: int) -> list[str]:
    def score(name: str) -> tuple[int, int]:
        low = name.lower()
        avoided = any(word in low for word in AVOID_TILES)
        preferred = any(word in low for word in PREFER_TILES)
        return (0 if avoided else 1, 1 if preferred else 0)

    out: list[str] = []
    for prefix in prefixes:
        candidates = [n for n, e in materials.items()
                      if e["kind"] == kind and n not in out and n.startswith(prefix)]
        candidates.sort(key=lambda n: (-score(n)[0], -score(n)[1], n))
        for name in candidates:
            out.append(name)
            if len(out) >= limit:
                return out
    return out


def resolve_layer(art_root: Path, layer: str) -> Path | None:
    """A map's ground layer path to its shipped tile texture.

    The shipped maps name their ground layers as `terrain_textures/tiles/<layer>_dif.dds`
    (measured: `stone/jungle_rocky_moss_02` -> `tiles/stone/jungle_rocky_moss_02_dif.dds`). This is
    the link between what a map paints with and what the archive holds, so the kit is the maps' own
    vocabulary rather than a guess from file names.
    """
    for base in (art_root / "sga", art_root):
        if not base.is_dir():
            continue
        for hit in base.rglob(f"{Path(layer).name}_dif.dds"):
            if "terrain_textures" in str(hit).replace("\\", "/") and "tiles" in str(hit):
                return hit
    return None


def from_maps(palette: Path, art_root: Path, out_dir: Path, per_biome: int,
              tex_cache: Path) -> dict:
    """The forge's ground palette, taken from the shipped maps' own layer records."""
    from PIL import Image
    import numpy as np
    data = json.loads(palette.read_text())
    kit: dict[str, dict] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for biome, layers in data.get("ground_layers_per_biome", {}).items():
        entry = {"tiles": [], "splats": []}
        for layer, _count in list(layers.items())[:per_biome]:
            dds = resolve_layer(art_root, layer)
            if dds is None:
                continue
            name = Path(layer).name
            dest = out_dir / f"{name}.png"
            if not dest.exists():
                try:
                    Image.open(dds).convert("RGB").save(dest)
                except Exception as exc:
                    print(f"  SKIP {dds.name}: {exc}", file=sys.stderr)
                    continue
            rgb = [int(v) for v in np.asarray(Image.open(dest).resize((16, 16))).reshape(-1, 3).mean(axis=0).round()]
            entry["tiles"].append({"name": name, "layer": layer,
                                   "url": f"/assets/terrain/{name}.png", "rgb": rgb})
        kit[biome] = entry
    return kit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", type=Path,
                    default=ROOT / "output/source_lab/ground_library.json")
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/terrain")
    ap.add_argument("--per-kind", type=int, default=PER_KIND)
    ap.add_argument("--from-maps", type=Path, default=None,
                    help="biome_palette.json: build the ground palette from the shipped maps' own "
                         "layer records instead of the name-prefix rules")
    ap.add_argument("--art", type=Path, default=None, help="unpacked DoW2 data root")
    a = ap.parse_args(argv)
    if a.from_maps:
        art = a.art
        if art is None:
            env = os.environ.get("DOW2_RETRIB")
            art = Path(env).expanduser() if env else None
        if art is None:
            raise SystemExit("--from-maps needs --art or DOW2_RETRIB")
        kit = from_maps(a.from_maps, art, a.out, a.per_kind, None)
        manifest = a.out / "ground_kit.json"
        manifest.write_text(json.dumps({
            "generated_by": "asset-pipeline/tools/dow2/ground_kit.py --from-maps",
            "note": ("The ground layers the SHIPPED MAPS paint each biome with, taken from the maps' "
                     "own layer records (surface + cliff per layer) and resolved to the shipped tile "
                     "textures. `rgb` is measured from each texture."),
            "biomes": kit,
        }, indent=1))
        print(f"{len(kit)} biome recipes from the map corpus -> {manifest}")
        for biome, entry in kit.items():
            print(f"  {biome:10s} tiles {len(entry['tiles'])}")
        return 0
    library = json.loads(a.library.read_text())
    materials = library["materials"]
    a.out.mkdir(parents=True, exist_ok=True)
    kit: dict[str, dict] = {}
    copied = 0
    for biome, prefixes in BIOME_PREFIXES.items():
        entry = {"tiles": [], "splats": []}
        for kind, key in (("tile", "tiles"), ("splat", "splats")):
            for name in pick(materials, kind, prefixes[kind], a.per_kind):
                src = Path(materials[name]["png"])
                if not src.is_absolute():
                    src = ROOT / src
                if not src.exists():
                    print(f"  MISSING png {src}", file=sys.stderr)
                    continue
                dest = a.out / f"{name}.png"
                if not dest.exists():
                    shutil.copyfile(src, dest)
                    copied += 1
                entry[key].append({
                    "name": name,
                    "url": f"/assets/terrain/{name}.png",
                    "rgb": materials[name]["mean_rgb"],
                })
        kit[biome] = entry
    manifest = a.out / "ground_kit.json"
    manifest.write_text(json.dumps({
        "generated_by": "asset-pipeline/tools/dow2/ground_kit.py",
        "note": ("The ground materials for each biome: `tiles` are the ground itself, `splats` the "
                 "dressing (cobbles, cracks, snow, basalt). Every entry is a shipped DoW2 texture; "
                 "`rgb` is measured from it so a recipe can be matched to the game's own ground."),
        "biomes": kit,
    }, indent=1))
    print(f"{len(kit)} biome recipes, {copied} textures copied -> {manifest}")
    for biome, entry in kit.items():
        print(f"  {biome:10s} tiles {len(entry['tiles'])} splats {len(entry['splats'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
