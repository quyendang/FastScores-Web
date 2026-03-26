import os
import httpx
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/send", response_class=HTMLResponse)
async def send_page(request: Request):
    return templates.TemplateResponse("send.html", {"request": request})


@router.post("/send/push")
async def send_push(
    anon_key: str = Form(...),
    lang:     str = Form(...),
    title:    str = Form(...),
    message:  str = Form(...),
):
    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    if not supabase_url:
        return JSONResponse({"error": "SUPABASE_URL not configured on server"}, status_code=500)

    edge_url = f"{supabase_url}/functions/v1/send-notification"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                edge_url,
                headers={
                    "Authorization": f"Bearer {anon_key}",
                    "Content-Type": "application/json",
                },
                json={"lang": lang, "title": title, "message": message},
            )
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text}
        return JSONResponse(data, status_code=resp.status_code)
    except httpx.TimeoutException:
        return JSONResponse({"error": "Request timed out"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
