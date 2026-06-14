# Fix Checklist — Scribe

Generated from full-codebase review (Python pipeline, CLI/MCP/config, Swift menu bar app).

**Status: all 53 review items fixed ✅**, plus a batch of follow-up fixes found during
real-world testing (see the bottom section). Python: 14 tests pass. Swift: builds clean.

---

## 🔴 Critical (broken functionality or security)

- [x] **1. Long meetings crash — `process_chunked` calls nonexistent `self._call_llm`.**
  Fixed the dispatch to the module-level `_call_llm` with the correct signature; added a `process_chunked` regression test (+ chunk-split and JSON-parse tests).

- [x] **2. MCP server path traversal — arbitrary file read.**
  `read_note`/`get_action_items` now resolve + contain paths under `NOTES_DIR`; `../.env` and absolute paths are rejected (verified).

- [x] **3. One malformed note breaks the entire MCP server.**
  Note titles are YAML-escaped on write (via `json.dumps`, verified round-trip); `_parse_note` tolerates malformed frontmatter instead of raising.

---

## 🟠 Major — Python pipeline

- [x] **4. stdout protocol violation in transcriber fallback.** Routed to stderr; transformers fallback now raises a clear "install torch/transformers/scipy" error instead of a cryptic `ImportError`.
- [x] **5. Chunked-mode output schema mismatch.** Synthesis prompt emits `title`/`summary`; `due` → `deadline`; added a dedicated `## Sections` renderer; internal `_`-keys no longer leak into notes.
- [x] **6. Fragile JSON fallback + stderr violations.** Hardened parsing path; all `process_chunked` prints go to stderr.
- [x] **7. Anthropic least-protected branch.** `max_tokens` raised to 8192 with a truncation warning on `stop_reason == max_tokens`.
- [x] **8. `max_duration_minutes` never enforced.** Enforced as a safety cap in the `record`/`quick` loops.
- [x] **9. `process-latest` reports "No recordings found." as success.** Now goes to stderr with a non-zero exit.

---

## 🟠 Major — Swift menu bar app

- [x] **10. `cancelRecording()` can delete the wrong recording.** Snapshots recordings at start; cancel deletes only files created this session.
- [x] **11. Launch failures swallowed → phantom recording state.** Launch the recorder first; only enter recording state if it actually starts.
- [x] **12. No reentrancy guard on processing.** Single-pipeline guard added.
- [x] **13. Quitting mid-processing orphans the pipeline; no cancel.** Pipeline process tracked in a thread-safe box and terminated on quit.
- [x] **14. "Quick Process" shortcut does nothing.** Handler registered (now wired to the file picker — see field fixes).
- [x] **15. Speaker enrollment deadlocks + hot-mic + main-thread hang.** stderr streamed concurrently; delete moved off main thread; sheet cleans up the recorder on dismiss.
- [x] **16. Settings "Model" field silently never saves.** Blank-line section-tracking bug fixed; write failures now surfaced ("Save failed…").
- [x] **17. build.sh can install a stale binary.** `set -euo pipefail` + explicit `xcodebuild` status check via `PIPESTATUS`; Xcode presence check; nested-bundle signing (dropped `--deep`).

---

## 🟠 Major — packaging & docs

- [x] **18. Install docs point at a nonexistent app.** install.sh/README now reference `Scribe.app`; prereq check requires full Xcode (`xcodebuild`).
- [x] **19. Undeclared dependencies.** Added `mcp`, `parakeet-mlx`, `pytest` to `environment.yml`/`requirements.txt`.
- [x] **20. CLAUDE.md describes things that don't exist.** Created `docs/adr/` + `docs/IMPROVEMENTS.md`; removed the inaccurate "openclaw" claim.

---

## 🟡 Minor

### Recorder
- [x] **21.** Empty-file check now uses actual frame count (FLOAT-WAV safe). 
- [x] **22.** `_emergency_save` stops the writer before closing the file.
- [x] **23.** `_switch_stream` stops the old stream before starting the new one.
- [x] **24.** Bare-filename `output_path` no longer crashes `os.makedirs`.
- [x] **25.** Writer-join timeout now warns about possible lost tail audio.

### Processor / output
- [x] **26.** Docstring placement fixed. 
- [x] **27.** Parsed JSON type-checked (dict). 
- [x] **28.** JSON-parse logic consolidated. 
- [x] **29.** LLM SDKs imported lazily per provider. 
- [x] **30.** Filename collisions get a `-2`, `-3`, … suffix. 
- [x] **31.** `format_slack_message` has the dict guard. 
- [x] **32.** Dead `_SKIP_KEYS` condition removed.

### CLI
- [x] **33.** `quick` timer writes to stderr. 
- [x] **34.** `--slack` preview goes to stderr. 
- [x] **35.** "Latest recording" restricted to `recording_YYYYMMDD_HHMMSS.wav`. 
- [x] **36.** `_compress_audio` logs failures. 
- [x] **37.** `diarizing` stage emitted by `process` too and added to Swift `stageOrder`.

### Swift
- [x] **38.** Timers run in `.common` run-loop mode (don't freeze with menu open).
- [x] **39.** Stage-marker parsing line-buffered across pipe-read boundaries.
- [x] **40.** Conda env name centralized to one overridable source; project-dir fallbacks updated.
- [x] **41.** Speaker window reloads profiles each time it's shown.
- [x] **42.** Stop waits with a 15s timeout, then force-terminates.
- [x] **43.** `Info.plist` declares `LSMinimumSystemVersion 14.0`.

### MCP server
- [x] **44.** `NOTES_DIR` honors `config.yaml`'s `output.notes_dir`.
- [x] **45.** `date.fromisoformat` guarded on args + frontmatter.
- [x] **46.** `get_action_items` has the same fuzzy filename matching as `read_note`.

### Config / env drift
- [x] **47.** Dead config keys removed.
- [x] **48.** `.env.example` reference corrected.
- [x] **49.** `.env` parser handles inline comments + `export`.
- [x] **50.** Empty `config.yaml` raises a clear error instead of an opaque crash.

### Naming drift
- [x] **51.** Consolidated to **Scribe** across the codebase; conda env migrated `chikki` → `scribe`; `SingdanaApp.swift` → `ScribeApp.swift`.
- [x] **52.** `src/menubar.py` (legacy rumps app) rebranded and cleaned (dead hotkey read removed). Kept as a working `menubar` CLI command rather than deleted; revisit if it stays unused.

### Tests
- [x] **53.** Added coverage for `Processor.process`, `process_chunked`, chunk splitting, and JSON parsing (4 → 14 tests).

---

## ➕ Follow-up fixes (found during real-world testing)

- [x] **Orphaned recorder held the mic.** Stop signalled only the `zsh` wrapper, orphaning the Python recorder (mic stayed on, nothing processed). Now launches subprocesses with `exec` so signals hit Python directly; added a launch-time cleanup of stray `src.cli record` processes.
- [x] **Menu items "hopped" / wrong-row highlight during recording & processing.** The per-second timer mutated `@Published` state the dropdown observed, re-bridging the open NSMenu every second. Moved the per-second menu-bar icon into a separate `StatusIconModel` observed only by the icon, so the dropdown re-renders only on real state changes.
- [x] **Dropdown showed a stale keyboard shortcut.** Replaced the hardcoded `⌘⇧R` with the library's `.globalKeyboardShortcut(name)`, which displays the user's current shortcut and updates live.
- [x] **Quick Process repurposed.** The "Process Audio File" shortcut now opens a picker for *any* audio file (instead of re-processing the latest recording).
- [x] **Conda env rename `chikki` → `scribe`.** Cloned the env, flipped all code defaults, kept `chikki` as a rollback. Procedure documented in `docs/IMPROVEMENTS.md`.
