#!/usr/bin/env bash
# generate_batch.sh <N> — generate one material sheet, then derive its PBR set.
# One sheet per invocation on purpose: Gemini quota windows are small and a
# failure must not take the rest of the backlog with it.
set -uo pipefail
N="${1:?usage: generate_batch.sh <batch-number>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
LIB="assets/materials/grimdark_scifi"
GEN="$LIB/generate.sh"

seg="$(awk -v n="$N" '$0 ~ "^# batch "n":" {f=1} f && /^$/ {exit} f' "$GEN")"
if [[ -z "$seg" ]]; then echo "no batch $N in $GEN" >&2; exit 2; fi

echo "=== batch $N ==="
echo "$seg" | head -1
if ! bash -c "$seg"; then
  echo "GENERATION FAILED for batch $N (quota or service) — stopping here" >&2
  exit 1
fi
if ! ls "$LIB"/sheets/batch_$(printf '%02d' "$N")_*_0.png >/dev/null 2>&1; then
  echo "no sheet produced for batch $N — stopping here" >&2
  exit 1
fi
python3 tools/pbr/derive_maps.py --batch "$N"
