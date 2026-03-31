from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/fm", tags=["FastMoments"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def fm_landing(request: Request, lang: str = Query(default="en")):
    return templates.TemplateResponse("fm/index.html", {"request": request, "lang": lang})


@router.get("/privacy", response_class=HTMLResponse)
async def fm_privacy(request: Request, lang: str = Query(default="en")):
    return templates.TemplateResponse("fm/privacy.html", {"request": request, "lang": lang})


@router.get("/support", response_class=HTMLResponse)
async def fm_support(request: Request, lang: str = Query(default="en")):
    return templates.TemplateResponse("fm/support.html", {"request": request, "lang": lang})
