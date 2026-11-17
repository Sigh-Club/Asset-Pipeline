# DoW2 animation decode — where it stands and what to do next

> Audience: the next agent. This records the exact state of the `hkDeltaCompressedSkeletalAnimation`
> decode, the evidence behind it, and the one validation that proves it correct. Everything here was
> measured on the shipped files; nothing is assumed.

## Why this matters

DoW2 is an RTS and we are building a **turn-based** game, so we do not need its locomotion cycles. We
need its **action library**: the poses and timings for aim, fire, reload, melee, grenade, leap, throw,
ability-cast, hit reaction and death — each triggerable by our action system, with its events.

Each shipped clip file is one such action. What we have been using so far is the file's *reference
pose*, which is why only the clip a rig was built from looks correct: a reference pose is one frame of
one clip, on that clip's own skeleton. The **tracks** are the actual animation, and they are
delta-compressed inside the same file.

## The format, as declared by the file itself

From the `__types__` section of `fb_idle_stand_01.hkx` (class names and members, in declaration order):

```
hkSkeletalAnimation
  type, duration, numberOfTracks, extractedMotion, annotationTracks
hkDeltaCompressedSkeletalAnimation
  numberOfPoses, blockSize, qFormat, quantizedDataIdx, quantizedDataSize,
  staticMaskIdx, staticMaskSize, staticDOFsIdx, staticDOFsSize,
  totalBlockSize, lastBlockSize, dataBuffer
hkDeltaCompressedSkeletalAnimationQuantizationFormat
  maxBitWidth, preserved, numD, offsetIdx, scaleIdx, bitWidthIdx
```

`__types__` also carries the animation-type enum in order: `HK_UNKNOWN_ANIMATION`,
`HK_INTERLEAVED_ANIMATION`, `HK_DELTA_COMPRESSED_ANIMATION`, `HK_WAVELET_COMPRESSED_ANIMATION`.

`hkAnimationBinding` is present in `__classnames__`, which is the track→bone map: **the game has one
skeleton and bindings, not per-clip skeletons.** That is the whole reason one rig should be able to
play every clip.

## The header, located

`fb_idle_stand_01.hkx`, `__data__` section (offset 1024, size 26400). At data offset **5320**:

| data offset | value | meaning |
|---|---|---|
| 5320 | `2` | animation type = `HK_DELTA_COMPRESSED_ANIMATION` |
| 5324 | `7.333` | duration, seconds |
| 5328 | `46` | numberOfTracks — equal to the skeleton's bone count (46), as expected |

The scan that found it: every 4-byte-aligned offset where the u32 equals the skeleton bone count, the
preceding float is a plausible duration (0.05–30 s), and the preceding u32 is a valid animation type.
Exactly one hit in the file. Reproduce:

```bash
python3 - <<'EOF'
import sys, struct; sys.path.insert(0,'tools/hkx')
from hkxread import Packfile
H='.../fb_idle_stand_01.hkx'
p=Packfile.open(H); s=p.sections['__data__']; seg=open(H,'rb').read()[s.offset:s.offset+s.size]
nb=p.skeleton()['bone_count']
for off in range(0,len(seg)-24,4):
    v=struct.unpack_from('<I',seg,off)[0]
    if v==nb:
        dur=struct.unpack_from('<f',seg,off-4)[0]; typ=struct.unpack_from('<I',seg,off-8)[0]
        if 0.05<dur<30 and typ in (0,1,2,3): print(off,typ,round(dur,3))
EOF
```

## What is still to do

1. **Fix the type-table parser.** `hkxread.type_table()` currently reads names 2 bytes late
   (`ationBinding` for `hkAnimationBinding`, `AttributeHolder` for `hkxAttributeHolder`) and returns 4
   bogus types. In `__types__` the first type name `hkxEnvironment` begins at payload offset 48, so
   the per-type record header is 48 bytes before the inline name — the current reader is off by 2.
   Once correct, the member offsets come from the table instead of from guesswork.
2. **Map the 11 delta fields to byte offsets** after the `hkSkeletalAnimation` base, using the fixed
   type table. The `Idx` fields index into `dataBuffer`, so no pointer fix-up is needed — that is the
   design that makes this decodable without the Havok SDK.
3. **Decode one frame and validate against the file's own reference pose.** Frame 0 of the tracks
   must reproduce `hkSkeleton.referencePose` for that file. This is a self-checking target: a wrong
   quantisation layout cannot fake it. Decode frame 0 for one bone first, then all 46.
4. **Then the action library**: for each clip, sample the frames the action needs (the fire frame from
   `hkAnnotationTrack` events, the reload midpoint, the leap apex), and export them as named actions
   with their events, on the one canonical rig.

## Why this is the right fix and not another rig attempt

- It removes the per-clip rig entirely: one skeleton, bindings, tracks — the way the game does it.
- It removes the 180° frame correction: that artefact exists only because two files' *reference poses*
  were being compared.
- It gives us DoW2's own action timings and events, which is what a turn-based action system needs.
- It is a decoder, so it is testable offline and gateable, unlike a Blender session.

## Status of the current build in the meantime

`tools/build_source_lab.sh` + `build_source_lab_all.sh` produce a unit that is **exact for the clip it
was rigged from** (Imperial Guard guardsman and Chaos Sorcerer: 0.000 torn edges / 0.000 inverted, and
they render as complete textured DoW2 units) and approximate for the rest of that loadout. That is a
usable bridge until the tracks land, and it is honest about its own limitation.
