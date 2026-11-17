#!/usr/bin/env python3
"""fetch_sources.py — download and verify the packaged DoW2 source assets.

The pipeline reads Dawn of War II's shipped data (geometry, clips, textures, wargear blueprints).
`tools/sources/pack_sources.py` packages the exact subset it needs and the archive is published as a
release asset, so a checkout works without a DoW2 install.

This downloads that archive, verifies the sha256, unpacks it and prints the DOW2_RETRIB to export.

Usage:
  python3 tools/sources/fetch_sources.py --out ~/dow2-sources
  python3 tools/sources/fetch_sources.py --out ~/dow2-sources --url <release asset url> --sha256 <hash>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

DEFAULT_URL = ("https://github.com/Sigh-Club/Asset-Pipeline/releases/download/"
               "source-v2/dow2-unit-sources-v2.zst")
DEFAULT_SHA = "d905e64d612f216a5c995f4f76fc42cf3a20f0cf3b8038dbb68fac017b3458aa"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="directory to unpack into")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--sha256", default=DEFAULT_SHA, help="expected hash; '' to skip the check")
    a = ap.parse_args(argv)
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    archive = out / "dow2-unit-sources-v2.zst"

    if not archive.exists():
        print(f"downloading {a.url}")
        urllib.request.urlretrieve(a.url, archive)
    got = sha256(archive)
    if a.sha256 and got != a.sha256:
        raise SystemExit(f"sha256 mismatch\n  expected {a.sha256}\n  got      {got}")
    print(f"sha256 ok: {got}")

    print(f"unpacking into {out}")
    subprocess.run(f"zstd -d -q -f {archive} -o {out/'pack.tar'} && "
                   f"tar -C {out} -xf {out/'pack.tar'} && rm -f {out/'pack.tar'}",
                   shell=True, check=True)

    manifest = out / "MANIFEST.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        print(f"manifest: {len(m.get('files', []))} files, units {', '.join(m.get('units', []))}")
    print()
    print("Use it with:")
    print(f'  export DOW2_RETRIB="{out}"')
    print("  tools/build_source_lab_all.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
