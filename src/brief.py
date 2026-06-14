"""LLM-generated 'morning brief' synthesizing recent meeting notes.

Cached to disk so the web page can render instantly and regenerate on demand.
"""

import json
import os
from datetime import datetime

from .config import CONFIG, _BASE_DIR
from . import notes_index as ni

_CACHE_PATH = os.path.join(_BASE_DIR, ".scribe_brief.json")
_MAX_NOTE_CHARS = 1800  # cap per-note context to control tokens


def _brief_context(days: int) -> tuple[str, list]:
    notes = ni.recent_notes(days)
    if not notes:
        notes = ni.load_notes()[:5]  # fall back to the most recent few
    blocks = []
    for n in notes:
        body = n.body[:_MAX_NOTE_CHARS]
        blocks.append(f"### {n.title} ({n.date}, type: {n.type or 'general'})\n{body}")
    return "\n\n".join(blocks), notes


def generate_brief(days: int = 30) -> dict:
    """Generate the brief from recent notes, cache it, and return the cache dict."""
    from .processor import _call_llm  # lazy: avoids importing LLM SDKs unless used

    context, notes = _brief_context(days)
    cfg = CONFIG["processing"]
    user = ni.user_name()

    system = (
        f"You are {user}'s executive assistant writing their morning briefing. "
        "Address them DIRECTLY in the second person — use \"you\" and \"your\". Never refer to "
        f"them by name ({user}) or in the third person. Be concise and scannable (read in under "
        "a minute). Use markdown with these sections (omit any that are empty):\n"
        "## The gist — 2-3 sentences on where things stand, written to you.\n"
        "## Your next actions — concrete things you committed to or need to do, most important "
        "first. Bullet list.\n"
        "## Waiting on others — what others owe you, with the person's name.\n"
        "## Deadlines — anything time-sensitive, with the date.\n"
        "Do not invent items. Only use what's in the notes. If a section has nothing, leave it out."
    )
    prompt = f"Recent meeting notes:\n\n{context}\n\nWrite the briefing now."

    markdown_text = _call_llm(cfg.get("provider", "anthropic"), cfg["model"],
                              system, prompt, cfg.get("temperature", 0.3))

    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "note_count": len(notes),
        "markdown": markdown_text.strip(),
    }
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass
    return data


def cached_brief() -> "dict | None":
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
