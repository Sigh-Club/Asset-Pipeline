#!/usr/bin/env python3
"""discover_units.py — find every DoW2 unit the shipped data can build, from the data itself.

The lab's build table was hand-written for ten units. A roster needs dozens, so this reads the link
the game uses and prints the same columns the build table holds:

  * the unit blueprint's `animator` field names the animation set (`animator = "race_ig\\troops\\ogryn\\
    ig_ogryn"`), which is the `art/race_<race>/troops/<dir>` folder holding the clips and the
    `.motiontree`;
  * `default_wargear` names the unit's wargear items, and each item's own file carries the shipped
    `render_models` (body, head, backpack, weapons);
  * `animator_attachments` names the head/kit the game attaches.

Nothing here is guessed from file names: the animator path, the wargear list and the attachments are
all read out of the blueprints. Chapter (DLC) variants are skipped, as in `parts.py`.

Usage:
  python3 tools/dow2/discover_units.py --list [--race ig] [--json out.json]
  python3 tools/dow2/discover_units.py --unit ig_ogryn_squad      # one unit's full spec
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "dow2"))

import parts  # noqa: E402

ART_ENV = "DOW2_RETRIB"
# `animator = "race_ig\troops\ogryn\ig_ogryn"` — the value is art-relative and may or may not carry
# the `art\` prefix the wargear paths use.
ANIMATOR = re.compile(r'animator\s*=\s*"(?:art[\\/])?([^"]+)"', re.IGNORECASE)
WARGEAR = re.compile(r'wargear\s*=\s*"([^"]+)"', re.IGNORECASE)
RACES = ("ig", "chaos", "eldar", "ork", "tyranid", "tau", "necron")


def data_root() -> Path:
    base = os.environ.get(ART_ENV)
    if not base:
        raise SystemExit(f"set {ART_ENV} to the unpacked DoW2 data")
    root = Path(base).expanduser()
    if (root / "attrib-decoded").is_dir():
        return root
    raise SystemExit(f"{root} has no attrib-decoded/ directory")


def art_root() -> Path:
    root = data_root()
    art = root / "sga_art"
    return art if art.is_dir() else root


def locate(rel: str) -> Path | None:
    """Resolve an art-relative path to a directory under any art root.

    The blueprint's `animator` carries the animation-set stem (`race_ig/troops/ogryn/ig_ogryn`), so a
    path that is not itself a directory is retried without its last component — that stem is also the
    unit's own model name (`ig_ogryn.model`), which is the body for units that ship one.
    """
    rel = rel.replace("\\", "/")
    candidates = [rel]
    if "/" in rel:
        candidates.append(rel.rsplit("/", 1)[0])
    for base in sorted(art_root().glob("???_data/DATA/art")) + sorted(art_root().glob("???_extra/DATA/art")):
        for cand_rel in candidates:
            cand = base / cand_rel
            if cand.is_dir():
                return cand
    return None


def blueprint_animator(text: str) -> str | None:
    m = ANIMATOR.search(text)
    return m.group(1).replace("\\", "/") if m else None


def blueprint_wargear(text: str) -> list[str]:
    """The unit's `default_wargear` items (the block, not the level-up tables)."""
    out, in_block, depth = [], False, 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("default_wargear"):
            in_block, depth = True, 0
            continue
        if not in_block:
            continue
        for ch in s:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        m = WARGEAR.search(s)
        if m:
            out.append(m.group(1).replace("\\", "/"))
        if depth == 0 and "}" in s:
            in_block = False
    return out


def wargear_models(rel: str, root: Path) -> list[Path]:
    """The shipped models a wargear item names (empty for attachments with no model)."""
    path = root / "attrib-decoded" / (rel if rel.endswith(".txt") else rel + ".txt")
    if not path.exists():
        return []
    text = path.read_text(errors="replace")
    raw = parts.entries_outside_chapters(text, parts.ENTRY)
    if not raw:
        return []
    found, _missing = parts._locate(parts.preferred_tier(raw), [art_root()])
    return found


def has_mesh(path: Path) -> bool:
    """True when the model carries geometry (IMOD mesh records), not just a skeleton.

    Measured: `hormagaunt.model`, `ig_ogryn.model`, `heretic.model`, `warlock.model`,
    `general.model`, `witchhunter.model`, `guardian.model` and `termagaunt.model` are 5-7 KB stubs
    holding the FOLDSKEL and no mesh at all — the unit's geometry lives entirely in its wargear. A
    build that treats the stub as the body imports zero vertices and renders a floating weapon.
    """
    try:
        return b"IMOD" in path.read_bytes()
    except OSError:
        return False


def prune_models(models: list[Path], body: Path | None, head: Path | None,
                 loadout: str) -> list[Path]:
    """One part per slot, chosen by the loadout the unit actually uses.

    A blueprint's `default_wargear` can list several alternatives (the Inquisitor carries an inferno
    pistol, a power sword AND a crossbow bolter; the Ork boy's list repeats the slugga, the choppa, an
    armour tier and two heads once per wargear item). Welding them all puts three weapons in one hand
    and two bodies in the same space. The loadout directory names the slots the unit's clips were
    authored for (`melee_blade_range_pistol` = a blade and a pistol), so the parts are filtered by
    slot: one head, one armour, one accessory that belongs to the body, and one weapon per slot the
    loadout names.
    """
    seen: set[str] = set()
    keep: list[Path] = []
    body_stem = body.stem.lower() if body else ""
    slots = set()
    for token, slot in (("melee", "melee"), ("blade", "melee"), ("axe", "melee"), ("spear", "melee"),
                        ("hammer", "melee"), ("fist", "melee"), ("claw", "melee"),
                        ("talon", "melee"), ("pistol", "ranged"), ("range", "ranged"),
                        ("burst", "ranged"), ("gun", "ranged"), ("cannon", "ranged"),
                        ("devourer", "ranged"), ("mouth", "ranged"), ("energy", "ranged"),
                        ("shot", "ranged"), ("flamer", "ranged")):
        if token in loadout.lower():
            slots.add(slot)
    if not slots:
        slots = {"melee", "ranged"}
    have = {"head": bool(head), "armour": False, "accessory": False,
            "melee": False, "ranged": False}
    for model in models:
        path = str(model).replace("\\", "/").lower()
        key = str(model)
        if key in seen:
            continue
        seen.add(key)
        if body is not None and model == body:
            continue
        if "/heads/" in path or "/head/" in path:
            if have["head"]:
                continue
            have["head"] = True
        elif "/weapons_melee/" in path:
            if "melee" not in slots or have["melee"]:
                continue
            have["melee"] = True
        elif "/weapons_ranged/" in path or "/weapons/" in path:
            if "ranged" not in slots or have["ranged"]:
                continue
            have["ranged"] = True
        elif "/armour/" in path or "/armor/" in path:
            if have["armour"]:
                continue
            have["armour"] = True
        elif "/accessories/" in path:
            if have["accessory"]:
                continue
            # an accessory belongs to the body if its stem shares the body's leading words
            prefix = body_stem.split("_")[0]
            if prefix and prefix not in model.stem.lower():
                continue
            have["accessory"] = True
        else:
            continue
        keep.append(model)
    return keep


TIER_SCORE = {"epic": 3, "rare": 2, "common": 1, "": 0, "legendary": 4, "campaign": -1}


def fallback_body(animator: str) -> Path | None:
    """The unit's body when its blueprint does not list the armour.

    Several blueprints carry only weapons in `default_wargear` (measured: `eld_warlock`, `ork_nob`,
    `ork_weirdboy`, `ig_ogryn`) while the body ships as `troops_wargear/armour/<unit>_<tier>` — DoW2
    names the armour after the unit. This scans the race's armour and accessory models for one whose
    stem contains the unit's, prefers the highest quality tier, and requires real geometry. It is a
    naming rule, not a guess about layout, and every result is verified by the render.
    """
    race = animator.split("/")[0].replace("race_", "")
    stem = animator.rsplit("/", 1)[-1].lower()
    for suffix in ("_hero", "_squad", "_leader", "_sergeant"):
        stem = stem.replace(suffix, "")
    best = None
    for base in sorted(art_root().glob("???_data/DATA/art")):
        root_dir = base / f"race_{race}/troops_wargear"
        if not root_dir.is_dir():
            continue
        for sub in ("armour", "armor", "accessories"):
            d = root_dir / sub
            if not d.is_dir():
                continue
            for model in d.rglob("*.model"):
                name = model.stem.lower()
                if stem not in name:
                    continue
                if not has_mesh(model):
                    continue
                tier = next((t for t in TIER_SCORE if name.endswith("_" + t) or name == t), "")
                score = (1 if name.startswith(stem) else 0, TIER_SCORE.get(tier, 0))
                if best is None or score > best[0]:
                    best = (score, model)
    return best[1] if best else None


def spec_for(ebps: Path, root: Path) -> dict | None:
    text = ebps.read_text(errors="replace")
    animator = blueprint_animator(text)
    if not animator:
        return None
    art_dir = locate(animator)
    if art_dir is None:
        return None
    anims = art_dir / "animations"
    if not anims.is_dir():
        return None
    motiontrees = sorted(art_dir.glob("*.motiontree"))
    if not motiontrees:
        return None
    # the body is the unit's OWN model only when that model actually carries geometry; otherwise
    # (measured on the ogryn, heretic, warlock, guardian, termagaunt, general, witchhunter) the own
    # model is a skeleton stub and the body is the wargear's armour
    stem = animator.rsplit("/", 1)[-1]
    own = art_dir / f"{stem}.model"
    own_is_body = own.exists() and has_mesh(own)
    wargear_rels: list[str] = []
    for rel in blueprint_wargear(text):
        path = root / "attrib-decoded" / (rel if rel.endswith(".txt") else rel + ".txt")
        if not path.exists():
            continue
        wargear_rels.extend(parts.entries_outside_chapters(path.read_text(errors="replace"),
                                                           parts.ENTRY))
    # one model per logical part across ALL the unit's wargear (the same armour is listed per tier)
    wanted = parts.preferred_tier(wargear_rels)
    wargear_found, _missing = parts._locate(wanted, [art_root()])
    # drop the skeleton stubs a wargear item can name as its "body" attachment: they import nothing
    wargear_found = [m for m in wargear_found if has_mesh(m)]
    models: list[Path] = [own] if own_is_body else list(wargear_found)
    if own_is_body:
        models.extend(wargear_found)
    attachments, _missing = parts.resolve_attachments(ebps, [art_root()])
    # the base `animator_attachments` armour is already the body's tier variant; the head is what the
    # game attaches, so attachments that are not heads are dropped unless no body was found
    heads = [p for p in attachments if "heads" in str(p) or "headdress" in str(p)]
    if not models:
        return None
    loadout_name = sorted(p.name for p in anims.iterdir() if p.is_dir())[0]
    # when the own model is a stub, the body is an armour piece from the wargear; a unit with neither
    # is skipped rather than built as a floating weapon (measured: the ogryn's only wargear item is
    # its ripper gun, so its armour is not reachable from this blueprint)
    if own_is_body:
        body = own
    else:
        armour = [m for m in models if "/armour/" in str(m).replace("\\", "/").lower()
                  or "/armor/" in str(m).replace("\\", "/").lower()]
        if armour:
            body = armour[0]
        else:
            body = fallback_body(animator)
            if body is None:
                return None
    rest = [m for m in models if m != body]
    models = [body] + prune_models(rest, body, heads[0] if heads else None, loadout_name)
    return {
        "ebps": str(ebps.relative_to(root / "attrib-decoded")),
        "race": animator.split("/")[0].replace("race_", ""),
        "animator": animator,
        "art_dir": str(art_dir),
        "loadouts": sorted(p.name for p in anims.iterdir() if p.is_dir()),
        "motiontree": str(motiontrees[0]),
        "models": [str(p) for p in models],
        "heads": [str(p) for p in heads],
    }


def discover(race: str | None = None) -> list[dict]:
    root = data_root()
    out = []
    for ebps in sorted((root / "attrib-decoded/ebps").rglob("*.txt")):
        if "projectiles" in str(ebps) or "fx" in ebps.parts:
            continue
        spec = spec_for(ebps, root)
        if spec is None:
            continue
        if race and spec["race"] != race:
            continue
        out.append(spec)
    # one row per (animator, wargear set): the same art set is reused by several blueprints
    seen, unique = set(), []
    for spec in out:
        key = (spec["animator"], tuple(spec["models"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--race", default=None, choices=RACES)
    ap.add_argument("--unit", default=None, help="one ebps stem")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--emit-catalogue", type=Path, default=None,
                    help="write the game's DoW2 roster TypeScript from --select")
    ap.add_argument("--emit-build-specs", type=Path, default=None,
                    help="write build_community_units specs for the units named in --select")
    ap.add_argument("--select", type=Path, default=None,
                    help="JSON {unit_id: {ebps, faction, archetypes}} to emit specs for")
    a = ap.parse_args(argv)
    specs = discover(a.race)
    if a.unit:
        specs = [s for s in specs if Path(s["ebps"]).stem == a.unit]
        if not specs:
            raise SystemExit(f"no unit named {a.unit}")
        for s in specs:
            print(json.dumps(s, indent=1))
        return 0
    if a.json:
        a.json.write_text(json.dumps(specs, indent=1))
        print(f"{len(specs)} units -> {a.json}")
        return 0
    if a.emit_catalogue:
        selection = json.loads(a.select.read_text())
        built = {p.stem for p in (ROOT / "output/source_lab/community").glob("*.glb")}
        rows = []
        for unit_id, want in sorted(selection.items()):
            if unit_id not in built:
                print(f"SKIP {unit_id}: no built GLB")
                continue
            rows.append((unit_id, want))
        lines = [
            "/**",
            " * dow2Roster.ts — the DoW2-imported unit roster (GENERATED, do not hand-edit).",
            " *",
            " * Written by asset-pipeline/tools/dow2/discover_units.py --emit-catalogue from",
            " * tools/dow2/roster.json. Each entry is a unit built from the shipped Dawn of War II data",
            " * (geometry, rig, weights, materials, weapons, clips) through the community toolchain, at",
            " * the same standard as the rig lab: `sourceMaterials` keeps the shipped textures rather",
            " * than repainting them into the IoA palette.",
            " */",
            "export interface Dow2RosterEntry {",
            "  unit: string;",
            "  label: string;",
            "  faction: string;",
            "  archetypes: string[];",
            "}",
            "",
            "export const DOW2_ROSTER: Dow2RosterEntry[] = [",
        ]
        for unit_id, want in rows:
            label = unit_id.replace("dow_", "").replace("_", " ")
            lines.append(f"  {{ unit: '{unit_id}', label: '{label}', faction: '{want['faction']}', "
                         f"archetypes: {json.dumps(want.get('archetypes', []))} }},")
        lines.append("];")
        lines.append("")
        lines.append("/** Every archetype the DoW2 roster now serves, per faction. */")
        lines.append("export const DOW2_COVERED_ARCHETYPES: Record<string, string[]> = {")
        covered: dict[str, list[str]] = {}
        for _unit_id, want in rows:
            covered.setdefault(want["faction"], []).extend(want.get("archetypes", []))
        for faction, archetypes in sorted(covered.items()):
            lines.append(f"  {faction}: {json.dumps(sorted(set(archetypes)))},")
        lines.append("};")
        a.emit_catalogue.write_text("\n".join(lines) + "\n")
        print(f"{len(rows)} roster entries -> {a.emit_catalogue}")
        return 0
    if a.emit_build_specs:
        selection = json.loads(a.select.read_text()) if a.select else {}
        by_stem = {Path(s["ebps"]).stem: s for s in specs}
        out = {}
        for unit_id, want in selection.items():
            spec = by_stem.get(want["ebps"])
            if spec is None:
                print(f"MISSING {unit_id}: no discovered unit {want['ebps']}")
                continue
            loadout = want.get("loadout") or (spec["loadouts"][0] if spec["loadouts"] else "")
            if not loadout:
                print(f"MISSING {unit_id}: no loadout")
                continue
            def rel(path_str: str) -> str:
                """Path relative to a `NNN_data/DATA/art` root, which is what the build table holds."""
                path = Path(path_str)
                for parent in path.parents:
                    if parent.name == "art":
                        return str(path.relative_to(parent))
                return path_str

            body_override = want.get("body")
            extra_override = want.get("extra")
            out[unit_id] = {
                "body": body_override or rel(spec["models"][0]),
                "extra": extra_override if extra_override is not None
                         else [rel(m) for m in spec["models"][1:]],
                "head": want.get("head") or (rel(spec["heads"][0]) if spec["heads"] else ""),
                "weapon": "",
                "weapons": [],
                "loadout": rel(str(Path(spec["art_dir"]) / "animations" / loadout)),
                "motiontree": rel(spec["motiontree"]),
                "faction": want.get("faction", spec["race"]),
                "archetypes": want.get("archetypes", []),
                "race": spec["race"],
            }
        a.emit_build_specs.write_text(json.dumps(out, indent=1))
        print(f"{len(out)} build specs -> {a.emit_build_specs}")
        return 0
    for s in specs:
        heads = ",".join(Path(h).stem for h in s["heads"]) or "-"
        models = ",".join(Path(m).stem for m in s["models"])
        print(f"{Path(s['ebps']).stem:38s} {s['race']:8s} animator={s['animator'].split('/')[-1]:24s} "
              f"models=[{models}] heads=[{heads}] loadouts={s['loadouts']}")
    print(f"{len(specs)} units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
