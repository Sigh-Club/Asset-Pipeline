#!/usr/bin/env -S /home/talzanar/.venvs/scrapling/bin/python3
"""gemini_ask.py — ask the Gemini web app through a real Chrome over CDP.

Why this shape (verified 2026-11-23):

* `gemini-img` drives Gemini through `gemini_webapi`, a third-party client that
  replays the web app's internal RPCs. Since the Gemini 3 build it reads the
  account as unauthenticated (GET_USER_STATUS 1016), falls into guest mode, and
  fails every turn that carries an image with "Unknown API error code: 1100".
  The cookies are fine — page 200, upload 200, text-only prompts answered.
* A headless browser with injected cookies also fails: Google serves
  https://www.google.com/sorry/index (anti-bot) and the app's sidebar/composer
  never settle, so "New chat" and the upload control cannot be clicked. Modern
  AI web apps also key the session on localStorage and a matching fingerprint,
  not cookies alone.

So: launch a real Chrome on a dedicated profile (seeded once from the profile
that is already logged in), attach with Playwright over CDP, and drive the UI
exactly as a person would. The browser keeps cookies + localStorage + fingerprint,
so no cookie juggling and no bot interstitial.

Usage:
  gemini_ask.py --prompt "describe this render" --image out/render.png
  gemini_ask.py --prompt "..." --image a.png --image b.png
  gemini_ask.py --prompt "..." --keep-open --screenshot /tmp/x.png
  gemini_ask.py --check            # is the browser up and logged in?

Output: JSON {ok, text, elapsed_s, new_chat, logged_in, images}. Exit 0 when an
answer was captured (and, when images were given, actually attached).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

HOME = pathlib.Path('~').expanduser()
DEFAULT_PROFILE = HOME / '.config/gemini-chrome'
SEED_PROFILES = [
    HOME / '.config/sighnet-chrome',   # the profile that is actually logged in
    HOME / '.config/google-chrome',
]
CHROME_BINS = ['google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser']
APP_URL = 'https://gemini.google.com/app'

COMPOSER = 'rich-textarea [contenteditable="true"], [contenteditable="true"][role="textbox"]'
NEW_CHAT_SCREEN = r'where should we start'
SEND_BUTTON = 'button[aria-label*="Send" i]'
STOP_BUTTON = 'button[aria-label*="Stop" i]'
ATTACH_THUMB = ('single-image-container, img[data-test-id="image"], .attachment-container, '
                '.file-chip, uploader-file-preview, [data-test-id="image-preview"], '
                'img[src^="blob:"], img[src^="data:image"]')


# --------------------------------------------------------------- browser ---

def chrome_bin() -> str:
    for name in CHROME_BINS:
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit('no Chrome/Chromium binary found on PATH')


def port_is_up(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def seed_profile(dest: pathlib.Path) -> str:
    """Copy the auth-bearing parts of the logged-in profile (not its 7 GB cache).

    Cookies alone are not enough for a modern web app; localStorage and the
    profile's own identity are what keep the session valid.
    """
    if (dest / 'Default' / 'Cookies').exists():
        return 'existing'
    src = next((p for p in SEED_PROFILES if (p / 'Default' / 'Cookies').exists()), None)
    if src is None:
        return 'no seed profile found — log in once in the window that opens'
    dest.mkdir(parents=True, exist_ok=True)
    items = ['Local State', 'First Run', 'Default/Preferences', 'Default/Secure Preferences',
             'Default/Cookies', 'Default/Local Storage', 'Default/Session Storage',
             'Default/Web Data', 'Default/Login Data']
    for rel in items:
        s, d = src / rel, dest / rel
        if not s.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    return f'seeded from {src.name}'


def ensure_chrome(port: int, profile: pathlib.Path, headed: bool) -> tuple[bool, str]:
    if port_is_up(port):
        return True, 'reused running browser'
    note = seed_profile(profile)
    args = [chrome_bin(), f'--remote-debugging-port={port}',
            f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
            '--disable-blink-features=AutomationControlled', '--window-size=1400,1000']
    if not headed:
        args.append('--headless=new')
    args.append('about:blank')
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(60):
        if port_is_up(port):
            return True, note
        time.sleep(0.5)
    return False, f'{note}; CDP port {port} never opened'


# ------------------------------------------------------------------ page ---

def dismiss_overlays(page) -> None:
    """Clear the consent sheet that otherwise swallows every click."""
    for label in (r'accept all', r'reject all', r'got it', r'i agree'):
        try:
            btn = page.get_by_role('button', name=re.compile(label, re.I)).first
            if btn.count():
                btn.click(timeout=3000)
                time.sleep(0.4)
                return
        except Exception:
            continue


def start_new_chat(page, state: dict) -> bool:
    """Click New chat and prove it by the empty-state screen.

    A new chat has no id in the URL, so a URL change is the wrong test — the
    only reliable signal is "Where should we start?".
    """
    # already on the empty state? then there is nothing to click
    try:
        if page.get_by_text(NEW_CHAT_SCREEN, exact=False).count():
            state['new_chat'] = 'already fresh'
            return True
    except Exception:
        pass

    clicked = False
    for make in (lambda: page.get_by_role('button', name='New chat').first,
                 lambda: page.get_by_role('link', name='New chat').first,
                 lambda: page.get_by_text('New chat', exact=True).first,
                 lambda: page.locator('[aria-label*="New chat" i]').first):
        try:
            el = make()
            if el.count():
                el.click(timeout=6000)
                clicked = True
                break
        except Exception as e:
            state['new_chat_err'] = f'{type(e).__name__}: {str(e)[:80]}'
    if not clicked:
        state['new_chat'] = 'no New chat control found'
        return False
    for _ in range(40):
        try:
            if page.get_by_text(re.compile(NEW_CHAT_SCREEN, re.I)).count():
                state['new_chat'] = 'ok'
                return True
        except Exception:
            pass
        time.sleep(0.5)
    state['new_chat'] = 'clicked but no empty state'
    return False


def attach_images(page, images: list[pathlib.Path], state: dict, settle: float) -> bool:
    """Attach through the composer's "+" -> "Upload files" file chooser."""
    files = [str(p.resolve()) for p in images]
    try:
        # the composer's "+" is aria-label="Upload and tools" (verified live
        # 2026-11-23); Playwright matches a string name as a substring but a
        # regex name as a full match, which is why regexes never matched
        plus = page.get_by_role('button', name='Upload and tools')
        if not plus.count():
            plus = page.locator('[aria-label="Upload and tools"], [aria-label*="Upload" i]')
        with page.expect_file_chooser(timeout=30000) as fc:
            plus.first.click(timeout=15000)
            page.get_by_role('menuitem', name='Upload files').first.click(timeout=20000)
        fc.value.set_files(files)
    except Exception as e:
        state['upload_error'] = f'{type(e).__name__}: {str(e)[:200]}'
        return False

    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if page.evaluate(f"() => !!document.querySelector('{ATTACH_THUMB}')"):
                state['attached'] = True
                time.sleep(settle)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    state['upload_error'] = 'file chooser accepted the file but no thumbnail appeared'
    return False


def wait_for_answer(page, args, state: dict) -> str:
    def read_latest() -> str:
        try:
            return page.evaluate("""() => {
                const nodes = [...document.querySelectorAll(
                    'model-response message-content, model-response, .model-response-text')];
                return nodes.length ? (nodes[nodes.length - 1].innerText || '').trim() : '';
            }""")
        except Exception:
            return ''

    deadline = time.time() + args.max_wait
    last, stable_since, best = '', None, ''
    while time.time() < deadline:
        cur = read_latest()
        if cur and cur != last:
            last, stable_since = cur, time.time()
        if len(cur) > len(best):
            best = cur
        generating = False
        try:
            generating = page.locator(STOP_BUTTON).count() > 0
        except Exception:
            pass
        if best and not generating and stable_since and time.time() - stable_since >= args.stable_s:
            break
        time.sleep(1.0)
    return (best or last).strip()


def main() -> int:
    p = argparse.ArgumentParser(description='ask the Gemini web app through real Chrome (CDP)')
    p.add_argument('--prompt')
    p.add_argument('--image', action='append', default=[])
    p.add_argument('--check', action='store_true', help='report browser/login state and exit')
    p.add_argument('--port', type=int, default=9222)
    p.add_argument('--profile', default=str(DEFAULT_PROFILE))
    p.add_argument('--headless', action='store_true', help='new headless mode (default: headed)')
    p.add_argument('--keep-open', action='store_true', help='leave the tab open')
    p.add_argument('--timeout', type=int, default=90)
    p.add_argument('--max-wait', type=int, default=300)
    p.add_argument('--stable-s', type=float, default=6.0)
    p.add_argument('--upload-settle', type=float, default=2.5)
    p.add_argument('--type-delay', type=int, default=8)
    p.add_argument('--screenshot')
    p.add_argument('--dump-html')
    args = p.parse_args()

    out: dict = {'ok': False, 'text': '', 'images': [], 'elapsed_s': 0.0}
    profile = pathlib.Path(args.profile).expanduser()
    ok, note = ensure_chrome(args.port, profile, headed=not args.headless)
    out['browser'] = note
    if not ok:
        print(json.dumps(out | {'error': note}, ensure_ascii=False))
        return 1

    from playwright.sync_api import sync_playwright

    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{args.port}')
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        state: dict = {}
        try:
            page.goto(APP_URL, wait_until='domcontentloaded', timeout=args.timeout * 1000)
            page.wait_for_selector(COMPOSER, timeout=args.timeout * 1000)
            state['logged_in'] = 'accounts.google.com' not in page.url
            dismiss_overlays(page)

            if args.check:
                out.update({'ok': bool(state['logged_in']), 'logged_in': state['logged_in'],
                            'url': page.url, 'elapsed_s': round(time.time() - t0, 1)})
                print(json.dumps(out, ensure_ascii=False))
                return 0 if state['logged_in'] else 1

            start_new_chat(page, state)
            if args.image:
                attach_images(page, [pathlib.Path(i) for i in args.image], state, args.upload_settle)

            box = page.locator(COMPOSER).first
            try:
                box.click(timeout=8000)
            except Exception:
                box.focus()
            page.keyboard.type(args.prompt, delay=args.type_delay)

            sent = False
            try:
                btn = page.locator(SEND_BUTTON)
                if btn.count() and btn.last.is_visible():
                    btn.last.click(timeout=8000)
                    sent = True
            except Exception:
                pass
            if not sent:
                page.keyboard.press('Control+Enter')

            state['text'] = wait_for_answer(page, args, state)
            if args.dump_html:
                pathlib.Path(args.dump_html).write_text(page.content())
            if args.screenshot:
                page.screenshot(path=args.screenshot, full_page=True)
        except Exception as e:
            state['error'] = f'{type(e).__name__}: {str(e)[:300]}'
        finally:
            out.update({
                'text': state.get('text', ''),
                'elapsed_s': round(time.time() - t0, 1),
                'logged_in': state.get('logged_in'),
                'new_chat': state.get('new_chat'),
                'attached': state.get('attached', False),
                'images': args.image,
            })
            if state.get('error'):
                out['error'] = state['error']
            elif state.get('upload_error'):
                out['error'] = f"image not attached: {state['upload_error']}"
            elif not out['text']:
                out['error'] = 'no response text captured'
            out['ok'] = bool(out['text']) and not out.get('error')
            if not args.keep_open:
                page.close()

    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
