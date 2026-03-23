"""
bot_backtest.py — Backtest engine dùng chính algorithm của bot.

Dùng CSV data từ ./data/ (được tạo bởi data.py).
Reuse hoàn toàn: check_entry(), check_exit(), update_trailing_stop(), get_bot_config()
từ bot_service.py → kết quả nhất quán 100% với bot thực.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

DATA_DIR = Path("data")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _available_files() -> List[Dict]:
    """Trả về danh sách các file CSV hiện có."""
    out = []
    for f in sorted(DATA_DIR.glob("*.csv")):
        parts = f.stem.split("_")          # BTCUSDT_4h_10y
        if len(parts) >= 2:
            out.append({"symbol": parts[0], "interval": parts[1], "file": str(f)})
    return out


def _build_daily_map(df_1d: pd.DataFrame) -> Dict[str, dict]:
    """Xây dựng map ngày → 1D context từ CSV."""
    daily: Dict[str, dict] = {}
    for _, row in df_1d.iterrows():
        day = str(row["datetime"])[:10]
        daily[day] = {
            "uptrend":  int(row.get("price_above_ema200", 0)) == 1,
            "bull_ema": int(row.get("ema_bullish", 0)) == 1,
            "bear_ema": int(row.get("ema_bearish", 0)) == 1,
            "danger":   int(row.get("danger_overbought", 0)) == 1,
            "rsi":      float(row.get("rsi_14", 50) or 50),
            "adx":      float(row.get("adx_14", 20) or 20),
        }
    return daily


def _row_to_snap(row) -> dict:
    """Chuyển 1 dòng CSV thành snap dict cho check_entry/check_exit."""
    def _f(col, default=0.0):
        v = row.get(col, default)
        return float(v) if v is not None and v == v else float(default)  # NaN check

    price  = _f("close")
    bb_u   = _f("bb_upper") or None
    bb_l   = _f("bb_lower") or None
    bb_pct = None
    if bb_u and bb_l and bb_u > bb_l:
        bb_pct = (price - bb_l) / (bb_u - bb_l)

    return {
        "price":      price,
        "rsi_14":     _f("rsi_14", 50),
        "macd_hist":  _f("macd_hist", 0),
        "macd_rising":int(row.get("macd_rising", 0)) == 1,
        "adx_14":     _f("adx_14", 20),
        "di_plus":    _f("di_plus", 20),
        "di_minus":   _f("di_minus", 20),
        "stoch_k":    _f("stoch_k", 50),
        "atr_14":     _f("atr_14", 0),
        "bb_pct":     bb_pct,
        "bb_upper":   bb_u,
        "bb_lower":   bb_l,
        "buy_score":  int(row.get("buy_score", 0) or 0),
        "sell_score": int(row.get("sell_score", 0) or 0),
        "in_buy_zone":  int(row.get("in_buy_zone", 0)) == 1,
        "in_sell_zone": int(row.get("in_sell_zone", 0)) == 1,
        "obv_trend":  "flat",
        "danger_overbought": int(row.get("danger_overbought", 0)) == 1,
        "dyn_oversold":  _f("rsi_oversold_dyn", 35),
        "dyn_overbought":_f("rsi_overbought_dyn", 70),
    }


# ── Core backtest engine ──────────────────────────────────────────────────────

def _load_cfg(symbol: str, mode: str):
    """Import bot_service với BOT_MODE override, trả về (cfg, check_entry, check_exit, update_trailing_stop)."""
    import os
    old_mode = os.environ.get("BOT_MODE", "default")
    os.environ["BOT_MODE"] = mode
    try:
        from services.bot_service import get_bot_config, check_entry, check_exit, update_trailing_stop
        cfg = get_bot_config(symbol)
    finally:
        os.environ["BOT_MODE"] = old_mode
    return cfg, check_entry, check_exit, update_trailing_stop


def _simulate(df: pd.DataFrame, daily_map: Dict[str, dict],
              cfg: dict, check_entry, check_exit, update_trailing_stop,
              initial_capital: float, symbol: str, interval: str, mode: str) -> dict:
    """Core bar-by-bar simulation. Dùng chung cho cả file-based và upload-based backtest."""
    _DEFAULT_DCTX = {
        "uptrend": False, "bull_ema": False, "bear_ema": False,
        "danger": False, "rsi": 50.0, "adx": 20.0,
    }

    capital   = initial_capital
    position: Optional[dict] = None
    trades:   List[dict] = []
    equity_curve: List[dict] = []

    for i in range(len(df)):
        row   = df.iloc[i]
        day   = str(row["datetime"])[:10]
        dctx  = daily_map.get(day, _DEFAULT_DCTX)
        snap  = _row_to_snap(row)
        price = snap["price"]
        atr   = snap["atr_14"]

        eq = capital
        if position:
            eq += position["pos_usd"] * (price - position["entry_price"]) / position["entry_price"]
        equity_curve.append({"date": day, "equity": round(eq, 2)})

        if position:
            entry    = position["entry_price"]
            new_stop = update_trailing_stop(price, entry, atr, position["stop_price"], cfg)
            position["stop_price"] = new_stop

            if price <= new_stop:
                exit_price = new_stop
                pnl_pct    = (exit_price - entry) / entry * 100
                pnl_usd    = position["pos_usd"] * pnl_pct / 100
                fee        = position["pos_usd"] * cfg["commission_pct"] / 100
                capital   += position["pos_usd"] + pnl_usd - fee
                trades.append(_make_trade(position, exit_price, day, "STOP", pnl_pct, pnl_usd - fee))
                position = None
                continue

            should_exit, reason = check_exit(snap, dctx, cfg)
            if should_exit:
                exit_price = price
                pnl_pct    = (exit_price - entry) / entry * 100
                pnl_usd    = position["pos_usd"] * pnl_pct / 100
                fee        = position["pos_usd"] * cfg["commission_pct"] / 100
                capital   += position["pos_usd"] + pnl_usd - fee
                trades.append(_make_trade(position, exit_price, day, reason, pnl_pct, pnl_usd - fee))
                position = None
        else:
            should_enter, strategy = check_entry(snap, dctx, cfg)
            if should_enter and atr > 0:
                pos_usd = capital * cfg["position_pct"]
                stop    = price - cfg["sl_atr_mult"] * atr
                position = {
                    "entry_price": price,
                    "stop_price":  stop,
                    "strategy":    strategy,
                    "entry_atr":   atr,
                    "pos_usd":     pos_usd,
                    "entry_time":  day,
                }
                capital -= pos_usd

    if position:
        last_price = float(df.iloc[-1]["close"])
        last_day   = str(df.iloc[-1]["datetime"])[:10]
        entry      = position["entry_price"]
        pnl_pct    = (last_price - entry) / entry * 100
        pnl_usd    = position["pos_usd"] * pnl_pct / 100
        fee        = position["pos_usd"] * cfg["commission_pct"] / 100
        capital   += position["pos_usd"] + pnl_usd - fee
        trades.append(_make_trade(position, last_price, last_day, "END", pnl_pct, pnl_usd - fee))

    return _compute_metrics(trades, equity_curve, df, initial_capital, capital, cfg, symbol, interval, mode)


def run_backtest(
    symbol: str,
    interval: str,
    mode: str = "default",
    initial_capital: float = 10_000,
) -> dict:
    """Chạy backtest từ file CSV trong ./data/."""
    cfg, check_entry, check_exit, update_trailing_stop = _load_cfg(symbol, mode)

    f_main = DATA_DIR / f"{symbol}_{interval}_10y.csv"
    f_1d   = DATA_DIR / f"{symbol}_1d_10y.csv"

    if not f_main.exists():
        return {"error": f"Không tìm thấy {f_main.name}. Hãy chạy data.py trước."}

    df = pd.read_csv(f_main, parse_dates=["datetime"])
    df = df.dropna(subset=["close", "atr_14"]).reset_index(drop=True)

    daily_map: Dict[str, dict] = {}
    if f_1d.exists() and interval != "1d":
        df_1d = pd.read_csv(f_1d, parse_dates=["datetime"])
        daily_map = _build_daily_map(df_1d)
    elif interval == "1d":
        daily_map = _build_daily_map(df)

    return _simulate(df, daily_map, cfg, check_entry, check_exit, update_trailing_stop,
                     initial_capital, symbol, interval, mode)


def run_backtest_from_df(
    df_main: "pd.DataFrame",
    df_1d: "Optional[pd.DataFrame]",
    symbol: str,
    interval: str,
    mode: str = "default",
    initial_capital: float = 10_000,
) -> dict:
    """Chạy backtest từ DataFrame (dùng khi user upload CSV)."""
    cfg, check_entry, check_exit, update_trailing_stop = _load_cfg(symbol, mode)

    if "datetime" not in df_main.columns:
        return {"error": "CSV thiếu cột 'datetime'. Vui lòng kiểm tra định dạng file."}
    if "close" not in df_main.columns or "atr_14" not in df_main.columns:
        return {"error": "CSV thiếu cột 'close' hoặc 'atr_14'. Hãy dùng file được tạo bởi data.py."}

    df = df_main.copy()
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["close", "atr_14", "datetime"]).reset_index(drop=True)

    if df.empty:
        return {"error": "File CSV không có dữ liệu hợp lệ sau khi lọc."}

    daily_map: Dict[str, dict] = {}
    if df_1d is not None and interval != "1d":
        df_1d = df_1d.copy()
        df_1d["datetime"] = pd.to_datetime(df_1d["datetime"], errors="coerce")
        daily_map = _build_daily_map(df_1d)
    elif interval == "1d":
        daily_map = _build_daily_map(df)

    return _simulate(df, daily_map, cfg, check_entry, check_exit, update_trailing_stop,
                     initial_capital, symbol, interval, mode)


def _make_trade(pos: dict, exit_price: float, exit_date: str, reason: str,
                pnl_pct: float, net_pnl: float) -> dict:
    return {
        "entry_date":  pos["entry_time"],
        "exit_date":   exit_date,
        "strategy":    pos["strategy"],
        "entry_price": round(pos["entry_price"], 4),
        "exit_price":  round(exit_price, 4),
        "reason":      reason,
        "pnl_pct":     round(pnl_pct, 2),
        "net_pnl":     round(net_pnl, 2),
        "win":         pnl_pct > 0,
    }


def _compute_metrics(trades, equity_curve, df, initial_capital, final_capital,
                     cfg, symbol, interval, mode) -> dict:
    if not trades:
        return {
            "error": None, "symbol": symbol, "interval": interval, "mode": mode,
            "summary": {"total_trades": 0, "total_return_pct": 0},
            "trades": [], "equity_curve": equity_curve, "exit_reasons": {}, "strategy_counts": {},
        }

    pnls    = [t["pnl_pct"] for t in trades]
    net_pnls= [t["net_pnl"] for t in trades]
    wins    = [p for p in pnls if p > 0]
    losses  = [p for p in pnls if p <= 0]

    total_return = (final_capital - initial_capital) / initial_capital * 100
    win_rate     = len(wins) / len(trades) * 100

    gross_win  = sum(p for p in net_pnls if p > 0)
    gross_loss = abs(sum(p for p in net_pnls if p < 0))
    pf = round(gross_win / gross_loss, 3) if gross_loss > 0 else float("inf")

    # Equity curve metrics
    eq_vals = [e["equity"] for e in equity_curve]
    eq_arr  = np.array(eq_vals, dtype=float)
    peak    = np.maximum.accumulate(eq_arr)
    dd      = (eq_arr - peak) / peak * 100
    max_dd  = float(dd.min())

    # Sharpe (per bar)
    ret_arr = np.diff(eq_arr) / eq_arr[:-1]
    ret_arr = ret_arr[np.isfinite(ret_arr)]
    bars_per_year = {"1d": 365, "4h": 365 * 6, "1h": 365 * 24}.get(interval, 365)
    sharpe = float(np.mean(ret_arr) / np.std(ret_arr) * np.sqrt(bars_per_year)) if ret_arr.std() > 0 else 0.0

    # Buy & Hold
    bh_start = float(df.iloc[0]["close"])
    bh_end   = float(df.iloc[-1]["close"])
    bh_ret   = (bh_end - bh_start) / bh_start * 100

    # Exit reasons
    exit_reasons: Dict[str, Any] = {}
    for t in trades:
        r = t["reason"]
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "wins": 0, "total_pnl": 0.0}
        exit_reasons[r]["count"]    += 1
        exit_reasons[r]["wins"]     += 1 if t["win"] else 0
        exit_reasons[r]["total_pnl"]+= t["pnl_pct"]
    for v in exit_reasons.values():
        v["avg_pnl"]  = round(v["total_pnl"] / v["count"], 2)
        v["win_rate"] = round(v["wins"] / v["count"] * 100, 1)

    # Strategy breakdown
    strategy_counts: Dict[str, Any] = {}
    for t in trades:
        s = t["strategy"]
        if s not in strategy_counts:
            strategy_counts[s] = {"count": 0, "wins": 0, "total_pnl": 0.0}
        strategy_counts[s]["count"]    += 1
        strategy_counts[s]["wins"]     += 1 if t["win"] else 0
        strategy_counts[s]["total_pnl"]+= t["pnl_pct"]
    for v in strategy_counts.values():
        v["avg_pnl"]  = round(v["total_pnl"] / v["count"], 2)
        v["win_rate"] = round(v["wins"] / v["count"] * 100, 1)

    # Max consecutive wins/losses
    max_cw = max_cl = cw = cl = 0
    for t in trades:
        if t["win"]:
            cw += 1; cl = 0; max_cw = max(max_cw, cw)
        else:
            cl += 1; cw = 0; max_cl = max(max_cl, cl)

    # Downsample equity curve for chart (max 500 points)
    step = max(1, len(equity_curve) // 500)
    equity_sampled = equity_curve[::step]

    return {
        "error": None,
        "symbol": symbol, "interval": interval, "mode": mode,
        "config": {k: cfg[k] for k in ["position_pct","sl_atr_mult","buy_score_min","adx_min","commission_pct"]},
        "summary": {
            "initial_capital":   initial_capital,
            "final_capital":     round(final_capital, 2),
            "total_return_pct":  round(total_return, 1),
            "buy_hold_return_pct": round(bh_ret, 1),
            "alpha_pct":         round(total_return - bh_ret, 1),
            "max_drawdown_pct":  round(max_dd, 1),
            "sharpe_ratio":      round(sharpe, 3),
            "profit_factor":     pf,
            "total_trades":      len(trades),
            "win_rate_pct":      round(win_rate, 1),
            "wins":              len(wins),
            "losses":            len(losses),
            "avg_win_pct":       round(sum(wins)/len(wins), 2) if wins else 0,
            "avg_loss_pct":      round(sum(losses)/len(losses), 2) if losses else 0,
            "best_trade_pct":    round(max(pnls), 2),
            "worst_trade_pct":   round(min(pnls), 2),
            "max_win_streak":    max_cw,
            "max_loss_streak":   max_cl,
            "period_start":      str(df.iloc[0]["datetime"])[:10],
            "period_end":        str(df.iloc[-1]["datetime"])[:10],
        },
        "trades":         trades[-200:],    # last 200 trades for table
        "total_trades_count": len(trades),
        "equity_curve":   equity_sampled,
        "exit_reasons":   exit_reasons,
        "strategy_counts": strategy_counts,
    }
