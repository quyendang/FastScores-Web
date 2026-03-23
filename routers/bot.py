"""
bot.py — Crypto bot dashboard endpoints.
"""
import asyncio, json, logging
from datetime import datetime
from typing import Any, Dict, List
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.supabase_client import get_bot_supabase as get_supabase
from services import bot_indicators as ind
from services.bot_service import (
    BOT_MODE, get_bot_config,
    get_daily_context, get_4h_snapshot,
    run_symbol_tracker_once, compute_simulated_trade,
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL, TRACKER_INTERVAL,
)
from services.bot_ai import call_openrouter_analysis, call_openrouter_analysis_model2

router = APIRouter(prefix="/bot", tags=["bot"])
templates = Jinja2Templates(directory="templates")


@router.post("/subscribe")
async def subscribe_symbol(symbol: str = Form(...)):
    symbol = symbol.upper()
    try:
        get_supabase().table("bot_subscriptions").upsert(
            {"symbol": symbol, "is_active": True}, on_conflict="symbol"
        ).execute()
    except Exception as e:
        logging.error(f"[SUBSCRIBE] {symbol}: {e}")
    return RedirectResponse(url=f"/bot?symbol={symbol}", status_code=303)


@router.post("/unsubscribe")
async def unsubscribe_symbol(symbol: str = Form(...)):
    symbol = symbol.upper()
    try:
        get_supabase().table("bot_subscriptions").update(
            {"is_active": False}
        ).eq("symbol", symbol).execute()
    except Exception as e:
        logging.error(f"[UNSUBSCRIBE] {symbol}: {e}")
    return RedirectResponse(url=f"/bot?symbol={symbol}", status_code=303)


@router.get("", response_class=HTMLResponse)
async def bot_dashboard(
    request: Request,
    symbol: str = Query("ETHUSDT"),
    tf: str = Query("4h"),
):
    symbol = symbol.upper()
    if tf not in {"15m", "1h", "4h", "1d"}:
        tf = "4h"

    # ── Parallel fetches ──────────────────────────────────────────────────────
    def _klines():
        try:
            return ind.fetch_klines(symbol, tf, limit=200)
        except Exception as e:
            logging.error(f"[DASH] klines: {e}"); return []

    def _tracker():
        try:
            return run_symbol_tracker_once(symbol, send_notify=False)
        except Exception as e:
            logging.error(f"[DASH] tracker: {e}")
            return {"action": "HOLD", "reason": "", "snapshot": {}, "daily_context": {},
                    "simulated_trade": {}, "mode": BOT_MODE}

    def _sr_d1():
        try:
            return ind.find_support_resistance(symbol, "1d", limit=120)
        except Exception:
            return {"supports": [], "resistances": []}

    def _sr_near():
        if tf == "1d":
            return {"supports": [], "resistances": []}
        try:
            return ind.find_support_resistance(symbol, tf, limit=100, pivot_strength=2)
        except Exception:
            return {"supports": [], "resistances": []}

    def _db_signals():
        try:
            return (get_supabase().table("signal_history")
                    .select("signal_type,price,rsi,buy_score,sell_score,signal_detail,created_at")
                    .eq("symbol", symbol).order("created_at", desc=False)
                    .limit(200).execute()).data or []
        except Exception:
            return []

    def _subscribed():
        try:
            rows = (get_supabase().table("bot_subscriptions")
                    .select("is_active").eq("symbol", symbol).limit(1).execute()).data or []
            return bool(rows and rows[0].get("is_active"))
        except Exception:
            return False

    klines, tracker, sr_d1, sr_near, db_signals, is_subscribed = await asyncio.gather(
        asyncio.to_thread(_klines),
        asyncio.to_thread(_tracker),
        asyncio.to_thread(_sr_d1),
        asyncio.to_thread(_sr_near),
        asyncio.to_thread(_db_signals),
        asyncio.to_thread(_subscribed),
    )

    # ── Parse klines ──────────────────────────────────────────────────────────
    closes, highs, lows, volumes, labels = [], [], [], [], []
    for k in klines:
        try:
            dt = datetime.utcfromtimestamp(int(k[0]) / 1000)
            labels.append(dt.strftime("%Y-%m-%d %H:%M"))
            highs.append(float(k[2])); lows.append(float(k[3]))
            closes.append(float(k[4])); volumes.append(float(k[5]))
        except Exception:
            pass

    snap    = tracker.get("snapshot", {})
    dctx    = tracker.get("daily_context", {})
    sim     = tracker.get("simulated_trade", {})
    cfg     = get_bot_config(symbol)

    # ── Compute chart series ──────────────────────────────────────────────────
    ema34 = ema89 = ema200 = bb_upper = bb_lower = []
    rsi_vals = macd_hist_vals = []
    if closes:
        try:
            ema34    = ind.ema_series(closes, 34)
            ema89    = ind.ema_series(closes, 89)
            ema200   = ind.ema_series(closes, 200)
            _, bb_u, bb_l = ind.bollinger_bands(closes, 20, 2.0)
            bb_upper = bb_u; bb_lower = bb_l
            rsi_vals = ind.rsi_series(closes, 14)
            _, _, macd_hist_vals = ind.macd_series(closes, 12, 26, 9)
        except Exception as e:
            logging.error(f"[DASH] indicators: {e}")

    n = min(len(closes), len(labels), len(ema34) if ema34 else 9999)

    rows_json: List[Dict[str, Any]] = []
    for i in range(n):
        rows_json.append({
            "time_str": labels[i], "price": closes[i],
            "high": highs[i], "low": lows[i], "volume": volumes[i],
            "ema34":  ema34[i]  if ema34  and i < len(ema34)  else None,
            "ema89":  ema89[i]  if ema89  and i < len(ema89)  else None,
            "ema200": ema200[i] if ema200 and i < len(ema200) else None,
            "bb_upper": bb_upper[i] if bb_upper and i < len(bb_upper) else None,
            "bb_lower": bb_lower[i] if bb_lower and i < len(bb_lower) else None,
            "rsi":     rsi_vals[i]      if rsi_vals      and i < len(rsi_vals)      else None,
            "macd_hist": macd_hist_vals[i] if macd_hist_vals and i < len(macd_hist_vals) else None,
        })

    last_price  = closes[-1] if closes else None
    change_24h  = None
    if len(closes) >= 7 and closes[-7]:
        change_24h = (closes[-1] - closes[-7]) / closes[-7] * 100

    # ── AI analysis (parallel) ────────────────────────────────────────────────
    ai_snap = {
        "price": snap.get("price", last_price), "rsi_14": snap.get("rsi_14"),
        "adx_14": snap.get("adx_14"), "macd_hist": snap.get("macd_hist"),
        "macd_rising": snap.get("macd_rising"), "stoch_k": snap.get("stoch_k"),
        "uptrend": dctx.get("uptrend"), "entry_strategy": sim.get("strategy"),
    }
    ai1, ai2 = await asyncio.gather(
        asyncio.to_thread(call_openrouter_analysis, symbol, tf, ai_snap),
        asyncio.to_thread(call_openrouter_analysis_model2, symbol, tf, ai_snap),
    )

    return templates.TemplateResponse("bot_dashboard.html", {
        "request": request,
        "symbol": symbol, "tf": tf,
        "last_price": last_price, "change_24h": change_24h,
        "rows_json_str": json.dumps(rows_json),
        "tracker": tracker,
        "snap": snap, "dctx": dctx,
        "sim": sim, "cfg": cfg,
        "bot_mode": BOT_MODE,
        "is_subscribed": is_subscribed,
        "sr_d1_json": json.dumps(sr_d1),
        "sr_near_json": json.dumps(sr_near),
        "db_signals_json": json.dumps(db_signals),
        "ai_analysis": ai1, "ai_analysis2": ai2,
        # Legacy compat
        "d1_bullish": dctx.get("uptrend", False) and dctx.get("bull_ema", False),
        "d1_bearish": not dctx.get("uptrend", True) and dctx.get("bear_ema", False),
        "tracker_action": tracker.get("action", "HOLD"),
        "tracker_reason": tracker.get("reason", ""),
    })


# ── /bot/backtest ─────────────────────────────────────────────────────────────

@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(
    request: Request,
    symbol:   str   = Query("BTCUSDT"),
    interval: str   = Query("4h"),
    mode:     str   = Query(BOT_MODE),
    capital:  float = Query(10000),
    run:      int   = Query(0),   # run=1 để thực sự chạy backtest
):
    symbol   = symbol.upper()
    interval = interval if interval in {"1d", "4h", "1h"} else "4h"
    mode     = mode     if mode     in {"default", "optimized"} else BOT_MODE
    capital  = max(100.0, min(capital, 10_000_000))

    # Danh sách file có sẵn
    available = []
    data_dir  = Path("data")
    if data_dir.exists():
        for f in sorted(data_dir.glob("*_10y.csv")):
            parts = f.stem.split("_")
            if len(parts) >= 2:
                available.append({"symbol": parts[0], "interval": parts[1]})

    result = None
    if run:
        def _run():
            from services.bot_backtest import run_backtest
            return run_backtest(symbol, interval, mode, capital)
        result = await asyncio.to_thread(_run)

    return templates.TemplateResponse("bot_backtest.html", {
        "request":    request,
        "symbol":     symbol,
        "interval":   interval,
        "mode":       mode,
        "capital":    capital,
        "bot_mode":   BOT_MODE,
        "available":  available,
        "result":     result,
        "result_json": json.dumps(result) if result else "null",
    })
