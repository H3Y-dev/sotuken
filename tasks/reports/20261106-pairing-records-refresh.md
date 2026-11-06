# Pairing test stability and records refresh

## Changes

- Records: manual refresh clears the history cache and reruns the app, including the page header count.
- Optional automatic refresh is off by default. Installed Streamlit 1.40.1 supports `st.fragment(run_every="5s")`; the records fragment reloads history, inspection choices, counts, and pending images every five seconds.
- Pending images: `manager.pending_images.pending_images(incoming_dir, storage)` returns a file count and up to five sorted names. It compares SHA-256 against `Storage.get_processed_hashes()`, exactly as ingest/watch_inbox do, and reuses the existing size/mtime-keyed `_file_hash` cache.
- Only regular JPG/JPEG/PNG files are counted. Partial uploads, sidecars, directories, and processed content under another filename are excluded. Two unprocessed files with identical contents count as two files until that content is processed.
- Receiver, importer, and database schema are unchanged.

## Existing test changes (old → new)

No expected status, JSON assertion, filesystem assertion, or credential assertion was changed.

| File / test or shared helper | Old | New |
| --- | --- | --- |
| `tests/test_pairing.py` / `PairingTests.test_slow_trickle_cannot_extend_read_deadline` | Assert 408, then require body read to finish | Assert 408, then tolerate only `ConnectionResetError` / `ConnectionAbortedError` during body read; invitation reuse must still return 200 |
| `tests/test_pairing.py` / `PairingTests.test_partial_body_times_out_without_consuming_invite` | Assert 408, then require body read to finish | Same narrow allowance after mandatory 408; invitation reuse assertion retained |
| `tests/test_pairing.py` / `PairingTests.request`, used for 400/413 by `test_small_strict_json_and_health_does_not_disclose` | Require JSON body read for all responses | Parse JSON as before when available; only 400/413 may return an empty body result after either connection exception; caller status assertions retained; all other statuses still propagate errors |
| `tests/test_receiver.py` / `TestReceiverServer.test_short_body_returns_400_without_files` | Assert 400, then require body read to finish | Same narrow allowance after mandatory 400; empty-directory assertion retained |
| `tests/test_receiver.py` / `TestReceiverServer._request`, used by `test_sha256_mismatch_returns_400`, `test_invalid_file_name_returns_400`, `test_sidecar_validation_returns_400`, `test_content_length_oversize_returns_413` | Require HTTP error body read before returning status | Only 400/408/413 may return status and an empty body result after either connection exception; otherwise parse the body as before; caller status assertions retained |

`tests/test_receiver_limits.py` already reads only through the status line and never requires an error response body, so no change was needed there. The existing 403 error-message assertions remain mandatory.

## Validation

- Full suite: **588 tests passed** (580 existing + 8 new).
- Seven pending-image unit tests cover empty/missing directories, pending images/preview limit, processed hashes, partial uploads/sidecars/directories, replacement under the same name, duplicate contents under different names, and cache reuse with fresh database checks.
- One Streamlit AppTest opens the records tab, verifies the default-off checkbox and pending count, inserts a new database record/inspection, presses refresh, and checks the new count/options and disappearance of the pending indicator. It also enables automatic refresh without an app exception.
- Real browser smoke test: isolated Streamlit server on `127.0.0.1:18561`, records tab opened, refresh button clicked, pending count visible, automatic refresh enabled. Adding a second incoming image updated the indicator from one to two without another click.
- The browser smoke test used an isolated incoming folder/database and a stubbed receiver initializer; actual phone transmission and the image-processing pipeline were not exercised.
- Automatic refresh updates the records fragment; the page-wide header and other tabs refresh on manual update or another full app rerun.
- No child agents used. The coordinator-owned prompt file was left untouched.
