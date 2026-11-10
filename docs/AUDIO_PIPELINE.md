# Audio Pipeline — Licensed Libraries, SFX Design, Mixing and Delivery

**Status**: implemented (v0.1.0) · **Last updated**: 2026-11-10
**Owner**: `tools/audio/` · **Gate**: `tools/audio/build_bank.py --verify`

This document is the operating manual for game and website audio: where the
source recordings come from, what their licences actually allow, how the bank is
designed and mastered, how it is mixed at runtime, and the evidence gate that
must pass before a bank ships.

It is deliberately separate from `DEVELOPMENT.md` (sprite/3D programme) because
audio has its own licence, loudness and delivery constraints.

---

## 1. What IoA needs (the requirement, from the repo)

The game's audio surface is defined by `frontend/src/phaser-game/utils/AudioRegistry.ts`
and `docs/architecture/COMBAT_PRESENTATION_AND_FEEL.md` §3.5, plus
`docs/skills/xcomcombatskill.md` §11. The required cue classes are:

| Class | Purpose | Example cues |
|---|---|---|
| Weapon fire | faction-scoped report, 3 variants each | `directorate_fire`, `cinderborn_fire` |
| Impact | armour/flesh hit, crit stinger | `directorate_hit`, `cinderborn_hit`, `impact_crit` |
| Miss | quiet whiff, deliberately low | `directorate_miss`, `cinderborn_miss` |
| Movement | boots on plate / on rubble | `directorate_move`, `cinderborn_move` |
| Vox | radio/comms bed + beep | `*_vox_ready` |
| Battle ambience | looping faction bed | `ambient_directorate`, `ambient_cinderborn` |
| Music / stingers | theme, level-up, turn transition | `theme`, `level_up`, `turn_start` |
| UI | confirm/deny/hover, every action | `ui_click`, `ui_hover`, `ui_error`, `ui_success` |
| World | explosions, melee, reload, death | `explosion_large`, `melee_impact`, `reload`, `death_cry` |
| Website | navigation and form feedback | `web_hover`, `web_click`, `web_page`, `web_error`, `web_success` |

The existing bank in `Imperium-of-Ash/frontend/public/assets/audio/` is a
**procedural placeholder** (`Imperium-of-Ash/scripts/generate_combat_audio.py`,
numpy/scipy synthesis). The project owner's verdict is recorded in
`frontend/src/utils/audioSettings.ts`: *"the audio is horrible"* — audio is off
by default. That is the problem this pipeline exists to solve, and it is why the
bank must be judged by measurement (section 6) rather than by "it rendered".

---

## 2. Source libraries — what is actually usable

Bulk libraries were evaluated against four criteria: (a) commercial use in a
game **and** a website, (b) bulk download without a per-sound API token or a
logged-in browser session, (c) terms stated in writing by the rights holder,
(d) provenance that can be recorded per file.

| Source | Licence | Attribution | AI training | Bulk fetch | Verdict |
|---|---|---|---|---|---|
| [Sonniss #GameAudioGDC](https://sonniss.com/gameaudiogdc/) 2015–2024, 2026 | Sonniss EULA v2.0 (27 Aug 2026): royalty-free, worldwide, unlimited projects, commercial | none | **prohibited** | Yes — direct HTTPS, resumable, ~46 MB/s | **Primary SFX library** |
| [Kenney](https://kenney.nl/assets/category:Audio) audio packs | CC0 1.0 | none | permitted | Yes — signed-link JSON API | **Primary UI/prototype library** |
| [Pixabay](https://pixabay.com/service/license-summary/) audio | Pixabay Content Licence | none | permitted (no opt-out clause found) | Yes via CDN, no API key for direct files | Music/ambience supplement |
| [OpenGameArt](https://opengameart.org) CC0 filter | per asset (filter CC0) | none for CC0 | varies | Yes — direct file URLs | Supplement, curation-heavy |
| [Freesound](https://freesound.org) | per sound CC0 / CC-BY / CC-BY-NC | depends | depends | **No** — originals are OAuth2-only; API token required | Targeted supplement only |
| [ZapSplat](https://zapsplat.com/license/) | free tier | **required** | — | No (login) | Rejected as a base |
| [BBC Sound Effects](https://sound-effects.bbcrewind.co.uk/licensing) | RemArc | — | — | No | **Rejected** — personal/education only, not commercial |
| freepd.com | CC0 | — | — | — | **Dead** — closed permanently in 2025 |

### 2.1 Sonniss — the primary library

Direct, resumable URLs are published on the index page (all verified with HTTP
200 + `Content-Length` on 2026-11-10):

```
https://downloads.sonniss.com/Sonniss.com-GDC2026-GameAudioBundle1of5.zip   (1.30 GB)
https://downloads.sonniss.com/Sonniss.com-GDC2024-GameAudioBundle1of9.zip   (2.93 GB)
https://downloads.sonniss.com/Sonniss.com%20-%20GDC%202020%20-%20Game%20Audio%20Bundle%20Part1of14.zip
... one URL per part; part counts and templates are in tools/audio/sources.py
```

Licence constraints that matter to this project:

- Commercial use in games/websites: **allowed**, no attribution.
- Redistribution of the raw sounds (e.g. shipping the library itself): **not**
  allowed — which is one reason only the derived, processed bank is committed.
- **AI/ML training is prohibited.** If IoA later fine-tunes an audio model, the
  Sonniss-derived files must be excluded from that training set. Kenney (CC0) and
  Pixabay are safe for training. This is recorded as a decision constraint in
  §8.

Content shape: the bundles are *samples of many commercial libraries*, with
UCS-style category prefixes (`WEAPFire_…`, `EXPLImp_…`, `AMBSubn_…`). Coverage
is broad (weapons, explosions, foley, ambience, vehicles, creatures, UI) but
shallow per category — a cue may only have a handful of candidates in a given
year. That is why the fetcher takes multiple years.

### 2.2 Kenney — the UI and prototype library

Kenney publishes CC0 audio packs. Downloads are behind a donate splash on the
website, but the site exposes a signed-link API that the fetcher uses directly:

```
GET https://kenney.nl/download-link/<hex("assets/<slug>")>  ->  {"url": "<signed>"}
```

Verified working for `interface-sounds` (100 files), `impact-sounds`,
`sci-fi-sounds`, `rpg-audio`, `digital-audio`, `music-jingles`, `ui-audio`,
`voiceover-pack`, `casino-audio`. Files are 44.1 kHz OGG; licence text ships in
each zip as `License.txt` (CC0).

### 2.3 Fetching

```bash
# UI/prototype library (~30 MB)
python3 tools/audio/fetch_library.py --source kenney

# primary SFX library: start with the modern bundles
python3 tools/audio/fetch_library.py --source sonniss --years 2026 2024

# the full ten-year archive (~110 GB, ~13k-30k files)
python3 tools/audio/fetch_library.py --source sonniss --years all

# rebuild the search index after adding years
python3 tools/audio/fetch_library.py --index
```

Raw library location: `assets/_audio_library/` (gitignored, ~120 GB).
`MANIFEST.json` records source, URL, byte count, SHA-256, file count and licence
per downloaded archive; `LICENCE.txt` is written into each source directory.

---

## 3. Cue design and mixing

`tools/audio/cues_ioa.json` is the cue sheet: per cue it names candidate queries
(UCS CatID prefixes and filename tokens), the design recipe, a duration ceiling,
variant count and gain trim. `tools/audio/build_bank.py` executes it.

Per cue the chain is: **decode → trim/de-click → design chain (EQ, dynamics,
transient shaping) → convolution reverb send → variant pitch offset → loop-seam
crossfade (beds) → loudness/peak levelling → true-peak limiting → OGG + M4A
encode**. The reverb impulse is synthesised in-process (`make_ir`) so no external
IR asset is needed and the bank stays reproducible.

Design intent by class (this is the "grimdark" translation, not a generic preset):

| Class | Chain intent |
|---|---|
| Weapon fire | transient crack kept intact, 90–120 Hz thump, 3 kHz presence, short slap-back, limited |
| Heavy/incendiary | sub-70 Hz weight, low-passed body, longer tail, heavier compression |
| Armour impact | 2.1/4.2 kHz metallic ring, tight attack, short room |
| Flesh impact | low-pass 4.5 kHz, 160 Hz body, no ring |
| Miss/whiff | band-limited air, no low end, trimmed and trimmed quiet |
| Vox | 280–3600 Hz comms band, heavy compression |
| Ambience | 20 s bed, 0.6 s circular crossfade, dark tilt, loop-safe |
| UI | 420 Hz high-pass, 2.6 kHz click emphasis, very short, no tail |

Candidate selection is deterministic: token/CatID score, then shorter recording,
then path. Every processed cue records the exact source path(s) in the bank
manifest, so a bank can be rebuilt byte-for-byte from the same library.

### 3.1 Variants and repetition control

Weapons, impacts, movement and UI clicks ship 2–3 variants. Each variant is
pitch-shifted by a fixed musical step (±1 semitone, 1.6 semitones) using a
rate/resample/atempo pair, so the round-robin is not the same sample twice. The
game additionally applies a ±7% playback-rate jitter at runtime
(`CombatTheatreManager.playCombatSound`), which the bank is mastered to survive
(pitch shifts up to ~7% do not expose artefacts at these bandwidths).

### 3.2 Loop construction

Beds are cut to length and joined with an equal-power circular crossfade over
0.6 s (`loop_seam`). `build_bank.py --verify` measures the RMS discontinuity
across the join and fails the cue above 6% of the file's own RMS.

---

## 4. Loudness and levelling

Targets are stored in the cue sheet and applied per class. They are *per-asset*
targets, which is the complement of the platform standard:

- Platform guidance (Sony ASWG-R001 v1.2, 03/2024) sets title-level average
  loudness at **-24 ±2 LKFS** for home consoles and **-18 ±2 LKFS** for portable,
  with a **-1 dBTP** ceiling, measured per ITU-R BS.1770-5. Source:
  <https://github.com/Sony-ASWG/Loudness> (quoted from the PDF: "should not
  exceed -1 dBTP").
- A browser game cannot hit a title-level target by normalising every asset to
  it; it needs **consistent relative levels** so cues mix predictably. The bank
  therefore normalises each asset to a fixed class level and leaves the title
  loudness to the runtime master bus.
- Practical per-asset targets used here: one-shots and stingers peak-levelled to
  their class ceiling (-1 / -1.5 dBTP), UI peak-levelled to -3 dBTP, ambience
  -24 LUFS and music -20 LUFS. Ceilings: -1 dBTP for SFX, -3 dBTP for
  UI/music, -6 dBTP for beds. Beds with a high crest factor land quieter than
  their LUFS target because the ceiling binds; the gate accepts that case and the
  manifest records the achieved value.

Measurement method, and why it is not uniform:

| Asset length | Method | Why |
|---|---|---|
| beds, music (≥ 2.5 s, ambient/music class only) | two-pass `loudnorm` to class LUFS | long enough for BS.1770 integrated gating |
| every other cue | peak-levelled to the class ceiling, then oversampled limiting | a 100 ms click and a 1 s metallic ring have incomparable crest factors; RMS levelling makes one 8 dB too quiet or the other 8 dB too loud (measured: a 1 s sword hit sat at -25 dBFS RMS while a click reached -22) |

This is a deliberate divergence from "one loudness number for everything" and it
is enforced by the gate, not by convention.

---

## 5. Delivery and runtime mixing

### 5.1 Formats

Each cue is emitted three ways:

- `master/*.wav` — 48 kHz/16-bit stereo, tracked, the remix master.
- `web/*.ogg` — Vorbis q4, the game/website delivery format (Chrome, Firefox,
  Edge, Opera).
- `web/*.m4a` — AAC 112 kbps, Safari/iOS fallback. Phaser's loader accepts a
  URL array and picks the first playable type:
  `this.load.audio(key, ['x.ogg', 'x.m4a'])`.

Opus was evaluated and rejected for the primary format: Chrome/Firefox support
it, Safari does not decode Opus-in-Ogg, so it would need a third fallback for no
size win at these cue lengths.

### 5.2 Browser autoplay constraints

Chrome's autoplay policy (Web Audio since Chrome 71) suspends audio until the
user has interacted with the domain: "Autoplay with sound is allowed if: the user
has interacted with the domain (click, tap, etc.)"
(<https://developer.chrome.com/blog/autoplay>). Consequences for both surfaces:

- The game already applies `audioSettings.ts` and starts muted; keep that.
- The website must never autoplay music. UI cues are constructed lazily on the
  first pointer/key event; the audio context is resumed inside that handler.
- A visible mute/unmute control is required, and the default must be muted
  because the game's current bank is still being replaced.

### 5.3 Runtime bus and ducking

The mix at runtime is a bus tree, not per-call volumes:

```
master ──┬── music   (-7 dB, ducked -9 dB under stingers)
         ├── ambient (-9 dB, ducked -6 dB under stingers)
         ├── sfx     ( 0 dB, 8-voice cap, 40 ms de-dupe per key)
         └── ui      (-6 dB, never ducked)
```

Rules: one stinger ducks ambient/music for 120 ms attack / 800 ms release; a
weapon report ducks nothing (it is the event); identical keys inside 40 ms are
dropped rather than stacked (prevents 6-unit alpha-strike phasing); panning
follows screen-space unit position (Phaser `WebAudioSound.setPan` is available
in 3.90); the whole tree hangs off the existing mute switch.

### 5.4 Website design audio

Website audio is a subset: `web_hover`, `web_click`, `web_page`, `web_error`,
`web_success` at -9 to -4 dB trims, all under 10 KB, preloaded after the first
gesture. Rules: hover cues only on pointer devices (`matchMedia('(hover: hover)')`),
never on focus, never repeated within 120 ms, and a single global mute persisted
in `localStorage`. Marketing pages should use at most one ambient bed and it must
start only after an explicit user action.

---

## 6. The gate

```bash
python3 tools/audio/build_bank.py --build          # build all cues
python3 tools/audio/build_bank.py --verify         # certification gate
```

`--verify` re-measures the encoded masters and fails on: missing master/web
file, loudness outside ±1.5 LU of the class target (LUFS mode) or ±2.5 dB
(RMS mode), true peak above -1 dBTP, peak-mode cue outside -6.5..-1 dBTP,
byte-identical duplicate variants, and loop-seam discontinuity. Exit code is
non-zero on any failure. The bank manifest is the evidence record: per cue it
lists the source file, recipe, target, measured LUFS/RMS/true peak, sizes and
SHA-256.

Do not mark an audio stage complete on "it built". Run the gate and record the
result in the manifest.

---

## 7. Repo layout

```
assets/_audio_library/            raw licensed library (gitignored, ~120 GB)
  MANIFEST.json                   source, URL, sha256, licence per archive
  library_index.json              file index with UCS CatID per file
  LICENCE.txt                     human-readable terms per source
tools/audio/sources.py            registry: URLs, part counts, licence notes
tools/audio/fetch_library.py      download / extract / index
tools/audio/cues_ioa.json         cue sheet (queries, recipes, targets)
tools/audio/picks.json            optional explicit per-cue source overrides
tools/audio/build_bank.py         design, mix, master, encode, verify
output/audio/v0.1.0/              derived bank (tracked)
  master/  web/  manifest.json
```

`picks.json` is the human-ear override: `{"directorate_fire": ["sonniss/2024/…wav"]}`.
Automatic selection is the bootstrap; once a cue has been auditioned, pin it.

---

## 8. Decisions

- **Choice**: Sonniss bundles + Kenney CC0 as the base library (not Freesound).
  **Because**: bulk, key-less, resumable download with an explicit written
  commercial licence; Freesound requires an API token, OAuth for originals, and
  per-sound attribution bookkeeping for CC-BY.
  **Revisit when** we need a specific missing category and can afford the
  attribution ledger.
- **Choice**: keep the raw library out of git and commit only the derived bank +
  manifests. **Because**: 120 GB vs a few MB, and the Sonniss licence forbids
  redistributing the raw sounds anyway.
  **Revisit when** reproducible builds must survive the libraries going offline
  (then archive the chosen sources, not the whole library).
- **Choice**: per-asset class levelling rather than one title-level LUFS target.
  **Because**: ASWG-R001 defines a title target, not a per-asset one; consistent
  relative levels are what makes cues mixable, and browser playback has no
  platform loudness stage.
  **Revisit when** IoA ships to consoles, which need a title-level -24 LKFS pass.
- **Choice**: OGG Vorbis + M4A rather than Opus. **Because**: Safari does not
  decode Opus-in-Ogg; two formats already cover the installed base, three do not
  pay for themselves on 5–200 KB cues.
  **Revisit when** minimum browser versions guarantee Opus-in-CAF/WebM.
- **Choice**: exclude Sonniss audio from any future model training. **Because**:
  the EULA prohibits AI/ML training use. Kenney/Pixabay are the training-safe
  pool.
  **Revisit when** Sonniss grants a training exception.

## 9. Dead ends (do not re-test)

- `freepd.com` — permanently closed in 2025; public-domain music has to come from
  OpenGameArt, Pixabay or Wikimedia Commons instead.
- BBC Sound Effects (RemArc) — not licensed for commercial use. Excellent
  recordings, wrong licence.
- Bulk `curl` of `sonniss.com` HTML — Cloudflare challenge; use the
  `downloads.sonniss.com` URLs directly, they are not challenged.
- `kenney.nl/assets/<slug>/download` — 404. The signed-link JSON endpoint is the
  only scriptable path.
- Freesound bulk download without an account — original files are OAuth2-gated;
  only public previews are open.
- `loudnorm` on sub-second files — returns `-inf` and errors out; use RMS or peak
  levelling instead.

## 10. Tripwire

Re-check when: Sonniss publishes a new GDC bundle (annual, March), the Sonniss
EULA version changes (currently v2.0, effective 27 Aug 2026), Safari ships
Opus-in-Ogg support, or ASWG-R001 is revised above v1.2.
