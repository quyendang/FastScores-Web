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

from routers import report, student
from routers import bot as bot_router

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
app.include_router(bot_router.router)


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


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Background scheduler (crypto bot) ────────────────────────────────────────
@app.on_event("startup")
def start_bot_scheduler():
    from services.supabase_client import get_bot_supabase
    from services.bot_service import symbols_tracker_job, poll_telegram_commands

    def _job():
        try:
            symbols_tracker_job(get_bot_supabase())
        except Exception as e:
            logging.error(f"[SCHEDULER] symbols_tracker_job error: {e}")

    def _cmd_job():
        try:
            poll_telegram_commands()
        except Exception as e:
            logging.error(f"[SCHEDULER] poll_telegram_commands error: {e}")

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _job,
        "interval",
        minutes=10,
        id="symbols_tracker_job",
        replace_existing=True,
        next_run_time=datetime.utcnow(),
    )
    scheduler.add_job(
        _cmd_job,
        "interval",
        seconds=30,
        id="telegram_command_handler",
        replace_existing=True,
    )
    scheduler.start()
    logging.info("[SCHEDULER] Bot scheduler started (tracker: 10 min, cmd poll: 30s)")
