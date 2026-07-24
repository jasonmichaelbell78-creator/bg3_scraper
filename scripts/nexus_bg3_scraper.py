#!/usr/bin/env python3
"""
nexus_bg3_scraper.py  v1.5
================================================================================
Nexus Mods – Baldur's Gate 3 – English Language Mods
================================================================================
Pulls ALL English-language mods for BG3 from Nexus Mods V1 REST API.

WHAT IT PULLS per mod:
  Metadata    : name, summary, description, author, version, category,
                timestamps, endorsements, downloads, status, picture_url, tags
  Files       : file_id, name, version, category, size, description,
                upload date, changelog text
  Changelogs  : full version history
  Comments    : all pages (text, author, date, reply_to, likes)

STRATEGY:
  Phase 1 – Recent activity sweep:
    Pull mod IDs from updated (1d/1w/1m), latest_added, trending
  Phase 2 – Full historical sweep:
    Walk mod IDs 1 → MAX_MOD_ID sequentially
    404s (deleted) and 403s (hidden) silently skipped

RESUME SAFE:
  progress.json is updated after every single mod.
  If Codespaces times out or you Ctrl+C, run with --resume to continue
  exactly where you left off. Output files are appended, never overwritten.

OUTPUT (./bg3_nexus_data/):
  mods_metadata.jsonl     – one JSON object per mod
  mods_files.jsonl        – one JSON object per file
  mods_changelogs.jsonl   – one JSON object per mod changelog
  mods_comments.jsonl     – one JSON object per comment
  run_summary.json        – stats
  progress.json           – resume checkpoint

USAGE:
  pip install requests tqdm
  python nexus_bg3_scraper.py --api-key "YOUR_KEY"
  python nexus_bg3_scraper.py --api-key "YOUR_KEY" --limit 20   # test
  python nexus_bg3_scraper.py --api-key "YOUR_KEY" --resume     # continue

FLAGS:
  --output-dir PATH     Output directory (default: ./bg3_nexus_data)
  --delay FLOAT         Seconds between requests (default: 0.6)
  --limit INT           Max mods to write; 0 = unlimited (default: 0)
  --max-mod-id INT      Highest mod ID to check in historical sweep (default: 26000)
  --skip-files          Skip file enumeration
  --skip-changelogs     Skip changelog pull
  --skip-comments       Skip comment pull
  --resume              Resume from progress.json
  --phase1-only         Only run recent activity sweep, skip historical
================================================================================
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

# ── Constants ──────────────────────────────────────────────────────────────────

GAME_DOMAIN       = "baldursgate3"
API_BASE          = "https://api.nexusmods.com/v1"
USER_AGENT        = "BG3-Nexus-Scraper/1.5 (personal research)"
RATE_LIMIT_BUFFER = 50
DEFAULT_RETRY     = 65

NON_ENGLISH_RANGES = re.compile(
    r"[\u0400-\u04FF"   # Cyrillic
    r"\u0600-\u06FF"   # Arabic
    r"\u0900-\u097F"   # Devanagari
    r"\u3000-\u9FFF"   # CJK + Japanese kana
    r"\uAC00-\uD7AF"   # Korean Hangul
    r"\u0590-\u05FF"   # Hebrew
    r"\u0E00-\u0E7F"   # Thai
    r"]"
)

NON_ENGLISH_TAGS = {
    "russian", "chinese", "japanese", "korean", "german", "french",
    "spanish", "italian", "portuguese", "polish", "czech", "hungarian",
    "turkish", "arabic", "ukrainian", "dutch", "romanian", "swedish",
    "translation", "traduccion", "tradução", "traduction",
}

# ── Filters ────────────────────────────────────────────────────────────────────

def is_non_english(text: str) -> bool:
    return bool(NON_ENGLISH_RANGES.search(text or ""))

def has_non_english_tag(tags: list) -> bool:
    for tag in tags:
        if isinstance(tag, dict):
            name = (tag.get("name") or "").lower()
        elif isinstance(tag, str):
            name = tag.lower()
        else:
            name = ""
        if any(ne in name for ne in NON_ENGLISH_TAGS):
            return True
    return False

def is_english_mod(mod: dict) -> bool:
    for field in ("name", "summary", "description"):
        if is_non_english(mod.get(field) or ""):
            return False
    if has_non_english_tag(mod.get("tags") or []):
        return False
    return True

# ── Rate limiter ───────────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, base_delay: float = 0.6):
        self.base_delay       = base_delay
        self.hourly_remaining = 2000
        self.hourly_limit     = 2000
        self.daily_remaining  = 20000
        self.daily_limit      = 20000
        self.hourly_reset     = None
        self.requests_made    = 0

    def update(self, headers: dict):
        try:
            self.hourly_limit     = int(headers.get("x-rl-hourly-limit",     self.hourly_limit))
            self.hourly_remaining = int(headers.get("x-rl-hourly-remaining", self.hourly_remaining))
            self.daily_limit      = int(headers.get("x-rl-daily-limit",      self.daily_limit))
            self.daily_remaining  = int(headers.get("x-rl-daily-remaining",  self.daily_remaining))
            self.hourly_reset     = headers.get("x-rl-hourly-reset")
        except Exception:
            pass

    def status(self) -> str:
        return (f"H:{self.hourly_remaining}/{self.hourly_limit} "
                f"D:{self.daily_remaining}/{self.daily_limit} "
                f"reqs:{self.requests_made}")

    def throttle(self):
        time.sleep(self.base_delay)
        if self.hourly_remaining < RATE_LIMIT_BUFFER:
            wait = 65
            if self.hourly_reset:
                try:
                    reset = datetime.fromisoformat(
                        self.hourly_reset.replace("+0000", "+00:00")
                    )
                    wait = max(10, (reset - datetime.now(timezone.utc)).total_seconds() + 5)
                except Exception:
                    pass
            tqdm.write(
                f"\n⚠  Hourly limit low ({self.hourly_remaining} left). "
                f"Sleeping {wait:.0f}s…"
            )
            time.sleep(wait)

# ── API client ─────────────────────────────────────────────────────────────────

class NexusClient:
    def __init__(self, api_key: str, rl: RateLimiter):
        self.rl      = rl
        self.session = requests.Session()
        self.session.headers.update({
            "apikey":     api_key,
            "User-Agent": USER_AGENT,
            "Accept":     "application/json",
        })

    def _get(self, url: str, params: dict = None, retries: int = 3) -> dict | list | None:
        for attempt in range(retries):
            self.rl.throttle()
            try:
                resp = self.session.get(url, params=params, timeout=30)
                self.rl.update(resp.headers)
                self.rl.requests_made += 1

                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception:
                        return {}

                elif resp.status_code == 204:
                    return {}

                elif resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", DEFAULT_RETRY))
                    tqdm.write(f"\n  429 — sleeping {wait}s…")
                    time.sleep(wait)

                elif resp.status_code in (404, 403):
                    return None  # deleted or hidden — silent skip

                elif resp.status_code == 401:
                    tqdm.write("\n  ❌ 401 Unauthorized — API key rejected.")
                    sys.exit(1)

                else:
                    tqdm.write(f"\n  HTTP {resp.status_code}: {url}")
                    if attempt < retries - 1:
                        time.sleep(5 * (attempt + 1))

            except requests.RequestException as e:
                tqdm.write(f"\n  Network error: {e}")
                if attempt < retries - 1:
                    time.sleep(10)

        return None

    def validate(self) -> dict | None:
        url = f"{API_BASE}/users/validate.json"
        self.rl.throttle()
        resp = self.session.get(url, timeout=30)
        self.rl.update(resp.headers)
        self.rl.requests_made += 1
        print(f"   validate.json → HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   User    : {data.get('name')}")
            print(f"   Premium : {data.get('is_premium?')}")
            print(f"   Hourly  : {resp.headers.get('x-rl-hourly-remaining')}/{resp.headers.get('x-rl-hourly-limit')}")
            print(f"   Daily   : {resp.headers.get('x-rl-daily-remaining')}/{resp.headers.get('x-rl-daily-limit')}")
            return data
        print(f"   ❌ HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    def get_updated_ids(self, period: str) -> list[int]:
        data = self._get(
            f"{API_BASE}/games/{GAME_DOMAIN}/mods/updated.json",
            params={"period": period},
        )
        if isinstance(data, list):
            return [int(e["mod_id"]) for e in data if "mod_id" in e]
        return []

    def get_latest_added(self) -> list[int]:
        data = self._get(f"{API_BASE}/games/{GAME_DOMAIN}/mods/latest_added.json")
        if isinstance(data, list):
            return [int(m["mod_id"]) for m in data if "mod_id" in m]
        return []

    def get_trending(self) -> list[int]:
        data = self._get(f"{API_BASE}/games/{GAME_DOMAIN}/mods/trending.json")
        if isinstance(data, list):
            return [int(m["mod_id"]) for m in data if "mod_id" in m]
        return []

    def get_mod(self, mod_id: int) -> dict | None:
        return self._get(f"{API_BASE}/games/{GAME_DOMAIN}/mods/{mod_id}.json")

    def get_files(self, mod_id: int) -> list:
        data = self._get(f"{API_BASE}/games/{GAME_DOMAIN}/mods/{mod_id}/files.json")
        if isinstance(data, dict):
            return data.get("files", [])
        return []

    def get_changelogs(self, mod_id: int) -> dict | None:
        return self._get(f"{API_BASE}/games/{GAME_DOMAIN}/mods/{mod_id}/changelogs.json")

    def get_comments(self, mod_id: int) -> list:
        """Fetches all comment pages for a mod."""
        all_comments = []
        page = 1
        while True:
            data = self._get(
                f"{API_BASE}/games/{GAME_DOMAIN}/mods/{mod_id}/comments.json",
                params={"page": page, "limit": 100, "sort": "ASC"},
            )
            if not data:
                break
            if isinstance(data, list):
                all_comments.extend(data)
                if len(data) < 100:
                    break
                page += 1
            elif isinstance(data, dict):
                comments = data.get("comments", [])
                all_comments.extend(comments)
                if len(comments) < 100:
                    break
                page += 1
            else:
                break
        return all_comments

# ── JSONL writer ───────────────────────────────────────────────────────────────

class JsonlWriter:
    def __init__(self, path: Path):
        self._fh = open(path, "a", encoding="utf-8")

    def write(self, obj: dict):
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self):
        self._fh.close()

# ── Progress ───────────────────────────────────────────────────────────────────

def load_progress(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"done_ids": [], "historical_next": 1}

def save_progress(path: Path, done: set, historical_next: int):
    path.write_text(
        json.dumps({"done_ids": list(done), "historical_next": historical_next}),
        encoding="utf-8",
    )

# ── Process one mod ────────────────────────────────────────────────────────────

def process_mod(mod_id, client, args, w_meta, w_file, w_cl, w_comments, stats):
    mod = client.get_mod(mod_id)

    if mod is None:
        stats["unavailable"] += 1
        return

    if not is_english_mod(mod):
        stats["skipped_lang"] += 1
        return

    now = datetime.now(timezone.utc).isoformat()

    # Files
    if not args.skip_files:
        files = client.get_files(mod_id)
        for f in files:
            w_file.write({"mod_id": mod_id, **f, "_fetched_at": now})
        stats["files"] += len(files)

    # Changelogs
    if not args.skip_changelogs:
        cl = client.get_changelogs(mod_id)
        if cl:
            w_cl.write({"mod_id": mod_id, "changelogs": cl, "_fetched_at": now})
            stats["changelogs"] += 1

    # Comments
    if not args.skip_comments:
        comments = client.get_comments(mod_id)
        for c in comments:
            w_comments.write({"mod_id": mod_id, **c, "_fetched_at": now})
        stats["comments"] += len(comments)

    # Metadata
    mod["_fetched_at"] = now
    w_meta.write(mod)
    stats["written"] += 1

# ── Main ───────────────────────────────────────────────────────────────────────

def scrape(args):
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    prog_file = out / "progress.json"

    rl     = RateLimiter(base_delay=args.delay)
    client = NexusClient(args.api_key, rl)

    print("🔑 Validating API key…")
    user = client.validate()
    if not user:
        print("❌ Auth failed. Exiting.")
        sys.exit(1)
    print(f"✅ Authenticated as {user.get('name')}\n")

    state           = load_progress(prog_file) if args.resume else {"done_ids": [], "historical_next": 1}
    done_ids: set   = set(state.get("done_ids", []))
    historical_next = state.get("historical_next", 1)

    w_meta     = JsonlWriter(out / "mods_metadata.jsonl")
    w_file     = JsonlWriter(out / "mods_files.jsonl")
    w_cl       = JsonlWriter(out / "mods_changelogs.jsonl")
    w_comments = JsonlWriter(out / "mods_comments.jsonl")

    stats = {
        "written": 0, "skipped_lang": 0, "unavailable": 0,
        "files": 0, "changelogs": 0, "comments": 0,
    }

    limit     = args.limit if args.limit > 0 else float("inf")
    hit_limit = False

    def _do(mod_id: int) -> bool:
        nonlocal hit_limit
        if mod_id in done_ids:
            return True
        process_mod(mod_id, client, args, w_meta, w_file, w_cl, w_comments, stats)
        done_ids.add(mod_id)
        if stats["written"] >= limit:
            hit_limit = True
            return False
        return True

    # Phase 1 — Recent activity
    print("📋 Phase 1 — Recent activity sweep…")
    phase1_ids: set[int] = set()
    for period in ("1d", "1w", "1m"):
        ids = client.get_updated_ids(period)
        print(f"   updated ({period})   : {len(ids):,}")
        phase1_ids.update(ids)
    ids = client.get_latest_added()
    print(f"   latest_added    : {len(ids):,}")
    phase1_ids.update(ids)
    ids = client.get_trending()
    print(f"   trending        : {len(ids):,}")
    phase1_ids.update(ids)

    todo_p1 = sorted(phase1_ids - done_ids)
    print(f"\n   Unique new IDs  : {len(todo_p1):,}")
    print(f"   Already done    : {len(done_ids):,}\n")

    for mod_id in tqdm(todo_p1, desc="Phase 1", unit="mod", dynamic_ncols=True):
        if not _do(mod_id):
            break
        save_progress(prog_file, done_ids, historical_next)

    print(f"\n   Phase 1 done — {stats['written']:,} English mods written\n")

    # Phase 2 — Full historical sweep
    if not args.phase1_only and not hit_limit:
        print(f"📚 Phase 2 — Historical sweep (IDs {historical_next:,} → {args.max_mod_id:,})…")
        print(f"   404s and 403s silently skipped.\n")

        for mod_id in tqdm(
            range(historical_next, args.max_mod_id + 1),
            desc="Phase 2",
            unit="id",
            dynamic_ncols=True,
        ):
            historical_next = mod_id + 1
            if not _do(mod_id):
                break
            if mod_id % 50 == 0:
                save_progress(prog_file, done_ids, historical_next)

        save_progress(prog_file, done_ids, historical_next)
        print(f"\n   Phase 2 done — {stats['written']:,} total English mods written\n")

    # Close writers
    w_meta.close()
    w_file.close()
    w_cl.close()
    w_comments.close()

    summary = {
        "finished_at":      datetime.now(timezone.utc).isoformat(),
        "mods_written":     stats["written"],
        "skipped_language": stats["skipped_lang"],
        "unavailable":      stats["unavailable"],
        "files_written":    stats["files"],
        "changelogs":       stats["changelogs"],
        "comments":         stats["comments"],
        "api_requests":     rl.requests_made,
        "hourly_remaining": rl.hourly_remaining,
        "daily_remaining":  rl.daily_remaining,
    }
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("═" * 56)
    print("✅  Complete")
    print("═" * 56)
    print(f"  English mods written   : {stats['written']:,}")
    print(f"  Skipped (non-English)  : {stats['skipped_lang']:,}")
    print(f"  Unavailable/deleted    : {stats['unavailable']:,}")
    print(f"  Files written          : {stats['files']:,}")
    print(f"  Changelogs written     : {stats['changelogs']:,}")
    print(f"  Comments written       : {stats['comments']:,}")
    print(f"  API requests used      : {rl.requests_made:,}")
    print(f"  Hourly remaining       : {rl.hourly_remaining}/{rl.hourly_limit}")
    print(f"  Daily remaining        : {rl.daily_remaining}/{rl.daily_limit}")
    print(f"\n  Output: {out.resolve()}")
    print("═" * 56)

# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Nexus Mods BG3 scraper — English mods, files, changelogs, comments.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--api-key",          required=True)
    p.add_argument("--output-dir",       default="./bg3_nexus_data")
    p.add_argument("--delay",            type=float, default=0.6)
    p.add_argument("--limit",            type=int,   default=0,
                   help="Max English mods to write (0 = unlimited)")
    p.add_argument("--max-mod-id",       type=int,   default=26000,
                   help="Highest mod ID to check in historical sweep")
    p.add_argument("--skip-files",       action="store_true")
    p.add_argument("--skip-changelogs",  action="store_true")
    p.add_argument("--skip-comments",    action="store_true")
    p.add_argument("--resume",           action="store_true",
                   help="Continue from progress.json — safe after timeout or Ctrl+C")
    p.add_argument("--phase1-only",      action="store_true",
                   help="Only run recent activity sweep, skip historical")
    args = p.parse_args()
    scrape(args)

if __name__ == "__main__":
    main()
