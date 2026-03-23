"""
bot_ai.py — AI analysis for crypto bot (simplified).
Dual-model macro brief + dashboard analysis.
"""
import os, time, logging
from typing import Dict

import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL",  "google/gemini-flash-1.5")
OPENROUTER_MODEL2  = os.getenv("OPENROUTER_MODEL2", "")

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
        f"Ph\u00e2n t\u00edch r\u1ee7i ro (\u226480 t\u1eeb, ti\u1ebfng Vi\u1ec7t) cho {symbol} {tf}:\n"
        f"Chi\u1ebfn l\u01b0\u1ee3c: {snap.get('entry_strategy', 'Kh\u00f4ng c\u00f3 t\u00edn hi\u1ec7u')} | "
        f"RSI: {snap.get('rsi_14', 50):.1f} | Stoch: {snap.get('stoch_k', 50):.1f}\n"
        f"Nguy c\u01a1 ch\u00ednh v\u00e0 \u0111i\u1ec1u ki\u1ec7n v\u00f4 hi\u1ec7u t\u00edn hi\u1ec7u l\u00e0 g\u00ec?"
    )
    result = _call(OPENROUTER_MODEL2, [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=150)
    _cache[cache_key] = (now, result)
    return result
