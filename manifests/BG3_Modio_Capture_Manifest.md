# Raw mod.io API Capture — Manifest
**Prepared:** 2026-07-21, in response to ChatGPT's request for full manifest before source import
**Archive:** `bg3_modio_data.zip`
**Archive SHA-256:** `9e73e347926677d765e67585b122fb5b39e949215f7d1c6ee96756a25c6f5cce`
**Archive size:** 34,077,631 bytes

## Per-file manifest (all six data files, plus the progress tracker)

| Filename | Size (bytes) | SHA-256 |
|---|---|---|
| `modio_mods_full_sweep.jsonl` | 68,606,373 | `a414b8b8b0543d288724655d1555ba41be4fd43d1c162f47d5c25cdc1cdb7759` |
| `modio_comments_fullsweep.jsonl` | 59,964,241 | `1170262c52137e86b36d29fb623dde788597611d1ef9258a1587369cd5811f0a` |
| `modio_deps_fullsweep.jsonl` | 36,758,641 | `341a20d3aeefe6c43faeb2481f6f1ea8d05e11de4d08fd1ce50f09e0e25a3f8c` |
| `modio_files_fullsweep.jsonl` | 23,358,675 | `7b1bb9c5dca54ec1a10b5d5642ef7283a49bf37dfb2feb0c1d44fc4ea64bfdff` |
| `modio_team_fullsweep.jsonl` | 5,830,944 | `8f349b98053871b110117679543b5665c75d8816c02eacf0961dfd57acdcf6a8` |
| `modio_events_fullsweep.jsonl` | 3,893,420 | `cefbd4c38bff782eea3d12063a56e8df1ab0dc8ce1c8e79f9acbef82ace15b9a` |
| `modio_progress.json` | 73,857 | `a0ffce51b15ded4fc8b76545881e19003159c9addab5e313011b53742e41ecd0` |

All filenames are original — nothing renamed.

## Capture/run metadata — stated plainly, including what's *not* present

Unlike the Nexus capture (which bundles a distinct `run_summary.json` with dates and explicit skip-reason counts), **the mod.io capture has no separate narrative run-summary file.** `modio_progress.json` is a resumability tracker only — it contains `completed_offsets`, `completed_mod_details`, and `result_total: 8145`. There is no bundled README describing the run.

- **Result total per the tracker:** 8,145 mods (matches the distinct-ID count independently verified earlier this session).
- **Effective capture-date proxy:** file modification timestamps from when this archive was first extracted in this session, ~July 10, 2026. This is inferred from file metadata, not a stated field inside the capture itself — flagging that distinction rather than presenting it as a verified capture date.
- **Known pagination limit, independently verified, not stated anywhere in the capture's own metadata**: `modio_comments_fullsweep.jsonl` caps at up to ~100 comments per mod. Confirmed directly against the raw file for at least one mod (Containers Extended, real mod.io ID 4213146) — exactly 100 in the raw file, while the live mod.io site currently shows 211 for that same mod. This is a real, load-bearing limitation for anything downstream that treats comment counts as complete.
- **No per-record capture timestamp field was found in the mods or comments records during earlier inspection** (unlike the Nexus capture's `_fetched_at` field) — meaning within-file recency can't be determined record-by-record from the mod.io side the way it can for Nexus.

## What this manifest does not claim

This manifest describes what's in the archive and its checksums. It makes no claim about ingestion readiness, schema compatibility, or which of the six files should be ingested first — that sequencing is explicitly ChatGPT's call per the accepted work delineation, and the proposed order (mods/listings → team → deps/events → files after `mod_files` design → comments after comment-evidence schema design) is accepted as stated, not contested here.
