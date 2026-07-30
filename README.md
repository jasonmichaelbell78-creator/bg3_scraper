# BG3 Mod Scraper and Reference Catalog

This repository contains runnable BG3 Nexus/mod.io scraper code and non-sensitive provenance manifests. Large scraped data remains local-only and ignored by Git.

## Local layout

- `app/scripts/` — scraper, merger, and utility scripts.
- `app/manifests/` — tracked, non-sensitive provenance, checksums, and upload queues.
- `data/` — active local scraped output: `collections/`, `modio/`, and `nexus/`.
- `catalog/B26/` — local immutable B26 database, snapshot, and validation receipt; ignored by Git.
- `Downloads/` — immutable local intake; ignored by Git.
- `archive/` — local archival material, including the stale manual Drive mirror and the compressed completed-control history.

Google Drive is the authoritative shared record. Its active structure is `BG3/{CATALOG,SOURCES,SCRAPER,ARCHIVE}`. The B26 standalone database and snapshot are documented in the manual-upload queue for `BG3/CATALOG/B26`; do not treat the local archived Drive mirror as authoritative.
