# PC inspection filter validation (2026-11-06)

Branch: `feat/pc-inspection-filter`

## Behavior

- Optional `inspection_id` / `inspection_name` are normalized at sidecar load and DB write. Invalid values do not reject a photograph.
- Existing databases receive two nullable columns and an `inspection_id` index through the existing backed-up migration.
- The first non-null name for an inspection ID is retained. Earlier unnamed records of that ID receive that name. Writes serialize name selection and insertion in one transaction.
- Initial ingest, late sidecars and reprocessing preserve inspection metadata. A late sidecar cannot replace an already assigned inspection ID.
- The records tab offers all / no inspection / each named inspection with its record count. Device and date filters compose with the inspection filter; CSV and JSONL export that same filtered list and append the new fields.
- Full-history rows show the inspection name (ID fallback). The existing latest-reading table keeps its columns.
- Selecting a specific inspection displays its full device roster before the other filters: one row per device ID, missing IDs grouped together, source labels combined when photographs have different sources, latest captured timestamp, and a separate missing-ID photograph count.
- Existing sources are `sidecar_qr`, `sidecar_manual`, `pc_qr`; the roster also recognizes `qr` and `manual`. Unknown/missing source is shown as none because PC QR already has an explicit stored value.

## Checks

Interpreter: `C:\卒研\git_stk\sotuken\venv\Scripts\python.exe`.

- Added tests: 9 passed, including Streamlit AppTest selection, combined filters, roster visibility and actual CSV/JSONL output counts.
- Final full run: **562 tests passed in 88.173 seconds** (553 existing tests + 9 added tests), exit code 0. Log: `.cache/pc-inspection-filter/unittest-final.log`.
- Initial full run: 559 tests, 6 failures, all exact legacy column/key expectations that cannot include the requested new fields without updates. The coordinator subsequently approved only the necessary schema expectation changes; assertions, test counts and meaning are retained.
- Whitespace check: `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` passed (the original `test_export.py` blob uses CRLF).
- Real Streamlit server started on port 8539; isolated browser session opened the records tab and visually confirmed the inspection selector. Synthetic round selection and roster values were checked in the browser accessibility tree (two photographs for one device, one photograph with no device ID). Screenshot: `.cache/pc-inspection-filter/selected.png`; initial empty records screenshot: `.cache/pc-inspection-filter/records.png` (local artifacts, not committed).
- Browser and server were stopped; the synthetic records were deleted from the worktree's ignored database.

Not performed: Android-to-PC end-to-end transfer, production-data migration, visual inspection of every roster row, manual browser downloads. These are covered only by the corresponding unit/AppTest paths where applicable.

No child agents were used. No merge or vault changes were made.

## Existing expectations updated with coordinator approval

| File | Test | Old → new |
| --- | --- | --- |
| `tests/test_export.py` | `TestExportToCsv.test_writes_header_and_rows` | CSV header ends at `image_rel` → append `inspection_id,inspection_name`; both data rows gain exactly two empty trailing fields; expected line count remains 3 |
| `tests/test_export.py` | `TestExportToCsv.test_empty_list_writes_header_only` | Same two header fields appended; expected line count remains 1 |
| `tests/test_export.py` | `TestExportToJsonl.test_export_to_jsonl` | Exact ordered key list appends `inspection_id`, `inspection_name`; record count and value assertions unchanged |
| `tests/test_sidecar.py` | `TestSidecarDeviceMetadata.test_to_dict_includes_new_optional_fields` | Exact dictionary gains `inspection_id: None`, `inspection_name: None` |
| `tests/test_storage_schema.py` | `TestStorageSchema.test_old_schema_preserves_values_and_adds_nullable_columns_and_devices` | New nullable tail `(None,) * 6` → `(None,) * 8`; original 18 columns remain exactly equal |
| `tests/test_storage_schema.py` | `TestStorageSchema.test_memory_database_does_not_back_up` | Exact column count 24 → 26; backup assertion unchanged |
