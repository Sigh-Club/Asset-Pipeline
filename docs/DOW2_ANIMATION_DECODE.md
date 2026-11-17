# DoW2 animation decode — solved, with the measurements

> Audience: the next agent. This records the `hkDeltaCompressedSkeletalAnimation` format as the
> shipped files declare it, the decoder that reads it, the validation that proves it, and what is
> still not decoded. Everything here is measured on the shipped data; nothing is assumed.

## What was wrong, in one paragraph

Every shipped clip file carries a skeleton whose reference pose is **that clip's own pose**, plus
delta-compressed animation tracks. The pipeline used the reference pose, so a unit was exact only for
the clip its rig was built from; applying another clip file's reference pose is a *frame difference*,
not a pose (measured: ~180° per bone, 23 % torn edges). That is what broke the rig lab's clip
switching. The tracks are the animation, and they decode.

## The format, as the file declares it

Packfile: `0x57E0E057 0x10C0C010`, version 4, contents version `Havok-4.5.1-r1`, layout
`bytesInPointer=4, littleEndian=1, reusePaddingOptimization=0, emptyBaseClassOptimization=1`.

Section descriptor = 16-byte NUL-padded tag, a `0xff000000` end marker, then seven u32:
absolute data start, local/global/virtual fixup offsets, exports, imports, data-buffer size.

`__classnames__` = u32 signature hash, a TAB, then the NUL-terminated class name. (An earlier reader
treated the TAB as a length byte and advanced two bytes per record — that was the "misaligned by 2
bytes" bug, and it returned `ationBinding` for `hkAnimationBinding`.)

`__types__` = class records: 48-byte header (class version at +8, declared-enum count at +20,
declared-member count at +28), the class name, an optional enum block, member records (20 bytes:
type at +12, subtype at +13, cArraySize at +14, member offset at +18) and the member names.
`hkClassMember::Type` is the file's own enum: 7 = int32, 8 = uint32, 11 = real, 16 = qstransform,
20 = pointer, 24 = enum, 25 = struct, 26 = simplearray, 29 = cstring.

Object locations come from the virtual fixups (`dataoffset, section, classnameoffset`) and pointers
from the local/global fixup tables — so an object is found by its declared class, not by scanning for
plausible values.

For `fb_idle_stand_01.hkx` the animation object is at data offset 5312, and the type table gives:

```
hkSkeletalAnimation      type +8, duration +12, numberOfTracks +16, extractedMotion +20,
                         annotationTracks +24 (hkArray = {ptr,size}: 8 bytes in this version)
hkDeltaCompressed…       numberOfPoses +32, blockSize +36, qFormat +40, quantizedDataIdx +60,
                         quantizedDataSize +64, staticMaskIdx +68, staticMaskSize +72,
                         staticDOFsIdx +76, staticDOFsSize +80, totalBlockSize +84,
                         lastBlockSize +88, dataBuffer +92 (pointer)
hkDeltaCompressed…QuantizationFormat  maxBitWidth +0, preserved +1, numD +4, offsetIdx +8,
                         scaleIdx +12, bitWidthIdx +16
```

`staticMaskSize` and `staticDOFsSize` read as unrelocated pointers in this build and are not needed by
the decoder; the `*Idx` fields are the serialized offsets that matter, and they are consistent
(staticMaskIdx 0, staticDOFsIdx 92 = 46 masks x 2 bytes, offsetIdx 1036 = end of the static DOF block).

## The decoder

`tools/hkx/hkxread.py`:

* `Packfile.classnames()`, `.type_table()`, `.objects_by_class()`, `.pointers()` — the container.
* `Packfile.animation()` — the tracks. Block format: per block, per dynamic DOF, `preserved` absolute
  floats then a bit-packed delta stream dequantised as `ref + offset + code*scale/(2^bits-1)`; the
  static-mask table says per track whether position/rotation/scale are dynamic, static or identity and
  which sub-components are dynamic; rotations with W = ±2 are the smallest-three encoding.
* `Packfile.animation_events()` — `hkAnnotationTrack` names/annotations (empty in the shipped troop
  clips; the timed action events live in the unit's `.motiontree`, see below).
* `validate_animation(path)` — the gate.

## The validation (self-checking, cannot be faked)

Frame 0 of the decoded tracks must reproduce the same file's `hkSkeleton.referencePose`.

```
fb_idle_stand_01.hkx: 221 frames, 7.333 s (30.14 fps), 46 tracks, 57 dynamic DOFs
  max translation error 5.5e-06 m
  max rotation error    3.40 deg   (8-bit delta quantisation)
  dynamic DOFs consumed 57/57, static DOFs consumed 944/944, quantised bytes exact
```

Corpus sweep over the packaged source set (243 clips): **236 decoded, 0 structural failures** (every
clip consumes exactly its declared quantised and static-DOF ranges). 203 full-body clips reproduce
their reference pose at frame 0; 2 full-body clips start elsewhere; 31 are partial-track clips
(upper-body/aim overlays, e.g. `aim_stand_horiz` animates 1 track of 46) and cannot reproduce a full
body by construction.

Not decoded: 5 clips are `hkInterleavedSkeletalAnimation` instead of delta-compressed
(`fb_run`, `fb_sprint`, `fb_melee_attack_01..03`, `fb_reload_stand`, `ragdoll` — which of them varies by
unit). `Packfile.animation()` returns None for those; the action library then picks a delta-compressed
alternative where one exists.

## The action library

`tools/dow2/action_library.py` turns the clips into named actions with their shipped timing and events:

* action set: idle, idle_combat, idle_crouch, aim, fire, reload, melee, grenade, ability, hit,
  thrown_getup, death, death_sync, walk, run, pinned;
* events: the unit's `.motiontree` carries `FOLDEVCT`/`DATAEVNT` = `clip -> (time, event)` and
  `FOLDACTC`/`DATAACTN` = the event's definition (type + parameters). Measured on the guardsman's
  `fb_fire_stand`: 8 shots at 0.209 s intervals (`att_bolter_fire_fx`,
  `att_weap_ranged_fire_sfx`); reload: gun chunk/cock/clinks foley at 0.30–1.80 s; death:
  `att_voice_die_sfx` at 0 s and `trigger_bodyfall` at 0.587 s;
* where a clip ships no event, the manifest records a *measured* effect frame (the frame where the
  acting hand moves fastest in world space) and flags it `derived`.

`tools/build_source_lab.sh` runs the library and passes the manifest to the Blender builder, which
keys the real tracks as glTF actions named by the action, at the clip's own rate, and writes the
timing/events sidecar `<unit>.actions.json` beside the GLB.

## Retargeting, and why the first attempt tore

The unit rig is built from one clip file's skeleton. Transferring another clip's *pose* needs a root
frame correction (the legacy path). Transferring *motion* must not: each clip's reference pose is that
clip's own bind pose (measured: fire's reference differs from idle's by up to 28° per bone), so the
correct retarget is

```
motion_i(frame) = W_i(frame) @ inv(W_i(reference of that same clip))
target_i(frame) = BASE @ motion_i(frame) @ inv(BASE) @ rest_i
```

Anchoring to the unit's rest instead bakes the difference between two clips' bind poses into the
animation and tears the mesh (measured: 12–19 % torn edges on every action at frame 1). With the
relative form, frame 1 of every action measures 0.0–0.02 torn edges.

## Gates

* `python3 tools/rig_fidelity.py <unit.glb> --clip <action> --frame <n>` — deformation gate. It now
  derives the clip's own key rate (assuming 24 fps sampled a 30 fps clip between keys and reported
  4–9 % tearing on an intact mesh), and it measures a **rigid reference** (the same mesh bound 100 %
  to each vertex's dominant joint). A pose that separates the shipped rigid plates is not a bind
  defect: DoW2 ships armour plates as one bone at full weight, so plates slide apart at extreme poses
  (guardsman death: blend 0.0893, shipped weight column 0.1061, 100 % rigid 0.0867 — the three agree).
  The gate exempts a metric only when the build is no worse than that reference.
* `python3 tools/lab_fidelity.py --lab <lab>` — regenerates `fidelity.json` from every unit's action
  set, measuring the worst keyframe of every action.
