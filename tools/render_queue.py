#!/usr/bin/env python3
"""
render_queue.py — Render job queue for the IoA asset pipeline.

Manages a queue of render jobs that can be added during the day and
processed when the machine is idle (night, lunch break, etc.).

Queue file: output/render_queue.json

Usage:
    # Add a unit to the render queue
    python -m tools.render_queue add --unit iron_directorate_line_infantry
    python -m tools.render_queue add --config configs/vehicles/predator_tank.json --unit predator_tank

    # List queued jobs
    python -m tools.render_queue list
    python -m tools.render_queue list --status done
    python -m tools.render_queue list --verbose

    # Remove a job
    python -m tools.render_queue remove --id 3

    # Run all queued jobs (processes sequentially)
    python -m tools.render_queue run
    python -m tools.render_queue run --parallel 2    # run up to 2 renders at once

    # Clear completed jobs
    python -m tools.render_queue clear --status done
    python -m tools.render_queue clear --all

    # Show queue status summary
    python -m tools.render_queue status

    # Schedule for later (Linux at/cron)
    at 02:00 -f tools/schedule_render.sh
    python -m tools.render_queue schedule --at "22:00"
"""

import os
import sys
import json
import time
import threading
import subprocess
import signal
import argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# =============================================================================
# QUEUE FILE
# =============================================================================

QUEUE_DIR = os.path.join(PROJECT_ROOT, "output")
QUEUE_PATH = os.path.join(QUEUE_DIR, "render_queue.json")
PROGRESS_PATH = os.path.join(QUEUE_DIR, "render_progress.json")
PAUSE_PATH = os.path.join(QUEUE_DIR, ".render_pause")
LOG_DIR = os.path.join(QUEUE_DIR, "render_logs")


# =============================================================================
# BLENDER PROCESS MANAGEMENT
# =============================================================================

def kill_blender_processes(include_gui: bool = False):
    """Force-kill all stale Blender processes before starting a new render.

    Prevents resource exhaustion from orphaned/crashed Blender processes.
    By default only kills --background processes (headless renders).
    Set include_gui=True to also kill GUI Blender instances.
    """
    import subprocess
    import signal

    try:
        # Get all blender PIDs
        result = subprocess.run(
            ["pgrep", "-x", "blender"],
            capture_output=True, text=True, timeout=5,
        )
        if not result.stdout.strip():
            return 0

        pids = [int(p) for p in result.stdout.strip().split() if p]
        if not pids:
            return 0

        killed = 0
        for pid in pids:
            try:
                # Check if this is a background render process
                cmdline = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "args="],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()

                is_background = "--background" in cmdline
                is_gui = not is_background and "blender" in cmdline.lower()

                if is_background or (include_gui and is_gui):
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                    log(f"Killed stale Blender PID {pid} ({'--background' if is_background else 'GUI'})")
            except (ProcessLookupError, OSError):
                pass

        if killed > 0:
            # Brief wait to ensure processes release GPU/resources
            time.sleep(0.5)
            log(f"Cleaned {killed} stale Blender process(es)")

        return killed
    except FileNotFoundError:
        # pgrep not available — fallback to ps-based approach
        return _kill_blender_fallback(include_gui)
    except subprocess.TimeoutExpired:
        return 0


def _kill_blender_fallback(include_gui: bool = False) -> int:
    """Fallback: iterate /proc to find and kill blender processes."""
    killed = 0
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/cmdline", "rb") as f:
                    raw = f.read()
                cmdline = raw.decode("utf-8", errors="replace").replace("\0", " ")
                if "blender" not in cmdline.lower():
                    continue
                is_background = "--background" in cmdline
                is_gui = not is_background
                if is_background or (include_gui and is_gui):
                    os.kill(int(entry), signal.SIGKILL)
                    killed += 1
            except (ProcessLookupError, OSError, IOError):
                pass
    except FileNotFoundError:
        pass  # /proc not available (unusual)
    if killed > 0:
        time.sleep(0.5)
        log(f"Cleaned {killed} stale Blender process(es) (fallback)")
    return killed


def _load_queue() -> list:
    """Load the render queue from disk. Returns list of job dicts."""
    if not os.path.exists(QUEUE_PATH):
        return []
    try:
        with open(QUEUE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_queue(queue: list):
    """Save the render queue to disk."""
    os.makedirs(QUEUE_DIR, exist_ok=True)
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def _next_id(queue: list) -> int:
    """Generate the next unique job ID."""
    if not queue:
        return 1
    return max(j.get("id", 0) for j in queue) + 1


def _timestamp() -> str:
    """Return current timestamp string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_path(job_id: int, unit_name: str) -> str:
    """Get the log file path for a render job."""
    os.makedirs(LOG_DIR, exist_ok=True)
    safe_name = unit_name.replace("/", "_")
    return os.path.join(LOG_DIR, f"render_{job_id:04d}_{safe_name}.log")


# =============================================================================
# PROGRESS TRACKING — real-time progress file for the dashboard
# =============================================================================

# Per-animation frame counts (from parametric_unit_generator.py defaults)
ANIM_FRAMES = {
    "idle": 4, "walk": 7, "attack": 5, "hurt": 3, "die": 7,
}
DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
TOTAL_FRAMES_PER_UNIT = sum(ANIM_FRAMES.values()) * len(DIRECTIONS)  # 208


def _write_progress(phase: str, unit_name: str = "", job_id: int = 0,
                    done: int = 0, total: int = 0,
                    current_anim: str = "", current_dir: str = "",
                    log_tail: str = ""):
    """Write real-time progress to the shared progress file."""
    try:
        progress = {
            "phase": phase,
            "unit_name": unit_name,
            "job_id": job_id,
            "steps": {"done": done, "total": total},
            "pct": round(done / total * 100, 1) if total > 0 else 0,
            "current": {},
            "log_tail": log_tail[-2000:],
            "timestamp": _timestamp(),
        }
        if current_anim:
            progress["current"]["animation"] = current_anim
        if current_dir:
            progress["current"]["direction"] = current_dir
        os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
        with open(PROGRESS_PATH, "w") as f:
            json.dump(progress, f)
    except (IOError, OSError):
        pass


def _clear_progress():
    """Clear the progress file (render complete)."""
    try:
        _write_progress("done", done=1, total=1)
    except (IOError, OSError):
        pass


# =============================================================================
# DISCOVERY — find units by name or config
# =============================================================================

def _find_blend_path(unit_name: str) -> str:
    """Find the .blend file for a given unit name."""
    units_dir = os.path.join(PROJECT_ROOT, "assets", "units")
    unit_dir = os.path.join(units_dir, unit_name)

    if os.path.exists(unit_dir):
        model_blends = list(Path(unit_dir).rglob("*.blend"))
        if model_blends:
            # Prefer v2 blends in model/ subdir
            for b in model_blends:
                if "model" in str(b) and "v2" in b.name.lower():
                    return str(b)
            # Fall back to any .blend
            return str(model_blends[0])

    # Broader search
    for b in Path(units_dir).rglob(f"**/{unit_name}*.blend"):
        return str(b)

    # Search all .blend files for matching name
    for b in Path(units_dir).rglob("*.blend"):
        if unit_name in str(b):
            return str(b)

    return None


def _find_config_path(unit_name: str) -> str:
    """Find a config file for a given unit name."""
    for root, dirs, files in os.walk(os.path.join(PROJECT_ROOT, "configs")):
        for f in files:
            if f.endswith(".json") and unit_name in f:
                return os.path.join(root, f)
    return None


def _get_units_dir_list() -> list:
    """List all unit directories that have configs or .blend files."""
    units = set()

    # From configs
    for root, dirs, files in os.walk(os.path.join(PROJECT_ROOT, "configs")):
        for f in files:
            if f.endswith(".json"):
                units.add(f.replace(".json", ""))

    # From existing unit directories
    units_dir = os.path.join(PROJECT_ROOT, "assets", "units")
    if os.path.exists(units_dir):
        for d in os.listdir(units_dir):
            if os.path.isdir(os.path.join(units_dir, d)):
                units.add(d)

    return sorted(units)


# =============================================================================
# COMMANDS
# =============================================================================

def cmd_add(args):
    """Add a unit to the render queue."""
    queue = _load_queue()
    unit_name = args.unit
    config_path = args.config
    body_type = args.body_type or "humanoid"
    priority = args.priority or 0

    # Validate
    if not config_path:
        config_path = _find_config_path(unit_name)
        if not config_path:
            print(f"  No config found for '{unit_name}'. Use --config <path> to specify.")
            return 1

    # Check for duplicates (same unit, still queued)
    existing = [
        j for j in queue
        if j.get("unit_name") == unit_name and j.get("status") in ("queued", "running")
    ]
    if existing and not args.force:
        print(f"  '{unit_name}' is already queued (job #{existing[0]['id']}, status: {existing[0]['status']})")
        print(f"  Use --force to queue again anyway")
        return 0

    job = {
        "id": _next_id(queue),
        "unit_name": unit_name,
        "config_path": config_path,
        "body_type": body_type,
        "priority": priority,
        "status": "queued",
        "created": _timestamp(),
        "started": None,
        "completed": None,
        "log_path": _log_path(_next_id(queue), unit_name),
        "result": None,
    }

    queue.append(job)
    _save_queue(queue)
    print(f"  Queued #{job['id']}: {unit_name} ({body_type})")
    print(f"  Config: {config_path}")
    return 0


def cmd_list(args):
    """List all jobs in the queue."""
    queue = _load_queue()

    if not queue:
        print("  Queue is empty.")
        return 0

    # Filter by status
    if args.status:
        queue = [j for j in queue if j.get("status") == args.status]
        if not queue:
            print(f"  No jobs with status '{args.status}'.")
            return 0

    # Sort by priority (higher first), then ID
    queue = sorted(queue, key=lambda j: (-j.get("priority", 0), j.get("id", 0)))

    if args.verbose:
        # Detailed listing
        for j in queue:
            status_icon = {
                "queued": "⏳", "running": "🔄", "done": "✅",
                "failed": "❌", "skipped": "⏭️",
            }.get(j.get("status", "unknown"), "❓")
            print(f"  #{j['id']} {status_icon} {j['unit_name']}")
            print(f"       Status: {j.get('status', 'unknown')}")
            print(f"       Config: {j.get('config_path', 'N/A')}")
            print(f"       Type:   {j.get('body_type', 'humanoid')}")
            print(f"       Prio:   {j.get('priority', 0)}")
            print(f"       Created: {j.get('created', 'N/A')}")
            if j.get("started"):
                print(f"       Started: {j['started']}")
            if j.get("completed"):
                print(f"       Done:    {j['completed']}")
            if j.get("log_path") and os.path.exists(j.get("log_path", "")):
                log_size = os.path.getsize(j["log_path"])
                print(f"       Log:     {j['log_path']} ({log_size} bytes)")
            print()
    else:
        # Compact listing
        print(f"{'ID':>4} {'Status':<8} {'Prio':<4} {'Unit':<50}")
        print(f"{'-'*4} {'-'*8} {'-'*4} {'-'*50}")
        for j in queue:
            print(f"{j['id']:>4} {j.get('status', '?'):<8} {j.get('priority', 0):<4} {j['unit_name']:<50}")

    # Summary
    counts = {}
    for j in queue:
        s = j.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    status_parts = [f"{v} {k}" for k, v in sorted(counts.items())]
    print(f"\n  Total: {len(queue)} jobs — {', '.join(status_parts)}")

    return 0


def cmd_remove(args):
    """Remove a job from the queue."""
    queue = _load_queue()
    job_id = args.id
    target = [j for j in queue if j["id"] == job_id]

    if not target:
        print(f"  Job #{job_id} not found.")
        return 1

    job = target[0]
    if job.get("status") == "running":
        print(f"  Job #{job_id} ({job['unit_name']}) is running. Remove anyway? (use --force)")
        if not args.force:
            return 0

    queue = [j for j in queue if j["id"] != job_id]
    _save_queue(queue)
    print(f"  Removed #{job_id}: {job['unit_name']}")
    return 0


def cmd_clear(args):
    """Clear completed/failed/skipped jobs."""
    queue = _load_queue()
    before = len(queue)

    if args.all:
        queue = []
    elif args.status:
        queue = [j for j in queue if j.get("status") not in args.status]
    else:
        queue = [j for j in queue if j.get("status") in ("queued", "running")]

    after = len(queue)
    _save_queue(queue)
    print(f"  Cleared {before - after} jobs. {after} remaining.")
    return 0


def cmd_status(args):
    """Show queue status summary."""
    queue = _load_queue()

    if not queue:
        print("  No jobs in queue history.")
        return 0

    counts = {}
    for j in queue:
        s = j.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1

    queued = counts.get("queued", 0)
    running = counts.get("running", 0)
    done = counts.get("done", 0)
    failed = counts.get("failed", 0)

    total_render_time = 0
    for j in queue:
        if j.get("started") and j.get("completed"):
            try:
                start = datetime.strptime(j["started"], "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(j["completed"], "%Y-%m-%d %H:%M:%S")
                total_render_time += (end - start).total_seconds()
            except (ValueError, TypeError):
                pass

    print(f"\n  ╔═══ Render Queue ═══╗")
    print(f"  ║                    ║")
    print(f"  ║  Queued:  {queued:<3}            ║")
    print(f"  ║  Running: {running:<3}            ║")
    print(f"  ║  Done:    {done:<3}            ║")
    print(f"  ║  Failed:  {failed:<3}            ║")
    print(f"  ║  Total:   {len(queue):<3}            ║")
    print(f"  ║                    ║")
    if total_render_time > 0:
        hours = int(total_render_time // 3600)
        minutes = int((total_render_time % 3600) // 60)
        print(f"  ║  Render time:       ║")
        print(f"  ║  {hours}h {minutes}m            ║")
    print(f"  ╚════════════════════╝")

    # Show newest jobs first
    recent = sorted(queue, key=lambda j: j.get("created", ""), reverse=True)[:5]
    if recent:
        print(f"\n  Recent jobs:")
        for j in recent:
            icon = {"done": "✅", "failed": "❌", "running": "🔄", "queued": "⏳"}.get(j.get("status", ""), "❓")
            print(f"    {icon} #{j['id']} {j['unit_name']} — {j.get('status', '?')}")

    return 0


# =============================================================================
# RUN — Process all queued renders
# =============================================================================

# Per-animation frame counts (from parametric_unit_generator.py defaults)
ANIM_FRAMES = {
    "idle": 4, "walk": 7, "attack": 5, "hurt": 3, "die": 7,
}
DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
TOTAL_FRAMES_PER_UNIT = sum(ANIM_FRAMES.values()) * len(DIRECTIONS)  # 208

PROGRESS_PATH = os.path.join(QUEUE_DIR, "render_progress.json")
PAUSE_PATH = os.path.join(QUEUE_DIR, ".render_pause")


def _recover_stale_jobs(queue: list) -> list:
    """Reset jobs stuck in 'running' state back to 'queued' for crash recovery.
    Also detect already-rendered units and mark them done."""
    changed = 0
    for j in queue:
        if j.get("status") == "running":
            j["status"] = "queued"
            j["started"] = None
            j["completed"] = None
            j["result"] = None
            changed += 1
            continue

        # Skip already-completed
        if j.get("status") in ("done", "failed"):
            continue

        # Check if this unit was already fully rendered (e.g., from a previous run)
        if j.get("status") == "queued" and j.get("unit_name"):
            unit_name = j["unit_name"]
            unit_dir = os.path.join(PROJECT_ROOT, "assets", "units", unit_name)
            if os.path.exists(unit_dir):
                raw_dirs = []
                for root, dirs, files in os.walk(unit_dir):
                    if root.endswith("/raw") or root.endswith("\\raw"):
                        if any(f.endswith(".png") for f in files):
                            total_pngs = sum(
                                1 for _, _, fs in os.walk(root) for f in fs if f.endswith(".png")
                            )
                            # If we have substantial frames (more than expected total is impossible,
                            # but > 180 is "close enough" to 208)
                            if total_pngs >= 180:
                                j["status"] = "done"
                                j["completed"] = _timestamp()
                                j["result"] = "pass (previous render)"
                                changed += 1

    if changed:
        print(f"  Recovery: {changed} jobs cleaned up (stale running → queued / already-rendered → done)")
    return queue


def _is_paused() -> bool:
    return os.path.exists(PAUSE_PATH)


def _set_pause(paused: bool):
    """Create or remove the pause sentinel file."""
    if paused:
        with open(PAUSE_PATH, "w") as f:
            f.write(f"Paused at {_timestamp()}\n")
    else:
        try:
            os.remove(PAUSE_PATH)
        except FileNotFoundError:
            pass


def _check_already_rendered(unit_name: str) -> bool:
    """Check if a unit already has complete rendered output from a previous run."""
    unit_dir = os.path.join(PROJECT_ROOT, "assets", "units", unit_name)
    if not os.path.exists(unit_dir):
        return False
    for root, dirs, files in os.walk(unit_dir):
        if root.endswith("/raw") or root.endswith("\\raw"):
            pngs = [f for f in files if f.endswith(".png")]
            if len(pngs) >= TOTAL_FRAMES_PER_UNIT * 0.8:  # 80% threshold
                return True
    return False


def _write_progress(phase: str, unit_name: str = "", job_id: int = 0,
                    done: int = 0, total: int = 0,
                    current_anim: str = "", current_dir: str = "",
                    log_tail: str = ""):
    """Write real-time progress to the shared progress file for the dashboard."""
    try:
        progress = {
            "phase": phase,
            "unit_name": unit_name,
            "job_id": job_id,
            "steps": {"done": done, "total": total},
            "pct": round(done / total * 100, 1) if total > 0 else 0,
            "current": {},
            "log_tail": log_tail[-2000:],
            "timestamp": _timestamp(),
        }
        if current_anim:
            progress["current"]["animation"] = current_anim
        if current_dir:
            progress["current"]["direction"] = current_dir
        os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
        with open(PROGRESS_PATH, "w") as f:
            json.dump(progress, f)
    except (IOError, OSError):
        pass


def _clear_progress():
    """Clear the progress file (render complete)."""
    try:
        _write_progress("done", done=1, total=1)
    except (IOError, OSError):
        pass


def _render_job(job: dict, engine: str, fast: bool) -> dict:
    """Render a single job with real-time progress tracking to sidecar file."""
    unit_name = job["unit_name"]
    config_path = job.get("config_path", "")
    body_type = job.get("body_type", "humanoid")
    log_path = job.get("log_path", _log_path(job["id"], unit_name))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    job["status"] = "running"
    job["started"] = _timestamp()
    job["log_path"] = log_path

    # Kill stale Blender processes before starting (avoids resource exhaustion)
    kill_blender_processes()

    with open(log_path, "w") as log:
        _write_progress("generating", unit_name, job["id"],
                        done=0, total=TOTAL_FRAMES_PER_UNIT)
        log.write(f"=== Render Job #{job['id']}: {unit_name} ===\n")
        log.write(f"Started: {job['started']}\n")
        log.write(f"Config: {config_path}\n")
        log.write(f"Body type: {body_type}\n\n")

        # Step 1: Generate .blend (only if config exists)
        if config_path and os.path.exists(config_path):
            log.write(f"[1/3] Generating .blend from config...\n")
            log.flush()
            result = subprocess.run(
                ["blender", "--background", "--python",
                 os.path.join(SCRIPT_DIR, "blender", "parametric_unit_generator.py"),
                 "--", "--config", config_path],
                capture_output=True, text=True, timeout=120,
            )
            log.write(result.stdout)
            if result.stderr:
                log.write(f"STDERR: {result.stderr}\n")
            if result.returncode != 0:
                log.write(f"  Generation FAILED (exit {result.returncode})\n")
                job["status"] = "failed"
                job["completed"] = _timestamp()
                job["result"] = "generation_failed"
                _write_progress("failed", unit_name, job["id"],
                                done=0, total=TOTAL_FRAMES_PER_UNIT)
                return job
            log.write(f"  Generation OK\n\n")
            log.flush()

        # Step 2: Find .blend file
        blend_path = _find_blend_path(unit_name)
        if not blend_path:
            log.write(f"  ERROR: No .blend file found for '{unit_name}'\n")
            job["status"] = "failed"
            job["completed"] = _timestamp()
            job["result"] = "no_blend_file"
            _write_progress("failed", unit_name, job["id"],
                            done=0, total=TOTAL_FRAMES_PER_UNIT)
            return job

        log.write(f"[2/3] Rendering: {blend_path}\n\n")
        log.flush()

        # Remove old renders
        render_dir = os.path.join(os.path.dirname(blend_path), "render", "raw")
        if os.path.exists(render_dir):
            import shutil
            shutil.rmtree(render_dir)

        # Build render command
        render_args = ["blender", "--background", blend_path,
                       "--python", os.path.join(SCRIPT_DIR, "blender", "render_8dir_v2.py"),
                       "--", "--engine", engine]
        if fast:
            render_args.append("--fast")
        faction = job.get("faction")
        if faction:
            render_args.extend(["--faction", faction])

        # --- STREAMING RENDER with real-time progress tracking ---
        _write_progress("rendering", unit_name, job["id"],
                        done=0, total=TOTAL_FRAMES_PER_UNIT)

        frames_done = 0
        last_frame_count = 0
        render_raw_dir = os.path.join(os.path.dirname(blend_path), "render", "raw")

        def count_rendered_frames():
            """Count actual rendered PNG files in the render directory."""
            if not os.path.exists(render_raw_dir):
                return 0
            count = 0
            for root, dirs, files in os.walk(render_raw_dir):
                count += sum(1 for f in files if f.endswith(".png"))
            return count

        # Background thread: count PNGs every 5 seconds as fallback progress
        # This works even if stdout buffering prevents real-time parsing
        stop_monitor = False

        def monitor_progress():
            while not stop_monitor:
                time.sleep(5)
                png_count = count_rendered_frames()
                if png_count > 0:
                    _write_progress(
                        "rendering", unit_name, job["id"],
                        done=png_count, total=TOTAL_FRAMES_PER_UNIT,
                        log_tail=f"Rendered {png_count}/{TOTAL_FRAMES_PER_UNIT} frames"
                    )

        monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
        monitor_thread.start()

        try:
            proc = subprocess.Popen(
                render_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # line-buffered
            )

            # Read output line by line — we log everything but progress
            # is handled by the monitor thread which counts PNG files.
            for line in proc.stdout:
                log.write(line)
                log.flush()

                if "Blender quit" in line:
                    break

            exit_code = proc.wait(timeout=30)

        except subprocess.TimeoutExpired:
            log.write(f"\n  Render TIMEOUT (10 min)\n")
            proc.kill()
            exit_code = -1
        except Exception as e:
            log.write(f"\n  Render ERROR: {e}\n")
            exit_code = -1

        finally:
            stop_monitor = True

        log.write(f"\n")

        if exit_code != 0:
            log.write(f"  Render FAILED (exit {exit_code})\n")
            job["status"] = "failed"
            job["completed"] = _timestamp()
            job["result"] = "render_failed"
            _write_progress("failed", unit_name, job["id"],
                            done=frames_done, total=TOTAL_FRAMES_PER_UNIT)
            return job

        log.write(f"  Render OK — {frames_done}/{TOTAL_FRAMES_PER_UNIT} frames\n\n")
        log.flush()

        # Step 3: Run critic
        log.write(f"[3/3] Running critic...\n\n")
        log.flush()
        _write_progress("critic", unit_name, job["id"],
                        done=frames_done, total=TOTAL_FRAMES_PER_UNIT)

        if os.path.exists(render_dir):
            critic_result = subprocess.run(
                ["python3", os.path.join(SCRIPT_DIR, "critic.py"), render_dir],
                capture_output=True, text=True, timeout=60,
            )
            log.write(critic_result.stdout)
            if critic_result.stderr:
                log.write(f"Critic STDERR: {critic_result.stderr}\n")

            if critic_result.returncode == 0:
                log.write(f"  \u2713 Critic PASSED\n")
                job["result"] = "pass"
            else:
                log.write(f"  \u26a0 Critic FAILED (check quality)\n")
                job["result"] = "critic_fail"
        else:
            log.write(f"  No render directory found at {render_dir}\n")
            job["result"] = "no_render_dir"

        job["status"] = "done"
        job["completed"] = _timestamp()
        log.write(f"\nCompleted: {job['completed']}\n")
        log.write(f"Result: {job['result']}\n")

    _clear_progress()
    return job


def cmd_run(args):
    """Process all queued render jobs."""
    # Kill any stale Blender processes before starting queue processing
    kill_blender_processes()

    queue = _load_queue()
    engine = args.engine or "CYCLES"
    fast = args.fast or False

    # Crash recovery: reset stale "running" → "queued", detect already-rendered
    queue = _recover_stale_jobs(queue)
    _save_queue(queue)

    # Remove pause file if present (user explicitly called 'run' to resume)
    if _is_paused():
        _set_pause(False)
        print("  Removed pause — resuming queue processing.")

    # Get queued jobs, sorted by priority
    queued = sorted(
        [j for j in queue if j.get("status") == "queued"],
        key=lambda j: (-j.get("priority", 0), j.get("id", 0))
    )

    if not queued:
        print("  No queued jobs to process.")
        # Show recently completed instead
        recent = [j for j in queue if j.get("status") in ("done", "failed")]
        if recent:
            print(f"  Recent completions: {len(recent)} jobs")
            for j in recent[-3:]:
                icon = "✅" if j.get("status") == "done" else "❌"
                print(f"    {icon} #{j['id']} {j['unit_name']} — {j.get('result', '?')}")
        return 0

    total = len(queued)
    start_time = time.time()
    print(f"\n  ╔═══ Processing {total} render jobs ═══╗")
    print(f"  ║  Engine: {engine:<8} Fast: {fast:<5}       ║")
    print(f"  ╚══════════════════════════════════╝")
    print()

    for i, job in enumerate(queued, 1):
        job_start = time.time()
        print(f"  [{i}/{total}] Rendering: #{job['id']} {job['unit_name']}...", end=" ")
        sys.stdout.flush()

        updated_job = _render_job(job, engine, fast)
        elapsed = time.time() - job_start

        # Update the job in the queue
        for idx, j in enumerate(queue):
            if j["id"] == updated_job["id"]:
                queue[idx] = updated_job
                break
        _save_queue(queue)

        mins, secs = divmod(int(elapsed), 60)
        if updated_job["status"] == "done":
            print(f"✓ done ({mins}m {secs}s)")
            if updated_job.get("result") == "critic_fail":
                print(f"    ⚠ Critic flagged quality issues — check log: {updated_job.get('log_path', 'N/A')}")
        else:
            print(f"✗ FAILED ({mins}m {secs}s)")
            print(f"    Log: {updated_job.get('log_path', 'N/A')}")

        # Check for pause — finish current job, then stop
        if _is_paused():
            remaining = total - i
            if remaining > 0:
                print(f"  ⏸ Paused. {remaining} jobs remaining. Resume with 'queue run'.")
            break

    elapsed = time.time() - start_time
    hours, remainder = divmod(int(elapsed), 3600)
    mins, secs = divmod(remainder, 60)
    done = sum(1 for j in queue if j.get("status") == "done")
    failed = sum(1 for j in queue if j.get("status") == "failed")

    print(f"\n  ╔═══ Render Run Complete ═══╗")
    print(f"  ║  Total: {total:<3}  Done: {done:<3}  Failed: {failed:<3}  ║")
    print(f"  ║  Time:  {hours}h {mins}m {secs}s              ║")
    print(f"  ╚══════════════════════════╝")

    if done > 0:
        print(f"\n  Next steps:")
        print(f"    PIPELINE_VERSION={get_latest_version()} python3 tools/batch_pipeline.py")
        print(f"    python3 tools/pipeline_cli.py sync --target <ioa_path>")

    return 0 if failed == 0 else 1


def get_latest_version() -> str:
    """Get the current pipeline version."""
    versions_file = os.path.join(PROJECT_ROOT, ".pipeline_version")
    if os.path.exists(versions_file):
        with open(versions_file) as f:
            return f.read().strip()
    return "v0.4.0"


# =============================================================================
# CLI COMMANDS — Pause, Resume, Clean
# =============================================================================


def cmd_pause(args):
    """Pause the render queue after the current job finishes."""
    _set_pause(True)
    print(f"  ⏸ Pause signal sent. Current job will finish, then queue stops.")
    print(f"  Resume with: queue run")
    return 0


def cmd_resume(args):
    """Resume the render queue (remove pause and start processing)."""
    was_paused = _is_paused()
    _set_pause(False)

    queue = _load_queue()
    queue = _recover_stale_jobs(queue)
    _save_queue(queue)

    remaining = sum(1 for j in queue if j.get("status") == "queued")
    if remaining == 0:
        print(f"  No queued jobs remaining.")
        done = sum(1 for j in queue if j.get("status") == "done")
        print(f"  {done} renders completed — pack with 'batch_pipeline.py'")
        return 0

    if not was_paused:
        print(f"  (wasn't paused, but {remaining} jobs remain queued)")

    # Immediately start processing again
    print(f"  ▶ Resuming — {remaining} jobs queued.")
    new_args = argparse.Namespace(
        command="run", action="run",
        engine="CYCLES", fast=True,
    )
    cmd_run(new_args)
    return 0


def cmd_clean(args):
    """Clean up stale running jobs and detect already-rendered units."""
    queue = _load_queue()
    before = sum(1 for j in queue if j.get("status") == "running")
    queue = _recover_stale_jobs(queue)
    _save_queue(queue)
    after = sum(1 for j in queue if j.get("status") == "queued")
    print(f"  Cleaned {before} stale running jobs. {after} queued, ready to run.")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="IoA Render Queue Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add units to the queue
  python -m tools.render_queue add --unit iron_directorate_line_infantry
  python -m tools.render_queue add --config configs/cinderborn/cinder_cultist.json \\
      --unit cinderborn_cinder_cultist --priority 1

  # List what's queued
  python -m tools.render_queue list

  # Process all queued jobs (run when machine is idle)
  python -m tools.render_queue run

  # Fast mode (16 Cycles samples) for quicker iteration
  python -m tools.render_queue run --fast

  # Check status
  python -m tools.render_queue status

  # Clear completed jobs
  python -m tools.render_queue clear --status done failed
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Queue command")

    # --- add ---
    add_parser = subparsers.add_parser("add", help="Add a unit to the render queue")
    add_parser.add_argument("--unit", "-u", required=True, help="Unit name")
    add_parser.add_argument("--config", "-c", default=None, help="Path to JSON config (auto-detected if omitted)")
    add_parser.add_argument("--body-type", "-t", default="humanoid", help="Body type: humanoid/vehicle/creature/insectoid")
    add_parser.add_argument("--priority", "-p", type=int, default=0, help="Priority (higher = sooner)")
    add_parser.add_argument("--force", action="store_true", help="Queue even if already queued")

    # --- list ---
    list_parser = subparsers.add_parser("list", help="List queued jobs")
    list_parser.add_argument("--status", "-s", default=None, help="Filter by status")
    list_parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")

    # --- remove ---
    remove_parser = subparsers.add_parser("remove", help="Remove a job from the queue")
    remove_parser.add_argument("--id", "-i", type=int, required=True, help="Job ID to remove")
    remove_parser.add_argument("--force", action="store_true", help="Force remove even if running")

    # --- clear ---
    clear_parser = subparsers.add_parser("clear", help="Clear jobs from the queue")
    clear_parser.add_argument("--status", "-s", nargs="+", default=["done", "failed"],
                              help="Statuses to clear (default: done failed)")
    clear_parser.add_argument("--all", action="store_true", help="Clear everything")

    # --- status ---
    subparsers.add_parser("status", help="Show queue status summary")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Process all queued render jobs")
    run_parser.add_argument("--engine", "-e", default="CYCLES", choices=["CYCLES", "BLENDER_EEVEE"])
    run_parser.add_argument("--fast", action="store_true", help="Fast mode (16 Cycles samples)")

    # --- pause / resume / clean ---
    subparsers.add_parser("pause", help="Pause after current job finishes")
    subparsers.add_parser("resume", help="Resume paused queue processing")
    subparsers.add_parser("clean", help="Reset stale running jobs + detect already-rendered")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "add": cmd_add,
        "list": cmd_list,
        "remove": cmd_remove,
        "clear": cmd_clear,
        "status": cmd_status,
        "run": cmd_run,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "clean": cmd_clean,
    }

    handler = commands.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
