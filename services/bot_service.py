"""
bot_service.py — Multi-Timeframe crypto bot (v6 algorithm).
  1D trend filter + 4H entry signals + ATR trailing stop.

  v6 vs v5: bounce_rsi 30-65 (was 40-60), breakeven 0.1xATR (was 0.3/0.2)

BOT_MODE=default    -> pos=70%, sl=2.0xATR, score>=5, adx>=20
BOT_MODE=optimized  -> pos=50%, sl=1.5xATR, score>=4, adx>=22(BTC)/18(ETH)
"""

import os, time, threading, logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from services import bot_indicators as ind

# ── Env ───────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS  = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
RSI_SYMBOLS        = [s.strip() for s in os.getenv("RSI_SYMBOLS", "ETHUSDT,BTCUSDT").split(",") if s.strip()] or ["ETHUSDT", "BTCUSDT"]
NOTIFY_COOLDOWN_MINUTES = int(os.getenv("NOTIFY_COOLDOWN_MINUTES", "120"))
BOT_MODE           = os.getenv("BOT_MODE", "default").lower()

# Keep these for router compatibility
TRACKER_INTERVAL = "4h"
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

# ── Strategy config ───────────────────────────────────────────────────────────
_BASE_CFG = dict(
    position_pct   = 0.70,
    sl_atr_mult    = 2.0,
    commission_pct = 0.075,
    rsi_dip        = 40.0,
    bb_pct_dip     = 0.20,
    adx_min        = 20.0,
    buy_score_min  = 5,
    rsi_max_entry  = 75.0,
    sell_score_exit= 4,
    rsi_exit       = 70.0,
    stoch_ob       = 85.0,
    adx_bear_exit  = 25.0,
    rsi_trend_break= 40.0,
    trail_tier3    = 3.0,
    trail_tier2    = 2.0,
    trail_tier1    = 1.0,
    breakeven_atr  = 0.1,
    # MODE B: Bear Bounce
    bounce_position_pct    = 0.30,
    bounce_sl_atr          = 1.5,
    bounce_adx_max_1d      = 35.0,
    bounce_rsi_min         = 30.0,
    bounce_rsi_max         = 65.0,
    bounce_exit_rsi        = 65.0,
    bounce_exit_sell_score = 3,
    bounce_exit_rsi_mom    = 55.0,
    bounce_trail_t2        = 1.5,
    bounce_trail_t1        = 0.8,
    bounce_breakeven_atr   = 0.1,
    # BREAKOUT_BUY
    breakout_position_pct  = 0.50,
    breakout_sl_atr        = 2.0,
    breakout_min_bars      = 15,
    breakout_rsi_min       = 40.0,
    breakout_rsi_max       = 68.0,
)

_OPT_OVERRIDES: Dict[str, dict] = {
    "BTCUSDT":  dict(position_pct=0.50, sl_atr_mult=1.5, buy_score_min=4, adx_min=22.0),
    "ETHUSDT":  dict(position_pct=0.50, sl_atr_mult=1.5, buy_score_min=4, adx_min=18.0),
    "_default": dict(position_pct=0.50, sl_atr_mult=1.5, buy_score_min=4, adx_min=20.0),
}

def get_bot_config(symbol: str) -> dict:
    if BOT_MODE == "optimized":
        overrides = _OPT_OVERRIDES.get(symbol, _OPT_OVERRIDES["_default"])
        return {**_BASE_CFG, **overrides}
    return dict(_BASE_CFG)

# ── In-memory state ───────────────────────────────────────────────────────────
_open_positions: Dict[str, dict] = {}   # {symbol: {entry_price, stop_price, ...}}
_notify_last_sent: Dict[str, float] = {}
_chat_ids_cache: Dict[str, Any] = {"ids": [], "fetched_at": 0.0}
CHAT_IDS_CACHE_TTL = 300
_cmd_update_offset: int = 0             # last processed update_id + 1 for /check command polling

# ── Telegram ──────────────────────────────────────────────────────────────────
def _can_notify(key: str) -> bool:
    return (time.time() - _notify_last_sent.get(key, 0.0)) >= NOTIFY_COOLDOWN_MINUTES * 60

def _mark_notified(key: str) -> None:
    _notify_last_sent[key] = time.time()

def get_dynamic_chat_ids() -> List[str]:
    if not TELEGRAM_BOT_TOKEN:
        return TELEGRAM_CHAT_IDS
    now = time.time()
    if now - _chat_ids_cache["fetched_at"] < CHAT_IDS_CACHE_TTL and _chat_ids_cache["ids"]:
        return _chat_ids_cache["ids"]
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        chat_ids: set = set()
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
                    if msg:
                        chat = msg.get("chat")
                        if chat and chat.get("id"):
                            chat_ids.add(str(chat["id"]))
                cb = upd.get("callback_query")
                if cb:
                    msg = (cb.get("message") or {})
                    chat = msg.get("chat")
                    if chat and chat.get("id"):
                        chat_ids.add(str(chat["id"]))
            last_id = results[-1].get("update_id")
            if last_id is None or len(results) < 100:
                break
            offset = last_id + 1
        if chat_ids:
            ids = list(chat_ids)
            _chat_ids_cache.update({"ids": ids, "fetched_at": now})
            return ids
    except Exception as e:
        logging.warning(f"[TELEGRAM] getUpdates: {e}")
    return TELEGRAM_CHAT_IDS

def telegram_notify(title: str, message: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    chat_ids = get_dynamic_chat_ids()
    if not chat_ids:
        return
    text = f"<b>{title}</b>\n{message}"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for cid in chat_ids:
        try:
            requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "HTML"}, timeout=15)
        except Exception:
            pass

# ── 1H trend (for multi-timeframe display) ───────────────────────────────────
def get_1h_trend(symbol: str) -> dict:
    """Fetch 1H klines and return simplified trend info."""
    try:
        klines = ind.fetch_klines(symbol, "1h", limit=150)
        closes = [float(k[4]) for k in klines]
        highs  = [float(k[2]) for k in klines]
        lows   = [float(k[3]) for k in klines]

        e34  = ind.ema_series(closes, 34)
        e89  = ind.ema_series(closes, 89)
        rsi  = ind.rsi_series(closes, 14)
        _, _, macd_h = ind.macd_series(closes, 12, 26, 9)

        rsi_v = rsi[-1] if rsi else 50.0
        mh    = macd_h[-1] if macd_h else 0.0
        mh_p  = macd_h[-2] if len(macd_h) >= 2 else 0.0
        macd_rising = mh > mh_p
        ema_bull = bool(e34[-1] and e89[-1] and e34[-1] > e89[-1])
        uptrend  = ema_bull and macd_rising

        return {"uptrend": uptrend, "rsi": rsi_v, "macd_rising": macd_rising, "ema_bull": ema_bull}
    except Exception as e:
        logging.warning(f"[1H] {symbol}: {e}")
        return {}

# ── 1D context ────────────────────────────────────────────────────────────────
def get_daily_context(symbol: str) -> dict:
    klines = ind.fetch_klines(symbol, "1d", limit=250)
    closes = [float(k[4]) for k in klines]
    highs  = [float(k[2]) for k in klines]
    lows   = [float(k[3]) for k in klines]

    e34  = ind.ema_series(closes, 34)
    e89  = ind.ema_series(closes, 89)
    e200 = ind.ema_series(closes, 200)
    rsi  = ind.rsi_series(closes, 14)
    _, bb_upper, _ = ind.bollinger_bands(closes, 20, 2.0)

    price = closes[-1]
    return {
        "uptrend":  e200[-1] is not None and price > e200[-1],
        "bull_ema": e34[-1] is not None and e89[-1] is not None and e34[-1] > e89[-1],
        "bear_ema": e34[-1] is not None and e89[-1] is not None and e34[-1] < e89[-1],
        "danger":   bb_upper[-1] is not None and price >= bb_upper[-1] and rsi[-1] > 72,
        "rsi":      rsi[-1] if rsi else 50.0,
        "adx":      ind.compute_adx(highs, lows, closes)["adx"],
        "price":    price,
        "ema200":   e200[-1],
    }

# ── 4H snapshot ───────────────────────────────────────────────────────────────
def get_4h_snapshot(symbol: str) -> dict:
    klines = ind.fetch_klines(symbol, "4h", limit=250)
    closes = [float(k[4]) for k in klines]
    highs  = [float(k[2]) for k in klines]
    lows   = [float(k[3]) for k in klines]
    vols   = [float(k[5]) for k in klines]

    rsi_s   = ind.rsi_series(closes, 14)
    _, _, macd_h = ind.macd_series(closes, 12, 26, 9)
    e34  = ind.ema_series(closes, 34)
    e50  = ind.ema_series(closes, 50)
    e89  = ind.ema_series(closes, 89)
    e200 = ind.ema_series(closes, 200)
    _, bb_upper, bb_lower = ind.bollinger_bands(closes, 20, 2.0)
    stoch = ind.stochastic_k(highs, lows, closes, 14)
    atr_s = ind.atr_series(highs, lows, closes, 14)
    adx_r = ind.compute_adx(highs, lows, closes)
    obv_r = ind.compute_obv_signals(closes, vols)
    dyn_os, dyn_ob = ind.dynamic_rsi_thresholds(rsi_s, 100)

    try:
        zones = ind.compute_zones(symbol, "4h", lookback=60)
        sl, sh, bl, bh, _, _ = zones
    except Exception:
        sl = sh = bl = bh = None

    price   = closes[-1]
    rsi_v   = rsi_s[-1] if rsi_s else 50.0
    mh      = macd_h[-1] if macd_h else 0.0
    mh_p    = macd_h[-2] if len(macd_h) >= 2 else 0.0
    macd_rising = mh > mh_p
    bb_u    = bb_upper[-1]
    bb_l    = bb_lower[-1]
    atr_v   = atr_s[-1] if atr_s else 0.0
    stk     = stoch[-1] if stoch else 50.0
    e34_v   = e34[-1]
    e50_v   = e50[-1]
    e89_v   = e89[-1]

    # Đếm số bar liên tiếp close < EMA200 (trước bar hiện tại)
    bars_below_ema200 = 0
    for j in range(len(closes) - 2, -1, -1):
        if e200[j] is None: break
        if closes[j] < e200[j]:
            bars_below_ema200 += 1
        else:
            break

    bb_pct = None
    if bb_u is not None and bb_l is not None and bb_u > bb_l:
        bb_pct = (price - bb_l) / (bb_u - bb_l)

    in_buy  = bl is not None and bh is not None and bl <= price <= bh
    in_sell = sl is not None and sh is not None and sl <= price <= sh

    # Buy score (adapted from v2)
    bs = 0
    if in_buy: bs += 3
    if rsi_v < 45: bs += 1
    if rsi_v < 35: bs += 1
    if macd_rising: bs += 1
    if mh > 0: bs += 1
    if e34_v and e89_v and e34_v > e89_v: bs += 1
    if stk and stk < 30: bs += 1
    if bb_l and price <= bb_l: bs += 1
    if rsi_v < dyn_os: bs += 1
    if obv_r["obv_trend"] == "up": bs += 1
    bs = min(bs, 13)

    # Sell score
    ss = 0
    if in_sell: ss += 3
    if rsi_v > 55: ss += 1
    if rsi_v > 65: ss += 1
    if not macd_rising: ss += 1
    if mh < 0: ss += 1
    if e34_v and e89_v and e34_v < e89_v: ss += 1
    if stk and stk > 70: ss += 1
    if bb_u and price >= bb_u: ss += 1
    if rsi_v > dyn_ob: ss += 1
    if obv_r["obv_trend"] == "down": ss += 1
    ss = min(ss, 13)

    return {
        "price": price, "rsi_14": rsi_v, "macd_hist": mh, "macd_rising": macd_rising,
        "adx_14": adx_r["adx"], "di_plus": adx_r["di_plus"], "di_minus": adx_r["di_minus"],
        "stoch_k": stk, "atr_14": atr_v, "bb_pct": bb_pct,
        "bb_upper": bb_u, "bb_lower": bb_l,
        "ema34": e34_v, "ema50": e50_v, "ema89": e89_v, "ema200": e200[-1],
        "buy_score": bs, "sell_score": ss,
        "in_buy_zone": in_buy, "in_sell_zone": in_sell,
        "obv_trend": obv_r["obv_trend"],
        "danger_overbought": bb_u is not None and price >= bb_u and rsi_v > 72,
        "dyn_oversold": dyn_os, "dyn_overbought": dyn_ob,
        "bars_below_ema200": bars_below_ema200,
    }

# ── Entry / Exit checks (v2 algorithm) ───────────────────────────────────────
def check_entry(snap: dict, dctx: dict, cfg: dict):
    if not dctx.get("uptrend"):
        return False, ""
    if dctx.get("danger"):
        return False, ""
    if snap["rsi_14"] >= cfg["rsi_max_entry"]:
        return False, ""

    bb_pct = snap.get("bb_pct")
    if snap["rsi_14"] < cfg["rsi_dip"] and bb_pct is not None and bb_pct < cfg["bb_pct_dip"]:
        return True, "DIP_BUY"

    if (snap["macd_rising"] and snap["macd_hist"] > 0
            and snap["adx_14"] > cfg["adx_min"]
            and snap["di_plus"] > snap["di_minus"]):
        return True, "TREND_FOLLOW"

    if snap["buy_score"] >= cfg["buy_score_min"] and snap["macd_rising"]:
        return True, "SCORE_BUY"

    return False, ""

def check_exit(snap: dict, dctx: dict, cfg: dict):
    if snap["sell_score"] >= cfg["sell_score_exit"] and snap["rsi_14"] > cfg["rsi_exit"]:
        return True, "SELL_SIG"
    if dctx.get("danger") and snap["stoch_k"] is not None and snap["stoch_k"] > cfg["stoch_ob"]:
        return True, "OB_EXIT"
    if dctx.get("bear_ema") and snap["adx_14"] > cfg["adx_bear_exit"]:
        return True, "BEAR"
    if not dctx.get("uptrend", True) and snap["rsi_14"] < cfg["rsi_trend_break"]:
        return True, "TREND_REV"
    return False, ""

def update_trailing_stop(price: float, entry: float, atr: float, current_stop: float, cfg: dict) -> float:
    if atr <= 0:
        return current_stop
    profit_atr = (price - entry) / atr
    if profit_atr > cfg["trail_tier3"]:
        return max(current_stop, price - 1.0 * atr)
    elif profit_atr > cfg["trail_tier2"]:
        return max(current_stop, price - 1.2 * atr)
    elif profit_atr > cfg["trail_tier1"]:
        return max(current_stop, price - 1.5 * atr)
    elif profit_atr > cfg["breakeven_atr"]:
        return max(current_stop, entry)
    return current_stop

def update_bounce_trailing(price: float, entry: float, atr: float, current_stop: float, cfg: dict) -> float:
    """Trailing stop nhẹ hơn cho MODE B (Bear Bounce)."""
    if atr <= 0: return current_stop
    profit_atr = (price - entry) / atr
    if profit_atr > cfg["bounce_trail_t2"]:
        return max(current_stop, price - 0.8 * atr)
    elif profit_atr > cfg["bounce_trail_t1"]:
        return max(current_stop, price - 1.0 * atr)
    elif profit_atr > cfg["bounce_breakeven_atr"]:
        return max(current_stop, entry)
    return current_stop

def check_bounce_entry(snap: dict, dctx: dict, cfg: dict):
    """MODE B: Bear Bounce — micro uptrend trong downtrend 1D."""
    if dctx.get("uptrend", True): return False, ""
    if dctx.get("adx", 50) >= cfg["bounce_adx_max_1d"]: return False, ""
    ema34 = snap.get("ema34"); ema50 = snap.get("ema50")
    if ema34 is None or ema50 is None or ema34 <= ema50: return False, ""
    if not (snap["macd_rising"] and snap["macd_hist"] > 0): return False, ""
    if not (cfg["bounce_rsi_min"] < snap["rsi_14"] < cfg["bounce_rsi_max"]): return False, ""
    return True, "BEAR_BOUNCE"

def check_bounce_exit(snap: dict, dctx: dict, cfg: dict):
    """Exit cho MODE B (Bear Bounce)."""
    ema34 = snap.get("ema34"); ema50 = snap.get("ema50")
    if ema34 is not None and ema50 is not None and ema34 < ema50:
        return True, "MICRO_LOST"
    if snap["rsi_14"] > cfg["bounce_exit_rsi"]: return True, "BOUNCE_OB"
    if snap["sell_score"] >= cfg["bounce_exit_sell_score"]: return True, "BOUNCE_SELL"
    if not snap["macd_rising"] and snap["macd_hist"] < 0 and snap["rsi_14"] > cfg["bounce_exit_rsi_mom"]:
        return True, "MOM_FADE"
    return False, ""

def check_breakout_entry(snap: dict, dctx: dict, bars_below: int, cfg: dict):
    """BREAKOUT_BUY: giá vừa tái chiếm EMA200 sau downtrend >= breakout_min_bars bar."""
    if not dctx.get("uptrend"): return False, ""
    if bars_below < cfg["breakout_min_bars"]: return False, ""
    if not (snap["macd_rising"] and snap["macd_hist"] > 0): return False, ""
    if not (cfg["breakout_rsi_min"] <= snap["rsi_14"] <= cfg["breakout_rsi_max"]): return False, ""
    return True, "BREAKOUT_BUY"

# ── Simulated trade ($10k) ────────────────────────────────────────────────────
def compute_simulated_trade(symbol: str, snap: dict, dctx: dict, cfg: dict) -> dict:
    price   = snap["price"]
    atr     = snap["atr_14"]
    pos     = _open_positions.get(symbol)

    if pos:
        trade_mode  = pos.get("mode", "trend")
        pos_pct     = (cfg["breakout_position_pct"] if trade_mode == "breakout"
                       else cfg["bounce_position_pct"] if trade_mode == "bounce"
                       else cfg["position_pct"])
        pos_usd     = 10_000 * pos_pct
        entry       = pos["entry_price"]
        stop        = pos["stop_price"]
        qty         = pos_usd / entry
        pnl_pct     = (price - entry) / entry * 100
        pnl_usd     = pos_usd * pnl_pct / 100
        sl_pct      = abs(entry - stop) / entry * 100
        profit_atr  = (price - entry) / max(atr, 0.001)
        tier = 3 if profit_atr > cfg["trail_tier3"] else \
               2 if profit_atr > cfg["trail_tier2"] else \
               1 if profit_atr > cfg["trail_tier1"] else \
               0 if profit_atr > cfg["breakeven_atr"] else -1
        tier_labels = {
            3: "Tier 3 - Tight (1xATR)", 2: "Tier 2 - Medium (1.2xATR)",
            1: "Tier 1 - Normal (1.5xATR)", 0: "Breakeven", -1: "Chua kich hoat",
        }
        return {
            "status": "IN_TRADE", "strategy": pos.get("strategy", ""),
            "mode": trade_mode,
            "entry_price": entry, "entry_time": pos.get("entry_time", ""),
            "stop_price": round(stop, 2), "current_price": price,
            "qty": round(qty, 6), "pos_usd": round(pos_usd, 0),
            "pnl_pct": round(pnl_pct, 2), "pnl_usd": round(pnl_usd, 2),
            "sl_pct": round(sl_pct, 2), "profit_atr": round(profit_atr, 2),
            "trail_tier": tier, "trail_label": tier_labels[tier],
        }
    else:
        bars_below = snap.get("bars_below_ema200", 0)
        # Check all modes in priority order
        entered, strategy = check_breakout_entry(snap, dctx, bars_below, cfg)
        if entered:
            pos_pct = cfg["breakout_position_pct"]; sl_mult = cfg["breakout_sl_atr"]
        else:
            entered, strategy = check_entry(snap, dctx, cfg)
            if entered:
                pos_pct = cfg["position_pct"]; sl_mult = cfg["sl_atr_mult"]
            else:
                entered, strategy = check_bounce_entry(snap, dctx, cfg)
                if entered:
                    pos_pct = cfg["bounce_position_pct"]; sl_mult = cfg["bounce_sl_atr"]
                else:
                    pos_pct = cfg["position_pct"]; sl_mult = cfg["sl_atr_mult"]

        pos_usd  = 10_000 * pos_pct
        sl       = price - sl_mult * atr
        tp_est   = price + cfg["trail_tier2"] * atr
        sl_pct   = abs(price - sl) / price * 100
        qty      = pos_usd / price
        risk_usd = pos_usd * sl_pct / 100
        return {
            "status": "SIGNAL" if entered else "WATCHING",
            "strategy": strategy,
            "entry_price": price, "stop_price": round(sl, 2),
            "tp_estimate": round(tp_est, 2),
            "qty": round(qty, 6), "pos_usd": round(pos_usd, 0),
            "sl_pct": round(sl_pct, 2), "risk_usd": round(risk_usd, 0),
            "pnl_pct": 0.0, "pnl_usd": 0.0,
        }

# ── Main tracker ──────────────────────────────────────────────────────────────
def run_symbol_tracker_once(symbol: str, send_notify: bool = True) -> dict:
    cfg = get_bot_config(symbol)
    try:
        dctx = get_daily_context(symbol)
        snap = get_4h_snapshot(symbol)
    except Exception as e:
        logging.error(f"[TRACKER] {symbol}: {e}")
        return {"action": "HOLD", "reason": str(e), "symbol": symbol,
                "snapshot": {}, "daily_context": {}, "simulated_trade": {}, "mode": BOT_MODE}

    price = snap["price"]
    atr   = snap["atr_14"]
    pos   = _open_positions.get(symbol)

    result = {
        "symbol": symbol, "price": price, "atr": atr,
        "action": "HOLD", "reason": "",
        "daily_context": dctx, "snapshot": snap,
        "position": pos, "config": cfg, "mode": BOT_MODE,
    }

    if pos:
        entry     = pos["entry_price"]
        old_stop  = pos["stop_price"]
        trade_mode = pos.get("mode", "trend")

        if trade_mode == "bounce":
            new_stop = update_bounce_trailing(price, entry, atr, old_stop, cfg)
        else:
            new_stop = update_trailing_stop(price, entry, atr, old_stop, cfg)
        _open_positions[symbol]["stop_price"] = new_stop
        result["position"] = dict(_open_positions[symbol])

        if price <= new_stop:
            pnl_pct = (price - entry) / entry * 100
            _open_positions.pop(symbol, None)
            result.update(action="CLOSE", reason="STOP_HIT", pnl_pct=pnl_pct)
            if send_notify and _can_notify(f"{symbol}_CLOSE"):
                _mark_notified(f"{symbol}_CLOSE")
                _send_close(symbol, entry, price, atr, pnl_pct, "Stop Loss", pos.get("strategy", ""), cfg, trade_mode)
            return result

        if trade_mode == "bounce":
            should_exit, exit_reason = check_bounce_exit(snap, dctx, cfg)
        else:
            should_exit, exit_reason = check_exit(snap, dctx, cfg)

        if should_exit:
            pnl_pct = (price - entry) / entry * 100
            _open_positions.pop(symbol, None)
            result.update(action="CLOSE", reason=exit_reason, pnl_pct=pnl_pct)
            if send_notify and _can_notify(f"{symbol}_CLOSE"):
                _mark_notified(f"{symbol}_CLOSE")
                emoji = "" if pnl_pct >= 0 else ""
                _send_close(symbol, entry, price, atr, pnl_pct, f"{emoji} {exit_reason}", pos.get("strategy", ""), cfg, trade_mode)
            return result

        result.update(action="HOLD_POS",
                      reason=f"stop={new_stop:.2f} pnl={((price-entry)/entry*100):+.2f}%")

    else:
        bars_below = snap.get("bars_below_ema200", 0)
        entered = False; strategy = ""; mode_str = "trend"

        # Priority 1: BREAKOUT_BUY
        should_enter, strategy = check_breakout_entry(snap, dctx, bars_below, cfg)
        if should_enter:
            entered = True; mode_str = "breakout"

        # Priority 2: Trend MODE A
        if not entered:
            should_enter, strategy = check_entry(snap, dctx, cfg)
            if should_enter:
                entered = True; mode_str = "trend"

        # Priority 3: Bear Bounce MODE B
        if not entered:
            should_enter, strategy = check_bounce_entry(snap, dctx, cfg)
            if should_enter:
                entered = True; mode_str = "bounce"

        if entered:
            pos_pct = (cfg["breakout_position_pct"] if mode_str == "breakout"
                       else cfg["bounce_position_pct"] if mode_str == "bounce"
                       else cfg["position_pct"])
            sl_mult = (cfg["breakout_sl_atr"] if mode_str == "breakout"
                       else cfg["bounce_sl_atr"] if mode_str == "bounce"
                       else cfg["sl_atr_mult"])
            stop = price - sl_mult * atr
            _open_positions[symbol] = {
                "entry_price": price, "stop_price": stop,
                "entry_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                "strategy": strategy, "entry_atr": atr,
                "mode": mode_str,
            }
            result.update(action="BUY", reason=strategy, strategy=strategy)
            if send_notify and _can_notify(f"{symbol}_BUY"):
                _mark_notified(f"{symbol}_BUY")
                _send_entry(symbol, price, stop, atr, strategy, snap, dctx, cfg, mode_str)
        else:
            result.update(action="LOOKING", reason="No entry condition")

    result["simulated_trade"] = compute_simulated_trade(symbol, snap, dctx, cfg)
    return result

# ── Telegram notification formatters ──────────────────────────────────────────
_STRAT_LABELS = {
    "DIP_BUY":      "Mua day (Dip Buy)",
    "TREND_FOLLOW": "Theo xu huong",
    "SCORE_BUY":    "Score-based",
    "BEAR_BOUNCE":  "Bear Bounce",
    "BREAKOUT_BUY": "Breakout EMA200",
}

def _send_entry(symbol, price, stop, atr, strategy, snap, dctx, cfg, trade_mode="trend"):
    mode_tag = "Optimized" if BOT_MODE == "optimized" else "Default"
    # Pos size theo đúng mode
    pos_pct = (cfg["breakout_position_pct"] if trade_mode == "breakout"
               else cfg["bounce_position_pct"] if trade_mode == "bounce"
               else cfg["position_pct"])
    sl_pct   = abs(price - stop) / price * 100
    tp_est   = price + cfg["trail_tier2"] * atr
    pos_usd  = 10_000 * pos_pct
    qty      = pos_usd / price
    risk_usd = pos_usd * sl_pct / 100
    strat    = _STRAT_LABELS.get(strategy, strategy)

    # Mode label
    mode_labels = {"trend": "Trend", "bounce": "Bear Bounce", "breakout": "Breakout EMA200"}
    mode_label  = mode_labels.get(trade_mode, trade_mode.capitalize())

    # Extra context cho bounce / breakout
    extra = ""
    if trade_mode == "bounce":
        extra = f"\nEMA34: ${snap.get('ema34', 0):,.2f} | EMA50: ${snap.get('ema50', 0):,.2f}"
    elif trade_mode == "breakout":
        extra = f"\nBars below EMA200 truoc day: {snap.get('bars_below_ema200', 0)}"

    # Parallel AI macro
    macro      = ind.fetch_macro_snapshot()
    m1_text    = m2_text = ""
    try:
        from services.bot_ai import ai_macro_brief, OPENROUTER_MODEL, OPENROUTER_MODEL2
        m1_res, m2_res = {}, {}
        def _m1(): m1_res["t"] = ai_macro_brief(symbol, "BUY", price, macro, "4h", OPENROUTER_MODEL, "correlation")
        def _m2(): m2_res["t"] = ai_macro_brief(symbol, "BUY", price, macro, "4h", OPENROUTER_MODEL2, "risk")
        t1 = threading.Thread(target=_m1); t2 = threading.Thread(target=_m2)
        t1.start(); t2.start(); t1.join(timeout=20); t2.join(timeout=20)
        m1_text = m1_res.get("t", ""); m2_text = m2_res.get("t", "")
    except Exception:
        pass

    macro_block = ""
    if m1_text: macro_block += f"\nMacro: {m1_text}"
    if m2_text: macro_block += f"\nRisk: {m2_text}"

    msg = (
        f"Chien luoc: <b>{strat}</b> [{mode_label}] ({mode_tag})\n"
        f"---\n"
        f"Vao: <b>${price:,.2f}</b>\n"
        f"SL: <b>${stop:,.2f}</b> (-{sl_pct:.1f}%)\n"
        f"TP uoc tinh: <b>${tp_est:,.2f}</b> (+{(tp_est-price)/price*100:.1f}%)\n"
        f"---\n"
        f"Gia lap $10,000\n"
        f"Vi the: ${pos_usd:,.0f} ({pos_pct*100:.0f}%)\n"
        f"SL luong: {qty:.4f} {symbol.replace('USDT','')}\n"
        f"Rui ro: ~${risk_usd:,.0f}\n"
        f"---\n"
        f"RSI: {snap['rsi_14']:.1f} | ADX: {snap['adx_14']:.1f} | ATR: ${atr:,.2f}\n"
        f"1D: {'Uptrend' if dctx['uptrend'] else 'Downtrend'}"
        f"{extra}"
        f"{macro_block}"
    )
    telegram_notify(f"{symbol} - TIN HIEU MUA", msg)

def _send_close(symbol, entry, exit_price, atr, pnl_pct, reason_label, strategy, cfg, trade_mode="trend"):
    pos_pct = (cfg["breakout_position_pct"] if trade_mode == "breakout"
               else cfg["bounce_position_pct"] if trade_mode == "bounce"
               else cfg["position_pct"])
    pos_usd  = 10_000 * pos_pct
    pnl_usd  = pos_usd * pnl_pct / 100
    strat    = _STRAT_LABELS.get(strategy, strategy)
    msg = (
        f"Ly do: <b>{reason_label}</b>\n"
        f"---\n"
        f"Vao: ${entry:,.2f} -&gt; Ra: ${exit_price:,.2f}\n"
        f"P&amp;L: <b>{pnl_pct:+.2f}%</b> (~${pnl_usd:+,.0f})\n"
        f"Chien luoc: {strat}"
    )
    telegram_notify(f"{symbol} - Dong lenh", msg)

# ── Background job (called by scheduler) ─────────────────────────────────────
def _db_record_buy(supabase, symbol: str, result: dict):
    """Insert a new BUY trade row into signal_history."""
    snap       = result.get("snapshot", {})
    cfg        = get_bot_config(symbol)
    price      = result.get("price") or snap.get("price")
    trade_mode = result.get("position", {}).get("mode", "trend") if result.get("position") else "trend"
    pos_pct    = (cfg["breakout_position_pct"] if trade_mode == "breakout"
                  else cfg["bounce_position_pct"] if trade_mode == "bounce"
                  else cfg["position_pct"])
    pos_usd = 10_000 * pos_pct
    supabase.table("signal_history").insert({
        "symbol":        symbol,
        "signal_type":   "BUY",
        "status":        "open",
        "price":         price,
        "entry_price":   price,
        "rsi":           snap.get("rsi_14"),
        "macd_hist":     snap.get("macd_hist"),
        "buy_score":     snap.get("buy_score", 0),
        "sell_score":    snap.get("sell_score", 0),
        "signal_strength": 2,
        "signal_detail": result.get("reason", ""),
        "strategy":      result.get("strategy", result.get("reason", "")),
        "position_usd":  round(pos_usd, 2),
    }).execute()


def _db_record_close(supabase, symbol: str, result: dict):
    """Find the most recent open BUY for this symbol and close it with P&L."""
    snap      = result.get("snapshot", {})
    cfg       = get_bot_config(symbol)
    exit_price = result.get("price") or snap.get("price")
    reason     = result.get("reason", "")
    now_iso    = datetime.utcnow().isoformat()

    # Find open row
    rows = (supabase.table("signal_history")
            .select("id,entry_price,position_usd")
            .eq("symbol", symbol).eq("status", "open")
            .order("created_at", desc=True).limit(1).execute()).data or []

    if rows:
        row       = rows[0]
        row_id    = row["id"]
        entry     = float(row.get("entry_price") or exit_price)
        pos_usd   = float(row.get("position_usd") or 10_000 * cfg["position_pct"])
        pnl_pct   = (exit_price - entry) / entry * 100 if entry else 0.0
        fee       = pos_usd * cfg["commission_pct"] / 100
        pnl_usd   = pos_usd * pnl_pct / 100 - fee
        new_status = "closed" if pnl_pct > 0 else "stopped"
        supabase.table("signal_history").update({
            "status":      new_status,
            "exit_price":  round(exit_price, 4),
            "pnl_pct":     round(pnl_pct, 2),
            "pnl_usd":     round(pnl_usd, 2),
            "exit_reason": reason,
            "closed_at":   now_iso,
            "sell_score":  snap.get("sell_score", 0),
            "signal_detail": reason,
        }).eq("id", row_id).execute()
    else:
        # No open trade found — insert a standalone CLOSE record
        supabase.table("signal_history").insert({
            "symbol":      symbol,
            "signal_type": "CLOSE",
            "status":      "closed",
            "price":       exit_price,
            "exit_price":  exit_price,
            "rsi":         snap.get("rsi_14"),
            "sell_score":  snap.get("sell_score", 0),
            "signal_strength": 1,
            "signal_detail": reason,
            "exit_reason": reason,
            "closed_at":   now_iso,
        }).execute()


def symbols_tracker_job(supabase=None):
    for symbol in RSI_SYMBOLS:
        try:
            result = run_symbol_tracker_once(symbol, send_notify=True)
            logging.info(f"[JOB] {symbol}: {result.get('action')} -- {result.get('reason')}")

            if supabase:
                action = result.get("action")
                try:
                    if action == "BUY":
                        _db_record_buy(supabase, symbol, result)
                    elif action == "CLOSE":
                        _db_record_close(supabase, symbol, result)
                except Exception as e:
                    logging.warning(f"[JOB] DB {action} {symbol}: {e}")
        except Exception as e:
            logging.error(f"[JOB] {symbol}: {e}")

# ── /check Telegram command handler ──────────────────────────────────────────

def _rsi_label(rsi: float) -> str:
    if rsi < 30:   return "Quá bán 🟢"
    if rsi < 45:   return "Thấp"
    if rsi < 55:   return "Trung tính"
    if rsi < 70:   return "Cao"
    return "Quá mua 🔴"

def _adx_label(adx: float) -> str:
    if adx < 20:   return "Sideway"
    if adx < 25:   return "Xu hướng yếu"
    if adx < 40:   return "Xu hướng vừa"
    return "Xu hướng mạnh"

def _trend_str(uptrend: bool) -> str:
    return "✅ Tăng" if uptrend else "⚠️ Giảm"


def _handle_check_command(chat_id: str, symbol: str):
    """Process /check <symbol>: multi-timeframe analysis + 4-AI panel vote, reply to chat_id."""
    url_send = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    try:
        # ── Parallel data fetching ────────────────────────────────────────────
        tracker_res: Dict[str, Any] = {}
        sr_d1_res:   Dict[str, Any] = {}
        sr_4h_res:   Dict[str, Any] = {}
        h1_res:      Dict[str, Any] = {}
        zones_res:   Dict[str, Any] = {}

        def _tracker():  tracker_res["v"] = run_symbol_tracker_once(symbol, send_notify=False)
        def _sr_d1():    sr_d1_res["v"]   = ind.find_support_resistance(symbol, "1d", limit=120)
        def _sr_4h():    sr_4h_res["v"]   = ind.find_support_resistance(symbol, "4h", limit=100, pivot_strength=2)
        def _h1():       h1_res["v"]      = get_1h_trend(symbol)
        def _zones():
            try:
                sl, sh, bl, bh, _, _ = ind.compute_zones(symbol, "4h", lookback=60)
                zones_res["v"] = {"sell_low": sl, "sell_high": sh, "buy_low": bl, "buy_high": bh}
            except Exception:
                zones_res["v"] = {}

        threads = [
            threading.Thread(target=_tracker),
            threading.Thread(target=_sr_d1),
            threading.Thread(target=_sr_4h),
            threading.Thread(target=_h1),
            threading.Thread(target=_zones),
        ]
        for t in threads: t.start()
        threads[0].join(timeout=30)
        for t in threads[1:]: t.join(timeout=15)

        tracker = tracker_res.get("v", {})
        sr_d1   = sr_d1_res.get("v", {"supports": [], "resistances": []})
        sr_4h   = sr_4h_res.get("v", {"supports": [], "resistances": []})
        h1_ctx  = h1_res.get("v", {})
        zones   = zones_res.get("v", {})

        snap   = tracker.get("snapshot", {})
        dctx   = tracker.get("daily_context", {})
        sim    = tracker.get("simulated_trade", {})
        action = tracker.get("action", "HOLD")

        price      = snap.get("price", 0)
        rsi        = snap.get("rsi_14", 50)
        stoch      = snap.get("stoch_k", 50)
        adx        = snap.get("adx_14", 0)
        macd_h     = snap.get("macd_hist", 0)
        rising     = snap.get("macd_rising", False)
        atr        = snap.get("atr_14", 0)
        ema34      = snap.get("ema34") or 0
        ema50      = snap.get("ema50") or 0
        ema200     = snap.get("ema200") or 0
        bars_below = snap.get("bars_below_ema200", 0)
        buy_score  = snap.get("buy_score", 0)
        sell_score = snap.get("sell_score", 0)
        in_buy     = snap.get("in_buy_zone", False)
        in_sell    = snap.get("in_sell_zone", False)
        uptrend_d1 = dctx.get("uptrend", False)

        # ── Signal header ─────────────────────────────────────────────────────
        if action == "BUY":
            sig_emoji = "🟢"; sig_label = f"MUA — {tracker.get('reason', '')}"
        elif action == "HOLD_POS":
            sig_emoji = "🔄"; sig_label = "Đang giữ lệnh"
        elif action == "CLOSE":
            sig_emoji = "🔴"; sig_label = f"Đóng lệnh — {tracker.get('reason', '')}"
        else:
            sig_emoji = "⚪"; sig_label = "Chờ tín hiệu"

        mode_tag = "Optimized" if BOT_MODE == "optimized" else "Default"
        atr_pct  = (atr / price * 100) if price else 0

        msg = (
            f"📊 <b>{symbol}</b> /check [{mode_tag}]\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{sig_emoji} <b>{sig_label}</b>\n"
            f"Giá: <b>${price:,.2f}</b> | ATR: ${atr:,.2f} (±{atr_pct:.1f}%)\n"
        )

        # ── Multi-timeframe trend ─────────────────────────────────────────────
        h1_up   = h1_ctx.get("uptrend")
        h1_rsi  = h1_ctx.get("rsi", 50)
        h1_macd = h1_ctx.get("macd_rising", False)
        h4_up   = (rising and rsi > 50)  # proxy from 4H snap
        d1_up   = uptrend_d1

        # Align count: how many of 3 timeframes are bullish
        bull_count = sum([bool(h1_up), bool(h4_up), bool(d1_up)])
        if bull_count >= 3:
            tf_summary = "Tất cả khung đều tăng → Xu hướng tăng mạnh"
        elif bull_count == 2:
            tf_summary = "2/3 khung tăng → Xu hướng tăng vừa"
        elif bull_count == 1:
            tf_summary = "1/3 khung tăng → Xu hướng không rõ"
        else:
            tf_summary = "Tất cả khung đều giảm → Xu hướng giảm mạnh"

        h1_str = _trend_str(h1_up) if h1_up is not None else "Không rõ"
        msg += (
            f"━━━━━━━━━━━━━━━\n"
            f"📈 <b>XU HƯỚNG ĐA KHUNG</b>\n"
            f"H1:  {h1_str} (RSI {h1_rsi:.0f}, MACD {'↑' if h1_macd else '↓'})\n"
            f"H4:  {_trend_str(h4_up)} (RSI {rsi:.0f}, MACD {'↑' if rising else '↓'})\n"
            f"D1:  {_trend_str(d1_up)} (xu hướng chính)\n"
            f"→ {tf_summary}\n"
        )

        # ── Price zones ───────────────────────────────────────────────────────
        res_d1 = sr_d1.get("resistances", [])
        sup_d1 = sr_d1.get("supports", [])
        res_4h = sr_4h.get("resistances", [])
        sup_4h = sr_4h.get("supports", [])

        msg += "━━━━━━━━━━━━━━━\n📌 <b>VÙNG GIÁ QUAN TRỌNG</b>\n"

        # Dynamic buy/sell zones
        bz_lo = zones.get("buy_low"); bz_hi = zones.get("buy_high")
        sz_lo = zones.get("sell_low"); sz_hi = zones.get("sell_high")
        if bz_lo and bz_hi:
            if in_buy:
                zone_note = " ← <b>Giá đang trong vùng mua! 🎯</b>"
            elif price < bz_lo:
                zone_note = " ← Giá đang dưới vùng mua"
            else:
                zone_note = ""
            msg += f"🟢 <b>Vùng mua (Buy Zone):</b> ${bz_lo:,.0f} – ${bz_hi:,.0f}{zone_note}\n"
        if sz_lo and sz_hi:
            if in_sell:
                zone_note = " ← <b>Giá đang trong vùng bán! ⚠️</b>"
            else:
                zone_note = ""
            msg += f"🔴 <b>Vùng bán (Sell Zone):</b> ${sz_lo:,.0f} – ${sz_hi:,.0f}{zone_note}\n"

        # S/R levels
        if res_d1 or sup_d1 or res_4h or sup_4h:
            if res_d1:
                msg += f"🔴 Kháng cự 1D: {' | '.join(f'${v:,.2f}' for v in res_d1)}\n"
            if sup_d1:
                msg += f"🟢 Hỗ trợ 1D:   {' | '.join(f'${v:,.2f}' for v in sup_d1)}\n"
            if res_4h:
                msg += f"🟠 Kháng cự 4H: {' | '.join(f'${v:,.2f}' for v in res_4h)}\n"
            if sup_4h:
                msg += f"🔵 Hỗ trợ 4H:   {' | '.join(f'${v:,.2f}' for v in sup_4h)}\n"

        # ── Technical indicators ──────────────────────────────────────────────
        stoch_label = "⚠️ Quá mua" if stoch > 80 else ("🟢 Quá bán" if stoch < 20 else "Bình thường")
        msg += (
            f"━━━━━━━━━━━━━━━\n"
            f"📊 <b>CHỈ SỐ KỸ THUẬT</b>\n"
            f"RSI: {rsi:.1f} ({_rsi_label(rsi)}) | Stoch: {stoch:.1f} ({stoch_label})\n"
            f"MACD: {'↑ Tăng' if rising else '↓ Giảm'} | ADX: {adx:.1f} ({_adx_label(adx)})\n"
            f"Buy: {buy_score}/13 | Sell: {sell_score}/13\n"
            f"EMA34 ${ema34:,.2f} | EMA50 ${ema50:,.2f}"
            + (f" | EMA200 ${ema200:,.2f}" if ema200 else "") + "\n"
        )

        if bars_below >= 15:
            msg += f"⚡ <b>Breakout Watch:</b> {bars_below} nến dưới EMA200\n"
        elif bars_below > 0:
            msg += f"Dưới EMA200: {bars_below} nến\n"

        # ── Open position / signal ─────────────────────────────────────────────
        sim_status = sim.get("status", "WATCHING")
        strategy   = sim.get("strategy", "") or tracker.get("reason", "")
        strat_label = _STRAT_LABELS.get(strategy, strategy)

        if sim_status == "IN_TRADE":
            entry_p = sim.get("entry_price", price)
            stop_p  = sim.get("stop_price", 0)
            pnl_pct = sim.get("pnl_pct", 0)
            pos_usd = sim.get("pos_usd", 0)
            trail   = sim.get("trail_label", "")
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
            msg += (
                f"━━━━━━━━━━━━━━━\n"
                f"🔄 <b>Lệnh đang mở</b> ({strat_label})\n"
                f"Vào: ${entry_p:,.2f} → Hiện: ${price:,.2f}\n"
                f"Cắt lỗ (SL): ${stop_p:,.2f} | {trail}\n"
                f"{pnl_emoji} Lãi/lỗ: <b>{pnl_pct:+.2f}%</b> | Vị thế: ${pos_usd:,.0f}\n"
            )
        elif sim_status == "SIGNAL":
            stop_p  = sim.get("stop_price", 0)
            tp_p    = sim.get("tp_estimate", 0)
            pos_usd = sim.get("pos_usd", 0)
            sl_pct  = sim.get("sl_pct", 0)
            rr      = abs((tp_p - price) / (price - stop_p)) if stop_p and tp_p and price != stop_p else 0
            msg += (
                f"━━━━━━━━━━━━━━━\n"
                f"🚀 <b>Tín hiệu vào lệnh</b> ({strat_label})\n"
                f"Vào: ${price:,.2f}\n"
                f"Cắt lỗ (SL): ${stop_p:,.2f} (-{sl_pct:.1f}%)\n"
                f"Chốt lời (TP): ${tp_p:,.2f}"
                + (f" | R/R ≈ 1:{rr:.1f}" if rr > 0 else "") + "\n"
                f"Vốn đề xuất: ${pos_usd:,.0f}\n"
            )

        # ── 4-AI panel vote ───────────────────────────────────────────────────
        try:
            from services.bot_ai import run_ai_panel_vote
            ai_snap = {
                "price": price, "rsi_14": rsi, "adx_14": adx, "atr_14": atr,
                "macd_hist": macd_h, "macd_rising": rising,
                "stoch_k": stoch, "uptrend": uptrend_d1,
                "h1_uptrend": h1_ctx.get("uptrend"),
                "in_buy_zone": in_buy, "in_sell_zone": in_sell,
                "buy_score": buy_score, "sell_score": sell_score,
                "entry_strategy": sim.get("strategy") or tracker.get("reason", ""),
                "ema34": ema34, "ema50": ema50, "bars_below_ema200": bars_below,
            }
            extra_sr = ""
            if res_d1:
                extra_sr += f"• Kháng cự gần nhất: ${res_d1[0]:,.0f}\n"
            if sup_d1:
                extra_sr += f"• Hỗ trợ gần nhất: ${sup_d1[0]:,.0f}\n"

            votes = run_ai_panel_vote(symbol, "4h", ai_snap, extra_ctx=extra_sr)
        except Exception:
            votes = []

        if votes:
            yes_count = sum(1 for v in votes if v.get("vote") == "CÓ")
            total     = len(votes)
            vote_icons = ["🔵", "🟣", "🟠", "🔴"]
            msg += "━━━━━━━━━━━━━━━\n🤖 <b>HỘI ĐỒNG AI BỎ PHIẾU</b>\n\n"
            for i, v in enumerate(votes):
                icon    = vote_icons[i] if i < len(vote_icons) else "⚫"
                label   = v.get("label", f"AI {i+1}")
                vote    = v.get("vote", "KHÔNG")
                reason  = v.get("reason", "")
                v_emoji = "✅" if vote == "CÓ" else "❌"
                msg += f"{icon} <b>{label}:</b> {v_emoji} {vote}\n"
                if reason:
                    msg += f"  └ {reason}\n"
                msg += "\n"

            if yes_count >= 3:
                verdict = f"✅ NÊN VÀO LỆNH ({yes_count}/{total} đồng ý)"
            elif yes_count == 2:
                verdict = f"⚠️ CÒN PHÂN VÂN ({yes_count}/{total} đồng ý) — Thận trọng"
            else:
                verdict = f"❌ CHƯA NÊN VÀO LỆNH ({yes_count}/{total} đồng ý)"
            msg += f"📊 <b>Kết quả: {verdict}</b>\n"

        requests.post(url_send, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=15)

    except Exception as e:
        logging.error(f"[CHECK CMD] {symbol}: {e}")
        try:
            requests.post(url_send, json={
                "chat_id": chat_id,
                "text": f"❌ Lỗi khi kiểm tra {symbol}: {e}",
            }, timeout=10)
        except Exception:
            pass


def poll_telegram_commands():
    """Poll getUpdates for /check <symbol> commands and reply. Called every 30s by scheduler."""
    global _cmd_update_offset
    if not TELEGRAM_BOT_TOKEN:
        return

    url_updates = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        params: Dict[str, Any] = {"limit": 50, "timeout": 0, "allowed_updates": ["message"]}
        if _cmd_update_offset:
            params["offset"] = _cmd_update_offset
        resp  = requests.get(url_updates, params=params, timeout=10)
        data  = resp.json()
        if not data.get("ok"):
            return
        for upd in data.get("result", []):
            update_id = upd.get("update_id", 0)
            msg = upd.get("message") or {}
            text    = (msg.get("text") or "").strip()
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            if chat_id and text.lower().startswith("/check"):
                parts  = text.split()
                symbol = parts[1].upper() if len(parts) >= 2 else ""
                if symbol:
                    logging.info(f"[CMD] /check {symbol} from {chat_id}")
                    _handle_check_command(chat_id, symbol)
            if update_id + 1 > _cmd_update_offset:
                _cmd_update_offset = update_id + 1
    except Exception as e:
        logging.warning(f"[TELEGRAM CMD] poll error: {e}")


# ── Legacy compat (used by old router) ───────────────────────────────────────
def compute_d1_bias(symbol: str):
    dctx = get_daily_context(symbol)
    return (dctx.get("uptrend", False) and dctx.get("bull_ema", False),
            not dctx.get("uptrend", True) and dctx.get("bear_ema", False))

def compute_candle_signals(*args, **kwargs):
    return []
