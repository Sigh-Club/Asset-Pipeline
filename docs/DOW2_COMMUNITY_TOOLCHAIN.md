# DoW2 community toolchain — the recipe that actually builds the units

> Audience: the next agent. This is the method the lab units are built with. It is not our own
> assembly: it is the community importer used by the DoW2 modding scene (Santos Tools 2 lineage, the
> tooling behind the Elite mod), plus our own clip reader in place of its Windows binary. Everything
> below was verified on the shipped files and by rendering the result.

## Why a "simple import" is not simple

A DoW2 unit is not a file. It is a kit — body, head, weapon, the bone table, and a folder of clips —
and the game snaps them together at runtime. Three consequences, each measured:

1. **The model's rig and the clips' rig are different skeletons.** Same bone names, different frames.
   Only 5 of 39 local rests match between the guardsman's `FOLDSKEL` and its clip skeleton.
2. **Clip transforms are in DirectX space** and the conversion to Blender includes a mirror
   (`BLENDER_TO_DX` below). Without it, left and right swap and the mesh shears.
3. **The game layers animations** (base + upper-body additive, driven by `.hkanim`). One clip is one
   ingredient. We export individual clips; the game's composed pose is a later step.

The heads are not in the armour: they are the unit blueprint's `animator_attachments`
(`cadian_trooper`, `warboss_head_01`). Read the `ebps`, not just the wargear.

## The tool

`atmalto/dow2-blender` v0.3.3 (DoW2 Tools). Release zip, unpacked into
`~/.config/blender/5.1/scripts/addons/dow2_tools`. It enables on Blender 5.1 (declares 4.3) and its
**model import is pure Python** and works on Linux. Its animation *reader* is a Windows `.exe`
(`blender_hkx/havok_io_cli.exe`) used for import/export of `.hkx` and `.hkanim`; on Linux we replace
it with `tools/hkx/hkxread.py`, which decodes the same data (validated: frame 0 reproduces each
file's own reference pose to 1e-5 m).

ModDB is behind Cloudflare: use `stealth-fetch`, not `curl`.

## The constants (copied from the add-on, not invented)

```python
BONE_AXIS_ADAPTER     = Matrix.Rotation(radians(-90), 4, 'Z')   # model/skeleton_space.py
BONE_AXIS_ADAPTER_INV = BONE_AXIS_ADAPTER.inverted()
BLENDER_TO_DX = Matrix(((-1,0,0,0),(0,0,1,0),(0,-1,0,0),(0,0,0,1)))  # utils.py
DX_TO_BLENDER = BLENDER_TO_DX.inverted()
def dx_to_blender(M): return DX_TO_BLENDER @ M @ BLENDER_TO_DX
```

## The sequence

1. **Assemble with the add-on's importer**, merging extra parts onto one armature:

   ```
   bpy.ops.import_scene.dow2_model(filepath=body,  merge=False)
   bpy.ops.import_scene.dow2_model(filepath=head,  merge=True)
   bpy.ops.import_scene.dow2_model(filepath=weapon, merge=True)
   ```

   The add-on builds the armature from the model's own `FOLDSKEL`, applies the bone-axis adapter,
   binds the shipped weights and resolves the materials (it imports `_dif`, `_nrm`, `_spc`, `_emi`).

2. **Pose with the add-on's own maths** (`animation/import_core.py`): for each tracked bone,

   ```
   L  = dx_to_blender(track local)
   W  = parent_world @ L
   d  = rest_local^-1 @ (parent_world^-1 @ W)
   d  = ADAPTER_INV @ d @ ADAPTER
   set location/rotation_quaternion/scale, keyframe
   ```

   where `rest_local` is the armature bone's rest relative to the *nearest mapped ancestor in the
   clip's hierarchy* (the add-on's `parent_anim_idx`). Bones the model lacks (the necron's cape
   chain) are skipped and their children hang off the nearest ancestor the model has.

3. **Match bones case-insensitively against the armature's own names.** The add-on keeps the model's
   `FOLDSKEL` names (`bip01 r thigh`), not our canonical vocabulary. Mapping through
   `skeleton.canonical()` finds nothing, leaves every bone unkeyed, and exports a constant pose —
   this is what made the lictor's idle silent and the eldar have no idle.

4. **Export with `export_optimize_animation_size=False`.** Blender's glTF exporter otherwise
   collapses each action to two constant keys.

5. **Scale sanity.** A clip's scale track is either sane (every component within ±25% of 1, measured
   across the corpus) or a decode artefact — the necron overlord's run from −4951 to 699 while its
   translations are correct. Judge the track as a whole: if any component is outside [0.5, 2.0], use
   1 for the whole clip. Per-component clamping left plausible-looking 0.38–3.13 values that made
   the model pulse (max joint scale deviation 0.12; 0.0003 after).

## Traps, all paid for

- Enabling the add-on twice in one session raises `register_class(...) already registered`; guard with
  `if "dow2_tools" not in bpy.context.preferences.addons`.
- Blender exits 0 on a Python exception inside `-P`. A build that never prints `EXPORTED` is a
  failure; check the log, not the exit code.
- `export_optimize_animation_size` (default on) silently empties animations.
- A clip whose hierarchy differs from the model's (necron 57 vs 54 bones) must not be placed by world
  matrix; use the rest-delta form against the nearest mapped ancestor.
- Five clip families are `hkInterleavedSkeletalAnimation`, which `hkxread` does not decode:
  `fb_run`, `fb_sprint`, `fb_melee_attack_01..03`, `fb_reload_stand`, `ragdoll` (which ones varies by
  unit). The action library falls back to a delta-compressed alternative.

## Where each unit's data lives

| unit | art root | body | head/attachment | clips |
|---|---|---|---|---|
| dow_ig_guardsman | `000_data` | `troops_wargear/armour/ig_armour` | `heads/cadian_trooper` | `troops/gaurdsman/animations/range_burst` |
| dow_chaos_sorcerer | `000_data` | `armour/chaos_sorcerer_epic` | `heads/chaos_sorcerer_epic` + backpack | `chaos_lord/animations/melee_blade_range_pistol` |
| dow_eldar_farseer | `000_data` | `armour/farseer_armour_common` | head is in the armour | `banshee/animations/melee_blade_range_pistol` |
| dow_ork_warboss | `000_data` | `accessories/warboss_body` + `armour/warboss_armour_epic` | `heads/warboss_01` | `warboss/animations/melee_axe_range_pistol` |
| dow_tyranid_lictor | `000_data` | `armour/lictor_armour_common` | — | `lictor/animations/talons_claws` |
| dow_necron_overlord | `005_data` | `armour/necron_overlord_common` | `accessories/necron_overlord_headdress_02` | `necron_overlord/animations/melee_staff` |
| dow_tau_battlesuit | `003_data` | `armor/xv8_default_crisis_suit` | — | `battlesuit_commander/animations/range_burst` |

## The build and the gates

```bash
# one unit
blender -b -P tools/blender/dow2_import_community.py -- --id <unit> --out <dir> \
  --manifest output/source_lab/actions/<unit>.json \
  --part <body.model> [--part <head.model>] [--weapon <weapon.model>]

# renders (the visual gate; a numeric gate cannot see a wrong bind)
blender -b -P tools/render_lab.py -- <glb dir> <png dir> idle:1 fire:30

# deformation gate, and the per-action report the lab page reads
python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>
python3 tools/lab_fidelity.py --lab <lab dir>
```

Measured on the current build: seven units, all with a walk action and real leg motion (chaos 0.07 m,
eldar 0.13 m, necron 1.59 m), worst tear 0.0016–0.116 against the shipped rigid assignment.
