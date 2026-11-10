#!/usr/bin/env python3
"""Fetch licensed sound-effect libraries and index them for cue design.

The raw library is ~120 GB and lives outside git
(``assets/_audio_library/``, gitignored).  Only the derived bank in
``output/audio/v*/`` is tracked.

Usage:
    python3 tools/audio/fetch_library.py --source kenney
    python3 tools/audio/fetch_library.py --source sonniss --years 2026 2024
    python3 tools/audio/fetch_library.py --source sonniss --years all
    python3 tools/audio/fetch_library.py --index

Downloads are resumable (curl -C -) and idempotent: a part that already has the
expected byte count is skipped.  Extraction uses the stdlib zipfile so a
truncated archive fails loudly instead of producing a half library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sources

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "assets" / "_audio_library"
INDEX = LIBRARY / "library_index.json"
AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3", ".m4a", ".opus"}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def remote_size(url: str, timeout: int = 40) -> int:
    """Content-Length in bytes, or 0 when the server will not say."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001 - a missing size is not fatal
        return 0


MIRRORS = ["https://hippolytus.feralhosting.com/sonniss/"]
MIRROR_PREFIX = "https://downloads.sonniss.com/"


def with_mirrors(url: str) -> list[str]:
    """Primary URL first, then the published mirrors.

    downloads.sonniss.com intermittently returns 404 on a part that is present;
    the mirrors carry the same files, so a failed primary is retried there.
    """
    candidates = [url]
    if url.startswith(MIRROR_PREFIX):
        name = url[len(MIRROR_PREFIX):]
        candidates += [m + name for m in MIRRORS]
    return candidates


CHUNK = 1024 * 1024 * 1024


def download(url: str, dest: Path, expected: int = 0) -> bool:
    """Chunked, resumable download.  Returns True when the file is complete.

    downloads.sonniss.com stalls on an open-ended range (`Range: bytes=0-`) and
    on plain full-file GETs, but serves closed ranges immediately.  The client
    therefore walks the file in explicit 32 MiB windows, appending each one, and
    falls back to the published mirrors on failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (expected == 0 or dest.stat().st_size == expected):
        log(f"  skip (complete) {dest.name} {dest.stat().st_size:,} B")
        return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    if dest.exists() and not tmp.exists():
        dest.rename(tmp)
    urls = with_mirrors(url)

    for attempt in range(1, 11):
        if expected and tmp.exists() and tmp.stat().st_size > expected:
            tmp.unlink()
        offset = tmp.stat().st_size if tmp.exists() else 0
        if expected and offset == expected:
            tmp.rename(dest)
            return True
        source = urls[(attempt - 1) % len(urls)]
        end = (min(offset + CHUNK, expected) - 1) if expected else offset + CHUNK - 1
        log(f"  fetch {dest.name} attempt {attempt} bytes {offset:,}-{end:,}")
        with tmp.open("ab") as fh:
            rc = subprocess.run(
                ["curl", "-sL", "--fail", "--max-time", "900", "-A", UA,
                 "-r", f"{offset}-{end}", "-o", "-", source],
                stdout=fh,
            ).returncode
        have = tmp.stat().st_size if tmp.exists() else 0
        if expected and have >= expected:
            tmp.rename(dest)
            log(f"  ok {dest.name} {have:,} B")
            return True
        if not expected and rc == 0 and (end - offset + 1) > (have - offset):
            tmp.rename(dest)
            log(f"  ok {dest.name} {have:,} B (size unknown)")
            return True
        if rc != 0 and have == offset:
            log(f"  no progress rc={rc} - mirror/retry")
            time.sleep(2 * attempt)
        # a successful partial chunk just continues the loop
    return False


def extract(zip_path: Path, out_dir: Path) -> int:
    """Extract an archive and return the number of audio files written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise RuntimeError(f"corrupt member {bad} in {zip_path.name}")
            zf.extractall(out_dir)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise SystemExit(f"EXTRACT FAILED {zip_path}: {exc}") from exc
    return sum(
        1
        for p in out_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXT
    )


def write_license(dest: Path, key: str) -> None:
    notes = sources.source_notes()[key]
    text = (
        f"Source: {notes['index']}\n"
        f"Licence: {notes['licence']}\n"
        f"Licence text: {notes['licence_url']}\n"
        f"Commercial use: {notes['commercial']}\n"
        f"Attribution: {notes['attribution']}\n"
        f"AI training: {notes['ai_training']}\n"
        f"Resale of raw files: {notes['resale_raw']}\n"
        f"Retrieved: {time.strftime('%Y-%m-%d')}\n"
    )
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "LICENCE.txt").write_text(text, encoding="utf-8")


def fetch_sonniss(years: list[str], keep_zips: bool) -> list[dict]:
    out_root = LIBRARY / "sonniss"
    write_license(out_root, "sonniss")
    records: list[dict] = []
    for year in years:
        log(f"[sonniss {year}]")
        for url in sources.sonniss_parts(year):
            name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
            expected = remote_size(url)
            zip_path = out_root / "_zips" / name
            if not download(url, zip_path, expected):
                raise SystemExit(f"DOWNLOAD FAILED {url}")
            dest = out_root / year
            before = {p for p in dest.rglob("*") if p.is_file()} if dest.exists() else set()
            count = extract(zip_path, dest)
            records.append({
                "source": "sonniss",
                "year": year,
                "url": url,
                "file": name,
                "bytes": zip_path.stat().st_size,
                "sha256": sha256(zip_path),
                "audio_files_present": count,
                "licence": sources.SONNISS_LICENCE,
                "downloaded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            log(f"  extracted -> {dest} ({len(list(dest.rglob('*.wav')))} wav total)")
            if not keep_zips:
                zip_path.unlink(missing_ok=True)
            del before
    return records


def fetch_kenney(keep_zips: bool) -> list[dict]:
    out_root = LIBRARY / "kenney"
    write_license(out_root, "kenney")
    records: list[dict] = []
    for slug, title in sorted(sources.KENNEY_PACKS.items()):
        log(f"[kenney {slug}] {title}")
        api = "https://kenney.nl/download-link/" + sources.kenney_slug_id(slug)
        req = urllib.request.Request(
            api,
            headers={"User-Agent": UA, "Referer": f"https://kenney.nl/assets/{slug}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                payload = json.load(resp)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"kenney signed link failed for {slug}: {exc}") from exc
        url = payload.get("url")
        if not url:
            raise SystemExit(f"kenney returned no url for {slug}: {payload}")
        zip_path = out_root / "_zips" / f"kenney_{slug}.zip"
        if not download(url, zip_path):
            raise SystemExit(f"DOWNLOAD FAILED {url}")
        dest = out_root / slug
        count = extract(zip_path, dest)
        records.append({
            "source": "kenney",
            "pack": slug,
            "title": title,
            "url": f"https://kenney.nl/assets/{slug}",
            "file": zip_path.name,
            "bytes": zip_path.stat().st_size,
            "sha256": sha256(zip_path),
            "audio_files_present": count,
            "licence": sources.KENNEY_LICENCE,
            "downloaded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        log(f"  extracted -> {dest} ({count} audio files)")
        if not keep_zips:
            zip_path.unlink(missing_ok=True)
    return records


def merge_manifest(records: list[dict]) -> None:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    path = LIBRARY / "MANIFEST.json"
    existing: list[dict] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8")).get("downloads", [])
    key = lambda r: (r["source"], r.get("year") or r.get("pack"))
    merged = {key(r): r for r in existing}
    merged.update({key(r): r for r in records})
    doc = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": sources.source_notes(),
        "downloads": [merged[k] for k in sorted(merged)],
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    log(f"manifest -> {path} ({len(merged)} entries)")


def build_index() -> None:
    """Index every audio file by relative path plus its UCS category prefix.

    UCS (Universal Category System) is the public-domain naming standard used by
    most commercial SFX libraries and by the Sonniss bundles: filenames start
    with a CatID such as ``WEAPFire_`` or ``EXPLImp_``.  Parsing it gives the cue
    designer a reliable category filter that survives renames inside a pack.
    """
    LIBRARY.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for path in sorted(LIBRARY.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXT:
            continue
        if "_zips" in path.parts:
            continue
        rel = path.relative_to(LIBRARY).as_posix()
        if "__MACOSX" in path.parts or path.name.startswith("._"):
            continue
        stem = path.stem
        catid = ""
        parts = stem.split("_", 1)
        if parts and 4 <= len(parts[0]) <= 24 and parts[0][:4].isalpha():
            catid = parts[0]
        entries.append({
            "path": rel,
            "source": rel.split("/", 1)[0],
            "bytes": path.stat().st_size,
            "catid": catid,
            "stem": stem,
        })
    doc = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "count": len(entries),
        "by_source": {
            s: sum(1 for e in entries if e["source"] == s)
            for s in sorted({e["source"] for e in entries})
        },
        "by_catid": _top_counts(entries),
        "files": entries,
    }
    INDEX.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    log(f"index -> {INDEX} ({len(entries)} files, {INDEX.stat().st_size/1048576:.1f} MB)")
    for catid, n in list(doc["by_catid"].items())[:20]:
        log(f"  {catid:<14} {n}")


def _top_counts(entries: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        if entry["catid"]:
            counts[entry["catid"]] = counts.get(entry["catid"], 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["sonniss", "kenney"], action="append")
    ap.add_argument("--years", nargs="*", default=[],
                    help="Sonniss years, or 'all'. Default: the modern bundles.")
    ap.add_argument("--keep-zips", action="store_true")
    ap.add_argument("--index", action="store_true", help="rebuild the file index")
    args = ap.parse_args()

    if not args.source and not args.index:
        ap.error("choose --source and/or --index")

    records: list[dict] = []
    if "sonniss" in (args.source or []):
        years = args.years or ["2026", "2024"]
        if years == ["all"]:
            years = sorted(sources.SONNISS_YEARS)
        unknown = [y for y in years if y not in sources.SONNISS_YEARS]
        if unknown:
            ap.error(f"unknown Sonniss years: {unknown}")
        records += fetch_sonniss(years, args.keep_zips)
    if "kenney" in (args.source or []):
        records += fetch_kenney(args.keep_zips)
    if records:
        merge_manifest(records)
    if args.index or records:
        build_index()


if __name__ == "__main__":
    main()
