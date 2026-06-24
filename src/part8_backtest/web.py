"""Real backtest results shaped for the web terminal's Backtest view.

``run_for_ui`` replays the SAME strategy/risk stack as the CLI backtester over a
short, coarse-timeframe window (so it returns within an HTTP request) and emits
a JSON payload the frontend renders directly — replacing the synthetic ``genBT``
demo with real numbers when a backend is connected.
"""
from __future__ import annotations

import bisect
from typing import Any

from ..part1_data.connector import timeframe_seconds
from .data import load_history
from .engine import run_backtest

_TF_MAP = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}


def run_for_ui(symbol: str = "BTC/USDT", timeframe: str = "1d",
               bars: int = 180, source: str = "mainnet") -> dict[str, Any]:
    tf = _TF_MAP.get(str(timeframe).lower(), str(timeframe).lower())
    tf_sec = timeframe_seconds(tf)
    bars = max(20, min(int(bars), 1_600_000))  # up to ~3y of 1m bars
    days = bars * tf_sec / 86400.0
    candles = load_history(symbol, days=days, timeframe=tf, source=source)
    candles = candles[-bars:]
    if len(candles) < 2:
        raise ValueError(f"not enough history for {symbol} {tf}")

    res = run_backtest(symbol, candles, timeframe=tf)
    eq = [v for _, v in res.equity_curve]
    c0 = candles[0].close or 1.0
    bh = [round(10000.0 * c.close / c0, 2) for c in candles][:len(eq)]

    peak = eq[0]
    dd = []
    for v in eq:
        peak = max(peak, v)
        dd.append(round((v - peak) / peak * 100, 2) if peak > 0 else 0.0)

    ts_list = [c.ts for c in candles]
    markers = []
    for t in res.trades:
        i = min(max(bisect.bisect_left(ts_list, t.ts), 0), len(candles) - 1)
        markers.append({"i": i, "side": t.side})

    m = res.metrics
    pf = m.get("profit_factor")
    stats = {
        "totalRet": m.get("total_return_pct", 0.0),
        "bhRet": m.get("buy_hold_return_pct", 0.0),
        "maxDd": -abs(m.get("max_drawdown_pct", 0.0)),
        "sharpe": m.get("sharpe", 0.0),
        "win": m.get("win_rate_pct", 0.0),
        "pf": pf if pf is not None else 0.0,
        "trades": m.get("num_trades", 0),
        "fees": round(m.get("fees_paid", 0.0), 2),
    }
    return {
        "symbol": symbol, "tf": timeframe, "bars": len(candles), "source": source,
        "candles": [[round(c.ts, 2), c.open, c.high, c.low, c.close,
                     round(float(getattr(c, "volume", 0.0) or 0.0), 4)] for c in candles],
        "equity": [round(x, 2) for x in eq],
        "bh": bh, "dd": dd, "markers": markers, "stats": stats,
    }
