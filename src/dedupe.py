"""LLM-assisted duplicate detection for open action items.

Meetings are extracted independently, so the same real task often appears several
times worded differently across notes. This proposes groups of items that are the
same underlying task; the user approves each group and the dashboard consolidates
them via the existing merge engine (notes_index.set_merge).
"""

from .config import CONFIG
from . import notes_index as ni
from .processor import _call_llm, Processor

_MAX_ITEMS = 80  # cap items sent to the LLM to bound tokens

_SYSTEM = (
    "You help consolidate a meeting to-do list. You'll get a numbered list of open "
    "action items, each with its owner and source meeting. Identify groups of items "
    "that refer to the SAME underlying task — duplicates or near-duplicates, even if "
    "worded differently or raised in different meetings.\n\n"
    "Be CONSERVATIVE: only group items you are confident are the same actionable task. "
    "Do NOT group items that are merely related, share a topic, or are sequential steps "
    "of a larger effort. When in doubt, leave an item on its own.\n\n"
    "Return JSON of this exact shape:\n"
    '{"groups": [{"ids": [<item numbers>], "label": "<short canonical phrasing of the task>"}]}\n'
    "Only include groups with 2+ items. If there are no duplicates, return "
    '{"groups": []}. Do not invent items or ids.'
)


def _open_unmerged() -> list:
    """Open, not-yet-merged action items eligible for de-duplication."""
    return [
        it for it in ni.action_items(include_done=False)
        if it.merge_id == "" and it.bucket in ("mine", "waiting", "unassigned")
    ]


def find_duplicate_groups(max_items: int = _MAX_ITEMS) -> dict:
    """Return {groups, scanned, truncated}. Each group: {label, members:[ActionItem]}."""
    items = _open_unmerged()
    scanned = items[:max_items]
    truncated = len(items) > max_items
    if len(scanned) < 2:
        return {"groups": [], "scanned": len(scanned), "truncated": truncated}

    lines = [
        f"{i}. {it.text}  [owner: {it.owner or 'unassigned'}; meeting: {it.note_title}]"
        for i, it in enumerate(scanned)
    ]
    prompt = "Open action items:\n" + "\n".join(lines)

    cfg = CONFIG["processing"]
    raw = _call_llm(cfg.get("provider", "anthropic"), cfg["model"], _SYSTEM, prompt,
                    temperature=0.1)
    try:
        data = Processor._parse_json_response(raw)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    groups = []
    for g in (data.get("groups") or []):
        members, seen = [], set()
        for x in (g.get("ids") or []):
            try:
                idx = int(x)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(scanned):
                it = scanned[idx]
                key = (it.note_filename, it.line_no)
                if key not in seen:
                    seen.add(key)
                    members.append(it)
        if len(members) >= 2:
            label = str(g.get("label") or "").strip() or members[0].text
            groups.append({"label": label, "members": members})

    return {"groups": groups, "scanned": len(scanned), "truncated": truncated}
