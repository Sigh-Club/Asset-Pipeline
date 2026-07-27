#!/usr/bin/env python3
"""
gallery_server.py — Web gallery for browsing rendered asset atlases.

Provides a browser-based UI to browse release folders, preview atlas PNGs,
and view individual atlas frames extracted from atlas JSON metadata.

All JavaScript is external (tools/static/gallery.js) — no inline scripts
to avoid Python escaping issues. Uses modern JS template literals.

Usage:
    python3 tools/gallery_server.py
    python3 tools/gallery_server.py --port 9090
    python3 tools/gallery_server.py --scan-dir /path/to/output
    python3 tools/gallery_server.py --no-browser
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
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_SCAN_DIR = os.path.join(PROJECT_ROOT, "output")
STATIC_DIR = os.path.join(SCRIPT_DIR, "static")

# Minimal HTML page — JS and CSS are loaded externally
GALLERY_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IoA Asset Gallery</title>
<link rel="stylesheet" href="/static/gallery.css">
</head>
<body>
<header>
  <h1>IoA Asset <span>Gallery</span></h1>
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


class GalleryHandler(BaseHTTPRequestHandler):
    """HTTP handler for the asset gallery."""

    scan_dir = DEFAULT_SCAN_DIR
    static_dir = STATIC_DIR

    def log_message(self, format, *args):
        path = urlparse(self.path).path
        if not any(path.endswith(ext) for ext in (".png", ".jpg", ".ico", ".css", ".js")):
            print(f"  {args[0]} {args[1]}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        params = parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                self.send_html(GALLERY_PAGE)
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
            else:
                self.send_json({"error": f"Not found: {path}"}, status=404)
        except ConnectionError:
            pass
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/static/"):
            file_path = self._resolve_static(path[8:])
            if file_path and file_path.exists():
                self.send_response(200)
                self.send_header("Content-Length", str(file_path.stat().st_size))
                self.end_headers()
                return
        self.send_response(404)

    # ---- Helpers ----

    def _resolve_static(self, rel_path: str) -> Path | None:
        """Resolve a static file, checking scan_dir first, then static_dir."""
        # First try scan dir (atlas PNGs live here)
        cand = Path(self.scan_dir) / rel_path
        if cand.exists() and cand.is_file():
            return cand
        # Fall back to static dir (JS, CSS)
        cand = Path(self.static_dir) / rel_path
        if cand.exists() and cand.is_file():
            return cand
        return None

    def send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    # ---- Static file serving ----

    def serve_static(self, rel_path: str):
        file_path = self._resolve_static(rel_path)
        if not file_path:
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

    # ---- API: folders ----

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
            # Only count LOD0 atlas files for accurate "atlas files" count
            atlas_pngs = [
                p for p in entry.glob("*.png")
                if p.stem.endswith("_atlas")  # LOD0 only
            ]
            if not atlas_pngs:
                # Fallback: count all PNGs if no LOD0 atlases found
                all_pngs = list(entry.glob("*.png"))
                if not all_pngs:
                    return None
                file_count = len(all_pngs)
            else:
                file_count = len(atlas_pngs)

            name = entry.name
            date_str = name
            if "-20" in name or "_20" in name:
                parts = name.rsplit("-", 1)
                if len(parts) > 1 and len(parts[-1]) >= 8:
                    ts = parts[-1].replace("_", " ")[:19]
                    date_str = ts

            parent_str = str(entry.parent)
            scan_str = str(self.scan_dir)
            if scan_str in parent_str:
                rel_path = str(entry.relative_to(self.scan_dir))
            else:
                rel_path = entry.name

            return {
                "name": name,
                "rel_path": rel_path,
                "type": ftype,
                "date": date_str,
                "file_count": file_count,
                "is_latest": False,
            }
        except Exception:
            return None

    # ---- API: browse ----

    def _get_frame_list(self, meta):
        frames = meta.get("frames", [])
        if isinstance(frames, dict):
            return [{"filename": k, **v} for k, v in sorted(frames.items())]
        return frames

    def browse_folder(self, folder_path):
        base = Path(self.scan_dir)
        target = base / folder_path if not os.path.isabs(folder_path) else Path(folder_path)
        if not target.exists() or not target.is_dir():
            return {"error": f"Folder not found: {folder_path}", "atlases": []}

        atlases = []
        for png_file in sorted(target.glob("*_atlas*.png")):
            if "_lod1" in png_file.stem or "_lod2" in png_file.stem:
                continue

            name_stem = png_file.stem
            # Extract unit name from filename — strip trailing _atlas (possibly doubled)
            unit = name_stem
            while unit.endswith("_atlas"):
                unit = unit[:-6]

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

            parent_str = str(png_file.parent)
            scan_str = str(self.scan_dir)
            if scan_str in parent_str:
                rel_path = str(png_file.relative_to(self.scan_dir))
            else:
                rel_path = png_file.name

            atlases.append({
                "name": png_file.name,
                "unit": unit,
                "url": f"/static/{rel_path}",
                "thumb": f"/static/{rel_path}",
                "rel_path": rel_path,
                "size": size or full_size or {"w": 0, "h": 0},
                "frame_count": frame_count,
            })

        return {"atlases": atlases, "folder": folder_path}

    # ---- API: frames ----

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
                "name": filename,
                "index": i,
                "size": f"{w}x{h}" if w and h else "unknown",
                "thumb": f"/api/crop?atlas={atlas_rel_path}&index={i}",
                "frame": frame_data,
            })

        size = None
        if frames and "frame" in frames[0]:
            f = frames[0]["frame"]
            size = {"w": f.get("w", 0), "h": f.get("h", 0)}

        fps = meta.get("fps", meta.get("meta", {}).get("fps", 12))
        return {"frames": result_frames, "size": size, "unit": unit_name, "fps": fps}

    # ---- API: crop ----

    def serve_crop(self, atlas_rel_path, index):
        base = Path(self.scan_dir)
        atlas_path = base / atlas_rel_path if not os.path.isabs(atlas_rel_path) else Path(atlas_rel_path)
        json_path = atlas_path.with_suffix(".json")
        if not atlas_path.exists() or not json_path.exists():
            self.send_json({"error": "Atlas or metadata not found"}, status=404)
            return

        try:
            from PIL import Image
            with open(json_path) as f:
                meta = json.load(f)
            frames = self._get_frame_list(meta)
            if index < 0 or index >= len(frames):
                self.send_json({"error": f"Frame index {index} out of range"}, status=404)
                return

            frame_data = frames[index]
            frame_rect = frame_data.get("frame", {})
            x = frame_rect.get("x", 0)
            y = frame_rect.get("y", 0)
            w = frame_rect.get("w", 64)
            h = frame_rect.get("h", 64)

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


def ensure_port(port: int, host: str = "127.0.0.1") -> int:
    """Forcefully clear the port, then bind to verify it's free."""
    import subprocess, time
    try:
        subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    time.sleep(0.3)
    for _ in range(3):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            s.close()
            return port
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"Could not claim port {port}")


def main():
    parser = argparse.ArgumentParser(description="IoA Asset Gallery — browse rendered sprite atlases")
    parser.add_argument("--port", "-p", type=int, default=8082, help="Port (default: 8082)")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--scan-dir", default=DEFAULT_SCAN_DIR, help="Base directory to scan")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    scan_dir = os.path.abspath(args.scan_dir)
    if not os.path.exists(scan_dir):
        print(f"[gallery] Scan directory not found: {scan_dir}")
        sys.exit(1)

    if not os.path.exists(STATIC_DIR):
        print(f"[gallery] Static assets directory not found: {STATIC_DIR}")
        sys.exit(1)

    GalleryHandler.scan_dir = scan_dir
    GalleryHandler.static_dir = STATIC_DIR

    port = ensure_port(args.port, args.host)
    server = HTTPServer((args.host, port), GalleryHandler)
    url = f"http://{args.host}:{port}/"

    print(f"[gallery] IoA Asset Gallery running at: {url}")
    print(f"[gallery] Scanning: {scan_dir}")
    print(f"[gallery] Press Ctrl+C to stop")

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[gallery] Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
