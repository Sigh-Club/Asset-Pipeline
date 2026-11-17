# DoW2 unit stance — the reference, read from the shipped game

> Audience: developers. This is the stance specification the rig work has to match. It exists
> because several sessions authored poses from imagination and produced "arms out at the chest"
> stances that no DoW2 unit ever holds, while every numeric gate passed.

## Source images

Taken from the official Steam store screenshots for Dawn of War II (app 15620), Chaos Rising
(app 20570) and Retribution (app 56437) and stored beside this file:

- `evidence/dow2-stance/marines_idle_thunder_hammer.jpg`
- `evidence/dow2-stance/orks_idle_hunched.jpg`
- `evidence/dow2-stance/marine_aim_two_handed_bolter.jpg`

## What the units actually do

**Idle (standing, weapon in hand):**

| element | measured from the screenshots |
|---|---|
| torso | **hunched forward.** The head sits forward of the hips and the shoulders are rounded. Orks are bent almost double. |
| legs | **wide stance, knees bent**, weight low and planted. Not a straight-legged A-pose stand. |
| weapon hand | the weapon is carried **low, in the right hand, with a bent elbow**, muzzle pointing down and forward. It is not held up at the chest. |
| off hand | **hangs relaxed** at the side. It is not on the weapon during idle. |
| shoulders | the pauldrons are enormous rigid plates that sit *over* the shoulders; they do not deform with the arm. |

**Two-handed aim (firing, bracing):**

| element | measured |
|---|---|
| weapon | at **chest height**, both hands on it, **both elbows bent**, muzzle forward. |
| torso | upright to slightly forward, turned into the weapon. |
| legs | still wide and planted. |

**Orks:** the same construction with a much deeper forward fold — the torso is close to horizontal and
the head is low and forward.

## What this rules out

- Arms extended straight out in front at the chest, hands together: **wrong**. That is neither the
  idle nor the aim; the reference always has bent elbows and the weapon closer to the body.
- Standing upright with straight legs: **wrong**. Every DoW2 unit stands with a bent-knee, wide base.
- A weapon carried at chest height while idle: **wrong**. It hangs low in the right hand.
- Smoothly skinned pauldrons: **wrong**. They are rigid plates and must be bound to one bone.

## The loadout rule — the actual mechanism

This is the part that was missing, and it is visible in the shipped file layout: **DoW2 ships one
animation set per weapon loadout, and the game selects the set from the weapon the unit carries.**

```
race_ig/troops/gaurdsman/animations/        melee_blade_range_pistol  melee_fist_range_pistol
                                           range_burst  range_heavy_shot
race_necron/troops/necron_overlord/animations/   melee_staff
race_ork/troops/boy/animations/            combo_blade_pistol  dakka_deff_gun  deffgun_beamy_common
                                           melee_blade_range_pistol  range_burst  range_flamer
```

A staff unit is animated by the `melee_staff` set. A lasgun guardsman is animated by `range_burst`.
The arm poses in each set are authored for that weapon, so the hand arrives at the weapon already
correct and the weapon is a rigid child of the hand.

**What we were doing instead:** one clip set, authored for a two-handed rifle carry, played on every
unit regardless of what it carries. That is why a Necron with a staff held it like a rifle, why a
sword unit reads wrong, and why the arms tear — the clip demands arm rotations the body was never
skinned for.

**The construction that follows:**

1. A unit is a `(body, weapon, loadout)` triple. The loadout is chosen by the weapon, never a single
   global set.
2. Clips are retargeted from that loadout's directory only.
3. The weapon is attached to the hand with its own authored hold transform (see `WEAPON_HOLD` in
   `tools/blender/dow2_build_unit.py`): rifle carried low with the barrel forward, staff upright in
   one hand, blade up.
4. Nothing is solved at runtime and nothing reaches for the weapon. The pose comes from the clip; the
   weapon follows the hand.

## Consequence for the rig

The shipped skeleton's own reference pose (3ds Max Biped, arms hanging at ~64° below horizontal,
`Bip01 L/R Weapon` co-located with the hands) is already close to the idle stance for the arms. The
gap between our build and the reference is therefore **the legs and the torso, not the arms** — and
the tearing is a skinning defect, not a posing defect.

## How to use this

1. Before authoring or judging any unit pose, open the three images and compare the silhouette.
2. Judge the render at game camera distance against the reference, not in isolation.
3. A pose that passes every numeric gate but disagrees with these images is still wrong.

---

# The import rules that actually work (measured 2026-11-17)

Four rules, each established by a build that failed without it and passed with it. They are the
difference between "DoW2's own unit, standing in its own idle" and "a pile of shards".

## R1. Rig the unit with the skeleton from the SAME FILE its clips come from

Measured: building the rig on `guardsman.hkx` and then applying `fb_idle_stand_01` gave **every bone a
~180° delta** — a constant frame difference between two skeletons, not a pose. The mesh tore 23 %.
Building the rig from `animations/range_burst/fb_idle_stand_01.hkx` itself makes the rig's reference
pose identical to the clip's, and the same idle then measures **0.000 torn edges / 0.000 inverted**.

Do not mix a unit's `.hkx` with a loadout's clips. The `.hkx` and the clips are different skeletons
(45 vs 46 bones on the guardsman) with different reference frames.

## R2. The wargear part list must contain the BODY, not only armour overlays

`render_models` sometimes lists only armour pieces. `war_boss_epic` resolves to a single shoulder/chest
part, so the built "unit" is a scattering of plates with no body. `flak_common` and
`sorcerer_defying_death` resolve to complete bodies and build correctly.

De-duplicate quality tiers (the same body appears as `_common`, `_epic`, `_rare` …) but do not
de-duplicate distinct sub-parts (`ig_armour_common_a/b/c` are genuinely different pieces).

## R3. A unit whose skeleton the game does not ship cannot be source-faithful yet

Recorded gaps, all data-side:

| unit | why |
|---|---|
| necron overlord | its clips are not Havok packfiles (`magic 0x0003da78`) and its `.model` has no `FOLDSKEL`; it currently borrows the Imperial Guard skeleton and explodes |
| eldar farseer | the farseer ships no skeleton; the build borrows the banshee's, whose robes and runes are authored for a different rig |
| tyranid lictor | built on the carnifex's loadout; same class of mismatch |

The fix is to find the skeleton each of those units actually uses (`.hkanim` clip bank, a sibling
troop directory, or the `.model` marker bones such as `rig_rleg_calf` on the overlord) — not to
tune the rig.

## R4. Weapon hold is authored per weapon, and the clips must match the loadout

See the loadout table above. A staff unit animated by rifle clips will hold the staff like a rifle no
matter how correct the weapon transform is, because the arm pose comes from the clip.

## What a correct build looks like

`asset-pipeline/tools/build_source_lab_all.sh` is the table. The two entries that pass are the two
whose wargear resolves to a complete body **and** whose rig was built from its own loadout clip:
`dow_ig_guardsman` and `dow_chaos_sorcerer`.
