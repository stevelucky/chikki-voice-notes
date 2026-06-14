"""Scribe web front end.

  /         This Week — morning brief (deadlines, recent meetings, AI narrative)
  /actions  Action Center — Mine / Waiting / Unassigned to-do triage

Run from the repo root:
    conda activate scribe
    uvicorn web.app:app --reload
Then open http://localhost:8000
"""

import os
from collections import OrderedDict
from datetime import date

import markdown as _md
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src import notes_index as ni
from src import brief as brief_mod

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "static")
templates = Jinja2Templates(directory=os.path.join(_HERE, "templates"))

app = FastAPI(title="Scribe")
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Browsers request /favicon.ico automatically; serve the small PNG.
    return FileResponse(os.path.join(_STATIC, "favicon.png"), media_type="image/png")


def _render_md(text: str) -> str:
    return _md.markdown(text or "", extensions=["extra", "sane_lists"])


_VALID_BUCKETS = {"mine", "waiting", "unassigned", "done"}


def _reassign_ctx() -> dict:
    """Context the reassign dropdown needs in any template that renders items."""
    return {"owners": ni.known_people(), "user_name": ni.user_name()}


def _group_items(bucket: str = "mine", query: str = ""):
    """Action items for the given view, grouped by source note (newest first),
    with an optional text filter. The 'done' view shows completed items across
    all buckets; the others show open items in that bucket."""
    if bucket == "done":
        items = [it for it in ni.action_items(include_done=True) if it.done]
    else:
        items = [it for it in ni.action_items(include_done=False) if it.bucket == bucket]
    q = query.strip().lower()
    filtered = [
        it for it in items
        if (not q or q in it.text.lower() or q in it.note_title.lower()
            or (it.owner and q in it.owner.lower()))
    ]

    groups: "OrderedDict[str, dict]" = OrderedDict()
    for it in filtered:
        g = groups.get(it.note_filename)
        if g is None:
            g = {
                "note_filename": it.note_filename,
                "note_title": it.note_title,
                "note_date": it.note_date,
                "items": [],
            }
            groups[it.note_filename] = g
        g["items"].append(it)
    return list(groups.values())


@app.get("/", response_class=HTMLResponse)
def this_week(request: Request):
    """Morning brief: AI narrative (cached) + deadlines + recent meetings."""
    cached = brief_mod.cached_brief()
    deadlines = ni.deadline_view(ni.items_with_deadlines())
    return templates.TemplateResponse(request, "brief.html", {
        "nav": "brief",
        "deadlines": deadlines[:12],
        "deadlines_total": len(deadlines),
        "recent": ni.recent_notes(30),
        "brief": cached,
        "brief_html": _render_md(cached["markdown"]) if cached else None,
        "today": date.today().strftime("%A, %B %-d, %Y"),
    })


@app.post("/brief/generate", response_class=HTMLResponse)
def brief_generate(request: Request):
    data = brief_mod.generate_brief(days=30)
    return templates.TemplateResponse(request, "_aibrief.html", {
        "brief": data, "brief_html": _render_md(data["markdown"]),
    })


@app.get("/actions", response_class=HTMLResponse)
def dashboard(request: Request, bucket: str = "mine", q: str = ""):
    bucket = bucket if bucket in _VALID_BUCKETS else "mine"
    return templates.TemplateResponse(request, "dashboard.html", {
        "nav": "actions",
        "groups": _group_items(bucket, q),
        "bucket": bucket,
        "q": q,
        "stats": ni.stats(),
        **_reassign_ctx(),
    })


@app.get("/stats")
def stats_json():
    """Live counts for the header + tab badges (fetched after toggles/clears)."""
    return ni.stats()


@app.get("/items", response_class=HTMLResponse)
def items(request: Request, bucket: str = "mine", q: str = ""):
    """Filtered list partial (htmx target)."""
    bucket = bucket if bucket in _VALID_BUCKETS else "mine"
    return templates.TemplateResponse(request, "_list.html", {
        "groups": _group_items(bucket, q), "bucket": bucket, **_reassign_ctx(),
    })


def _reread_item(filename: str, line_no: int):
    return next(
        (it for it in ni.action_items(include_done=True)
         if it.note_filename == filename and it.line_no == line_no),
        None,
    )


@app.post("/action-items/toggle", response_class=HTMLResponse)
def toggle(request: Request, filename: str = Form(...), line_no: int = Form(...),
           done: bool = Form(False)):
    # Re-render the row in place (struck-through when done) so an accidental check
    # is reversible — just uncheck. Completed rows leave the open view only on the
    # next list refresh ("Clear completed" button, filter, or reload).
    ni.toggle_action_item(filename, line_no, done)
    item = _reread_item(filename, line_no)
    return templates.TemplateResponse(request, "_item.html", {"item": item, **_reassign_ctx()})


@app.post("/action-items/reassign", response_class=HTMLResponse)
def reassign(request: Request, filename: str = Form(...), line_no: int = Form(...),
             owner: str = Form(...)):
    ni.set_owner(filename, line_no, owner)
    item = _reread_item(filename, line_no)
    return templates.TemplateResponse(request, "_item.html", {"item": item, **_reassign_ctx()})
