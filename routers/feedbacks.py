import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services.supabase_client import get_supabase

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/feedbacks", response_class=HTMLResponse)
async def feedbacks_page(request: Request):
    db = get_supabase()
    resp = (
        db.table("feedbacks")
        .select("id, type, title, body, created_at, teacher_id, teachers(full_name, email)")
        .order("created_at", desc=True)
        .execute()
    )
    items = resp.data or []

    # Normalise nested teacher join
    for item in items:
        teacher = item.pop("teachers", None) or {}
        item["teacher_name"]  = teacher.get("full_name") or "—"
        item["teacher_email"] = teacher.get("email") or ""

    return templates.TemplateResponse(
        "feedbacks.html", {"request": request, "items": items}
    )
