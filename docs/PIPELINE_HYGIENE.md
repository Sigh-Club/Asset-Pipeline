
## Workspace hygiene audit — 2026-10-23 (00:10)

Session-close state, recorded not pruned (asset dirt is owner domain):

- `iron_directorate_line_infantry` model assets show uncommitted modifications
  (diffuse PNG, blend, new AO variants) + `tools/dow/pose_whm.py` — an in-flight
  pose/texture experiment. Owner to review and commit or discard.
- Untracked `dow_chaos_marine/`, `dow_space_marine/` unit trees + `data/` — legacy
  DoW import experiments; candidate for `archive/` per the retention rules above.
- `output/` deletions restored from git (a phase37/phase52 preview dir had drifted);
  `output/` is versioned-record — do not hand-prune without the retention rules.
- The night's renders/queue jobs: queue cleared at owner request; the H1 atlas
  delivery used the ALREADY-rendered processed/ trees (no new GPU time).
