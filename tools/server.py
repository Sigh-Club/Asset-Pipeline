#!/usr/bin/env python3
"""
server.py — Unified IoA web dashboard (gallery + render queue).

Combines the asset gallery browser and render queue dashboard into
a single web interface on one port.

Usage:
    python3 tools/server.py                  # Port 8080 (default)
    python3 tools/server.py --port 9090
    python3 tools/server.py --no-browser

    # Via pipeline CLI:
    python3 tools/pipeline_cli.py dashboard
"""

import os
import sys
import json
import io
import socket
import mimetypes
import argparse
import webbrowser
import threading
import signal
import subprocess
import time
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
STATIC_DIR = os.path.join(SCRIPT_DIR, "static")

# =============================================================================
# IMPORT GALLERY FUNCTIONS
# =============================================================================

sys.path.insert(0, SCRIPT_DIR)
from gallery_server import GalleryHandler as _GalleryHandler
from batch_process import load_palette, process_frame

# =============================================================================
# IMPORT QUEUE FUNCTIONS
# =============================================================================

try:
    from tools.render_queue import (
        RenderQueue, load_queue, save_queue,
        QUEUE_PATH as _Q_PATH,
        JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_DONE, JOB_STATUS_FAILED,
    )
    QUEUE_AVAILABLE = True
    QUEUE_PATH = _Q_PATH
except ImportError:
    QUEUE_AVAILABLE = False
    QUEUE_PATH = os.path.join(PROJECT_ROOT, "output", "render_queue.json")

# =============================================================================
# PATHS
# =============================================================================

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
SCAN_DIR = OUTPUT_DIR  # same as gallery server
RELEASES_DIR = os.path.join(OUTPUT_DIR, "releases")
LOG_DIR = os.path.join(OUTPUT_DIR, "render_logs")
QUEUE_DIR = OUTPUT_DIR

# =============================================================================
# COMBINED HTML (landing page)
# =============================================================================

LANDING_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IoA Pipeline — Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #111; color: #ddd; min-height: 100vh;
  }
  header {
    background: #1a1a1a; border-bottom: 2px solid #d4a017; padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
  }
  header h1 { font-size: 20px; color: #d4a017; }
  header h1 span { color: #888; font-weight: normal; }
  nav { display: flex; gap: 4px; background: #1a1a1a; padding: 8px 24px; border-bottom: 1px solid #333; }
  nav a {
    color: #aaa; text-decoration: none; padding: 8px 20px; border-radius: 4px 4px 0 0;
    font-size: 14px; transition: all 0.2s; cursor: pointer;
    border: 1px solid transparent; border-bottom: none;
  }
  nav a:hover { background: #252525; color: #fff; }
  nav a.active { background: #222; color: #d4a017; border-color: #444; font-weight: bold; }
  .tab { display: none; }
  .tab.active { display: block; }
  iframe { width: 100%; border: none; height: calc(100vh - 120px); }
</style>
</head>
<body>
<header>
  <h1>IoA Pipeline <span>Dashboard</span></h1>
  <div style="font-size:12px;color:#666;">
    v0.5.0
  </div>
</header>
<nav>
  <a href="#" class="active" onclick="switchTab('gallery', this)">Asset Gallery</a>
  <a href="#" onclick="switchTab('queue', this)">Render Queue</a>
  <a href="#" onclick="switchTab('logs', this)">Recent Logs</a>
</nav>
<div id="tab-gallery" class="tab active"><iframe src="/gallery/page"></iframe></div>
<div id="tab-queue" class="tab"><iframe src="/queue/page"></iframe></div>
<div id="tab-logs" class="tab"><div id="log-viewer" style="padding:24px;font-family:monospace;font-size:12px;color:#888;"></div></div>

<script>
function switchTab(name, btn) {
  document.querySelectorAll('nav a').forEach(function(a) { a.classList.remove('active'); });
  btn.classList.add('active');
  document.querySelectorAll('.tab').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('tab-' + name).classList.add('active');
}
// Load logs when switching to logs tab
document.querySelector('a[onclick*=\"logs\"]').addEventListener('click', function() {
  setTimeout(function() {
    fetch('/api/logs').then(function(r) { return r.json(); }).then(function(data) {
      document.getElementById('log-viewer').textContent = (data.logs || ['No logs']).join('\\n');
    });
  }, 200);
});
</script>
</body>
</html>"""


# =============================================================================
# UNIFIED HTTP HANDLER
# =============================================================================

class UnifiedHandler(BaseHTTPRequestHandler):
    """Single HTTP handler serving gallery + queue + logs."""

    scan_dir = SCAN_DIR

    def log_message(self, format, *args):
        path = urlparse(self.path).path
        if not any(path.endswith(ext) for ext in (".png", ".jpg", ".ico", ".css", ".woff")):
            print(f"  {args[0]} {args[1]}")

    # ---- dispatch ----

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        params = parse_qs(parsed.query)

        try:
            # Root → landing page
            if path == "/" or path == "/index.html":
                self.send_html(LANDING_PAGE)

            # Gallery routes
            elif path == "/gallery/page":
                self.send_gallery_page()
            elif path == "/api/folders":
                self.send_json(self.get_folders())
            elif path == "/api/browse":
                folder = params.get("folder", [""])[0]
                self.send_json(self.browse_folder(folder))
            elif path == "/api/frames":
                atlas_path = params.get("atlas", [""])[0]
                unit = params.get("unit", [""])[0]
                self.send_json(self.get_frames(atlas_path, unit))
            elif path == "/api/crop":
                atlas_path = params.get("atlas", [""])[0]
                index_str = params.get("index", ["0"])[0]
                self.serve_crop(atlas_path, int(index_str))
            elif path.startswith("/static/"):
                self.serve_static(path[8:])

            # Queue routes
            elif path == "/queue/page":
                self.send_queue_page()
            elif path == "/api/queue/status":
                self.send_json(self.get_queue_status())
            elif path == "/api/queue/list":
                self.send_json(self.list_queue())
            elif path == "/api/queue/log":
                job_id = params.get("id", [""])[0]
                self.send_json(self.get_queue_log(job_id))
            elif path == "/api/queue/progress":
                self.send_json(self.get_queue_progress())

            # Log viewer
            elif path == "/api/logs":
                self.send_json(self.get_recent_logs())

            else:
                self.send_json({"error": f"Not found: {path}"}, status=404)

        except ConnectionError:
            pass
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length else "{}"

        try:
            data = json.loads(body) if body else {}

            if path == "/api/queue/add":
                result = self.queue_add(data)
                self.send_json(result)
            elif path == "/api/queue/remove":
                result = self.queue_remove(data)
                self.send_json(result)
            elif path == "/api/queue/clear":
                result = self.queue_clear(data)
                self.send_json(result)
            elif path == "/api/queue/run":
                result = self.queue_run(data)
                self.send_json(result)
            elif path == "/api/queue/pause":
                result = self.queue_pause()
                self.send_json(result)
            elif path == "/api/queue/resume":
                result = self.queue_resume()
                self.send_json(result)
            elif path == "/api/queue/clean":
                result = self.queue_clean()
                self.send_json(result)
            else:
                self.send_json({"error": f"Not found: {path}"}, status=404)
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    # ========== GALLERY HANDLERS ==========

    def send_gallery_page(self):
        """Serve the gallery HTML — uses external JS/CSS from tools/static/."""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<base href="/">
<title>IoA Asset Gallery</title>
<link rel="stylesheet" href="/static/gallery.css">
</head>
<body>
<header>
  <h1>Asset <span>Gallery</span></h1>
  <nav>
    <a href="#" id="back-to-dashboard">Back to Dashboard</a>
  </nav>
</header>
<div class="container">
  <h2>Release Snapshots &amp; Versioned Outputs</h2>
  <div id="folder-list" class="folders"><div class="loading">Scanning directories...</div></div>
  <div id="gallery-view" style="display:none;">
    <div class="breadcrumb" id="breadcrumb"></div>
    <div class="tab-bar" id="tab-bar"></div>
    <div class="tab-content active" id="tab-atlas"><div class="gallery" id="atlas-gallery"></div></div>
    <div class="tab-content" id="tab-frames"><div class="gallery" id="frame-gallery"></div></div>
  </div>
</div>
<div id="modal" class="modal" onclick="closeModal(event)">
  <span class="close" onclick="closeModal()">&times;</span>
  <div style="max-width:90vw;max-height:90vh;text-align:center;">
    <img id="modal-img" src="" alt="full-size preview">
    <div id="modal-info" class="atlas-info"></div>
    <div id="modal-frames" class="frame-grid"></div>
  </div>
</div>
<script src="/static/gallery.js"></script>
</body>
</html>"""
        self.send_html(html)

    # --- gallery data methods (shared with gallery_server logic) ---

    def _get_frame_list(self, meta):
        frames = meta.get("frames", [])
        if isinstance(frames, dict):
            return [{"filename": k, **v} for k, v in sorted(frames.items())]
        return frames

    def get_folders(self):
        scan_dir = Path(self.scan_dir)
        folders = []
        releases_dir = scan_dir / "releases"
        if releases_dir.exists():
            for entry in sorted(releases_dir.iterdir(), reverse=True):
                if entry.is_dir() and entry.name != "latest":
                    info = self._folder_info(entry, "release")
                    if info:
                        folders.append(info)
        for entry in sorted(scan_dir.iterdir(), reverse=True):
            if entry.is_dir() and entry.name.startswith("v") and entry.name[1:2].isdigit():
                info = self._folder_info(entry, "version")
                if info:
                    folders.append(info)
        latest_link = releases_dir / "latest"
        if latest_link.is_symlink():
            target = os.readlink(str(latest_link))
            for f in folders:
                if f["name"] == target or f["rel_path"].endswith(target):
                    f["is_latest"] = True
        return {"folders": folders}

    def _folder_info(self, entry, ftype):
        try:
            pngs = list(entry.glob("*.png"))
            if not pngs:
                return None
            name = entry.name
            date_str = name
            if "-20" in name or "_20" in name:
                parts = name.rsplit("-", 1)
                if len(parts) > 1 and len(parts[-1]) >= 8:
                    date_str = parts[-1].replace("_", " ")[:16]
            rel_path = str(entry.relative_to(self.scan_dir)) if str(self.scan_dir) in str(entry.parent) else entry.name
            return {
                "name": name, "rel_path": rel_path, "type": ftype,
                "date": date_str, "file_count": len(pngs), "is_latest": False,
            }
        except Exception:
            return None

    def browse_folder(self, folder_path):
        base = Path(self.scan_dir)
        target = base / folder_path if not os.path.isabs(folder_path) else Path(folder_path)
        if not target.exists():
            return {"error": f"Folder not found: {folder_path}", "atlases": []}
        atlases = []
        for png_file in sorted(target.glob("*_atlas*.png")):
            if "_lod1" in png_file.stem or "_lod2" in png_file.stem:
                continue
            name = png_file.stem
            unit = name.replace("_atlas", "").replace("_atlas", "")
            json_path = png_file.with_suffix(".json")
            frame_count = 0
            size = None
            if json_path.exists():
                try:
                    with open(json_path) as jf:
                        meta = json.load(jf)
                    frames = self._get_frame_list(meta)
                    frame_count = len(frames)
                    if frames and "frame" in frames[0]:
                        f = frames[0]["frame"]
                        size = {"w": f.get("w", 0), "h": f.get("h", 0)}
                except Exception:
                    pass
            try:
                from PIL import Image
                with Image.open(png_file) as img:
                    full_size = {"w": img.width, "h": img.height}
            except Exception:
                full_size = None
            rel_path = str(png_file.relative_to(self.scan_dir)) if self.scan_dir in str(png_file.parent) else png_file.name
            atlases.append({
                "name": png_file.name, "unit": unit,
                "url": f"/static/{rel_path}", "thumb": f"/static/{rel_path}",
                "rel_path": rel_path,
                "size": size or full_size or {"w": 0, "h": 0},
                "frame_count": frame_count,
            })
        return {"atlases": atlases, "folder": folder_path}

    def get_frames(self, atlas_rel_path, unit_name):
        base = Path(self.scan_dir)
        atlas_path = base / atlas_rel_path if not os.path.isabs(atlas_rel_path) else Path(atlas_rel_path)
        json_path = atlas_path.with_suffix(".json")
        if not json_path.exists():
            return {"frames": [], "size": None, "unit": unit_name}
        try:
            with open(json_path) as f:
                meta = json.load(f)
        except Exception:
            return {"frames": [], "size": None, "unit": unit_name}
        frames = self._get_frame_list(meta)
        result_frames = []
        for i, frame in enumerate(frames):
            filename = frame.get("filename", f"frame_{i:04d}.png")
            frame_data = frame.get("frame", {})
            w = frame_data.get("w", 0)
            h = frame_data.get("h", 0)
            result_frames.append({
                "name": filename, "index": i, "size": f"{w}x{h}" if w and h else "unknown",
                "thumb": f"/api/crop?atlas={atlas_rel_path}&index={i}",
                "frame": frame_data,
            })
        size = None
        if frames and "frame" in frames[0]:
            f = frames[0]["frame"]
            size = {"w": f.get("w", 0), "h": f.get("h", 0)}
        fps = meta.get("fps", meta.get("meta", {}).get("fps", 12))
        return {"frames": result_frames, "size": size, "unit": unit_name, "fps": fps}

    def serve_crop(self, atlas_rel_path, index):
        base = Path(self.scan_dir)
        atlas_path = base / atlas_rel_path if not os.path.isabs(atlas_rel_path) else Path(atlas_rel_path)
        json_path = atlas_path.with_suffix(".json")
        if not atlas_path.exists() or not json_path.exists():
            self.send_json({"error": "Not found"}, status=404)
            return
        try:
            from PIL import Image
            with open(json_path) as f:
                meta = json.load(f)
            frames = self._get_frame_list(meta)
            if index < 0 or index >= len(frames):
                self.send_json({"error": "Index out of range"}, status=404)
                return
            frame_data = frames[index]
            frame_rect = frame_data.get("frame", {})
            x = frame_rect.get("x", 0); y = frame_rect.get("y", 0)
            w = frame_rect.get("w", 64); h = frame_rect.get("h", 64)
            atlas_img = Image.open(atlas_path).convert("RGBA")
            sprite = atlas_img.crop((x, y, x + w, y + h))
            max_dim = 256
            if w > max_dim or h > max_dim:
                ratio = min(max_dim / w, max_dim / h)
                sprite = sprite.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            sprite.save(buf, format="PNG")
            buf.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("Content-Length", str(buf.getbuffer().nbytes))
            self.end_headers()
            self.wfile.write(buf.getvalue())
        except Exception as e:
            self.send_json({"error": f"Crop failed: {e}"}, status=500)

    def serve_static(self, rel_path):
        base = Path(self.scan_dir)
        file_path = base / rel_path
        if not file_path.exists():
            # Fallback: try tools/static/ (gallery JS/CSS)
            file_path = Path(STATIC_DIR) / rel_path
        if not file_path.exists() or not file_path.is_file():
            self.send_json({"error": f"File not found: {rel_path}"}, status=404)
            return
        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type:
            content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "max-age=3600")
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/static/"):
            rel = path[8:]
            file_path = Path(self.scan_dir) / rel
            if not file_path.exists():
                file_path = Path(STATIC_DIR) / rel
            if file_path.exists():
                self.send_response(200)
                self.send_header("Content-Length", str(file_path.stat().st_size))
                self.end_headers()
                return
        self.send_response(404)

    # ========== QUEUE HANDLERS ==========

    def _load_queue(self):
        """Load queue from disk — handles both list and dict formats."""
        if not os.path.exists(QUEUE_PATH):
            return {"jobs": [], "meta": {}}
        try:
            with open(QUEUE_PATH) as f:
                data = json.load(f)
            if isinstance(data, list):
                return {"jobs": data, "meta": {}}
            return data
        except Exception:
            return {"jobs": [], "meta": {}}

    def _save_queue(self, data):
        os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
        with open(QUEUE_PATH, "w") as f:
            json.dump(data, f, indent=2)

    def send_queue_page(self):
        """Render the queue dashboard HTML."""
        html = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Render Queue</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #111; color: #ddd; margin: 0; padding: 20px; }
  h2 { color: #d4a017; font-size: 18px; margin-bottom: 16px; }
  .queue-summary { display: flex; gap: 12px; margin-bottom: 20px; }
  .stat { background: #1e1e1e; border: 1px solid #333; border-radius: 6px; padding: 12px 20px; text-align: center; }
  .stat .num { font-size: 24px; font-weight: bold; color: #fff; }
  .stat .label { font-size: 11px; color: #888; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 8px 12px; background: #1a1a1a; color: #888; border-bottom: 1px solid #333; }
  td { padding: 8px 12px; border-bottom: 1px solid #222; }
  .status { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; }
  .status-queued { background: #2a4a6d; color: #aec8e8; }
  .status-running { background: #2a6d2a; color: #aee8ae; }
  .status-done { background: #333; color: #888; }
  .status-failed { background: #6d2a2a; color: #e8aeae; }
  .action-btn { background: #333; border: 1px solid #555; color: #ddd; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .action-btn:hover { background: #444; }
  .action-btn.danger { border-color: #a33; }
  .action-btn.danger:hover { background: #633; }
  .action-btn.primary { border-color: #d4a017; color: #d4a017; }
  .action-btn.primary:hover { background: #3a2a0a; }
  .progress-bar { background: #333; height: 4px; border-radius: 2px; margin: 8px 0; }
  .progress-fill { background: #d4a017; height: 100%; border-radius: 2px; transition: width 0.5s; }
  .log-box { background: #0a0a0a; border: 1px solid #222; border-radius: 4px; padding: 12px; font-family: monospace; font-size: 11px; color: #888; max-height: 200px; overflow-y: auto; white-space: pre-wrap; }
</style></head><body>
<h2>Render Queue</h2>
<div id="queue-controls" style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap;">
  <button class="action-btn primary" onclick="queueAction('run')">Run Now</button>
  <button class="action-btn" onclick="queueAction('pause')">Pause</button>
  <button class="action-btn" onclick="queueAction('resume')">Resume</button>
  <button class="action-btn danger" onclick="queueAction('clean')">Clean</button>
</div>
<div class="queue-summary" id="queue-summary">
  <div class="stat"><div class="num" id="q-total">0</div><div class="label">Total</div></div>
  <div class="stat"><div class="num" id="q-queued">0</div><div class="label">Queued</div></div>
  <div class="stat"><div class="num" id="q-running">0</div><div class="label">Running</div></div>
  <div class="stat"><div class="num" id="q-done">0</div><div class="label">Done</div></div>
  <div class="stat"><div class="num" id="q-failed">0</div><div class="label">Failed</div></div>
</div>
<div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>
<div style="margin-bottom:16px;display:flex;gap:8px;align-items:center;">
  <input type="text" id="unit-input" placeholder="Unit name..." style="background:#1e1e1e;border:1px solid #333;color:#ddd;padding:6px 12px;border-radius:4px;flex:1;">
  <button class="action-btn primary" onclick="addUnit()">Add to Queue</button>
</div>
<div id="queue-table-wrap"><table><thead><tr><th>ID</th><th>Unit</th><th>Status</th><th>Progress</th><th>Actions</th></tr></thead><tbody id="queue-body"></tbody></table></div>
<div id="queue-log" class="log-box" style="margin-top:16px;">Select a job to view its log.</div>
<script>
async function refreshQueue() {
  var r = await fetch('/api/queue/list');
  var data = await r.json();
  var jobs = data.jobs || [];
  var counts = { total: jobs.length, queued: 0, running: 0, done: 0, failed: 0 };
  var tbody = document.getElementById('queue-body');
  tbody.innerHTML = jobs.map(function(j) {
    counts[j.status + '']++;
    var pct = j.progress || 0;
    return '<tr><td>' + j.id + '</td><td>' + j.unit + '</td>'
      + '<td><span class="status status-' + j.status + '">' + j.status + '</span></td>'
      + '<td><div class="progress-bar"><div class="progress-fill" style="width:' + pct + '%"></div></div>' + pct + '%</td>'
      + '<td><button class="action-btn danger" onclick="removeJob(' + j.id + ')">Remove</button>'
      + ' <button class="action-btn" onclick="viewLog(' + j.id + ')">Log</button></td></tr>';
  }).join('');
  document.getElementById('q-total').textContent = counts.total;
  document.getElementById('q-queued').textContent = counts.queued;
  document.getElementById('q-running').textContent = counts.running;
  document.getElementById('q-done').textContent = counts.done;
  document.getElementById('q-failed').textContent = counts.failed;
  var totalPct = counts.total > 0 ? Math.round((counts.done / counts.total) * 100) : 0;
  document.getElementById('progress-fill').style.width = totalPct + '%';
}
async function queueAction(action) {
  await fetch('/api/queue/' + action, { method: 'POST', body: '{}' });
  refreshQueue();
}
async function addUnit() {
  var unit = document.getElementById('unit-input').value.trim();
  if (!unit) return;
  await fetch('/api/queue/add', { method: 'POST', body: JSON.stringify({ unit: unit }) });
  document.getElementById('unit-input').value = '';
  refreshQueue();
}
async function removeJob(id) {
  await fetch('/api/queue/remove', { method: 'POST', body: JSON.stringify({ id: id }) });
  refreshQueue();
}
async function viewLog(id) {
  var r = await fetch('/api/queue/log?id=' + id);
  var data = await r.json();
  document.getElementById('queue-log').textContent = data.log || 'No log available.';
}
refreshQueue();
setInterval(refreshQueue, 5000);
</script></body></html>"""
        self.send_html(html)

    def get_queue_status(self):
        data = self._load_queue()
        jobs = data.get("jobs", [])
        counts = {"total": len(jobs)}
        for s in ["queued", "running", "done", "failed"]:
            counts[s] = sum(1 for j in jobs if j.get("status") == s)
        paused = os.path.exists(os.path.join(QUEUE_DIR, ".render_pause"))
        return {"counts": counts, "paused": paused}

    def list_queue(self):
        data = self._load_queue()
        jobs = data.get("jobs", [])
        # Add progress info
        progress_path = os.path.join(QUEUE_DIR, "render_progress.json")
        progress = {}
        if os.path.exists(progress_path):
            try:
                with open(progress_path) as f:
                    progress = json.load(f)
            except Exception:
                pass
        for j in jobs:
            if j.get("status") == "running" and progress.get("unit_name") == j.get("unit"):
                j["progress"] = progress.get("pct", 0)
            elif j.get("status") == "done":
                j["progress"] = 100
            else:
                j["progress"] = 0
        return {"jobs": jobs}

    def get_queue_log(self, job_id):
        if not job_id:
            return {"log": ""}
        # Search render logs for this job
        if os.path.exists(LOG_DIR):
            for f in sorted(os.listdir(LOG_DIR), reverse=True):
                if job_id in f or (job_id.isdigit() and f.startswith(f"job_{job_id}")):
                    path = os.path.join(LOG_DIR, f)
                    try:
                        with open(path) as lf:
                            lines = lf.readlines()
                        return {"log": "".join(lines[-200:])}
                    except Exception:
                        pass
        # Try the batch render log
        batch_log = os.path.join(QUEUE_DIR, "v0.5.0_batch_render.log")
        if os.path.exists(batch_log):
            try:
                with open(batch_log) as f:
                    return {"log": "".join(f.readlines()[-200:])}
            except Exception:
                pass
        return {"log": "No log available."}

    def get_queue_progress(self):
        progress_path = os.path.join(QUEUE_DIR, "render_progress.json")
        if os.path.exists(progress_path):
            try:
                with open(progress_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"pct": 0, "phase": "idle"}

    def queue_add(self, data):
        unit = data.get("unit", "")
        if not unit:
            return {"error": "No unit specified"}
        q = self._load_queue()
        # Check for duplicates
        for j in q.get("jobs", []):
            if j.get("unit") == unit and j.get("status") in ("queued", "running"):
                return {"message": f"Already queued: {unit}"}
        next_id = max([j.get("id", 0) for j in q.get("jobs", [])] or [0]) + 1
        q.setdefault("jobs", []).append({
            "id": next_id, "unit": unit,
            "status": "queued", "created": datetime.now().isoformat(),
        })
        self._save_queue(q)
        return {"message": f"Added {unit} (job #{next_id})"}

    def queue_remove(self, data):
        job_id = data.get("id")
        if job_id is None:
            return {"error": "No job ID specified"}
        q = self._load_queue()
        q["jobs"] = [j for j in q.get("jobs", []) if j.get("id") != job_id]
        self._save_queue(q)
        return {"message": f"Removed job #{job_id}"}

    def queue_clear(self, data):
        statuses = data.get("status", ["done", "failed"])
        q = self._load_queue()
        q["jobs"] = [j for j in q.get("jobs", []) if j.get("status") not in statuses]
        self._save_queue(q)
        return {"message": f"Cleared {statuses} jobs"}

    def queue_run(self, data):
        # Launch render_queue runner in background
        engine = data.get("engine", "CYCLES")
        fast = data.get("fast", False)
        cmd = [sys.executable, "-m", "tools.render_queue", "run",
               "--engine", engine]
        if fast:
            cmd.append("--fast")
        try:
            subprocess.Popen(cmd, cwd=PROJECT_ROOT)
            return {"message": "Render queue started"}
        except Exception as e:
            return {"error": str(e)}

    def queue_pause(self):
        open(os.path.join(QUEUE_DIR, ".render_pause"), "w").close()
        return {"message": "Queue paused"}

    def queue_resume(self):
        pause_file = os.path.join(QUEUE_DIR, ".render_pause")
        if os.path.exists(pause_file):
            os.remove(pause_file)
        return {"message": "Queue resumed"}

    def queue_clean(self):
        q = self._load_queue()
        for j in q.get("jobs", []):
            if j.get("status") == "running":
                j["status"] = "queued"
        self._save_queue(q)
        return {"message": "Cleaned stale running jobs"}

    # ========== LOGS HANDLER ==========

    def get_recent_logs(self):
        logs = []
        # Gather recent log files
        log_sources = [
            os.path.join(OUTPUT_DIR, "v0.5.0_batch_render.log"),
            os.path.join(QUEUE_DIR, "render_queue_scheduled.log"),
            os.path.join(QUEUE_DIR, "schedule_render.log"),
        ]
        for path in log_sources:
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        lines = f.readlines()
                    logs.append(f"=== {os.path.basename(path)} ===")
                    logs.extend(lines[-50:])
                    logs.append("")
                except Exception:
                    pass
        if not logs:
            logs = ["No log files found. Run a render first."]
        return {"logs": logs}

    # ========== HELPERS ==========

    def send_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


# =============================================================================
# SERVER LAUNCH
# =============================================================================

def ensure_port(port: int, host: str = "127.0.0.1") -> int:
    """Forcefully clear the port, then bind to verify it's free.

    Kills any process holding the port (via fuser), then attempts
    bind + close. Returns the port on success.
    Raises RuntimeError if port cannot be claimed.
    """
    import subprocess
    # Try to kill whatever is on this port
    try:
        subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            capture_output=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Small delay for OS to release the socket
    import time as _time
    _time.sleep(0.3)
    # Verify we can bind
    for _ in range(3):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.close()
            return port
        except OSError:
            _time.sleep(0.5)
            continue
    raise RuntimeError(f"Could not claim port {port} after clearing")


def main():
    parser = argparse.ArgumentParser(description="IoA Unified Dashboard — gallery + render queue")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--scan-dir", default=SCAN_DIR, help="Output directory to scan")
    args = parser.parse_args()

    scan_dir = os.path.abspath(args.scan_dir)
    UnifiedHandler.scan_dir = scan_dir

    port = ensure_port(args.port, args.host)
    server = HTTPServer((args.host, port), UnifiedHandler)
    url = f"http://{args.host}:{port}/"

    print(f"[dashboard] IoA Pipeline Dashboard running at: {url}")
    print(f"[dashboard] Scanning: {scan_dir}")
    print(f"[dashboard] Press Ctrl+C to stop")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
