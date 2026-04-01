"""
bot_plan.py — Newbie-friendly trade plan generator.
Transforms raw indicator data into plain-language Vietnamese output.
Zero additional API calls: consumes data already computed by bot_service.py.
"""
from typing import List, Tuple


def _determine_action(snap: dict) -> Tuple[str, int]:
    bs = snap.get("buy_score", 0)
    ss = snap.get("sell_score", 0)
    if bs >= 4 and bs > ss + 1:
        return "BUY", bs
    if ss >= 4 and ss > bs + 1:
        return "SELL", ss
    return "WAIT", max(bs, ss)


def _calc_confidence(action: str, snap: dict) -> int:
    if action == "BUY":
        return min(snap.get("buy_score", 0) * 7, 95)
    if action == "SELL":
        return min(snap.get("sell_score", 0) * 7, 95)
    return 0


def _calc_entry(snap: dict, sim: dict) -> dict:
    price = snap.get("price", 0)
    if sim.get("status") in ("SIGNAL", "IN_TRADE") and sim.get("entry_price"):
        entry_price = sim["entry_price"]
    else:
        entry_price = price
    diff_pct = abs(price - entry_price) / entry_price if entry_price else 0
    entry_type = "NOW" if diff_pct <= 0.003 else "LIMIT"
    note = f"Vào lệnh ngay tại ${entry_price:,.2f}" if entry_type == "NOW" else f"Đặt lệnh chờ tại ${entry_price:,.2f}"
    return {"price": round(entry_price, 2), "note": note, "type": entry_type}


def _calc_sl(entry_price: float, action: str, snap: dict,
             sr_d1: dict, sr_near: dict, cfg: dict) -> dict:
    atr = max(snap.get("atr_14", 0), entry_price * 0.001)
    sl_mult = cfg.get("sl_atr_mult", 2.0)

    if action == "BUY":
        sl_atr = entry_price - sl_mult * atr
        hard_cap = entry_price * 0.95
        all_supports = sorted(
            sr_d1.get("supports", []) + sr_near.get("supports", [])
        )
        candidates = [s for s in all_supports if s < entry_price]
        sl_sr = max(candidates) if candidates else None
        sl_price = max(sl_atr, sl_sr) if sl_sr is not None else sl_atr
        sl_price = max(sl_price, hard_cap)
        note = f"Cắt lỗ nếu giá xuống dưới ${sl_price:,.2f}"
    else:
        sl_atr = entry_price + sl_mult * atr
        hard_cap = entry_price * 1.05
        all_resistances = sorted(
            sr_d1.get("resistances", []) + sr_near.get("resistances", [])
        )
        candidates = [r for r in all_resistances if r > entry_price]
        sl_sr = min(candidates) if candidates else None
        sl_price = min(sl_atr, sl_sr) if sl_sr is not None else sl_atr
        sl_price = min(sl_price, hard_cap)
        note = f"Cắt lỗ nếu giá vượt trên ${sl_price:,.2f}"

    sl_pct = (sl_price - entry_price) / entry_price * 100
    return {"price": round(sl_price, 2), "pct": round(sl_pct, 2), "note": note}


def _calc_tp(entry_price: float, action: str, snap: dict,
             sr_d1: dict, sr_near: dict, cfg: dict) -> list:
    atr = max(snap.get("atr_14", 0), entry_price * 0.001)
    t1 = cfg.get("trail_tier1", 1.0)
    t2 = cfg.get("trail_tier2", 2.0)

    all_resistances = sorted(
        sr_d1.get("resistances", []) + sr_near.get("resistances", [])
    )
    all_supports = sorted(
        sr_d1.get("supports", []) + sr_near.get("supports", [])
    )

    if action == "BUY":
        res_above = [r for r in all_resistances if r > entry_price * 1.002]
        tp1_atr = entry_price + t1 * atr
        tp1_sr = res_above[0] if res_above else None
        tp1 = min(tp1_atr, tp1_sr) if tp1_sr else tp1_atr

        tp2_atr = entry_price + t2 * atr
        tp2_sr = res_above[1] if len(res_above) >= 2 else None
        tp2 = min(tp2_atr, tp2_sr) if tp2_sr else tp2_atr
        if tp2 <= tp1:
            tp2 = entry_price + t2 * atr
    else:
        sup_below = sorted([s for s in all_supports if s < entry_price * 0.998], reverse=True)
        tp1_atr = entry_price - t1 * atr
        tp1_sr = sup_below[0] if sup_below else None
        tp1 = max(tp1_atr, tp1_sr) if tp1_sr else tp1_atr

        tp2_atr = entry_price - t2 * atr
        tp2_sr = sup_below[1] if len(sup_below) >= 2 else None
        tp2 = max(tp2_atr, tp2_sr) if tp2_sr else tp2_atr
        if tp2 >= tp1:
            tp2 = entry_price - t2 * atr

    tp1_pct = (tp1 - entry_price) / entry_price * 100
    tp2_pct = (tp2 - entry_price) / entry_price * 100
    return [
        {"price": round(tp1, 2), "pct": round(tp1_pct, 2), "label": f"Mục tiêu 1 ({tp1_pct:+.1f}%)"},
        {"price": round(tp2, 2), "pct": round(tp2_pct, 2), "label": f"Mục tiêu 2 ({tp2_pct:+.1f}%)"},
    ]


def _calc_rr(entry: float, tp_list: list, sl: dict) -> float:
    if not tp_list or not sl:
        return 0.0
    risk = abs(entry - sl["price"])
    reward = abs(tp_list[0]["price"] - entry)
    return round(reward / risk, 2) if risk > 0 else 0.0


def _market_mood(snap: dict, dctx: dict) -> Tuple[str, str, str]:
    """Returns (mood, emoji, text)."""
    uptrend = dctx.get("uptrend", False)
    bull_ema = dctx.get("bull_ema", False)
    bear_ema = dctx.get("bear_ema", False)
    danger = dctx.get("danger", False)
    rsi = snap.get("rsi_14", 50)
    macd_rising = snap.get("macd_rising", False)
    adx = snap.get("adx_14", 0)

    if danger:
        return "WARNING", "🚨", "Giá đang ở vùng nguy hiểm — dễ đảo chiều"
    if uptrend and bull_ema and rsi < 55:
        return "BULLISH_STRONG", "🚀", "Xu hướng tăng rõ ràng — cơ hội tốt"
    if uptrend and macd_rising:
        return "BULLISH", "📈", "Thị trường đang có xu hướng tăng"
    if not uptrend and bear_ema:
        return "BEARISH", "📉", "Xu hướng giảm — thận trọng khi mua"
    if adx < 20:
        return "SIDEWAYS", "😴", "Thị trường đi ngang — chờ tín hiệu rõ hơn"
    return "NEUTRAL", "⚖️", "Tín hiệu chưa rõ ràng — quan sát thêm"


def _build_reasons(action: str, snap: dict, sim: dict) -> List[str]:
    reasons = []
    rsi = snap.get("rsi_14", 50)
    macd_h = snap.get("macd_hist", 0)
    macd_rising = snap.get("macd_rising", False)
    ema34 = snap.get("ema34")
    ema89 = snap.get("ema89")
    ema200 = snap.get("ema200")
    price = snap.get("price", 0)
    strategy = sim.get("strategy", "")

    if action == "BUY":
        if rsi < 40:
            reasons.append(f"RSI {rsi:.0f} — thị trường đang bị bán quá mức, có thể sắp phục hồi")
        elif rsi < 55:
            reasons.append(f"RSI {rsi:.0f} — ở mức trung lập, còn dư địa tăng")
        if macd_h > 0 and macd_rising:
            reasons.append("Đà mua đang tăng dần (MACD dương và tăng)")
        if ema34 and ema89 and ema34 > ema89:
            reasons.append("Đường ngắn hạn vượt dài hạn — xu hướng tăng")
        if ema200 and price > ema200:
            reasons.append("Giá trên EMA200 — xu hướng dài hạn tích cực")
        if strategy == "BEAR_BOUNCE":
            reasons.append("Tín hiệu bật trong xu hướng giảm (Bear Bounce) — lệnh nhỏ")
        elif strategy == "BREAKOUT_BUY":
            reasons.append("Giá vừa tái chiếm đường trung bình dài hạn")
    elif action == "SELL":
        if rsi > 70:
            reasons.append(f"RSI {rsi:.0f} — thị trường đang quá mua, áp lực bán lớn")
        if not macd_rising:
            reasons.append("Đà mua đang yếu đi (MACD giảm)")
        if ema34 and ema89 and ema34 < ema89:
            reasons.append("Đường ngắn hạn dưới dài hạn — xu hướng giảm")
    else:
        bs = snap.get("buy_score", 0)
        ss = snap.get("sell_score", 0)
        reasons.append("Chưa có tín hiệu rõ ràng để vào lệnh")
        if bs > 2:
            reasons.append(f"Buy Score {bs}/13 — cần đạt 4+ để kích hoạt tín hiệu mua")
        if ss > 2:
            reasons.append(f"Sell Score {ss}/13 — theo dõi nếu tiếp tục tăng")
    return reasons[:3]


def _build_warnings(action: str, snap: dict, sl: dict, rr: float) -> List[str]:
    warnings = []
    rsi = snap.get("rsi_14", 50)
    adx = snap.get("adx_14", 0)
    price = snap.get("price", 0)
    bb_u = snap.get("bb_upper")
    bb_l = snap.get("bb_lower")
    macd_rising = snap.get("macd_rising", False)
    sl_pct = abs(sl.get("pct", 0))

    if action != "WAIT" and rr < 1.5:
        warnings.append(f"Tỷ lệ R:R chỉ {rr:.1f}:1 — thấp hơn mức lý tưởng 2:1")
    if action == "BUY" and rsi > 65:
        warnings.append(f"RSI {rsi:.0f} — thị trường có dấu hiệu quá mua")
    if action == "SELL" and rsi < 35:
        warnings.append(f"RSI {rsi:.0f} — thị trường có dấu hiệu quá bán, SELL rủi ro")
    if adx < 20:
        warnings.append(f"Xu hướng yếu (ADX {adx:.0f}) — nhiều tín hiệu giả")
    if action == "BUY" and bb_u and price >= bb_u * 0.99:
        warnings.append("Giá gần dải Bollinger trên — nguy cơ đảo chiều giảm")
    if action == "SELL" and bb_l and price <= bb_l * 1.01:
        warnings.append("Giá gần dải Bollinger dưới — nguy cơ đảo chiều tăng")
    if action == "BUY" and not macd_rising:
        warnings.append("MACD đang giảm — tín hiệu mua chưa được xác nhận đầy đủ")
    if sl_pct > 4.0:
        warnings.append(f"Stop Loss xa ({sl_pct:.1f}%) — thị trường đang biến động mạnh")
    return warnings


STRATEGY_MAP = {
    "DIP_BUY":      ("Mua Đáy RSI",       "Giá về vùng oversold, RSI thấp — cơ hội mua dips"),
    "TREND_FOLLOW": ("Theo Xu Hướng",      "MACD tăng + ADX mạnh — bắt sóng theo trend"),
    "SCORE_BUY":    ("Điểm Số Cao",        "Nhiều chỉ báo đồng thuận — tín hiệu cộng hưởng"),
    "BEAR_BOUNCE":  ("Bật Từ Đáy",         "Sóng hồi trong downtrend — chỉ vào lệnh nhỏ"),
    "BREAKOUT_BUY": ("Phá Vỡ EMA200",      "Giá tái chiếm EMA dài hạn — tín hiệu đổi xu hướng"),
    "":             ("Chờ Tín Hiệu",       "Chưa đủ điều kiện vào lệnh, theo dõi thêm"),
}


def compute_newbie_trade_plan(
    snap: dict,
    sr_d1: dict,
    sr_near: dict,
    cfg: dict,
    sim: dict,
    dctx: dict,
) -> dict:
    """
    Tính kế hoạch giao dịch thân thiện với newbie trader.
    Không gọi thêm API — dùng data đã tính sẵn từ bot_service.py.
    """
    price = snap.get("price", 0)
    action, raw_score = _determine_action(snap)
    confidence_pct = _calc_confidence(action, snap)
    entry_info = _calc_entry(snap, sim)
    entry_price = entry_info["price"]

    effective_action = action if action != "WAIT" else "BUY"
    sl_info = _calc_sl(entry_price, effective_action, snap, sr_d1, sr_near, cfg)
    tp_list = _calc_tp(entry_price, effective_action, snap, sr_d1, sr_near, cfg)
    rr = _calc_rr(entry_price, tp_list, sl_info)

    mood, mood_emoji, mood_text = _market_mood(snap, dctx)
    strategy = sim.get("strategy", "")
    strategy_name, strategy_desc = STRATEGY_MAP.get(strategy, STRATEGY_MAP[""])

    reasons = _build_reasons(action, snap, sim)
    warnings = _build_warnings(action, snap, sl_info, rr)

    # Checklist
    bs = snap.get("buy_score", 0)
    checklist = [
        {"item": "Giá đang ở xu hướng tăng dài hạn (1D)?",
         "ok": dctx.get("uptrend", False)},
        {"item": "RSI chưa quá mua (< 65)?",
         "ok": snap.get("rsi_14", 50) < 65},
        {"item": "Đà mua đang tăng (MACD)?",
         "ok": snap.get("macd_rising", False)},
        {"item": f"Buy Score đủ ngưỡng ({bs}/{cfg.get('buy_score_min', 5)}+)?",
         "ok": bs >= cfg.get("buy_score_min", 5)},
        {"item": "Tỷ lệ R:R >= 1.5:1?",
         "ok": rr >= 1.5},
    ]

    # Signal strength
    if action == "BUY":
        signal_strength = "STRONG" if bs >= 8 else "MODERATE" if bs >= 5 else "WEAK"
    elif action == "SELL":
        ss = snap.get("sell_score", 0)
        signal_strength = "STRONG" if ss >= 8 else "MODERATE" if ss >= 5 else "WEAK"
    else:
        signal_strength = "NO_SIGNAL"

    # Position size note
    pos_pct = int(cfg.get("position_pct", 0.7) * 100)
    if signal_strength == "STRONG":
        position_note = f"Tín hiệu mạnh — có thể dùng {pos_pct}% vốn"
    elif signal_strength == "MODERATE":
        half = pos_pct // 2
        position_note = f"Tín hiệu vừa — nên dùng {half}% vốn thôi"
    else:
        position_note = "Chưa nên vào lệnh lúc này"

    return {
        "action":           action,
        "confidence_pct":   confidence_pct,
        "signal_strength":  signal_strength,
        "entry":            entry_info,
        "tp":               tp_list,
        "sl":               sl_info,
        "risk_reward":      rr,
        "reasons":          reasons,
        "warnings":         warnings,
        "market_mood":      mood,
        "market_mood_emoji": mood_emoji,
        "market_mood_text": mood_text,
        "strategy_name":    strategy_name,
        "strategy_desc":    strategy_desc,
        "position_note":    position_note,
        "checklist":        checklist,
    }
