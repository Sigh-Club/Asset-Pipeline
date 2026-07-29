#!/usr/bin/env python3
"""
queue_dashboard.py — Web dashboard for the IoA render queue.

Provides a simple browser-based UI to:
  - View the render queue and job statuses
  - Start renders immediately ("Render Now")
  - Set a scheduled render time (default 00:00)
  - View live progress and recent log output
  - Remove / clear jobs

Usage:
    python3 tools/queue_dashboard.py
    # Opens http://localhost:8083 in your browser

    # Custom port
    python3 tools/queue_dashboard.py --port 9090

    # Bind to all interfaces (access from other devices)
    python3 tools/queue_dashboard.py --host 0.0.0.0
"""

import os
import sys
import json
import time
import socket
import signal
import subprocess
import threading
import webbrowser
import argparse
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
QUEUE_DIR = os.path.join(PROJECT_ROOT, "output")
QUEUE_PATH = os.path.join(QUEUE_DIR, "render_queue.json")
LOG_DIR = os.path.join(QUEUE_DIR, "render_logs")
SCHEDULE_FILE = os.path.join(QUEUE_DIR, "schedule_time.txt")
SCHEDULE_LOG = os.path.join(QUEUE_DIR, "nightly_render.log")
SCHEDULE_SCRIPT = os.path.join(SCRIPT_DIR, "schedule_render.sh")

# Global state
render_process = None
render_lock = threading.Lock()
render_start_time = None
current_job_name = None
current_job_num = 0
total_jobs = 0


# =============================================================================
# Queue helpers
# =============================================================================

def load_queue():
    if os.path.exists(QUEUE_PATH):
        try:
            with open(QUEUE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_queue(queue):
    os.makedirs(QUEUE_DIR, exist_ok=True)
    with open(QUEUE_PATH, "w") as f:
        json.dump(queue, f, indent=2)


def get_schedule_time():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE) as f:
                return f.read().strip()
        except IOError:
            pass
    return "00:00"


def set_schedule_time(time_str):
    os.makedirs(QUEUE_DIR, exist_ok=True)
    with open(SCHEDULE_FILE, "w") as f:
        f.write(time_str.strip())


def get_cron_status():
    """Check if the cron job is installed."""
    try:
        script_path = os.path.abspath(SCHEDULE_SCRIPT)
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5
        )
        return script_path in result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def get_render_progress():
    """Get current render process info from the queue and process list."""
    info = {"running": False, "current": None, "recent_log": ""}

    # Check 1: Internal dashboard process
    if render_process and render_process.poll() is None:
        info["running"] = True

    # Check 2: Queue file — any job with status "running"?
    queue = load_queue()
    for j in queue:
        if j.get("status") == "running":
            info["running"] = True
            info["current"] = j.get("unit_name")
            break

    # Check 3: Process list — is another render_queue running?
    if not info["running"]:
        try:
            result = subprocess.run(
                ["pgrep", "-af", "render_queue run"],
                capture_output=True, text=True, timeout=3
            )
            if "render_queue run" in result.stdout and "grep" not in result.stdout:
                info["running"] = True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    # Read recent log output
    log_paths = []
    if os.path.exists(LOG_DIR):
        log_paths = sorted(
            Path(LOG_DIR).iterdir(),
            key=lambda p: p.stat().st_mtime, reverse=True
        )[:3]

    log_lines = []
    for lp in log_paths:
        try:
            with open(lp) as f:
                lines = f.readlines()
                relevant = [l.strip() for l in lines if l.strip() and not l.startswith("STDERR")]
                log_lines.extend(relevant[-15:])
        except (IOError, OSError):
            pass

    info["recent_log"] = "\n".join(log_lines[-30:])
    return info


# =============================================================================
# Background render runner
# =============================================================================

def run_render_background(fast=True):
    """Launch render processing in a background thread."""
    global render_process, render_start_time

    def _run():
        global render_process, render_start_time
        cmd = [
            sys.executable, "-m", "tools.render_queue", "run"
        ]
        if fast:
            cmd.append("--fast")
        with render_lock:
            render_start_time = time.time()
            render_process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
        render_process.wait()
        with render_lock:
            render_process = None

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def stop_render():
    """Stop the current render process gracefully."""
    global render_process
    with render_lock:
        if render_process and render_process.poll() is None:
            render_process.terminate()
            # Give it a moment, then kill
            try:
                render_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                render_process.kill()
            render_process = None


# =============================================================================
# API handler
# =============================================================================

class QueueHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the queue dashboard API + static files."""

    # Cache the HTML page
    html_page = None

    def log_message(self, format, *args):
        """Quiet logging — only log errors."""
        if "200" not in args[0]:
            super().log_message(format, *args)

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        if QueueHandler.html_page is None:
            QueueHandler.html_page = self._build_html()
        body = QueueHandler.html_page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _build_html(self):
        """Build the HTML page — embedded for zero dependencies."""
        return HTML_PAGE

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if not path:
            path = "/"

        if path == "/" or path == "/index.html":
            self._send_html()

        elif path == "/api/status":
            queue = load_queue()
            progress = get_render_progress()

            counts = {"queued": 0, "running": 0, "done": 0, "failed": 0}
            for j in queue:
                s = j.get("status", "unknown")
                counts[s] = counts.get(s, 0) + 1
                if s == "running":
                    pass  # handled by progress

            schedule = get_schedule_time()
            cron_active = get_cron_status()

            running_count = sum(1 for j in queue if j.get("status") == "running")
            if progress.get("running"):
                running_count = max(running_count, 1)

            self._send_json({
                "counts": counts,
                "total": len(queue),
                "running": running_count or (1 if progress.get("running") else 0),
                "schedule_time": schedule,
                "cron_active": cron_active,
                "render_running": progress.get("running", False),
                "recent_log": progress.get("recent_log", ""),
                "paused": os.path.exists(os.path.join(QUEUE_DIR, ".render_pause")),
            })

        elif path == "/api/progress":
            """Return real-time render progress from the sidecar file."""
            prog_path = os.path.join(QUEUE_DIR, "render_progress.json")
            if os.path.exists(prog_path):
                try:
                    with open(prog_path) as f:
                        prog = json.load(f)
                    self._send_json(prog)
                except (json.JSONDecodeError, IOError):
                    self._send_json({
                        "phase": "idle", "unit_name": "", "job_id": 0,
                        "steps": {"done": 0, "total": 1}, "pct": 0,
                        "current": {}, "log_tail": ""
                    })
                return

            self._send_json({
                "phase": "idle", "unit_name": "", "job_id": 0,
                "steps": {"done": 0, "total": 1}, "pct": 0,
                "current": {}, "log_tail": ""
            })

        elif path == "/api/queue":
            queue = load_queue()
            # Sort: queued first (by priority/ID), then running, then done/failed
            priority = {"queued": 0, "running": 1, "done": 2, "failed": 3}
            queue.sort(key=lambda j: (
                priority.get(j.get("status", "unknown"), 9),
                -j.get("priority", 0),
                j.get("id", 0)
            ))
            self._send_json({"jobs": queue})

        elif path == "/api/render_log":
            progress = get_render_progress()
            self._send_json({
                "running": progress.get("running", False),
                "recent_log": progress.get("recent_log", ""),
                "schedule_log_exists": os.path.exists(SCHEDULE_LOG),
            })

        elif path == "/api/schedule":
            self._send_json({
                "time": get_schedule_time(),
                "script_path": os.path.abspath(SCHEDULE_SCRIPT),
                "cron_active": get_cron_status(),
            })

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode() if content_len else "{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}

        if path == "/api/render/start":
            # Don't start if already running
            if render_process and render_process.poll() is None:
                self._send_json({"ok": True, "message": "Already running"})
                return

            fast = data.get("fast", True)
            run_render_background(fast=fast)
            self._send_json({"ok": True, "message": "Render started"})

        elif path == "/api/render/stop":
            stop_render()
            self._send_json({"ok": True, "message": "Render stopped"})

        elif path == "/api/render/pause":
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "tools.render_queue", "pause"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
            )
            self._send_json({"ok": True, "message": "Pause signal sent — will stop after current job"})

        elif path == "/api/render/resume":
            import subprocess
            subprocess.run(
                [sys.executable, "-m", "tools.render_queue", "resume"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300
            )
            self._send_json({"ok": True, "message": "Resumed"})

        elif path == "/api/queue/clean":
            import subprocess
            result = subprocess.run(
                [sys.executable, "-m", "tools.render_queue", "clean"],
                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10
            )
            self._send_json({"ok": True, "message": result.stdout.strip() or "Cleaned"})

        elif path == "/api/job/remove":
            job_id = data.get("id")
            queue = load_queue()
            queue = [j for j in queue if j.get("id") != job_id]
            save_queue(queue)
            self._send_json({"ok": True})

        elif path == "/api/queue/add":
            unit = data.get("unit", "").strip()
            if not unit:
                self._send_json({"ok": False, "message": "Unit name required"}, 400)
                return
            # Call render_queue add
            cmd = [
                sys.executable, "-m", "tools.render_queue", "add",
                "--unit", unit
            ]
            body_type = data.get("body_type", "")
            if body_type:
                cmd.extend(["--body-type", body_type])
            if data.get("force"):
                cmd.append("--force")
            result = subprocess.run(cmd, cwd=PROJECT_ROOT,
                                    capture_output=True, text=True, timeout=10)
            self._send_json({
                "ok": result.returncode == 0,
                "message": result.stdout.strip() or result.stderr.strip()
            })

        elif path == "/api/queue/clear":
            statuses = data.get("status", ["done", "failed"])
            queue = load_queue()
            queue = [j for j in queue if j.get("status") not in statuses]
            save_queue(queue)
            self._send_json({"ok": True, "message": f"Cleared {statuses} jobs"})

        elif path == "/api/schedule/set":
            time_str = data.get("time", "00:00")
            if not time_str or ":" not in time_str:
                self._send_json({"ok": False, "message": "Invalid time format"}, 400)
                return
            set_schedule_time(time_str)
            self._send_json({"ok": True, "message": f"Schedule set to {time_str}"})

        elif path == "/api/schedule/install-cron":
            time_str = data.get("time", get_schedule_time())
            result = install_cron(time_str)
            if result is True:
                self._send_json({"ok": True, "message": "Cron installed for " + time_str})
            else:
                self._send_json({"ok": False, "message": str(result)})

        elif path == "/api/schedule/remove-cron":
            success = remove_cron()
            self._send_json({
                "ok": success,
                "message": "Cron removed" if success else "Failed to remove cron"
            })

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


# =============================================================================
# Cron management
# =============================================================================

def install_cron(time_str="00:00"):
    """Install or update the cron job."""
    try:
        hour, minute = time_str.split(":")
        hour = int(hour)
        minute = int(minute)
    except (ValueError, TypeError):
        hour, minute = 0, 0

    script_path = os.path.abspath(SCHEDULE_SCRIPT)
    log_path = os.path.abspath(SCHEDULE_LOG)
    cron_line = f"{minute} {hour} * * * {script_path} --fast >> {log_path} 2>&1"
    marker = "# IoA Render Queue"

    # Check if crontab command exists
    import shutil
    if not shutil.which("crontab"):
        return "crontab command not found — install cronie or bcron"

    # Get existing crontab (handles empty/non-existent)
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        existing = result.stdout
        if result.returncode != 0:
            existing = ""
    except FileNotFoundError:
        existing = ""
    except subprocess.SubprocessError:
        existing = ""

    # Remove any existing IoA cron entries
    lines = existing.split("\n")
    lines = [l for l in lines if marker not in l and script_path not in l]
    lines = [l for l in lines if l.strip()]

    # Add new entry
    lines.insert(0, f"{marker} — nightly render queue (set via dashboard)")
    lines.append(cron_line)
    lines.append("")

    new_cron = "\n".join(lines)

    # Install via crontab stdin (works without temp files)
    try:
        proc = subprocess.Popen(
            ["crontab", "-"],
            stdin=subprocess.PIPE,
            text=True,
        )
        proc.communicate(input=new_cron)
        if proc.returncode != 0:
            return f"crontab returned exit code {proc.returncode}"
        return True
    except FileNotFoundError:
        return "crontab command not found on this system"
    except subprocess.SubprocessError as e:
        return f"cron install failed: {e}"


def remove_cron():
    """Remove the IoA cron job."""
    script_path = os.path.abspath(SCHEDULE_SCRIPT)
    marker = "# IoA Render Queue"
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.split("\n")
        if result.returncode != 0:
            lines = []
        lines = [l for l in lines if marker not in l and script_path not in l]
        new_cron = "\n".join(l for l in lines if l.strip()) + "\n"
        proc = subprocess.Popen(
            ["crontab", "-"],
            stdin=subprocess.PIPE, text=True
        )
        proc.communicate(input=new_cron)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


# =============================================================================
# HTML PAGE
# =============================================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IoA Render Queue</title>
<style>
:root {
    --bg: #0d1117;
    --surface: #161b22;
    --border: #30363d;
    --text: #c9d1d9;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --green: #3fb950;
    --red: #f85149;
    --yellow: #d29922;
    --orange: #d4760a;
    --success: #238636;
    --danger: #da3633;
    font-family: 'Segoe UI', -apple-system, sans-serif;
    font-size: 14px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); padding: 20px; min-height: 100vh; }
.container { max-width: 1200px; margin: 0 auto; }

/* Header */
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
.header h1 { font-weight: 600; font-size: 22px; color: var(--accent); }
.header .subtitle { color: var(--text-dim); font-size: 12px; }
.header-badge { padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: 500; }
.badge-idle { background: var(--surface); color: var(--text-dim); border: 1px solid var(--border); }
.badge-rendering { background: #1a3a2a; color: var(--green); border: 1px solid var(--green); }

/* Stat cards */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; text-align: center; }
.stat-card .value { font-size: 28px; font-weight: 700; }
.stat-card .label { font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }
.stat-card .value.queued { color: var(--accent); }
.stat-card .value.rendering { color: var(--green); }
.stat-card .value.done { color: var(--text); }
.stat-card .value.failed { color: var(--red); }

/* Controls */
.controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; align-items: center; }
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 18px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.15s; }
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { background: var(--green); color: #000; border-color: var(--green); font-weight: 600; }
.btn-primary:hover { filter: brightness(1.15); color: #000; }
.btn-danger { background: var(--danger); color: #fff; border-color: var(--danger); }
.btn-danger:hover { filter: brightness(1.15); color: #fff; }
.btn-small { padding: 4px 10px; font-size: 12px; }

/* Schedule bar */
.schedule-bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 20px; padding: 12px 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
.schedule-bar label { font-size: 13px; color: var(--text-dim); }
.schedule-bar input[type="time"] { background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 4px; font-size: 13px; font-family: monospace; }
.schedule-bar input[type="time"]:focus { outline: none; border-color: var(--accent); }
.schedule-status { font-size: 12px; color: var(--text-dim); }
.schedule-status .active { color: var(--green); }

/* Queue table */
table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
th { text-align: left; padding: 10px 12px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-dim); border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: middle; }
tr:hover td { background: rgba(88,166,255,0.04); }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
.status-queued { background: rgba(88,166,255,0.15); color: var(--accent); }
.status-running { background: rgba(63,185,80,0.15); color: var(--green); }
.status-done { background: rgba(88,166,255,0.08); color: var(--text-dim); }
.status-failed { background: rgba(248,81,73,0.15); color: var(--red); }
.job-id { color: var(--text-dim); font-family: monospace; font-size: 12px; }
.job-name { font-weight: 500; }
.job-action { cursor: pointer; color: var(--text-dim); opacity: 0; transition: opacity 0.15s; }
tr:hover .job-action { opacity: 1; }
.job-action:hover { color: var(--red); }

/* Log section */
.log-section { margin-top: 12px; }
.log-section summary { cursor: pointer; color: var(--text-dim); font-size: 13px; padding: 8px 0; user-select: none; }
.log-section summary:hover { color: var(--text); }
.log-output { background: #000; border: 1px solid var(--border); border-radius: 6px; padding: 12px; font-family: 'Cascadia Code', 'Fira Code', monospace; font-size: 12px; line-height: 1.5; color: var(--text-dim); white-space: pre-wrap; max-height: 240px; overflow-y: auto; }

/* Add unit form */
.add-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 12px 0; }
.add-form input[type="text"] { background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 4px; font-size: 13px; flex: 1; min-width: 200px; }
.add-form input[type="text"]:focus { outline: none; border-color: var(--accent); }
.add-form select { background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 8px 10px; border-radius: 4px; font-size: 13px; }

/* Toast */
.toast { position: fixed; bottom: 24px; right: 24px; padding: 12px 20px; border-radius: 6px; color: #fff; font-size: 13px; z-index: 1000; opacity: 0; transform: translateY(10px); transition: all 0.3s; pointer-events: none; }
.toast.show { opacity: 1; transform: translateY(0); }
.toast-success { background: var(--success); }
.toast-error { background: var(--danger); }
.toast-info { background: #1f6feb; }

/* Responsive */
@media (max-width: 700px) {
    body { padding: 12px; }
    .stats { grid-template-columns: repeat(2, 1fr); }
    .controls { flex-direction: column; align-items: stretch; }
    .controls .btn { justify-content: center; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>IoA Render Queue</h1>
            <div class="subtitle">asset-pipeline &mdash; <span id="version">v0.4.0</span></div>
        </div>
        <div id="headerBadge" class="header-badge badge-idle">● Idle</div>
    </div>

    <!-- Stats -->
    <div class="stats" id="stats">
        <div class="stat-card"><div class="value queued" id="statQueued">0</div><div class="label">Queued</div></div>
        <div class="stat-card"><div class="value rendering" id="statRendering">0</div><div class="label">Rendering</div></div>
        <div class="stat-card"><div class="value done" id="statDone">0</div><div class="label">Completed</div></div>
        <div class="stat-card"><div class="value failed" id="statFailed">0</div><div class="label">Failed</div></div>
    </div>

    <!-- Current render progress -->
    <div id="progressSection" style="display:none; margin-bottom:20px; background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <div>
                <span id="progressUnit" style="font-weight:600;font-size:14px;"></span>
                <span id="progressPhase" style="margin-left:8px; font-size:12px; color:var(--accent);"></span>
            </div>
            <span id="progressPct" style="font-size:16px; font-weight:700; color:var(--accent);"></span>
        </div>
        <div style="width:100%; height:20px; background:var(--bg); border-radius:10px; overflow:hidden; margin-bottom:6px;">
            <div id="progressBar" style="height:100%; width:0%; background: linear-gradient(90deg, #238636, #3fb950); border-radius:10px; transition:width 0.5s ease;"></div>
        </div>
        <div id="progressDetail" style="font-size:12px; color:var(--text-dim); display:flex; justify-content:space-between;">
            <span id="progressFrames"></span>
            <span id="progressAnimDir"></span>
        </div>
        <div id="progressLogBar" style="margin-top:8px; display:none;">
            <pre id="progressLogText" style="margin:0; padding:6px 8px; background:#000; border-radius:4px; font-size:11px; color:var(--text-dim); max-height:60px; overflow-y:auto; white-space:pre-wrap;"></pre>
        </div>
    </div>

    <!-- Controls -->
    <div class="controls">
        <button class="btn btn-primary" id="btnRenderNow" onclick="startRender()">&#9654; Render Now</button>
        <button class="btn" id="btnPause" onclick="pauseRender()" disabled>&#9208; Pause</button>
        <button class="btn" id="btnResume" onclick="resumeRender()" style="display:none;">&#9654; Resume</button>
        <button class="btn" id="btnStop" onclick="stopRender()" disabled>&#9632; Stop</button>
        <button class="btn btn-danger" id="btnClear" onclick="clearDone()">&#10005; Clear Done</button>
        <span style="flex:1; min-width:20px;"></span>
        <button class="btn btn-small" onclick="refreshAll()">&#8635; Refresh</button>
    </div>

    <!-- Schedule -->
    <div class="schedule-bar">
        <label for="schedTime">&#9200; Nightly schedule:</label>
        <input type="time" id="schedTime" value="00:00" onchange="saveSchedule()">
        <button class="btn btn-small" id="btnInstallCron" onclick="installCron()">Install Cron</button>
        <button class="btn btn-small" id="btnRemoveCron" onclick="removeCron()" style="display:none;">Remove Cron</button>
        <span class="schedule-status" id="cronStatus"></span>
    </div>

    <!-- Add unit -->
    <details>
        <summary style="cursor:pointer;color:var(--text-dim);font-size:13px;padding:8px 0;">+ Add unit to queue</summary>
        <div class="add-form">
            <input type="text" id="newUnitName" placeholder="Unit name (e.g. iron_directorate_shade_swarm)" list="unitSuggestions">
            <datalist id="unitSuggestions"></datalist>
            <select id="newBodyType">
                <option value="humanoid">Humanoid</option>
                <option value="vehicle">Vehicle</option>
                <option value="creature">Creature</option>
                <option value="insectoid">Insectoid</option>
            </select>
            <button class="btn btn-primary btn-small" onclick="addUnit()">Add to Queue</button>
        </div>
    </details>

    <!-- Queue table -->
    <table>
        <thead>
            <tr><th>ID</th><th>Status</th><th>Unit</th><th>Type</th><th>Created</th><th style="width:30px;"></th></tr>
        </thead>
        <tbody id="queueBody">
            <tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:40px;">Loading...</td></tr>
        </tbody>
    </table>

    <!-- Live log -->
    <details class="log-section" id="logSection">
        <summary>&#9776; Render Log</summary>
        <div class="log-output" id="logOutput">Waiting for render output...</div>
    </details>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
// === Auto-refresh ===
let refreshTimer = null;
const REFRESH_INTERVAL_FAST = 3000;   // 3s when rendering
const REFRESH_INTERVAL_SLOW = 6000;   // 6s when idle

function startRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(tick, REFRESH_INTERVAL_FAST);
}

async function tick() {
    try {
        await Promise.all([fetchStatus(), fetchQueue(), fetchProgress()]);
        if (document.getElementById('logSection').open) await fetchLog();
    } catch (e) {
        console.warn('Refresh tick failed, retrying...', e);
    }
}

startRefresh();

// === Status ===
let lastDoneCount = null;

async function fetchStatus() {
    try {
        const r = await fetch('/api/status');
        const data = await r.json();
        document.getElementById('statQueued').textContent = data.counts.queued || 0;
        document.getElementById('statRendering').textContent = data.running || 0;
        document.getElementById('statDone').textContent = data.counts.done || 0;
        document.getElementById('statFailed').textContent = data.counts.failed || 0;

        // Update page title with progress
        if (data.counts.done > 0 || data.counts.failed > 0) {
            const totalDone = data.counts.done + data.counts.failed;
            document.title = `[${totalDone}/${data.total}] IoA Render Queue`;
        }

        // Flash badge if new job completed
        if (lastDoneCount !== null && data.counts.done > lastDoneCount) {
            const badge = document.getElementById('headerBadge');
            badge.style.transition = 'none';
            badge.style.color = 'var(--green)';
            setTimeout(() => { badge.style.transition = 'color 2s'; badge.style.color = ''; }, 500);
        }
        lastDoneCount = data.counts.done;

        const badge = document.getElementById('headerBadge');
        if (data.render_running) {
            badge.textContent = '● Rendering';
            badge.className = 'header-badge badge-rendering';
        } else {
            badge.textContent = '● Idle';
            badge.className = 'header-badge badge-idle';
        }

        document.getElementById('btnRenderNow').disabled = data.render_running;
        document.getElementById('btnStop').disabled = !data.render_running;
        document.getElementById('btnPause').disabled = !data.render_running || data.paused;
        document.getElementById('btnResume').style.display = data.paused ? 'inline-flex' : 'none';
        document.getElementById('btnRenderNow').style.display = data.paused ? 'none' : 'inline-flex';

        // Show pause indicator
        const pauseMsg = document.getElementById('pauseIndicator');
        if (data.paused) {
            if (!pauseMsg) {
                const el = document.createElement('div');
                el.id = 'pauseIndicator';
                el.style.cssText = 'padding:12px 16px;background:#1a2a3a;border:1px solid var(--yellow);border-radius:8px;margin-bottom:16px;text-align:center;font-size:14px;color:var(--yellow);';
                el.innerHTML = '&#9208; Queue <b>paused</b> &mdash; will stop after current job finishes. <a href="#" onclick="resumeRender();return false;" style="color:var(--green);font-weight:600;">Resume</a>';
                document.getElementById('stats').after(el);
            }
        } else if (pauseMsg) {
            pauseMsg.remove();
        }
        document.getElementById('schedTime').value = data.schedule_time || '00:00';

        const cronStatus = document.getElementById('cronStatus');
        const btnInstall = document.getElementById('btnInstallCron');
        const btnRemove = document.getElementById('btnRemoveCron');
        if (data.cron_active === true) {
            cronStatus.innerHTML = '<span class="active">&#10003; Cron active</span>';
            btnInstall.style.display = 'none';
            btnRemove.style.display = 'inline-flex';
        } else if (data.cron_active === false) {
            cronStatus.textContent = 'No cron job installed';
            btnInstall.style.display = 'inline-flex';
            btnRemove.style.display = 'none';
        } else {
            cronStatus.textContent = '(cron not available)';
            btnInstall.style.display = 'none';
            btnRemove.style.display = 'none';
        }
    } catch (e) { /* silent */ }
}

// === Queue list ===
async function fetchQueue() {
    try {
        const r = await fetch('/api/queue');
        const data = await r.json();
        const tbody = document.getElementById('queueBody');
        if (!data.jobs || data.jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:40px;">Queue is empty. Add units above to get started.</td></tr>';
            return;
        }
        tbody.innerHTML = data.jobs.map(j => {
            const statusClass = 'status-' + (j.status || 'unknown');
            const icon = j.status === 'queued' ? '&#9203;' : j.status === 'running' ? '&#9654;' : j.status === 'done' ? '&#10003;' : j.status === 'failed' ? '&#10007;' : '&#10068;';
            const type = j.body_type || 'humanoid';
            const created = j.created ? j.created.split(' ')[0] : '-';
            const removeBtn = j.status === 'done' || j.status === 'failed' ? `<span class="job-action" onclick="removeJob(${j.id})" title="Remove">&#10005;</span>` : '';
            return `<tr>
                <td class="job-id">#${j.id}</td>
                <td><span class="status-badge ${statusClass}">${icon} ${j.status}</span></td>
                <td class="job-name">${j.unit_name}</td>
                <td style="color:var(--text-dim);font-size:12px;">${type}</td>
                <td style="color:var(--text-dim);font-size:12px;">${created}</td>
                <td>${removeBtn}</td>
            </tr>`;
        }).join('');
    } catch (e) { /* silent */ }
}

// === Log ===
async function fetchLog() {
    try {
        const r = await fetch('/api/render_log');
        const data = await r.json();
        const el = document.getElementById('logOutput');
        if (data.recent_log) {
            el.textContent = data.recent_log;
        } else {
            el.textContent = data.running ? 'Render running, waiting for output...' : 'No recent render activity.';
        }
    } catch (e) { /* silent */ }
}

// === Progress ===
async function fetchProgress() {
    try {
        const r = await fetch('/api/progress');
        const data = await r.json();

        const section = document.getElementById('progressSection');
        const bar = document.getElementById('progressBar');
        const pctEl = document.getElementById('progressPct');
        const unitEl = document.getElementById('progressUnit');
        const phaseEl = document.getElementById('progressPhase');
        const framesEl = document.getElementById('progressFrames');
        const animDirEl = document.getElementById('progressAnimDir');

        if (!data.phase || data.phase === 'idle' || data.phase === 'done') {
            section.style.display = 'none';
            return;
        }

        // Show progress section
        section.style.display = 'block';

        const pct = data.pct || 0;
        const done = data.steps?.done || 0;
        const total = data.steps?.total || 208;

        bar.style.width = pct + '%';
        pctEl.textContent = pct + '%';
        unitEl.textContent = data.unit_name || 'Unknown';
        phaseEl.textContent = data.phase === 'generating' ? '(Generating .blend...)' :
            data.phase === 'rendering' ? '(Rendering frames...)' :
            data.phase === 'critic' ? '(Running quality check...)' :
            data.phase === 'failed' ? '(Failed)' : '';

        framesEl.textContent = `Frames: ${done} / ${total}`;

        const anim = data.current?.animation || '';
        const dir = data.current?.direction || '';
        if (anim && dir) {
            animDirEl.textContent = `${anim} / ${dir}`;
        } else {
            animDirEl.textContent = '';
        }

        // Show log tail if rendering
        const logTailEl = document.getElementById('progressLogText');
        const logBar = document.getElementById('progressLogBar');
        if (data.log_tail) {
            logBar.style.display = 'block';
            logTailEl.textContent = data.log_tail;
        } else {
            logBar.style.display = 'none';
        }
    } catch (e) { /* silent */ }
}

// === Actions ===
async function startRender() {
    try {
        await fetch('/api/render/start', { method: 'POST', body: '{"fast":true}', headers: {'Content-Type':'application/json'} });
        showToast('Render started', 'info');
        fetchStatus();
    } catch (e) { showToast('Failed to start render', 'error'); }
}

async function stopRender() {
    try {
        await fetch('/api/render/stop', { method: 'POST', headers: {'Content-Type':'application/json'} });
        showToast('Render stopped', 'info');
        fetchStatus();
    } catch (e) { showToast('Failed to stop render', 'error'); }
}

async function pauseRender() {
    try {
        await fetch('/api/render/pause', { method: 'POST', headers: {'Content-Type':'application/json'} });
        showToast('Pause signal sent — will stop after current job', 'info');
        fetchStatus();
    } catch (e) { showToast('Failed to pause', 'error'); }
}

async function resumeRender() {
    try {
        await fetch('/api/render/resume', { method: 'POST', headers: {'Content-Type':'application/json'} });
        showToast('Resumed', 'success');
        fetchStatus(); fetchQueue();
    } catch (e) { showToast('Failed to resume', 'error'); }
}

async function clearDone() {
    try {
        await fetch('/api/queue/clear', { method: 'POST', body: '{"status":["done","failed"]}', headers: {'Content-Type':'application/json'} });
        showToast('Cleared completed/failed jobs', 'success');
        fetchQueue(); fetchStatus();
    } catch (e) { showToast('Failed to clear', 'error'); }
}

async function removeJob(id) {
    try {
        await fetch('/api/job/remove', { method: 'POST', body: JSON.stringify({id}), headers: {'Content-Type':'application/json'} });
        fetchQueue(); fetchStatus();
    } catch (e) { /* silent */ }
}

async function addUnit() {
    const name = document.getElementById('newUnitName').value.trim();
    if (!name) { showToast('Enter a unit name', 'error'); return; }
    const body_type = document.getElementById('newBodyType').value;
    try {
        const r = await fetch('/api/queue/add', { method: 'POST', body: JSON.stringify({unit: name, body_type}), headers: {'Content-Type':'application/json'} });
        const data = await r.json();
        showToast(data.message || 'Added', data.ok ? 'success' : 'error');
        if (data.ok) {
            document.getElementById('newUnitName').value = '';
            fetchQueue(); fetchStatus();
        }
    } catch (e) { showToast('Failed to add', 'error'); }
}

async function saveSchedule() {
    const time = document.getElementById('schedTime').value;
    try {
        await fetch('/api/schedule/set', { method: 'POST', body: JSON.stringify({time}), headers: {'Content-Type':'application/json'} });
        showToast('Schedule set to ' + time, 'success');
    } catch (e) { /* silent */ }
}

async function installCron() {
    const time = document.getElementById('schedTime').value;
    try {
        const r = await fetch('/api/schedule/install-cron', { method: 'POST', body: JSON.stringify({time}), headers: {'Content-Type':'application/json'} });
        const data = await r.json();
        showToast(data.message || 'Cron installed', data.ok ? 'success' : 'error');
        fetchStatus();
    } catch (e) { showToast('Failed to install cron', 'error'); }
}

async function removeCron() {
    try {
        const r = await fetch('/api/schedule/remove-cron', { method: 'POST', headers: {'Content-Type':'application/json'} });
        const data = await r.json();
        showToast(data.message || 'Cron removed', data.ok ? 'success' : 'error');
        fetchStatus();
    } catch (e) { showToast('Failed to remove cron', 'error'); }
}

function refreshAll() {
    fetchStatus(); fetchQueue(); fetchLog();
}

// === Toast ===
function showToast(message, type = 'info') {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.className = 'toast toast-' + type + ' show';
    setTimeout(() => el.classList.remove('show'), 3000);
}

// === Init ===
document.getElementById('logSection').addEventListener('toggle', function() {
    if (this.open) fetchLog();
});

// Refresh immediately when user switches back to this tab
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        tick();
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'r' && !e.ctrlKey && !e.metaKey && !e.target.closest('input,select')) {
        e.preventDefault(); refreshAll();
    }
    if (e.key === 'Enter' && e.target.id === 'newUnitName') addUnit();
});

startRefresh();
fetchStatus();
fetchQueue();
</script>
</body>
</html>"""


# =============================================================================
# SERVER
# =============================================================================

def find_free_port(start=8083, max_attempts=20):
    """Find a free port starting from start."""
    for port in range(start, start + max_attempts):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.bind(('', port))
            sock.close()
            return port
        except (OSError, socket.error):
            continue
    return start  # fallback, will fail gracefully


def run_server(host='127.0.0.1', port=None):
    if port is None:
        port = find_free_port()

    server = HTTPServer((host, port), QueueHandler)
    url = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}/"

    print(f"  ┌──────────────────────────────────────────────┐")
    print(f"  │  IoA Render Queue Dashboard                  │")
    print(f"  │                                              │")
    print(f"  │  Open: {url:<35} │")
    print(f"  │                                              │")
    print(f"  │  Press Ctrl+C to stop                        │")
    print(f"  └──────────────────────────────────────────────┘")

    # Auto-open browser (skip if binding to 0.0.0.0)
    if host in ('127.0.0.1', 'localhost'):
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")
        server.shutdown()


# =============================================================================
# ENTRY
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="IoA Render Queue Dashboard — web UI for managing render jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start dashboard (opens browser)
  python3 tools/queue_dashboard.py

  # Custom port
  python3 tools/queue_dashboard.py --port 9090

  # Access from other devices on the network
  python3 tools/queue_dashboard.py --host 0.0.0.0
        """
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8083, help="Port (default: 8083)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
