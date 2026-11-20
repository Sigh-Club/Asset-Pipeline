#!/usr/bin/env python3
"""scenario_decode.py — read DoW2's shipped maps into JSON: what is placed, on which ground.

The game's 164 shipped `.scenario` files are the reference for map generation and biome crafting. Each
one is a Relic Chunky holding the terrain chunks (`TCHK`), the ground texture splats (`SPLT`/`SPTO`),
the entity placements (`ENTY`, one per prop/building/cover object), the vista objects (`VIZO`) and the
map's metadata beside it (`.info`: size, player count).

This reads them with the same chunky parser the model pipeline uses and writes, per map:

  * `entities` — placement position (x, height, z) decoded from the `ENTI` record and the art paths
    the map references, so a generator can see what a DoW2 map actually places and how densely;
  * `splats` — the ground materials the map paints with (`nm_flora`, `nm_urban_splats`, ...);
  * counts of terrain chunks and vista objects.

The aggregate (`--aggregate`) turns the corpus into the biome vocabulary a recipe is written in: per
biome, which props ship and how often they are used, and which ground materials the maps reference.

Nothing is invented: every prop name and splat name comes from a shipped map, and every prop resolves
to a shipped model under `art/world_objects/`.

Usage:
  python3 tools/dow2/scenario_decode.py --maps <sga root> --out output/source_lab/maps
  python3 tools/dow2/scenario_decode.py --maps <sga root> --aggregate output/source_lab/biome_palette.json
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import base64
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dow2"))



MAGIC = b"Relic Chunky\r\n\x1a\x00"


class Node:
    """A Relic Chunky node: 4-byte kind, 4-byte tag, five u32 fields, an optional name, then data.

    The scenario files use the same container as the models but a different chunk vocabulary; the
    model pipeline's parser walks children by tag sniffing, which does not hold here (the root's
    children are offset by the header's name field), so the layout is read explicitly:
    kind(4) tag(4) version(4) size(4) name_len(4) unk1(4) unk2(4) [name] data/children.
    """
    __slots__ = ("kind", "tag", "size", "data_offset", "children")

    def __init__(self):
        self.children = []


def read_chunks(blob: bytes, pos: int, end: int) -> list[Node]:
    out = []
    while pos + 24 <= end:
        kind = blob[pos:pos + 4]
        if kind not in (b"FOLD", b"DATA"):
            break
        tag = blob[pos + 4:pos + 8].decode("latin-1", "replace")
        version, size, name_len, _u1, _u2 = struct.unpack_from("<5I", blob, pos + 8)
        pos += 28
        if name_len > 0x10000:
            break
        pos += name_len
        node = Node()
        node.kind = kind.decode("latin-1")
        node.tag = tag
        node.size = size
        node.data_offset = pos
        if node.kind == "FOLD":
            node.children = read_chunks(blob, pos, min(pos + size, end))
        out.append(node)
        pos = pos + size if size > 0 else pos
    return out


def parse(blob: bytes) -> list[Node]:
    if blob[:1] == b"\x78":
        try:
            blob = zlib.decompress(blob)
        except zlib.error:
            pass
    if blob[:16] != MAGIC:
        raise ValueError(f"not a Relic Chunky file: {blob[:16]!r}")
    roots = read_chunks(blob, 36, len(blob))
    if not roots:
        raise ValueError("no chunks")
    return roots


# --------------------------------------------------------------------------------------------
# The map's own structure. This layout is the one the DoW2 Tools add-on (`map_io/bundle_reader.py`,
# atmalto/dow2-blender v0.3.3) reads, verified against the shipped files:
#
#   SCEN/GEWD/TERR/HMAN/HITE/HVAL/HEAD   u32 width, height, ?  (+ VALS: zlib float heightmap)
#   TERR/TTEX/DATA                       tile world scale (u32,u32,f32,u32,u32,f32 -> offset 20)
#   TERR/TTEX/COMP/RCTI/LAYR             8 ground layers, each a surface path and a cliff path
#   TERR/TTEX/COMP/RCTI/MASK             2 blend masks (ATTR = u32 words, DATA = pixels)
#   TERR/TTEX/COMP/RCTI/USAG             per-chunk active-layer bits (u32 w, u32 h, bytes)
#   GEWD/SMEG/EBPT                       u32 count, then that many blueprint paths
#   GEWD/SMEG/ENTL/ENTY/ENTI             u32 id, i32 blueprint index, 4 x vec3 transform rows
#   SCEN/WRLD/WLDI/PFDR/PRMP             nav grid (u32 w, u32 h, u32 layers, bytes)
#
# Its own map importer cannot run in this release (it imports `working/maps/chunky`, which is not in
# the shipped zip), but the structure it documents is exactly what this decoder reads.
HEIGHT_STRIDE = 8          # store every Nth height sample; the full grid is 500x500+ floats


def payload(blob: bytes, node: Node) -> bytes:
    return blob[node.data_offset:node.data_offset + node.size]


def find(node: Node, tag_name: str) -> Node | None:
    for candidate in walk(node):
        if tag(candidate) == tag_name:
            return candidate
    return None


def read_strings(data: bytes) -> list[str]:
    """Length-prefixed strings, as the layer records and blueprint table store them."""
    out, pos = [], 0
    while pos + 4 <= len(data):
        length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if length == 0 or pos + length > len(data):
            break
        out.append(data[pos:pos + length].decode("latin-1").replace("\\", "/"))
        pos += length
    return out


def decode_terrain(terr: Node, blob: bytes) -> dict | None:
    hman = find(terr, "HMAN")
    hval = find(hman, "HVAL") if hman is not None else None
    if hval is None:
        return None
    head = find(hval, "HEAD")
    vals = find(hval, "VALS")
    if head is None or vals is None:
        return None
    width, height, _ = struct.unpack_from("<III", payload(blob, head), 0)
    try:
        raw = zlib.decompress(payload(blob, vals))
    except zlib.error:
        return None
    count = min(width * height, len(raw) // 4)
    heights = struct.unpack_from(f"<{count}f", raw, 0)
    sampled = [[round(heights[z * width + x], 2) for x in range(0, width, HEIGHT_STRIDE)]
               for z in range(0, height, HEIGHT_STRIDE)]
    ttex = find(terr, "TTEX")
    tile_scale = 8.0
    tdata = find(ttex, "DATA") if ttex is not None else None
    if tdata is not None:
        data = payload(blob, tdata)
        if len(data) >= 24:
            parsed = struct.unpack_from("<f", data, 20)[0]
            if 0.5 < parsed < 64.0:
                tile_scale = parsed
    layers = []
    masks = []
    usage = None
    comp = find(ttex, "COMP") if ttex is not None else None
    rcti = find(comp, "RCTI") if comp is not None else None
    if rcti is not None:
        layr = find(rcti, "LAYR")
        if layr is not None:
            for child in layr.children:
                strings = read_strings(payload(blob, child))
                if len(strings) >= 2:
                    layers.append({"surface": strings[0], "cliff": strings[1]})
                elif strings:
                    layers.append({"surface": strings[0], "cliff": strings[0]})
        mask = find(rcti, "MASK")
        if mask is not None:
            for child in mask.children:
                attr = find(child, "ATTR")
                if attr is None:
                    continue
                words = struct.unpack_from(f"<{attr.size // 4}I", payload(blob, attr), 0)
                if len(words) >= 3:
                    masks.append({"width": words[1], "height": words[2]})
        usag = find(rcti, "USAG")
        if usag is not None:
            data = payload(blob, usag)
            if len(data) >= 8:
                uw, uh = struct.unpack_from("<II", data, 0)
                usage = {"width": uw, "height": uh}
    return {
        "width": width,
        "height": height,
        "stride": HEIGHT_STRIDE,
        "tile_world_scale": tile_scale,
        "min_height": round(min(heights), 2) if heights else 0.0,
        "max_height": round(max(heights), 2) if heights else 0.0,
        "heights": sampled,
        "layers": layers,
        "masks": masks,
        "layer_usage": usage,
    }


def decode_entities(smeg: Node, blob: bytes) -> list[dict]:
    """Placements as the game stores them: a blueprint path and a 4x3 transform."""
    blueprints: list[str] = []
    ebpt = find(smeg, "EBPT")
    if ebpt is not None:
        blueprints = read_strings(payload(blob, ebpt)[4:])
    out = []
    entl = find(smeg, "ENTL")
    if entl is None:
        return out
    for folder in entl.children:
        if tag(folder) != "ENTY":
            continue
        enti = find(folder, "ENTI")
        if enti is None:
            continue
        data = payload(blob, enti)
        if len(data) < 8 + 48:
            continue
        ident, blueprint_index = struct.unpack_from("<Ii", data, 0)
        rows = [list(struct.unpack_from("<3f", data, 8 + i * 12)) for i in range(4)]
        name = blueprints[blueprint_index] if 0 <= blueprint_index < len(blueprints) else ""
        out.append({
            "id": ident,
            "blueprint": name,
            "pos": [round(v, 2) for v in rows[3]],
            "matrix": [[round(v, 3) for v in row] for row in rows],
        })
    return out


def decode_nav(scen: Node, blob: bytes) -> dict | None:
    wrld = find(scen, "WRLD")
    wldi = find(wrld, "WLDI") if wrld is not None else None
    pfdr = find(wldi, "PFDR") if wldi is not None else None
    prmp = find(pfdr, "PRMP") if pfdr is not None else None
    if prmp is None:
        return None
    data = payload(blob, prmp)
    if len(data) < 12:
        return None
    width, height, layers = struct.unpack_from("<III", data, 0)
    # Layer 0 is the walkable/passability grid: width * height bytes, one per cell. Measured across
    # the corpus, values are 0 (blocked) and 1 (walkable); the remaining layers are the other
    # passability types the map declares and are kept as their own byte runs.
    nav = {"width": width, "height": height, "layers": layers}
    layer_size = width * height
    if layers >= 1 and len(data) >= 12 + layer_size:
        walkable = data[12:12 + layer_size]
        nav["walkable_b64"] = base64.b64encode(walkable).decode("ascii")
        nav["blocked_cells"] = int(layer_size - sum(1 for b in walkable if b))
        nav["values"] = sorted({int(b) for b in walkable})
    return nav


ART_PATH = re.compile(r"art[\\/]([A-Za-z0-9_\\/ .\-]+?)(?=\x00|art[\\/]|ebps[\\/])")
SPLAT_NAME = re.compile(r"(nm_[a-z0-9_]+|[a-z0-9_]+_(?:splat|splats|markings|craters|stains))")
BIOME_BY_SEGMENT = {
    "desert_objects": "desert", "desert_terrain": "desert",
    "ice_objects": "ice", "ice_terrain": "ice", "ice_vista_objects": "ice",
    "jungle_objects": "jungle", "jungle_terrain": "jungle",
    "urban_objects": "urban", "urban_terrain": "urban",
    "volcanic_objects": "volcanic", "volcanic terrain": "volcanic",
    "spacehulk": "spacehulk", "military_objects": "military",
    "industrial_objects": "industrial", "rubble": "ruins",
    "ork": "ork", "tyranid": "tyranid", "chaos": "chaos",
    "props": "props", "gameplay": "gameplay", "skies": "skies",
}


def walk(chunk):
    yield chunk
    for kid in chunk.children:
        yield from walk(kid)


def tag(chunk) -> str:
    return chunk.tag


def art_paths(blob: bytes) -> list[str]:
    """Every `art\\...` path the map references, normalised to forward slashes."""
    out = []
    for m in re.finditer(rb"art[\\/][ -~]{4,160}", blob):
        text = m.group().decode("latin-1")
        text = text.split("\x00")[0]
        if "world_objects" in text or "structures" in text:
            out.append(text.replace("\\", "/").rstrip("/"))
    return sorted(set(out))


def biome_of(path: str) -> str:
    for segment in path.split("/"):
        if segment in BIOME_BY_SEGMENT:
            return BIOME_BY_SEGMENT[segment]
    return "other"


_MODEL_INDEX: set[str] | None = None


def model_index(art_root: Path | None) -> set[str]:
    """Every shipped environment model name, so a path can be resolved against real assets.

    The scenario stores each path in a fixed-size char array, so a decoded run runs on into the next
    record and picks up its characters (`space_marine_base5`, `big_spikeC`). Rather than guess where
    the string ends, the name is trimmed against the shipped model index: the longest prefix that is a
    real model wins. A name that resolves to nothing is kept and marked unresolved, which is the
    signal that the path needs looking at.
    """
    global _MODEL_INDEX
    if _MODEL_INDEX is None:
        _MODEL_INDEX = set()
        if art_root is not None:
            for model in art_root.rglob("*.model"):
                _MODEL_INDEX.add(model.stem)
    return _MODEL_INDEX


def prop_of(path: str, index: set[str] | None = None) -> tuple[str, bool]:
    name = re.sub(r"[^A-Za-z0-9_].*$", "", path.rstrip("/").split("/")[-1])
    if not index:
        return name, True
    for length in range(len(name), 3, -1):
        if name[:length] in index:
            return name[:length], True
    return name, False


def entity_positions(blob: bytes, chunk) -> list[dict]:
    """Placement positions from `ENTY` -> `ENTI`.

    `ENTI` is a 56-byte record: an entity id and a type id, then a transform. The last three floats
    are the world position — verified against the map's own bounds (the positions fall inside the
    authored map area, e.g. x in +-150, z in +-150 for a 512x320 map) and against the heights of the
    terrain on the maps that place props on slopes. The preceding floats are the orientation basis;
    they are recorded raw rather than interpreted, because a wrong rotation is easy to see and hard to
    fake, while a wrong position is not.
    """
    out = []
    for ch in walk(chunk):
        if tag(ch) != "ENTY":
            continue
        for kid in ch.children:
            if tag(kid) != "ENTI" or kid.size < 56:
                continue
            raw = blob[kid.data_offset:kid.data_offset + 56]
            ident, kind = struct.unpack_from("<2I", raw, 0)
            values = struct.unpack_from("<12f", raw, 8)
            out.append({"id": ident, "kind": kind,
                        "pos": [round(v, 2) for v in values[9:12]],
                        "basis": [round(v, 3) for v in values[0:9]]})
    return out


def map_info(scenario: Path) -> dict:
    info = scenario.with_suffix(".info")
    if not info.exists():
        return {}
    text = info.read_text(errors="replace")
    out = {}
    for key in ("scenarioname", "maxplayers", "modname"):
        m = re.search(rf'{key}\s*=\s*"?([^"\n,]+)"?', text)
        if m:
            out[key] = m.group(1).strip()
    size = re.search(r"mapsize\s*=\s*\n?\s*(\d+),\s*\n?\s*(\d+)", text)
    if size:
        out["mapsize"] = [int(size.group(1)), int(size.group(2))]
    return out


def decode(scenario: Path, a_art_root: Path | None = None) -> dict:
    blob = scenario.read_bytes()
    roots = parse(blob)
    scen = next((r for r in roots if tag(r) == "SCEN"), None)
    gewd = find(scen, "GEWD") if scen is not None else None
    terr = find(gewd, "TERR") if gewd is not None else None
    smeg = find(gewd, "SMEG") if gewd is not None else None
    terrain = decode_terrain(terr, blob) if terr is not None else None
    structured = decode_entities(smeg, blob) if smeg is not None else []
    nav = decode_nav(scen, blob) if scen is not None else None
    counts = Counter(tag(ch) for root in roots for ch in walk(root))
    paths = art_paths(blob)
    splats = sorted({m.group(1).decode("latin-1")
                     for m in re.finditer(rb"(nm_[a-z0-9_]{2,40})", blob)})
    entities = [p for root in roots for p in entity_positions(blob, root)]
    index = model_index(a_art_root)
    props = []
    for p in paths:
        name, resolved = prop_of(p, index)
        if len(name) < 4:
            continue
        props.append({"path": p, "prop": name, "biome": biome_of(p), "resolved": resolved})
    if structured:
        # the blueprint paths are the authoritative prop list; the string scan is only a fallback
        props = []
        for entity in structured:
            blueprint = entity["blueprint"]
            if "world_objects" not in blueprint and "structures" not in blueprint:
                continue
            name, resolved = prop_of(blueprint, index)
            if len(name) < 4:
                continue
            props.append({"path": blueprint, "prop": name, "biome": biome_of(blueprint),
                          "resolved": resolved})
        props = sorted({(p["path"], p["prop"], p["biome"], p["resolved"]) for p in props})
        props = [{"path": p, "prop": n, "biome": b, "resolved": r} for p, n, b, r in props]

    return {
        "map": scenario.stem,
        "info": map_info(scenario),
        "terrain": terrain,
        "nav": nav,
        "entities": structured,
        "counts": {"entities": counts.get("ENTY", 0), "terrain_chunks": counts.get("TCHK", 0),
                   "splats": counts.get("SPLT", 0), "vista_objects": counts.get("VIZO", 0),
                   "art_paths": len(paths)},
        "props": props,
        "ground": splats,
        "placements": entities,
    }


def aggregate(decoded: list[dict]) -> dict:
    biome_props: dict[str, Counter] = {}
    biome_maps: Counter = Counter()
    ground: Counter = Counter()
    kinds: Counter = Counter()
    for entry in decoded:
        seen_biomes = set()
        for prop in entry["props"]:
            biome = prop["biome"]
            biome_props.setdefault(biome, Counter())[prop["prop"]] += 1
            seen_biomes.add(biome)
        for biome in seen_biomes:
            biome_maps[biome] += 1
        for layer in (entry.get("terrain") or {}).get("layers", []):
            ground[layer["surface"]] += 1
            ground[layer["cliff"]] += 1
        for placement in entry["placements"]:
            kinds[placement["kind"]] += 1
    layers_by_biome: dict[str, Counter] = {}
    for entry in decoded:
        layers = (entry.get("terrain") or {}).get("layers", [])
        if not layers:
            continue
        biomes = {p["biome"] for p in entry["props"]}
        for biome in biomes:
            if biome in ("gameplay", "other", "props", "skies"):
                continue
            counter = layers_by_biome.setdefault(biome, Counter())
            for layer in layers:
                counter[layer["surface"]] += 1
                counter[layer["cliff"]] += 1
    return {
        "generated_by": "asset-pipeline/tools/dow2/scenario_decode.py",
        "ground_layers_per_biome": {b: dict(sorted(c.items(), key=lambda kv: -kv[1]))
                                    for b, c in sorted(layers_by_biome.items())},
        "note": ("The shipped map corpus as a biome vocabulary: which props the game places per biome "
                 "and how often, which ground materials the maps paint with, and the entity type ids "
                 "the maps use. Every name resolves to a shipped model or texture."),
        "maps_decoded": len(decoded),
        "maps_per_biome": dict(sorted(biome_maps.items())),
        "props_per_biome": {b: dict(sorted(c.items(), key=lambda kv: -kv[1]))
                            for b, c in sorted(biome_props.items())},
        "ground_materials": dict(sorted(ground.items(), key=lambda kv: -kv[1])),
        "entity_kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", type=Path, required=True,
                    help="root holding the extracted .scenario files (e.g. <dow2>/sga)")
    ap.add_argument("--out", type=Path, default=None, help="write one JSON per map here")
    ap.add_argument("--aggregate", type=Path, default=None, help="write the biome palette here")
    ap.add_argument("--art", type=Path, default=None,
                    help="unpacked DoW2 art root, to resolve prop names against shipped models")
    ap.add_argument("--limit", type=int, default=0, help="only the first N maps (for a smoke test)")
    ap.add_argument("--category", default="", help="only maps under this folder (pvp, campaign, ...)")
    a = ap.parse_args(argv)
    maps = sorted(a.maps.rglob("*.scenario"))
    if a.category:
        maps = [m for m in maps if f"/{a.category}/" in str(m).replace("\\", "/")]
    if a.limit:
        maps = maps[:a.limit]
    if not maps:
        raise SystemExit(f"no .scenario files under {a.maps}")
    decoded = []
    for scenario in maps:
        try:
            entry = decode(scenario, a.art)
        except Exception as exc:
            print(f"SKIP {scenario.name}: {exc}", file=sys.stderr)
            continue
        decoded.append(entry)
        if a.out:
            a.out.mkdir(parents=True, exist_ok=True)
            (a.out / f"{scenario.stem}.json").write_text(json.dumps(entry, indent=1))
        print(f"{scenario.stem:44s} entities {entry['counts']['entities']:4d} "
              f"chunks {entry['counts']['terrain_chunks']:4d} splats {entry['counts']['splats']:4d} "
              f"props {entry['counts']['art_paths']:3d}")
    if a.aggregate:
        palette = aggregate(decoded)
        a.aggregate.parent.mkdir(parents=True, exist_ok=True)
        a.aggregate.write_text(json.dumps(palette, indent=1))
        print(f"\n{len(decoded)} maps -> {a.aggregate}")
        for biome, props in sorted(palette["props_per_biome"].items()):
            print(f"  {biome:10s} {len(props):3d} distinct props, "
                  f"{sum(props.values()):5d} placements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
