"""
bot.py — Crypto signal bot endpoints.

Endpoints:
  GET  /bot?symbol={symbol}&tf={tf}   — Interactive dashboard
  POST /bot/subscribe                  — Subscribe symbol to notifications
  POST /bot/unsubscribe                — Unsubscribe symbol
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.supabase_client import get_supabase
from services import bot_indicators as ind
from services.bot_service import (
    RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    TRACKER_INTERVAL,
    compute_d1_bias,
    compute_candle_signals,
    run_symbol_tracker_once,
)
from services.bot_ai import call_openrouter_analysis

router = APIRouter(prefix="/bot", tags=["bot"])
templates = Jinja2Templates(directory="templates")


@router.post("/subscribe")
async def subscribe_symbol(symbol: str = Form(...)):
    symbol = symbol.upper()
    try:
        get_supabase().table("bot_subscriptions").upsert(
            {"symbol": symbol, "is_active": True},
            on_conflict="symbol",
        ).execute()
    except Exception as e:
        logging.error(f"[SUBSCRIBE] {symbol}: {e}")
    return RedirectResponse(url=f"/bot?symbol={symbol}", status_code=303)


@router.post("/unsubscribe")
async def unsubscribe_symbol(symbol: str = Form(...)):
    symbol = symbol.upper()
    try:
        get_supabase().table("bot_subscriptions").update({"is_active": False}).eq("symbol", symbol).execute()
    except Exception as e:
        logging.error(f"[UNSUBSCRIBE] {symbol}: {e}")
    return RedirectResponse(url=f"/bot?symbol={symbol}", status_code=303)


@router.get("", response_class=HTMLResponse)
async def bot_dashboard(
    request: Request,
    symbol: str = Query("ETHUSDT"),
    tf: str = Query("4h"),
):
    """
    Interactive dashboard for any symbol.
    Query params:
      symbol — e.g. ETHUSDT, BTCUSDT, BNBUSDT
      tf     — 15m | 1h | 4h | 1d
    """
    symbol = symbol.upper()
    valid_tfs = {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    if tf not in valid_tfs:
        tf = "4h"
    interval = valid_tfs[tf]

    # ── Parallel network fetches ──────────────────────────────────────────────
    def _safe_klines():
        try:
            return ind.fetch_klines(symbol, interval, limit=200)
        except Exception as e:
            logging.error(f"[BOT_DASH] klines {symbol}: {e}")
            return []

    def _safe_d1_bias():
        try:
            return compute_d1_bias(symbol)
        except Exception as e:
            logging.error(f"[BOT_DASH] d1 bias {symbol}: {e}")
            return (False, False)

    def _safe_btc_context():
        try:
            _, btc_rsi = ind.rsi_latest("BTCUSDT", interval, RSI_PERIOD)
            _, _, btc_macd_h, _ = ind.macd_latest_with_prev("BTCUSDT", interval)
            return btc_rsi, btc_macd_h
        except Exception as e:
            logging.error(f"[BOT_DASH] btc context: {e}")
            return None, None

    klines, d1_result, btc_result, fng_data, funding_data = await asyncio.gather(
        asyncio.to_thread(_safe_klines),
        asyncio.to_thread(_safe_d1_bias),
        asyncio.to_thread(_safe_btc_context),
        asyncio.to_thread(ind.fetch_fear_greed),
        asyncio.to_thread(ind.fetch_funding_rate, symbol),
    )
    d1_bullish, d1_bearish = d1_result
    btc_rsi_h4, btc_macd_hist_val = btc_result
    # ─────────────────────────────────────────────────────────────────────────

    labels: List[str] = []
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    volumes: List[float] = []

    for k in klines:
        try:
            dt = datetime.utcfromtimestamp(int(k[0]) / 1000.0)
            labels.append(dt.strftime("%Y-%m-%d %H:%M"))
            highs.append(float(k[2]))
            lows.append(float(k[3]))
            closes.append(float(k[4]))
            volumes.append(float(k[5]))
        except Exception as e:
            logging.warning(f"[BOT_DASH] Bad kline row: {e}")

    _empty_ctx = {
        "request": request, "symbol": symbol, "tf": tf,
        "rows_json_str": "[]", "last_price": None, "last_rsi": None,
        "change_24h": None, "buy_low": None, "buy_high": None,
        "sell_low": None, "sell_high": None, "is_subscribed": False,
        "tracker_action": "HOLD", "tracker_reason": "No data",
        "d1_bullish": False, "d1_bearish": False, "ai_analysis": "",
        "db_signals_json": "[]", "fng_value": 50, "funding_rate_pct": 0.0,
    }
    if not closes:
        return templates.TemplateResponse("bot_dashboard.html", _empty_ctx)

    # ── Indicators ────────────────────────────────────────────────────────────
    rsi_values = ind.rsi_series(closes, RSI_PERIOD)
    macd_line_s, macd_sig_s, macd_hist_values = ind.macd_series(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    ema34 = ind.ema_series(closes, 34)
    ema50 = ind.ema_series(closes, 50)
    ema89 = ind.ema_series(closes, 89)
    ema200 = ind.ema_series(closes, 200)
    sma_50 = ind.sma_series(closes, 50)
    sma_150 = ind.sma_series(closes, 150)
    bb_middle, bb_upper, bb_lower = ind.bollinger_bands(closes, period=20, k=2.0)
    stoch_k = ind.stochastic_k(highs, lows, closes, period=14)
    wr_vals = ind.williams_r(highs, lows, closes, period=14)

    buy_low = buy_high = sell_low = sell_high = recent_low = recent_high = None
    try:
        zones = ind.compute_zones(symbol, interval, lookback=60)
        sell_low, sell_high, buy_low, buy_high, recent_low, recent_high = zones
    except Exception as e:
        logging.error(f"[BOT_DASH] zones {symbol}: {e}")

    # ── Trim to min series length ─────────────────────────────────────────────
    n = min(
        len(closes), len(labels), len(volumes), len(rsi_values),
        len(macd_hist_values), len(ema34), len(ema50), len(ema89), len(ema200),
        len(sma_50), len(sma_150), len(bb_upper), len(bb_lower),
        len(stoch_k), len(wr_vals),
    )
    labels = labels[-n:]
    closes_t = closes[-n:]
    highs_t = highs[-n:]
    lows_t = lows[-n:]
    volumes_t = volumes[-n:]
    rsi_values = rsi_values[-n:]
    macd_hist_values = macd_hist_values[-n:]
    ema34 = ema34[-n:]
    ema50 = ema50[-n:]
    ema89 = ema89[-n:]
    ema200 = ema200[-n:]
    sma_50 = sma_50[-n:]
    sma_150 = sma_150[-n:]
    bb_middle = bb_middle[-n:]
    bb_upper = bb_upper[-n:]
    bb_lower = bb_lower[-n:]
    stoch_k = stoch_k[-n:]
    wr_vals = wr_vals[-n:]

    atr_vals = ind.atr_series(highs_t, lows_t, closes_t)
    obv_sig = ind.compute_obv_signals(closes_t, volumes_t)

    # ── Build rows JSON ───────────────────────────────────────────────────────
    rows_json: List[Dict[str, Any]] = []
    for i in range(n):
        rows_json.append({
            "time_str": labels[i],
            "price": closes_t[i],
            "high": highs_t[i],
            "low": lows_t[i],
            "volume": volumes_t[i],
            "rsi_h4": rsi_values[i],
            "macd_hist": macd_hist_values[i],
            "ema34": ema34[i],
            "ema50": ema50[i],
            "ema89": ema89[i],
            "ema200": ema200[i],
            "sma_50": sma_50[i],
            "sma_150": sma_150[i],
            "bb_middle": bb_middle[i],
            "bb_upper": bb_upper[i],
            "bb_lower": bb_lower[i],
            "stoch_k": stoch_k[i],
            "wr": wr_vals[i],
            "atr": atr_vals[i] if i < len(atr_vals) else None,
            "obv_trend": obv_sig["obv_trend"],
        })

    # ── Candle signals ────────────────────────────────────────────────────────
    signals = compute_candle_signals(
        closes=closes_t, highs=highs_t, lows=lows_t,
        rsi=rsi_values, macd_hist=macd_hist_values,
        ema34=ema34, ema50=ema50, ema89=ema89, ema200=ema200,
        sma_50=sma_50, sma_150=sma_150,
        bb_upper=bb_upper, bb_lower=bb_lower,
        stoch_k=stoch_k, williams_r=wr_vals,
        buy_zone_low=buy_low, buy_zone_high=buy_high,
        sell_zone_low=sell_low, sell_zone_high=sell_high,
        d1_bullish=d1_bullish, d1_bearish=d1_bearish,
        btc_rsi_h4=btc_rsi_h4, btc_macd_hist=btc_macd_hist_val,
        atr_series=atr_vals, volumes=volumes_t,
        fng_adj=fng_data, funding_adj=funding_data,
    )
    for i, row in enumerate(rows_json):
        row.update(signals[i])

    last_price = closes_t[-1]
    last_rsi = rsi_values[-1] if rsi_values else None

    change_24h = None
    if len(closes_t) >= 7:
        ref = closes_t[-7]
        if ref != 0:
            change_24h = (last_price - ref) / ref * 100.0

    # ── Tracker action ────────────────────────────────────────────────────────
    tracker_action = "HOLD"
    tracker_reason = ""
    try:
        payload = run_symbol_tracker_once(symbol, send_notify=False)
        tracker_action = payload.get("action", "HOLD")
        tracker_reason = payload.get("reason", "")
    except Exception as e:
        logging.error(f"[BOT_DASH] tracker {symbol}: {e}")

    # ── Subscription status ───────────────────────────────────────────────────
    is_subscribed = False
    try:
        resp = (
            get_supabase().table("bot_subscriptions")
            .select("is_active")
            .eq("symbol", symbol)
            .limit(1)
            .execute()
        )
        db_rows = resp.data or []
        if db_rows and db_rows[0].get("is_active"):
            is_subscribed = True
    except Exception as e:
        logging.error(f"[BOT_DASH] subscription {symbol}: {e}")

    # ── Historical DB signals ─────────────────────────────────────────────────
    db_signals: List[Dict[str, Any]] = []
    try:
        db_signals = (
            get_supabase().table("signal_history")
            .select("signal_type,price,rsi,macd_hist,buy_score,sell_score,signal_strength,signal_detail,created_at")
            .eq("symbol", symbol)
            .order("created_at", desc=False)
            .limit(500)
            .execute()
        ).data or []
    except Exception as e:
        logging.error(f"[BOT_DASH] signal_history {symbol}: {e}")

    # ── AI analysis ───────────────────────────────────────────────────────────
    last_signal = signals[-1] if signals else {}
    ai_snap = {
        "price": last_price,
        "change_24h": change_24h,
        "rsi": last_rsi,
        "macd_hist": macd_hist_values[-1] if macd_hist_values else None,
        "macd_hist_rising": (
            len(macd_hist_values) >= 2
            and macd_hist_values[-1] is not None
            and macd_hist_values[-2] is not None
            and macd_hist_values[-1] > macd_hist_values[-2]
        ),
        "ema_bullish": (ema34[-1] is not None and ema89[-1] is not None and ema34[-1] > ema89[-1]),
        "ema_bearish": (ema34[-1] is not None and ema89[-1] is not None and ema34[-1] < ema89[-1]),
        "stoch_k": stoch_k[-1] if stoch_k else None,
        "wr": wr_vals[-1] if wr_vals else None,
        "bb_upper": bb_upper[-1] if bb_upper else None,
        "bb_lower": bb_lower[-1] if bb_lower else None,
        "d1_bullish": d1_bullish,
        "d1_bearish": d1_bearish,
        "btc_rsi": btc_rsi_h4,
        "btc_macd_hist": btc_macd_hist_val,
        "buy_low": buy_low,
        "buy_high": buy_high,
        "sell_low": sell_low,
        "sell_high": sell_high,
        "zone": last_signal.get("zone", "neutral"),
        "tracker_action": tracker_action,
        "buy_score": last_signal.get("buy_score", 0),
        "sell_score": last_signal.get("sell_score", 0),
    }
    ai_analysis = call_openrouter_analysis(symbol, tf, ai_snap)

    return templates.TemplateResponse("bot_dashboard.html", {
        "request": request,
        "symbol": symbol,
        "tf": tf,
        "rows_json_str": json.dumps(rows_json),
        "last_price": last_price,
        "last_rsi": last_rsi,
        "change_24h": change_24h,
        "buy_low": buy_low,
        "buy_high": buy_high,
        "sell_low": sell_low,
        "sell_high": sell_high,
        "is_subscribed": is_subscribed,
        "tracker_action": tracker_action,
        "tracker_reason": tracker_reason,
        "d1_bullish": d1_bullish,
        "d1_bearish": d1_bearish,
        "ai_analysis": ai_analysis,
        "db_signals_json": json.dumps(db_signals),
        "fng_value": fng_data.get("value", 50),
        "funding_rate_pct": funding_data.get("funding_rate_pct", 0.0),
    })
