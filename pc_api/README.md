# PC API verification process

Run from the same explicit data working directory as the owner. The API never
starts the receiver, USB service, or inbox watcher, and never initializes the DB.

```powershell
python -m pc_api.server --db C:\data\manager.db --incoming-dir C:\data\incoming --images-dir C:\data\images --overlays-dir C:\data\overlays --static-dir C:\build\dist --internal-key-file C:\private\owner-key.txt
```

`--incoming-dir`, `--images-dir` and `--overlays-dir` are all required (the
launch is refused with a usage message when any is missing or empty, when a root
is a drive root, or when `--db` does not exist: the API never creates the DB).
They form the image allowlist, not a search path. Out-of-root absolute paths are
rejected; absolute stored paths within these roots are supported. Relative
stored paths resolve against the process working directory (run from the same
data directory as the owner). Roots are not required to exist yet.

Where the existing app writes (pass the same folders):

| Flag | Existing location |
|---|---|
| `--incoming-dir` | `manager.receiver.get_default_incoming_dir()` = `<repo>/incoming` (the owner uses the same default; `run_pc.py`/receiver `--incoming` can override it) |
| `--images-dir` | `manager.ingest.ingest_image(images_dir=...)` via `store_image`; `manager/watch_inbox.py` default `<repo>/images`; Streamlit manual upload uses `images` under the working directory. DB `image_path` is stored as an absolute path |
| `--overlays-dir` | `save_overlay(...)`; `manager/watch_inbox.py` default `<repo>/overlays`; Streamlit manual upload uses `overlays` under the working directory |

Ports: `--port` (default `8766`) is the API listener, always bound to `127.0.0.1`.
The Host/Origin check uses the actual port, so the browser must open
`http://127.0.0.1:<port>`; change it only when 8766 is taken. `--owner-port`
(default `8767`) must match the owner's management port. The static directory is
optional; a small readiness page is served when its index is absent.

The verification launcher must obtain `Owner.internal_key` from the owner it
starts. It can construct `PCAPI(..., internal_key=owner.internal_key)` directly,
or pass that key to the standalone process through a private UTF-8 file using
`--internal-key-file`. Keep that file readable only by the current OS user and
remove it after startup. No existing owner key-discovery endpoint is added.
The standalone `pc_api.owner` command does not export its key: launcher wiring
belongs to the next verification step. Never print the key or embed it in HTML.

For React step (3):

* Read `document.querySelector('meta[name="pc-token"]').content` from the served
  HTML. Add `X-PC-Token` to every `/api/v1` fetch, including image fetches.
  Fetch image bytes and create/revoke Blob URLs; a plain image `src` cannot add
  this header. Do not store the token in URLs, logs, or localStorage.
* Use the same origin, `http://127.0.0.1:8766`. The server provides no CORS
  permission. Bundle scripts locally; the CSP excludes external scripts and
  inline scripts. Only index HTML, JS, CSS, PNG, SVG, and ICO static files are
  served. No SPA history fallback is implemented in this initial API step.
* Image IDs are opaque and restart-scoped (`<db id>-<o|v>-<HMAC>`; do not parse
  them). Reload HTML after restarting the API. Unexpected server errors return
  `500 internal_error` with no detail; do not retry them automatically.
* Pairing POST accepts an empty body or `{}`; DELETE returns 204. Do not retry
  either mutation automatically. Hide QR immediately on owner-unavailable or
  local expiry, and use the owner instance ID to notice owner restart.
* Runtime and USB use the owner's `/internal/status`; USB defaults are supplied
  when disabled. API shutdown leaves the owner and watcher running.
* The API has its own reader (`ReadOnlyStorage`: `mode=ro`, `query_only`, 250 ms
  busy timeout, one short connection per request; detail/image requests read a
  single row by id). It never constructs `Storage`. Its column list mirrors
  `Storage.get_all_readings(include_raw=False)`; a test compares the two against
  `MeterManager.get_history`, so a schema change in Storage fails that test
  rather than silently diverging. Rows keep DB id descending order;
  `filter_readings` supplies existing date/filter rules. Nonfinite public numbers
  become null. Production `journal_mode` is `delete`; the API never changes it
  (busy while ingest commits returns `503 db_busy`, retry the GET).

This step does not measure end-to-end React latency or make a Go/No-Go decision.
Use fixed temporary data for step (3), and measure DB-commit-to-render and
receive-to-render separately as specified in the design.
