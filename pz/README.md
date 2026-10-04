# PZ sub-pipeline outputs (Project Zomboid — not IoA)

Everything under `pz/` belongs to the **Project Zomboid** mod toolchain
(MTCDeathsExpanded + the MTC-DE Discord bot). Per AGENTS.md: PZ outputs
never enter IoA `assets/`, `configs/` or `output/`.

## emotes/

- `pixel_sheet_set/` — Gemini-generated pixel zombie emote sheet cells
  (source sheets cut by `cut_emotes.py`)
- `hq_sheet_set/` — the HQ cartoon generation pass (reference tier)
- `forge_emoji_set/` — the icon_forge-rendered emoji pack (24 emotes +
  contact sheet), byte-verified against the engine
- `cut_emotes.py` — sheet -> Discord emote cutter (defringe + cell isolate
  + resize); uses `tools/defringe.py`
- `build_hq.sh` — the HQ generation build script

Shipped copies live in the mod repo
(`~/.local/share/Steam/steamapps/common/ProjectZomboid/Workshop/MTCDeathsExpanded/`)
and the Discord bot hosts the uploads. The generator (`tools/icon_forge.py`)
is the single source of truth for the forge-rendered art.
