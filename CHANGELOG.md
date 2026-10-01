# Changelog

All notable changes to the Business Card Scanner project will be documented in this file.

## [2.1.39] — 2026-10-01

### Fixed

- **Preview still showed the sliver after 2.1.38.** `/api/preview` carried its _own_ ~125-line copy of the gap-overlay inference (`_find_gap_positions` → regularize → rects), so the relative sliver filter and the ≥4-tile banner gate added to `_gap_detect_and_regularize` never reached it — scans were fixed, previews weren't. The duplicated block is replaced by a call to the shared function; when it yields nothing the preview draws the frame as one card instead of re-inferring a uniform grid, and the "Apply N×M grid" banner only fires for ≥4 tiles. Verified: two stacked cards → 2 boxes, no banner (synthetic test added; 373 total pass).

---

## [2.1.38] — 2026-10-01

### Fixed

- **Single-card photos were exploded into 4–8 fake cards in Automatic mode.** An audit over 95 archived originals showed every one-card phone photo (IMG_1658 → 8, IMG_2525 → 4, IMG_2628 → 7, IMG_8943 → 5, all identical aspects) being tiled by "infer a grid when fewer than 4 contours are found" rules at **three** layers, plus a fourth path on the server. The user's reported case — 2 cards previewed as 3 with a ~20px sliver and a bogus "Apply 3×1 grid" banner — is the same bug. Fixes, one per layer:
  - `card_processor.detect_cards`: removed the `<4 → split_image_grid` guess. Real contours are trusted; zero contours → the whole image is one card (a phone photo of one card is far likelier than an 8-card sheet with invisible edges). Grid stays an explicit user mode.
  - `ImprovedCardDetector`: a tiling may replace contour results only if it's a plausible sheet — ≥4 tiles that **don't span the frame** (full-width/height tiles are 1-D strips of one card cut along its printed rules). Crucially, `_detect_grid_by_gaps` is _edge-derived_: when it returns exactly 1 region and contours found ≤1, that's a confident "one card, here are its bounds" (it produced the correct crop on every single-card photo) and now wins. The blind `_uniform_grid_split` still runs on low counts — it legitimately recovers scanned sheets where contours under-find (Steinweg p1: 3 → 8) — but can no longer out-vote that confident single.
  - `server._gap_detect_and_regularize`: added a _relative_ sliver filter (drop tiles under 30% of median width/height). The old absolute 80px floor missed inter-card gutters on 4032px phone photos.
  - `server._process_with_refinement`: a gap-inferred tiling may override the detector only when it yields ≥4 tiles; a 2–3 tile result is the classic crease/shadow false split.
- Verified against the archive: all five single-card photos → exactly 1 region with card-like crops; every multi-card sheet unchanged (Steinweg 8/8, page_1_sample 5/5, IMG_1584 14, Comontation 6).

### Known residue

- Under-detection on dense sheets with vertically stacked cards (IMG_1544 7 of ~18, IMG_8706 7 of 14, YOUR_8CARD 5 of 8) — adjacent cards merge into one portrait-aspect contour. Different fix; candidate for a Jev plausibility judgment over the detection summary (count, aspects, image dims) before spending vision calls.
- 5 new deterministic tests (`tests/test_card_detection_rules.py`, synthetic images). 372 total pass.

---

## [2.1.37] — 2026-07-09

### Fixed

- **Per-card time was a hardcoded placeholder.** `server._contact_data_to_frontend` read `card.get("processing_time", 1.0)`, but nothing ever _set_ `processing_time` — so every card reported `1.0s` and the Scanner tab's "Avg time" was meaningless. `CardProcessor.process_single_card` now measures real wall-clock (QR detection + vision + repairs) and puts it on the card; the server default drops to `0.0` instead of a fake `1.0`.
- **The "via" badge always said "GLM-OCR", whatever model actually ran.** It was hardcoded — so after the qwen default (and especially after a not-installed substitution) the badge lied about which model produced the contact. `ScanResult` now carries `model_used` (set by `extract_with_fallback` to the model that _actually_ ran, post-fallback), threaded to the UI via the same `_`-prefixed stash pattern as `_qr_url`/`_detected_lang` (popped server-side, never reaches the saved contact). The badge now reads e.g. `qwen2.5vl:7b` or `QR + qwen2.5vl:7b`.
- Frontend `via` checks that compared against the literal `"QR + GLM-OCR"` now match on the `QR` prefix, so the "Via QR" stat and badge colour stay correct with any model name.

### Notes

- Verified on a real scan: `via: QR + qwen2.5vl:7b`, `time: 10.4s` (was `1.0s`), and `_model_used` confirmed absent from the saved contact. 367 tests pass.

---

## [2.1.36] — 2026-07-09

### Fixed

- **Scans returned 0 cards when the selected model wasn't installed.** Regression from 2.1.28: the model-routing fix applied the requested model to the provider config **unconditionally**, overriding the Ollama provider's own "fall back to any installed vision model" logic. So when `qwen2.5vl:7b` (the 2.1.31 default) was absent from Ollama, every scan 404'd (`model 'qwen2.5vl:7b' not found`), all providers failed, and the UI showed `0 Cards found`. `extract_with_fallback` now only forces the requested model **if it's actually installed** (tag-tolerant: `glm-ocr` matches `glm-ocr:latest`); otherwise it keeps the installed model `check_availability()` picked and logs the substitution loudly with the `ollama pull` command to fix it. Providers that can't enumerate their models (cloud) get the benefit of the doubt.
- **`Avg time` showed `NaNs`** on a zero-card result (divide-by-zero); now shows `—`.
- 5 new tests (uninstalled → fallback, installed → honoured, tag-tolerant match, helper unit, unknown-lister benefit-of-doubt). 367 total pass.

---

## [2.1.35] — 2026-07-08

### Added

- **Duplicate-contact detection** ("Duplicates" button, Contacts tab). Exact-email dupes already merge on save; this catches the rest — the same person scanned twice with a different or typo'd email. Conservative by design: a pair is flagged only on **same email**, or **matching name AND (matching company OR a shared phone number)**. "Matching name" needs ≥2 shared accent-folded tokens with one name a subset of the other (so "Gilberto Costa" ~ "Gilberto Moura Costa"), which avoids first-name-only collisions. Found 2 real pairs in the live data (Fabiola Souza `.com`/`.com.br`; André/Andre Marra — accent + different emails) with zero false positives.
  - `ContactsRepository.find_duplicates()` (union-find, so A~~B~~C collapse into one group) + `merge_contacts(target, sources)`. Merge is **non-destructive** on the kept record (fills only its empty fields), respects locked-field protection (a locked target's name/email are never overwritten), inherits a card image/source file if missing, then deletes the sources. Regenerates the VCF.
  - Endpoints: `GET /api/contacts/duplicates`, `POST /api/contacts/merge`.
  - Review modal: each group shows both records side by side (email · company · phone · added-date), a radio to pick which to keep (defaults to the older one), lock badges, and Merge / "Not duplicates" per group. **Nothing merges without a click.**
- 20 new tests (detection evidence rules, conservative rejections, transitive grouping, merge fill/protect/delete semantics). 362 total pass. UI verified end-to-end in the preview (both real pairs render; merge intentionally not run on live data).

---

## [2.1.34] — 2026-07-08

### Added

- **User-editable company alias list** — closes the last "bucket 2" benchmark miss (`BNB` vs "Banco do Nordeste") and any org short-form that string logic can't derive. `temp/company_aliases.json` is a JSON list-of-lists, each inner list a set of equivalent names:
  ```json
  [
    ["BNB", "Banco do Nordeste", "Banco do Nordeste do Brasil"],
    ["Citibank", "Citi", "Citigroup"]
  ]
  ```
  A company field matches ground truth when the verified value and the extracted value both fall in the same group (with normalized equality + containment inside the group, so "Banco do Nordeste" matches the fuller alias entry). Loaded by `field_matches` for the `company` field only, cached by file mtime so edits are picked up without a restart, and fails safe to `[]` if the file is missing or malformed.
  - Seeded on this machine with the three known cases (BNB / Citibank / MME). A committed `company_aliases.example.json` documents the format for fresh installs (the live file lives in the gitignored `temp/`, like the contacts store).
- 12 new tests (alias matching both directions, in-group containment, no cross-group leak, company-field-only, missing/malformed file handling). 352 total pass.

### Notes

- Bucket 2 is now fully closeable: acronym + brand-prefix handle the derivable cases generically; the alias list handles the rest under your explicit control (no guessing, no false positives). Scoring-only — extraction untouched.

---

## [2.1.33] — 2026-07-08

### Changed

- **Benchmark now credits acronym / brand short-forms for Company** (the "bucket 2" cases from the last investigation). When a company is verified as a short form but the model reads the full legal name, two new matchers close the derivable ones:
  - **Acronym-of-initials** (`_acronym_match`): `"MME"` ↔ "Ministério de Minas e Energia" — the acronym is a subsequence of the significant words' initials (stopwords like _de/do/e_ skipped).
  - **Brand-prefix** (`_brand_prefix_match`): `"Citibank"` ↔ "Citi Treasury and Trade Solutions" — a single-token brand that is the ≥4-char first word of a longer name.
  - Applied to `company` only (not title). Guarded against flukes: short first words (`"San"` vs "Sandvik Mining"), wrong acronyms (`"ABC"` vs "Apple Inc"), and 1-char OCR errors (`"Maceló"`→"Maceió") all still count as misses.
- **Not closeable by string logic:** `"BNB"` vs "Banco do Nordeste" — the acronym is \*Banco do Nordeste **do Brasil\***, and the model dropped "do Brasil", so its output literally lacks the third letter. Left as a miss rather than adding a guess that would risk false positives; a per-org alias list is the honest way to force it if ever wanted.

### Notes

- 7 new tests; two 2.1.32 tests that asserted MME/Citibank as misses were updated to the new intended behavior. 343 total pass. Scoring-only; extraction untouched. Of the 4 bucket-2 company misses, 3 now score correctly.

---

## [2.1.32] — 2026-07-08

### Fixed

- **Benchmark under-scored Company** (~67% for the best model). Investigating the qwen misses showed most weren't extraction errors: the verified truth used a short form while the model read the full legal name — `"Inter Maritima"` vs `"Intermarítima Portos e Logística S.A."` (same name, different word breaks + legal suffix). Company/title matching now also does a **space-insensitive prefix match**, guarded to ≥4 chars on the shorter side. This credits the spacing case while correctly leaving genuine differences as misses: short acronyms (`"MME"` ↔ Ministério de Minas e Energia, `"BNB"` ↔ Banco do Nordeste), different divisions (`"Citibank"` ↔ "Citi Treasury and Trade Solutions"), and 1-char OCR errors (`"Maceló"` → "Maceió") all still count against the model — those reflect a real gap between the model's output and your verified data.

### Notes

- 5 new company-matching tests. 338 total pass. As with the name fix, this only changes benchmark _scoring_ — extraction and storage are untouched. Company extraction was already strong; the low number was mostly your own abbreviations vs the models' full legal names.

---

## [2.1.31] — 2026-07-08

### Changed

- **Default vision model is now `qwen2.5vl:7b`** (was `glm-ocr`). Driven by the benchmark against the user's own locked contacts: qwen won overall (~84% field accuracy — perfect email + website), while glm-ocr, though fastest, is OCR-only and weakest on full-contact fields. Updated every default site: scan endpoint, relaunch fallback, `AppConfig` (`vision_model` + `ollama_preload_model`), `CardProcessor` signatures, the Ollama provider config + `DEFAULT_VISION_MODELS` ordering, and the frontend picker default. The `VISION_MODELS` catalogue is reordered (qwen → minicpm-v → glm-ocr …) with speed/quality ranks and blurbs rewritten from the measured numbers.

### Fixed

- **Benchmark scored glm-ocr's names as 0% — a scorer bug, not a model failure.** glm-ocr (OCR-specialised) populates `firstName`/`lastName` and usually leaves `fullName` empty; the benchmark's Name column only read `fullName`. The real app already derives `fullName` from first+last (`_contact_to_api`), so those names show correctly in-app — the scorer just didn't replicate it. Name matching now checks both `fullName` and `firstName+lastName`, with token-subset logic so "Gilberto Costa" matches a fuller "Gilberto Moura Costa" and a first-name-only truth still matches. Re-running the benchmark will now show glm-ocr's true (much higher) name accuracy.

### Notes

- 5 new name-matching tests + config-default updates. 333 total pass. This does not change how the app extracts or stores names — only how the benchmark scores them.

---

## [2.1.30] — 2026-07-08

### Fixed

- **Contacts with `title: "Gerente=Manager, Diretor=Director, Presidente=President"`.** That string is a fragment of OUR extraction prompt — a Portuguese-glossary hint line — which weaker vision models copied verbatim into the title field instead of reading the card. Three-part fix:
  - The glossary line is gone from the prompt (replaced with "keep job titles exactly as printed, in their original language" — we never wanted translated titles anyway).
  - New `strip_prompt_echoes` post-processing pass: any field value containing a run of two or more `X=Y` glossary pairs (a pattern that never occurs on real cards) has the echo removed, keeping whatever legitimate text surrounds it. Runs first in the repair chain at all three post-processing sites. A single stray `=` (e.g. in notes) is left alone.
  - **Stored data scrubbed:** 4 contacts had the glossary as their title; cleared and their VCFs regenerated (backup written alongside, as always).
- 6 new tests, including a guard that the extraction prompt never contains the glossary again. 328 total pass.

---

## [2.1.29] — 2026-07-08

### Changed

- **zxing-cpp is now the primary QR decoder.** Modern C++ port of ZXing with official arm64 wheels and a pybind11 binding — structurally immune to the ctypes `restype` bug class that made pyzbar segfault libzbar. Decodes a full 9 MP card photo in ~50 ms with internal binarization (raw image first; the preprocessing variants only run if that yields nothing). Decode order: pyzbar (opt-in via `USE_PYZBAR=1`) → **zxing-cpp** → OpenCV ArUco → OpenCV basic. `zxing-cpp==3.1.0` added to requirements + hash-pinned lock (lock regenerated).
- **Contacts store hardened.** `temp/contacts_repository.json` was rewritten in place on every mutation with no locking — a crash mid-save could truncate the entire repository, and FastAPI's thread pool made concurrent mutations racy. Now: atomic writes (temp file + fsync + `os.replace`, so readers/crashes see old-or-new, never partial) and an RLock around every mutator (`add_contact`, `apply_field_updates`, `set_locked`, `remove_contact`, `update_contact`, `clear_all`).

### Added

- Tests: zxing round-trip through the full `QRReader` (synthetic QR via `cv2.QRCodeEncoder`: URL + vCard parsing, rect/polygon shape, blank-image no-op) and store safety (no temp litter, always-parseable JSON mid-mutation, 8-thread concurrent-add consistency). 322 total pass. Live-verified: the Mobiz HEIC scans with `qrUrl` populated via the new decoder and the server stays healthy.

---

## [2.1.28] — 2026-07-08

### Fixed

- **The model you picked in the UI was never actually used.** `CardProcessor.extract_contact` received `vision_model`, logged it, and dropped it — `ProviderFactory.extract_with_fallback` had no model parameter at all. Worse, the Ollama provider's `check_availability()` overwrites its configured model with _whichever vision model is currently loaded in Ollama's memory_ (a swap-cost optimisation). Net effect: scans and "Relaunch with model X" silently ran on the loaded model while history metadata recorded the requested one. **All past model comparisons are unreliable.** `extract_with_fallback` now accepts `model=` and applies it to the matching provider's config after the availability check (so the explicit request wins); `claude-*`/`gpt-*` strings route to their cloud providers, everything else to Ollama. Regression-tested.

### Added

- **Model benchmark against your verified contacts** ("Benchmark" button, Contacts tab). Your locked contacts are human-reviewed ground truth, and each carries the cropped card image it was extracted from. The benchmark re-runs extraction on those images with each selected model and scores field-level accuracy against the locked data — answering "which model should I default to?" with your own cards instead of vibes.
  - Backend: `utils/model_benchmark.py` (normalisation + scoring + item collection) and `POST /api/benchmark` (SSE progress, `POST /api/benchmark/stop` to cancel). QR data is deliberately excluded (pure vision comparison); the app's normal post-processing (CJK repair, permutation fix, title demotion) is included, so scores reflect what you actually get.
  - Scoring: only truth-populated fields count; accent-folded/containment matching for text (`Sandvik` vs `Sandvik Mining and Rock Solutions` is not an error); digits-suffix matching for phones with phone/mobile pooled (models swap the slots); scheme/www-stripped websites.
  - Frontend: modal with installed-model checkboxes (catalogue models preselected), card-count limit, live progress, ranked results table (per-field %, overall %, avg seconds, failure count; winner highlighted).
- 17 new tests (matching, scoring, item collection, accumulator math, model routing). 314 total pass. Verified live: 2-card × glm-ocr run streams progress and returns ranked per-field scores.

---

## [2.1.27] — 2026-07-08

### Added

- **Email-anchored field-permutation repair** (`fix_field_permutations` in `utils/providers/base.py`). Vision models don't just put the title in the name field — they emit whole permutations. Observed with qwen2.5vl on a real card: `title: "Victor Becattini"`, `company: "Vice Presidente Vendas Brasil"`, while the email (`victor.becattini@sandvik.com`) held the truth. The email is the most reliably-OCR'd field on a card, so it's used as the anchor:
  - **Name recovery:** if the current name doesn't match the email local-part tokens but title/company matches ALL of them, the name is rotated into `fullName` (first/last re-derived); whatever the wrong field held is re-homed (role-like → title, domain-match → company, else → notes).
  - **Title untangling:** a role-like company (multilingual wordlist) that doesn't mention the email domain moves to an empty `title`.
  - **Company from domain:** empty company gets the email domain base title-cased (`sandvik.com` → `Sandvik`) — fill-empty-only, skipped for freemail/ISP domains (gmail, hotmail, uol, terra, …).
  - Conservative gates: needs ≥2 name tokens in the email local part and a 100 % token match to rotate; accent-folded matching (`João` ↔ `joao`); correct extractions pass through byte-for-byte untouched.
- Runs in the pipeline as `repair_cjk → fix_field_permutations → demote_title_misplaced_as_name`, wired into all three post-processing sites (provider results + both CardProcessor paths).
- 10 new tests (`TestFieldPermutations`); 297 total pass. Verified live: re-scanning the exact HEIC that produced the scramble now yields name/title/company all correctly placed straight from OCR, before the QR fetch.

---

## [2.1.26] — 2026-07-08

### Fixed

- **`localhost:9247` hung forever after starting a scan.** The uvicorn worker was dying with a **SIGSEGV inside `libzbar.0.dylib` (`_zbar_scan_image`)**, called through ctypes by **pyzbar**. Crash report: `EXC_BAD_ACCESS / KERN_INVALID_ADDRESS at 0xffffffffffffffff`.
  - **pyzbar is now disabled by default.** pyzbar 0.1.9 (its latest release) doesn't declare `restype` for several pointer-returning libzbar functions; on arm64 the pointer is truncated and libzbar dereferences garbage. Reproduced deterministically here (zbar 0.23.93 + pyzbar 0.1.9 + CPython 3.13): **every** `pyzbar.decode()` segfaults, even on a blank 64×64 array, via the numpy, PIL _and_ raw-bytes paths. `zbarimg` (libzbar directly) is stable, so the fault is in pyzbar's binding, not the library. Opt back in with `USE_PYZBAR=1`.
  - **No functionality lost.** pyzbar was never actually used in this deployment: the system Python is SIP-protected, so macOS strips `DYLD_LIBRARY_PATH` and the `from pyzbar import pyzbar` always raised `ImportError`, silently falling back to the OpenCV QR detectors. Switching to a `.venv` (a non-SIP interpreter) let `DYLD_LIBRARY_PATH` through and armed the bomb. The OpenCV path decodes these cards fine — verified it still reads `https://my.mobiz.pro/victorbecattini/` off the same HEIC.
- **Auto-reload is now off by default** (`RELOAD=1` to enable). This is what turned a crash into a _silent hang_: with `reload=True` the reloader parent binds the socket and a child serves. When the child segfaulted, the parent kept the port bound — TCP connects succeeded, no HTTP response ever came, and the browser spun with no error in any log. Without the reloader a crash just ends the process and frees the port, which fails loudly. (A segfault cannot be caught with `try/except`, so preventing the crash _and_ removing the wedge are both necessary.)

### Notes

- Verified end-to-end: a real scan of the HEIC that previously killed the worker now completes (`warmup → detect → extract → generate → done`), yields **one** card with `qrUrl` set, and leaves the server responsive. 287 tests pass.

---

## [2.1.25] — 2026-07-08

### Fixed

- **`setup.sh` failed with an unreadable pip error on Python 3.9.** The project declares `requires-python = ">=3.10"` and pins `starlette>=1.0.1` (the CVE-2026-48710 BadHost fix) plus `fastapi>=0.111` — neither publishes wheels for 3.9. `setup.sh` only _printed_ the Python version, never checked it, so pip died with a wall of `Ignored the following versions that require a different python version` and `No matching distribution found for starlette>=1.0.1`. It now enforces the ≥3.10 floor up front with an actionable message (suggesting `brew install python@3.13` or `uv`).
- **`setup.sh` installed into user site-packages, never a venv** — while `BusinessCardScanner.app` execs `$PROJECT_DIR/.venv/bin/python3`. A fresh `setup.sh` therefore left the desktop shortcut permanently broken ("Python venv not found"). Setup now always creates a project-local `.venv`, preferring `uv` when available (which supplies its own Python) and falling back to `python -m venv`.
- **Installs from `requirements.lock` when present** (hash-pinned, reproducible) instead of the floating `requirements.txt`.
- Docs (`README.md`, `QUICKSTART.md`) no longer tell users to `pip install -r requirements.txt` into user-site; they point at `./setup.sh` / the `.venv` and state the 3.10+ floor.

### Notes

- The existing `.venv` on this machine was **orphaned**: `pyvenv.cfg` pointed at `/opt/homebrew/opt/python@3.13`, which had been uninstalled, leaving `.venv/bin/python` a dangling symlink. Rebuilt against uv's managed CPython 3.13.13 and reinstalled from `requirements.lock` — this also upgraded the runtime from the vulnerable `starlette 0.27.0` / `fastapi 0.104.1` (user-site, Python 3.9) to `starlette 1.3.1` / `fastapi 0.136.3`, and pulled in `probablepeople` + `pytest-timeout`, which had been silently missing. 287 tests pass on the full pytest config.

---

## [2.1.24] — 2026-06-04

### Fixed

- **A single card with a QR code produced two result cards.** Two compounding causes:
  - **"Single Card" mode wasn't actually single.** `server.py` maps the frontend's `"single"` to the string `"Single Card"`, but `CardProcessor.detect_cards` only recognised `"Manual - Single Card"` — so the value matched nothing and fell through to **Automatic** detection. Automatic detection then picked up the card's QR square as its own rectangular region → two cards (one from vision with the full contact, one from the QR region with just the URL). `detect_cards` now normalises the mode string and accepts all spellings (`Single Card`, `single`, `Manual - Single Card`, …) for single/grid/auto, so a mismatch can never silently fall through again.
  - **Robustness net for Automatic mode**, where a QR square can still be detected as a separate region: `_consolidate_qr_only_cards` folds a "QR-only" card (no name/email/phone, just a pending `_qr_url`) back into the real card on the same image — transferring the QR URL + website so the "Fetch contact data" button is preserved — and drops the duplicate. Guarded to only fire when there's exactly **one** rich card, so batch scans (where a stray QR can't be attributed) are left untouched.
- 9 new tests (single-card string variants; consolidation merge / batch-safety / lone-QR / no-op). 287 total pass.

---

## [2.1.23] — 2026-06-04

### Fixed

- **QR-resolved names now split into first/last** for VCF exports. Many hosted vCards pack the whole name into one field (`N:;Victor Becattini;;;`), leaving `firstName` holding the full name and `lastName` empty — so the exported VCF `N:` line had no surname. New `_normalize_name` derives first/last from `full_name` when `last_name` is empty (first token → first, remainder → last), without clobbering a legitimate split from the source. Single-token names (e.g. "Cher") are left untouched. 4 new tests; 279 total pass.

---

## [2.1.22] — 2026-06-04

### Fixed

- **QR-linked contact pages now resolve to the full, correct contact** (was returning sparse/wrong data — typically a single field or the wrong name). Found while testing a real Mobiz digital business card (`my.mobiz.pro/...`). Three resolver bugs:
  - **Authoritative vCard was being rejected.** Digital-card platforms expose a "save contact" endpoint (e.g. `/<slug>/vcard`) that serves the real vCard as `application/octet-stream`. The content-type allowlist blocked it, so the resolver fell back to scraping the HTML. Added `application/octet-stream` to the allowlist (still only parsed as a vCard if the body starts with `BEGIN:VCARD`, still 2 MB-capped). The `/vcard`-style endpoint (no `.vcf` extension) was already discovered; now it's actually used.
  - **Wrong name from the page author.** WordPress/Mobiz pages embed a JSON-LD `Person` for the _site author_ (the agency that built the card), which the parser took as the contact — e.g. returning "Marcelo Dias" for Victor Becattini's card. Person nodes whose `@id`/`url` is an `/author/` archive are now skipped.
  - **`og:title` is now authoritative for the owner's name.** On these cards `og:title` is "Name | Company"; the parser now splits it, overrides the name, and fills the company.
  - Also: vCard `ROLE` now maps to the job title (Mobiz puts the title in `ROLE`, not `TITLE`).
  - Net result on the test card: full name, "Vice President Sales Brazil", SANDVIK, work + cell phones, and email — all pulled correctly, then merged non-destructively with the card's OCR fields (website, notes preserved).
- 5 new resolver tests (octet-stream vCard accepted, `/vcard` endpoint discovery, author-node skip, `og:title` override, `ROLE`→title). 275 total pass.

---

## [2.1.21] — 2026-06-04

### Added

- **Resolve QR codes that link to a hosted contact page.** Some business cards encode a URL (a hosted vCard, a digital-business-card page like HiHello/Popl) in their QR instead of inline fields. The scanner now detects this and, on the card's expanded view, shows a **"Fetch contact data"** button (plus a "QR link" badge on the collapsed card). Fetching is **user-initiated** — nothing hits the network during the scan.
  - New `utils/qr_url_resolver.py` does the guarded fetch + extraction. Extraction priority: vCard / MECARD body → `application/json` (schema.org Person) → HTML (JSON-LD `Person`/`Organization`, then a discovered `.vcf` download link re-fetched for richer data, then `mailto:`/`tel:` links and `og:title`).
  - New endpoint `POST /api/resolve-qr-url`. Pulled fields are merged **non-destructively** into the card (only fills empty fields, so reviewed OCR data isn't clobbered); the user then Saves as normal.
- **Security — the URL is threat-checked before any request is made:**
  - Scheme allowlist (http/https only), no embedded credentials, ports limited to 80/443.
  - **SSRF guard:** every hostname is DNS-resolved and each IP checked against private/loopback/link-local/reserved ranges (blocks `127.0.0.1`, `10/8`, `192.168/16`, `169.254.169.254` cloud-metadata, `::1`, etc.). `localhost` rejected outright.
  - Redirects followed manually (max 3), **re-validated at every hop** so a public URL can't bounce to an internal one.
  - Response caps: 8s timeout, 2 MB max, content-type allowlist.
  - Optional Google Safe Browsing lookup when `GOOGLE_SAFE_BROWSING_API_KEY` is set (skipped silently otherwise).
- Tests: `tests/test_qr_url_resolver.py` — 28 cases (SSRF/scheme/port rejections incl. cloud-metadata IP, DNS-resolves-to-private, vCard/MECARD/JSON-LD/HTML parsing, and mocked end-to-end orchestration confirming no fetch happens for a blocked URL).
- Dep: `beautifulsoup4` added to `requirements.txt` (was used elsewhere but unlisted).

---

## [2.1.20] — 2026-06-04

### Fixed

- **The desktop shortcut sometimes opened a different app (a Streamlit "cota" dashboard) instead of the scanner.** Root cause: the server defaulted to port **8501**, which is also Streamlit's default port. When a Streamlit project was already running, the launcher's bare `lsof` check saw the port occupied and just opened the browser to whatever was there. Two-part fix:
  - **Moved the scanner to a dedicated port 9247** (clear of Streamlit's 8501, Ollama's 11434, and the user's other local dashboards clustered around 850x/876x). Updated `server.py` default, the launcher app, the Stop app, and all docs (`README`, `TESTING`, `QUICKSTART`, `CLAUDE.md`, `setup.sh`, `.claude/launch.json`).
  - **Hardened the launcher to verify identity before opening.** It now probes the BCS-specific `/api/status` endpoint and only opens the browser if the response is actually our server (JSON with an `"ollama"` key). If a foreign app squats the port, it shows a dialog telling the user to stop that app rather than silently opening the wrong thing.
- The Stop app now targets 9247 too, so it can no longer accidentally kill a Streamlit project that happened to be on 8501.

---

## [2.1.19] — 2026-05-28

### Fixed

- **Title-as-name demotion no longer blanks real names that collide with a role word.** The 2.1.15 heuristic demoted on _any_ strong token (`CEO`, `Director`, `Diretor`, …) regardless of context, so a person legitimately named "Mike Director" or "Anna Presidente" would have their name silently wiped. The strong-token shortcut now only fires when **every** token in the string is a role token (which still covers "CEO", "Vice President", "Sales Director"). Mixed strings fall through to the density rule (≥2 role tokens and ≥50 % role density), so "Mike Director" / "Daniel Sales" / "Patricia Marketing" are correctly left alone.

### Added

- **Regression test** `tests/test_providers.py::TestTitleDemotion` — 26 cases covering unambiguous titles (EN/PT), surname collisions, honorific vetoes, and the demotion side-effects (empty-title move, existing-title preservation, first/last clearing, None-safety). Run: `pytest tests/test_providers.py::TestTitleDemotion`.

---

## [2.1.18] — 2026-05-28

### Changed

- **Contacts tab now shows the actual cropped card thumbnail** in place of the coloured initials avatar. Falls back to the old initials chip if the contact has no `cardId`, no archived thumbnail, or the image 404s. Avatar bumped to 44 × 44 so the thumb is actually legible. New `<ContactThumb>` component encapsulates the load + fallback logic.
- **Click-to-magnify.** Clicking the thumbnail opens a full-size lightbox (95 vw × 95 vh, dark backdrop, blur). Esc or click-outside dismisses; body scroll locks while open. `stopPropagation` on the thumb click so it doesn't also select the row.
- **Thumbnail quality bumped 7× (200 px → 1400 px on the long edge, JPEG q=85 → q=92).** The old 200 px thumb was fine as a list-row avatar but pixelated badly when magnified. New size is ~170 kB on average — still small enough to load instantly in the list, sharp enough to read every line of the card when expanded. Optimised JPEG encoding so file size doesn't balloon.
- **One-shot regen** of all 953 existing thumbnails from the archived `temp/history/*/cards/*/preview.png` sources, using the new size/quality settings.
- **Thumbnail HTTP endpoint now uses ETag revalidation** (keyed on file mtime) with `max-age=60, must-revalidate`. The browser auto-fetches the new high-res thumb after a regen instead of serving a stale 200 px copy from cache for an hour. Out-of-band file changes also invalidate the in-memory cache via the same mtime check.

---

## [2.1.17] — 2026-05-28

### Fixed

- **Edits to cards in the Scanner tab silently corrupted the saved contact.** The `POST /api/contacts` and `PUT /api/contacts/{id}` endpoints were translating frontend camelCase keys into snake_case (`fullName` → `full_name`) and dropping every field not in their hand-maintained `field_map` (firstName, lastName, notes, city/state/zip/country). The repository's canonical schema is camelCase — `_MERGEABLE_FIELDS`, the VCFGenerator, and the merge-or-conflict logic all key on `fullName`/`firstName`/etc. Net effect of an edit: VCF regeneration produced a nameless vCard; firstName/lastName/notes/city/state/zip/country got wiped; future rescan-merges treated all camelCase fields as missing and created phantom additions.
- Both endpoints now pass frontend camelCase through unchanged, filter against an explicit allowlist, and **PUT merges instead of replacing** (uses `apply_field_updates` so fields the Edit modal doesn't expose are preserved).
- **One-shot migration** of `temp/contacts_repository.json`: 61/79 contacts had snake-case keys mixed in from prior edits. All were rewritten to camelCase canonical form and VCFs regenerated. Backup written to `temp/contacts_repository.backup_<timestamp>.json`.

---

## [2.1.16] — 2026-05-28

### Added

- **Vision-model catalogue with speed / quality ranks** in `frontend/index.html` (`VISION_MODELS`). Every model gets a 1-5 speed score, a 1-5 quality score, a short blurb, and a tooltip. The Settings model picker is now driven from this catalogue — pills show an inline `S{speed}/Q{quality}` badge and the selected model's blurb appears underneath. Catalogue order (best speed-quality balance for business-card OCR first):
  1. `glm-ocr` — S5/Q4 — OCR-specialised, fastest, ~2 GB. Default for clean Latin-text cards.
  2. `qwen2.5vl:7b` — S3/Q5 — strongest general multilingual vision, 5.7 GB. Best on complex layouts.
  3. `minicpm-v` — S3/Q4 — balanced multilingual VLM, 5.2 GB. Often better on Asian text.
  4. `moondream` — S5/Q3 — tiny + fast, 1.7 GB. Use when low-resource.
  5. `llava:latest` — S3/Q3 — older fallback, 4.5 GB.
  6. `claude-3` — S2/Q5 — cloud, highest quality, costs per call.
- **History-tab relaunch picker** now sorts installed models by the catalogue (recommended first, unknowns alphabetically at the end) and shows the same `S/Q` badge next to each entry. So `qwen2.5vl` and `glm-ocr` float to the top instead of being lost in alphabetical order.

### Removed

- Dead model options from the Settings picker that weren't installed on this machine (`llama3.2-vision`, `llava:13b`). The catalogue lists what's actually pullable + useful.

---

## [2.1.15] — 2026-05-28

### Changed

- **Locked contacts now fully protect name + email.** Stated invariant: "locked means I checked it and I'm OK with most of it — never change name and email." `firstName`, `lastName`, `fullName`, and `email` are added to `_LOCKED_PROTECTED_FIELDS` in `ContactsRepository`. On a locked contact:
  - If existing has a value for any of these → incoming is silently dropped (no conflict surfaced, no resolver radio buttons, no chance of override).
  - If existing is empty → incoming can populate (additive still works).
  - Enforced at two layers: the merge logic in `_merge_or_conflict` filters them from the `conflicts` list; the `apply_field_updates` primitive (called by the `/resolve` endpoint) also refuses to overwrite them. Belt-and-suspenders so neither the rescan path nor a hand-crafted API call can flip a protected field.

### Fixed

- **Job titles being emitted as the person's name.** Vision models routinely latch onto the largest text block on a card (often the role) and emit it as `fullName`. New `demote_title_misplaced_as_name(contact_dict)` helper detects role-like strings against a multilingual wordlist (EN / PT / ES / FR / DE / IT — 100+ tokens covering CEO/Diretor/Geschäftsführer/Direttore/etc.) and moves them to `title` (only if `title` is empty), clearing the name fields so a real name can still be pulled from elsewhere. Honorifics (Mr/Sra/Herr/etc.) veto the demotion. Strong tokens (CEO, Director, Diretor, Founder, Manager) trip the rule alone; weaker tokens need ≥50 % role density and ≥2 role hits. Applied at both vision and QR-only post-processing paths.

---

## [2.1.14] — 2026-05-28

### Fixed

- **Relaunch silently produced 0 cards for any archived run larger than 25 MB.** The validator on the scan generator capped uploads at 25 MB (`MAX_UPLOAD_BYTES`) to protect the upload endpoint. On the relaunch path the same cap was being re-applied to files coming from our own archive, so anything bigger (e.g. a 31 MB multi-page PDF) was rejected with a `warning` SSE event that the frontend never surfaced — the result was an empty new run with 0 files / 0 cards and no explanation. Now `_scan_generator(skip_size_check=True)` is passed on the relaunch path; the cap still applies to fresh uploads.
- **Relaunch warnings are now visible.** The SSE consumer now collects `stage: "warning"` events and appends them to the post-run alert. When a relaunch produces 0 cards, the consumer surfaces the warnings (or a generic "the model may have failed" hint when there are none) instead of leaving the user staring at an empty run.

### Changed

- **Conflict resolution is now interactive.** Previously the conflict panel was informational — it told you which locked-contact fields had been kept and which incoming values were skipped, but offered no way to override the decision short of editing the contact manually. Now every conflict renders as two radio buttons (left = keep existing, right = use incoming) plus an **"Apply N changes" button**. Click Apply and the merge is persisted via a new `POST /api/contacts/{id}/resolve` endpoint, which regenerates the VCF so exports stay consistent.
- Works in both surfaces:
  - **Scanner tab** — per-card expanded conflict block.
  - **History tab** — inline conflict panel on the newly-created run card after a Relaunch (each contact gets its own resolver, name-hinted).
- Unsaved cards (no `repoId` yet) show the picker but the Apply button is disabled with a tooltip explaining you need to save the contact first.

### Added

- `ContactsRepository.apply_field_updates(contact_id, updates)` — partial-merge primitive that takes a `{field: value}` dict, applies it on top of the existing `contact_data`, regenerates the VCF, and saves. Pass `None`/`""` as a value to clear a field. Distinct from `update_contact`, which replaces the whole record.
- New `<ConflictResolver>` React component, reused by both surfaces.

---

## [2.1.13] — 2026-05-28

### Added

- **"Suspicious relaunch" red banner** in the History tab when a relaunch's conflict ratio exceeds 50 % of cards (typical signature of a model that confabulated badly — names in the title field, addresses in the company field, etc.). Includes:
  - A one-line explanation that locked contacts blocked the bad values (your data is safe).
  - A **"Delete run" button** right inside the banner — click → confirm → run is gone from history with no further action needed.
  - When the offending model wasn't one of the known-good vision-OCR models (`glm-ocr`, `qwen2.5vl`, `qwen3-vl`, `minicpm-v`, `internvl3.5`, `olmocr`), the banner names the model used and suggests trying a vision-tuned one instead.

### Notes

- The 50 % threshold is heuristic — a healthy relaunch on a non-changed image should produce 0 conflicts (everything matches the stored values). Anything that flips half the locked contacts is almost certainly a model issue, not the data being genuinely different.

---

## [2.1.12] — 2026-05-28

### Fixed

- **Relaunch conflicts were invisible** despite the alert telling users to "switch to the Scanner tab to view". That tab has its own state — the relaunch SSE data never reached it, so the user always saw nothing. The misleading alert text has been replaced and the conflicts are now shown **inline on the newly-created run card in the History tab itself**.

### Added

- **Post-relaunch repo-impact panel** in the History tab's expanded run card. When a Relaunch finishes:
  - The new run is auto-expanded (no scrolling, no clicking).
  - A "Repo impact (this relaunch)" panel appears at the top of the expanded view with four colour-coded badges: `N new`, `N updated`, `N merged`, `N with conflicts`.
  - When conflicts exist: a yellow detail block lists each one — `kept "X" · skipped "Y"` — grouped by contact. Plus a one-line nudge: _"Locked values were kept. To accept the new value, edit the contact in the Contacts tab (or unlock it and rescan)."_
  - When additive merges happened: a green block lists which fields were added to which contact.
- Backed by a new client-side `relaunchResults` cache keyed by run id. `/api/history` doesn't preserve `repoStatus` per card, so this only shows for the relaunch session that created the run — reloading the page clears it (intentional: the conflicts are still recorded in the contacts repo and visible per-contact in the Contacts tab).

---

## [2.1.11] — 2026-05-28

### Fixed

- **Field conflicts were invisible in the Scanner tab even when they existed.** The data was correct end-to-end (verified the SSE `done` event was emitting `repoStatus: "conflict"` with populated `conflicts: [...]` for every card that touched a locked existing contact), and the top-of-results banner was rendering — but it was easy to miss in dense result lists. Two new always-visible indicators:
  - **Per-card status badge** in the header row, sitting next to the `via` / language badges:
    - `2 conflicts` (amber) when locked-contact merge produced field disagreements
    - `+3 merged` (green) when locked-contact merge added new fields without conflict
    - `updated` (neutral) when an unlocked contact got overwritten with fresh scan data
    - `new` (blue) when this is the first time the email was seen
  - **Expandable conflict / additions panels** inside the card's expanded view. Click _More_ on any card and you see exactly which fields conflicted (`kept "X" · skipped "Y"`) and which fields were added by the merge.

### Notes

- The top banner from 2.1.5 is unchanged — still summarises the whole run, still has the _Show details_ toggle. The per-card badges + expanded panels are additive, so users who already used the banner workflow keep it.

---

## [2.1.10] — 2026-05-28

### Added

- **Language-aware LLM post-correction routing.** The optional post-correction pass (off by default) now detects the card's language from the raw OCR text via `langdetect` and routes to a per-language model when available.
  - Configure overrides with `OCR_POST_CORRECTION_MODEL_<LANG>` env vars, where `<LANG>` is the 2-letter ISO 639-1 code uppercased:
    ```
    export OCR_POST_CORRECTION_MODEL_PT=gemma3:1b-pt-ocr-correct
    export OCR_POST_CORRECTION_MODEL_ES=qwen2.5:3b
    export OCR_POST_CORRECTION_MODEL_EN=qwen2.5:3b
    ```
  - Falls back to the generic `OCR_POST_CORRECTION_MODEL` for any language without a specific override. When neither is set, no correction runs (same as before).
- **`detectedLang` field in the scan API response** — surfaces the detected language code (e.g. `"pt"`) on each card. Frontend now shows a small `PT` / `EN` / `ES` badge next to the `via` badge in the scan-result card, so you can see at a glance which model corrected which card.
- **`langdetect>=1.0.9`** added to `requirements.txt`.

### Internal

- Two new helpers on `OllamaVisionProvider`:
  - `_detect_language(text)` — best-effort ISO 639-1 detection with seeded determinism. Returns None for text under 12 chars or when langdetect isn't installed.
  - `_pick_correction_model(raw_text)` — returns `(lang, model_name)` after consulting the env vars.
- `_detected_lang` is set on `contact_dict` before correction runs, then lifted out by the server's frontend mapper so it doesn't pollute the saved contact data.

### Recommended setup for trilingual workflows (EN / PT / ES)

A single multilingual small model (qwen2.5:3b, gemma3:1b, llama3.2:3b) handles all three languages adequately. Pull it once:

```
ollama pull qwen2.5:3b
export OCR_POST_CORRECTION_MODEL=qwen2.5:3b
```

If you find a pt-BR-specific corrector model that beats qwen on Portuguese cards (Gemma 3 pt-OCR-fine-tunes exist on HuggingFace), use the `_PT` override to route just those.

---

## [2.1.9] — 2026-05-28

### Changed

- **JSON-schema constrained decoding now applies to GLM-OCR too**, not just the LLM-vision fallback path. Previously gated to `not _is_ocr_model()` because an earlier schema embedded example values that GLM-OCR would parrot. Current schema uses only null defaults — nothing to copy. End-to-end test on `IMG_1544.heic` (the 18-card reference fixture):
  - **name** went from 14/18 → 17/18
  - **phone** went from 17/18 → 18/18
  - **title** is now a separately-tracked field, 16/18 populated (previously bundled into name)
  - **email / website** dipped slightly (-1, -6); the regex parser was better at extracting bare-domain URLs the model isn't emitting under structured output. Net win is substantial — proper field separation matters more than raw recall on website strings.
- The OCR-regex parser (`_parse_ocr_to_contact`) is no longer the primary path; it's a **fallback** that only fires when the JSON parse fails on an OCR-named model.
- Post-correction (`OCR_POST_CORRECTION_MODEL` env var) now applies on both paths, not just OCR — useful even with schema-constrained output for fixing accent loss.

### Added

- **`OLLAMA_DISABLE_JSON_SCHEMA=1` env var** as an emergency opt-out. Set to revert to the legacy raw-OCR-text path for `glm-ocr` (and any other model matching `_OCR_ONLY_MODELS`). Useful if a future GLM-OCR build regresses on JSON output.

### Investigated, not shipped

- Regex `pattern` constraints on the JSON schema (e.g. forcing `email` to match a regex). Ollama 0.24's grammar backend hangs the server on every pattern tried, even trivial ones like `^.{1,5}$`. Documented in the schema function's docstring; revisit when Ollama merges full XGrammar regex support. Until then we rely on downstream `phonenumbers` / `email_validator` for format validation.

---

## [2.1.8] — 2026-05-27

### Added

- **"Relaunch with different model" picker** on every History tab run card. The Relaunch action is now a split button:
  - Main button: relaunches with the original saved settings (same as 2.1.6 behaviour).
  - Chevron dropdown: lists every model `/api/status` reports as installed locally — pick one and the relaunch runs with that model instead of the original. The model that matches the original is highlighted with a check mark.
  - Useful for A/B'ing extraction quality on a known-input scan ("did Claude beat GLM-OCR on this card layout?") without re-uploading anything.

### Internal

- `HistoryTab` fetches `/api/status.models` once on mount and de-duplicates Ollama tag suffixes (`:latest`, `:13b`, …) for a cleaner picker.
- `handleRelaunch(runId, options)` accepts an optional `{model}` (and any other backend-supported override). Passed as the JSON body of `POST /api/history/{run_id}/relaunch`, which already supported per-call overrides from 2.1.6.

---

## [2.1.7] — 2026-05-27

### Added

- **"NEW" badge + green left-edge ribbon** on contacts added today. Spotted right after a scan / relaunch — no need to remember which contacts were just imported.
- **Collapse / Expand all** button in the Contacts-tab toolbar (only visible when "Group by company" is on). Toggles every `CompanyGroup` open or closed at once. Useful when you have dozens of companies.

### Fixed

- **Lock / unlock button in the Contacts tab wasn't responding to clicks**. The previous design used a bare 13×13 padlock icon with `color: var(--text-tertiary)` — nearly invisible, easy to miss-click, and the click was bubbling up to row-level handlers in some layouts. Now the lock control is a proper labelled pill button ("Lock" / "Locked"), 1px border, accent-tinted when locked, with explicit `stopPropagation()` and a `console.log` breadcrumb on click for diagnostics. Visual state change is unmistakable.

### Internal

- `CompanyGroup` accepts optional controlled `isOpen` / `onToggleOpen` props for parent-driven expansion state. Falls back to local state if those props aren't provided, so other call sites (none currently) stay backwards-compatible.

---

## [2.1.6] — 2026-05-27

### Added

- **History → Relaunch is now real.** Previously a stub: clicked, showed "Relaunching…" for 2 seconds, did nothing. Now:
  - **`POST /api/history/{run_id}/relaunch`** endpoint reads the run's archived originals from `temp/history/<runId>/original/`, replays them through the same `_scan_generator` SSE pipeline a fresh upload uses, defaulting to the run's saved settings (`vision_model`, `detection_mode`, `vision_timeout`). Body can override any of model/mode/rows/cols/timeout/row_lines/col_lines/margin\_\*/deskew.
  - Results land as a **new** history run; the original is untouched.
  - Cards flow through the same contacts-repository merge logic — locked contacts respect the merge-or-conflict rule from 2.1.5; unlocked contacts get the legacy overwrite.
  - **Live progress overlay** on the History tab run card during relaunch: stage badge, progress bar, message text — same data the Scanner shows. Once done, the history list auto-refreshes so the new run appears.
  - One-at-a-time guard: clicking Relaunch on another card while one is in-flight is a no-op.

### Internal

- New helper class `_SyntheticUpload` in `server.py` — minimal `UploadFile`-shaped wrapper around in-memory bytes (just `.filename` and async `read()`). Lets `_scan_generator` consume disk files identically to fresh uploads without changing its signature.
- `_MODE_REVERSE_MAP` maps `CardProcessor.detection_mode` strings back to the frontend's short codes (`"Automatic"` → `"auto"`, etc.) so a relaunch without overrides uses exactly the original detection mode.

---

## [2.1.5] — 2026-05-27

### Added

- **Persistent per-contact lock** in the contacts repository. Lock a contact (click the padlock icon next to Edit/Delete in the Contacts tab, or in the scan-result card view) to mark it as "the version of truth". Locked contacts survive future scans intact — see the new merge-or-conflict rule below.
- **Merge-or-conflict on re-scan of locked contacts.** When a new scan extracts a card whose email matches an existing **locked** repo contact:
  - **Additive fields** — any field the existing contact didn't have (e.g. phone, mobile, address) is merged in silently, and the VCF is regenerated to include them.
  - **Conflicting fields** — any field where existing and incoming disagree is recorded as a conflict and reported back to the UI. The existing value is preserved; nothing is overwritten.
- **Conflict-resolution banner** in the scan results panel. If any scanned card touched a locked existing contact:
  - Shows "Added fields to N locked contact(s)" for purely additive merges.
  - Shows "N field conflicts on M locked contact(s) — review below" with a **Show details** toggle that lists each conflict (`field: existing X vs new Y`) and what was added. Includes instructions on how to resolve (edit the saved contact, or unlock to allow overwrite).
- **`PUT /api/contacts/{id}/lock`** endpoint. Body: `{"locked": true|false}`.

### Changed

- `ContactsRepository.add_contact()` now returns a dict `{id, status, additions, conflicts, locked}` instead of just the contact id. `status` is one of `added`, `updated` (unlocked overwrite), `merged` (locked, additive only), `conflict` (locked, some values disagree). All callers in `server.py` updated; the public API responses now include `status`, `additions`, and `conflicts` where relevant.
- Unlocked contacts still follow the legacy "rescan overwrites" behaviour, so you can deliberately refresh extracted data by leaving a card unlocked.

### Documented

- `_MERGEABLE_FIELDS` is the canonical list of fields that participate in the merge-or-conflict comparison: `firstName`, `lastName`, `fullName`, `title`, `company`, `email`, `phone`, `mobile`, `website`, `linkedin`, `address`, `city`, `state`, `zip`, `country`, `notes`. Comparison normalises whitespace and case, so `"Acme Corp"` and `"acme  corp"` don't trip a conflict.

---

## [2.1.4] — 2026-05-26

### Improved

- **Website extraction in the OCR-parser path.** Previous regex was too narrow:
  - Required 3+ domain labels (`label.label.tld`), so bare `acme.com` / `itaubba.com` were missed.
  - TLD whitelist was only `com|br|net|org|io|ca|co|app` — `.gov`, `.gouv`, `.edu`, `.fr`, `.de`, `.it`, `.uk`, `.es`, `.gov.br`, etc. all slipped through.
  - First-match-wins: if a card had both a bare domain and an `https://` URL, the bare one was taken.
  - No prefix stripping: `URL: www.x.com` and `(www.x.com)` captured the extra chars.

  New behaviour: collects all candidates, picks the strongest by score (explicit `https://` scheme > `www.` prefix > longest). Strips leading `URL:` / `Web:` / `Site:` / `Link:` / `Homepage:` prefixes and trailing punctuation. Supports the full common-TLD list including country TLDs and government/academic domains. **Priority order is preserved**: email/linkedin lines are still consumed first, name/company classification still runs after URL extraction, so a URL line can never be claimed as a company name.

### Documented

- The codebase-wide field priority is now: **Name → Company → Email → Phone → Website → others.** Higher-priority fields claim lines first; lower-priority extractors only see what's left. This invariant is encoded in the parser's run order and called out in `_parse_ocr_to_contact`.

---

## [2.1.3] — 2026-05-26

### Fixed

- **HEIC uploads rejected with "File content does not match a supported image/PDF format".** The upload validator's magic-byte sniff only accepted two specific ISOBMFF `ftyp` box lengths (`0x18` and `0x1c`). HEIC files from newer iOS versions use other box lengths (`0x14`, `0x20`, etc.) depending on the brand list, so they tripped the validator before even reaching the loader. Validator now checks the brand at bytes 8–11 against the full HEIF/HEIC/AVIF brand set (`heic, heix, hevc, hevx, heim, heis, hevm, hevs, mif1, msf1, heif, avif, avis`) and ignores box length, matching ISOBMFF spec. WEBP detection also tightened to require the `WEBP` fourCC at byte 8 (not just `RIFF` anywhere in the first 16 bytes).

---

## [2.1.2] — 2026-05-26

### Fixed

- **Silent dependency-missing regression on phone & name extraction.** `phonenumbers` and `probablepeople` were declared in `requirements.txt` but never `pip install`ed into the runtime Python 3.9. Both per-card try-imports in `utils/providers/ollama_provider.py` (lines 498 and 597 in 2.1.1) had `except ImportError: pass` with no log — so the OCR parser silently dropped every phone field and fell back to brittle regex name/company detection on every scan, for an unknown number of runs. On a single test image this surfaced as 3/18 phones (vs 17/18 once libs were installed) and the `company: "São Paulo, SP, Brazil"` (address misclassified as company) symptom.

### Changed

- Replaced both per-call try/import blocks with **module-level availability probes** (`PHONENUMBERS_AVAILABLE`, `PROBABLEPEOPLE_AVAILABLE`) that run once at import time. If either lib is missing, an actionable `logger.error(...)` fires immediately at server startup pointing at the pip command to fix it — so the next silent-dependency regression is visible in `/tmp/bcr_server.log` instead of hiding behind empty fields. Per-card overhead drops from 18 imports per scan to 1.

---

## [2.1.1] — 2026-05-25

Bug-fix follow-up to 2.1.0. All three issues surfaced on `IMG_1544.heic` (6×3 Portuguese-language card layout).

### Fixed

- **Empty `fullName` on every extracted card.** Root cause: the vision LLM returns camelCase keys (`firstName`, `lastName`, `fullName`) via `ContactInfo.to_legacy_dict()`, but the server's frontend-mapper in `_contact_data_to_frontend` and `_contact_to_api` was reading **snake_case** (`full_name`) and never falling back to `firstName + lastName` concatenation. Title/company/email survived because they're single-word keys. Mapper now tries (in order): `fullName`, `full_name`, `firstName + lastName`, `first_name + last_name`, `name`. Applied to all three sites in `server.py`.
- **CJK-character contamination in Portuguese text.** GLM-OCR (Chinese-origin model) was substituting accented Latin characters with visually-vaguely-similar CJK ideographs: `é → 矇` (U+77C7), `ç → 癟` (U+765F), `ã → 瓊` (U+74CA). Three-pronged fix:
  1. Added explicit prompt rule in `utils/providers/base.py`: _"Use ONLY Latin characters with proper Western European accents. NEVER substitute non-Latin characters (Chinese, Japanese, Korean, etc.) for accented Latin letters."_
  2. New `repair_cjk_substitutions()` post-processor with a confirmed-substitution table (`_CJK_TO_LATIN`) and a CJK-range regex (`_CJK_RE`). Unknown CJK chars in Latin-context fields fall through to `?` so corruption is visible rather than silent.
  3. Applied at **three sites** (the QR-only short-circuit at `extract_contact:185` was the gotcha — it bypasses every vision provider, so the base-class repair never ran for QR-sufficient cards): `card_processor.extract_contact` (both return points) + `providers.base._make_scan_result`. All paths through `extract_contact` now repair before returning.

### Added

- **`POST /api/scan/export/{fmt}`** — exports the just-completed scan's cards directly, separate from the persistent contacts repository. Supports `vcf` (concatenated, uses pre-generated `vcfContent`), `xlsx`, `csv` (Outlook format), and `zip` (bundles all three + per-card individual VCFs under `per_card/`).
- Wired up every export button in the Results panel — they were UI-only placeholders before. **Export All** and **Download ZIP** hit `/api/scan/export/zip`; the **VCF / Excel / Outlook CSV** pills hit their respective formats. Each button shows a spinner while in-flight and disables when no cards or another export is running. Errors surface via `alert()`. The **+ Outlook Push** button is visibly disabled with `(soon)` and a tooltip — MS Graph integration is not yet wired.

---

## [2.1.0] — 2026-05-25

Detection & extraction overhaul aimed at photographed multi-card images (phone-camera shots, not just flatbed scans). Auto mode now reliably extracts every card in a 6×3 layout where it previously got 7/18.

### Added

- **Interactive preview phase** — between Upload and Extract. `POST /api/preview` runs detection-only (no LLM), returns an annotated JPEG + tile count + inferred grid dims. Lets you confirm tiling before committing to slow vision inference.
- **Draggable grid editor** (Grid mode) — `GridOverlay` React component renders dashed internal dividers + solid outer crop rectangle + drag handles. Move row/column lines, drag the 4 outer edges to crop margins, dim mask shows excluded area. Lines clamp at 2 % min gap; debounced re-preview fires 350 ms after any drag.
- **"Apply N×N grid" suggestion** — when Auto mode falls back to a grid layout, the preview returns the inferred `(rows, cols)` and a one-click banner offers to switch to Grid mode with those dims.
- **Auto-deskew toggle** — opt-in pre-detection warp via `_deskew_to_card_cluster()`: finds the convex region containing all cards using edge density + morphological close, then applies four-point perspective transform so cards become axis-aligned before detection. Skipped automatically if cluster is < 25 % of the image or rotation < 1.5°.
- **Per-tile card refinement** — `_refine_tile_to_card()` runs CLAHE + 3 parallel edge strategies (Canny low, Canny high, adaptive threshold) inside every grid tile to find the actual card boundary, then four-point-warps or tight-crops to it. Drops inter-card gap pixels that confuse the vision model.
- **Gap-detection regularization** — `_gap_detect_and_regularize()`: drops outer bands < 50 % of median height (margins), splits oversized bands > 160 % of median, and re-runs `_find_gap_positions()` _inside_ each oversized band to find the real missed gap (not just an equal split).
- **HEIC / HEIF / WEBP upload support** — file picker `accept` + drag-drop filter accept these formats; server falls back to Pillow + `pillow-heif` when `cv2.imdecode` returns None.
- **Inline error & warning banners** in the Scanner — replaces silent `console.error` failures. Per-event SSE `error`/`warning` stages now surface visibly in the right pane.

### Changed

- `_scan_generator` no longer calls `CardProcessor.process_batch()` directly. Auto / Single / Single-card-from-PDF all route through `_process_with_refinement()`, which keeps contour-based detections as-is (already perspective-corrected by the detector) but runs `_refine_tile_to_card()` on every contour-less rectangular tile.
- When Auto detector returns few cells (gap detection failing on a real grid), `_process_with_refinement()` overrides with `_gap_detect_and_regularize()` and refines each cell — this is what restored 18/18 extraction on `IMG_1544.heic`.
- Preview annotation skipped in Grid mode — server returns the raw JPEG and the React overlay draws _everything_ (boundaries, dim mask, drag handles, tile numbers). Eliminates the previous "double-rendering" mess where server-baked thick green lines overlapped with React's dashed lines.
- Auto preview uses gap-detection bounds instead of re-inferring a uniform grid from sample dimensions — the inferred grid dims now match what the detector actually used, not a fictional uniform grid.

### Fixed

- HEIC uploads from iPhone no longer fail with `Could not decode image: IMG_*.heic`.
- Preview now matches scan card count for Auto mode (was off by 5+ on photographed layouts because uniform-grid inference re-introduced phantom cells the detector had already filtered).
- Bottom row of cards in photographed grids no longer gets merged with the row above; the regularizer re-runs gap detection inside oversized bands to find the real divider.
- Scan timer / progress interval now clears on `done` and `error` events (was leaking until the component unmounted).

---

## [2.0.0] — 2026-05

Major architectural change: **Streamlit removed; FastAPI + React is now the only frontend.**

### Added

- **`server.py`** — FastAPI backend with REST + SSE streaming for the scan pipeline.
- **React UI** under `frontend/index.html` (and `business-card-reader/project/` design source).
- **Stop button** on the scanner with `POST /api/scan/stop` + per-card cancellation checkpoints in `CardProcessor.process_batch`.
- **Edit contact** action in the Contacts tab — reuses the EditModal, optimistic update, `PUT /api/contacts/{id}`.
- **MECARD support** in the QR parser, with widened "QR-sufficient" rules so vision is skipped more often.
- **Optional LLM post-correction pass** in the OCR parser pipeline.
- **`phonenumbers`** (Google libphonenumber) for international phone parsing — replaces ~40 lines of brittle BR-only regex.
- **`probablepeople`** (CRF) for name vs corporation classification — solves the "Banco do Brasil" / "Acme Corp" misclassification class.
- **Pydantic-style JSON schema** enforced via Ollama `format` for LLM vision models (guaranteed valid JSON output).
- **`qwen2.5vl`** added as fallback Ollama vision model.
- **`PORT`** env var for choosing the FastAPI bind port (default 8501).
- **CI workflow** (`.github/workflows/ci.yml`) with pytest matrix on Python 3.10/3.11/3.12, system deps for libheif/tesseract/zbar, signal-mode timeout + 5-min OS-level kill switch.
- **`.env.example`** documenting `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.
- **216-test suite** covering FastAPI routes (`tests/test_server.py`), QR parser (`tests/test_qr_reader.py`), VCF round-trip (`tests/test_vcf_generator.py`), OCR parser (`tests/test_ocr_parser.py`), models, history, providers, contacts repository, export processor, card processor, UI helpers.
- **macOS launcher** (`BusinessCardScanner.app`) — double-clickable Dock icon that starts the server and opens the browser, with a paired `StopBusinessCardScanner.app` for clean shutdown.

### Changed

- `pyproject.toml` bumped to **2.0.0**, `requires-python>=3.10`, black/ruff/mypy targets bumped to py310.
- Provider package now uses relative imports (`from ..models import …`) instead of `sys.path.insert` hacks.
- Claude Opus model ID corrected (`claude-opus-4-6` → `claude-opus-4-7`).
- `pillow>=10.3,<12` (CVE-2023-50447), `opencv-python>=4.9` (NumPy 2.0 ABI), `numpy>=1.26,<3`.
- History list endpoint stops re-reversing the already-sorted result — newest runs now appear first.
- History persistence call signature corrected (was raising TypeError silently every scan).

### Removed

- `app.py` (Streamlit UI), `start_app.sh`, `tests/test_app.py`.
- `utils/ms_graph.py` (Outlook 365 sync — never wired into the React UI; recoverable from git history if needed).
- Dead utils: `ocr_processor.py`, `csv_validator.py`, `logging_config.py`, `pdf_processor.py`, `pdf_memory_optimizer.py`, `performance_monitor.py`.
- Stale docs: `IMPLEMENTATION_SUMMARY.md`, `SESSION_SUMMARY.md`, `IMPROVEMENTS.md`, `DESIGN_IMPLEMENTATION_SUMMARY.md`, `RELEASE_NOTES_v1.1.0.md`, `RELEASE_NOTES_v1.2.0.md`.
- `assets/custom.css` (Streamlit-era stylesheet, no longer referenced).

---

## [1.3.0] - 2025-11-03

### 🎨 UI Improvements & Code Cleanup

#### Added

- **CSV Validator Module** (`utils/csv_validator.py`): Diagnostic tool for Outlook CSV compatibility
  - Validates CSV format, encoding, line endings, and field names
  - Generates detailed diagnostic reports
  - Detects common import issues
- **Test CSV Generator** (`test_csv_generation.py`): Generate test CSV files for Outlook compatibility testing
- **Exact Outlook CSV Format**: CSV export now matches Outlook's native export format exactly
  - 61 columns in exact Outlook order
  - Field positions match Outlook expectations (E-mail Address at position 9, Business Phone at position 14)
  - Based on analysis of actual Outlook CSV exports

#### Changed

- **UI Cleanup**: Major interface reorganization
  - Removed regular CSV export option (kept only Outlook CSV)
  - Individual cards now displayed as compact list format with smaller icons
  - Better visual separation between Individual Cards Management and Bulk Downloads sections
  - Export format selection simplified (VCF, Excel, Outlook CSV only)
- **Vision Mode Only**: Removed OCR+LLM processing mode
  - Application now uses Vision mode exclusively for better accuracy
  - Simplified sidebar configuration
  - Removed all OCR and LLM processor dependencies
- **Default Vision Model**: Changed to `llava:13b` (most accurate)
  - Previously defaulted to `llama3.2-vision`
  - Better extraction quality out of the box
- **Detection Mode Renamed**: "Improved Auto (Recommended)" renamed to "Automatic"
  - More intuitive naming
  - Removed old "Automatic" detection mode (based on CardDetector)
  - Only uses ImprovedCardDetector for automatic detection
- **Outlook CSV Format Options**: Added configurable field names
  - Support for "E-mail Address", "Email Address", or "Email"
  - Support for "Business Phone", "Phone", or "Work Phone"
  - Simplified format option for maximum compatibility
  - Quote/no-quote options for troubleshooting

#### Removed

- **OCR+LLM Mode**: Completely removed OCR+LLM processing option
  - Removed `OCRProcessor` imports and initialization
  - Removed `LLMProcessor` imports and initialization
  - Removed OCR language selection UI
  - Removed LLM model selection for OCR mode
- **Old Automatic Detection**: Removed legacy `CardDetector` mode
  - Removed `CardDetector` imports
  - Only uses `ImprovedCardDetector` for automatic detection
- **Regular CSV Export**: Removed standard CSV option
  - Users can still export to Excel or use Outlook CSV
  - Outlook CSV is now the primary CSV format

#### Fixed

- **Outlook CSV Import**: Fixed email and phone field import issues
  - CSV format now matches Outlook export exactly (tested successfully)
  - Proper field ordering and naming ensures automatic mapping
  - Email and phone fields now import correctly to Outlook

#### Technical

- Simplified codebase by removing unused OCR/LLM processing paths
- Reduced dependencies (no longer need OCRProcessor/LLMProcessor for main flow)
- Better separation of concerns in export module
- CSV validator enables troubleshooting import issues

## [1.2.0] - 2025-10-31

### 🆕 Major Feature: Multiple Export Formats

#### Added - Export Formats

- **CSV Export**: Universal spreadsheet format for Excel/Google Sheets
  - Includes source file column
  - UTF-8 encoding for international characters
  - Compatible with all spreadsheet applications
- **Excel (XLSX) Export**: Professional formatted workbooks
  - Auto-sized columns for readability
  - Bold header row
  - Optimized column widths (max 50 chars)
  - Native Excel format with openpyxl
- **Outlook Import CSV**: Special format for direct Outlook import
  - Outlook-specific column names (Business Phone, Job Title, etc.)
  - UTF-8 with BOM for perfect Excel/Outlook compatibility
  - Pre-formatted for seamless import workflow
- **Complete Export Package**: One-click ZIP download
  - Combines all selected formats
  - Individual VCF files in dedicated folder
  - Timestamped bulk exports (CSV, XLSX, Outlook CSV)
  - User selects which formats to include

#### Added - Export UI Enhancements

- **Format Selection Checkboxes**: Choose VCF, CSV, Excel, or Outlook CSV
- **Export Statistics**: Summary showing contacts with email/phone/company
- **Helpful Tooltips**: Explains each export format's purpose
- **Organized Layout**: Individual files on left, bulk downloads on right
- **Smart Defaults**: VCF and CSV enabled by default

#### Added - New Module

- `utils/export_processor.py`: Unified export handling
  - `contacts_to_dataframe()`: Convert contacts to pandas DataFrame
  - `export_to_csv()`: Generate CSV with optional source column
  - `export_to_excel()`: Create formatted XLSX workbooks
  - `export_to_outlook_csv()`: Outlook-compatible CSV format
  - `create_export_package()`: Multi-format ZIP generator
  - `get_export_stats()`: Calculate contact statistics

#### Changed

- Download section reorganized for better UX
- Export options now customizable per user preference
- ZIP package now includes multiple formats, not just VCF

#### Dependencies

- Added `pandas==2.0.3` for data manipulation
- Added `openpyxl==3.1.2` for Excel file generation

#### Benefits

- ✅ Import contacts into CRM systems via CSV
- ✅ Share formatted contact lists in Excel
- ✅ Direct Outlook import without VCF hassles
- ✅ Choose only the formats you need
- ✅ One download for all formats

---

## [1.1.0] - 2025-10-31 (improvements branch)

### 🎯 Major Feature: Vision Mode

#### Added (Latest Updates)

- **Vision Processor Module** (`utils/vision_processor.py`)
  - Direct image analysis using Ollama vision models
  - Supports: llama3.2-vision, llava, llava:13b, bakllava
  - Base64 image encoding and API integration
  - Intelligent JSON parsing with multiple fallback methods
  - Timeout handling (90s default)
  - Better accuracy than OCR for complex layouts

- **Processing Mode Toggle**
  - "Vision (Recommended)" - Direct image analysis
  - "OCR + LLM" - Traditional pipeline (backward compatible)
  - Dynamic UI that shows relevant options per mode

- **Improved QR Code Detection**
  - OpenCV QR detector as fallback when pyzbar unavailable
  - Dual detection methods (pyzbar + OpenCV)
  - Multiple preprocessing attempts for difficult QR codes
  - Detection method indicator (shows which library found the code)
  - More reliable detection overall

#### Fixed (Bug Fixes)

- **PNG Encoding**: Switched from JPEG to PNG for better reliability (fixes "0xff00 sequence" errors)
- **VCF Generation**: Added `_sanitize_contact_data()` to handle None/null values from vision model
- **QR Fallback**: Auto-uses QR code data when vision processing times out or fails
- **Image Validation**: Comprehensive checks for empty, corrupted, or malformed images
- **Memory Handling**: Fixed non-contiguous array issues and multi-format support

#### Changed

- QR detection now always attempts to read codes (no more "disabled" state)
- Sidebar UI adapts based on processing mode selected
- Better error messages with actionable suggestions
- App initialization handles missing models gracefully
- Timeout errors now gracefully fallback to QR data if available

#### Benefits of Vision Mode

- ✅ No more OCR errors on rotated/skewed text
- ✅ Better handling of complex card layouts
- ✅ Understands context better than OCR + text parsing
- ✅ Reduces processing steps (no OCR needed)
- ✅ More accurate for handwritten notes
- ✅ Better multi-language support (vision models handle any language)

#### Configuration

- **Configurable Timeout**: 60-300 seconds (default: 180s/3 min)
- Timeout slider in sidebar for user customization
- Visible timeout feedback in processing spinner

#### Trade-offs

- ⚠️ Slower: 30-60s per card vs 5-10s for OCR mode
- ⚠️ Higher memory usage (~4-8GB VRAM recommended)
- ⚠️ Requires vision model: `ollama pull llama3.2-vision`

#### Production Ready

- ✅ Handles 7+ cards in batch processing
- ✅ QR code fallback for timeout errors
- ✅ Robust error handling with graceful degradation
- ✅ All None/null values sanitized for VCF generation
- ✅ PNG encoding eliminates image format issues

---

## [1.0.0] - 2025-10-31

### 🎉 Initial Release

#### Added

- **Core Features**
  - Web-based interface using Streamlit
  - Multiple card detection modes (Improved Auto, Automatic, Manual Grid, Manual Single)
  - OCR text extraction with EasyOCR (English + Portuguese support)
  - QR code detection and decoding with pyzbar
  - LLM-powered contact parsing using Ollama
  - VCF file generation for Outlook contacts
  - Bulk processing with ZIP download

- **Detection Modes**
  - Improved Auto: Document scanner algorithm with perspective correction
  - Automatic: Contour-based detection with fallback
  - Manual Grid: Split images by rows/columns with adjustable margins
  - Manual Single: Process entire image as one card

- **User Interface**
  - Visual grid preview with overlay
  - Adjustable detection parameters (area %, margins)
  - Language selector for OCR (6 languages supported)
  - High contrast contact information display
  - Real-time processing feedback

- **Smart Processing**
  - Brazilian/Portuguese business card support
  - Phone number formatting (+55 country code)
  - OCR error correction (O→0, l→1 in numbers)
  - Company name recognition (Ltda, S.A., government entities)
  - Address parsing (Rua, Avenida, CEP codes)
  - QR code data prioritization over OCR

- **Documentation**
  - README with installation and usage instructions
  - QUICKSTART guide for beginners
  - TESTING guide with examples
  - Setup scripts (setup.sh, start_app.sh)

#### Technical Details

- **Dependencies**: Streamlit, OpenCV, EasyOCR, pyzbar, vobject, Ollama
- **Python Version**: 3.8+
- **Platform**: macOS (tested), Linux (should work), Windows (may need adjustments)
- **LLM Models**: Supports any Ollama model (llama3.2, mistral, etc.)

#### Known Limitations

- QR code reading requires zbar library and proper DYLD_LIBRARY_PATH
- Grid layout margins need manual adjustment for best results
- LLM quality varies by model selection
- Processing speed depends on OCR/LLM model sizes

---

## Future Versions

See the `improvements` branch for ongoing enhancements and the `IMPROVEMENTS.md` file for the roadmap.
