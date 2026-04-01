"""
bot_ai.py — AI analysis for crypto bot.
4-model panel vote for /check command + dashboard analysis.
"""
import os, time, logging, threading
from typing import Dict, List

import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL",  "google/gemini-flash-1.5")
OPENROUTER_MODEL2  = os.getenv("OPENROUTER_MODEL2", "")
OPENROUTER_MODEL3  = os.getenv("OPENROUTER_MODEL3", "meta-llama/llama-3.1-8b-instruct:free")
OPENROUTER_MODEL4  = os.getenv("OPENROUTER_MODEL4", "mistralai/mistral-7b-instruct:free")

_cache: Dict[str, tuple] = {}
AI_CACHE_TTL = 600  # 10 min


def _call(model: str, messages: list, temperature=0.35, max_tokens=250) -> str:
    if not OPENROUTER_API_KEY or not model:
        return ""
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"[AI] {model}: {e}")
        return ""


def _macro_str(macro: dict) -> str:
    parts = []
    for k, v in macro.items():
        parts.append(f"{v.get('name', k)}: ${v.get('price', 0):,.2f} ({v.get('change_pct', 0):+.2f}%)")
    return " | ".join(parts)


def ai_macro_brief(symbol: str, action: str, price: float, macro: dict,
                   interval: str, model: str, style: str) -> str:
    """Short macro-context brief. style='correlation' or 'risk'."""
    if not macro:
        return ""
    macro_s = _macro_str(macro)
    if style == "correlation":
        prompt = (f"[DXY\u2194Crypto] {symbol} {action} @ ${price:,} | {macro_s}\n"
                  f"Nh\u1eadn x\u00e9t ng\u1eafn (\u226460 t\u1eeb ti\u1ebfng Vi\u1ec7t): DXY v\u00e0 macro t\u00e1c \u0111\u1ed9ng g\u00ec \u0111\u1ebfn {symbol} hi\u1ec7n t\u1ea1i?")
    else:
        prompt = (f"[R\u1ee7i ro macro] {symbol} {action} @ ${price:,} | {macro_s}\n"
                  f"Nh\u1eadn x\u00e9t ng\u1eafn (\u226460 t\u1eeb ti\u1ebfng Vi\u1ec7t): r\u1ee7i ro macro l\u1edbn nh\u1ea5t hi\u1ec7n t\u1ea1i l\u00e0 g\u00ec?")
    return _call(model, [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=150)


def call_openrouter_analysis(symbol: str, tf: str, snap: dict) -> str:
    """Dashboard AI analysis — Model 1. Cached 10 min."""
    if not OPENROUTER_API_KEY:
        return ""
    cache_key = f"m1_{symbol}_{tf}"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < AI_CACHE_TTL:
        return _cache[cache_key][1]

    strat = snap.get("entry_strategy", "Ch\u01b0a c\u00f3 t\u00edn hi\u1ec7u")
    prompt = (
        f"Ph\u00e2n t\u00edch ng\u1eafn (\u2264120 t\u1eeb, ti\u1ebfng Vi\u1ec7t) cho {symbol} khung {tf}:\n"
        f"Gi\u00e1: ${snap.get('price', 0):,.2f} | RSI: {snap.get('rsi_14', 50):.1f} | "
        f"ADX: {snap.get('adx_14', 20):.1f} | MACD: {'\u2191' if snap.get('macd_rising') else '\u2193'}\n"
        f"1D trend: {'Uptrend \u2705' if snap.get('uptrend') else 'Downtrend \u26a0\ufe0f'} | "
        f"Chi\u1ebfn l\u01b0\u1ee3c: {strat}\n"
        f"H\u1ecfi: xu h\u01b0\u1edbng v\u00e0 m\u1ee9c gi\u00e1 quan tr\u1ecdng c\u1ea7n theo d\u00f5i?"
    )
    result = _call(OPENROUTER_MODEL, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=220)
    _cache[cache_key] = (now, result)
    return result


def call_openrouter_analysis_model2(symbol: str, tf: str, snap: dict) -> str:
    """Risk analysis — Model 2. Cached 10 min."""
    if not OPENROUTER_API_KEY or not OPENROUTER_MODEL2:
        return ""
    cache_key = f"m2_{symbol}_{tf}"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < AI_CACHE_TTL:
        return _cache[cache_key][1]

    prompt = (
        f"Ph\u00e2n t\u00edch r\u1ee7i ro (\u2264100 t\u1eeb, ti\u1ebfng Vi\u1ec7t) cho {symbol} {tf}:\n"
        f"Chi\u1ebfn l\u01b0\u1ee3c: {snap.get('entry_strategy', 'Kh\u00f4ng c\u00f3 t\u00edn hi\u1ec7u')} | "
        f"RSI: {snap.get('rsi_14', 50):.1f} | Stoch: {snap.get('stoch_k', 50):.1f}\n"
        f"Nguy c\u01a1 ch\u00ednh v\u00e0 \u0111i\u1ec1u ki\u1ec7n v\u00f4 hi\u1ec7u t\u00edn hi\u1ec7u l\u00e0 g\u00ec? "
        f"Vi\u1ebft \u0111\u1ea7y \u0111\u1ee7 kh\u00f4ng c\u1eaft gi\u1eefa c\u00e2u."
    )
    result = _call(OPENROUTER_MODEL2, [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=200)
    _cache[cache_key] = (now, result)
    return result


# ── Newbie-friendly AI functions ─────────────────────────────────────────────

def call_ai_newbie_summary(symbol: str, tf: str, snap: dict) -> str:
    """Newbie trend summary — plain Vietnamese, no technical terms. Cached 10 min."""
    if not OPENROUTER_API_KEY:
        return ""
    cache_key = f"nb_sum_{symbol}_{tf}"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < AI_CACHE_TTL:
        return _cache[cache_key][1]

    price      = snap.get("price", 0)
    uptrend    = snap.get("uptrend", False)
    macd_up    = snap.get("macd_rising", False)
    buy_score  = snap.get("buy_score", 0)
    sell_score = snap.get("sell_score", 0)
    in_buy     = snap.get("in_buy_zone", False)
    in_sell    = snap.get("in_sell_zone", False)
    strategy   = snap.get("entry_strategy", "")

    trend_desc = "đang đi lên" if uptrend else "đang đi xuống"
    momentum   = "đà mua đang tăng dần" if macd_up else "đà mua đang yếu đi"
    zone_desc  = ("đang ở vùng giá hấp dẫn để mua" if in_buy else
                  "đang ở vùng nhiều người muốn chốt lời" if in_sell else
                  "đang ở giữa hai vùng")
    signal_map = {
        "DIP_BUY":      "Giá vừa về vùng rẻ sau khi điều chỉnh.",
        "TREND_FOLLOW": "Sóng tăng đang hình thành rõ nét.",
        "BREAKOUT_BUY": "Giá vừa phá vỡ vùng kháng cự.",
        "BEAR_BOUNCE":  "Giá đang bật nhẹ trong xu hướng giảm.",
    }
    signal_desc = signal_map.get(strategy, "")

    prompt = (
        f"Bạn là người mentor dạy trading cho học viên hoàn toàn mới.\n"
        f"Giải thích tình huống {symbol} khung {tf} bằng ngôn ngữ thật đơn giản, dùng ẩn dụ đời thường.\n\n"
        f"Dữ liệu (ĐỪNG nhắc lại các con số, chỉ dùng để hiểu ngữ cảnh):\n"
        f"- Giá: ${price:,.2f} | Xu hướng: {trend_desc}\n"
        f"- Động lực: {momentum} | Vị trí: {zone_desc}\n"
        f"- {signal_desc} Điểm mua: {buy_score}/13, điểm bán: {sell_score}/13\n\n"
        f"Yêu cầu bắt buộc:\n"
        f"1. KHÔNG dùng từ: RSI, ADX, MACD, EMA, Stochastic, indicator, resistance, support\n"
        f"2. Dùng ẩn dụ: 'Giá đang như người chạy đà lên', 'Nhiều người đang muốn bán ở đây'\n"
        f"3. Câu cuối PHẢI bắt đầu bằng 'Lúc này nên...'\n"
        f"4. Tối đa 80 từ tiếng Việt, viết liền mạch không dùng bullet points"
    )
    result = _call(OPENROUTER_MODEL, [{"role": "user", "content": prompt}], temperature=0.5, max_tokens=180)
    if result:
        _cache[cache_key] = (now, result)
    return result


def call_ai_risk_warning(symbol: str, tf: str, snap: dict) -> str:
    """Newbie risk checklist — 3 lines with ⚠️/✅ icons. Cached 15 min."""
    if not OPENROUTER_API_KEY:
        return ""
    model = OPENROUTER_MODEL2 or OPENROUTER_MODEL
    if not model:
        return ""
    cache_key = f"nb_risk_{symbol}_{tf}"
    now = time.time()
    NB_RISK_TTL = 900
    if cache_key in _cache and now - _cache[cache_key][0] < NB_RISK_TTL:
        return _cache[cache_key][1]

    price      = snap.get("price", 0)
    uptrend    = snap.get("uptrend", False)
    buy_score  = snap.get("buy_score", 0)
    sell_score = snap.get("sell_score", 0)
    in_buy     = snap.get("in_buy_zone", False)
    in_sell    = snap.get("in_sell_zone", False)
    macd_up    = snap.get("macd_rising", False)
    bars_below = snap.get("bars_below_ema200", 0)

    parts = []
    if in_sell:
        parts.append("giá đang ở vùng mà nhiều người đã đặt lệnh bán từ trước")
    if not uptrend:
        parts.append("xu hướng lớn đang đi xuống")
    if sell_score >= 7:
        parts.append(f"có {sell_score} dấu hiệu cảnh báo đang xuất hiện")
    if bars_below >= 5:
        parts.append(f"giá đã đi dưới đường trung bình dài hạn {bars_below} cây nến liên tiếp")
    if not macd_up:
        parts.append("lực mua đang suy yếu")
    if buy_score >= 8:
        parts.append(f"có {buy_score} dấu hiệu tích cực")
    if in_buy:
        parts.append("giá đang ở vùng hỗ trợ tốt")

    context_str = "; ".join(parts) if parts else "thị trường đang ở trạng thái trung tính"

    prompt = (
        f"Bạn đang tư vấn cho người mới học trading về {symbol} tại ${price:,.2f} (khung {tf}).\n"
        f"Tình huống: {context_str}.\n\n"
        f"Viết ĐÚNG 3 dòng theo format này, KHÔNG thêm gì khác:\n"
        f"⚠️ [rủi ro hoặc điều cần chú ý, tối đa 15 từ]\n"
        f"⚠️ [rủi ro hoặc điều cần chú ý, tối đa 15 từ]\n"
        f"✅ [điểm tích cực hoặc điều kiện thuận lợi, tối đa 15 từ]\n\n"
        f"KHÔNG dùng: RSI, ADX, MACD, EMA, indicator, resistance, support level, overbought, oversold\n"
        f"DÙNG ngôn ngữ đời thường. Nếu tích cực nhiều hơn: cho 2 dấu ✅ và 1 dấu ⚠️"
    )
    result = _call(model, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=120)
    if result:
        _cache[cache_key] = (now, result)
    return result


def call_ai_entry_timing(symbol: str, tf: str, snap: dict, sim: dict) -> str:
    """Entry timing advice — 1 sentence max 40 words. Cached 5 min."""
    if not OPENROUTER_API_KEY:
        return ""
    model = OPENROUTER_MODEL3 or OPENROUTER_MODEL
    if not model:
        return ""
    cache_key = f"nb_entry_{symbol}_{tf}"
    now = time.time()
    NB_ENTRY_TTL = 300
    if cache_key in _cache and now - _cache[cache_key][0] < NB_ENTRY_TTL:
        return _cache[cache_key][1]

    price      = snap.get("price", 0)
    uptrend    = snap.get("uptrend", False)
    macd_up    = snap.get("macd_rising", False)
    buy_score  = snap.get("buy_score", 0)
    in_buy     = snap.get("in_buy_zone", False)
    in_sell    = snap.get("in_sell_zone", False)

    status    = sim.get("status", "WATCHING")
    stop_p    = sim.get("stop_price", 0)
    tp_p      = sim.get("tp_estimate", price * 1.02)
    sl_pct    = sim.get("sl_pct", 0)

    if status == "SIGNAL":
        signal_ctx = f"Bot phát tín hiệu vào lệnh. SL đề xuất: ${stop_p:,.2f} ({sl_pct:.1f}% rủi ro). TP: ${tp_p:,.2f}."
    elif status == "IN_TRADE":
        signal_ctx = "Đang có lệnh mở."
    else:
        signal_ctx = "Chưa có tín hiệu rõ ràng."

    trend_ctx = (
        f"Xu hướng {'tăng' if uptrend else 'giảm'}, đà mua {'mạnh' if macd_up else 'yếu'}, "
        f"điểm mua {buy_score}/13, "
        f"{'vùng mua tốt' if in_buy else 'vùng bán' if in_sell else 'giữa hai vùng'}."
    )

    prompt = (
        f"Trợ lý trading cho người mới. Đánh giá THỜI ĐIỂM vào lệnh MUA {symbol}.\n"
        f"Giá hiện tại: ${price:,.2f} (khung {tf})\n"
        f"Tình huống: {trend_ctx}\n"
        f"{signal_ctx}\n\n"
        f"Trả lời ĐÚNG 1 trong 3 dạng câu, KHÔNG giải thích thêm:\n"
        f"- 'Vào lệnh ngay tại ${price:,.2f}, đặt cắt lỗ ${stop_p:,.2f}' (nếu điều kiện tốt)\n"
        f"- 'Đợi giá về $[mức giá] rồi vào, vì [lý do ≤8 từ]' (nếu cần chờ)\n"
        f"- 'Không phải lúc này vì [lý do ≤8 từ]' (nếu rủi ro cao)\n\n"
        f"Tối đa 40 từ. KHÔNG dùng RSI, MACD, ADX, indicator."
    )
    result = _call(model, [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=100)
    if result:
        _cache[cache_key] = (now, result)
    return result


# ── 4-model panel vote ────────────────────────────────────────────────────────

def _model_short_label(model_id: str) -> str:
    """Extract a short display label from a model ID string."""
    if not model_id:
        return "AI"
    name = model_id.split("/")[-1].split(":")[0].lower()
    mapping = [
        ("gemini-2.5", "Gemini 2.5"), ("gemini-2", "Gemini 2"),
        ("gemini-flash", "Gemini"), ("gemini-pro", "Gemini Pro"),
        ("gpt-4o", "GPT-4o"), ("gpt-4", "GPT-4"), ("gpt-3", "GPT-3"),
        ("claude-3-opus", "Claude Opus"), ("claude-3-sonnet", "Claude Sonnet"),
        ("claude-3-haiku", "Claude Haiku"), ("claude", "Claude"),
        ("llama-3.3", "Llama 3.3"), ("llama-3.1", "Llama 3.1"), ("llama", "Llama"),
        ("mistral-large", "Mistral Lg"), ("mistral-small", "Mistral Sm"), ("mistral", "Mistral"),
        ("deepseek-r1", "DeepSeek R1"), ("deepseek", "DeepSeek"),
        ("qwen2.5", "Qwen 2.5"), ("qwen", "Qwen"),
        ("phi-3", "Phi-3"),
    ]
    for key, label in mapping:
        if key in name:
            return label
    # fallback: take first 12 chars of raw name
    return model_id.split("/")[-1].split(":")[0][:12]


def _call_vote(model: str, symbol: str, tf: str, snap: dict,
               extra_ctx: str = "", direction: str = "buy") -> dict:
    """Ask a single AI model: MUA / BÁN / CHỜ with specific price level.
    direction='buy'  → focus on long entry evaluation.
    direction='sell' → focus on short/sell entry evaluation.
    """
    if not OPENROUTER_API_KEY or not model:
        return {}

    uptrend_d1  = snap.get("uptrend", False)
    h1_uptrend  = snap.get("h1_uptrend", None)
    macd_rising = snap.get("macd_rising", False)
    rsi         = snap.get("rsi_14", 50)
    stoch       = snap.get("stoch_k", 50)
    adx         = snap.get("adx_14", 0)
    price       = snap.get("price", 0)
    buy_score   = snap.get("buy_score", 0)
    sell_score  = snap.get("sell_score", 0)
    in_buy      = snap.get("in_buy_zone", False)
    in_sell     = snap.get("in_sell_zone", False)

    h1_str = "Tăng" if h1_uptrend is True else ("Giảm" if h1_uptrend is False else "?")
    h4_str = "Tăng" if (macd_rising and rsi > 50) else "Giảm"
    d1_str = "Tăng" if uptrend_d1 else "Giảm"

    rsi_label = (
        "quá bán" if rsi < 30 else
        "thấp"    if rsi < 45 else
        "trung tính" if rsi < 55 else
        "cao"     if rsi < 70 else
        "quá mua"
    )
    zone_str = "vùng MUA" if in_buy else ("vùng BÁN" if in_sell else "giữa hai vùng")

    if direction == "sell":
        question = (
            f"Người dùng muốn BÁN/SHORT {symbol}. Đánh giá: Có nên BÁN ngay không?\n\n"
        )
        detail_hint = (
            f"nếu BÁN ngay thì SL (stop-loss) và TP (chốt lời) đề xuất là bao nhiêu; "
            f"nếu CHỜ thì chờ giá lên vùng bán nào; "
            f"nếu KHÔNG BÁN thì lý do (giá quá thấp, tín hiệu tăng mạnh...)"
        )
        key_metrics = f"Sell Score: {sell_score}/13 (quan trọng) | Buy Score: {buy_score}/13"
    else:
        question = (
            f"Người dùng muốn MUA/LONG {symbol}. Đánh giá: Có nên MUA ngay không?\n\n"
        )
        detail_hint = (
            f"nếu MUA ngay thì SL (stop-loss) và TP (chốt lời) đề xuất là bao nhiêu; "
            f"nếu CHỜ thì chờ giá về vùng mua nào; "
            f"nếu KHÔNG MUA thì lý do (giá quá cao, tín hiệu giảm mạnh...)"
        )
        key_metrics = f"Buy Score: {buy_score}/13 (quan trọng) | Sell Score: {sell_score}/13"

    prompt = (
        f"Trader chuyên nghiệp phân tích {symbol} khung {tf}.\n"
        f"{question}"
        f"Dữ liệu:\n"
        f"Giá: ${price:,.2f} | Xu hướng H1={h1_str} H4={h4_str} D1={d1_str}\n"
        f"RSI {rsi:.0f} ({rsi_label}) | Stoch {stoch:.0f} | ADX {adx:.0f} | "
        f"MACD {'↑' if macd_rising else '↓'}\n"
        f"{key_metrics} | Vị trí: {zone_str}\n"
        f"{extra_ctx}"
        f"\nTrả lời ĐÚNG định dạng, không thêm gì:\n"
        f"QUYẾT ĐỊNH: [MUA hoặc BÁN hoặc CHỜ]\n"
        f"CHI TIẾT: [{detail_hint}. Tối đa 25 từ tiếng Việt, nêu MỨC GIÁ cụ thể.]"
    )

    raw = _call(model, [{"role": "user", "content": prompt}], temperature=0.25, max_tokens=130)
    if not raw:
        return {}

    decision = "CHỜ"
    detail   = ""
    for line in raw.split("\n"):
        line = line.strip()
        u    = line.upper()
        if u.startswith("QUYẾT ĐỊNH:") or u.startswith("QUYET DINH:") or u.startswith("QUYẾT DINH:"):
            val = line.split(":", 1)[-1].strip().upper()
            if   "MUA" in val or "BUY" in val or "LONG" in val:          decision = "MUA"
            elif "BÁN" in val or "BAN" in val or "SELL" in val or "SHORT" in val: decision = "BÁN"
            else:                                                          decision = "CHỜ"
        elif u.startswith("CHI TIẾT:") or u.startswith("CHI TIET:") or u.startswith("CHI TIÉT:"):
            detail = line.split(":", 1)[-1].strip()

    if not detail:
        detail = raw[:150]

    return {"vote": decision, "reason": detail, "label": _model_short_label(model)}


def run_ai_panel_vote(symbol: str, tf: str, snap: dict,
                      extra_ctx: str = "", direction: str = "buy") -> List[dict]:
    """Run up to 4 AI models in parallel. direction='buy' or 'sell'."""
    if not OPENROUTER_API_KEY:
        return []

    models = [m for m in [OPENROUTER_MODEL, OPENROUTER_MODEL2, OPENROUTER_MODEL3, OPENROUTER_MODEL4] if m]
    if not models:
        return []

    cache_key = f"vote_{symbol}_{tf}_{direction}"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key][0] < AI_CACHE_TTL:
        return _cache[cache_key][1]

    results: list = [None] * len(models)

    def _fetch(idx: int, model: str):
        results[idx] = _call_vote(model, symbol, tf, snap, extra_ctx, direction)

    threads = [threading.Thread(target=_fetch, args=(i, m)) for i, m in enumerate(models)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    votes = [r for r in results if r]
    _cache[cache_key] = (now, votes)
    return votes
