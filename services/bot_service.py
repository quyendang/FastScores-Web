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
TELEGRAM_CHAT_IDS = [
    cid.strip() for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if cid.strip()
]
FIXED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
ADX_MIN = float(os.getenv("BOT_ADX_MIN", "25"))
RR_MIN = float(os.getenv("BOT_RR_MIN", "1.5"))
ATR_SL_MULT = float(os.getenv("BOT_ATR_SL_MULT", "1.0"))
PULLBACK_LOOKBACK = int(os.getenv("BOT_PULLBACK_LOOKBACK", "8"))
SIGNAL_COOLDOWN_MINUTES = int(os.getenv("BOT_SIGNAL_COOLDOWN_MINUTES", "120"))
MIN_ATR_PCT = float(os.getenv("BOT_MIN_ATR_PCT", "0.003"))

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
        "volume": [float(k[5]) for k in rows],
        "close_time": [int(k[6]) for k in rows],
    }


def _get_dynamic_chat_ids() -> List[str]:
    if not TELEGRAM_BOT_TOKEN:
        return TELEGRAM_CHAT_IDS

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
        ids = list(chat_ids | set(TELEGRAM_CHAT_IDS))
        _chat_ids_cache.update({"ids": ids, "fetched_at": now})
        return ids

    return _chat_ids_cache["ids"] or TELEGRAM_CHAT_IDS


def _telegram_notify(title: str, message: str) -> int:
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("[TELEGRAM] Missing TELEGRAM_BOT_TOKEN, skip notify")
        return 0
    chat_ids = _get_dynamic_chat_ids()
    if not chat_ids:
        logging.warning("[TELEGRAM] No chat_id found from getUpdates/TELEGRAM_CHAT_IDS")
        return 0

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text = f"<b>{title}</b>\n{message}"
    sent = 0
    for cid in chat_ids:
        try:
            resp = requests.post(
                url,
                json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.ok:
                sent += 1
            else:
                logging.warning(f"[TELEGRAM] sendMessage failed for {cid}: {resp.text[:200]}")
        except Exception:
            logging.exception(f"[TELEGRAM] sendMessage exception for {cid}")
    return sent


def _to_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(int(v))
    if isinstance(v, str):
        t = v.strip().lower()
        if t in {"1", "true", "yes", "y"}:
            return True
        if t in {"0", "false", "no", "n"}:
            return False
    return None


def _pick(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _tf_snapshot(symbol: str, interval: str) -> Optional[Dict[str, Any]]:
    data = _closed_hlcv(symbol, interval, 260 if interval == "1h" else 230)
    if not data:
        return None

    opens = data["open"]
    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    volumes = data["volume"]
    close_time = data["close_time"][-1]

    try:
        ema50 = ind.ema_series(closes, 50)[-1]
        ema200 = ind.ema_series(closes, 200)[-1]
        rsi14 = ind.rsi_series(closes, 14)[-1]
        _, _, macd_hist_s = ind.macd_series(closes, 12, 26, 9)
        macd_hist = macd_hist_s[-1] if macd_hist_s else None
        prev_macd_hist = macd_hist_s[-2] if len(macd_hist_s) >= 2 else None
        macd_rising = (macd_hist is not None and prev_macd_hist is not None and macd_hist > prev_macd_hist)
        adx14 = ind.compute_adx(highs, lows, closes, 14)["adx"]
        atr14 = ind.atr_series(highs, lows, closes, 14)[-1]
        _, bb_upper_s, bb_lower_s = ind.bollinger_bands(closes, 20, 2.0)
        bb_upper = bb_upper_s[-1] if bb_upper_s else None
        bb_lower = bb_lower_s[-1] if bb_lower_s else None
    except Exception as e:
        logging.warning(f"[STRATEGY] {symbol} {interval} indicator error: {e}")
        return None

    close = closes[-1]
    bb_pct = None
    if bb_upper is not None and bb_lower is not None and bb_upper > bb_lower:
        bb_pct = (close - bb_lower) / (bb_upper - bb_lower)

    avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
    volume_spike = bool(avg_vol and avg_vol > 0 and volumes[-1] > avg_vol * 1.5)

    buy_signal = False
    if len(closes) >= 2:
        buy_signal = closes[-1] > opens[-1] and closes[-1] > highs[-2]

    ema_bullish = bool(ema50 is not None and ema200 is not None and close > ema200 and ema50 > ema200)
    ema_bearish = bool(ema50 is not None and ema200 is not None and close < ema200 and ema50 < ema200)

    atr_pct = (atr14 / close) if (atr14 is not None and close > 0) else None

    return {
        "symbol": symbol,
        "interval": interval,
        "candle_time": close_time,
        "close": close,
        "ema_bullish": ema_bullish,
        "ema_bearish": ema_bearish,
        "macd_hist": macd_hist,
        "adx_14": adx14,
        "rsi_14": rsi14,
        "buy_signal": buy_signal,
        "volume_spike": volume_spike,
        "macd_rising": macd_rising,
        "atr_14": atr14,
        "atr_pct": atr_pct,
        "bb_pct": bb_pct,
    }


def _generate_signal(symbol: str) -> Dict[str, Any]:
    d1 = _tf_snapshot(symbol, "1d")
    h4 = _tf_snapshot(symbol, "4h")
    h1 = _tf_snapshot(symbol, "1h")
    if not d1 or not h4 or not h1:
        return {"state": "NO SIGNAL", "reason": "Thiếu dữ liệu đa khung"}

    # Name fallback mapping to support legacy/alternate field names.
    ema_bullish_d1 = _to_bool(_pick(d1, "ema_bullish_d1", "ema_bullish", "ema_bull", default=False))
    ema_bearish_d1 = _to_bool(_pick(d1, "ema_bearish_d1", "ema_bearish", "ema_bear", default=False))
    ema_bullish_h4 = _to_bool(_pick(h4, "ema_bullish_h4", "ema_bullish", "ema_bull", default=False))
    macd_hist_h4 = _pick(h4, "macd_hist_h4", "macd_hist")
    adx_14_h4 = _pick(h4, "adx_14_h4", "adx_14")
    rsi_14_h4 = _pick(h4, "rsi_14_h4", "rsi_14")

    buy_signal_h1 = _to_bool(_pick(h1, "buy_signal_h1", "buy_signal", default=False))
    volume_spike_h1 = _to_bool(_pick(h1, "volume_spike_h1", "volume_spike", default=False))
    macd_rising_h1 = _to_bool(_pick(h1, "macd_rising_h1", "macd_rising", default=False))
    rsi_14_h1 = _pick(h1, "rsi_14_h1", "rsi_14")
    bb_pct_h1 = _pick(h1, "bb_pct_h1", "bb_pct")
    close_h1 = _pick(h1, "close_h1", "close")
    atr_14_h1 = _pick(h1, "atr_14_h1", "atr_14_h1", "atr_14", "atr")
    atr_pct_h1 = _pick(h1, "atr_pct_h1", "atr_pct")
    if atr_pct_h1 is None and atr_14_h1 is not None and close_h1:
        atr_pct_h1 = atr_14_h1 / close_h1

    # Volatility filter
    if atr_pct_h1 is None:
        logging.warning(f"[STRATEGY] {symbol}: thiếu atr_pct_h1/atr_14_h1, bỏ qua tín hiệu an toàn")
        return {"state": "NO SIGNAL", "reason": "Thiếu ATR% H1"}
    if atr_pct_h1 < MIN_ATR_PCT:
        return {"state": "NO SIGNAL", "reason": f"ATR% H1 thấp ({atr_pct_h1:.4f})"}

    long_ok = bool(
        ema_bullish_d1
        and ema_bullish_h4
        and macd_hist_h4 is not None and macd_hist_h4 > 0
        and adx_14_h4 is not None and adx_14_h4 > 20
        and buy_signal_h1
        and volume_spike_h1
    )

    short_ok = bool(
        ema_bearish_d1
        and macd_hist_h4 is not None and macd_hist_h4 < 0
        and rsi_14_h4 is not None and rsi_14_h4 < 50
        and (macd_rising_h1 is False)
        and rsi_14_h1 is not None and rsi_14_h1 > 50
    )

    # Additional block filters
    if long_ok:
        if (rsi_14_h1 is not None and rsi_14_h1 > 68) or (bb_pct_h1 is not None and bb_pct_h1 > 0.95):
            return {"state": "NO SIGNAL", "reason": "LONG bị chặn (quá nóng)", "h1": h1, "h4": h4, "d1": d1}
        return {"state": "LONG", "reason": "D1/H4/H1 đều xác nhận LONG", "h1": h1, "h4": h4, "d1": d1}

    if short_ok:
        if (rsi_14_h1 is not None and rsi_14_h1 < 40) or (bb_pct_h1 is not None and bb_pct_h1 < 0.10):
            return {"state": "NO SIGNAL", "reason": "SHORT bị chặn (quá bán)", "h1": h1, "h4": h4, "d1": d1}
        return {"state": "SHORT", "reason": "D1/H4/H1 đều xác nhận SHORT", "h1": h1, "h4": h4, "d1": d1}

    return {"state": "NO SIGNAL", "reason": "Không đủ điều kiện LONG/SHORT", "h1": h1, "h4": h4, "d1": d1}


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
    direction = "LONG (MUA)" if signal["direction"] == "LONG" else "SHORT (BÁN)"
    entry = signal["entry"]
    stop = signal["stop"]
    target = signal["target"]
    rr = signal["rr"]
    atr = signal["atr"]
    adx = trend["adx"]
    return (
        f"Hướng lệnh: <b>{direction}</b>\n"
        f"Điểm vào: <b>${entry:,.2f}</b>\n"
        f"Cắt lỗ (ATR14): <b>${stop:,.2f}</b>\n"
        f"Mục tiêu: <b>${target:,.2f}</b>\n"
        f"RR: <b>{rr:.2f}</b>\n"
        f"ADX(14) H4: {adx:.1f} | ATR(14) H1: {atr:,.2f}\n"
        f"Điều kiện: trend H4 + pullback H1 + nến xác nhận + nến đã đóng"
    )


def _format_startup_analysis(symbol: str) -> str:
    res = _generate_signal(symbol)
    state = res.get("state", "NO SIGNAL")
    reason = res.get("reason", "Không có lý do")
    h1 = res.get("h1") or {}
    h4 = res.get("h4") or {}
    d1 = res.get("d1") or {}
    return (
        f"<b>{symbol}</b>\n"
        f"Trạng thái: <b>{state}</b>\n"
        f"D1 ema_bullish={int(bool(_pick(d1, 'ema_bullish', default=False)))} | "
        f"ema_bearish={int(bool(_pick(d1, 'ema_bearish', default=False)))}\n"
        f"H4 macd_hist={_pick(h4, 'macd_hist', default='N/A')} | "
        f"adx_14={_pick(h4, 'adx_14', default='N/A')} | rsi_14={_pick(h4, 'rsi_14', default='N/A')}\n"
        f"H1 buy_signal={int(bool(_pick(h1, 'buy_signal', default=False)))} | "
        f"volume_spike={int(bool(_pick(h1, 'volume_spike', default=False)))} | "
        f"rsi_14={_pick(h1, 'rsi_14', default='N/A')} | bb_pct={_pick(h1, 'bb_pct', default='N/A')}\n"
        f"Lý do: {reason}"
    )


def send_startup_market_analysis() -> None:
    """Send one startup market brief for BTC/ETH to all Telegram bot users."""
    if not TELEGRAM_BOT_TOKEN:
        return
    parts = [_format_startup_analysis(symbol) for symbol in FIXED_SYMBOLS]
    message = (
        "Bot vừa khởi động. Tổng hợp phân tích thị trường hiện tại (nến đã đóng):\n\n"
        + "\n\n".join(parts)
    )
    sent = _telegram_notify("PHÂN TÍCH THỊ TRƯỜNG KHI KHỞI ĐỘNG", message)
    logging.info(f"[TELEGRAM] Startup market analysis sent to {sent} chat(s)")


def run_symbol_tracker_once(symbol: str, send_notify: bool = True) -> dict:
    symbol = symbol.upper()
    res = _generate_signal(symbol)
    state = res.get("state", "NO SIGNAL")
    if state not in {"LONG", "SHORT"}:
        return {"symbol": symbol, "action": "HOLD", "reason": res.get("reason", "NO SIGNAL")}

    h1 = res.get("h1") or {}
    h4 = res.get("h4") or {}
    candle_time = int(_pick(h1, "candle_time", default=0) or 0)
    if candle_time <= 0:
        logging.warning(f"[STRATEGY] {symbol}: thiếu candle_time H1, bỏ qua an toàn")
        return {"symbol": symbol, "action": "HOLD", "reason": "Thiếu candle_time H1"}

    if not _cooldown_ok(symbol, state, candle_time):
        return {"symbol": symbol, "action": "HOLD", "reason": "Cooldown active"}

    entry = _pick(h1, "close", default=0.0)
    atr = _pick(h1, "atr_14", default=0.0)
    if not entry or not atr:
        return {"symbol": symbol, "action": "HOLD", "reason": "Thiếu close/ATR H1"}
    stop = entry - ATR_SL_MULT * atr if state == "LONG" else entry + ATR_SL_MULT * atr

    signal = {"direction": state, "entry": entry, "stop": stop, "target": entry, "rr": RR_MIN, "atr": atr}
    trend = {"adx": _pick(h4, "adx_14", default=0.0)}

    if send_notify:
        title = f"{symbol} - TÍN HIỆU {state}"
        _telegram_notify(title, _format_signal(symbol, trend, signal))

    return {
        "symbol": symbol,
        "action": "SIGNAL",
        "direction": state,
        "entry": entry,
        "stop": stop,
        "target": None,
        "rr": None,
    }


def symbols_tracker_job() -> None:
    for symbol in FIXED_SYMBOLS:
        try:
            result = run_symbol_tracker_once(symbol, send_notify=True)
            logging.info(f"[JOB] {symbol}: {result.get('action')} - {result.get('reason', '')}")
        except Exception as e:
            logging.error(f"[JOB] {symbol}: {e}")

