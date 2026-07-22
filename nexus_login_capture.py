#!/usr/bin/env python3
"""
nexus_login_capture.py
================================================================================
One-time interactive helper. Opens a real (headed) Chromium window and lets
you log into Nexus Mods by hand -- whatever a real login needs (password,
captcha, email verification) -- then saves the resulting session as a
Playwright storage_state file. nexus_deep_comments.py can reuse that session
via --auth-state to see adult-content-gated mods, which an anonymous session
can't: the page simply omits thread_id for them, so fetch_all_comments()
correctly (but unhelpfully) returns [] rather than the real comment count.
See CLAUDE.md for the "known gap: NSFW-tagged mods return 0 comments" note.

Run this on a machine/network that can actually reach nexusmods.com --
your home connection, already confirmed working, not the Codespace (which
only exists to get *bulk scraping* traffic off the Mimecast-monitored work
device; this one-time interactive login doesn't need that at all).

Use a throwaway account, not your main one -- this session gets reused by
an automated script afterward.

After logging in, also go to your account's content-preferences page and
enable "Show adult content" -- the whole point of this capture is a session
that can actually see NSFW-gated mods.

USAGE:
  py nexus_login_capture.py
  (log in and enable adult content in the window that opens, then press
  Enter in this terminal once both are done)

Produces: nexus_auth_state.json -- this is session/credential data, never
commit it (already added to .gitignore).
================================================================================
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
AUTH_STATE_FILE = BASE_DIR / "nexus_auth_state.json"
START_URL = "https://www.nexusmods.com/"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        # Same fix as nexus_deep_comments.py's open_browser_context() -- a vanilla
        # launch() reports navigator.webdriver = True, which Cloudflare checks
        # directly, and login pages tend to be watched even more closely than
        # normal page loads.
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")
        page = context.new_page()
        page.goto(START_URL, wait_until="domcontentloaded")

        print("A browser window has opened. In it:")
        print("  1. Click 'Log in' and sign into the throwaway account.")
        print("  2. Go to your account's content preferences and enable 'Show adult content'.")
        print("  3. Come back here and press Enter once both are done.")
        input()

        context.storage_state(path=str(AUTH_STATE_FILE))
        print(f"Saved session to {AUTH_STATE_FILE}")
        browser.close()


if __name__ == "__main__":
    main()
