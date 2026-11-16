## Workspace hygiene — standing rules

Session-by-session dirt is the owner's call; these are the rules that should hold
in every session (pruned 2026-11-09 from the 2026-10-23 audit, which recorded
in-flight experiments that are long since resolved).

1. **`output/` is a record, not scratch.** Do not hand-prune it; retention is
   governed by the rules in `DEVELOPMENT.md`. Generated sheets and raw renders are
   gitignored; derived maps and reports are the tracked artefacts.
2. **One GPU job at a time.** This box has one 8 GB card shared with the desktop.
   Use `tools/blender_run.sh`; a second concurrent Blender/CUDA job is the most
   common cause of an OOM twenty minutes into a batch.
3. **Kill orphaned Blender processes before a render.** A crashed `--background`
   session holds VRAM invisibly (`pgrep -x blender`).
4. **Version every output directory** (`v0.x.y/`) and record the profile used
   (`IOA_GPU_PROFILE`) in the run log, so a bad result is reproducible.
5. **No asset ships without its gate**: `tools/glb_contract.py` for 3D,
   `tools/validate_uv.py` + `tools/critic.py` for the sprite bake.
6. **Do not "clean up" another agent's uncommitted work.** If a tree is dirty and
   you did not make it dirty, leave it and note it.

## Current state (2026-11-09)

3D: one unit GLB shipped, contract-failing (clay, no UVs, 3/9 clips); material
library 4/79 built; retopo and the clip set are the open quality gaps — see
[`3D_ASSETS.md`](3D_ASSETS.md) §6. Sprite path: 65/65 atlases, 0/81 combat
animation clips.
