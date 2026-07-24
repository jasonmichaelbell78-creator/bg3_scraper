#!/usr/bin/env python3
"""
nexus_collections_scraper.py  v1.0  (2026-07-24, see CLAUDE.md "Collections" section)
================================================================================
Collections (curated mod bundles) on Nexus -- confirmed live 2026-07-24 as
fully scriptable via the official GraphQL API, and meaningfully simpler than
nexus_deep_comments.py: no browser automation, no Cloudflare challenge, no
cookies, NO AUTH AT ALL. 87 total BG3 collections confirmed live.

Endpoint -- easy to get wrong, found by reading the docs page's own "API
Endpoints" section rather than guessing from the host name:
  https://graphql.nexusmods.com only serves the interactive SpectaQL docs
  page (GET) -- POSTing a query there 405s and looks like a dead end but
  isn't one. The real query endpoint is a v2 path on the REST v1 host:
  https://api.nexusmods.com/v2/graphql

Two queries used here:
  collectionsV2(filter: {gameDomain: [{value: "baldursgate3"}]}, count, offset)
    -- list/search. `count`/`offset` pagination confirmed live (not Relay
    cursor-based like the comments field below) -- tested offset=3 against
    the 87-collection list, no overlap with the first page. Only 87 exist,
    so a single request comfortably covers all of them, but this still
    paginates properly in case that grows past one page later.
  collection(slug, domainName)
    -- full detail for one collection: name, summary, category, downloads,
    latestPublishedRevision { modCount modFiles { file { modId name version
    uid } optional } } for the mod list (confirmed: returns the ~complete
    list in one shot, no separate pagination needed -- tested against a
    1016-mod collection, got 1015 modFiles entries back, not truncated at
    any round page-size boundary), and commentThread { comments(first,
    after) { totalCount pageInfo { hasNextPage endCursor } nodes { id body
    createdAt likesCount creator { name } parent { id } } } } for comments.

  Comments pagination gotcha found live: comments() is Relay-style cursor
  pagination (first/after + pageInfo), NOT offset-based -- `comments(offset:
  N)` errors with "Field 'comments' doesn't accept argument 'offset'".
  ALWAYS pass forward the exact endCursor the API just returned for you --
  a manually-reconstructed or mismatched-request-size cursor can silently
  desync (tested: an endCursor taken from a first:3 request, when replayed
  as `after` on a separate request, came back with hasNextPage:false and
  zero nodes, even though the collection has 3205 total comments -- almost
  certainly because a handful of top comments are shown out of strict
  chronological order, e.g. bumped for recent reply activity, so their
  cursors don't line up with the underlying sort the rest of the connection
  uses). Sequential same-size pagination (first:50, then first:50 after:
  <the endCursor THAT SAME response just gave back>, repeated) was verified
  live across 6 pages / 300 comments with zero duplicate IDs -- that's the
  pattern this script follows: never cache or recompute a cursor, only ever
  forward the one just received.

  Second, bigger gotcha, found live testing this exact script against
  "Difficulty, Immersion, Quality" (3205 reported total comments): the
  thread-level `comments()` connection only enumerates ROOT/top-level
  comments -- walking it fully returned exactly 1076 comments, every single
  one with `parent: null`, then correctly reported hasNextPage: false. The
  gap (3205 - 1076 = 2129) is replies, which live under a SEPARATE, per-
  comment `replies(first, after)` connection (confirmed live: comment
  247542's `replies { totalCount }` = 4, none of which appear anywhere in
  the root `comments()` walk). A standalone `comment(commentId: ID!)` query
  also exists and exposes that same `replies` connection directly, which is
  what this script uses to walk each root comment's replies (and recurse
  into any reply that itself reports a nonzero `replies.totalCount`, since
  nothing in the schema guarantees replies can't nest more than one level
  deep, even though every sample checked live topped out at depth 1). This
  costs one extra request per comment that actually HAS replies (the large
  majority have zero and are skipped immediately via the free `replies {
  totalCount }` field returned alongside each root comment) -- cheap in
  practice, since most comments in a thread are unreplied-to.

  requests' default User-Agent works fine against this endpoint (verified
  live) -- unlike Python's urllib, which got a blanket 403 (untested further
  since requests is what this project already uses everywhere else).

USAGE:
  py nexus_collections_scraper.py
  py nexus_collections_scraper.py --limit 5      # test on first 5 collections
  py nexus_collections_scraper.py --resume       # skip collections already fully done
================================================================================
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# See modio_deep_collections.py for why: Windows' cp1252 console can crash on an
# emoji in a collection/comment name mid-print. Codespace/Linux runs are already
# UTF-8 by default (this check is a no-op there), but this keeps the script safe
# if ever run locally too.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
GRAPHQL_URL = "https://api.nexusmods.com/v2/graphql"
GAME_DOMAIN = "baldursgate3"
REQUEST_DELAY = 0.3
LIST_PAGE_SIZE = 100
COMMENTS_PAGE_SIZE = 100

META_FILE = BASE_DIR / "nexus_collections_meta.jsonl"
MODS_FILE = BASE_DIR / "nexus_collections_mods.jsonl"
COMMENTS_FILE = BASE_DIR / "nexus_collections_comments.jsonl"

LIST_QUERY = """
query($count: Int!, $offset: Int!) {
  collectionsV2(filter: {gameDomain: [{value: "%s"}]}, count: $count, offset: $offset) {
    totalCount
    nodes { slug name summary }
  }
}
""" % GAME_DOMAIN

COMMENT_FIELDS = "id body createdAt likesCount creator { name } parent { id } replies { totalCount }"

DETAIL_QUERY = """
query($slug: String!, $domainName: String!) {
  collection(slug: $slug, domainName: $domainName) {
    name
    summary
    category { name }
    totalDownloads
    latestPublishedRevision {
      revisionNumber
      modCount
      modFiles { optional file { modId name version uid } }
    }
    commentThread {
      comments(first: %d) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}
""" % (COMMENTS_PAGE_SIZE, COMMENT_FIELDS)

COMMENTS_PAGE_QUERY = """
query($slug: String!, $domainName: String!, $after: String!) {
  collection(slug: $slug, domainName: $domainName) {
    commentThread {
      comments(first: %d, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}
""" % (COMMENTS_PAGE_SIZE, COMMENT_FIELDS)

# Root comments() only enumerates top-level comments -- replies live under each
# comment's own `replies` connection, reachable via this standalone query (see
# module docstring's "second, bigger gotcha").
REPLIES_QUERY = """
query($commentId: ID!) {
  comment(commentId: $commentId) {
    replies(first: %d) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}
""" % (COMMENTS_PAGE_SIZE, COMMENT_FIELDS)

REPLIES_PAGE_QUERY = """
query($commentId: ID!, $after: String!) {
  comment(commentId: $commentId) {
    replies(first: %d, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}
""" % (COMMENTS_PAGE_SIZE, COMMENT_FIELDS)


def gql(session: requests.Session, query: str, variables: dict) -> dict:
    resp = session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def list_all_collections(session: requests.Session) -> list[dict]:
    collections = []
    offset = 0
    while True:
        data = gql(session, LIST_QUERY, {"count": LIST_PAGE_SIZE, "offset": offset})
        batch = data["collectionsV2"]["nodes"]
        collections.extend(batch)
        offset += len(batch)
        time.sleep(REQUEST_DELAY)
        if not batch or offset >= data["collectionsV2"]["totalCount"]:
            break
    return collections


def fetch_replies_recursive(session: requests.Session, comment_id: str) -> list[dict]:
    """Fetches ALL replies of one comment via the standalone comment(commentId)
    query, then recurses into any reply that itself reports replies.totalCount > 0.
    Only called for comments already known (via the free `replies { totalCount }`
    field on the parent fetch) to actually have at least one reply."""
    replies = []
    after = None
    while True:
        if after is None:
            data = gql(session, REPLIES_QUERY, {"commentId": comment_id})
        else:
            data = gql(session, REPLIES_PAGE_QUERY, {"commentId": comment_id, "after": after})
        r = data["comment"]["replies"]
        replies.extend(r["nodes"])
        if not r["pageInfo"]["hasNextPage"]:
            break
        after = r["pageInfo"]["endCursor"]
        time.sleep(REQUEST_DELAY)

    nested = []
    for reply in replies:
        if (reply.get("replies") or {}).get("totalCount", 0) > 0:
            time.sleep(REQUEST_DELAY)
            nested.extend(fetch_replies_recursive(session, reply["id"]))
    return replies + nested


def fetch_collection_detail(session: requests.Session, slug: str) -> tuple[dict, list[dict]]:
    """Returns (collection_detail_without_comments, all_comments -- roots + all
    nested replies at any depth). Walks root-comment pagination starting from the
    first page already embedded in the detail query, then continuing via
    COMMENTS_PAGE_QUERY -- always using the endCursor the API just returned, never
    a cached/reconstructed one (see module docstring). For each root comment with
    replies, separately walks its full reply tree via fetch_replies_recursive."""
    data = gql(session, DETAIL_QUERY, {"slug": slug, "domainName": GAME_DOMAIN})
    coll = data["collection"]
    if coll is None:
        raise FileNotFoundError(f"collection {slug} not found")

    thread = coll.pop("commentThread")
    comments = thread["comments"]["nodes"]
    page_info = thread["comments"]["pageInfo"]

    while page_info["hasNextPage"]:
        time.sleep(REQUEST_DELAY)
        page_data = gql(session, COMMENTS_PAGE_QUERY,
                         {"slug": slug, "domainName": GAME_DOMAIN, "after": page_info["endCursor"]})
        page_comments = page_data["collection"]["commentThread"]["comments"]
        comments.extend(page_comments["nodes"])
        page_info = page_comments["pageInfo"]

    all_comments = list(comments)
    for c in comments:
        if (c.get("replies") or {}).get("totalCount", 0) > 0:
            time.sleep(REQUEST_DELAY)
            all_comments.extend(fetch_replies_recursive(session, c["id"]))

    return coll, all_comments


def load_done_slugs() -> set[str]:
    done = set()
    if META_FILE.exists():
        with open(META_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done.add(json.loads(line)["slug"])
    return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N collections (0 = all)")
    parser.add_argument("--resume", action="store_true", help="Skip collections already fully recorded")
    args = parser.parse_args()

    session = requests.Session()

    print("Listing all BG3 collections...")
    collections = list_all_collections(session)
    print(f"Found {len(collections)} collections")

    done_slugs = load_done_slugs() if args.resume else set()
    todo = [c for c in collections if c["slug"] not in done_slugs]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Already done (resume): {len(done_slugs)}")
    print(f"Processing: {len(todo)}")

    mods_mode = "a" if MODS_FILE.exists() else "w"
    comments_mode = "a" if COMMENTS_FILE.exists() else "w"
    meta_mode = "a" if META_FILE.exists() else "w"

    written_mods = written_comments = 0
    consecutive_failures = 0
    CONSECUTIVE_FAILURE_LIMIT = 5

    with open(MODS_FILE, mods_mode, encoding="utf-8") as mods_out, \
         open(COMMENTS_FILE, comments_mode, encoding="utf-8") as comments_out, \
         open(META_FILE, meta_mode, encoding="utf-8") as meta_out:

        for i, coll_stub in enumerate(todo, 1):
            slug, name = coll_stub["slug"], coll_stub.get("name", "?")
            now = datetime.now(timezone.utc).isoformat()
            try:
                detail, comments = fetch_collection_detail(session, slug)
            except FileNotFoundError as e:
                print(f"[{i}/{len(todo)}] {name} ({slug}): {e}, skipping")
                meta_out.write(json.dumps({"slug": slug, "_fetched_at": now, "_status": "not_found"},
                                            ensure_ascii=False) + "\n")
                meta_out.flush()
                continue
            except Exception as e:
                consecutive_failures += 1
                print(f"[{i}/{len(todo)}] {name} ({slug}) FAILED: {e}")
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    print(f"\n{consecutive_failures} consecutive failures -- stopping early. "
                          f"Re-run with --resume once whatever broke is resolved.")
                    break
                continue

            consecutive_failures = 0

            mod_files = (detail.get("latestPublishedRevision") or {}).get("modFiles") or []
            for mf in mod_files:
                f = mf.get("file") or {}
                mods_out.write(json.dumps({
                    "collection_slug": slug,
                    "mod_id": f.get("modId"),
                    "mod_name": f.get("name"),
                    "version": f.get("version"),
                    "uid": f.get("uid"),
                    "optional": mf.get("optional"),
                    "_fetched_at": now,
                }, ensure_ascii=False) + "\n")
            mods_out.flush()
            written_mods += len(mod_files)

            if comments:
                for c in comments:
                    creator = c.get("creator") or {}
                    parent = c.get("parent") or {}
                    comments_out.write(json.dumps({
                        "collection_slug": slug,
                        "comment_id": c.get("id"),
                        "body": c.get("body"),
                        "created_at": c.get("createdAt"),
                        "likes_count": c.get("likesCount"),
                        "creator_name": creator.get("name"),
                        "parent_comment_id": parent.get("id"),
                        "_fetched_at": now,
                    }, ensure_ascii=False) + "\n")
            else:
                comments_out.write(json.dumps({"collection_slug": slug, "_fetched_at": now, "_status": "no_comments"},
                                                ensure_ascii=False) + "\n")
            comments_out.flush()
            written_comments += len(comments)

            revision = detail.get("latestPublishedRevision") or {}
            meta_out.write(json.dumps({
                "slug": slug,
                "name": detail.get("name"),
                "summary": detail.get("summary"),
                "category": (detail.get("category") or {}).get("name"),
                "total_downloads": detail.get("totalDownloads"),
                "revision_number": revision.get("revisionNumber"),
                "mod_count": revision.get("modCount"),
                "comments_total_count": len(comments),
                "_fetched_at": now,
            }, ensure_ascii=False) + "\n")
            meta_out.flush()

            print(f"[{i}/{len(todo)}] {name} ({slug}): {len(mod_files)} mods, {len(comments)} comments")

    print(f"\nDone. {written_mods} mod rows, {written_comments} comment rows written.")
    print(f"  {META_FILE}\n  {MODS_FILE}\n  {COMMENTS_FILE}")


if __name__ == "__main__":
    main()
