# PC P2 validation — 2026-11-06

Branch: `feat/pc-routes-manifest`, based on `f4fe255`.
Single worker; no child agents used.

## Implementation

- Transactional `CREATE TABLE IF NOT EXISTS` for routes, ordered route devices and received manifests, integrated with the existing schema migration and backup mechanism.
- Route CRUD, registry selection and manual additions, editable order/removal, confirmed deletion, and UTF-8 QR payload capped at 1,500 bytes including `SOTUKEN-ROUTE:`.
- Authenticated route list/detail endpoints and manifest POST with JSON validation, overwrite by inspection ID, upload-equivalent body size limit and total read deadline.
- SHA-256 matching against existing reading hashes and received images before OCR. Received image hashes are cached by path, byte size and nanosecond modification time, so unchanged images are not rehashed on each status request.
- Record tab includes manifest-only inspections, reception state/missing filenames, route progress, and separate phone missing/extra claims. Actual received photos override contradictory claims.
- Optional `route_id` travels through sidecar normalization, upload validation, DB writes/reads, late sidecars, reprocessing, CSV and JSONL.
- A separately launched receiver can select the same DB with `--db`; default remains `manager.db` in the working directory.

## Verification

Python: `C:\卒研\git_stk\sotuken\venv\Scripts\python.exe`.

- Full suite: `python -m unittest discover -s tests -q` (final result recorded below).
- Added unit/integration tests in `test_routes_manifest.py`, `test_routes_receiver.py` and `test_routes_ui.py`: route CRUD/order/validation, QR size, manifest overwrite/validation, complete/partial/late SHA matches, raw received files before OCR and cache invalidation, actual-photo precedence over missing/extra, legacy readings, route metadata propagation, HTTP auth/404/invalid JSON/limits/deadline, and Streamlit form CRUD/manifest-only inspection display.
- Streamlit AppTest runs the complete app and exercises route creation, edit, confirmed deletion and the record-tab state display.
- A real Streamlit server was started on port 18572; an isolated `agent-browser` session opened both the route and record tabs successfully. Screenshots were inspected locally.
- `git -c core.whitespace=cr-at-eol diff --check` passes. The override accounts for the pre-existing tracked CRLF file `tests/test_export.py`; its original line endings were preserved.

## Existing test expectations necessarily updated

No assertions were removed, relaxed or skipped.

| File / test | Old → new |
|---|---|
| `tests/test_export.py` / `TestExportToCsv.test_writes_header_and_rows` | 15 CSV fields → 16; append `route_id` to header and one empty field to each legacy row |
| `tests/test_export.py` / `TestExportToCsv.test_empty_list_writes_header_only` | Header appends `route_id` |
| `tests/test_export.py` / `TestExportToJsonl.test_export_to_jsonl` | Expected key sequence appends `route_id` (25 → 26 keys) |
| `tests/test_inspection_filter.py` / `InspectionFilterTest.test_combined_filter_options_and_exports` | Last two CSV keys `inspection_id, inspection_name` → last three including `route_id` |
| `tests/test_sidecar.py` / `TestSidecarDeviceMetadata.test_to_dict_includes_new_optional_fields` | Exact dictionary adds `route_id: None` |
| `tests/test_storage_schema.py` / `TestStorageSchema.test_memory_database_does_not_back_up` | 26 → 27 reading columns |
| `tests/test_storage_schema.py` / `TestStorageSchema.test_old_schema_preserves_values_and_adds_nullable_columns_and_devices` | Eight → nine appended NULL fields; legacy values unchanged |

## Not performed / remaining scope

Android device communication, camera QR decoding, Android route snapshots and offline persistence were not exercised; Android is assigned separately. USB extraction and OCR behavior were not modified. No merge was performed.
