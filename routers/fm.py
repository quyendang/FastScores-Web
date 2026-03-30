from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/fm", tags=["FastMoments"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def fm_landing(request: Request):
    return templates.TemplateResponse("fm/index.html", {"request": request})


@router.get("/privacy", response_class=HTMLResponse)
async def fm_privacy(request: Request):
    return templates.TemplateResponse("fm/privacy.html", {"request": request})


@router.get("/support", response_class=HTMLResponse)
async def fm_support(request: Request):
    return templates.TemplateResponse("fm/support.html", {"request": request})
