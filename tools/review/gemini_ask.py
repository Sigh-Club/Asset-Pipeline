#!/usr/bin/env -S /home/talzanar/.venvs/scrapling/bin/python3
"""gemini_ask.py — ask the Gemini web app through a real Chrome over CDP.

Why this shape (each point measured on this machine):

* `gemini-img` drives Gemini through `gemini_webapi`, which replays the web app's
  internal RPCs. Since the Gemini 3 build it reports the account unauthenticated
  (GET_USER_STATUS 1016), falls into guest mode, and fails every turn carrying an
  image with "Unknown API error code: 1100". Cookies are fine: page 200, upload
  200, text-only prompts answered.
* A headless browser with *injected cookies only* also fails — Google serves
  google.com/sorry/index, and the app keys the session on localStorage plus a
  matching fingerprint. The working combination is a real Chrome on a seeded
  profile, driven over CDP. Verified 2026-11-23: login, image attached, answer in
  22-88 s.
* Keep it single-path. A multi-profile retry loop and cookie injection were both
  tried and both broke it; one seeded profile is what works.

Usage:
  gemini_ask.py --check                       # browser up and logged in?
  gemini_ask.py --prompt "..." --image a.png  # attach and ask
  gemini_ask.py --prompt "..." --screenshot /tmp/x.png --dump-html /tmp/x.html

Output: JSON {ok, text, elapsed_s, logged_in, attached, images}. Exit 0 when an
answer was captured (and, if images were given, they were attached).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

HOME = pathlib.Path('~').expanduser()
PROFILE = HOME / '.config/gemini-chrome'
SEED = [HOME / '.config/sighnet-chrome', HOME / '.config/google-chrome']
APP_URL = 'https://gemini.google.com/app'
COMPOSER = 'rich-textarea [contenteditable="true"], [contenteditable="true"][role="textbox"]'
SEND = 'button[aria-label*="Send" i]'
STOP = 'button[aria-label*="Stop" i]'
THUMB = ('single-image-container, img[data-test-id="image"], .attachment-container, '
         '.file-chip, uploader-file-preview, [data-test-id="image-preview"], '
         'img[src^="blob:"], img[src^="data:image"]')
BINS = ['google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser']


def log(m: str) -> None:
    print(f'[gemini_ask] {m}', flush=True)


def chrome_bin() -> str:
    for b in BINS:
        p = shutil.which(b)
        if p:
            return p
    raise SystemExit('no Chrome on PATH')


def port_up(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def kill_stale(port: int) -> None:
    """Terminate any Chrome holding our profile (never the user's browser)."""
    try:
        subprocess.run(['pkill', '-f', f'user-data-dir={PROFILE}'], check=False)
        time.sleep(1.5)
    except Exception:
        pass


def seed_profile() -> str:
    """Copy the auth-bearing parts of the logged-in profile (never its 7 GB cache)."""
    if (PROFILE / 'Default' / 'Cookies').exists():
        return 'existing'
    src = next((p for p in SEED if (p / 'Default' / 'Cookies').exists()), None)
    if src is None:
        return 'no seed profile — log in once in the window that opens'
    PROFILE.mkdir(parents=True, exist_ok=True)
    for rel in ('Local State', 'Default/Preferences', 'Default/Secure Preferences',
                'Default/Cookies', 'Default/Local Storage', 'Default/Session Storage',
                'Default/Web Data'):
        s, d = src / rel, PROFILE / rel
        if not s.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    return f'seeded from {src.name}'


def ensure_chrome(port: int, headed: bool) -> bool:
    # A browser left on the port from an earlier run can be in any state, including
    # logged out; reusing it blindly is what made the gate "stop" with no cause
    # (measured 2026-11-23). Only reuse when it answers, otherwise restart it.
    if port_up(port):
        return True
    kill_stale(port)
    note = seed_profile()
    log(note)
    args = [chrome_bin(), f'--remote-debugging-port={port}', f'--user-data-dir={PROFILE}',
            '--no-first-run', '--no-default-browser-check', '--window-size=1400,1000']
    if not headed:
        args.append('--headless=new')
    args.append('about:blank')
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(60):
        if port_up(port):
            return True
        time.sleep(0.5)
    return False


def dismiss(page) -> None:
    for label in ('Accept all', 'Reject all', 'Got it', 'I agree'):
        try:
            b = page.get_by_role('button', name=label).first
            if b.count():
                b.click(timeout=3000)
                time.sleep(0.4)
                return
        except Exception:
            continue


def logged_in(page) -> bool:
    try:
        if page.get_by_role('button', name='Sign in').count():
            return False
        return page.locator(COMPOSER).count() > 0
    except Exception:
        return False


def attach(page, images: list[pathlib.Path], state: dict) -> bool:
    """Composer "+" (aria-label "Upload and tools") -> menu item "Upload files"."""
    plus = page.get_by_role('button', name='Upload and tools')
    if not plus.count():
        plus = page.locator('[aria-label="Upload and tools"], [aria-label*="Upload" i]')
    if not plus.count():
        state['upload_error'] = 'no "Upload and tools" control'
        return False
    try:
        with page.expect_file_chooser(timeout=30000) as fc:
            try:
                plus.first.click(timeout=10000)
            except Exception:
                plus.first.click(force=True, timeout=10000)
            page.get_by_role('menuitem', name='Upload files').first.click(timeout=20000)
        fc.value.set_files([str(p.resolve()) for p in images])
    except Exception as e:
        state['upload_error'] = f'{type(e).__name__}: {str(e)[:160]}'
        return False
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if page.evaluate(f"() => !!document.querySelector('{THUMB}')"):
                time.sleep(2.0)
                state['attached'] = True
                return True
        except Exception:
            pass
        time.sleep(0.5)
    state['upload_error'] = 'file chosen but no thumbnail appeared'
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--prompt')
    ap.add_argument('--image', action='append', default=[])
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--port', type=int, default=9222)
    ap.add_argument('--headed', action='store_true')
    ap.add_argument('--timeout', type=int, default=90)
    ap.add_argument('--max-wait', type=int, default=300)
    ap.add_argument('--stable-s', type=float, default=6.0)
    ap.add_argument('--type-delay', type=int, default=8)
    ap.add_argument('--screenshot')
    ap.add_argument('--dump-html')
    a = ap.parse_args()

    out: dict = {'ok': False, 'text': '', 'images': a.image, 'elapsed_s': 0.0}
    if not ensure_chrome(a.port, headed=a.headed):
        print(json.dumps(out | {'error': f'CDP port {a.port} never opened'}))
        return 1

    from playwright.sync_api import sync_playwright

    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{a.port}')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        state: dict = {}
        try:
            page.goto(APP_URL, wait_until='domcontentloaded', timeout=a.timeout * 1000)
            page.wait_for_selector(COMPOSER, timeout=30000)
            dismiss(page)
            state['logged_in'] = logged_in(page)
            if a.check:
                out.update({'ok': state['logged_in'], 'logged_in': state['logged_in'],
                            'url': page.url, 'elapsed_s': round(time.time() - t0, 1)})
                print(json.dumps(out))
                return 0 if state['logged_in'] else 1
            if not state['logged_in']:
                raise RuntimeError('not logged in (Sign in shown)')

            if a.image:
                attach(page, [pathlib.Path(i) for i in a.image], state)
            box = page.locator(COMPOSER).first
            try:
                box.click(timeout=8000)
            except Exception:
                box.focus()
            page.keyboard.type(a.prompt or '', delay=a.type_delay)
            sent = False
            try:
                b = page.locator(SEND)
                if b.count() and b.last.is_visible():
                    b.last.click(timeout=8000)
                    sent = True
            except Exception:
                pass
            if not sent:
                page.keyboard.press('Control+Enter')

            deadline = time.time() + a.max_wait
            last, stable, best = '', None, ''
            while time.time() < deadline:
                try:
                    cur = page.evaluate("""() => {
                        const n=[...document.querySelectorAll('model-response message-content, model-response')];
                        return n.length ? (n[n.length-1].innerText||'').trim() : ''; }""")
                except Exception:
                    cur = ''
                if cur and cur != last:
                    last, stable = cur, time.time()
                if len(cur) > len(best):
                    best = cur
                try:
                    busy = page.locator(STOP).count() > 0
                except Exception:
                    busy = False
                if best and not busy and stable and time.time() - stable >= a.stable_s:
                    break
                time.sleep(1.0)
            state['text'] = (best or last).strip()
            if a.dump_html:
                pathlib.Path(a.dump_html).write_text(page.content())
            if a.screenshot:
                page.screenshot(path=a.screenshot, full_page=True)
        except Exception as e:
            state['error'] = f'{type(e).__name__}: {str(e)[:200]}'
        finally:
            out.update({'text': state.get('text', ''),
                        'elapsed_s': round(time.time() - t0, 1),
                        'logged_in': state.get('logged_in'),
                        'attached': state.get('attached', False)})
            if state.get('error'):
                out['error'] = state['error']
            elif a.image and not state.get('attached'):
                out['error'] = f"image not attached: {state.get('upload_error', 'unknown')}"
            elif not out['text']:
                out['error'] = 'no response text captured'
            out['ok'] = bool(out['text']) and 'error' not in out
            page.close()

    print(json.dumps(out))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
