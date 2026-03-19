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

_ai_analysis_cache: Dict[str, tuple] = {}
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

    prompt = f"""Bạn là chuyên gia phân tích kỹ thuật cryptocurrency chuyên nghiệp.
Dưới đây là dữ liệu thị trường thực tế của {symbol} trên khung {tf}. Hãy phân tích và đưa ra nhận định bằng **tiếng Việt**.

---
## Snapshot thị trường — {symbol} ({tf})

| Chỉ báo | Giá trị |
|---------|---------|
| Giá hiện tại | {_fmt(snap.get('price'), 4)} USDT |
| Thay đổi ~24h | {_fmt(snap.get('change_24h'), 2)}% |
| RSI (14) | {_fmt(snap.get('rsi'))} |
| MACD Histogram | {_fmt(snap.get('macd_hist'), 6)} ({'⬆ tăng' if snap.get('macd_hist_rising') else '⬇ giảm'}) |
| EMA 34 vs EMA 89 | {'📈 EMA34 > EMA89 (tăng)' if snap.get('ema_bullish') else '📉 EMA34 < EMA89 (giảm)' if snap.get('ema_bearish') else '➡ Đan xen'} |
| Stochastic %K | {_fmt(snap.get('stoch_k'))} |
| Williams %R | {_fmt(snap.get('wr'))} |
| BB Upper / Lower | {_fmt(snap.get('bb_upper'), 4)} / {_fmt(snap.get('bb_lower'), 4)} |
| Vị trí giá | **{zone_label}** |

## Xu hướng D1 (Daily bias)
- D1 Bullish: {'✅' if snap.get('d1_bullish') else '❌'}
- D1 Bearish: {'✅' if snap.get('d1_bearish') else '❌'}

## BTC Context ({tf})
- BTC RSI: {_fmt(snap.get('btc_rsi'))}
- BTC MACD Hist: {_fmt(snap.get('btc_macd_hist'), 6)}

## Vùng giao dịch động
- 🟢 Vùng MUA: {_fmt(snap.get('buy_low'), 2)} – {_fmt(snap.get('buy_high'), 2)}
- 🔴 Vùng BÁN: {_fmt(snap.get('sell_low'), 2)} – {_fmt(snap.get('sell_high'), 2)}

## Tín hiệu bot ({tf})
- Hành động: **{snap.get('tracker_action', 'N/A')}**
- Buy score: {snap.get('buy_score', 0)} / 13
- Sell score: {snap.get('sell_score', 0)} / 13

---
Viết phân tích thị trường theo đúng cấu trúc sau, bằng tiếng Việt, súc tích và chuyên nghiệp:

### 1. 📊 Xu hướng tổng quan
Mô tả xu hướng ngắn và trung hạn dựa trên EMA, D1 bias và vị trí giá trong vùng.

### 2. 🔍 Phân tích chỉ báo kỹ thuật
Nhận xét từng chỉ báo: RSI, MACD, Stochastic, Williams %R, Bollinger Bands — điểm mạnh/yếu.

### 3. 📍 Vùng giá quan trọng
Phân tích vùng mua/bán động, mức hỗ trợ/kháng cự cần theo dõi.

### 4. 💡 Khuyến nghị giao dịch
Đưa ra khuyến nghị rõ ràng: **BUY / HOLD / SELL**.
Kèm theo:
- **Giá nên mua**: nêu mức giá cụ thể hoặc vùng giá entry lý tưởng
- **Giá nên bán / chốt lời**: nêu mức Take Profit (TP) cụ thể
- **Cắt lỗ (Stop Loss)**: mức SL tham khảo
Giải thích điều kiện vào lệnh và lý do chọn các mức giá này.

### 5. ⚠️ Rủi ro cần lưu ý
Các yếu tố có thể làm vô hiệu phân tích trên.

Không nhắc lại bảng số liệu. Dùng emoji phù hợp. Tối đa 500 từ."""

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
                "max_tokens": 1500,
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
