"""
bot_indicators.py — Technical indicator calculations for the crypto bot.
Pure math functions: no side effects, no network calls (except _rsi_fetch_klines).
"""

import math
import time
import threading
import logging
from typing import Dict, List, Optional

import requests

# ── Klines cache (5 min TTL) ────────────────────────────────────────────────
_klines_cache: Dict[str, tuple] = {}
_klines_cache_lock = threading.Lock()
KLINES_CACHE_TTL = 300  # seconds


def fetch_klines(symbol: str, interval: str, limit: int = 200):
    """Fetch klines from Binance with a 5-minute in-memory cache."""
    cache_key = f"{symbol}_{interval}"
    now = time.time()
    with _klines_cache_lock:
        entry = _klines_cache.get(cache_key)
        if entry and now - entry[0] < KLINES_CACHE_TTL:
            data = entry[1]
            return data[-limit:] if len(data) >= limit else data

    url = "https://api.binance.com/api/v3/klines"
    fetch_limit = max(limit, 250)
    params = {"symbol": symbol, "interval": interval, "limit": fetch_limit}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    with _klines_cache_lock:
        _klines_cache[cache_key] = (time.time(), data)

    return data[-limit:] if len(data) >= limit else data


# ── RSI ──────────────────────────────────────────────────────────────────────

def rsi_wilder(closes: List[float], period: int = 14) -> float:
    """Compute latest RSI using Wilder's smoothing."""
    if len(closes) < period + 1:
        raise ValueError("Not enough data to compute RSI")
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    return float(100 - (100 / (1 + avg_gain / avg_loss)))


def rsi_series(closes: List[float], period: int) -> List[float]:
    """Compute RSI series. Early values default to 50."""
    if len(closes) < period + 2:
        return [50.0] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out = [50.0] * len(closes)
    out[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        idx = i + 1
        out[idx] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return out


def rsi_latest(symbol: str, interval: str, period: int):
    """Return (price, rsi) for the latest closed candle."""
    kl = fetch_klines(symbol, interval, limit=max(200, period * 5))
    closes = [float(k[4]) for k in kl]
    rsi = rsi_wilder(closes, period=period)
    return closes[-1], rsi


def dynamic_rsi_thresholds(rsi_series_: List[float], lookback: int = 100):
    """Return (oversold_threshold, overbought_threshold) from recent RSI distribution."""
    recent = [r for r in rsi_series_[-lookback:] if r is not None and r > 0]
    if len(recent) < 20:
        return 40.0, 60.0
    s = sorted(recent)

    def pct(data, p):
        idx = (len(data) - 1) * p / 100.0
        lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
        return data[lo] + (data[hi] - data[lo]) * (idx - lo)

    oversold = max(25.0, min(50.0, pct(s, 20)))
    overbought = max(50.0, min(78.0, pct(s, 80)))
    if overbought - oversold < 10.0:
        mid = (oversold + overbought) / 2
        oversold, overbought = mid - 5.0, mid + 5.0
    return round(oversold, 1), round(overbought, 1)


# ── EMA / SMA ────────────────────────────────────────────────────────────────

def ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """EMA series; early elements are None."""
    if len(values) < period:
        raise ValueError(f"Not enough data for EMA({period})")
    out: List[Optional[float]] = [None] * len(values)
    sma = sum(values[:period]) / period
    out[period - 1] = sma
    k = 2 / (period + 1)
    prev = sma
    for i in range(period, len(values)):
        curr = (values[i] - prev) * k + prev
        out[i] = curr
        prev = curr
    return out


def sma_series(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    if n < period:
        return [None] * n
    out: List[Optional[float]] = [None] * (period - 1)
    window_sum = sum(values[:period])
    out.append(window_sum / period)
    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        out.append(window_sum / period)
    return out


# ── MACD ─────────────────────────────────────────────────────────────────────

def macd_series(closes, fast=12, slow=26, signal=9):
    """Return (macd_line[], signal_line[], hist[])."""
    if len(closes) < slow + signal + 5:
        n = len(closes)
        return [0.0] * n, [0.0] * n, [0.0] * n

    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    macd = [((ef[i] or 0.0) - (es[i] or 0.0)) for i in range(len(closes))]
    sig = ema_series(macd, signal)
    hist = [(macd[i] - (sig[i] or 0.0)) for i in range(len(closes))]
    return macd, sig, hist


def macd_latest_with_prev(symbol: str, interval: str, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, hist, prev_hist)."""
    kl = fetch_klines(symbol, interval, limit=max(200, slow * 5))
    closes = [float(k[4]) for k in kl]
    if len(closes) < slow + signal + 5:
        raise ValueError("Not enough data to compute MACD")
    ef = ema_series(closes, fast)
    es = ema_series(closes, slow)
    macd = [((ef[i] or 0.0) - (es[i] or 0.0)) for i in range(len(closes))]
    sig = ema_series(macd, signal)
    if sig[-1] is None or sig[-2] is None:
        raise ValueError("Signal line not ready")
    hist = macd[-1] - sig[-1]
    prev_hist = macd[-2] - sig[-2]
    return macd[-1], sig[-1], hist, prev_hist


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def bollinger_bands(values: List[float], period: int = 20, k: float = 2.0):
    """Return (middle[], upper[], lower[])."""
    n = len(values)
    middle = sma_series(values, period)
    upper: List[Optional[float]] = [None] * n
    lower: List[Optional[float]] = [None] * n
    if n < period:
        return middle, upper, lower
    for i in range(period - 1, n):
        m = middle[i]
        if m is None:
            continue
        window = values[i - period + 1: i + 1]
        variance = sum((v - m) ** 2 for v in window) / period
        std = math.sqrt(variance)
        upper[i] = m + k * std
        lower[i] = m - k * std
    return middle, upper, lower


# ── Stochastic / Williams %R ──────────────────────────────────────────────────

def stochastic_k(highs, lows, closes, period: int = 14) -> List[Optional[float]]:
    n = len(closes)
    if n < period:
        return [None] * n
    out: List[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        wh = max(highs[i - period + 1: i + 1])
        wl = min(lows[i - period + 1: i + 1])
        out[i] = 50.0 if wh == wl else (closes[i] - wl) / (wh - wl) * 100.0
    return out


def williams_r(highs, lows, closes, period: int = 14) -> List[Optional[float]]:
    n = len(closes)
    if n < period:
        return [None] * n
    out: List[Optional[float]] = [None] * n
    for i in range(period - 1, n):
        wh = max(highs[i - period + 1: i + 1])
        wl = min(lows[i - period + 1: i + 1])
        out[i] = -50.0 if wh == wl else -100.0 * (wh - closes[i]) / (wh - wl)
    return out


# ── ATR / ADX ─────────────────────────────────────────────────────────────────

def atr_series(highs, lows, closes, period: int = 14) -> List[Optional[float]]:
    n = len(closes)
    if n < 2:
        return [None] * n
    tr = [None]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    seed = sum(tr[1:period + 1]) / period
    out[period] = seed
    prev = seed
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def compute_adx(highs, lows, closes, period: int = 14) -> dict:
    n = len(closes)
    if n < period * 2 + 5:
        return {"adx": 20.0, "di_plus": 20.0, "di_minus": 20.0, "trending": False, "strong": False}
    tr_l, dmp_l, dmm_l = [0.0], [0.0], [0.0]
    for i in range(1, n):
        tr_l.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        dmp_l.append(up if up > dn and up > 0 else 0.0)
        dmm_l.append(dn if dn > up and dn > 0 else 0.0)

    def _wilder(s, p):
        r = [sum(s[:p])]
        for v in s[p:]:
            r.append(r[-1] - r[-1] / p + v)
        return r

    atr_s = _wilder(tr_l, period)
    dmp_s = _wilder(dmp_l, period)
    dmm_s = _wilder(dmm_l, period)
    di_p = [100 * d / a if a > 0 else 0 for d, a in zip(dmp_s, atr_s)]
    di_m = [100 * d / a if a > 0 else 0 for d, a in zip(dmm_s, atr_s)]
    dx_s = [100 * abs(p - m) / (p + m) if (p + m) > 0 else 0 for p, m in zip(di_p, di_m)]
    if len(dx_s) < period:
        return {"adx": 20.0, "di_plus": 20.0, "di_minus": 20.0, "trending": False, "strong": False}
    adx_s = _wilder(dx_s, period)
    adx = adx_s[-1]
    return {
        "adx": round(adx, 2),
        "di_plus": round(di_p[-1], 2),
        "di_minus": round(di_m[-1], 2),
        "trending": adx > 22.0,
        "strong": adx > 30.0,
    }


# ── OBV ───────────────────────────────────────────────────────────────────────

def compute_obv_signals(closes, volumes, lookback: int = 8) -> dict:
    n = len(closes)
    if n < 2 or not volumes:
        return {"buy_vol_score": 0, "sell_vol_score": 0, "obv_trend": "flat", "vol_spike": False}
    obv = [0.0]
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    w = min(lookback, n)
    half = max(1, w // 2)
    obv_start = sum(obv[-w:-half]) / half if half < w else obv[-w]
    obv_end = sum(obv[-half:]) / half
    change = (obv_end - obv_start) / (abs(obv_start) + 1e-9)
    obv_trend = "up" if change > 0.005 else ("down" if change < -0.005 else "flat")
    vw = min(20, n)
    avg_vol = sum(volumes[-vw:]) / vw
    curr_vol = volumes[-1]
    vol_spike = curr_vol > avg_vol * 1.5
    candle_up = closes[-1] > closes[-2]
    candle_dn = closes[-1] < closes[-2]
    price_change = abs(closes[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
    obv_bull_div = closes[-1] < closes[max(0, n - 10)] and obv[-1] > obv[max(0, n - 10)]
    obv_bear_div = closes[-1] > closes[max(0, n - 10)] and obv[-1] < obv[max(0, n - 10)]
    buy_score = 0
    sell_score = 0
    if obv_trend == "up": buy_score += 1
    if obv_bull_div: buy_score += 2
    if vol_spike and candle_up and price_change > 0.003: buy_score += 1
    if obv_trend == "down": sell_score += 1
    if obv_bear_div: sell_score += 2
    if vol_spike and candle_dn and price_change > 0.003: sell_score += 1
    return {
        "buy_vol_score": min(buy_score, 3),
        "sell_vol_score": min(sell_score, 3),
        "obv_trend": obv_trend,
        "vol_spike": vol_spike,
    }


# ── Support / Resistance ──────────────────────────────────────────────────────

def find_support_resistance(
    symbol: str,
    interval: str = "1d",
    limit: int = 120,
    pivot_strength: int = 3,
    cluster_pct: float = 0.008,
    max_levels: int = 3,
) -> dict:
    """
    Find key S/R levels from pivot highs/lows.
    Returns {"supports": [...], "resistances": [...]} sorted by proximity to current price.
    pivot_strength: number of candles on each side that must be lower/higher.
    cluster_pct: merge levels within this % of each other (default 0.8%).
    """
    try:
        kl = fetch_klines(symbol, interval, limit=limit)
    except Exception:
        return {"supports": [], "resistances": []}

    if len(kl) < pivot_strength * 2 + 5:
        return {"supports": [], "resistances": []}

    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    closes = [float(k[4]) for k in kl]
    price = closes[-1]
    n = len(kl)

    pivot_highs: List[float] = []
    pivot_lows: List[float] = []
    for i in range(pivot_strength, n - pivot_strength):
        if all(highs[i] >= highs[i - j] for j in range(1, pivot_strength + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, pivot_strength + 1)):
            pivot_highs.append(highs[i])
        if all(lows[i] <= lows[i - j] for j in range(1, pivot_strength + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, pivot_strength + 1)):
            pivot_lows.append(lows[i])

    def _cluster(levels: List[float]) -> List[float]:
        if not levels:
            return []
        grouped: List[List[float]] = [[sorted(levels)[0]]]
        for v in sorted(levels)[1:]:
            if abs(v - grouped[-1][-1]) / grouped[-1][-1] < cluster_pct:
                grouped[-1].append(v)
            else:
                grouped.append([v])
        return [sum(g) / len(g) for g in grouped]

    resistances = sorted([v for v in _cluster(pivot_highs) if v > price])
    supports = sorted([v for v in _cluster(pivot_lows) if v < price], reverse=True)

    return {
        "supports": [round(v, 2) for v in supports[:max_levels]],
        "resistances": [round(v, 2) for v in resistances[:max_levels]],
    }


# ── Market sentiment ─────────────────────────────────────────────────────────

def fetch_fear_greed() -> dict:
    try:
        resp = requests.get(
            "https://api.alternative.me/fng/",
            params={"limit": 1, "format": "json"},
            timeout=8,
        )
        resp.raise_for_status()
        entry = resp.json()["data"][0]
        value = int(entry["value"])
        return {
            "value": value,
            "buy_adj": 2 if value <= 20 else (1 if value <= 35 else 0),
            "sell_adj": 2 if value >= 80 else (1 if value >= 65 else 0),
        }
    except Exception:
        return {"value": 50, "buy_adj": 0, "sell_adj": 0}


def fetch_funding_rate(symbol: str) -> dict:
    try:
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=8,
        )
        resp.raise_for_status()
        fr = float(resp.json().get("lastFundingRate", 0))
        return {
            "funding_rate": fr,
            "funding_rate_pct": fr * 100,
            "buy_adj": 1 if fr < -0.0002 else (-2 if fr > 0.0005 else 0),
            "sell_adj": 2 if fr > 0.0005 else (0 if fr > 0 else -1),
        }
    except Exception:
        return {"funding_rate": 0.0, "funding_rate_pct": 0.0, "buy_adj": 0, "sell_adj": 0}


# ── Zone calculation ──────────────────────────────────────────────────────────

def compute_zones(symbol: str, interval: str, lookback: int = 60):
    """
    Dynamic buy/sell zones from high/low of last N candles.
    Returns (sell_low, sell_high, buy_low, buy_high, recent_low, recent_high).
    """
    kl = fetch_klines(symbol, interval, limit=lookback)
    if len(kl) < lookback:
        raise ValueError("Not enough klines for dynamic zone calc")
    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    recent_high = max(highs)
    recent_low = min(lows)
    price_range = recent_high - recent_low
    if price_range <= 0:
        raise ValueError("Invalid price range")
    zone_pct = 0.2
    buy_low = recent_low
    buy_high = recent_low + zone_pct * price_range
    sell_high = recent_high
    sell_low = recent_high - zone_pct * price_range
    return sell_low, sell_high, buy_low, buy_high, recent_low, recent_high
