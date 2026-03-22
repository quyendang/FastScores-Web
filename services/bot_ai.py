"""
bot_ai.py — OpenRouter AI market analysis for the crypto bot.
"""

import os
import time
import logging
from typing import Dict, List

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


def _parse_expert_panel(text: str, fallback_price: float) -> dict:
    """Parse structured expert panel response into a dict."""
    votes: List[dict] = []
    entry = fallback_price
    sl = tp = 0.0
    summary = ""

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("EXPERT:"):
            try:
                parts = {}
                for seg in line.split("|"):
                    if ":" in seg:
                        k, v = seg.split(":", 1)
                        parts[k.strip()] = v.strip()
                expert = parts.get("EXPERT", "?")
                vote = parts.get("VOTE", "REJECT").upper()
                reason = parts.get("REASON", "")
                votes.append({
                    "expert": expert,
                    "vote": vote,
                    "confirmed": vote == "CONFIRM",
                    "reason": reason,
                })
            except Exception:
                pass
        elif line.startswith("VERDICT:"):
            try:
                parts = {}
                for seg in line.split("|"):
                    if ":" in seg:
                        k, v = seg.split(":", 1)
                        parts[k.strip()] = v.strip()
                summary = parts.get("SUMMARY", "")
                entry = float(parts.get("ENTRY", fallback_price))
                try:
                    sl = float(parts.get("SL", "0").replace(",", ""))
                except (ValueError, TypeError):
                    sl = 0.0
                try:
                    tp = float(parts.get("TP", "0").replace(",", ""))
                except (ValueError, TypeError):
                    tp = 0.0
            except Exception:
                pass

    confirmed = sum(1 for v in votes if v["confirmed"])
    return {
        "go": confirmed >= 3,
        "confirmed": confirmed,
        "total": len(votes),
        "votes": votes,
        "summary": summary,
        "entry": entry,
        "sl": sl,
        "tp": tp,
    }


def expert_panel_verdict(
    symbol: str,
    action: str,
    price: float,
    rsi: float,
    macd_hist: float,
    macd_hist_rising: bool,
    d1_bullish: bool,
    d1_bearish: bool,
    btc_rsi: float,
    btc_macd_hist: float,
    atr_pct: float,
    interval: str,
    buy_low: float = 0.0,
    buy_high: float = 0.0,
    sell_low: float = 0.0,
    sell_high: float = 0.0,
    sr_supports: List[float] = None,
    sr_resistances: List[float] = None,
) -> dict:
    """
    Selective Breakout Sniper — hội đồng 4 chuyên gia bỏ phiếu.
    Trả về dict với go=True nếu >= 3/4 chuyên gia CONFIRM.
    Nếu không có API key, mặc định go=True (pass-through).
    """
    _no_gate = {"go": True, "bypass": True, "confirmed": 0, "total": 0, "votes": [], "summary": "", "entry": price, "sl": 0.0, "tp": 0.0}
    if not OPENROUTER_API_KEY:
        return _no_gate

    d1_label = "Bullish ✅" if d1_bullish else ("Bearish ✅" if d1_bearish else "Neutral ⚪")
    direction = "MUA (LONG)" if action == "BUY" else "BÁN (SHORT)"
    sup_str = ", ".join(f"{v:,.2f}" for v in (sr_supports or [])[:3]) or "N/A"
    res_str = ", ".join(f"{v:,.2f}" for v in (sr_resistances or [])[:3]) or "N/A"
    zone_str = f"BUY {buy_low:,.2f}–{buy_high:,.2f}" if action == "BUY" else f"SELL {sell_low:,.2f}–{sell_high:,.2f}"

    prompt = f"""Bạn là hội đồng 4 chuyên gia phân tích kỹ thuật crypto. Bot đang xét tín hiệu {direction} cho {symbol} tại {price:,.4f} USDT (khung {interval}).

DỮ LIỆU KỸ THUẬT:
- RSI: {rsi:.1f} | MACD hist: {macd_hist:.6f} ({'đang tăng ⬆' if macd_hist_rising else 'đang giảm ⬇'})
- D1 Bias: {d1_label} | BTC RSI (H4): {btc_rsi:.1f} | BTC MACD hist: {btc_macd_hist:.6f}
- ATR: {atr_pct:.2f}% | Zone: {zone_str}
- Hỗ trợ D1: {sup_str} | Kháng cự D1: {res_str}

Chiến lược: Selective Breakout Sniper — chỉ CONFIRM khi hội tụ đủ điều kiện, ưu tiên chắc chắn, lọc tín hiệu yếu.

Mỗi chuyên gia đánh giá độc lập theo chuyên môn riêng:
1. Chuyên gia Xu hướng: Phân tích xu hướng macro (D1 bias, EMA, BTC alignment)
2. Chuyên gia Đà giá: Xác nhận momentum (RSI vị trí, MACD hướng, tăng tốc/suy yếu)
3. Chuyên gia Vùng giá: Cấu trúc giá (giá có breakout rõ khỏi S/R chưa? Vào đúng zone không?)
4. Chuyên gia Rủi ro: Quản lý rủi ro (ATR có bình thường? R:R có đủ >= 2? Điều kiện thị trường an toàn?)

Trả lời ĐÚNG 5 dòng theo format mẫu dưới đây. VOTE chỉ được là CONFIRM hoặc REJECT. VERDICT chỉ được là GO hoặc NO. Không thêm bất kỳ chữ nào khác.

EXPERT:Chuyên gia Xu hướng|VOTE:CONFIRM|REASON:lý do ngắn gọn 1 câu tiếng Việt
EXPERT:Chuyên gia Đà giá|VOTE:REJECT|REASON:lý do ngắn gọn 1 câu tiếng Việt
EXPERT:Chuyên gia Vùng giá|VOTE:CONFIRM|REASON:lý do ngắn gọn 1 câu tiếng Việt
EXPERT:Chuyên gia Rủi ro|VOTE:CONFIRM|REASON:lý do ngắn gọn 1 câu tiếng Việt
VERDICT:GO|ENTRY:{price:.2f}|SL:84.50|TP:92.00|SUMMARY:tóm tắt 1 câu tiếng Việt

Thay các giá trị mẫu bằng đánh giá thực của bạn. VERDICT=GO nếu >=3 CONFIRM, VERDICT=NO nếu <=2 CONFIRM. SL/TP là số thực (ví dụ: 84.50) tính từ ATR={atr_pct:.2f}%."""

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Expert Panel",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.15,
            },
            timeout=35,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        logging.info(f"[EXPERT_PANEL] {symbol} raw:\n{text}")
        return _parse_expert_panel(text, price)
    except Exception as e:
        logging.warning(f"[EXPERT_PANEL] API error for {symbol}: {e}")
        return _no_gate  # bypass=True → bot_service sẽ dùng format đơn giản


def _macro_str(macro: dict) -> str:
    """Format macro snapshot thành chuỗi ngắn gọn cho prompt."""
    lines = []
    order = ["gold", "oil", "dxy", "sp500", "nasdaq", "nvda", "aapl", "msft"]
    for key in order:
        m = macro.get(key)
        if not m:
            continue
        chg = m["change_pct"]
        sign = "+" if chg >= 0 else ""
        lines.append(f"{m['name']}: {m['price']:,.2f} ({sign}{chg:.2f}%)")
    return " | ".join(lines) if lines else "Không có dữ liệu vĩ mô"


def ai_investment_guide(
    symbol: str,
    action: str,
    price: float,
    sl: float,
    tp: float,
    atr: float,
    atr_pct: float,
    rsi: float,
    macd_hist: float,
    d1_bullish: bool,
    d1_bearish: bool,
    btc_rsi: float,
    sr_d1_supports: List[float],
    sr_d1_resistances: List[float],
    sr_near_supports: List[float],
    sr_near_resistances: List[float],
    panel_confirmed: int,
    panel_total: int,
    buy_zone: tuple,
    sell_zone: tuple,
    macro: dict,
    interval: str,
) -> str:
    """
    Tổng hợp toàn bộ data → phương hướng đầu tư cụ thể cho Spot & Futures.
    Trả về HTML-safe plain text, không markdown.
    """
    if not OPENROUTER_API_KEY:
        return ""

    direction = "MUA (LONG)" if action == "BUY" else "BÁN (SHORT)"
    d1_label = "Bullish" if d1_bullish else ("Bearish" if d1_bearish else "Neutral")
    macro_line = _macro_str(macro) if macro else "Không có dữ liệu"

    def _fmtsr(lst): return " · ".join(f"{v:,.2f}" for v in lst[:4]) if lst else "N/A"

    # SL/TP tham chiếu
    sl_ref  = sl if sl > 0 else round(price - 2 * atr if action == "BUY" else price + 2 * atr, 2)
    tp1_ref = tp if tp > 0 else round(price + 2 * atr * 2 if action == "BUY" else price - 2 * atr * 2, 2)
    risk    = abs(price - sl_ref)
    tp2_ref = round(price + risk * 3 if action == "BUY" else price - risk * 3, 2)

    # DCA levels từ S/R gần nhất
    dca_levels = []
    if action == "BUY":
        candidates = sorted(sr_near_supports + sr_d1_supports)
        dca_levels = [v for v in candidates if v < price][:3]
    else:
        candidates = sorted(sr_near_resistances + sr_d1_resistances, reverse=True)
        dca_levels = [v for v in candidates if v > price][:3]

    dca_str = " → ".join(f"{v:,.2f}" for v in dca_levels) if dca_levels else "theo pullback"

    buy_low, buy_high = buy_zone
    sell_low, sell_high = sell_zone

    prompt = f"""Bạn là chuyên gia tư vấn đầu tư crypto thực chiến. Tổng hợp toàn bộ dữ liệu dưới đây để đưa ra phương hướng đầu tư CHI TIẾT cho nhà đầu tư cá nhân.

TỔNG HỢP TÍN HIỆU:
- {symbol}: tín hiệu {direction} tại {price:,.4f} USDT (khung {interval})
- Hội đồng chuyên gia: {panel_confirmed}/{panel_total} đồng thuận
- RSI: {rsi:.1f} | MACD hist: {macd_hist:.4f} | ATR: {atr:.4f} ({atr_pct:.2f}%)
- D1 Bias: {d1_label} | BTC RSI: {btc_rsi:.1f}
- Zone BUY: {buy_low:,.2f}–{buy_high:,.2f} | Zone SELL: {sell_low:,.2f}–{sell_high:,.2f}
- Hỗ trợ D1: {_fmtsr(sr_d1_supports)} | Kháng cự D1: {_fmtsr(sr_d1_resistances)}
- Hỗ trợ {interval}: {_fmtsr(sr_near_supports)} | Kháng cự {interval}: {_fmtsr(sr_near_resistances)}
- SL tham chiếu: {sl_ref:,.4f} | TP1: {tp1_ref:,.4f} | TP2: {tp2_ref:,.4f}
- DCA levels tiềm năng: {dca_str}
- Macro: {macro_line}

Viết phương hướng đầu tư bằng tiếng Việt theo đúng 4 mục sau. Dùng số liệu cụ thể từ dữ liệu trên. KHÔNG dùng markdown (*,#), chỉ dùng emoji + text thuần.

💎 SPOT — Phân bổ vốn:
Nêu rõ: vào bao nhiêu % vốn ngay bây giờ, DCA thêm ở mức giá nào (nếu có), TP từng phần ở đâu, cắt lỗ toàn bộ khi nào.

⚡ FUTURES — Thận trọng:
Nêu rõ: đòn bẩy khuyến nghị (bảo thủ & tối đa), % tài khoản mỗi lệnh, giá entry chính xác, SL/TP cụ thể.

⏰ Thời điểm vào lệnh:
Vào ngay hay chờ điều kiện gì? Nêu 1–2 điều kiện xác nhận thêm nếu chưa chắc.

⚠️ Vô hiệu tín hiệu khi:
Nêu 1–2 mức giá hoặc sự kiện cụ thể sẽ làm tín hiệu này mất hiệu lực.

Tối đa 200 từ. Số liệu cụ thể, không nói chung chung."""

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Investment Guide",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.3,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"[INVEST_GUIDE] Error: {e}")
        return ""


def ai_macro_brief(
    symbol: str,
    action: str,
    price: float,
    macro: dict,
    interval: str,
    model: str,
    style: str = "correlation",
) -> str:
    """
    AI brief về macro context cho Telegram.
    style='correlation' → Model 1: tương quan vĩ mô & crypto
    style='risk'        → Model 2: rủi ro vĩ mô có thể vô hiệu tín hiệu
    Trả về plain text tiếng Việt, không markdown.
    """
    if not OPENROUTER_API_KEY or not model:
        return ""

    macro_line = _macro_str(macro)
    if not macro_line or macro_line == "Không có dữ liệu vĩ mô":
        return ""

    direction = "MUA" if action == "BUY" else "BÁN"

    if style == "correlation":
        prompt = (
            f"Tín hiệu {direction} {symbol} tại {price:,.2f} USDT ({interval}).\n"
            f"Dữ liệu vĩ mô hôm nay: {macro_line}\n\n"
            f"Viết đúng 2–3 câu tiếng Việt: môi trường vĩ mô hiện tại (risk-on hay risk-off?) "
            f"ảnh hưởng thế nào đến tín hiệu {direction} này? "
            f"Chú ý tương quan DXY↔crypto, vàng/dầu như thế nào, cổ phiếu công nghệ (NVDA/AAPL/MSFT) "
            f"đang phát tín hiệu gì. Không dùng markdown, chỉ văn xuôi."
        )
    else:
        prompt = (
            f"Tín hiệu {direction} {symbol} tại {price:,.2f} USDT ({interval}).\n"
            f"Dữ liệu vĩ mô hôm nay: {macro_line}\n\n"
            f"Viết đúng 2–3 câu tiếng Việt: yếu tố vĩ mô nào là rủi ro chính có thể "
            f"vô hiệu hoá tín hiệu {direction} này? "
            f"Nếu DXY mạnh lên hoặc cổ phiếu công nghệ giảm thì crypto bị ảnh hưởng ra sao? "
            f"Không dùng markdown, chỉ văn xuôi."
        )

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://qapi.app",
                "X-Title": "QAPI Macro Brief",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 220,
                "temperature": 0.4,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"[MACRO_BRIEF] model={model} style={style}: {e}")
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
