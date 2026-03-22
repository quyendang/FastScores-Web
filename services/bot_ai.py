"""
bot_ai.py — OpenRouter AI market analysis for the crypto bot.
"""

import os
import time
import logging
from typing import Dict

import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
OPENROUTER_MODEL2 = os.getenv("OPENROUTER_MODEL2", "")

_ai_analysis_cache: Dict[str, tuple] = {}
_ai_analysis_cache2: Dict[str, tuple] = {}
AI_ANALYSIS_CACHE_TTL = 600  # 10 minutes


def call_openrouter_analysis(symbol: str, tf: str, snap: dict) -> str:
    """
    Full market analysis for the dashboard.
    Returns Vietnamese markdown string, or "" if API key is not set.
    Cached for 10 minutes per (symbol, tf).
    """
    if not OPENROUTER_API_KEY:
        return ""

    cache_key = f"{symbol}_{tf}"
    now = time.time()
    entry = _ai_analysis_cache.get(cache_key)
    if entry and now - entry[0] < AI_ANALYSIS_CACHE_TTL:
        return entry[1]

    def _fmt(v, decimals=2):
        return f"{v:.{decimals}f}" if v is not None else "N/A"

    zone_label = {"buy": "Vùng MUA", "sell": "Vùng BÁN", "neutral": "Vùng trung lập"}.get(
        snap.get("zone", "neutral"), "Trung lập"
    )

    prompt = f"""Bạn là chuyên gia phân tích kỹ thuật crypto. Dữ liệu {symbol} ({tf}):

Giá: {_fmt(snap.get('price'), 4)} USDT ({_fmt(snap.get('change_24h'), 2)}% 24h) | Vùng: **{zone_label}**
RSI: {_fmt(snap.get('rsi'))} | MACD Hist: {_fmt(snap.get('macd_hist'), 6)} ({'⬆' if snap.get('macd_hist_rising') else '⬇'}) | EMA: {'📈 bull' if snap.get('ema_bullish') else '📉 bear' if snap.get('ema_bearish') else '➡ neutral'}
Stoch %K: {_fmt(snap.get('stoch_k'))} | W%R: {_fmt(snap.get('wr'))} | BB: {_fmt(snap.get('bb_upper'), 4)}/{_fmt(snap.get('bb_lower'), 4)}
D1: {'Bull✅' if snap.get('d1_bullish') else 'Bear✅' if snap.get('d1_bearish') else 'Neutral'} | BTC RSI: {_fmt(snap.get('btc_rsi'))} | BTC MACD: {_fmt(snap.get('btc_macd_hist'), 6)}
Vùng MUA: {_fmt(snap.get('buy_low'), 2)}–{_fmt(snap.get('buy_high'), 2)} | Vùng BÁN: {_fmt(snap.get('sell_low'), 2)}–{_fmt(snap.get('sell_high'), 2)}
Bot: **{snap.get('tracker_action', 'N/A')}** (Buy {snap.get('buy_score', 0)}/13 · Sell {snap.get('sell_score', 0)}/13)

Phân tích bằng tiếng Việt, súc tích, theo đúng 4 mục:

### 1. 📊 Xu hướng & Chỉ báo
Tóm tắt xu hướng (EMA, D1 bias, BTC context) và nhận xét các chỉ báo chính (RSI, MACD, Stoch, BB).

### 2. 💡 Khuyến nghị
**BUY / HOLD / SELL** — nêu Entry, TP, SL cụ thể. Lý do ngắn gọn.

### 3. 🔄 Điều kiện đảo chiều
Nêu cụ thể: giá/chỉ báo phải đạt ngưỡng nào thì tín hiệu đảo chiều (cả 2 chiều nếu có).

### 4. ⚠️ Rủi ro chính
1–2 rủi ro quan trọng nhất có thể vô hiệu hoá phân tích trên.

Không nhắc lại số liệu thô. Tối đa 250 từ."""

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Crypto Dashboard",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 900,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        _ai_analysis_cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logging.error(f"[OPENROUTER] Error calling {OPENROUTER_MODEL}: {e}")
        return ""


def ai_brief_for_telegram_model2(
    symbol: str,
    action: str,
    price: float,
    rsi: float,
    macd_hist: float,
    d1_bullish: bool,
    d1_bearish: bool,
    btc_rsi: float,
    atr_pct: float,
    interval: str,
) -> str:
    """
    2-3 sentence second AI opinion for Telegram using OPENROUTER_MODEL2.
    Returns plain text or "" if MODEL2 not configured.
    """
    if not OPENROUTER_API_KEY or not OPENROUTER_MODEL2:
        return ""

    d1_label = "Bullish" if d1_bullish else ("Bearish" if d1_bearish else "Neutral")
    d1_alignment = (
        "đồng thuận với tín hiệu" if (
            (action == "BUY" and d1_bullish) or (action == "SELL" and d1_bearish)
        ) else "trung lập" if not d1_bullish and not d1_bearish
        else "ngược chiều tín hiệu — rủi ro cao hơn"
    )
    prompt = (
        f"Crypto signal: {symbol} — {action} tại {price:,.2f} USDT (khung {interval}).\n"
        f"H4 RSI: {rsi:.1f} | MACD hist: {macd_hist:.4f} | D1 bias: {d1_label} ({d1_alignment}) | "
        f"BTC RSI: {btc_rsi:.1f} | ATR: {atr_pct:.2f}%\n\n"
        f"Viết đúng 2–3 câu bằng tiếng Việt: đánh giá độc lập về tín hiệu — "
        f"D1 bias ảnh hưởng thế nào đến độ tin cậy, và điều kiện cần thiết để vào lệnh. "
        f"Không dùng markdown, không bullet point, chỉ văn xuôi."
    )
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Crypto Bot",
            },
            json={
                "model": OPENROUTER_MODEL2,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.4,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"[AI_BRIEF2] Error: {e}")
        return ""


def call_openrouter_analysis_model2(symbol: str, tf: str, snap: dict) -> str:
    """
    Second AI opinion using OPENROUTER_MODEL2 — cross-check perspective.
    Returns Vietnamese markdown string, or "" if MODEL2 is not configured.
    Cached for 10 minutes per (symbol, tf).
    """
    if not OPENROUTER_API_KEY or not OPENROUTER_MODEL2:
        return ""

    cache_key = f"{symbol}_{tf}_m2"
    now = time.time()
    entry = _ai_analysis_cache2.get(cache_key)
    if entry and now - entry[0] < AI_ANALYSIS_CACHE_TTL:
        return entry[1]

    def _fmt(v, decimals=2):
        return f"{v:.{decimals}f}" if v is not None else "N/A"

    zone_label = {"buy": "Vùng MUA", "sell": "Vùng BÁN", "neutral": "Vùng trung lập"}.get(
        snap.get("zone", "neutral"), "Trung lập"
    )

    prompt = f"""Bạn là chuyên gia phân tích kỹ thuật crypto với quan điểm độc lập. Cho dữ liệu {symbol} ({tf}):

Giá: {_fmt(snap.get('price'), 4)} USDT ({_fmt(snap.get('change_24h'), 2)}% 24h) | Vùng: **{zone_label}**
RSI: {_fmt(snap.get('rsi'))} | MACD Hist: {_fmt(snap.get('macd_hist'), 6)} ({'⬆' if snap.get('macd_hist_rising') else '⬇'}) | EMA: {'📈 bull' if snap.get('ema_bullish') else '📉 bear' if snap.get('ema_bearish') else '➡ neutral'}
Stoch %K: {_fmt(snap.get('stoch_k'))} | W%R: {_fmt(snap.get('wr'))} | BB: {_fmt(snap.get('bb_upper'), 4)}/{_fmt(snap.get('bb_lower'), 4)}
D1: {'Bull✅' if snap.get('d1_bullish') else 'Bear✅' if snap.get('d1_bearish') else 'Neutral'} | BTC RSI: {_fmt(snap.get('btc_rsi'))} | BTC MACD: {_fmt(snap.get('btc_macd_hist'), 6)}
Vùng MUA: {_fmt(snap.get('buy_low'), 2)}–{_fmt(snap.get('buy_high'), 2)} | Vùng BÁN: {_fmt(snap.get('sell_low'), 2)}–{_fmt(snap.get('sell_high'), 2)}
Bot: **{snap.get('tracker_action', 'N/A')}** (Buy {snap.get('buy_score', 0)}/13 · Sell {snap.get('sell_score', 0)}/13)

Đưa ra **nhận định thứ hai độc lập** bằng tiếng Việt, theo 3 mục:

### 🔎 Xác nhận hay phản biện?
Tín hiệu bot có đáng tin không? Chỉ báo nào đồng thuận / mâu thuẫn? Mức độ hội tụ tổng thể.

### 📐 Momentum & Cấu trúc giá
Nhận xét momentum hiện tại (tăng tốc hay suy yếu?), cấu trúc giá (higher highs / lower lows), ngưỡng pivot gần nhất.

### 🎯 Mức giá then chốt
Nêu 1–2 mức giá quan trọng nhất cần theo dõi (hỗ trợ/kháng cự), và kịch bản khi giá chạm các mức đó.

Tối đa 200 từ. Không nhắc lại số liệu thô."""

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Crypto Dashboard",
            },
            json={
                "model": OPENROUTER_MODEL2,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 700,
                "temperature": 0.4,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        _ai_analysis_cache2[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logging.error(f"[OPENROUTER2] Error calling {OPENROUTER_MODEL2}: {e}")
        return ""


def ai_brief_for_telegram(
    symbol: str,
    action: str,
    price: float,
    rsi: float,
    macd_hist: float,
    d1_bullish: bool,
    d1_bearish: bool,
    btc_rsi: float,
    atr_pct: float,
    interval: str,
) -> str:
    """
    2-3 sentence AI brief for Telegram notifications.
    Returns plain text (no markdown), or "" if API key not set.
    """
    if not OPENROUTER_API_KEY:
        return ""

    d1_label = "Bullish" if d1_bullish else ("Bearish" if d1_bearish else "Neutral")
    prompt = (
        f"Crypto signal alert: {symbol} — {action} tại {price:,.2f} USDT (khung {interval}).\n"
        f"RSI: {rsi:.1f} | MACD hist: {macd_hist:.4f} | D1 bias: {d1_label} | "
        f"BTC RSI: {btc_rsi:.1f} | ATR: {atr_pct:.2f}%\n\n"
        f"Viết đúng 2–3 câu bằng tiếng Việt: nhận định ngắn gọn về tín hiệu này "
        f"(xu hướng, độ tin cậy, rủi ro chính). Không dùng markdown, không bullet point, "
        f"chỉ văn xuôi thuần."
    )
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Crypto Bot",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.4,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"[AI_BRIEF] Error: {e}")
        return ""
