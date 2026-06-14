"""Shared read/parse layer over the notes folder.

Source of truth is the markdown in `notes/` (frontmatter + body). This module
parses notes and action items and supports write-back (checking a to-do edits the
source `.md`). Used by the web front end; the MCP server can be consolidated onto
it later.
"""

import os
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta

import yaml

from .config import CONFIG

_CHECKBOX_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<mark>[ xX])\]\s+(?P<text>.*\S)\s*$")
_OWNER_RE = re.compile(r"^\*\*(?P<owner>.+?)\*\*:\s*(?P<rest>.*)$")
_DEADLINE_RE = re.compile(r"\s*\(by (?P<deadline>[^)]+)\)\s*$")


def notes_dir() -> str:
    return CONFIG["output"]["notes_dir"]


# ─── owner identity / bucketing ─────────────────────────────────────────────
# The LLM labels the user many different ways (Steven, "Steven (Valentine Home)",
# Steve, "speaker", "me"). We collapse those into one "mine" bucket, route named
# others to "waiting", and unlabeled items to "unassigned".

_UNASSIGNED_TOKENS = {"", "unassigned", "speaker", "unknown", "tbd", "n/a", "na", "none", "?"}


def user_identity() -> list[str]:
    u = CONFIG.get("user", {}) or {}
    raw_aliases = u.get("aliases") or []
    if isinstance(raw_aliases, str):
        raw_aliases = raw_aliases.split(",")  # UI stores aliases as a comma-separated string
    names = [str(u.get("name", "") or "")] + [str(a) for a in raw_aliases]
    return [n.strip() for n in names if n and n.strip()]


def _build_me_matcher():
    names = user_identity()
    if not names:
        return None
    pattern = "|".join(re.escape(n) for n in names)
    return re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE)


_ME_MATCHER = _build_me_matcher()


_SPEAKER_LABEL_RE = re.compile(r"^speaker[_ ]?\d+$", re.IGNORECASE)


def classify_owner(owner: str | None) -> str:
    """Return 'mine' | 'waiting' | 'unassigned' for an action item owner."""
    o = (owner or "").strip().lower()
    # Unresolved diarization labels (SPEAKER_00) aren't a real person.
    if o in _UNASSIGNED_TOKENS or _SPEAKER_LABEL_RE.match(o):
        return "unassigned"
    if _ME_MATCHER and _ME_MATCHER.search(owner or ""):
        return "mine"
    return "waiting"


@dataclass
class ActionItem:
    text: str          # human-facing task text (owner/deadline stripped out)
    raw: str           # the full text inside the checkbox, as written
    done: bool
    owner: str | None
    deadline: str | None
    note_filename: str
    note_title: str
    note_date: str
    line_no: int       # 0-based line index in the source file (for write-back)
    bucket: str = "unassigned"   # 'mine' | 'waiting' | 'unassigned'


@dataclass
class Note:
    filename: str
    title: str
    date: str
    time: str
    type: str
    topics: list[str]
    duration: str
    body: str
    meta: dict = field(default_factory=dict)


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Tolerant of malformed frontmatter."""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                return {}, raw
            if isinstance(meta, dict):
                return meta, parts[2].strip()
    return {}, raw


def _time_from_filename(filename: str) -> str:
    m = re.match(r"\d{8}_(\d{4})_", filename)
    return f"{m.group(1)[:2]}:{m.group(1)[2:]}" if m else ""


def load_notes() -> list[Note]:
    """All notes, newest first."""
    d = notes_dir()
    if not os.path.isdir(d):
        return []
    notes: list[Note] = []
    for name in sorted(os.listdir(d), reverse=True):
        if not name.endswith(".md") or name == "CLAUDE.md":
            continue
        path = os.path.join(d, name)
        try:
            raw = open(path, encoding="utf-8").read()
        except OSError:
            continue
        meta, body = _parse_frontmatter(raw)
        topics = meta.get("topics") or []
        if not isinstance(topics, list):
            topics = [str(topics)]
        notes.append(Note(
            filename=name,
            title=str(meta.get("title", name)),
            date=str(meta.get("date", "")),
            time=str(meta.get("time", "") or _time_from_filename(name)),
            type=str(meta.get("type", "")),
            topics=[str(t) for t in topics],
            duration=str(meta.get("duration", "")),
            body=body,
            meta=meta if isinstance(meta, dict) else {},
        ))
    return notes


def _split_action_item(inner: str) -> tuple[str, str | None, str | None]:
    """From the text inside a checkbox, pull out (task, owner, deadline)."""
    owner = None
    deadline = None
    text = inner.strip()

    m = _DEADLINE_RE.search(text)
    if m:
        deadline = m.group("deadline").strip()
        text = text[: m.start()].rstrip()

    m = _OWNER_RE.match(text)
    if m:
        owner = m.group("owner").strip()
        text = m.group("rest").strip()

    return text, owner, deadline


def action_items(include_done: bool = False) -> list[ActionItem]:
    """All checkbox action items across notes. Open items only unless include_done."""
    items: list[ActionItem] = []
    d = notes_dir()
    for note in load_notes():
        path = os.path.join(d, note.filename)
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            m = _CHECKBOX_RE.match(line)
            if not m:
                continue
            done = m.group("mark").lower() == "x"
            if done and not include_done:
                continue
            inner = m.group("text")
            task, owner, deadline = _split_action_item(inner)
            items.append(ActionItem(
                text=task, raw=inner, done=done, owner=owner, deadline=deadline,
                note_filename=note.filename, note_title=note.title,
                note_date=note.date, line_no=i, bucket=classify_owner(owner),
            ))
    return items


def toggle_action_item(filename: str, line_no: int, done: bool) -> bool:
    """Set the checkbox on `filename` at `line_no` to done/not-done in the source
    markdown. Returns True on success. Guards against the file having shifted by
    verifying the target line is still a checkbox."""
    d = notes_dir()
    # Containment: filename must resolve to a file directly inside notes_dir.
    path = os.path.normpath(os.path.join(d, filename))
    if os.path.dirname(path) != os.path.normpath(d) or not os.path.isfile(path):
        return False
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    if line_no < 0 or line_no >= len(lines):
        return False
    m = _CHECKBOX_RE.match(lines[line_no])
    if not m:
        return False
    new_mark = "x" if done else " "
    lines[line_no] = f"{m.group('indent')}- [{new_mark}] {m.group('text')}"
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return True


def user_name() -> str:
    names = user_identity()
    return names[0] if names else "Me"


def known_people() -> list[str]:
    """Distinct named owners that aren't the user (for the reassign dropdown)."""
    people = set()
    for it in action_items(include_done=True):
        if it.bucket == "waiting" and it.owner:
            people.add(it.owner.strip())
    return sorted(people)


def set_owner(filename: str, line_no: int, owner: str) -> bool:
    """Rewrite the owner of the action item at `filename:line_no` in the source
    markdown, preserving the task text, deadline, indent, and checkbox state."""
    d = notes_dir()
    path = os.path.normpath(os.path.join(d, filename))
    if os.path.dirname(path) != os.path.normpath(d) or not os.path.isfile(path):
        return False
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    if line_no < 0 or line_no >= len(lines):
        return False
    m = _CHECKBOX_RE.match(lines[line_no])
    if not m:
        return False
    task, _old_owner, deadline = _split_action_item(m.group("text"))
    label = (owner or "").strip() or "unassigned"
    inner = f"**{label}**: {task}"
    if deadline:
        inner += f" (by {deadline})"
    lines[line_no] = f"{m.group('indent')}- [{m.group('mark')}] {inner}"
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    return True


def _parse_note_date(value) -> "date | None":
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def recent_notes(days: int = 14) -> list[Note]:
    """Notes whose date is within the last `days` (newest first)."""
    today = date.today()
    out = []
    for n in load_notes():
        d = _parse_note_date(n.date)
        if d and 0 <= (today - d).days <= days:
            out.append(n)
    return out


def items_with_deadlines(include_done: bool = False) -> list[ActionItem]:
    """Open action items that carry a deadline string (any bucket)."""
    return [it for it in action_items(include_done=include_done) if it.deadline]


# ─── deadline date parsing ──────────────────────────────────────────────────
# Deadlines are freeform LLM text ("by Sept 1", "next week", "Phase 2"). Parse
# the ones that are actual dates (relative to the meeting date) so the brief can
# sort by urgency; leave vague ones (project phases, conditions) undated.

_DEADLINE_PREFIX = re.compile(
    r'^(by|before|due(?:\s+by|\s+on)?|no later than|around|on|starting|'
    r'the week of|week of|end of|eod|cob)\s+', re.I)
_deadline_cache: dict = {}


def parse_deadline(text: str | None, base_date: "date | None" = None) -> "date | None":
    """Best-effort parse of a freeform deadline into a date, relative to base_date
    (the meeting date). Returns None for non-date strings. Memoized."""
    if not text:
        return None
    key = (text, base_date.isoformat() if base_date else "")
    if key in _deadline_cache:
        return _deadline_cache[key]
    cleaned = _DEADLINE_PREFIX.sub('', text.strip()).strip()
    result = None
    if cleaned:
        try:
            import dateparser
            settings = {'PREFER_DATES_FROM': 'future', 'REQUIRE_PARTS': ['day', 'month']}
            if base_date:
                settings['RELATIVE_BASE'] = datetime(base_date.year, base_date.month, base_date.day)
            dt = dateparser.parse(cleaned, settings=settings)
            result = dt.date() if dt else None
        except Exception:
            result = None
    _deadline_cache[key] = result
    return result


def _relative_label(due: "date", today: "date") -> str:
    delta = (due - today).days
    if delta < 0:
        return "overdue" if delta == -1 else f"{-delta}d overdue"
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta <= 7:
        return f"in {delta} days"
    return due.strftime("%b %-d")


def deadline_view(items: list[ActionItem], today: "date | None" = None) -> list[dict]:
    """Annotate action items with a parsed due date + urgency status, sorted
    soonest/overdue first, undated last. status ∈ overdue|soon|later|nodate."""
    today = today or date.today()
    soon = today + timedelta(days=7)
    rows = []
    for it in items:
        due = parse_deadline(it.deadline, _parse_note_date(it.note_date))
        if due:
            status = "overdue" if due < today else ("soon" if due <= soon else "later")
            when = _relative_label(due, today)
        else:
            status, when = "nodate", it.deadline
        rows.append({"item": it, "due": due, "status": status, "when": when})
    rows.sort(key=lambda r: (r["due"] is None, r["due"] or date.max))
    return rows


def stats() -> dict:
    notes = load_notes()
    all_items = action_items(include_done=True)
    open_items = [it for it in all_items if not it.done]
    counts = {"mine": 0, "waiting": 0, "unassigned": 0}
    for it in open_items:
        counts[it.bucket] = counts.get(it.bucket, 0) + 1
    return {
        "note_count": len(notes),
        "open_action_items": len(open_items),
        "buckets": counts,
        "done": len(all_items) - len(open_items),
    }


def to_dict(obj) -> dict:
    return asdict(obj)
