"""
MCP server exposing Scribe meeting notes to Claude.

Tools:
  list_notes        — list all notes with metadata
  read_note         — read a full note by filename
  search_notes      — keyword / topic / date-range search across notes
  get_action_items  — extract open [ ] action items (all notes or one)
"""

import re
from datetime import date
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP


def _notes_dir() -> Path:
    """Resolve the notes directory, honoring config.yaml's output.notes_dir
    (which src.config resolves to an absolute path). Falls back to ./notes."""
    default = (Path(__file__).parent / "notes").resolve()
    try:
        from src.config import CONFIG
        configured = CONFIG.get("output", {}).get("notes_dir")
        if configured:
            return Path(configured).resolve()
    except Exception:
        pass
    return default


NOTES_DIR = _notes_dir()

mcp = FastMCP("scribe-notes")


# ─── helpers ──────────────────────────────────────────────────────────────────

def _resolve_note_path(filename: str) -> Path | None:
    """Resolve a user-supplied filename to a path *inside* NOTES_DIR.

    Returns None if the resolved path escapes NOTES_DIR (path traversal /
    absolute path) — the caller turns that into a friendly error.
    """
    # Reject anything that isn't a bare filename up front; note files live
    # flat in NOTES_DIR, so a path separator is always suspicious.
    candidate = (NOTES_DIR / filename).resolve()
    try:
        candidate.relative_to(NOTES_DIR)
    except ValueError:
        return None
    return candidate


def _parse_note(path: Path) -> dict:
    """Return frontmatter dict + body text for a note file.

    Tolerant of malformed frontmatter: a note with broken YAML or a missing
    closing fence is returned with empty metadata rather than raising, so one
    bad note can't break list/search/action-item queries across all notes.
    """
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            _, fm, body = parts
            try:
                meta = yaml.safe_load(fm) or {}
            except yaml.YAMLError:
                meta, body = {}, raw
            if not isinstance(meta, dict):
                meta = {}
    meta["_filename"] = path.name
    meta["_body"] = body.strip()
    return meta


def _all_notes() -> list[dict]:
    notes = []
    for p in sorted(NOTES_DIR.glob("*.md"), reverse=True):
        if p.name == "CLAUDE.md":
            continue
        try:
            notes.append(_parse_note(p))
        except OSError:
            continue
    return notes


def _time_from_filename(filename: str) -> str:
    """Extract HH:MM from Scribe filename format YYYYMMDD_HHMM_title.md."""
    m = re.match(r"\d{8}_(\d{4})_", filename)
    if m:
        t = m.group(1)
        return f"{t[:2]}:{t[2:]}"
    return ""


def _meta_summary(note: dict) -> str:
    """One-line summary suitable for list output."""
    title = note.get("title", note["_filename"])
    date_str = str(note.get("date", ""))
    time_str = _time_from_filename(note["_filename"])
    duration = note.get("duration", "")
    topics = note.get("topics", [])
    topics_str = ", ".join(topics[:5]) if topics else ""
    return (
        f"**{title}**\n"
        f"  file: {note['_filename']}\n"
        f"  date: {date_str} {time_str}  duration: {duration}\n"
        f"  topics: {topics_str}"
    )


# ─── tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_notes(limit: int = 20) -> str:
    """
    List Scribe meeting notes, newest first.

    Args:
        limit: Maximum number of notes to return (default 20).

    Returns:
        A formatted list of notes with title, date, duration, and topics.
    """
    notes = _all_notes()[:limit]
    if not notes:
        return "No notes found."
    return "\n\n".join(_meta_summary(n) for n in notes)


@mcp.tool()
def read_note(filename: str) -> str:
    """
    Read the full content of a Scribe note.

    Args:
        filename: The markdown filename (e.g.
            '20260505_1304_Valentine Home Comfort — Founding Planning Session.md').
            Use list_notes to discover filenames.

    Returns:
        The complete note including frontmatter and body.
    """
    path = _resolve_note_path(filename)
    if path is None:
        return f"Invalid filename: {filename}"
    if not path.exists():
        # fuzzy match on prefix (only within NOTES_DIR)
        candidates = [p for p in NOTES_DIR.glob("*.md") if filename in p.name]
        if len(candidates) == 1:
            path = candidates[0]
        elif len(candidates) > 1:
            names = "\n".join(p.name for p in candidates)
            return f"Multiple matches — be more specific:\n{names}"
        else:
            return f"Note not found: {filename}"
    return path.read_text(encoding="utf-8")


@mcp.tool()
def search_notes(
    query: str = "",
    topic: str = "",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """
    Search Scribe meeting notes by keyword, topic, or date range.

    Args:
        query:     Case-insensitive keyword to search in title + body.
        topic:     Filter to notes whose topics list contains this string.
        date_from: ISO date string (YYYY-MM-DD) — include notes on or after.
        date_to:   ISO date string (YYYY-MM-DD) — include notes on or before.

    Returns:
        Matching notes with one-line summaries; up to 10 results.
    """
    notes = _all_notes()
    results = []

    try:
        df = date.fromisoformat(date_from) if date_from else None
        dt = date.fromisoformat(date_to) if date_to else None
    except ValueError:
        return "Invalid date filter — use ISO format YYYY-MM-DD."

    for note in notes:
        # date filter
        note_date = note.get("date")
        if note_date:
            if isinstance(note_date, str):
                try:
                    note_date = date.fromisoformat(note_date)
                except ValueError:
                    note_date = None
            if note_date is not None:
                if df and note_date < df:
                    continue
                if dt and note_date > dt:
                    continue

        # topic filter
        if topic:
            topics = [t.lower() for t in (note.get("topics") or [])]
            if not any(topic.lower() in t for t in topics):
                continue

        # keyword filter
        if query:
            haystack = (
                note.get("title", "") + " " + note["_body"]
            ).lower()
            if query.lower() not in haystack:
                continue

        results.append(note)
        if len(results) >= 10:
            break

    if not results:
        return "No matching notes."
    return "\n\n".join(_meta_summary(n) for n in results)


@mcp.tool()
def get_action_items(filename: str = "") -> str:
    """
    Extract open (unchecked) action items from notes.

    Args:
        filename: If provided, extract only from that note.
                  If empty, extract from all notes.

    Returns:
        Grouped list of open action items with their source note.
    """
    if filename:
        path = _resolve_note_path(filename)
        if path is None:
            return f"Invalid filename: {filename}"
        if not path.exists():
            # fuzzy match on prefix, mirroring read_note
            candidates = [p for p in NOTES_DIR.glob("*.md") if filename in p.name]
            if len(candidates) == 1:
                path = candidates[0]
            else:
                return f"Note not found: {filename}"
        notes = [_parse_note(path)]
    else:
        notes = _all_notes()

    pattern = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
    output = []

    for note in notes:
        items = pattern.findall(note["_body"])
        if items:
            title = note.get("title", note["_filename"])
            output.append(f"### {title}\n" + "\n".join(f"- [ ] {i}" for i in items))

    if not output:
        return "No open action items found."
    return "\n\n".join(output)


if __name__ == "__main__":
    mcp.run()
