#!/usr/bin/env python3
"""Design, mix and master the IoA combat/UI/web audio bank from licensed sources.

This is the "add and mix" stage.  It never invents samples: it selects a source
recording from the licensed library (``tools/audio/cues_ioa.json`` -> queries),
runs it through a per-cue-class design chain (EQ, dynamics, transient shaping,
reverb sends, loop-seam crossfade), masters to a per-asset loudness target, and
encodes the delivery formats.

Deterministic by construction: candidate selection is a stable sort over token
scores and duration, so the same library + spec produces the same bank.  The
chosen source for every cue is written to the bank manifest, so the whole bank is
reproducible and auditable.

Usage:
    python3 tools/audio/build_bank.py --list-candidates directorate_fire
    python3 tools/audio/build_bank.py --build                 # all cues
    python3 tools/audio/build_bank.py --build --only ui_click,directorate_fire
    python3 tools/audio/build_bank.py --verify                # gate an existing bank

Design notes and the loudness/target rationale: docs/AUDIO_PIPELINE.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "assets" / "_audio_library"
INDEX = LIBRARY / "library_index.json"
SPEC = Path(__file__).resolve().parent / "cues_ioa.json"
PICKS = Path(__file__).resolve().parent / "picks.json"
OUT = REPO / "output" / "audio" / "v0.1.0"
SR = 48000
AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3", ".m4a", ".opus"}


# --------------------------------------------------------------------------- #
# shell helpers
# --------------------------------------------------------------------------- #
def run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=capture, text=True)


def ffprobe_duration(path: Path) -> float:
    res = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def loudness(path: Path) -> dict:
    """EBU R128 measurement via ffmpeg's ITU-R BS.1770-5 implementation."""
    res = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
               "-af", "loudnorm=I=-16:TP=-1:LRA=11:print_format=json",
               "-f", "null", "-"])
    text = res.stderr
    start, end = text.rfind("{"), text.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


# --------------------------------------------------------------------------- #
# candidate selection
# --------------------------------------------------------------------------- #
def load_index() -> list[dict]:
    if not INDEX.exists():
        raise SystemExit(f"missing library index {INDEX} — run fetch_library.py first")
    return json.loads(INDEX.read_text(encoding="utf-8"))["files"]


def score(entry: dict, queries: list[str], source_bias: list[str]) -> float:
    """Token/CatID match score.  Higher is better; 0 means no match at all.

    Folder names are scored too: the older Sonniss bundles (2015-2019) predate
    UCS filenames, and the library name in the path ("SoundMorph - Future
    Weapons", "Gore Toolkit") is the only reliable category signal there.
    """
    stem = entry["stem"].lower()
    path = entry["path"].lower()
    folders = " ".join(path.split("/")[:-1])
    cat = entry["catid"].lower()
    total = 0.0
    for raw in queries:
        q = raw.lower()
        if not q:
            continue
        if cat.startswith(q):
            total += 6.0            # CatID prefix is the strongest signal
        elif q in cat:
            total += 3.0
        if q in stem:
            total += 2.0
        if q in folders:
            total += 1.5
        if f"_{q}" in stem or f" {q}" in stem:
            total += 1.0
    for bias in source_bias:
        if path.startswith(bias.lower()):
            total += 2.5
    return total


def _matches(entry: dict, tokens: list[str]) -> bool:
    hay = (entry["stem"] + " " + entry["path"]).lower()
    return any(t.lower() in hay for t in tokens)


def candidates(cue: dict, index: list[dict], limit: int = 60,
               probe: int = 24) -> list[dict]:
    """Stable, evidence-ordered candidate list for one cue.

    A cue may declare ``must`` tokens: at least one has to appear in the filename
    or path.  Without this a broad query like "Impact" selects anything with the
    word in it (measured: an armour hit resolved to a wooden-debris recording).
    """
    must = cue.get("must") or []
    pool = [e for e in index if _matches(e, must)] if must else index
    if must and not pool:
        print(f"  WARN no candidate matches must={must}; falling back to queries")
        pool = index
    scored = []
    for entry in pool:
        s = score(entry, cue.get("queries", []), cue.get("source_bias", ["sonniss"]))
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda t: (-t[0], t[1]["path"]))

    max_s = float(cue.get("max_seconds", 3.0))
    min_s = float(cue.get("min_seconds", 0.0))
    out: list[dict] = []
    for s, entry in scored[:limit]:
        if s < 1.0:
            continue
        path = LIBRARY / entry["path"]
        dur = ffprobe_duration(path)
        if dur <= 0 or dur < min_s or dur > max_s * 1.5:
            continue
        out.append({"score": round(s, 2), "duration": round(dur, 3), **entry})
        if len(out) >= probe:
            break
    return out


def pick(cue: dict, index: list[dict], picks: dict[str, str]) -> list[dict]:
    """Resolve the source layers for one cue, respecting explicit picks."""
    name = cue["name"]
    if name in picks:
        explicit = picks[name]
        layers = explicit if isinstance(explicit, list) else [explicit]
        return [{"path": p, "score": 99.0, "duration": ffprobe_duration(LIBRARY / p)}
                for p in layers]

    kenney = cue.get("kenney") or []
    if kenney:
        for rel in kenney:
            path = LIBRARY / "kenney" / rel
            if path.exists():
                return [{"path": path.relative_to(LIBRARY).as_posix(), "score": 99.0,
                         "duration": ffprobe_duration(path)}]
        raise SystemExit(f"cue '{name}': none of the pinned kenney files exist: {kenney}")

    cands = candidates(cue, index)
    max_s = float(cue.get("max_seconds", 3.0))
    fitting = [c for c in cands if c["duration"] <= max_s * 2.5]
    pool = fitting or cands
    if not pool:
        raise SystemExit(f"no candidate found for cue '{name}'")
    # prefer the best score, then the shorter recording (less trim surgery)
    pool.sort(key=lambda c: (-c["score"], c["duration"], c["path"]))
    rank = max(0, int(cue.get("rank", 0)))
    if rank:
        pool = pool[rank:] or pool
    return pool[: max(1, min(int(cue.get("sources", 1)), 3))]


# --------------------------------------------------------------------------- #
# design chains
# --------------------------------------------------------------------------- #
def trim_filter(seconds: float, fade_in: float = 0.004, fade_out: float = 0.05) -> str:
    """Trim to a bounded length and de-click the ends."""
    f = f"atrim=0:{seconds:.3f},asetpts=PTS-STARTPTS"
    if fade_in > 0:
        f += f",afade=t=in:st=0:d={fade_in:.3f}"
    if fade_out > 0:
        f += f",afade=t=out:st={max(0.0, seconds - fade_out):.3f}:d={fade_out:.3f}"
    return f


# recipe -> (filter chain template, reverb send amount, extra layers)
# recipe -> (filter chain template, reverb send amount, extra layers)
# Short cues cannot be measured as integrated LUFS: EBU R128 gating returns -inf
# under roughly one second, so one-shots are levelled by RMS and only beds/
# music (>= 2.5 s) use loudnorm.  Rationale and the table: docs/AUDIO_PIPELINE.md.
LUFS_MIN_SECONDS = 2.5

RECIPES: dict[str, dict] = {
    "ui_tick": {
        "chain": "highpass=f=420,lowpass=f=13000,equalizer=f=2600:t=q:w=1.1:g=2.5,"
                 "acompressor=threshold=0.08:ratio=4:attack=1:release=60",
        "send": 0.06, "fade_out": 0.02,
    },
    "ui_negative": {
        "chain": "highpass=f=180,lowpass=f=9000,equalizer=f=320:t=q:w=1.2:g=3,"
                 "acompressor=threshold=0.09:ratio=5:attack=1:release=90",
        "send": 0.08, "fade_out": 0.04,
    },
    "ui_positive": {
        "chain": "highpass=f=300,lowpass=f=12000,equalizer=f=1800:t=q:w=1.0:g=2,"
                 "acompressor=threshold=0.1:ratio=3:attack=2:release=120",
        "send": 0.12, "fade_out": 0.08,
    },
    "gunshot_rifle": {
        "chain": "highpass=f=45,lowpass=f=15000,equalizer=f=95:t=q:w=0.9:g=3,"
                 "equalizer=f=3200:t=q:w=1.2:g=2.5,"
                 "acompressor=threshold=0.05:ratio=6:attack=0.6:release=80,"
                 "alimiter=limit=0.9",
        "send": 0.18, "fade_out": 0.06,
    },
    "gunshot_heavy": {
        "chain": "highpass=f=35,lowpass=f=11000,equalizer=f=70:t=q:w=0.8:g=5,"
                 "equalizer=f=1800:t=q:w=1.4:g=2,"
                 "acompressor=threshold=0.04:ratio=8:attack=1:release=120,"
                 "alimiter=limit=0.9",
        "send": 0.22, "fade_out": 0.10,
    },
    "impact_metal": {
        "chain": "highpass=f=150,lowpass=f=16000,equalizer=f=2100:t=q:w=1.5:g=3,"
                 "equalizer=f=4200:t=q:w=2.0:g=2,"
                 "acompressor=threshold=0.07:ratio=5:attack=0.5:release=70",
        "send": 0.14, "fade_out": 0.05,
    },
    "impact_flesh": {
        "chain": "highpass=f=60,lowpass=f=4500,equalizer=f=160:t=q:w=1.0:g=3.5,"
                 "acompressor=threshold=0.07:ratio=5:attack=1:release=90",
        "send": 0.10, "fade_out": 0.05,
    },
    "whiff": {
        "chain": "highpass=f=320,lowpass=f=9000,"
                 "acompressor=threshold=0.1:ratio=3:attack=2:release=120",
        "send": 0.10, "fade_out": 0.05,
    },
    "explosion": {
        "chain": "highpass=f=28,lowpass=f=9000,equalizer=f=55:t=q:w=0.7:g=5.5,"
                 "equalizer=f=900:t=q:w=1.0:g=-2,"
                 "acompressor=threshold=0.03:ratio=9:attack=1:release=180,"
                 "alimiter=limit=0.9",
        "send": 0.30, "fade_out": 0.25,
    },
    "footstep_heavy": {
        "chain": "highpass=f=55,lowpass=f=7000,equalizer=f=120:t=q:w=1.0:g=3,"
                 "acompressor=threshold=0.08:ratio=4:attack=1:release=60",
        "send": 0.05, "fade_out": 0.04,
    },
    "footstep_soft": {
        "chain": "highpass=f=90,lowpass=f=6000,equalizer=f=220:t=q:w=1.2:g=-1.5,"
                 "acompressor=threshold=0.09:ratio=4:attack=1:release=70",
        "send": 0.05, "fade_out": 0.04,
    },
    "mech": {
        "chain": "highpass=f=180,lowpass=f=12000,equalizer=f=2600:t=q:w=1.6:g=2,"
                 "acompressor=threshold=0.08:ratio=4:attack=0.8:release=60",
        "send": 0.08, "fade_out": 0.04,
    },
    "vox": {
        "chain": "highpass=f=280,lowpass=f=3600,equalizer=f=1400:t=q:w=1.2:g=2,"
                 "acompressor=threshold=0.06:ratio=6:attack=2:release=90,"
                 "alimiter=limit=0.92",
        "send": 0.08, "fade_out": 0.06,
    },
    "vocal": {
        "chain": "highpass=f=140,lowpass=f=6500,"
                 "acompressor=threshold=0.07:ratio=4:attack=3:release=110",
        "send": 0.12, "fade_out": 0.10,
    },
    "stinger": {
        "chain": "highpass=f=45,lowpass=f=16000,"
                 "acompressor=threshold=0.08:ratio=3:attack=4:release=180",
        "send": 0.16, "fade_out": 0.30,
    },
    "crit": {
        "chain": "highpass=f=40,lowpass=f=16000,equalizer=f=110:t=q:w=0.8:g=4,"
                 "equalizer=f=3000:t=q:w=1.4:g=3,"
                 "acompressor=threshold=0.04:ratio=7:attack=0.8:release=120,"
                 "alimiter=limit=0.9",
        "send": 0.26, "fade_out": 0.18,
    },
    "suppression": {
        "chain": "highpass=f=50,lowpass=f=14000,"
                 "acompressor=threshold=0.05:ratio=6:attack=0.8:release=90,"
                 "alimiter=limit=0.9",
        "send": 0.16, "fade_out": 0.08,
    },
    "overwatch": {
        "chain": "highpass=f=200,lowpass=f=14000,equalizer=f=1800:t=q:w=1.0:g=3,"
                 "acompressor=threshold=0.07:ratio=5:attack=1:release=100",
        "send": 0.14, "fade_out": 0.12,
    },
    "alarm": {
        "chain": "highpass=f=150,lowpass=f=8000,equalizer=f=900:t=q:w=1.2:g=3,"
                 "acompressor=threshold=0.06:ratio=6:attack=2:release=140",
        "send": 0.12, "fade_out": 0.10,
    },
    "transition": {
        "chain": "highpass=f=300,lowpass=f=12000,"
                 "acompressor=threshold=0.09:ratio=3:attack=2:release=140",
        "send": 0.14, "fade_out": 0.10,
    },
    "ambient_bed": {
        # Beds are compressed before levelling: a dynamic bed cannot reach the
        # -24 LUFS target under a -6 dBTP ceiling without it (the limiter would
        # simply pull the whole bed down and the level would miss by several LU).
        "chain": "highpass=f=28,lowpass=f=9000,equalizer=f=180:t=q:w=0.8:g=-1.5,"
                 "equalizer=f=3200:t=q:w=1.0:g=-1.5,"
                 "acompressor=threshold=0.18:ratio=2.5:attack=25:release=450",
        "send": 0.22, "fade_out": 0.0, "loop": True,
    },
    "music_loop": {
        "chain": "highpass=f=25,lowpass=f=16000,equalizer=f=90:t=q:w=0.7:g=1.5,"
                 "acompressor=threshold=0.14:ratio=2.5:attack=12:release=350",
        "send": 0.20, "fade_out": 0.0, "loop": True,
    },
}


# --------------------------------------------------------------------------- #
# DSP
# --------------------------------------------------------------------------- #
def decode(src: Path, dst: Path) -> None:
    res = run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
               "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])
    if res.returncode != 0:
        raise SystemExit(f"decode failed {src}: {res.stderr.strip()[:300]}")


def wav_load(path: Path) -> np.ndarray:
    import wave
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        ch = w.getnchannels()
    return data.reshape(-1, ch) if ch > 1 else data.reshape(-1, 1)


def wav_save(path: Path, data: np.ndarray) -> None:
    import wave
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def loop_seam(data: np.ndarray, crossfade: float = 0.6) -> np.ndarray:
    """Circular crossfade so the bed loops without a click or a level jump.

    Head and tail are mixed with complementary equal-power curves; the result has
    the same length as the input minus the crossfade, and the join is energy
    continuous (verified by verify_bank's seam metric).
    """
    n = int(crossfade * SR)
    if n < 32 or data.shape[0] < 4 * n:
        return data
    head = data[:n].copy()
    tail = data[-n:].copy()
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    fade_in = np.sin(t * math.pi / 2.0)
    fade_out = np.cos(t * math.pi / 2.0)
    data[:n] = head * fade_in + tail * fade_out
    return data[:-n]


def mono_compat(data: np.ndarray) -> np.ndarray:
    """Keep the mix mono-safe: reject anti-phase content that vanishes on mono."""
    if data.shape[1] < 2:
        return data
    mid = (data[:, 0] + data[:, 1]) * 0.5
    side = (data[:, 0] - data[:, 1]) * 0.5
    energy_mid = float(np.mean(mid ** 2)) + 1e-12
    energy_side = float(np.mean(side ** 2))
    if energy_side > 4.0 * energy_mid:      # extreme out-of-phase stereo
        data = np.stack([mid, mid], axis=1)
    return data


def build_layer(src: Path, recipe: dict, seconds: float, workdir: Path,
                tag: str, reverb_ir: Path, send: float,
                variant: int = 0, variants: int = 1) -> Path:
    """Run one source through the design chain plus a convolution reverb send.

    When a cue ships several variants, each one is pitch-shifted by a small
    deterministic amount so the round-robin in the game is not audibly the same
    sample three times.  The shift is a rate/resample/atempo pair, which moves
    pitch without changing duration.
    """
    raw = workdir / f"{tag}_raw.wav"
    decode(src, raw)
    chain = trim_filter(seconds, 0.004, recipe.get("fade_out", 0.05))
    if variants > 1:
        steps = [-1.0, 1.0, 0.0, 1.6, -1.6]
        semis = steps[(variant - 1) % len(steps)]
        factor = 2 ** (semis / 12.0)
        chain += (f",asetrate={int(round(SR * factor))},aresample={SR}"
                  f",atempo={1.0 / factor:.6f}")
    filters = chain + ("," + recipe["chain"] if recipe.get("chain") else "")
    shaped = workdir / f"{tag}_shaped.wav"
    res = run(["ffmpeg", "-y", "-v", "error", "-i", str(raw),
               "-af", filters, "-ar", str(SR), "-ac", "2", str(shaped)])
    if res.returncode != 0:
        raise SystemExit(f"chain failed {src}: {res.stderr.strip()[:300]}")

    if send <= 0:
        return shaped
    wet = workdir / f"{tag}_wet.wav"
    res = run(["ffmpeg", "-y", "-v", "error", "-i", str(shaped), "-i", str(reverb_ir),
               "-filter_complex",
               f"[0:a][1:a]afir=dry=0:wet=1[rv];[rv]volume={send:.3f}[w]",
               "-map", "[w]", "-ar", str(SR), "-ac", "2", str(wet)])
    if res.returncode != 0:
        return shaped
    mixed = workdir / f"{tag}_layer.wav"
    res = run(["ffmpeg", "-y", "-v", "error", "-i", str(shaped), "-i", str(wet),
               "-filter_complex", "[0:a][1:a]amix=inputs=2:normalize=0[m]",
               "-map", "[m]", "-ar", str(SR), "-ac", "2", str(mixed)])
    return mixed if res.returncode == 0 else shaped


def make_ir(path: Path, seconds: float = 1.6, seed: int = 7) -> None:
    """Synthetic decaying-noise impulse response (no external IR asset needed)."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    env = np.exp(-t * 3.4) * (1.0 - np.exp(-t * 240.0))
    left = rng.standard_normal(n) * env
    right = rng.standard_normal(n) * env
    # darken the tail progressively so the reverb sits behind the transient
    for ch in (left, right):
        alpha = 0.35
        for i in range(1, n):
            ch[i] = ch[i - 1] * alpha + ch[i] * (1 - alpha)
    data = np.stack([left, right], axis=1)
    data /= max(1e-9, float(np.max(np.abs(data))))
    wav_save(path, data * 0.9)


def normalise(src: Path, dst: Path, lufs: float, tp: float, cls: str) -> dict:
    """Level a cue for the mix.

    Beds and music (>= 2.5 s, sustained, low crest) are normalised with two-pass
    EBU R128 to the class LUFS target.  Everything else — one-shots, stingers, UI,
    footsteps, impacts — is levelled by **peak**, because a 100 ms click and a
    1 s metallic ring have incomparable crest factors and RMS levelling would make
    the click 8 dB quieter or the ring 8 dB louder than intended. Relative
    prominence is set by the cue trim, the bus gains and the designer's ear, which
    is the only place it can be judged.

    The limiter ceiling carries a 1.2 dB inter-sample margin: `alimiter` bounds
    sample peaks, and true-peak meters read up to ~1 dB higher.
    """
    duration = ffprobe_duration(src)
    if cls in ("ambient", "music") and duration >= LUFS_MIN_SECONDS:
        first = loudness(src)
        if first.get("input_i") not in (None, "-inf"):
            res = run([
                "ffmpeg", "-y", "-v", "error", "-i", str(src),
                "-af",
                f"loudnorm=I={lufs}:TP={tp}:LRA=11:"
                f"measured_I={first['input_i']}:measured_TP={first['input_tp']}:"
                f"measured_LRA={first['input_lra']}:measured_thresh={first['input_thresh']}:"
                f"offset={first.get('target_offset', 0)}:linear=true,"
                f"aresample=192000,alimiter=limit={10 ** ((tp - 1.2) / 20):.4f}:level=false,"
                f"aresample={SR}",
                "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst),
            ])
            if res.returncode != 0:
                raise SystemExit(f"normalise failed {src}: {res.stderr.strip()[:300]}")
            return {"mode": "lufs", **first}

    data = mono_compat(wav_load(src))
    ceiling = 10 ** ((tp - 1.2) / 20.0)
    peak = float(np.max(np.abs(data))) + 1e-12
    data = data * (ceiling / peak)
    wav_save(dst, data)
    tmp_lim = dst.with_suffix(".lim.wav")
    res = run(["ffmpeg", "-y", "-v", "error", "-i", str(dst),
               "-af", f"aresample=192000,alimiter=limit={ceiling:.4f}:level=false,"
                      f"aresample={SR}",
               "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(tmp_lim)])
    if res.returncode != 0:
        raise SystemExit(f"limit failed {src}: {res.stderr.strip()[:300]}")
    tmp_lim.replace(dst)
    return {"mode": "peak", "input_tp": round(20 * math.log10(peak), 2),
            "target_dbfs": round(tp - 1.2, 2)}


def encode(master: Path, out_dir: Path, stem: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ogg = out_dir / f"{stem}.ogg"
    m4a = out_dir / f"{stem}.m4a"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(master),
         "-c:a", "libvorbis", "-q:a", "4", str(ogg)])
    run(["ffmpeg", "-y", "-v", "error", "-i", str(master),
         "-c:a", "aac", "-b:a", "112k", "-movflags", "+faststart", str(m4a)])
    return {"ogg": ogg, "m4a": m4a}


# --------------------------------------------------------------------------- #
# cue build
# --------------------------------------------------------------------------- #
def build_cue(cue: dict, sources: list[dict], spec: dict, workdir: Path,
              out_dir: Path, ir: Path) -> dict:
    name = cue["name"]
    cls = cue["class"]
    target = spec["targets"][cls]
    recipe = RECIPES[cue["recipe"]]
    seconds = float(cue.get("max_seconds", 1.0))
    gain_db = float(cue.get("gain_db", 0.0))
    variants = int(cue.get("variants", 1))
    send = float(recipe.get("send", 0.0))
    loop = bool(cue.get("loop", recipe.get("loop", False)))

    masters: list[dict] = []
    for variant in range(1, variants + 1):
        tag = f"{name}_{variant}" if variants > 1 else name
        layer_paths = []
        for i, source in enumerate(sources):
            src = LIBRARY / source["path"]
            if not src.exists():
                raise SystemExit(f"missing source {src}")
            layer_paths.append(build_layer(src, recipe, seconds, workdir,
                                           f"{tag}_s{i}", ir, send,
                                           variant, variants))

        # concatenate/repeat short sources when the cue needs a longer bed
        assembled = workdir / f"{tag}_assembled.wav"
        if len(layer_paths) == 1:
            # NOTE: the loop seam is applied after mastering, not here.
            # alimiter resets its first lookahead window, which re-introduces a
            # step at the join; the seam has to be the final operation.
            data = mono_compat(wav_load(layer_paths[0]))
            wav_save(assembled, data)
        else:
            listfile = workdir / f"{tag}_concat.txt"
            listfile.write_text("".join(f"file '{p}'\n" for p in layer_paths), encoding="utf-8")
            res = run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                       "-i", str(listfile), "-ar", str(SR), "-ac", "2", str(assembled)])
            if res.returncode != 0:
                raise SystemExit(f"concat failed for {tag}: {res.stderr.strip()[:200]}")

        if abs(gain_db) > 0.01:
            gained = workdir / f"{tag}_gain.wav"
            run(["ffmpeg", "-y", "-v", "error", "-i", str(assembled),
                 "-af", f"volume={gain_db}dB", str(gained)])
            assembled = gained

        master = out_dir / "master" / f"{tag}.wav"
        master.parent.mkdir(parents=True, exist_ok=True)
        measurement = normalise(assembled, master, target["lufs"], target["true_peak"], cls)
        if loop:
            wav_save(master, loop_seam(wav_load(master)))
        encoded = encode(master, out_dir / "web", tag)

        final = loudness(master)
        measured_rms = 20 * math.log10(
            float(np.sqrt(np.mean(wav_load(master) ** 2))) + 1e-12)
        final_i = final.get("input_i")
        masters.append({
            "stem": tag,
            "master": master.relative_to(OUT).as_posix(),
            "web": {k: p.relative_to(OUT).as_posix() for k, p in encoded.items()},
            "source": [s["path"] for s in sources],
            "recipe": cue["recipe"],
            "duration": round(ffprobe_duration(master), 3),
            "lufs_target": target["lufs"],
            "true_peak_target": target["true_peak"],
            "level_mode": measurement.get("mode"),
            "rms_target_dbfs": measurement.get("target_dbfs"),
            "lufs_measured": (round(float(final_i), 2)
                              if final_i not in (None, "-inf") else None),
            "rms_dbfs_measured": round(measured_rms, 2),
            "true_peak_dbtp": round(float(final.get("input_tp", float("nan"))), 2),
            "pre_normalise_lufs": measurement.get("input_i"),
            "pre_normalise_lra": measurement.get("input_lra"),
            "size_bytes": {k: p.stat().st_size for k, p in encoded.items()},
            "sha256": sha256(master),
        })
        print(f"  {tag:<28} {masters[-1]['duration']:>6.2f}s "
              f"{(masters[-1]['lufs_measured'] or float('nan')):>6.1f} LUFS "
              f"{masters[-1]['rms_dbfs_measured']:>6.1f} dBFS "
              f"{masters[-1]['true_peak_dbtp']:>6.1f} dBTP "
              f"ogg {masters[-1]['size_bytes']['ogg']//1024:>4} KB")
    return {
        "name": name,
        "class": cls,
        "surface": cue.get("surface", "game"),
        "loop": loop,
        "variants": masters,
    }


def cmd_build(only: set[str], dry: bool) -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    index = load_index()
    picks = json.loads(PICKS.read_text(encoding="utf-8")) if PICKS.exists() else {}
    out_dir = OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    ir = out_dir / "_ir_synthetic_1_6s.wav"
    if not ir.exists():
        make_ir(ir)

    manifest_cues: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="ioa-audio-") as td:
        workdir = Path(td)
        for cue in spec["cues"]:
            if only and cue["name"] not in only:
                continue
            print(f"[{cue['name']}] {cue['recipe']}")
            sources = pick(cue, index, picks)
            for s in sources:
                print(f"  src {s['path']} ({s.get('duration', 0):.2f}s, score {s.get('score')})")
            if dry:
                continue
            manifest_cues.append(build_cue(cue, sources, spec, workdir, out_dir, ir))

    if dry:
        return

    prior: list[dict] = []
    mpath = out_dir / "manifest.json"
    if mpath.exists():
        prior = json.loads(mpath.read_text(encoding="utf-8")).get("cues", [])
    merged = {c["name"]: c for c in prior}
    merged.update({c["name"]: c for c in manifest_cues})
    doc = {
        "bank": "ioa-audio",
        "version": "0.1.0",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample_rate": SR,
        "channels": 2,
        "loudness_standard": "ITU-R BS.1770-5 / EBU R128 (ffmpeg loudnorm), -1 dBTP ceiling",
        "targets": spec["targets"],
        "sources": _source_summary(),
        "cues": [merged[k] for k in sorted(merged)],
    }
    mpath.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"manifest -> {mpath} ({len(merged)} cues)")


def cmd_sync_ioa(ioa_root: Path) -> None:
    """Copy the built bank into the game and emit its runtime cue manifest.

    The game must not carry a hand-maintained list of audio keys: the bank is the
    authority, and LoadingScene loads whatever this manifest declares (OGG with an
    M4A fallback for Safari).
    """
    bank = OUT / "manifest.json"
    if not bank.exists():
        raise SystemExit(f"no bank manifest at {bank}; run --build first")
    doc = json.loads(bank.read_text(encoding="utf-8"))

    public_audio = ioa_root / "frontend" / "public" / "assets" / "audio" / "bank"
    public_audio.mkdir(parents=True, exist_ok=True)
    data_dir = ioa_root / "frontend" / "src" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    cues: dict[str, dict] = {}
    written = 0
    for cue in doc["cues"]:
        channel = {
            "ambient": "ambient",
            "music": "music",
            "ui": "ui",
        }.get(cue["class"], "sfx")
        variants = []
        for var in cue["variants"]:
            for kind, rel in var["web"].items():
                src = OUT / rel
                if not src.exists():
                    continue
                dst = public_audio / src.name
                if (not dst.exists()) or sha256(dst) != sha256(src):
                    dst.write_bytes(src.read_bytes())
                    written += 1
            variants.append({
                "key": var["stem"],
                "ogg": f"assets/audio/bank/{var['stem']}.ogg",
                "m4a": f"assets/audio/bank/{var['stem']}.m4a",
                "volume": 1.0,
            })
        cues[cue["name"]] = {
            "channel": channel,
            "loop": bool(cue["loop"]),
            "variants": variants,
        }

    live = {p.name for p in public_audio.iterdir() if p.is_file()}
    keep = {Path(v[k]).name for c in cues.values() for v in c["variants"]
            for k in ("ogg", "m4a")}
    for stale in sorted(live - keep):
        (public_audio / stale).unlink()

    runtime = {
        "bank": doc.get("bank"),
        "version": doc.get("version"),
        "generated": doc.get("generated"),
        "sampleRate": doc.get("sample_rate"),
        "cueCount": len(cues),
        "cues": cues,
    }
    out_json = data_dir / "audioManifest.json"
    out_json.write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    print(f"synced {written} file(s) -> {public_audio}")
    print(f"runtime manifest -> {out_json} ({len(cues)} cues)")


def _source_summary() -> dict:
    manifest = LIBRARY / "MANIFEST.json"
    if not manifest.exists():
        return {}
    return json.loads(manifest.read_text(encoding="utf-8")).get("sources", {})


def cmd_list(cue_name: str) -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    cue = next((c for c in spec["cues"] if c["name"] == cue_name), None)
    if cue is None:
        raise SystemExit(f"unknown cue '{cue_name}'")
    index = load_index()
    for cand in candidates(cue, index):
        print(f"{cand['score']:>6.2f} {cand['duration']:>7.2f}s  {cand['path']}")


# --------------------------------------------------------------------------- #
# verification gate
# --------------------------------------------------------------------------- #
def cmd_verify(tolerance_lu: float = 2.0) -> int:
    mpath = OUT / "manifest.json"
    if not mpath.exists():
        raise SystemExit(f"no bank manifest at {mpath}")
    doc = json.loads(mpath.read_text(encoding="utf-8"))
    failures: list[str] = []
    checked = 0
    seen: dict[str, str] = {}
    for cue in doc["cues"]:
        for var in cue["variants"]:
            master = OUT / var["master"]
            if not master.exists():
                failures.append(f"{var['stem']}: missing master")
                continue
            checked += 1
            m = loudness(master)
            try:
                lufs = float(m["input_i"])
                tp = float(m["input_tp"])
            except (KeyError, ValueError):
                failures.append(f"{var['stem']}: unmeasurable")
                continue
            target_lufs = float(var["lufs_target"])
            if var.get("level_mode") == "lufs":
                tp_target = float(var.get("true_peak_target") or -1.0)
                # Target-or-ceiling: a tonal bed cannot always reach its loudness
                # target under the true-peak ceiling, and crushing it to try is
                # worse than letting the ceiling bind. Louder-than-target always
                # fails; quieter-than-target passes only when the ceiling is what
                # stopped it.
                # the applied ceiling carries the 1.2 dB inter-sample margin
                ceiling_bound = tp >= tp_target - 1.6
                too_quiet = lufs < target_lufs - tolerance_lu
                too_loud = lufs > target_lufs + tolerance_lu
                if too_loud or (too_quiet and not ceiling_bound):
                    failures.append(
                        f"{var['stem']}: {lufs:.1f} LUFS vs target {target_lufs:.1f}" + (
                            "" if not too_quiet else " (not ceiling-bound)"))
            if var.get("level_mode") == "peak":
                if not (-6.5 <= tp <= -0.9):
                    failures.append(f"{var['stem']}: peak-mode true peak {tp:.1f} dBTP outside -6.5..-1")
            if tp > -0.9:
                failures.append(f"{var['stem']}: true peak {tp:.1f} dBTP exceeds -1")
            digest = sha256(master)
            if digest in seen:
                failures.append(f"{var['stem']}: duplicate of {seen[digest]}")
            seen[digest] = var["stem"]
            for kind, rel in var["web"].items():
                web = OUT / rel
                if not web.exists() or web.stat().st_size == 0:
                    failures.append(f"{var['stem']}: missing web {kind}")
            if cue["loop"]:
                if _seam_jump(master) > SEAM_TOLERANCE:
                    failures.append(f"{var['stem']}: loop seam discontinuity")
    print(f"checked {checked} masters, {len(failures)} failure(s)")
    for f in failures:
        print("  FAIL", f)
    return 1 if failures else 0


def _seam_jump(path: Path) -> float:
    """Click test for a loop join.

    Compares the sample step across the loop point (last sample -> first sample)
    against the largest ordinary step inside the file.  Comparing window RMS
    instead would flag any looping bed whose start and end simply carry different
    material, which is not a defect.
    """
    data = wav_load(path)
    if data.shape[0] < 8:
        return 0.0
    steps = np.abs(np.diff(data[:, 0]))
    reference = float(np.percentile(steps, 99.9)) + 1e-9
    join = float(np.abs(data[0, 0] - data[-1, 0]))
    return join / reference


SEAM_TOLERANCE = 3.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--list-candidates", metavar="CUE")
    ap.add_argument("--only", default="", help="comma-separated cue names")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sync-ioa", metavar="PATH",
                    help="game repo root (copies the bank + writes the runtime manifest)")
    args = ap.parse_args()
    only = {c.strip() for c in args.only.split(",") if c.strip()}
    if args.list_candidates:
        cmd_list(args.list_candidates)
    if args.build:
        cmd_build(only, args.dry_run)
    if args.verify:
        raise SystemExit(cmd_verify())
    if args.sync_ioa:
        cmd_sync_ioa(Path(args.sync_ioa).resolve())


if __name__ == "__main__":
    random.seed(20261110)   # noqa: F401 - reserved for future stochastic design
    main()
