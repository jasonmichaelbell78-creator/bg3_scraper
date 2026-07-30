# mod.io Comments Dataset — Manifest

Covers `modio_comments_merged.jsonl`, the dataset to use going forward. Machine-readable version: `manifest_modio_comments.json`. Per-mod counts for the 115 refreshed mods: `manifest_modio_per_mod.csv`.

## Scrapers and run timestamps

| Script | Version | Completed (America/Chicago) | Purpose |
|---|---|---|---|
| `bg3_scraper.py` | — | 2026-07-10 06:18:16 -05:00 | Base sweep: all mod metadata/files/deps/events/team + comments (comments truncated by a pagination bug — see below) |
| `modio_deep_comments.py` | v1.0 | 2026-07-21 12:30:47 -05:00 | Re-fetches full comment threads for truncated mods |
| `modio_merge_comments.py` | v1.1 | 2026-07-21 12:54:17 -05:00 | Merges + deduplicates into the final dataset (v1.0 of this script, run 12:31:00, lacked dedup and is superseded/discarded) |

## Mod-selection rule

A mod qualifies for deep-refresh if its comment row count in the base sweep's `modio_comments_fullsweep.jsonl` is **≥ 100**.

Rationale: the base sweep made one unpaginated request per mod at the API's default page size (100). Any mod at/above that count is provably truncated; any mod below it is provably complete — a single default-size page can't be truncated if the true total is under the page size.

**115 of 4,361 mods-with-comments matched** (out of 8,145 total mods in the base sweep; 3,784 have zero comments).

## Displayed vs. captured count

For all 115 refreshed mods, captured count equals mod.io's own `result_total` API field **by construction** — the pagination loop only exits when `offset >= result_total`, so it can't stop short. This was independently spot-checked against the live page for mod 5714166 ("DTO: Otherworldly Archetypes"): the page displayed "Discussion 129", captured count was 129 — exact match.

Per-mod captured counts for all 115 mods are in `manifest_modio_per_mod.csv`.

**Open gap**: the other 4,246 untouched mods' totals were *not* independently re-verified against mod.io's live counts — completeness there is inferred from the selection-rule logic above, not empirically confirmed per mod. Closing this would take ~4,246 lightweight `result_total`-only requests (no content re-fetch); not yet done.

## Pagination and authentication

- **Endpoint**: `https://mod.io/v1/games/@baldursgate3/mods/@<mod-slug>/comments` — an undocumented web-frontend host, different from the official `api.mod.io` / `g-6715.modapi.io` host the base sweep used.
- **Params**: `_offset` (0, then += batch size each call), `_sort=-id`.
- **Stop condition**: batch is empty, or `offset >= result_total`.
- **Auth**: no API key. Cloudflare bot-management session cookies (`__cf_bm`, `__cflb`, `_cfuvid`) minted by one headless-Chromium (Playwright) page load of `mod.io/g/baldursgate3`, then reused via a `requests.Session()` for every subsequent call, plus custom headers `x-modio-game: 6715`, `x-modio-mod: <id>`, `x-modio-origin: web`. Auto re-warms on HTTP 401 — **0 re-warms needed** during the actual run.
- Rate limit: 0.4s delay between paginated requests.

## Capture outcome

| Scope | Fully captured | Partial | Failed | Skipped | Inaccessible |
|---|---|---|---|---|---|
| Base sweep — mod metadata (8,145 mods) | 8,145 | 0 | 0 | 0 | 0 |
| Deep-refresh — targeted 115 mods | 115 | 0 | 0 | 0 | 0 |

Base sweep's internal checkpoint (`modio_progress.json`) `result_total` matches `modio_mods_full_sweep.jsonl`'s row count exactly (8,145 = 8,145), so its final state is complete. Per-mod fail/skip counts from *earlier retries within* that sweep weren't separately logged — only final-state completeness is known.

## Deduplication (the 128 duplicate IDs)

- **Key**: comment `id` (globally unique across mod.io, independent of `mod_id`).
- **Rule**: keep the first occurrence per `id` in file-processing order (untouched-old rows processed before new-refresh rows); drop later duplicates.
- **Where the duplicates came from**: `modio_comments_fullsweep.jsonl` itself had 184 duplicate-id groups (368 rows) — a repeated-write artifact from the base sweep's resume/retry logic not being idempotent at the comment level. Sampled pairs (e.g. ids `1543954`, `1531957`) were verified **byte-identical** across every field (content, timestamp, karma, user) — confirming plain repeated writes, not conflicting revisions.
- **Why 128, not 184**: 56 of the 184 groups belonged to mods among the 115 refreshed, so those old rows (dupes included) were already discarded wholesale during mod-replacement, before dedup logic even ran. The remaining 128 groups belonged to untouched mods and were caught by the id-based dedup.
- **Verified fixed**: `modio_comments_merged.jsonl` now has 76,043 rows and 76,043 unique ids — zero duplicates remain.

## The two schema cohorts (why some rows have fewer fields)

The merged file mixes rows from two different mod.io endpoints. Same underlying comment data both times — the difference is purely which endpoint's response shape was captured.

| | Cohort A (old/untouched) | Cohort B (deep-refresh) |
|---|---|---|
| Rows | 44,777 | 31,266 |
| Mods covered | 4,246 | 115 |
| Source | `modio_comments_fullsweep.jsonl` — same original sweep run as Cohort B's mod-list source, **not** a separate/different scraper run | `modio_comments_deep_refresh.jsonl` |
| Host | `g-6715.modapi.io` (api_key auth) | `mod.io/v1` (cookie auth) |
| Extra field(s) | `_mod_id` (scraper bookkeeping) | `game_name`, `game_name_id`, `resource_name`, `resource_name_id`, `resource_type` |

**Answer to "is the 44,905-field-poor cohort a separate run or different source?"** — No. (Note: this cohort is 44,777 rows after the dedup fix, not 44,905 — that earlier number was pre-dedup.) It's the same base sweep, same script, same run — just an older/different API host whose response omits five denormalized fields the newer web endpoint happens to include.

## Source files and hashes

| File | Role | Rows | SHA-256 |
|---|---|---|---|
| `modio_mods_full_sweep.jsonl` | mod metadata + slug lookup | 8,145 | `a414b8b8b0543d288724655d1555ba41be4fd43d1c162f47d5c25cdc1cdb7759` |
| `modio_comments_fullsweep.jsonl` | base comment sweep (untouched on disk) | 56,417 | `1170262c52137e86b36d29fb623dde788597611d1ef9258a1587369cd5811f0a` |
| `modio_comments_deep_refresh.jsonl` | deep-refresh output | 31,266 | `501e73c77d45903625f6d53283b295bda095096f4bc8306d17a68702d313b491` |
| **`modio_comments_merged.jsonl`** | **final merged + deduplicated — use this one** | **76,043** | `bcd546e99781a0005390e6e3367460d0f34930f0d35a11863a39689d4155893a` |
