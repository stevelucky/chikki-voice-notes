"""Apply a natural-language correction to an existing note and regenerate it.

The user reviews a freshly-generated note, spots a mistake (classically a reversed
speaker attribution — "I'm the host, not Dwight"), and describes the fix in plain
English. Rather than hand-editing the fix throughout a long markdown file, we
re-extract the note from its *original transcript* with the correction injected as
authoritative context, so it propagates everywhere — title, summary, action item
owners, decisions, quotes.

Checked-off action items are preserved across the regeneration by matching task
text. Owners are intentionally NOT preserved: fixing attribution is usually the
whole point of the correction, so the LLM must be free to reassign them.
"""

import difflib
import json
import os
import re
import shutil
from datetime import datetime

from .config import CONFIG
from . import notes_index as ni


def _notes_dir() -> str:
    return CONFIG["output"]["notes_dir"]


def _transcripts_dir() -> str:
    return os.path.join(os.path.dirname(_notes_dir()), "transcripts")


def _history_dir() -> str:
    return os.path.join(_notes_dir(), ".history")


def resolve_note(filename: str) -> "str | None":
    """Resolve a bare filename to a path directly inside notes_dir, or None.

    Guards against path traversal / absolute paths — note files live flat in
    notes_dir, so anything resolving elsewhere is rejected.
    """
    d = os.path.normpath(_notes_dir())
    path = os.path.normpath(os.path.join(d, filename))
    if os.path.dirname(path) != d or not os.path.isfile(path):
        return None
    return path


def _base_of(filename: str) -> str:
    return filename[:-3] if filename.endswith(".md") else filename


def latest_note() -> "str | None":
    """Filename of the most recently dated note (notes are named
    YYYYMMDD_HHMM_…, so a reverse sort puts the newest first)."""
    d = _notes_dir()
    if not os.path.isdir(d):
        return None
    notes = sorted(
        (f for f in os.listdir(d) if f.endswith(".md") and f != "CLAUDE.md"),
        reverse=True,
    )
    return notes[0] if notes else None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _load_transcript(base: str) -> "dict | None":
    """Load the original transcript for a note. Prefer the structured JSON
    (keeps segments for chunking/formatting); fall back to the plain .txt."""
    tdir = _transcripts_dir()
    jpath = os.path.join(tdir, base + ".json")
    if os.path.isfile(jpath):
        try:
            with open(jpath, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    tpath = os.path.join(tdir, base + ".txt")
    if os.path.isfile(tpath):
        try:
            return {"text": open(tpath, encoding="utf-8").read(), "segments": [], "language": "en"}
        except OSError:
            pass
    return None


def _timestamp_from_base(base: str):
    """Parse the recording datetime from a base filename (YYYYMMDD_HHMM_…)."""
    m = re.match(r"(\d{8})_(\d{4})", base)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
        except ValueError:
            pass
    return None


def _snapshot_items(filename: str) -> "list[dict]":
    """Capture the done-state and user note of each action item that carries
    either, keyed by normalized task text — so they can be re-applied after the
    note is regenerated from the transcript."""
    snap = []
    for it in ni.action_items(include_done=True):
        if it.note_filename == filename and (it.done or it.note):
            snap.append({"text": _normalize(it.text), "done": it.done, "note": it.note})
    return snap


def _reapply_items(filename: str, snapshot: "list[dict]") -> dict:
    """Re-apply remembered checkmarks and notes to the regenerated note, matching
    on task text (exact-normalized first, then fuzzy ratio >= 0.85). Each remembered
    item is consumed once. Returns counts of what was restored.

    Edits ride on each item's own line and don't shift line numbers, so the
    line_no captured while iterating stays valid for both set_note and toggle.
    """
    if not snapshot:
        return {"done": 0, "notes": 0}
    remaining = list(snapshot)
    restored_done = restored_notes = 0
    for it in ni.action_items(include_done=True):
        if it.note_filename != filename or not remaining:
            continue
        cand = _normalize(it.text)
        match = next((e for e in remaining if e["text"] == cand), None)
        if match is None:
            best, best_ratio = None, 0.0
            for e in remaining:
                r = difflib.SequenceMatcher(None, cand, e["text"]).ratio()
                if r > best_ratio:
                    best, best_ratio = e, r
            if best is not None and best_ratio >= 0.85:
                match = best
        if match is None:
            continue
        remaining.remove(match)
        if match["note"] and ni.set_note(filename, it.line_no, match["note"]):
            restored_notes += 1
        if match["done"] and ni.toggle_action_item(filename, it.line_no, True):
            restored_done += 1
    return {"done": restored_done, "notes": restored_notes}


def _backup(path: str, base: str) -> str:
    """Snapshot the current note into notes/.history/ before overwriting it."""
    hist = _history_dir()
    os.makedirs(hist, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(hist, f"{base}.{stamp}.bak.md")
    shutil.copy2(path, dest)
    return dest


def latest_backup(filename: str) -> "str | None":
    base = _base_of(filename)
    hist = _history_dir()
    if not os.path.isdir(hist):
        return None
    cands = sorted(
        (f for f in os.listdir(hist) if f.startswith(base + ".") and f.endswith(".bak.md")),
        reverse=True,
    )
    return os.path.join(hist, cands[0]) if cands else None


def has_backup(filename: str) -> bool:
    return latest_backup(filename) is not None


def undo(filename: str) -> bool:
    """Restore the most recent backup over the current note, consuming it
    (single-level undo per correction)."""
    path = resolve_note(filename)
    bak = latest_backup(filename)
    if not path or not bak:
        return False
    shutil.move(bak, path)
    return True


def correct_note(filename: str, correction: str) -> dict:
    """Regenerate a note from its original transcript, applying an authoritative
    user correction. Overwrites the note in place (same filename + date) and
    re-applies any previously checked-off items.

    Returns a result dict: {ok, error?, title, action_items, checkmarks_restored}.
    """
    from .processor import Processor
    from .output import write_note

    correction = (correction or "").strip()
    if not correction:
        return {"ok": False, "error": "Please describe the correction."}

    path = resolve_note(filename)
    if not path:
        return {"ok": False, "error": f"Note not found: {filename}"}

    base = _base_of(filename)
    meta, _ = ni._parse_frontmatter(open(path, encoding="utf-8").read())

    transcript = _load_transcript(base)
    if not transcript or not transcript.get("text", "").strip():
        return {"ok": False, "error": "Original transcript not found — this note can't be regenerated."}

    mtype = str(meta.get("type") or "default")
    try:
        p = Processor(meeting_type=mtype)
    except ValueError:
        p = Processor()  # note's type is no longer defined — fall back to default

    snapshot = _snapshot_items(filename)
    _backup(path, base)

    processed = p.process(transcript["text"], correction=correction)

    write_note(
        processed, transcript,
        audio_path=str(meta.get("audio") or ""),
        duration=meta.get("duration") or 0,
        base_name=base, timestamp=_timestamp_from_base(base),
    )

    restored = _reapply_items(filename, snapshot)
    return {
        "ok": True,
        "title": processed.get("title", "Untitled"),
        "action_items": len(processed.get("action_items", [])),
        "checkmarks_restored": restored["done"],
        "notes_restored": restored["notes"],
    }
