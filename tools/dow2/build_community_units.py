#!/usr/bin/env python3
"""build_community_units.py — build the lab units from the shipped DoW2 data, table-driven.

The table below is the contract: every column is a shipped file, not a choice we made. For each
unit it resolves the body/head/weapon models, writes the unit's action library from its own
`.motiontree`, runs the community importer (`tools/blender/dow2_import_community.py`) and copies the
GLB plus its `.actions.json` into the game's lab directory. A build that does not print `EXPORTED`
is a failure, whatever Blender's exit code says.

Why a table and not a discovery pass: a DoW2 unit is a kit, and which head or weapon belongs to it
is stated by the unit blueprint (the ebps `animator_attachments`) and by the wargear item it
carries, not by the directory layout. `tools/dow2/parts.py --ebps <ebps>` lists the attachment
candidates; the head column is the one the game attaches to the head bone. The ebps's base
`animator_attachments` armour is NOT added — the wargear already supplies the body, and adding both
welds a second body into the first (measured: `cadian_armour` beside `ig_armour`).

Usage:
  python3 tools/dow2/build_community_units.py --list
  python3 tools/dow2/build_community_units.py --only dow_chaos_sorcerer
  python3 tools/dow2/build_community_units.py            # every unit in the table
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ART_ENV = "DOW2_RETRIB"
LAB = ROOT.parent / "Imperium-of-Ash/frontend/public/assets/models/units/lab"

# Real-world heights, in metres. The shipped models are authored at the game's own scale, which is
# not metres and not constant: measured on the built GLBs, a guardsman came out 2.97 m tall, a
# Chimera 6.96 m and a Baneblade 10.55 m against a real 1.85 m, 3.7 m and 5.3 m. A single global
# factor cannot fix that, so each unit carries the height it should be and the importer scales the
# rig to it before export. A unit with no entry keeps the source scale (recorded, not silent).
HEIGHTS_M: dict[str, float] = {
    # infantry — human baseline
    "dow_ig_guardsman": 1.85, "dow_ig_commissar": 1.9, "dow_ig_officer": 1.9,
    "dow_ig_heavy_weapons": 1.9, "dow_ig_inquisitor": 2.0,
    "dow_chaos_heretic": 1.85, "dow_chaos_marine": 2.3, "dow_chaos_havoc": 2.3,
    "dow_chaos_champion": 2.4, "dow_chaos_sorcerer": 2.3, "dow_chaos_plague_champion": 2.4,
    "dow_chaos_bloodletter": 2.4, "dow_chaos_lord": 2.6,
    "dow_eldar_guardian": 2.0, "dow_eldar_ranger": 2.0, "dow_eldar_banshee": 2.0,
    "dow_eldar_warlock": 2.2, "dow_eldar_farseer": 2.2, "dow_eldar_wraithguard": 2.6,
    "dow_ork_boy": 2.2, "dow_ork_nob": 2.6, "dow_ork_warboss": 3.0, "dow_ork_weirdboy": 2.3,
    "dow_tyr_termagaunt": 1.4, "dow_tyr_hormagaunt": 1.5, "dow_tyr_warrior": 2.6,
    "dow_tyranid_lictor": 2.8, "dow_tyr_carnifex": 4.2, "dow_tyr_hive_tyrant": 5.8,
    "dow_necron_overlord": 2.8, "dow_necron_night_bringer": 5.0,
    "dow_tau_battlesuit": 3.2, "dow_tau_gun_drone": 1.2, "dow_tau_marker_drone": 1.2,
    "dow_tau_shield_drone": 1.2,
    # vehicles — length-dominated, so the height is the hull plus turret
    "dow_ig_sentinel": 4.3, "dow_ig_chimera": 3.7, "dow_ig_banewolf": 3.7,
    "dow_ig_manticore": 4.0, "dow_ig_baneblade": 5.3,
    "dow_ork_wartrukk": 2.8, "dow_ork_battlewagon": 4.4, "dow_ork_deff_dread": 4.2,
    "dow_chaos_dreadnought": 4.2, "dow_chaos_juggernaut": 3.0,
}

# unit | body (relative to an art root) | head | extra parts | weapon | loadout dir | motiontree
# The `head` is the ebps `animator_attachments` model the game attaches; `extra` carries the
# accessories the wargear lists (the chaos sorcerer's backpack).
UNITS: dict[str, dict] = {
    "dow_chaos_sorcerer": {
        "body": "race_chaos/troops_wargear/armour/chaos_sorcerer_epic/chaos_sorcerer_epic.model",
        "head": "race_chaos/troops_wargear/heads/chaos_sorcerer_epic/"
                "chaos_sorcerer_head_epic.model",
        "extra": ["race_chaos/troops_wargear/accessories/chaos_sorceror_backpack_epic/"
                  "chaos_sorcerer_backpack_epic.model"],
        "weapon": "",
        # the ebps `default_wargear` weapons, resolved through the weapon's own wargear file:
        # sorcerer_default_sword + bolt_pistol_sorcerer (chaos_sorcerer_hero.txt)
        "weapons": ["wargear/wargear/core/race_chaos/weapon_melee/survive/"
                    "sorcerer_default_sword.txt",
                    "wargear/wargear/core/race_chaos/weapon_ranged/survive/"
                    "bolt_pistol_sorcerer.txt"],
        "loadout": "race_chaos/troops/chaos_lord/animations/melee_blade_range_pistol",
        "motiontree": "race_chaos/troops/chaos_lord/chaos_lord.motiontree",
    },
    "dow_eldar_farseer": {
        "body": "race_eldar/troops_wargear/armour/farseer_armour_common/"
                "farseer_armour_common.model",
        "head": "",
        "extra": [],
        "weapon": "",
        # eld_farseer.txt default_wargear: witchblade + shuriken pistol
        "weapons": ["wargear/wargear/pvp/race_eldar/eld_wp2_witchblade_farseer_default.txt",
                    "wargear/wargear/pvp/race_eldar/eld_wp1_shuriken_pistol.txt"],
        "loadout": "race_eldar/troops/banshee/animations/melee_blade_range_pistol",
        "motiontree": "race_eldar/troops/banshee/banshee.motiontree",
    },
    "dow_ig_guardsman": {
        "body": "race_ig/troops_wargear/armour/ig_armour/ig_armour.model",
        "head": "race_ig/troops_wargear/heads/cadian_trooper/cadian_trooper.model",
        "extra": [],
        "weapon": "race_ig/troops_wargear/weapons_ranged/lasgun/lasgun.model",
        "loadout": "race_ig/troops/gaurdsman/animations/range_burst",
        "motiontree": "race_ig/troops/gaurdsman/guardsman.motiontree",
    },
    "dow_necron_overlord": {
        "body": "race_necron/troops_wargear/armour/necron_overlord_common/"
                "necron_overlord_common.model",
        "head": "race_necron/troops_wargear/accessories/necron_overlord_headdress_02/"
                "necron_overlord_headdress_02.model",
        "extra": [],
        "weapon": "race_necron/troops_wargear/weapons_ranged/tachyon_arrow/"
                  "tachyon_arrow.model",
        "loadout": "race_necron/troops/necron_overlord/animations/melee_staff",
        "motiontree": "race_necron/troops/necron_overlord/necron_overlord.motiontree",
    },
    "dow_ork_warboss": {
        "body": "race_ork/troops_wargear/accessories/warboss_body/warboss.model",
        "head": "race_ork/troops_wargear/heads/warboss_01/warboss_head_01.model",
        "extra": ["race_ork/troops_wargear/armour/warboss_armour_epic/"
                  "warboss_armour_epic.model"],
        "weapon": "",
        # ork_warboss.txt default_wargear: twin-linked shoota + huge choppa
        "weapons": ["wargear/wargear/pvp/race_ork/"
                    "ork_wp1_twin-linked_shoota_warboss.txt",
                    "wargear/wargear/pvp/race_ork/ork_wp2_huge_choppa_warboss.txt"],
        "loadout": "race_ork/troops/warboss/animations/melee_axe_range_pistol",
        "motiontree": "race_ork/troops/warboss/warboss.motiontree",
    },
    "dow_tau_battlesuit": {
        "body": "race_tau/troops_wargear/armor/xv8_default_crisis_suit/"
                "xv8_default_crisis_suit.model",
        "head": "",
        "extra": [],
        "weapon": "",
        # commander_hero.txt (tau) default_wargear: plasma rifle + shield
        "weapons": ["wargear/wargear/core/race_tau/weapon_ranged/survive/"
                    "plasma_rifle_default.txt",
                    "wargear/wargear/core/race_tau/weapon_ranged/survive/"
                    "shield_default.txt"],
        "loadout": "race_tau/troops/battlesuit_commander/animations/range_burst",
        "motiontree": "race_tau/troops/battlesuit_commander/battlesuit_commander.motiontree",
    },
    "dow_tau_gun_drone": {
        # a turret-like 6-bone rig with its own clip names (dhg_*): the gun is part of the model, and
        # its wargear's render_model is an empty string (nothing to attach)
        "body": "race_tau/troops/drone_heavy_gun/drone_heavy_gun.model",
        "head": "",
        "extra": [],
        "weapon": "",
        "loadout": "race_tau/troops/drone_heavy_gun/animations/base",
        "motiontree": "race_tau/troops/drone_heavy_gun/drone_heavy_gun.motiontree",
    },
    "dow_tau_marker_drone": {
        # same turret family as the gun drone, its own clip set (`dm_*`); the markerlight accessory
        # has no model of its own
        "body": "race_tau/troops/drone_marker/drone_marker.model",
        "head": "",
        "extra": [],
        "weapon": "",
        "loadout": "race_tau/troops/drone_marker/animations/base",
        "motiontree": "race_tau/troops/drone_marker/drone_marker.motiontree",
    },
    "dow_tau_shield_drone": {
        # no fire: its loadout ships an ability (`sd_ability_field`) instead
        "body": "race_tau/troops/shield_drone/shield_drone.model",
        "head": "",
        "extra": [],
        "weapon": "",
        "loadout": "race_tau/troops/shield_drone/animations/base",
        "motiontree": "race_tau/troops/shield_drone/shield_drone.motiontree",
    },
    "dow_tyranid_lictor": {
        "body": "race_tyranid/troops_wargear/armour/lictor_armour_common/"
                "lictor_armour_common.model",
        "head": "",
        "extra": [],
        "weapon": "",
        "loadout": "race_tyranid/troops/lictor/animations/talons_claws",
        "motiontree": "race_tyranid/troops/lictor/lictor.motiontree",
    },
}


def art_root() -> Path:
    base = os.environ.get(ART_ENV)
    if not base:
        raise SystemExit(f"set {ART_ENV} to the unpacked DoW2 data (its sga_art directory)")
    root = Path(base).expanduser()
    if (root / "sga_art").is_dir():
        root = root / "sga_art"
    if not root.is_dir():
        raise SystemExit(f"{root} is not a directory")
    return root


def locate(root: Path, rel: str) -> Path:
    """Find `rel` under any `NNN_data/DATA/art` root (the units live in 000/003/005)."""
    for base in sorted(root.glob("???_data/DATA/art")) + sorted(root.glob("???_extra/DATA/art")):
        cand = base / rel
        if cand.exists():
            return cand
    raise SystemExit(f"not found under {root}: {rel}")


def wargear_root() -> Path:
    base = Path(os.environ[ART_ENV]).expanduser()
    for cand in (base / "attrib-decoded", base):
        if (cand / "wargear/wargear").is_dir():
            return cand
    raise SystemExit(f"no attrib-decoded/wargear under {base}")


def weapon_models(root: Path, wargear_root_path: Path, rel: str) -> list[Path]:
    """The shipped models a weapon's wargear file names (`render_models`).

    A unit's default weapons are stated by its blueprint's `default_wargear` (measured:
    `chaos_sorcerer_hero.txt` -> sorcerer_default_sword + bolt_pistol_sorcerer,
    `eld_farseer.txt` -> witchblade + shuriken pistol, `ork_warboss.txt` -> shoota + choppa), and
    each weapon's own wargear file carries the model path. Resolving both is what makes the weapon
    the shipped one rather than a lookalike.
    """
    sys.path.insert(0, str(ROOT / "tools/dow2"))
    import parts
    text = (wargear_root_path / rel).read_text(errors="replace")
    raw = parts.entries_outside_chapters(text, parts.ENTRY)
    if not raw:
        # some wargear is an attachment on the suit rather than a model of its own (measured:
        # the Tau crisis commander's `shield_default`), so an empty list is data, not an error
        print(f"WEAPON {rel.split('/')[-1]}: no render_models (attachment only)")
        return []
    found, missing = parts._locate(parts.preferred_tier(raw), [root])
    if missing:
        raise SystemExit(f"{rel}: missing {missing}")
    return found


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)


def build(unit: str, spec: dict, root: Path, out: Path, manifest_dir: Path) -> None:
    print(f"=== {unit}")
    parts = [locate(root, spec["body"])]
    parts += [locate(root, p) for p in spec.get("extra", [])]
    if spec.get("head"):
        parts.append(locate(root, spec["head"]))
    weapon = locate(root, spec["weapon"]) if spec.get("weapon") else None
    if spec.get("weapons"):
        wroot = wargear_root()
        for rel in spec["weapons"]:
            parts.extend(weapon_models(root, wroot, rel))
    loadout = locate(root, spec["loadout"])
    motiontree = locate(root, spec["motiontree"])

    manifest = manifest_dir / f"{unit}.json"
    rc = run([sys.executable, str(ROOT / "tools/dow2/action_library.py"),
              "--loadout", str(loadout), "--motiontree", str(motiontree),
              "--unit", unit, "--out", str(manifest)]).returncode
    if rc != 0:
        raise SystemExit(f"{unit}: action library failed")

    cmd = ["blender", "-b", "-P", str(ROOT / "tools/blender/dow2_import_community.py"), "--",
           "--id", unit, "--out", str(out), "--manifest", str(manifest)]
    for p in parts:
        cmd += ["--part", str(p)]
    if weapon:
        cmd += ["--weapon", str(weapon)]
    height = HEIGHTS_M.get(unit, 0.0)
    if height:
        cmd += ["--height-m", str(height)]
    log = out / f"{unit}.log"
    out.mkdir(parents=True, exist_ok=True)
    with log.open("w") as fh:
        rc = run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode
    text = log.read_text(errors="replace")
    if "EXPORTED" not in text:
        tail = "\n".join(text.strip().splitlines()[-6:])
        raise SystemExit(f"{unit}: BUILD FAILED (no EXPORTED line in {log})\n{tail}")
    for line in text.splitlines():
        if line.startswith(("IMPORTED", "ASSEMBLED", "ACTION ", "EXPORTED", "SCALE", "SKIP")):
            print("   " + line)
    for suffix in (".glb", ".actions.json"):
        src = out / f"{unit}{suffix}"
        if src.exists():
            dest = LAB / f"{unit}{suffix}"
            dest.write_bytes(src.read_bytes())
            print(f"   lab <- {dest.name} ({dest.stat().st_size} bytes)")


def main(argv=None) -> int:
    global LAB
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", default=[], help="unit id (repeatable)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "output/source_lab/community")
    ap.add_argument("--manifest-dir", type=Path, default=ROOT / "output/source_lab/actions")
    ap.add_argument("--lab", type=Path, default=LAB)
    ap.add_argument("--specs", type=Path, default=None,
                    help="extra build specs (JSON, as emitted by discover_units --emit-build-specs)")
    a = ap.parse_args(argv)
    if a.specs:
        extra = json.loads(a.specs.read_text())
        for unit, spec in extra.items():
            UNITS.setdefault(unit, spec)
        print(f"specs: {len(extra)} unit(s) from {a.specs}")
    if a.list:
        for unit, spec in sorted(UNITS.items()):
            print(f"{unit:24s} body={spec['body']} head={spec.get('head') or '-'} "
                  f"weapon={spec.get('weapon') or '-'} "
                  f"weapons={len(spec.get('weapons', []))}")
        return 0
    LAB = a.lab
    root = art_root()
    chosen = a.only or sorted(UNITS)
    unknown = [u for u in chosen if u not in UNITS]
    if unknown:
        # a scripted build passes a list that can outlive a roster edit; report and carry on
        print(f"skipping unknown unit(s): {', '.join(unknown)}")
        chosen = [u for u in chosen if u in UNITS]
        if not chosen:
            raise SystemExit("no known units to build")
    failed = []
    for unit in chosen:
        try:
            build(unit, UNITS[unit], root, a.out, a.manifest_dir)
        except SystemExit as exc:
            # one bad unit must not stop a roster build; it is reported at the end
            print(f"FAILED {unit}: {exc}")
            failed.append(unit)
    print(f"built {len(chosen) - len(failed)} of {len(chosen)} unit(s)")
    if failed:
        print(f"failed: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
