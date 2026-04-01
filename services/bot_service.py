"""
Simple signal scheduler for BTCUSDT and ETHUSDT.

Rules:
- Trend on H4:
  - LONG: close > EMA200, EMA50 > EMA200, ADX(14) >= 25
  - SHORT: close < EMA200, EMA50 < EMA200, ADX(14) >= 25
- Entry on H1:
  - Pullback to EMA20/EMA50 then bullish/bearish confirmation
- Stop-loss from ATR(14)
- Only send signal if RR >= 1.5
- Never use unclosed candle
- Cooldown to avoid spam duplicate signal
- Send to users that have chatted with Telegram bot
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from services import bot_indicators as ind

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
FIXED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
ADX_MIN = float(os.getenv("BOT_ADX_MIN", "25"))
RR_MIN = float(os.getenv("BOT_RR_MIN", "1.5"))
ATR_SL_MULT = float(os.getenv("BOT_ATR_SL_MULT", "1.0"))
PULLBACK_LOOKBACK = int(os.getenv("BOT_PULLBACK_LOOKBACK", "8"))
SIGNAL_COOLDOWN_MINUTES = int(os.getenv("BOT_SIGNAL_COOLDOWN_MINUTES", "120"))

_last_signal_time: Dict[str, float] = {}
_last_signal_candle: Dict[str, int] = {}

_chat_ids_cache: Dict[str, Any] = {"ids": [], "fetched_at": 0.0}
CHAT_IDS_CACHE_TTL = 300


def _now_ms() -> int:
    return int(time.time() * 1000)


def _closed_hlcv(symbol: str, interval: str, limit: int) -> Optional[dict]:
    """Return closed-candle arrays only (exclude currently open candle)."""
    kl = ind.fetch_klines(symbol, interval, limit=max(limit + 2, 220))
    if len(kl) < limit + 1:
        return None

    now_ms = _now_ms()
    closed = [k for k in kl if int(k[6]) <= now_ms]
    if len(closed) < limit:
        return None

    rows = closed[-limit:]
    return {
        "open": [float(k[1]) for k in rows],
        "high": [float(k[2]) for k in rows],
        "low": [float(k[3]) for k in rows],
        "close": [float(k[4]) for k in rows],
        "close_time": [int(k[6]) for k in rows],
    }


def _get_dynamic_chat_ids() -> List[str]:
    if not TELEGRAM_BOT_TOKEN:
        return []

    now = time.time()
    if now - _chat_ids_cache["fetched_at"] < CHAT_IDS_CACHE_TTL and _chat_ids_cache["ids"]:
        return _chat_ids_cache["ids"]

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    chat_ids: set[str] = set()

    try:
        offset = 0
        while True:
            params: Dict[str, Any] = {"limit": 100, "timeout": 0}
            if offset:
                params["offset"] = offset
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if not data.get("ok"):
                break
            results = data.get("result", [])
            if not results:
                break

            for upd in results:
                for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
                    msg = upd.get(key)
                    if msg and (msg.get("chat") or {}).get("id"):
                        chat_ids.add(str(msg["chat"]["id"]))
                cb = upd.get("callback_query")
                if cb:
                    chat = (cb.get("message") or {}).get("chat") or {}
                    if chat.get("id"):
                        chat_ids.add(str(chat["id"]))

            last_id = results[-1].get("update_id")
            if last_id is None or len(results) < 100:
                break
            offset = int(last_id) + 1

    except Exception as e:
        logging.warning(f"[TELEGRAM] getUpdates failed: {e}")

    if chat_ids:
        ids = list(chat_ids)
        _chat_ids_cache.update({"ids": ids, "fetched_at": now})
        return ids

    return _chat_ids_cache["ids"] or []


def _telegram_notify(title: str, message: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        return
    chat_ids = _get_dynamic_chat_ids()
    if not chat_ids:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text = f"<b>{title}</b>\n{message}"
    for cid in chat_ids:
        try:
            requests.post(
                url,
                json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
        except Exception:
            pass


def _is_bullish_confirmation(opens: List[float], highs: List[float], closes: List[float]) -> bool:
    if len(closes) < 2:
        return False
    return closes[-1] > opens[-1] and closes[-1] > highs[-2]


def _is_bearish_confirmation(opens: List[float], lows: List[float], closes: List[float]) -> bool:
    if len(closes) < 2:
        return False
    return closes[-1] < opens[-1] and closes[-1] < lows[-2]


def _trend_h4(symbol: str) -> Optional[dict]:
    data = _closed_hlcv(symbol, "4h", 230)
    if not data:
        return None

    closes = data["close"]
    highs = data["high"]
    lows = data["low"]
    ctime = data["close_time"][-1]

    ema50 = ind.ema_series(closes, 50)
    ema200 = ind.ema_series(closes, 200)
    adx = ind.compute_adx(highs, lows, closes, 14)["adx"]

    e50 = ema50[-1]
    e200 = ema200[-1]
    close = closes[-1]
    if e50 is None or e200 is None:
        return None

    long_trend = close > e200 and e50 > e200 and adx >= ADX_MIN
    short_trend = close < e200 and e50 < e200 and adx >= ADX_MIN
    return {
        "long_trend": long_trend,
        "short_trend": short_trend,
        "close": close,
        "adx": adx,
        "candle_time": ctime,
    }


def _entry_h1(symbol: str, direction: str) -> Optional[dict]:
    data = _closed_hlcv(symbol, "1h", 260)
    if not data:
        return None

    opens = data["open"]
    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    close_time = data["close_time"][-1]

    ema20 = ind.ema_series(closes, 20)
    ema50 = ind.ema_series(closes, 50)
    atr = ind.atr_series(highs, lows, closes, 14)

    e20 = ema20[-1]
    e50 = ema50[-1]
    atr_v = atr[-1]
    if e20 is None or e50 is None or atr_v is None or atr_v <= 0:
        return None

    touch_long = False
    touch_short = False
    start = max(1, len(closes) - PULLBACK_LOOKBACK - 1)
    end = len(closes) - 1
    for i in range(start, end):
        e20_i = ema20[i]
        e50_i = ema50[i]
        if e20_i is None or e50_i is None:
            continue
        if lows[i] <= max(e20_i, e50_i):
            touch_long = True
        if highs[i] >= min(e20_i, e50_i):
            touch_short = True

    if direction == "LONG":
        if not touch_long or not _is_bullish_confirmation(opens, highs, closes):
            return None
        entry = closes[-1]
        stop = entry - ATR_SL_MULT * atr_v
        risk = entry - stop
        if risk <= 0:
            return None
        recent_high = max(highs[-31:-1]) if len(highs) > 31 else max(highs[:-1])
        reward = recent_high - entry
        rr = reward / risk if risk > 0 else 0.0
        if rr < RR_MIN:
            return None
        return {
            "direction": "LONG",
            "entry": entry,
            "stop": stop,
            "target": recent_high,
            "rr": rr,
            "atr": atr_v,
            "candle_time": close_time,
        }

    if direction == "SHORT":
        if not touch_short or not _is_bearish_confirmation(opens, lows, closes):
            return None
        entry = closes[-1]
        stop = entry + ATR_SL_MULT * atr_v
        risk = stop - entry
        if risk <= 0:
            return None
        recent_low = min(lows[-31:-1]) if len(lows) > 31 else min(lows[:-1])
        reward = entry - recent_low
        rr = reward / risk if risk > 0 else 0.0
        if rr < RR_MIN:
            return None
        return {
            "direction": "SHORT",
            "entry": entry,
            "stop": stop,
            "target": recent_low,
            "rr": rr,
            "atr": atr_v,
            "candle_time": close_time,
        }

    return None


def _cooldown_ok(symbol: str, direction: str, candle_time: int) -> bool:
    key = f"{symbol}:{direction}"
    now = time.time()
    if _last_signal_candle.get(key) == candle_time:
        return False
    if now - _last_signal_time.get(key, 0.0) < SIGNAL_COOLDOWN_MINUTES * 60:
        return False
    _last_signal_time[key] = now
    _last_signal_candle[key] = candle_time
    return True


def _format_signal(symbol: str, trend: dict, signal: dict) -> str:
    direction = signal["direction"]
    entry = signal["entry"]
    stop = signal["stop"]
    target = signal["target"]
    rr = signal["rr"]
    atr = signal["atr"]
    adx = trend["adx"]
    return (
        f"Direction: <b>{direction}</b>\n"
        f"Entry: <b>${entry:,.2f}</b>\n"
        f"Stop-loss (ATR14): <b>${stop:,.2f}</b>\n"
        f"Target: <b>${target:,.2f}</b>\n"
        f"RR: <b>{rr:.2f}</b>\n"
        f"H4 ADX(14): {adx:.1f} | H1 ATR(14): {atr:,.2f}\n"
        f"Rule: H4 trend + H1 pullback + confirmation + closed candle"
    )


def run_symbol_tracker_once(symbol: str, send_notify: bool = True) -> dict:
    symbol = symbol.upper()
    trend = _trend_h4(symbol)
    if not trend:
        return {"symbol": symbol, "action": "HOLD", "reason": "No enough H4 data"}

    direction = None
    if trend["long_trend"]:
        direction = "LONG"
    elif trend["short_trend"]:
        direction = "SHORT"
    else:
        return {"symbol": symbol, "action": "HOLD", "reason": "H4 trend condition not met"}

    signal = _entry_h1(symbol, direction)
    if not signal:
        return {"symbol": symbol, "action": "HOLD", "reason": f"No H1 {direction} setup"}

    if not _cooldown_ok(symbol, direction, signal["candle_time"]):
        return {"symbol": symbol, "action": "HOLD", "reason": "Cooldown active"}

    if send_notify:
        title = f"{symbol} - {direction} SIGNAL"
        _telegram_notify(title, _format_signal(symbol, trend, signal))

    return {
        "symbol": symbol,
        "action": "SIGNAL",
        "direction": direction,
        "entry": signal["entry"],
        "stop": signal["stop"],
        "target": signal["target"],
        "rr": signal["rr"],
    }


def symbols_tracker_job() -> None:
    for symbol in FIXED_SYMBOLS:
        try:
            result = run_symbol_tracker_once(symbol, send_notify=True)
            logging.info(f"[JOB] {symbol}: {result.get('action')} - {result.get('reason', '')}")
        except Exception as e:
            logging.error(f"[JOB] {symbol}: {e}")

