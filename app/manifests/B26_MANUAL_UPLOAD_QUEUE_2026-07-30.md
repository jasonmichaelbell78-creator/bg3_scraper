# Manual B26 Drive upload queue — 2026-07-30

The Drive connector accepts files no larger than 104,857,600 bytes. Upload each item manually to `BG3/CATALOG/B26/` (folder ID `1TRHmFhHAGYp_fSELWOBSMZ4dCHIUa4US`) without changing its filename. After upload, verify the Drive filename and byte size; then calculate or otherwise verify its SHA-256 against the value below and enter the returned Drive ID in `DRIVE_PARITY_MANIFEST_2026-07-30.json`.

| File | Bytes | SHA-256 | Required Drive path | Post-upload verification |
|---|---:|---|---|---|
| `BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` | 876,204,032 | `cb37e0392b7bdb0b06f8095c44b8352363610999498ff4803e07411df3187775` | `BG3/CATALOG/B26/BG3_Reference_Catalog_v1_1_Working_B26_Phase1_Coverage_candidate.db` | exact name, 876,204,032 bytes, SHA-256 matches |
| `C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip` | 200,722,310 | `50772e0059e78bc3f9f21e7ccdf80156b1c92ce436baa27b95554ff156ae7ef0` | `BG3/CATALOG/B26/C4_Semantic_B26_Phase1_Coverage_Full_Snapshot.zip` | exact name, 200,722,310 bytes, SHA-256 matches |
