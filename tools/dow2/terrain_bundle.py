#!/usr/bin/env python3
"""terrain_bundle.py — the ground of a shipped map, as the forge needs to render it.

The shipped terrain is eight layers blended by two RGBA masks: layer `i`'s weight is
`mask[i // 4]` channel `i % 4`, and the engine blends the layers weighted by those values. Rendering
one texture per biome (what the forge did until now) throws that away, and it is the last big reason
an imported board does not look like the map it came from.

This writes, per map:

  * `layer_<n>.png` — the eight surface textures, resolved from the map's own layer records;
  * `mask_0.png`, `mask_1.png` — the two weight masks, decoded from `RCTI/MASK`;
  * `terrain.json` — the manifest the forge reads: layer urls, mask urls, the mask's pixel size, the
    map extent in metres, and the layer tiling scale.

Usage:
    python3 tools/dow2/terrain_bundle.py --maps output/source_lab/maps \
        --out ../Imperium-of-Ash/frontend/public/assets/maps/terrain [--only 2p_hive_city]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def art_roots(explicit: Path | None) -> list[Path]:
    roots = []
    if explicit:
        roots.append(explicit)
    env = os.environ.get("DOW2_RETRIB")
    if env:
        roots.append(Path(env).expanduser())
    return [r for r in roots if r.is_dir()]


def resolve_layer(roots: list[Path], layer: str, suffix: str = "_dif") -> Path | None:
    """Resolve one shipped terrain tile map. The shipped tiles carry `_dif`, `_nrm` and `_spc` side by
    side; only the diffuse was exported for a long time, which is why the ground had no surface relief
    and no sheen."""
    name = Path(layer.replace("\\", "/")).name
    for root in roots:
        for base in (root / "sga", root, root / "sga_art"):
            if not base.is_dir():
                continue
            for hit in base.rglob(f"{name}{suffix}.dds"):
                text = str(hit).replace("\\", "/")
                if "terrain_textures" in text and "tiles" in text:
                    return hit
    return None


def write_mask(path: Path, width: int, height: int, pixels: bytes) -> None:
    from PIL import Image

    Image.frombytes("RGBA", (width, height), pixels).save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=Path, default=ROOT / "output/source_lab/maps")
    ap.add_argument("--out", type=Path,
                    default=ROOT.parent / "Imperium-of-Ash/frontend/public/assets/maps/terrain")
    ap.add_argument("--art", type=Path, default=None)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--max-texture", type=int, default=512)
    a = ap.parse_args(argv)

    roots = art_roots(a.art)
    if not roots:
        raise SystemExit("set DOW2_RETRIB to the unpacked DoW2 data (or pass --art)")
    from PIL import Image

    maps = sorted(a.maps.glob("*.json"))
    if a.only:
        maps = [m for m in maps if m.stem in a.only]
    if not maps:
        raise SystemExit("no maps found")
    a.out.mkdir(parents=True, exist_ok=True)

    index = []
    for map_json in maps:
        try:
            data = json.loads(map_json.read_text())
        except json.JSONDecodeError:
            continue
        terrain = data.get("terrain") or {}
        masks = [m for m in (terrain.get("masks") or []) if m.get("data_b64")]
        layers = terrain.get("layers") or []
        if not masks or not layers:
            continue
        nav = data.get("nav") or {}
        map_dir = a.out / map_json.stem
        map_dir.mkdir(parents=True, exist_ok=True)

        written_layers = []
        # One surface atlas for the whole board: R,G hold the layer's tangent-space normal, B its
        # shipped specular level. Eight layers in one texture keeps the ground shader inside the
        # fragment-sampler budget (8 albedo + 2 masks + 1 atlas), where eight normal maps alone would
        # have pushed it past the 16 units a WebGL2 context guarantees.
        atlas_tiles: list = []
        for index_no, layer in enumerate(layers[:8]):
            surface = layer.get("surface") or ""
            nrm = resolve_layer(roots, surface, "_nrm")
            spc = resolve_layer(roots, surface, "_spc")
            tile = None
            if nrm is not None or spc is not None:
                try:
                    tile = Image.new("RGBA", (a.max_texture, a.max_texture), (128, 128, 255, 255))
                    if nrm is not None:
                        normal = Image.open(nrm).convert("RGB").resize((a.max_texture, a.max_texture))
                        tile.paste(normal, (0, 0), None)
                    if spc is not None:
                        spec = Image.open(spc).convert("L").resize((a.max_texture, a.max_texture))
                        blue = tile.split()[2]
                        # the shipped specular map is a colour: its luminance is the specular level,
                        # which is what a dielectric's specular response needs
                        tile = Image.merge("RGBA", (tile.split()[0], tile.split()[1], spec, blue))
                except Exception as exc:
                    print(f"  SKIP surface {surface}: {exc}", file=sys.stderr)
                    tile = None
            atlas_tiles.append(tile)
            dds = resolve_layer(roots, surface)
            if dds is None:
                written_layers.append(None)
                continue
            dest = map_dir / f"layer_{index_no}.png"
            if not dest.exists():
                try:
                    image = Image.open(dds).convert("RGB")
                    if max(image.size) > a.max_texture:
                        image.thumbnail((a.max_texture, a.max_texture))
                    image.save(dest)
                except Exception as exc:
                    print(f"  SKIP {layer.get('surface')}: {exc}", file=sys.stderr)
                    written_layers.append(None)
                    continue
            written_layers.append(f"/assets/maps/terrain/{map_json.stem}/{dest.name}")

        written_masks = []
        for index_no, mask in enumerate(masks[:2]):
            dest = map_dir / f"mask_{index_no}.png"
            if not dest.exists():
                write_mask(dest, int(mask["width"]), int(mask["height"]),
                           base64.b64decode(mask["data_b64"]))
            written_masks.append(f"/assets/maps/terrain/{map_json.stem}/{dest.name}")

        atlas_url = None
        if any(t is not None for t in atlas_tiles):
            atlas = Image.new("RGBA", (a.max_texture, a.max_texture * 8), (128, 128, 255, 255))
            for slot, tile in enumerate(atlas_tiles):
                if tile is not None:
                    atlas.paste(tile, (0, slot * a.max_texture))
            dest = map_dir / "surface_atlas.png"
            atlas.save(dest)
            atlas_url = f"/assets/maps/terrain/{map_json.stem}/{dest.name}"

        manifest = {
            "map": data.get("map"),
            "surface_atlas": atlas_url,
            "surface_atlas_tiles": 8,
            "layers": written_layers,
            "masks": written_masks,
            "mask_size": [int(masks[0]["width"]), int(masks[0]["height"])],
            "map_size_m": [int(nav.get("width") or 0), int(nav.get("height") or 0)],
            "tile_scale_m": float(terrain.get("tile_world_scale") or 32.0),
            "layer_names": [l.get("surface") for l in layers[:8]],
            "note": ("Eight ground layers blended by two RGBA masks: layer i weight = mask[i // 4] "
                     "channel i % 4. The blend is the engine's own; the mask is in map space, the "
                     "layers tile at tile_scale_m."),
        }
        (map_dir / "terrain.json").write_text(json.dumps(manifest, indent=1))
        index.append({"map": map_json.stem, "manifest": f"/assets/maps/terrain/{map_json.stem}/terrain.json",
                      "layers": sum(1 for l in written_layers if l), "masks": len(written_masks)})
        print(f"{map_json.stem:34s} layers {sum(1 for l in written_layers if l)}/8 "
              f"masks {len(written_masks)} mask {manifest['mask_size']} tile {manifest['tile_scale_m']}")

    (a.out / "terrain_index.json").write_text(json.dumps({"maps": index}, indent=1))
    print(f"{len(index)} terrain bundles -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
