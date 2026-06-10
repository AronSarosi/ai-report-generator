# Security, cost & robustness audit (2026-06-10)

A four-track audit of the deployed app (security ×2, cost/abuse, data-robustness, code
quality) run before opening the public link. Findings and the fixes applied.

## Fixed

### Critical
- **Arbitrary file write / RCE via upload filename** (`app/main.py`). The API wrote
  uploads to `tempfile.gettempdir() / file.filename` — an absolute or `../` filename
  could overwrite files under `/app` (which the container owns), i.e. remote code
  execution on restart. **Fix:** the temp name is now generated server-side
  (`upload_<uuid><ext>`), the extension is allowlisted, and the raw file is always
  deleted after load.
- **Concurrent requests clobbered each other's data** (`app/main.py`). The API loaded
  every upload into one shared `data` table, so two simultaneous users could get each
  other's numbers. **Fix:** each request gets a unique table (`req_<uuid>`) and its own
  output directory; both are cleaned up afterwards.

### High
- **No usage caps on the public API.** `/generate` and `/chat` ran billable LLM calls
  with no limit. **Fix:** both now enforce the same caps as the UI plus a **global daily
  ceiling** across all clients (`src/limits.py`), so total spend per day is bounded no
  matter how many IPs hit it. Returns HTTP 429 when exceeded.
- **Cost amplification on wide datasets.** A 50-column upload became ~50 report sections
  ≈ up to ~200 LLM calls. **Fix:** dimensions per report capped (`_MAX_DIMS=6`), bars per
  chart capped (`_MAX_BARS=15`), an absolute dimension-cardinality ceiling in the
  profiler, a per-call `max_tokens` cap, a row cap (`MAX_ROWS`) and a 25 MB upload limit
  on both surfaces.
- **Dirty headers crashed the loader** (duplicate/empty column names → uncaught 500 on
  the API). **Fix:** headers are cleaned at load — whitespace trimmed, blanks filled,
  duplicates de-duped, and double-quotes (the SQL-identifier-injection vector) stripped.
- **SQL identifier injection via column names.** Uploaded headers flowed unescaped into
  f-string SQL; a header containing `"` could break out of the quoted identifier. **Fix:**
  the double-quote stripping above neutralises the vector at the source.

### Medium / robustness
- **Internal errors leaked to clients** (raw exception text). **Fix:** the API logs the
  detail server-side and returns a generic message; intentional guardrails (e.g. "no
  numeric column") still return their clear 422.
- **Numbers-as-text were silently ignored** (`$1,234`, `12%`, `1,000`). Very common in
  real exports, and it meant the user's actual metric vanished. **Fix:** text columns
  that are ≥95% numeric once `$ , %` are stripped are coerced to numbers at load.
- **`money()` produced `$nan` and `$1000000000.00M`.** **Fix:** NaN guard + `B`/`T`
  magnitude branches.
- **NULL / blank dimension groups rendered as the literal `None`.** **Fix:** mapped to
  `(blank)`.
- **`leader_share` could read `5,000,000%`** when the period total was ≤ 0. **Fix:**
  share is `n/a` unless the total is positive.
- **SQLite connection leak** in `src/limits.py` (`with conn` commits but never closes).
  **Fix:** wrapped in `contextlib.closing`.

## Accepted / documented (not changed)

- **IP-based caps are spoofable** via `X-Forwarded-For`. This is acknowledged as a soft
  lead-magnet gate; the **global daily ceiling and the OpenAI account spend cap are the
  real backstops**. Set a hard monthly limit in the OpenAI dashboard
  (platform.openai.com → Billing → Limits) — that is the one true ceiling for a personal
  key and lives outside this repo.
- **Cross-tenant reads via Talk2Data.** The read-only SQLite connection blocks writes but
  not reads of other transient uploaded tables; a crafted *question* could read another
  visitor's data. Low impact for a demo (uploads are transient and non-sensitive, and the
  per-request table is dropped immediately). Full isolation would use a per-session
  database file — noted as future hardening.
- **Prompt injection via dataset cells** can put attacker text into report prose, but the
  verifier strips any unapproved `$`/`%` figure and the model has no tools, so impact is
  cosmetic.
- **`defusedxml` for the PPTX template parser** (`src/branding.py`) — recommended hardening
  against XML-bomb DoS on the brand-template upload; deferred.

## Validation

- `pytest` deterministic suite extended to 67 tests (header cleaning, numeric coercion,
  `money()` branches, the two-layer usage caps, `drop_table`). All green.
- `scripts/run_torture.py` runs the full pipeline on 12 deliberately messy datasets
  (missing values, currency-as-text, dirty/dup/unicode headers, no time column, no numeric
  column, huge cardinality, negatives/zeros, mixed types, single row, 20-dimension wide).
  Results + saved decks in `data/torture/out/` (`index.md`).
