#!/usr/bin/env python3
"""
nexus_login_capture.py  v2.0
================================================================================
One-time interactive helper. Captures a real, logged-in Nexus Mods session
(with "Show adult content" enabled) as a Playwright storage_state file.
nexus_deep_comments.py can reuse that session via --auth-state to see
adult-content-gated mods, which an anonymous session can't -- the page simply
omits thread_id for them, so fetch_all_comments() correctly (but unhelpfully)
returns [] rather than the real comment count. See CLAUDE.md for the
"known gap: NSFW-tagged mods return 0 comments" note.

v1.0 launched its own Playwright-controlled Chromium for the whole flow
(login form included) and got stuck: Nexus's signup/login captcha never
rendered. Root cause -- the same class of issue as the 279/22659 investigation
in nexus_deep_comments.py's docstring, just hitting a captcha instead of a
comments page: captcha providers commonly detect a CDP-automation-controlled
browser (Playwright's launch() injects --enable-automation and other
automation-marking flags/behavior) and refuse to render the widget at all,
independent of and in addition to the navigator.webdriver signal.

Fix (v2.0), mirroring nexus_manual_rescue.py's approach from that same
investigation: split into two phases, LAUNCH and EXPORT. The browser used for
LAUNCH is a genuinely manually-spawned Chrome (bare subprocess, zero
automation flags) -- Playwright never drives it during login, so the captcha
never sees an automation signal. Playwright only attaches afterward, via
connect_over_cdp(), purely to read out the already-authenticated session's
cookies -- it never navigates or interacts with the login/captcha flow itself.

USAGE:
  py nexus_login_capture.py --launch
    Spawns a real Chrome window (remote-debugging-port enabled, but otherwise
    a completely normal launch) pointed at nexusmods.com. In that window,
    by hand: register (if you don't have a throwaway account yet) or log in,
    then go to account -> content preferences and enable "Show adult content".
    Leave the window open when done.

  py nexus_login_capture.py --export
    Run this after --launch and after you've finished logging in / enabling
    adult content in that window. Connects to the already-running Chrome via
    its debug port and saves the session to nexus_auth_state.json. Does NOT
    close the browser -- close it yourself once this prints success.

Produces: ../data/nexus/nexus_auth_state.json -- this is session/credential
data, never commit it (already covered by data/ in .gitignore).
================================================================================
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "nexus"
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_STATE_FILE = DATA_DIR / "nexus_auth_state.json"
PROFILE_DIR = DATA_DIR / "_login_capture_chrome_profile"
START_URL = "https://www.nexusmods.com/"
CDP_PORT = 9222

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("Could not find chrome.exe in the usual install locations -- "
                      "edit CHROME_CANDIDATES in this script with the correct path.")


def launch():
    chrome = find_chrome()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # No --enable-automation, no Playwright launch() -- a bare subprocess spawn
    # is indistinguishable from a human double-clicking the Chrome icon, aside
    # from the debug port (which by itself is not an automation signal any
    # captcha provider checks -- it's a developer-tools feature, not a
    # bot-detection flag).
    subprocess.Popen([
        chrome,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        START_URL,
    ])
    print(f"Launched Chrome (debug port {CDP_PORT}, profile dir {PROFILE_DIR}).")
    print("In that window, by hand:")
    print("  1. Register a throwaway account (or log into one you already made).")
    print("  2. Go to account -> content preferences and enable 'Show adult content'.")
    print("  3. Leave the window open, then run:  py nexus_login_capture.py --export")


def export():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        except Exception as e:
            raise SystemExit(
                f"Could not connect to Chrome on port {CDP_PORT}: {e}\n"
                "Make sure you ran --launch first and that window is still open."
            )
        context = browser.contexts[0]
        context.storage_state(path=str(AUTH_STATE_FILE))
        print(f"Saved session to {AUTH_STATE_FILE}")
        print("You can close the Chrome window now.")
        browser.close()


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--launch", action="store_true", help="Spawn a real Chrome window for manual login")
    group.add_argument("--export", action="store_true", help="Export the logged-in session after manual login")
    args = parser.parse_args()

    if args.launch:
        launch()
    else:
        export()


if __name__ == "__main__":
    main()
