#!/usr/bin/env python3
"""Verify the audio bank as it exists in the game tree.

`build_bank.py --verify` certifies the master/build output. This gate certifies
the *shipped* copy: the files the browser will actually request, the keys the
game code actually asks for, and the decode/size budgets of each cue class.

Usage:
    python3 tools/audio/verify_game_bank.py ../Imperium-of-Ash
    python3 tools/audio/verify_game_bank.py ../Imperium-of-Ash --json

Exit code is non-zero on any failure, so it can run in CI next to the build.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Decoded PCM budget per cue class, in MiB. Web Audio decodes the whole file into
# memory (48 kHz stereo float), so a long bed is a real memory cost, not a disk
# cost. Sizes here are the ceiling we accept for the current design.
DECODED_BUDGET_MIB = {
    "ui": 1,
    "sfx": 8,
    "ambient": 40,
    "music": 60,
}


def probe_duration(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def audio_keys_from_game(root: Path) -> set[str]:
    """Cue keys the TypeScript code can request at runtime.

    Sources: the AudioKey enum, plus literal keys passed to the theatre/unit
    helpers (`'${faction}_${kind}_${i}'` variants are covered by the manifest).
    """
    keys: set[str] = set()
    registry = root / "frontend/src/phaser-game/utils/AudioRegistry.ts"
    if registry.exists():
        text = registry.read_text(encoding="utf-8")
        for value in re.findall(r"=\s*'([a-z0-9_]+)'", text):
            keys.add(value)
    manifest = root / "frontend/src/data/audioManifest.json"
    if manifest.exists():
        cues = json.loads(manifest.read_text(encoding="utf-8")).get("cues", {})
        for name in cues:
            keys.add(name)
    keys.discard("click")  # legacy fallback key, only used when the bank is empty
    return keys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("game_root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.game_root).resolve()
    manifest_path = root / "frontend/src/data/audioManifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing runtime manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cues = manifest.get("cues", {})
    public = root / "frontend/public"

    failures: list[str] = []
    checked_files = 0
    total_bytes = 0
    decoded_bytes = 0

    for name, cue in sorted(cues.items()):
        channel = cue.get("channel", "sfx")
        budget = DECODED_BUDGET_MIB.get(channel, 8) * 1024 * 1024
        cue_decoded = 0
        for variant in cue.get("variants", []):
            for kind in ("ogg", "m4a"):
                rel = variant.get(kind)
                if not rel:
                    failures.append(f"{name}/{variant.get('key')}: no {kind} path")
                    continue
                path = public / rel
                checked_files += 1
                if not path.exists():
                    failures.append(f"{name}/{variant.get('key')}: missing {rel}")
                    continue
                size = path.stat().st_size
                total_bytes += size
                if size < 512:
                    failures.append(f"{name}/{variant.get('key')}: {rel} is {size} B")
                if probe_duration(path) <= 0:
                    failures.append(f"{name}/{variant.get('key')}: {rel} does not decode")
            if variant.get("ogg"):
                ogg = public / variant["ogg"]
                if ogg.exists():
                    cue_decoded += probe_duration(ogg) * 48000 * 2 * 4
        decoded_bytes += cue_decoded
        if cue_decoded > budget:
            failures.append(
                f"{name}: decoded {cue_decoded/1048576:.0f} MiB exceeds "
                f"{budget/1048576:.0f} MiB budget for channel '{channel}'")

    required = audio_keys_from_game(root)
    missing = sorted(k for k in required if k not in cues)
    for key in missing:
        failures.append(f"code requests '{key}' but the bank has no such cue")

    report = {
        "cues": len(cues),
        "files": checked_files,
        "bytes": total_bytes,
        "decoded_mib": round(decoded_bytes / 1048576, 1),
        "missing_keys": missing,
        "failures": failures,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"game bank: {len(cues)} cues, {checked_files} files, "
              f"{total_bytes/1048576:.1f} MiB on disk, "
              f"{report['decoded_mib']} MiB decoded")
        for f in failures:
            print("  FAIL", f)
        if not failures:
            print("  ok: every manifest file decodes and every code-referenced key exists")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
