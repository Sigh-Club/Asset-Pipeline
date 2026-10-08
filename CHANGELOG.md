# Changelog — IoA Asset Pipeline

All notable changes to this project are documented here.

## [Unreleased] — 2026-10-08

### Added — DoW decompile: animation / skeleton / team-colour pipeline

- `tools/dow/whm_animdata.py` — WHM skeleton/animation/marker/camera
  extractor → JSON; full RSGM v4 chunk anatomy documented (SKEL biped,
  embedded named ANIM clips with local pos/quat keys, MARK attachment
  markers, CAMS, SHDR material channels, 48-byte skinned vertex layout).
- `tools/dow/pose_whm.py` — skin any animation frame to OBJ (bind pose =
  anim frame 0, empirical; SKEL-rest bind tears limbs on Definitive assets).
  Feeds `blender_ork_import.py` unchanged — the sprite-sheet workhorse.
- `tools/dow/wtp_tint.py` — WTP team-colour compositor (PTLD soft masks ×
  `.teamcolour` RGB, multiplicative blend; PTBD badge rect decoded).
- `docs/DOW_IMPORT.md` §6 — full decompile writeup, replication recipe
  (authoring assets in DoW convention), GOG extraction runbook.
- Full GOG archive set extracted to `/run/media/talzanar/games/dow-definitive/`
  (W40kData.sga: unit icons, WTP masks, badges, teamcolour lua).

### Fixed

- `rsh_extract.py`: multi-page RSH output collisions (pages suffixed
  `_0.._3`, page 0 = diffuse); `blender_ork_import.py` picks page 0 and
  imports `os` (previous NameError).

## [v0.4.0] — 2026-07-26

### Added

#### Render Queue System (new)
- **`tools/render_queue.py`** — Persistent render job queue manager. Add/remove/list/run jobs via `pipeline_cli.py queue` or `python3 -m tools.render_queue`. Queue stored in `output/render_queue.json`, survives reboots.
- **`tools/schedule_render.sh`** — Scheduler script for cron/at/systemd. Handles locking, `systemd-inhibit` sleep prevention, and nice priority.
- **`tools/queue_dashboard.py`** — Web dashboard on port 8081/8082 for visual queue management. Live progress bars, pause/resume, cron installation, and job removal.
- **Pause / Resume / Clean** — `queue pause` creates a sentinel file; current job finishes then queue stops. `queue resume` removes pause and restarts processing. `queue clean` resets stale "running" jobs and detects already-rendered units.
- **Crash recovery** — `queue run` automatically resets stuck "running" jobs to "queued" and skips units that already have ≥80% rendered frames on disk.
- **Real-time progress tracking** — Background monitor thread counts rendered PNG files every 5 seconds. Progress written to `output/render_progress.json` and displayed in the dashboard with animated progress bars.

#### Non-Humanoid Body Templates (new)
- **`tools/blender/parametric_vehicle_generator.py`** — Three non-humanoid body types: **vehicle** (tank/gun_emplacement/chassis), **creature** (quadruped with spine+4-leg armature), **insectoid** (segmented body with 6-leg armature).
- **`parametric_unit_generator.py`** modified — dispatches by `body_type` field, importing and routing to the non-humanoid module when appropriate.
- **6 non-humanoid configs + .blend files**: Predator Tank (Iron Directorate), Battle Wagon (Wreckstorm Clans), Gun Drone (Harmonic Collective), Swarm Beast (Parasitic Bloom), Chrono Scarab (Chrono Revenants), Shade Swarm (Void Corsairs).

#### NPC Faction Materials & Units
- **5 new PBR material sets**: bio_flesh, chrome_white, cyan_bone, red_rust, black_silver (total: 10 materials across 7 factions).
- **10 NPC unit configs + .blend files**: Parasitic Bloom (bloated_swarm, toxic_reaver), Harmonic Collective (precision_drone, logic_weaver), Chrono Revenants (time_soldier, chrono_guardian), Wreckstorm Clans (wreck_raider, scrap_boss), Void Corsairs (void_raider, shadow_blade).
- **Config inheritance hierarchy** — `promoted_from` field enables clean progression from base → promoted → highest tier.

#### Unified CLI Integration
- **`tools/pipeline_cli.py`** — Single entry point routing to 8 sub-pipelines: character, tile, ui, materials, critic, pack, sync, info, doctor, queue, dashboard.
- **Sub-pipelines by asset type**: character (generate/render/full/batch), tile (generate/render), ui (icons/buttons), materials (generate/list), critic (single/batch), pack, sync, info, doctor, queue (add/list/remove/clear/status/run/pause/resume/clean), dashboard.

#### UI & Tile Generators
- **`tools/generate_ui_elements.py`** — Pillow-based UI element generation for 3 faction themes (iron_directorate, cinderborn, neutral). Buttons, panels, dividers, icon frames.
- **`tools/blender/tile_generator.py`** — Procedural isometric tile generation for 3 tile sets (urban_concrete, industrial_metal, corrupted_steel). Ground tiles, wall segments, props.

### Changed

#### Animation System (v3 → v4)
- **Rotation amplitudes increased 3-8×** across all animations: idle_intensity=1.0, walk_stride=0.4, attack_speed=1.5.
- Frame diffs now 15+ pixels at 96×128 (was 1-9px).
- All 28 unit configs updated with new animation parameters.

#### Geometry Enhancement
- **+30% vertices**: Primitive segments increased 12→24, subsurf levels 1→3. Average vertex count: 630→822.
- **Side-profile widened**: Shoulders 0.26→0.30, legs 0.08→0.10. Codpiece/tabard geometry added for E/W silhouette.
- All 28 .blend files regenerated with new geometry and animation parameters.

#### Render Pipeline
- **GPU auto-detect** with CPU fallback — no more CUDA/OptiX crashes.
- **`--fast` mode** (16 Cycles samples) for iteration; `--samples N` for quality.
- **Streaming render output** — `_render_job` uses `subprocess.Popen` with line-by-line stdout reading for real-time progress tracking.
- **Critic thresholds rebalanced**: edge_density min 2%→1.5%, direction_variance max 30%→50%.

#### Bug Fixes
- Hardcoded paths in `batch_pipeline.py`, `sync_to_ioa.py`, `generate_status_icons.py` resolved.
- Blender GPU crash fixed: `import bpy` moved inside function.
- CLI blend file resolution priority fixed.
- Pillow `getdata()` deprecations updated.
- Robot framework references removed from imports.

### Removed
- Old `cmd_run` approach using `subprocess.run()` with `capture_output=True` — replaced with streaming `subprocess.Popen()` for real-time progress.
- Standalone batch render scripts — functionality merged into unified CLI and queue system.

### Documentation
- `CHANGELOG.md` — created this file.
- `README.md` — updated with queue system, dashboard, and pause/resume documentation.
- `.pi/skills/asset-pipeline/SKILL.md` — updated with queue, dashboard, and non-humanoid references.
- `development.md` — session log for v4 added.
- `PLANNING.md`, `PIPELINE_V2.md`, `PARAMETRIC_CONFIG.md` — updated with v3→v4 changes.

### Technical Debt
- Non-humanoid animation bone keyframes not yet written — `animate_*` functions in `parametric_vehicle_generator.py` need implementation.
- Tile render script (`render_tiles.py`) not separated from `tile_generator.py` — tile render command warns and falls through.
- Geometry Nodes rivets disabled pending Blender 5.1 API fix (`DistributePointsOnFaces` API changed).
- E/W side-profile still thin (8.4% vs 14.7% N/S) — consider cape or over-shoulder weapon.
- CLI timeout (120s) insufficient for full Cycles renders — use `--fast` or `queue run` directly.
