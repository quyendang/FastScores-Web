import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from routers import report, student, send, feedbacks, fm as fm_router

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="FastScores Web", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Jinja2 custom filter ──────────────────────────────────────────────────────
def comma_format(value):
    try:
        return f"{float(value):,.0f}"
    except Exception:
        return value

templates.env.filters["comma"] = comma_format

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(report.router)
app.include_router(student.router)
app.include_router(send.router)
app.include_router(feedbacks.router)
app.include_router(fm_router.router)


# ── Static pages ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/support", response_class=HTMLResponse)
async def support(request: Request):
    return templates.TemplateResponse("support.html", {"request": request})


@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

@app.get("/fr-support", response_class=HTMLResponse)
async def support(request: Request):
    return templates.TemplateResponse("fastremindsupport.html", {"request": request})


@app.get("/fr-privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("fastremindprivacy.html", {"request": request})



@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Background scheduler (crypto bot) ────────────────────────────────────────
@app.on_event("startup")
def start_bot_scheduler():
    from services.bot_service import symbols_tracker_job, send_startup_market_analysis

    def _job():
        try:
            symbols_tracker_job()
        except Exception as e:
            logging.error(f"[SCHEDULER] symbols_tracker_job error: {e}")

    try:
        send_startup_market_analysis()
        logging.info("[SCHEDULER] Startup market analysis sent")
    except Exception as e:
        logging.error(f"[SCHEDULER] startup market analysis error: {e}")

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _job,
        "interval",
        minutes=10,
        id="symbols_tracker_job",
        replace_existing=True,
        next_run_time=datetime.utcnow(),
    )
    scheduler.start()
    logging.info("[SCHEDULER] Bot scheduler started (tracker: 10 min)")
