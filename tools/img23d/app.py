#!/usr/bin/env python3
"""img23d App — point-and-click front-end for the image-to-3D stage.

Import a concept image, reconstruct, make the print plate, tile for the
printer, verify detail fidelity — no terminal required. Long jobs run in
background threads; logs stream into the window; every product lands in one
output folder with a Reveal button.

Run:  python3 app.py          (system python is fine — pipeline runs in the venv)
"""

from __future__ import annotations

import queue
import subprocess
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

HERE = Path(__file__).resolve().parent
VENV_PY = HERE / ".venv" / "bin" / "python"
F3D = "f3d"
OUTPUT_ROOT = HERE.parent.parent / "output" / "img23d"

TOOLS = dict(recon=HERE / "img23d.py", plate=HERE / "plate.py",
             tiles=HERE / "tiles.py", verify=HERE / "verify.py")


def venv_py():
    return str(VENV_PY) if VENV_PY.exists() else sys.executable if (sys := __import__("sys")) else "python3"


class Runner:
    """Background job runner: one at a time, streamed to a queue."""

    def __init__(self, log_fn, done_fn):
        self.q: queue.Queue = queue.Queue()
        self.log_fn = log_fn
        self.done_fn = done_fn
        self.busy = False

    def run(self, cmd, cwd=None):
        if self.busy:
            self.log_fn("[app] a job is already running — wait for it")
            return
        self.busy = True

        def work():
            try:
                proc = subprocess.Popen(
                    cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env={**__import__("os").environ,
                                               "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
                for line in proc.stdout:
                    self.q.put(line.rstrip())
                proc.wait()
                self.q.put(f"[exit {proc.returncode}]")
            except Exception as e:  # noqa: BLE001
                self.q.put(f"[app error] {e}")
            self.q.put(None)

        threading.Thread(target=work, daemon=True).start()

    def pump(self):
        while True:
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                break
            if line is None:
                self.busy = False
                self.done_fn()
            else:
                self.log_fn(line)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("img23d — image to 3D")
        self.geometry("1180x780")
        self.image = None       # Path
        self.outdir = None      # Path after recon
        self.glb = None         # best mesh so far
        self.runner = Runner(self.log, self.refresh_outputs)

        pad = dict(padx=6, pady=4)

        # ---- top: source image
        top = ttk.LabelFrame(self, text="1 · Source artwork")
        top.pack(fill="x", **pad)
        self.img_label = ttk.Label(top, text="no image loaded")
        self.img_label.pack(side="left", padx=8, pady=4)
        ttk.Button(top, text="Import image…", command=self.pick_image).pack(side="left", padx=4)
        self.src_short = tk.StringVar(value="")
        ttk.Button(top, text="Open containing folder", command=lambda: self.reveal(self.image)).pack(side="right", padx=4)

        # ---- params
        par = ttk.LabelFrame(self, text="2 · Settings")
        par.pack(fill="x", **pad)
        self.vars = {
            "seed": tk.StringVar(value="7"),
            "steps": tk.StringVar(value="30"),
            "resolution": tk.StringVar(value="384"),
            "relief": tk.StringVar(value="0.12"),
            "width_mm": tk.StringVar(value="628"),
            "bed_mm": tk.StringVar(value="190"),
            "detail_strength": tk.StringVar(value="1.2"),
        }
        labels = [("Seed", "seed"), ("Diffusion steps", "steps"), ("MC resolution", "resolution"),
                  ("Plate relief", "relief"), ("Panel width mm", "width_mm"),
                  ("Printer bed mm", "bed_mm"), ("Detail strength", "detail_strength")]
        for i, (lab, key) in enumerate(labels):
            ttk.Label(par, text=lab).grid(row=0, column=2 * i, padx=(8, 2))
            ttk.Entry(par, width=7, textvariable=self.vars[key]).grid(row=0, column=2 * i + 1)

        # ---- actions
        act = ttk.LabelFrame(self, text="3 · Run")
        act.pack(fill="x", **pad)
        for txt, fn in [("Reconstruct 3D", self.do_recon), ("Verify vs artwork", self.do_verify),
                        ("Make print plate", self.do_plate), ("Tile for CR-200B", self.do_tiles),
                        ("Preview render", self.do_preview), ("Open output folder", self.open_dir)]:
            ttk.Button(act, text=txt, command=fn).pack(side="left", padx=6, pady=4)
        self.status = tk.StringVar(value="idle")
        ttk.Label(act, textvariable=self.status, foreground="#555").pack(side="right", padx=8)

        # ---- main: preview + log
        main = ttk.Panedwindow(self, orient="horizontal")
        main.pack(fill="both", expand=True, **pad)
        left = ttk.Labelframe(main, text="Preview (latest render / verification)")
        right = ttk.Notebook(main)
        main.add(left, weight=3); main.add(right, weight=2)

        self.canvas = tk.Canvas(left, bg="#222")
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self._photo = None

        logf = ttk.Frame(right)
        self.logbox = tk.Text(logf, height=10, wrap="none", state="disabled", font=("TkFixedFont", 9))
        ys = ttk.Scrollbar(logf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=ys.set)
        self.logbox.pack(side="left", fill="both", expand=True); ys.pack(side="right", fill="y")
        right.add(logf, text="Log")

        filesf = ttk.Frame(right)
        self.files = tk.Listbox(filesf)
        fs = ttk.Scrollbar(filesf, command=self.files.yview)
        self.files.configure(yscrollcommand=fs.set)
        self.files.pack(side="left", fill="both", expand=True); fs.pack(side="right", fill="y")
        self.files.bind("<Double-1>", self.open_selected)
        right.add(filesf, text="Output files")

        self.after(200, self.pump_loop)
        self.log("[app] ready — import an artwork image to begin")

    # ---------- helpers
    def log(self, line):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def pump_loop(self):
        self.runner.pump()
        self.after(200, self.pump_loop)

    def need_image(self):
        if not self.image:
            self.log("[app] import an image first (button top-left)")
        return bool(self.image)

    def pick_image(self):
        p = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
        if not p:
            return
        self.image = Path(p)
        self.outdir = OUTPUT_ROOT / f"{self.image.stem}-app"
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.src_short.set(str(self.image))
        im = Image.open(self.image); im.thumbnail((360, 300))
        self._src_photo = ImageTk.PhotoImage(im)
        self.img_label.configure(image=self._src_photo, text="")
        self.glb = self.outdir / f"{self.image.stem}.glb"
        if self.glb.exists():
            self.refresh_outputs()
        self.log(f"[app] source: {self.image}")
        self.status.set("image loaded")

    def args(self, prefix=()):
        return [venv_py(), str(TOOLS["recon"]), str(self.image),
                "--seed", self.vars["seed"].get(), "--steps", self.vars["steps"].get(),
                "--resolution", self.vars["resolution"].get(),
                "--out", str(self.outdir), *prefix]

    # ---------- actions
    def do_recon(self):
        if not self.need_image():
            return
        self.status.set("reconstructing… (~90 s, first run downloads weights)")
        self.runner.run(self.args())

    def do_plate(self):
        if not self.glb or not self.glb.exists():
            self.log("[app] reconstruct first")
            return
        self.status.set("building print plate…")
        self.runner.run([venv_py(), str(TOOLS["plate"]), str(self.glb),
                         "--res", "960x960", "--relief", self.vars["relief"].get(),
                         "--detail-image", str(self.image),
                         "--detail-strength", self.vars["detail_strength"].get(),
                         "--out", str(self.outdir / "plate.stl")])

    def do_tiles(self):
        plate = self.outdir / "plate.stl"
        if not plate.exists():
            self.log("[app] make the plate first")
            return
        self.status.set("tiling for the printer…")
        self.runner.run([venv_py(), str(TOOLS["tiles"]), str(plate),
                         "--width", self.vars["width_mm"].get(), "--bed", self.vars["bed_mm"].get()])

    def do_verify(self):
        plate = self.outdir / "plate.stl"
        target = plate if plate.exists() else self.glb
        if not target or not Path(target).exists():
            self.log("[app] nothing to verify yet")
            return
        self.status.set("verifying detail fidelity…")
        self.runner.run([venv_py(), str(TOOLS["verify"]), str(target), str(self.image),
                         "--out", str(self.outdir / "verify.png")])

    def do_preview(self):
        target = self.latest_mesh()
        if not target:
            self.log("[app] nothing rendered yet")
            return
        png = self.outdir / "preview.png"
        subprocess.run([F3D, str(target), "--output", str(png),
                        "--resolution", "1000,720", "--up", "+Z"], capture_output=True)
        self.show_image(png)
        self.refresh_outputs()

    def latest_mesh(self):
        for cand in [self.outdir / "plate.stl", self.glb]:
            if cand and Path(cand).exists():
                return cand
        return None

    def show_image(self, path: Path):
        if not Path(path).exists():
            return
        im = Image.open(path); im.thumbnail((760, 560))
        self._photo = ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2,
                                 image=self._photo, anchor="center")

    def refresh_outputs(self):
        self.files.delete(0, "end")
        if self.outdir and self.outdir.exists():
            for f in sorted(self.outdir.rglob("*")):
                if f.suffix in {".stl", ".glb", ".obj", ".png", ".json"}:
                    self.files.insert("end", str(f.relative_to(self.outdir)))
        if self.outdir and (self.outdir / "preview.png").exists():
            self.show_image(self.outdir / "preview.png")

    def open_selected(self, _):
        sel = self.files.curselection()
        if not sel:
            return
        f = self.outdir / self.files.get(sel)
        if f.suffix == ".stl":
            subprocess.Popen([F3D, str(f)])
        elif f.suffix == ".png":
            self.show_image(f)
        else:
            webbrowser.open(f.as_uri())

    def reveal(self, p):
        if p and Path(p).exists():
            webbrowser.open(Path(p).parent.as_uri())

    def open_dir(self):
        if self.outdir:
            webbrowser.open(self.outdir.as_uri())


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
