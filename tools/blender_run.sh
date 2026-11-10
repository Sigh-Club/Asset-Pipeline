#!/usr/bin/env bash
# blender_run.sh — launch headless Blender inside this workstation's memory budget.
#
# The box has one 8 GB GPU shared with the desktop. Two Blender jobs, or one job
# started while the GPU is busy, is how a 20-minute task becomes an OOM at minute
# 19. This wrapper waits for headroom, caps threads, disables user addons, and
# records the profile it chose so a bad render can be reproduced.
#
# Usage:
#   tools/blender_run.sh --job render -- -P tools/blender/preview_unit_materials.py -- --glb x.glb --out y
#   tools/blender_run.sh --job bake   --profile low -- -P tools/pbr/bake_unit.py -- ...
#   tools/blender_run.sh --check                       # print the plan and exit
#
# Options:
#   --job render|bake|uv|decimate|script   (default script)  selects the budget row
#   --profile auto|low|balanced|max        (default auto)    auto reads free VRAM
#   --timeout SEC                          how long to wait for VRAM (default 600)
#   --threads N                            Blender render threads (default 8 = physical cores)
#   --check                                print the resolved plan, do not launch
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
JOB="script"
PROFILE="auto"
TIMEOUT=600
THREADS=8
CHECK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job) JOB="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --threads) THREADS="$2"; shift 2 ;;
    --check) CHECK=1; shift ;;
    --) shift; break ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

case "$JOB" in
  render) JOB="blender_render" ;;
  bake) JOB="blender_bake" ;;
esac

PLAN_JSON="$(python3 "$HERE/gpu_policy.py" plan --job "$JOB" --profile "$PROFILE" --json || true)"
READ_PROFILE="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1]).get("profile","low"))' "$PLAN_JSON" 2>/dev/null || echo low)"
REQUIRE_MB="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1]).get("require_mb",1200))' "$PLAN_JSON" 2>/dev/null || echo 1200)"

echo "[blender_run] job=$JOB profile=$READ_PROFILE require=${REQUIRE_MB}MB threads=$THREADS"
if [[ "$CHECK" == "1" ]]; then
  python3 "$HERE/gpu_policy.py" status
  exit 0
fi

if ! python3 "$HERE/gpu_policy.py" require "$REQUIRE_MB" --timeout "$TIMEOUT"; then
  echo "[blender_run] not enough VRAM after ${TIMEOUT}s; falling back to low profile" >&2
  READ_PROFILE="low"
fi

export IOA_GPU_PROFILE="$READ_PROFILE"
export IOA_RENDER_JOBS=1
# keep the desktop responsive and the GPU queue short
export NICE=1
exec nice -n 5 blender -b --factory-startup -noaudio -t "$THREADS" "$@"
