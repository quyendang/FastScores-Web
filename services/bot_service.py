"""
bot_service.py — Core bot business logic:
  - Signal computation (D1 bias, candle signals, scoring)
  - Tracker (per-symbol BUY/SELL/HOLD decision)
  - DB persistence (signal_history, bot_subscriptions)
  - Telegram notifications
  - Background job (symbols_tracker_job)
"""

import os
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from services import bot_indicators as ind
from services.bot_ai import ai_brief_for_telegram

# ── Config ───────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = [
    cid.strip() for cid in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if cid.strip()
]
RSI_SYMBOLS = [
    s.strip() for s in os.getenv("RSI_SYMBOLS", "ETHUSDT,BTCUSDT").split(",") if s.strip()
] or ["ETHUSDT", "BTCUSDT"]
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_CHECK_MINUTES = int(os.getenv("RSI_CHECK_MINUTES", "5"))
RSI_TIMEFRAMES = {"1h": "1h", "4h": "4h", "1d": "1d"}
NOTIFY_COOLDOWN_MINUTES = int(os.getenv("NOTIFY_COOLDOWN_MINUTES", "120"))
TRACKER_INTERVAL = os.getenv("ETH_TRACKER_INTERVAL", "4h")

MACD_FAST = int(os.getenv("ETH_MACD_FAST", "12"))
MACD_SLOW = int(os.getenv("ETH_MACD_SLOW", "26"))
MACD_SIGNAL = int(os.getenv("ETH_MACD_SIGNAL", "9"))

ETH_RSI_BUY = float(os.getenv("ETH_RSI_BUY", "40"))
ETH_RSI_SELL = float(os.getenv("ETH_RSI_SELL", "65"))

# ── State ────────────────────────────────────────────────────────────────────

_rsi_last_state: Dict[str, Dict[str, str]] = {
    sym: {tf: "unknown" for tf in RSI_TIMEFRAMES} for sym in RSI_SYMBOLS
}
_notify_last_sent: Dict[str, float] = {}

# Cache chat IDs lấy từ getUpdates (TTL 5 phút)
_chat_ids_cache: Dict[str, Any] = {"ids": [], "fetched_at": 0.0}
CHAT_IDS_CACHE_TTL = 300  # 5 minutes


# ── Notification helpers ──────────────────────────────────────────────────────

def _can_notify(symbol: str, action: str) -> bool:
    key = f"{symbol}_{action}"
    return (time.time() - _notify_last_sent.get(key, 0.0)) >= NOTIFY_COOLDOWN_MINUTES * 60


def _mark_notified(symbol: str, action: str) -> None:
    _notify_last_sent[f"{symbol}_{action}"] = time.time()
    opposite = "SELL" if action == "BUY" else "BUY"
    _notify_last_sent.pop(f"{symbol}_{opposite}", None)


def get_dynamic_chat_ids() -> List[str]:
    """
    Lấy toàn bộ chat IDs từ Telegram getUpdates API (phân trang).
    Cache kết quả 5 phút. Fallback về TELEGRAM_CHAT_IDS nếu lỗi.
    """
    if not TELEGRAM_BOT_TOKEN:
        return TELEGRAM_CHAT_IDS

    now = time.time()
    if now - _chat_ids_cache["fetched_at"] < CHAT_IDS_CACHE_TTL and _chat_ids_cache["ids"]:
        return _chat_ids_cache["ids"]

    try:
        base_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        chat_ids: set = set()
        offset = 0

        while True:
            params: Dict[str, Any] = {"limit": 100, "timeout": 0}
            if offset:
                params["offset"] = offset

            resp = requests.get(base_url, params=params, timeout=10)
            data = resp.json()

            if not data.get("ok"):
                logging.warning(f"[TELEGRAM] getUpdates failed: {data.get('description')}")
                break

            results = data.get("result", [])
            if not results:
                break

            for update in results:
                # Hỗ trợ nhiều loại update: message, callback_query, channel_post, ...
                for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
                    msg = update.get(key)
                    if msg:
                        chat = msg.get("chat")
                        if chat and chat.get("id"):
                            chat_ids.add(str(chat["id"]))

                cb = update.get("callback_query")
                if cb:
                    msg = cb.get("message") or {}
                    chat = msg.get("chat")
                    if chat and chat.get("id"):
                        chat_ids.add(str(chat["id"]))

            # Phân trang: offset = update_id của bản cuối + 1
            last_update_id = results[-1].get("update_id")
            if last_update_id is None or len(results) < 100:
                break
            offset = last_update_id + 1

        if chat_ids:
            ids_list = list(chat_ids)
            _chat_ids_cache["ids"] = ids_list
            _chat_ids_cache["fetched_at"] = now
            logging.info(f"[TELEGRAM] Dynamic chat IDs: {ids_list}")
            return ids_list

    except Exception as e:
        logging.warning(f"[TELEGRAM] getUpdates error: {e}")

    # Fallback
    return TELEGRAM_CHAT_IDS


def telegram_notify(title: str, message: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    chat_ids = get_dynamic_chat_ids()
    if not chat_ids:
        return
    text = f"<b>{title}</b>\n{message}"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in chat_ids:
        try:
            requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=15,
            )
        except Exception:
            pass


# ── D1 Bias ───────────────────────────────────────────────────────────────────

def compute_d1_bias(symbol: str):
    """Return (d1_bullish, d1_bearish). ADX-gated EMA cross on daily chart."""
    klines = ind.fetch_klines(symbol, "1d", limit=250)
    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    ema34 = ind.ema_series(closes, 34)
    ema89 = ind.ema_series(closes, 89)
    ema200 = ind.ema_series(closes, 200)
    _, _, hist_d1 = ind.macd_series(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    adx = ind.compute_adx(highs, lows, closes)
    e34, e89, e200, h, p = ema34[-1], ema89[-1], ema200[-1], hist_d1[-1], closes[-1]
    threshold = p * 0.0001
    raw_bull = (
        e34 is not None and e89 is not None and e34 > e89
        and (e200 is None or p > e200)
        and h is not None and h > -threshold
    )
    raw_bear = (
        e34 is not None and e89 is not None and e34 < e89
        and (e200 is None or p < e200)
        and h is not None and h < threshold
    )
    is_trending = adx["trending"]
    return raw_bull and is_trending, raw_bear and is_trending


# ── Per-candle signal engine ──────────────────────────────────────────────────

def compute_candle_signals(
    closes, highs, lows, rsi, macd_hist,
    ema34, ema50, ema89, ema200,
    sma_50, sma_150, bb_upper, bb_lower, stoch_k, williams_r,
    buy_zone_low, buy_zone_high, sell_zone_low, sell_zone_high,
    d1_bullish, d1_bearish, btc_rsi_h4, btc_macd_hist,
    atr_series=None, volumes=None, fng_adj=None, funding_adj=None,
) -> List[dict]:
    n = len(closes)
    _obv = ind.compute_obv_signals(closes, volumes or []) if volumes else {"buy_vol_score": 0, "sell_vol_score": 0}
    _dyn_oversold, _dyn_overbought = ind.dynamic_rsi_thresholds(rsi, lookback=100)
    results = []

    for i in range(n):
        price = closes[i]
        rsi_i = rsi[i] if i < len(rsi) else None
        macd_i = macd_hist[i] if i < len(macd_hist) else None
        macd_p = macd_hist[i - 1] if i > 0 and (i - 1) < len(macd_hist) else None
        e34_i = ema34[i] if i < len(ema34) else None
        e89_i = ema89[i] if i < len(ema89) else None
        s150_i = sma_150[i] if i < len(sma_150) else None
        bb_u = bb_upper[i] if i < len(bb_upper) else None
        bb_l = bb_lower[i] if i < len(bb_lower) else None
        sk = stoch_k[i] if i < len(stoch_k) else None
        wr_i = williams_r[i] if i < len(williams_r) else None
        atr_i = atr_series[i] if atr_series and i < len(atr_series) else None

        vol_extreme = vol_high = False
        if atr_i is not None and price > 0:
            atr_pct = atr_i / price * 100
            if atr_pct > 5.0:
                vol_extreme = True
            elif atr_pct > 3.0:
                vol_high = True

        # ── BUY SCORE ────────────────────────────────────────────────
        buy_score = 0
        in_buy_zone = (
            buy_zone_low is not None and buy_zone_high is not None
            and buy_zone_low <= price <= buy_zone_high
        )
        if in_buy_zone:
            buy_score += 3
            if rsi_i is not None:
                if rsi_i < 45: buy_score += 1
                if rsi_i < 35: buy_score += 1
            if macd_i is not None and macd_p is not None:
                if macd_i > macd_p: buy_score += 1
                if macd_i > 0: buy_score += 1
            if e34_i is not None and e89_i is not None and e34_i > e89_i:
                buy_score += 1
            if s150_i is not None and price > s150_i:
                buy_score += 1
            if sk is not None and sk < 30: buy_score += 1
            if wr_i is not None and wr_i < -70: buy_score += 1
            if d1_bullish: buy_score += 2
            if bb_l is not None and price <= bb_l: buy_score += 1
            if rsi_i is not None and rsi_i < _dyn_oversold: buy_score += 1
            if i >= n - 3: buy_score += _obv["buy_vol_score"]
            if fng_adj: buy_score += fng_adj.get("buy_adj", 0)
            if funding_adj: buy_score += funding_adj.get("buy_adj", 0)

        # ── SELL SCORE ───────────────────────────────────────────────
        sell_score = 0
        in_sell_zone = (
            sell_zone_low is not None and sell_zone_high is not None
            and sell_zone_low <= price <= sell_zone_high
        )
        if in_sell_zone:
            sell_score += 3
            if rsi_i is not None:
                if rsi_i > 55: sell_score += 1
                if rsi_i > 65: sell_score += 1
            if macd_i is not None and macd_p is not None:
                if macd_i < macd_p: sell_score += 1
                if macd_i < 0: sell_score += 1
            if e34_i is not None and e89_i is not None and e34_i < e89_i:
                sell_score += 1
            if sk is not None and sk > 70: sell_score += 1
            if wr_i is not None and wr_i > -30: sell_score += 1
            if d1_bearish: sell_score += 2
            if bb_u is not None and price >= bb_u: sell_score += 1
            if rsi_i is not None and rsi_i > _dyn_overbought: sell_score += 1
            if i >= n - 3: sell_score += _obv["sell_vol_score"]
            if fng_adj: sell_score += fng_adj.get("sell_adj", 0)
            if funding_adj: sell_score += funding_adj.get("sell_adj", 0)

        # ── DANGER ZONE ──────────────────────────────────────────────
        dz_flags = []
        if d1_bearish: dz_flags.append("D1Bear")
        if bb_u is not None and rsi_i is not None and price >= bb_u and rsi_i > 72:
            dz_flags.append("OBought")
        if btc_rsi_h4 is not None and btc_macd_hist is not None and btc_rsi_h4 < 35 and btc_macd_hist < 0:
            dz_flags.append("BTCweak")
        is_danger_zone = len(dz_flags) > 0

        buy_blocked = is_danger_zone
        btc_bull = (btc_rsi_h4 is not None and btc_rsi_h4 > 65
                    and btc_macd_hist is not None and btc_macd_hist > 0)
        sell_blocked = d1_bullish or btc_bull

        is_buy_signal = buy_score >= 4 and not buy_blocked
        is_sell_signal = sell_score >= 4 and not sell_blocked

        if vol_extreme:
            is_buy_signal = is_sell_signal = False
        elif vol_high:
            is_buy_signal = buy_score >= 6 and not buy_blocked
            is_sell_signal = sell_score >= 6 and not sell_blocked

        buy_strength = 3 if buy_score >= 9 else (2 if buy_score >= 6 else 1)
        sell_strength = 3 if sell_score >= 9 else (2 if sell_score >= 6 else 1)
        signal_strength = (
            buy_strength if is_buy_signal else
            sell_strength if is_sell_signal else 0
        )

        zone = "buy" if in_buy_zone else ("sell" if in_sell_zone else "neutral")

        parts = []
        if is_buy_signal: parts.append(f"BUY str={buy_strength} score={buy_score}")
        if is_sell_signal: parts.append(f"SELL str={sell_strength} score={sell_score}")
        if dz_flags: parts.append("DANGER:" + ",".join(dz_flags))
        if not parts: parts.append(f"zone={zone} b={buy_score} s={sell_score}")
        signal_detail = " | ".join(parts)

        atr_levels = {}
        if atr_i and price > 0:
            mult = 1.5 if signal_strength == 3 else 2.0
            risk = mult * atr_i
            if is_buy_signal:
                atr_levels = {
                    "stop_loss": round(price - risk, 2),
                    "take_profit": round(price + 2 * risk, 2),
                    "atr": round(atr_i, 4),
                    "atr_pct": round(atr_i / price * 100, 2),
                }
            elif is_sell_signal:
                atr_levels = {
                    "stop_loss": round(price + risk, 2),
                    "take_profit": round(price - 2 * risk, 2),
                    "atr": round(atr_i, 4),
                    "atr_pct": round(atr_i / price * 100, 2),
                }

        results.append({
            "is_buy_signal": bool(is_buy_signal),
            "is_sell_signal": bool(is_sell_signal),
            "is_danger_zone": bool(is_danger_zone),
            "signal_strength": signal_strength,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "zone": zone,
            "signal_detail": signal_detail,
            "atr_levels": atr_levels,
        })

    return results


# ── Tracker (BUY/SELL/HOLD decision) ────────────────────────────────────────

def _decide_action(
    price, rsi_h4, macd_hist, prev_macd_hist, zones,
    btc_rsi_h4, btc_macd_hist, btc_prev_macd_hist,
    rsi_buy_threshold=None, rsi_sell_threshold=None,
) -> Dict[str, str]:
    rsi_buy_thr = rsi_buy_threshold if rsi_buy_threshold is not None else ETH_RSI_BUY
    rsi_sell_thr = rsi_sell_threshold if rsi_sell_threshold is not None else ETH_RSI_SELL
    sell_low, sell_high, buy_low, buy_high, recent_low, recent_high = zones

    reasons = [
        f"Dynamic zones: BUY[{buy_low:.1f}-{buy_high:.1f}] "
        f"SELL[{sell_low:.1f}-{sell_high:.1f}] "
        f"(range {recent_low:.1f}-{recent_high:.1f})"
    ]
    action = "HOLD"

    macd_weakening = macd_hist > 0 and prev_macd_hist is not None and macd_hist < prev_macd_hist

    if sell_low <= price <= sell_high and rsi_h4 >= rsi_sell_thr and macd_weakening:
        action = "SELL"
        reasons.append(f"Price in SELL zone & RSI_H4 {rsi_h4:.1f} >= {rsi_sell_thr:.1f}")
        reasons.append(f"MACD hist weakening: {macd_hist:.4f} < {prev_macd_hist:.4f}")
    elif buy_low <= price <= buy_high and rsi_h4 <= rsi_buy_thr:
        action = "BUY"
        reasons.append(f"Price in BUY zone & RSI_H4 {rsi_h4:.1f} <= {rsi_buy_thr:.1f}")
    else:
        reasons.append("No buy/sell condition matched (HOLD).")

    btc_bull_rsi = btc_rsi_h4 >= 65
    btc_macd_stronger = btc_macd_hist > 0 and btc_prev_macd_hist is not None and btc_macd_hist >= btc_prev_macd_hist

    if action == "SELL" and (btc_bull_rsi or btc_macd_stronger):
        reasons.append(
            f"Cancel SELL: BTC still bullish (RSI_H4={btc_rsi_h4:.1f}, "
            f"MACD hist {btc_macd_hist:.4f} >= prev {btc_prev_macd_hist:.4f})"
        )
        action = "HOLD"

    if abs(macd_hist) < 0.5:
        reasons.append("MACD hist ~0 → momentum weak / sideway.")
    elif macd_hist > 0:
        reasons.append("MACD hist > 0 → bullish momentum.")
    else:
        reasons.append("MACD hist < 0 → bearish momentum.")

    return {"action": action, "reason": " | ".join(reasons)}


def run_symbol_tracker_once(symbol: str, send_notify: bool = False) -> Dict[str, Any]:
    """Run one analysis cycle for a symbol. Returns full payload dict."""
    symbol = symbol.upper()
    interval = TRACKER_INTERVAL

    price, rsi_h4 = ind.rsi_latest(symbol, interval, RSI_PERIOD)
    macd_line, macd_signal, macd_hist, prev_macd_hist = ind.macd_latest_with_prev(symbol, interval)
    btc_price, btc_rsi_h4 = ind.rsi_latest("BTCUSDT", interval, RSI_PERIOD)
    _, _, btc_macd_hist, btc_prev_macd_hist = ind.macd_latest_with_prev("BTCUSDT", interval)
    zones = ind.compute_zones(symbol, interval, lookback=60)
    sell_low, sell_high, buy_low, buy_high, recent_low, recent_high = zones

    rsi_buy_thr = rsi_sell_thr = None
    try:
        kl = ind.fetch_klines(symbol, interval, limit=150)
        closes_full = [float(k[4]) for k in kl]
        rsi_s = ind.rsi_series(closes_full, RSI_PERIOD)
        rsi_buy_thr, rsi_sell_thr = ind.dynamic_rsi_thresholds(rsi_s)
    except Exception:
        pass

    decision = _decide_action(
        price=price, rsi_h4=rsi_h4, macd_hist=macd_hist, prev_macd_hist=prev_macd_hist,
        zones=zones, btc_rsi_h4=btc_rsi_h4, btc_macd_hist=btc_macd_hist,
        btc_prev_macd_hist=btc_prev_macd_hist,
        rsi_buy_threshold=rsi_buy_thr, rsi_sell_threshold=rsi_sell_thr,
    )
    action = decision["action"]
    reason = decision["reason"]
    now_utc = datetime.utcnow().isoformat() + "Z"

    payload: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": interval,
        "now_utc": now_utc,
        "price": price,
        "rsi_h4": rsi_h4,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "action": action,
        "reason": reason,
        "zones": {
            "sell_low": sell_low, "sell_high": sell_high,
            "buy_low": buy_low, "buy_high": buy_high,
            "recent_low": recent_low, "recent_high": recent_high,
        },
        "btc": {
            "price": btc_price, "rsi_h4": btc_rsi_h4,
            "macd_hist": btc_macd_hist, "prev_macd_hist": btc_prev_macd_hist,
        },
    }

    if send_notify and action != "HOLD" and _can_notify(symbol, action):
        _mark_notified(symbol, action)
        try:
            title = f"[{action}] {symbol}"
            atr_val = None
            try:
                kl_atr = ind.fetch_klines(symbol, interval, limit=50)
                h_atr = [float(k[2]) for k in kl_atr]
                l_atr = [float(k[3]) for k in kl_atr]
                c_atr = [float(k[4]) for k in kl_atr]
                atr_s = ind.atr_series(h_atr, l_atr, c_atr)
                atr_val = next((v for v in reversed(atr_s) if v is not None), None)
            except Exception:
                pass

            msg_lines = [
                f"💰 Giá: <b>{price:,.2f}</b> USDT",
                f"📊 RSI H4: {rsi_h4:.1f} | MACD Hist: {macd_hist:.4f}",
                f"🎯 Zone: BUY[{buy_low:.1f}-{buy_high:.1f}] SELL[{sell_low:.1f}-{sell_high:.1f}]",
                f"₿ BTC RSI: {btc_rsi_h4:.1f} | BTC MACD: {btc_macd_hist:.4f}",
            ]
            atr_pct_val = 0.0
            if atr_val:
                mult = 2.0
                risk = mult * atr_val
                atr_pct_val = atr_val / price * 100
                if action == "BUY":
                    sl, tp = price - risk, price + 2 * risk
                else:
                    sl, tp = price + risk, price - 2 * risk
                msg_lines.append(f"🛑 SL: {sl:,.2f} | 🎯 TP: {tp:,.2f} (ATR×{mult})")
                msg_lines.append(f"📐 ATR: {atr_val:.2f} ({atr_pct_val:.2f}%)")
            msg_lines.append(f"⏰ {now_utc}")

            d1_bull = d1_bear = False
            try:
                d1_bull, d1_bear = compute_d1_bias(symbol)
            except Exception:
                pass

            ai_brief = ai_brief_for_telegram(
                symbol=symbol, action=action, price=price, rsi=rsi_h4,
                macd_hist=macd_hist, d1_bullish=d1_bull, d1_bearish=d1_bear,
                btc_rsi=btc_rsi_h4, atr_pct=atr_pct_val, interval=interval,
            )
            if ai_brief:
                msg_lines.append(f"\n🤖 <i>{ai_brief}</i>")

            telegram_notify(title, "\n".join(msg_lines))
        except Exception as e:
            logging.error(f"[TRACKER_NOTIFY] Error: {e}")

    return payload


# ── DB persistence ────────────────────────────────────────────────────────────

def save_signal_to_db(
    supabase_admin,
    symbol: str,
    timeframe: str,
    signal_type: str,
    price: float,
    rsi: Optional[float] = None,
    macd_hist: Optional[float] = None,
    buy_score: int = 0,
    sell_score: int = 0,
    signal_strength: int = 1,
    signal_detail: str = "",
) -> None:
    try:
        from datetime import timezone, timedelta
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(minutes=NOTIFY_COOLDOWN_MINUTES)).isoformat()
        check = (
            supabase_admin.table("signal_history")
            .select("id")
            .eq("symbol", symbol)
            .eq("timeframe", timeframe)
            .eq("signal_type", signal_type)
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        if check.data:
            logging.info(f"[SIGNAL_DB] Skip duplicate {signal_type} {symbol}")
            return
        supabase_admin.table("signal_history").insert({
            "symbol": symbol, "timeframe": timeframe, "signal_type": signal_type,
            "price": price, "rsi": rsi, "macd_hist": macd_hist,
            "buy_score": buy_score, "sell_score": sell_score,
            "signal_strength": signal_strength, "signal_detail": signal_detail,
        }).execute()
        logging.info(f"[SIGNAL_DB] Saved {signal_type} {symbol} @ {price}")
    except Exception as e:
        logging.error(f"[SIGNAL_DB] Error: {e}")


# ── Background job ────────────────────────────────────────────────────────────

def symbols_tracker_job(supabase_admin) -> None:
    """Run every 10 minutes: check all active subscriptions, send alerts, save to DB."""
    try:
        rows = (
            supabase_admin.table("bot_subscriptions")
            .select("symbol")
            .eq("is_active", True)
            .execute()
        ).data or []
    except Exception as e:
        logging.error(f"[TRACKER_JOB] Error fetch subscriptions: {e}")
        return

    try:
        fng = ind.fetch_fear_greed()
        logging.info(f"[TRACKER_JOB] F&G Index: {fng['value']}")
    except Exception:
        pass

    for row in rows:
        symbol = (row.get("symbol") or "").upper()
        if not symbol:
            continue
        try:
            payload = run_symbol_tracker_once(symbol, send_notify=True)
            action = payload["action"]
            logging.info(f"[TRACKER_JOB] {symbol}: action={action} price={payload['price']}")
            if action in ("BUY", "SELL"):
                save_signal_to_db(
                    supabase_admin,
                    symbol=symbol,
                    timeframe=payload.get("timeframe", TRACKER_INTERVAL),
                    signal_type=action,
                    price=payload["price"],
                    rsi=payload.get("rsi_h4"),
                    macd_hist=payload.get("macd_hist"),
                    signal_detail=payload.get("reason", ""),
                )
        except Exception as e:
            logging.error(f"[TRACKER_JOB] {symbol}: {e}")
