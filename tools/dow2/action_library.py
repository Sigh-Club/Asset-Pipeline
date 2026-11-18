#!/usr/bin/env python3
"""action_library.py — extract a unit's shipped action library from the DoW2 data.

DoW2 is an RTS, so its clips are not the deliverable; its *actions* are. This tool reads the
shipped data and emits a manifest of named actions — aim, fire, reload, melee, grenade, throw,
ability, hit, death, idle — each with:

  * the exact clip file it comes from and its decoded timing (duration, fps, frame count);
  * the shipped events for that clip, with their times, read from the unit's `.motiontree`
    (`FOLDEVCT`/`DATAEVNT` carries `clip name -> (time, event name)`, and `FOLDACTC`/`DATAACTN`
    carries the event's definition: type and parameters);
  * a measured effect frame for actions that have no shipped event, taken from the clip's own
    motion (the frame where the acting hand moves fastest), flagged `derived` so a consumer can
    tell the difference.

Nothing is invented. Clip selection is a preference order over the clips the game ships for that
loadout; where the game ships nothing (there is no walk cycle), the manifest says so explicitly.

Usage:
  python3 tools/dow2/action_library.py --loadout <dir> --motiontree <unit.motiontree> \
      --unit <id> --out <manifest.json>
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "hkx"))

from hkxread import HkxError, Packfile, quat_angle  # noqa: E402

# --------------------------------------------------------------------------------------
# Action set. Each entry lists the shipped clip stems that can serve the action, in preference
# order. The order encodes only what the game ships: standing before crouching, a full-body clip
# before an upper-body one, and the plain variant before the `_rangeenergy` duplicate (same
# motion, different weapon VFX).
# --------------------------------------------------------------------------------------
ACTIONS: dict[str, list[str]] = {
    "idle": ["fb_idle_stand_01", "fb_idle_stand_02", "fb_idle_stand_03", "fb_idle_stand_04",
             "fb_idle_stand_05", "fb_idle_01", "fb_idle_02", "fb_idle_03", "necron_overlord_idle",
             "fb_melee_idle_01", "fb_melee_idle_02", "fb_melee_idle_03", "fb_crouch_idle01",
             "fb_idle_01"],
    "idle_combat": ["fb_idle_combat_stand_01", "fb_idle_combat_stand_02",
                    "fb_idle_combat_stand_03_range_energy", "fb_idle_combat_stand_04_range_energy",
                    "fb_combat_idle_01", "fb_combat_idle_02"],
    "idle_crouch": ["fb_idle_crouch_01", "fb_idle_crouch_02", "fb_idle_crouch_03"],
    # the shipped aim/melee/ability stems differ per faction (`fb_aiming_stand` for the Imperial
    # Guard, `fb_aim_stand` for Chaos, `fb_ability_casting01_enter` for the sorcerer), so the
    # preference lists carry every shipped spelling rather than one faction's.
    "aim": ["fb_aiming_stand", "fb_aim_stand", "fb_aiming_stand_rangeenergy",
            "fb_aiming_stand_grenadelauncher", "fb_aiming_crouch", "fb_idle_aim_01",
            "necron_overlord_staff_fire_aimidle", "necron_overlord_arrow_aim_loop",
            "fb_aim_stand_1h", "fb_aim_stand_2h"],
    "fire": ["fb_fire_stand", "fb_fire_stand_rangeenergy", "fb_fire_stand_grenadelauncher",
             "fb_fire_stand_flamer", "fb_fire_flamer_stand", "fb_fire_crouch",
             "fb_idle_fire_01", "necron_overlord_staff_fire", "necron_overlord_arrow_fire",
             "fb_fire_stand_2cannon", "fb_fire_stand_1cannon", "fb_fire_stand_1plasma",
             "fb_fire_stand_1flamer", "fb_fire_stand_1meltagun", "fb_fire_stand_1glauncher"],
    "reload": ["fb_reload_stand", "fb_reload_stand_rangeenergy", "fb_reload_crouch",
               "fb_reload_crouch_rangeenergy"],
    "melee": ["fb_melee_attack_04", "fb_melee_attack_01", "fb_melee_attack_02",
              "fb_melee_attack_03", "fb_melee_01", "fb_melee_02", "fb_melee_03",
              "fb_special_attack_01", "necron_overlord_melee_01", "necron_overlord_melee_02",
              "fb_melee_parry_01", "fb_melee_parry_02", "fb_melee_parry_03"],
    "grenade": ["fb_grenade", "fb_grenade_rangeenergy", "fb_grenade_throw",
                "fb_grenade_throw_01"],
    "ability": ["fb_ability_flare", "fb_ability_casting01_enter", "fb_ability_drainlife_enter",
                "fb_forceblast", "fb_ability_flesh_hooks"],
    "hit": ["fb_thrown_fly", "fb_thrown_fly_far", "fb_thrown_slide_near", "fb_thrown_slide_far",
            "fb_pinned_idle", "fb_knocked_out", "fb_knocked_out_01"],
    "thrown_getup": ["fb_thrown_getup", "fb_getup"],
    "leap": ["fb_melee_leap_fly", "fb_melee_leap_antic", "fb_melee_leap_land", "fb_charge",
             "fb_leap_fly"],
    "death": ["fb_die_01", "fb_die_f", "fb_die_b", "fb_die_l", "fb_die_r", "fb_die_normal_b",
              "fb_die_normal_f", "fb_die_normal_01", "fb_die_02", "fb_die_03", "fb_die_04",
              "necron_overlord_death_fromidle"],
    "death_sync": ["fb_death_sync_01", "fb_death_sync_02", "fb_death_sync_03"],
    "walk": ["fb_run", "fb_run01", "necron_overlord_wlk_f", "fb_aim_run", "fb_aim_run_01", "fb_charge"],
    "run": ["fb_sprint", "fb_run", "fb_run01", "necron_overlord_wlk_f", "fb_aim_run", "fb_aim_run_01", "fb_charge"],
    "pinned": ["fb_pinned_idle", "fb_pinned_idle_02"],
}

# The bones whose motion marks the action's effect when the clip ships no event for it.
ACTING_BONES = ("Bip01 R Hand", "Bip01 R Weapon", "Bip01 L Hand")


def parse_chunk_stream(blob: bytes, chunk_type: bytes) -> list[bytes]:
    """Payloads of every `chunk_type` chunk, sliced to the next sibling.

    The declared size field is not the payload length for these chunks (measured: a DATAACTN
    declaring 63 bytes holds 80), so the payload runs to the next occurrence of the same chunk
    type — the siblings are contiguous and fixed order.
    """
    offsets = [m.start() for m in re.finditer(re.escape(chunk_type), blob)]
    out = []
    for i, at in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(blob)
        out.append(blob[at + 28:end])
    return out


def decode_events(path: Path) -> list[dict]:
    """Clip -> (time, event) table and the event definitions, from the shipped `.motiontree`.

    `DATAEVNT` payload: u32 clip_len, clip, f32 time, u32 event_len, event.
    `DATAACTN` payload: NUL-terminated name, u32 flags, u32 type_len, type, u32 param_count,
    then (u32 key_len, key, u32 value_len, value) per parameter.
    """
    blob = path.read_bytes()
    definitions: dict[str, dict] = {}
    for payload in parse_chunk_stream(blob, b"DATAACTN"):
        end = payload.find(b"\x00")
        if end <= 0:
            continue
        name = payload[:end].decode("latin-1")
        pos = end + 1
        try:
            flags, = struct.unpack_from("<I", payload, pos)
            pos += 4
            type_len, = struct.unpack_from("<I", payload, pos)
            pos += 4
            atype = payload[pos:pos + type_len].decode("latin-1")
            pos += type_len
            count, = struct.unpack_from("<I", payload, pos)
            pos += 4
            params = {}
            for _ in range(count):
                klen, = struct.unpack_from("<I", payload, pos)
                pos += 4
                key = payload[pos:pos + klen].decode("latin-1")
                pos += klen
                vlen, = struct.unpack_from("<I", payload, pos)
                pos += 4
                value = payload[pos:pos + vlen]
                pos += vlen
                try:
                    text = value.decode("latin-1")
                    params[key] = text if all(32 <= ord(c) < 127 for c in text) else value.hex()
                except UnicodeDecodeError:
                    params[key] = value.hex()
        except struct.error:
            continue
        definitions[name] = {"type": atype, "flags": flags, "params": params}

    events: dict[str, list[dict]] = {}
    for payload in parse_chunk_stream(blob, b"DATAEVNT"):
        try:
            clip_len, = struct.unpack_from("<I", payload, 0)
            clip = payload[4:4 + clip_len].split(b"\x00")[0].decode("latin-1")
            pos = 4 + clip_len
            time, = struct.unpack_from("<f", payload, pos)
            pos += 4
            event_len, = struct.unpack_from("<I", payload, pos)
            pos += 4
            event = payload[pos:pos + event_len].split(b"\x00")[0].decode("latin-1")
        except struct.error:
            continue
        definition = definitions.get(event, {"type": "", "flags": 0, "params": {}})
        events.setdefault(clip.replace("\\", "/"), []).append({
            "time": round(time, 4),
            "event": event,
            "type": definition["type"],
            "params": definition["params"],
        })
    for items in events.values():
        items.sort(key=lambda e: e["time"])
    return events


def _quat_matrix(q: list[float]) -> list[list[float]]:
    x, y, z, w = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _compose(parent, local_t: list[float], local_r: list[float]):
    """Parent world (R, t) composed with a local rotation+translation."""
    pr, pt = parent
    lr = _quat_matrix(local_r)
    world_r = [[sum(pr[i][k] * lr[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    world_t = [pt[i] + sum(pr[i][k] * local_t[k] for k in range(3)) for i in range(3)]
    return world_r, world_t


def acting_frame(anim: dict, skeleton: dict | None) -> tuple[int, str, float]:
    """The frame where the acting hand moves fastest in world space, and its peak speed.

    A bone's *local* translation is constant in these clips (the motion is entirely in the
    rotations), so the hand's travel has to be composed down the chain. Used only for actions
    whose clip ships no event; the value is a measurement of the shipped motion, not an authored
    choice.
    """
    if not skeleton:
        return 0, "", 0.0
    names = skeleton["bone_names"]
    parents = skeleton["parents"]
    best = (0, "", 0.0)
    for bone, name in enumerate(names):
        if name not in ACTING_BONES or bone >= len(anim["tracks"]):
            continue
        chain = []
        cur = bone
        while cur >= 0:
            chain.append(cur)
            cur = parents[cur]
        chain.reverse()
        previous = None
        for frame in range(anim["numberOfPoses"]):
            world = ([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [0.0, 0.0, 0.0])
            for node in chain:
                track = anim["tracks"][node]
                world = _compose(world, track["translation"][frame], track["rotation"][frame])
            position = world[1]
            if previous is not None:
                speed = math.dist(position, previous)
                if speed > best[2]:
                    best = (frame, name, speed)
            previous = position
    return best


def clip_facts(path: Path, events: dict) -> dict | None:
    """Decode one clip and describe it; None when it is not a decodable delta clip."""
    try:
        pf = Packfile.open(path)
        anim = pf.animation()
    except HkxError:
        return None
    if anim is None:
        return None
    sk = pf.skeleton()
    names = sk["bone_names"] if sk else []
    max_delta = 0.0
    for bone in range(min(anim["numTracks"], len(sk["reference_pose"]) if sk else 0)):
        max_delta = max(max_delta, quat_angle(
            anim["tracks"][bone]["rotation"][0], sk["reference_pose"][bone]["rotation"]))
    frame, bone, speed = acting_frame(anim, sk)
    key = f"{path.parent.name}/{path.stem}"
    shipped = events.get(key, [])
    fps = anim["frame_rate"]
    return {
        "clip": key,
        "file": str(path),
        "duration": round(anim["duration"], 4),
        "fps": round(fps, 3),
        "frames": anim["numberOfPoses"],
        "tracks": anim["numTracks"],
        "full_body": bool(sk) and anim["numTracks"] == sk["bone_count"],
        "starts_at_reference_pose": max_delta < 8.0,
        "events": shipped,
        "acting_frame": {
            "frame": frame,
            "bone": bone,
            "speed_m_per_frame": round(speed, 5),
            "derived": not shipped,
        },
    }


def build_manifest(loadout: Path, motiontree: Path | None, unit: str) -> dict:
    events = decode_events(motiontree) if motiontree and motiontree.exists() else {}
    clips = {}
    for path in sorted(loadout.rglob("*.hkx")):
        facts = clip_facts(path, events)
        if facts:
            clips[path.stem] = facts
    actions = {}
    for action, preference in ACTIONS.items():
        chosen = next((clips[s] for s in preference if s in clips), None)
        if chosen is None:
            actions[action] = {"clip": None, "reason": "no shipped clip for this action in the loadout"}
            continue
        actions[action] = dict(chosen)
        actions[action]["preference_rank"] = preference.index(chosen["clip"].split("/")[-1])
    return {
        "unit": unit,
        "loadout": str(loadout),
        "motiontree": str(motiontree) if motiontree else None,
        "decoded_clips": len(clips),
        "actions": actions,
        "not_shipped": {
            "walk": "DoW2 ships no walk cycle; `walk` is served by fb_run (the slowest "
                    "locomotion the loadout has)",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--loadout", required=True, type=Path,
                    help="the loadout's animations directory (the clips the unit ships)")
    ap.add_argument("--motiontree", type=Path,
                    help="the unit's .motiontree, which carries the timed event table")
    ap.add_argument("--unit", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    manifest = build_manifest(a.loadout, a.motiontree, a.unit)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(manifest, indent=1))
    found = [k for k, v in manifest["actions"].items() if v.get("clip")]
    missing = [k for k, v in manifest["actions"].items() if not v.get("clip")]
    print(f"{a.unit}: {manifest['decoded_clips']} clips decoded, "
          f"{len(found)} actions resolved, {len(missing)} not shipped")
    for name in found:
        act = manifest["actions"][name]
        print(f"   {name:14s} <- {act['clip']:44s} {act['duration']:6.3f}s "
              f"{act['frames']:4d}f  events={len(act['events'])}"
              f"{'' if act['full_body'] else '  (partial body)'}"
              f"{'' if act['starts_at_reference_pose'] else '  (not from bind pose)'}")
    for name in missing:
        print(f"   {name:14s} <- not shipped")
    print(f"manifest -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
