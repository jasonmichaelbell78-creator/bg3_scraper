# BG3 Mod Scraper and Reference Catalog

This repository contains the runnable BG3 Nexus/mod.io scraper code and
non-sensitive provenance manifests. Large scraped data is local-only and
ignored by Git.

## Local layout

- `scripts/` — scraper, merger, and utility scripts.
- `data/` — local scraped output, organized by platform and purpose.
- `manifests/` — tracked, non-sensitive provenance and migration records.
- `catalog_workspace/` — local B26 validation workspace; ignored by Git.
- `Downloads/` — immutable local intake; ignored by Git.
- `archive/` — local archival material, including the stale manual Drive mirror.

Google Drive is the authoritative shared record. The human-readable catalog is
in Drive's `BG3/00_CURRENT_CATALOG`; the immutable B26 machine baseline is in
`BG3/01_MACHINE_BASELINE`. Do not treat the local archived Drive mirror as
authoritative.
