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
    # The Tau drones are turret-like rigs with their own clip names (`dhg_*`), so their stems are
    # listed alongside the humanoid ones rather than renamed.
    "idle": ["fb_idle_stand_01", "fb_idle_stand_02", "fb_idle_stand_03", "fb_idle_stand_04",
             "fb_idle_stand_05", "fb_idle_01", "fb_idle_02", "fb_idle_03", "necron_overlord_idle",
             "fb_melee_idle_01", "fb_melee_idle_02", "fb_melee_idle_03", "fb_crouch_idle01",
             "dhg_idle_01", "fb_idle_01"],
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
    "fire": ["dhg_fire_w_idle", "dhg_fire", "fb_fire_stand", "fb_fire_stand_rangeenergy", "fb_fire_stand_grenadelauncher",
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
    # The attack chain as the game ships it: three separate swings, each with its own timing and
    # events. `melee` above stays the single default an action system can trigger without knowing
    # the chain; these expose the individual attacks so a turn-based system can pick one per turn
    # instead of replaying the same swing. Measured: the three are distinct clips (chaos 46 frames
    # each, different hand travel), not duplicates of one motion.
    "melee_01": ["fb_melee_attack_01", "necron_overlord_melee_01", "fb_melee_01"],
    "melee_02": ["fb_melee_attack_02", "necron_overlord_melee_02", "fb_melee_02"],
    "melee_03": ["fb_melee_attack_03", "fb_melee_03"],
    "grenade": ["fb_grenade", "fb_grenade_rangeenergy", "fb_grenade_throw",
                "fb_grenade_throw_01"],
    "ability": ["fb_ability_flare", "fb_ability_casting01_enter", "fb_ability_drainlife_enter",
                "fb_forceblast", "fb_ability_flesh_hooks"],
    "hit": ["fb_thrown_fly", "fb_thrown_fly_far", "fb_thrown_slide_near", "fb_thrown_slide_far",
            "fb_pinned_idle", "fb_knocked_out", "fb_knocked_out_01"],
    "thrown_getup": ["fb_thrown_getup", "fb_getup"],
    "leap": ["fb_melee_leap_fly", "fb_melee_leap_antic", "fb_melee_leap_land", "fb_charge",
             "fb_leap_fly"],
    "death": ["dhg_death_01", "dhg_death_02", "fb_die_01", "fb_die_f", "fb_die_b", "fb_die_l", "fb_die_r", "fb_die_normal_b",
              "fb_die_normal_f", "fb_die_normal_01", "fb_die_02", "fb_die_03", "fb_die_04",
              "necron_overlord_death_fromidle"],
    "death_sync": ["fb_death_sync_01", "fb_death_sync_02", "fb_death_sync_03"],
    "walk": ["dhg_move", "fb_run", "fb_run01", "necron_overlord_wlk_f", "fb_aim_run", "fb_aim_run_01", "fb_charge"],
    "run": ["dhg_move", "fb_sprint", "fb_run", "fb_run01", "necron_overlord_wlk_f", "fb_aim_run", "fb_aim_run_01", "fb_charge"],
    "pinned": ["fb_pinned_idle", "fb_pinned_idle_02"],
}

# The aim-direction layers. DoW2 composes aiming from a full-body stance plus single-track
# upper-body layers that twist the spine: `aim_stand_horiz` drives `Bip01 Spine1` and
# `aim_stand_virt` drives `Bip01 Spine2` (read from each clip's own `hkAnimationBinding`), sweeping a
# full turn over 37 frames with the identity at frame 18. The game samples a frame by target
# direction. A turn-based unit aims at a chosen bearing, so the useful bakes are the four cardinal
# offsets: each is the stance with one layer held at its quarter-turn frame. Names are assigned by
# measurement (the render decides which way each frame twists), not by guesswork.
# Which layer family carries which axis is measured, not assumed: `aim_stand_horiz` turns out to be
# the BEARING sweep and `aim_stand_virt` the ELEVATION sweep (composed and measured in the built GLB:
# horiz frame 9 moves the pelvis->weapon bearing +89 deg with the head still up, virt frame 9 drops the
# head to 0.18 m, virt frame 27 raises the weapon). The four cardinal bakes are the stance plus one
# layer held at its quarter turn.
AIM_AXES = {
    "bearing": ("horiz", "vert", "virt"),
    "elevation": ("vert", "virt"),
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


def _norm_bone(name: str) -> str:
    """Bone names are compared with spaces and underscores removed (`bip01_r_weapon` exists on the
    Tau rig where the Imperial Guard ships `Bip01 R Weapon`)."""
    return name.lower().replace(" ", "").replace("_", "")


def _find_bone(names: list[str], wanted: str) -> int | None:
    target = _norm_bone(wanted)
    for i, n in enumerate(names):
        if _norm_bone(n) == target:
            return i
    return None


def quarter_frames(clip_file: str, degrees: float = 45.0) -> tuple[int, int] | None:
    """The two frames of a single-track layer that hold a +d and a -d degree twist.

    The offset is a sampling choice, not an invention: the shipped layer is a continuous parameter
    (a full turn over 37 frames, identity in the middle), so any direction can be baked. A
    turn-based unit faces its target and needs only the residual offset, so the cardinals are baked
    at 45 degrees; the layer's own extreme (90) is what the game uses for a target straight to the
    side, and it contorts the torso visibly when applied on top of a forward stance.

    The layers sweep a full turn: identity at the midpoint and ~180 deg at both ends (measured on
    every shipped aim layer: 37 frames, 0..179 deg, identity at frame 18). The quarter turns are
    therefore the midpoints between the identity frame and each end — structural, so it holds for a
    layer whose sweep axis is not the one another unit uses (a sign test on the quaternion's dominant
    component found only one quarter on the chaos and warboss layers).
    """
    try:
        pf = Packfile.open(clip_file)
        anim = pf.animation()
    except HkxError:
        return None
    if anim is None or anim["numTracks"] != 1:
        return None
    angles = [quat_angle(q, [0.0, 0.0, 0.0, 1.0]) for q in anim["tracks"][0]["rotation"]]
    if not angles:
        return None
    identity = min(range(len(angles)), key=lambda f: angles[f])
    last = len(angles) - 1
    if angles[identity] > 30.0 or max(angles) < 120.0:
        return None
    # the sweep is 180 deg from the identity frame to either end (18 frames in the shipped 37-frame
    # layers), so the frame for an angle is identity +/- (frames per 180 deg) * degrees/180
    span = (max(identity, last - identity)) * (degrees / 180.0)
    low = max(0, int(round(identity - span)))
    high = min(last, int(round(identity + span)))
    if low == identity or high == identity:
        return None
    return low, high


def _bone_world(anim, skeleton, frame: int, index: int):
    """World transform of a bone at a frame, composed down the clip's own hierarchy (DX space)."""
    local = []
    for i in range(skeleton["bone_count"]):
        t = anim["tracks"][i]
        local.append((t["translation"][frame], t["rotation"][frame]))
    world = [None] * len(local)

    def resolve(i):
        if world[i] is not None:
            return world[i]
        p = skeleton["parents"][i]
        if p < 0:
            world[i] = _compose(([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                                 [0.0, 0.0, 0.0]), local[i][0], local[i][1])
        else:
            world[i] = _compose(resolve(p), local[i][0], local[i][1])
        return world[i]

    for i in range(len(local)):
        resolve(i)
    return world[index]


def layer_axis_effect(base_file: str, layer_file: str, frame: int) -> dict | None:
    """Measure which way a layer frame moves the unit's weapon: bearing and elevation.

    The names must mean what the unit does, and the shipped layer families are not named by axis
    (`aim_stand_horiz` is the bearing sweep, `aim_stand_virt` the elevation sweep — measured by
    composing them and reading the weapon's movement). Bearing is the yaw change of the
    pelvis->weapon vector in the clip's own space (X/Z is horizontal there); elevation is its
    vertical change.
    """
    base = Packfile.open(base_file)
    banim = base.animation()
    bsk = base.skeleton()
    layer = Packfile.open(layer_file)
    lanim = layer.animation()
    lsk = layer.skeleton()
    bindings = layer.animation_bindings()
    if banim is None or bsk is None or lanim is None or lsk is None or not bindings:
        return None
    names = bsk["bone_names"]
    target = lsk["bone_names"][bindings[0]["track_to_bone"][0]]
    slot = _find_bone(names, target)
    if slot is None:
        return None
    # the pointer is the weapon bone on a humanoid rig; a turret rig has no such bone (the Tau drone's
    # layers drive `bone_aim_horiz` and `bone_axis`), so the deepest bone under the driven one is the
    # gun it carries, and the driven bone's parent is the origin.
    pelvis = _find_bone(names, "bip01 pelvis")
    weapon = _find_bone(names, "bip01 r weapon") or _find_bone(names, "bip01 l weapon")
    if pelvis is None or weapon is None:
        parents = bsk["parents"]
        deepest = slot
        for i, p in enumerate(parents):
            chain, cur = [], i
            while cur >= 0:
                chain.append(cur)
                cur = parents[cur]
            if slot in chain and len(chain) > len([1 for _ in ()]) and i != slot:
                if i == slot or slot in chain:
                    pass
            if slot in chain and len(chain) >= 1:
                deepest = i if (slot in chain and len(chain) > 0 and i != slot) else deepest
        # choose the bone with the longest chain that descends from the driven bone
        best, best_len = slot, 0
        for i in range(len(names)):
            chain, cur = [], i
            while cur >= 0:
                chain.append(cur)
                cur = parents[cur]
            if slot in chain and i != slot and len(chain) > best_len:
                best, best_len = i, len(chain)
        weapon = best
        pelvis = parents[slot] if parents[slot] >= 0 else slot
        if weapon == pelvis:
            return None

    def weapon_vector():
        w = [_bone_world(banim, bsk, 0, i) for i in (pelvis, weapon)]
        return [w[1][1][0] - w[0][1][0], w[1][1][1] - w[0][1][1], w[1][1][2] - w[0][1][2]]

    neutral = weapon_vector()
    track = lanim["tracks"][0]
    saved = banim["tracks"][slot]
    banim["tracks"][slot] = {
        "translation": [track["translation"][frame]] * banim["numberOfPoses"],
        "rotation": [track["rotation"][frame]] * banim["numberOfPoses"],
        "scale": [[1.0, 1.0, 1.0]] * banim["numberOfPoses"],
    }
    try:
        moved = weapon_vector()
    finally:
        banim["tracks"][slot] = saved
    yaw0 = math.degrees(math.atan2(neutral[0], neutral[2]))
    yaw1 = math.degrees(math.atan2(moved[0], moved[2]))
    delta = (yaw1 - yaw0 + 540.0) % 360.0 - 180.0
    return {
        "bearing_deg": round(delta, 1),
        "elevation_m": round(moved[1] - neutral[1], 4),
    }


def layer_clip_for(clips: dict, axis: str) -> dict | None:
    """The loadout's aim layer clip for an axis, by the names the shipped loadouts use.

    Standing layers are preferred over the run/crouch variants: the aim action they compose with is
    the standing stance, and mixing a crouch layer into a standing base tilts the body for no reason.
    """
    needles = AIM_AXES[axis]
    candidates = []
    for stem, facts in sorted(clips.items()):
        low = stem.lower()
        if "aim" not in low or not any(n in low for n in needles):
            continue
        if facts.get("tracks") != 1:
            continue
        candidates.append((0 if "stand" in low else 1, stem, facts))
    if not candidates:
        return None
    return sorted(candidates)[0][2]


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

    # aim directions: the stance clip plus one upper-body layer held at its quarter turn. The axis
    # each layer carries is measured from the built pose (see AIM_AXES), so the names mean what the
    # unit does.
    # a loadout whose aim is only a layer pair (the Tau drones rotate a gun mount) has no full-body
    # aim clip, so the idle stance is the base the layers compose onto
    # (a missing action is recorded as {"clip": None}, which is truthy, so the selection must test
    # the clip, not the entry)
    base = next((actions[n] for n in ("aim", "idle") if (actions.get(n) or {}).get("clip")), {})
    if base.get("clip"):
        for axis in ("bearing", "elevation"):
            layer = layer_clip_for(clips, axis)
            if layer is None:
                continue
            quarters = quarter_frames(layer["file"])
            if quarters is None:
                continue
            for frame in quarters:
                effect = layer_axis_effect(base["file"], layer["file"], frame)
                if effect is None:
                    continue
                if axis == "bearing":
                    # a positive rotation about the up axis turns the aim toward +X, which is the
                    # unit's right in the clip's space (checked against the render: the +90 bake
                    # shows the unit's back to a front-right camera)
                    name = "aim_right" if effect["bearing_deg"] > 0 else "aim_left"
                else:
                    name = "aim_up" if effect["elevation_m"] > 0 else "aim_down"
                entry = dict(base)
                entry["layers"] = [{"clip": layer["clip"], "file": layer["file"],
                                    "frame": frame, "layer_of": base["clip"], "axis": axis}]
                entry["layer_effect"] = effect
                actions[name] = entry
        # Loadouts whose aim layers are empty placeholders ship explicit aim-pivot clips instead
        # (measured: every necron `ub_aim_*` is an 8-byte zlib stub, while
        # `necron_overlord_staff_fire_aim_pivotl/pivotr` are full-body). Those are the game's own
        # left/right aim poses, so they are used directly, with the game's own naming.
        if not any(actions.get(n, {}).get("layers") for n in ("aim_left", "aim_right")):
            for suffix, name in (("pivotl", "aim_left"), ("pivotr", "aim_right")):
                hit = next((v for k, v in sorted(clips.items())
                            if "aim" in k.lower() and k.lower().endswith(suffix)), None)
                if hit:
                    actions[name] = dict(hit)
                    actions[name]["aim_source"] = "shipped aim pivot clip"

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
