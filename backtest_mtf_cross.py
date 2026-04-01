#!/usr/bin/env python3
"""
Backtest chiến lược MTF trong services/bot_service.py (_generate_signal).

- Dữ liệu: data/BTCUSDT_*_10y.csv, data/ETHUSDT_*_10y.csv (cột chỉ báo có sẵn).
- Mô phỏng: cross margin, đòn bẩy x20, mỗi lệnh dùng margin 1000 USDT
  → notional = margin * leverage = 20_000 USDT.
- Vào: đóng nến H1 tại giá close; SL = entry ± ATR_SL_MULT * ATR14(H1) (giống bot).
- Thoát: chạm SL trong nến tiếp theo (intrabar), hoặc đóng ở cuối dữ liệu / sau MAX_HOLD_BARS nến H1.

Lưu ý: bot dùng bot_indicators.compute_adx; hàm đó hiện lệch mạnh so với cột adx_14 trong CSV,
nên backtest dùng adx_14 / chỉ báo trên file để nhất quán với dataset.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Defaults giống bot_service (không đọc .env)
MIN_ATR_PCT = 0.003
ATR_SL_MULT = 1.0
RR_MIN = 1.5  # khớp BOT_RR_MIN — dùng làm mục tiêu chốt lời trong backtest
SIGNAL_COOLDOWN_MS = 120 * 60 * 1000
MARGIN_USD = 1000.0
LEVERAGE = 20.0
FEE_ROUND_TRIP_PCT = 0.0005 * 2.0  # 0.05% mỗi phía trên notional (ước lượng)
MAX_HOLD_BARS = 168  # ~1 tuần H1


@dataclass
class Trade:
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    entry: float
    exit: float
    stop: float
    target: float
    pnl_usd: float
    bars_held: int
    exit_reason: str


def _load_ohlc(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df.sort_values("datetime").reset_index(drop=True)


def _prepare_tf(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Giữ cột cần cho signal + đổi tên tránh trùng khi merge."""
    need = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ema_bullish",
        "ema_bearish",
        "macd_hist",
        "rsi_14",
        "adx_14",
        "bb_pct",
        "atr_14",
        "buy_signal",
        "volume_spike",
        "macd_rising",
    ]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"{prefix}: thiếu cột {missing}")
    out = df[need].copy()
    rename = {
        "ema_bullish": f"ema_bullish_{prefix}",
        "ema_bearish": f"ema_bearish_{prefix}",
        "macd_hist": f"macd_hist_{prefix}",
        "rsi_14": f"rsi_14_{prefix}",
        "adx_14": f"adx_14_{prefix}",
        "bb_pct": f"bb_pct_{prefix}",
        "atr_14": f"atr_14_{prefix}",
        "buy_signal": f"buy_signal_{prefix}",
        "volume_spike": f"volume_spike_{prefix}",
        "macd_rising": f"macd_rising_{prefix}",
    }
    return out.rename(columns=rename)


def _merge_mtf(h1: pd.DataFrame, h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    h1p = _prepare_tf(h1, "h1")
    h4p = _prepare_tf(h4, "h4")
    d1p = _prepare_tf(d1, "d1")
    m = pd.merge_asof(
        h1p.sort_values("datetime"),
        h4p.sort_values("datetime"),
        on="datetime",
        direction="backward",
    )
    m = pd.merge_asof(
        m.sort_values("datetime"),
        d1p.sort_values("datetime"),
        on="datetime",
        direction="backward",
    )
    return m.sort_values("datetime").reset_index(drop=True)


def _atr_pct_row(row: pd.Series) -> float | None:
    c = row["close"]
    a = row["atr_14_h1"]
    if c and c > 0 and a is not None and not pd.isna(a):
        return float(a) / float(c)
    return None


def _signal_state(row: pd.Series) -> tuple[str, str]:
    """Trả về (LONG|SHORT|HOLD, lý do ngắn). Khớp _generate_signal."""
    atr_pct = _atr_pct_row(row)
    if atr_pct is None:
        return "HOLD", "no_atr"
    if atr_pct < MIN_ATR_PCT:
        return "HOLD", "atr_low"

    ema_bullish_d1 = int(row.get("ema_bullish_d1", 0) or 0) == 1
    ema_bearish_d1 = int(row.get("ema_bearish_d1", 0) or 0) == 1
    ema_bullish_h4 = int(row.get("ema_bullish_h4", 0) or 0) == 1

    macd_hist_h4 = row.get("macd_hist_h4")
    adx_14_h4 = row.get("adx_14_h4")
    rsi_14_h4 = row.get("rsi_14_h4")

    buy_signal_h1 = int(row.get("buy_signal_h1", 0) or 0) == 1
    volume_spike_h1 = int(row.get("volume_spike_h1", 0) or 0) == 1
    rsi_14_h1 = row.get("rsi_14_h1")
    bb_pct_h1 = row.get("bb_pct_h1")

    long_ok = bool(
        ema_bullish_d1
        and ema_bullish_h4
        and macd_hist_h4 is not None
        and not pd.isna(macd_hist_h4)
        and float(macd_hist_h4) > 0
        and adx_14_h4 is not None
        and not pd.isna(adx_14_h4)
        and float(adx_14_h4) > 20
        and buy_signal_h1
        and volume_spike_h1
    )

    short_ok = bool(
        ema_bearish_d1
        and macd_hist_h4 is not None
        and not pd.isna(macd_hist_h4)
        and float(macd_hist_h4) < 0
        and rsi_14_h4 is not None
        and not pd.isna(rsi_14_h4)
        and float(rsi_14_h4) < 50
        and int(row.get("macd_rising_h1", 0) or 0) == 0
        and rsi_14_h1 is not None
        and not pd.isna(rsi_14_h1)
        and float(rsi_14_h1) > 50
    )

    if long_ok:
        if rsi_14_h1 is not None and not pd.isna(rsi_14_h1) and float(rsi_14_h1) > 68:
            return "HOLD", "long_block_rsi"
        if bb_pct_h1 is not None and not pd.isna(bb_pct_h1) and float(bb_pct_h1) > 0.95:
            return "HOLD", "long_block_bb"
        return "LONG", "ok"

    if short_ok:
        if rsi_14_h1 is not None and not pd.isna(rsi_14_h1) and float(rsi_14_h1) < 40:
            return "HOLD", "short_block_rsi"
        if bb_pct_h1 is not None and not pd.isna(bb_pct_h1) and float(bb_pct_h1) < 0.10:
            return "HOLD", "short_block_bb"
        return "SHORT", "ok"

    return "HOLD", "no_setup"


def _simulate_symbol(
    symbol: str,
    margin: float,
    leverage: float,
    warmup: int = 300,
) -> tuple[list[Trade], dict]:
    h1 = _load_ohlc(ROOT / "data" / f"{symbol}_1h_10y.csv")
    h4 = _load_ohlc(ROOT / "data" / f"{symbol}_4h_10y.csv")
    d1 = _load_ohlc(ROOT / "data" / f"{symbol}_1d_10y.csv")
    m = _merge_mtf(h1, h4, d1)

    notional = margin * leverage
    trades: list[Trade] = []
    in_pos: str | None = None
    entry_i = 0
    entry = 0.0
    stop = 0.0
    target = 0.0
    last_sig_ms = 0

    highs = m["high"].values
    lows = m["low"].values
    opens = m["open"].values
    closes = m["close"].values
    times = m["datetime"]

    n = len(m)
    i = warmup
    while i < n:
        row = m.iloc[i]
        t_ms = int(pd.Timestamp(times.iloc[i]).timestamp() * 1000)

        if in_pos is None:
            state, _ = _signal_state(row)
            if state in ("LONG", "SHORT"):
                if t_ms - last_sig_ms < SIGNAL_COOLDOWN_MS:
                    i += 1
                    continue
                atr = row["atr_14_h1"]
                if atr is None or pd.isna(atr) or float(atr) <= 0:
                    i += 1
                    continue
                entry = float(row["close"])
                atr_f = float(atr)
                if state == "LONG":
                    stop = entry - ATR_SL_MULT * atr_f
                    risk = entry - stop
                    target = entry + RR_MIN * risk
                else:
                    stop = entry + ATR_SL_MULT * atr_f
                    risk = stop - entry
                    target = entry - RR_MIN * risk
                in_pos = state
                entry_i = i
                last_sig_ms = t_ms
            i += 1
            continue

        # Đang có vị thế: từ i trở đi tìm exit (i là bar sau entry)
        j = max(i, entry_i + 1)
        exit_reason = "eod"
        exit_price = float(closes[-1])
        exit_j = n - 1
        while j < n:
            o, hi, lo = float(opens[j]), float(highs[j]), float(lows[j])
            if in_pos == "LONG":
                if o <= stop:
                    exit_price = o
                    exit_j = j
                    exit_reason = "sl_gap_long"
                    break
                if o >= target:
                    exit_price = o
                    exit_j = j
                    exit_reason = "tp_gap_long"
                    break
                hit_sl = lo <= stop
                hit_tp = hi >= target
                if hit_sl and hit_tp:
                    exit_price = stop
                    exit_j = j
                    exit_reason = "sl_first_long"
                    break
                if hit_sl:
                    exit_price = stop
                    exit_j = j
                    exit_reason = "sl_long"
                    break
                if hit_tp:
                    exit_price = target
                    exit_j = j
                    exit_reason = "tp_long"
                    break
            else:
                if o >= stop:
                    exit_price = o
                    exit_j = j
                    exit_reason = "sl_gap_short"
                    break
                if o <= target:
                    exit_price = o
                    exit_j = j
                    exit_reason = "tp_gap_short"
                    break
                hit_sl = hi >= stop
                hit_tp = lo <= target
                if hit_sl and hit_tp:
                    exit_price = stop
                    exit_j = j
                    exit_reason = "sl_first_short"
                    break
                if hit_sl:
                    exit_price = stop
                    exit_j = j
                    exit_reason = "sl_short"
                    break
                if hit_tp:
                    exit_price = target
                    exit_j = j
                    exit_reason = "tp_short"
                    break
            if j - entry_i >= MAX_HOLD_BARS:
                exit_price = float(closes[j])
                exit_j = j
                exit_reason = "time_stop"
                break
            j += 1

        bars_held = exit_j - entry_i
        if in_pos == "LONG":
            pnl = notional * (exit_price - entry) / entry
        else:
            pnl = notional * (entry - exit_price) / entry
        pnl -= notional * FEE_ROUND_TRIP_PCT

        trades.append(
            Trade(
                symbol=symbol,
                side=in_pos,
                entry_time=str(times.iloc[entry_i]),
                exit_time=str(times.iloc[exit_j]),
                entry=entry,
                exit=exit_price,
                stop=stop,
                target=target,
                pnl_usd=pnl,
                bars_held=bars_held,
                exit_reason=exit_reason,
            )
        )
        in_pos = None
        i = exit_j + 1

    total_pnl = sum(t.pnl_usd for t in trades)
    wins = sum(1 for t in trades if t.pnl_usd > 0)
    summary = {
        "symbol": symbol,
        "trades": len(trades),
        "total_pnl_usd": total_pnl,
        "win_rate": wins / len(trades) if trades else 0.0,
        "margin": margin,
        "leverage": leverage,
        "notional_usd": notional,
    }
    return trades, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest MTF + cross x20 + margin cố định")
    ap.add_argument("--margin", type=float, default=MARGIN_USD)
    ap.add_argument("--leverage", type=float, default=LEVERAGE)
    ap.add_argument("--out", type=str, default="backtest_mtf_cross_trades.csv")
    args = ap.parse_args()

    all_trades: list[Trade] = []
    summaries = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        tr, s = _simulate_symbol(sym, args.margin, args.leverage)
        all_trades.extend(tr)
        summaries.append(s)
        print(f"\n=== {sym} ===")
        for k, v in s.items():
            print(f"  {k}: {v}")

    out_path = ROOT / args.out
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "symbol",
                "side",
                "entry_time",
                "exit_time",
                "entry",
                "exit",
                "stop",
                "target",
                "pnl_usd",
                "bars_held",
                "exit_reason",
            ]
        )
        for t in all_trades:
            w.writerow(
                [
                    t.symbol,
                    t.side,
                    t.entry_time,
                    t.exit_time,
                    f"{t.entry:.8f}",
                    f"{t.exit:.8f}",
                    f"{t.stop:.8f}",
                    f"{t.target:.8f}",
                    f"{t.pnl_usd:.4f}",
                    t.bars_held,
                    t.exit_reason,
                ]
            )
    print(f"\nĐã ghi {len(all_trades)} lệnh -> {out_path}")


if __name__ == "__main__":
    main()
