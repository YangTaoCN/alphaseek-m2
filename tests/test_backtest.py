"""Offline backtest tests (no network required).

Focus: no-lookahead guarantees, exit resolution and metric math.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import (  # noqa: E402
    Trade,
    _resolve_exit,
    build_report,
    max_drawdown_pct,
    simulate_ticker,
    summarize_trades,
)
from src.config import load_settings  # noqa: E402
from src.scanner import TechnicalScanner  # noqa: E402


@pytest.fixture()
def settings():
    s = load_settings()
    s["indicators"]["min_avg_dollar_volume"] = 0
    s["ai"]["dry_run"] = True
    return s


def make_frame(*, bars=200, spike_at: int | None = None, spike_mult=1.8, drift=0.35, seed=11):
    """Synthetic uptrend; optionally inject a volume spike on one bar."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, 1.1, bars).cumsum()
    close = pd.Series(90 + steps)
    volume = pd.Series(rng.integers(4_000_000, 6_000_000, bars), dtype="float64")
    if spike_at is not None:
        volume.iloc[spike_at] = volume.iloc[max(0, spike_at - 20) : spike_at].mean() * spike_mult

    frame = pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close + 1.2,
            "Low": close - 1.2,
            "Close": close,
            "Volume": volume,
        }
    )
    # Assign the index *after* construction; passing `index=` would realign the
    # RangeIndexed series and turn every cell into NaN.
    frame.index = pd.bdate_range("2023-01-02", periods=bars)
    return frame


def test_exit_prefers_gap_fill_over_stop_price():
    opens = np.array([100.0, 90.0, 91.0])
    highs = np.array([101.0, 92.0, 93.0])
    lows = np.array([99.0, 88.0, 89.0])
    closes = np.array([100.0, 91.0, 92.0])
    idx, price, reason = _resolve_exit(opens, highs, lows, closes, 1, 95.0, 120.0, 5, 3)
    assert reason == "stop"
    assert price == 90.0  # gap down through the stop fills at the open, not at 95


def test_exit_stop_wins_when_bar_touches_both():
    opens = np.array([100.0, 100.0])
    highs = np.array([101.0, 130.0])
    lows = np.array([99.0, 90.0])
    closes = np.array([100.0, 100.0])
    _, price, reason = _resolve_exit(opens, highs, lows, closes, 1, 95.0, 120.0, 5, 2)
    assert reason == "stop"
    assert price == 95.0


def test_exit_timeout_uses_last_close():
    opens = np.array([100.0, 100.0, 100.0, 100.0])
    highs = np.array([100.0, 101.0, 101.0, 101.0])
    lows = np.array([100.0, 99.0, 99.0, 99.5])
    closes = np.array([100.0, 100.5, 100.5, 100.8])
    idx, price, reason = _resolve_exit(opens, highs, lows, closes, 1, 95.0, 120.0, 2, 4)
    assert reason == "timeout"
    assert price == pytest.approx(100.5)


def test_target_hit_after_entry():
    opens = np.array([100.0, 100.0, 119.0])
    highs = np.array([100.0, 101.0, 121.0])
    lows = np.array([100.0, 99.5, 118.0])
    closes = np.array([100.0, 100.5, 120.5])
    idx, price, reason = _resolve_exit(opens, highs, lows, closes, 1, 95.0, 120.0, 5, 3)
    assert reason == "target"
    assert price == 120.0


def test_target_gap_up_fills_at_open():
    """A gap through the target fills at the open (better than the limit)."""
    opens = np.array([100.0, 100.0, 130.0])
    highs = np.array([100.0, 101.0, 131.0])
    lows = np.array([100.0, 99.5, 129.0])
    closes = np.array([100.0, 100.5, 130.5])
    _, price, reason = _resolve_exit(opens, highs, lows, closes, 1, 95.0, 120.0, 5, 3)
    assert reason == "target"
    assert price == 130.0


def test_simulate_ticker_entry_is_next_bar_open(settings):
    """No lookahead: entry price must equal the open of the bar after the signal."""
    frame = make_frame(spike_at=150, spike_mult=2.4)
    scanner = TechnicalScanner(settings)
    result = simulate_ticker(scanner, "TEST", frame)
    trades = result["trades"]
    assert trades, "expected at least one triggered trade"

    for trade in trades:
        signal_i = frame.index.get_loc(pd.Timestamp(trade.signal_date))
        entry_i = frame.index.get_loc(pd.Timestamp(trade.entry_date))
        assert entry_i == signal_i + 1
        assert trade.entry_price == pytest.approx(float(frame["Open"].iloc[entry_i]), rel=1e-6)
        assert trade.stop < trade.entry_price < trade.target
        # ATR-anchored levels: target = entry + 1.5*3.0*ATR
        assert trade.target - trade.entry_price == pytest.approx(
            1.5 * 3.0 * trade.atr, rel=1e-3
        )


def test_simulate_ticker_has_no_overlapping_positions(settings):
    frame = make_frame(spike_at=150, spike_mult=2.4)
    scanner = TechnicalScanner(settings)
    trades = simulate_ticker(scanner, "TEST", frame)["trades"]
    for prev, nxt in zip(trades, trades[1:]):
        prev_exit = frame.index.get_loc(pd.Timestamp(prev.exit_date))
        next_signal = frame.index.get_loc(pd.Timestamp(nxt.signal_date))
        assert next_signal > prev_exit


def test_summarize_trades_metrics():
    trades = [
        Trade("T", "2023-01-02", "2023-01-03", 100, 95, 115, 3, "2023-01-06", 115, "target", 4, 3.0, 15.0),
        Trade("T", "2023-02-01", "2023-02-02", 100, 95, 115, 3, "2023-02-06", 95, "stop", 3, -1.0, -5.0),
        Trade("T", "2023-03-01", "2023-03-02", 100, 95, 115, 3, "2023-03-10", 102, "timeout", 8, 0.4, 2.0),
    ]
    stats = summarize_trades("T", trades, buy_hold_pct=12.5)
    assert stats.trades == 3
    assert stats.wins == 2
    assert stats.losses == 1
    assert stats.timeouts == 1
    assert stats.win_rate == pytest.approx(66.7, abs=0.05)
    assert stats.total_r == pytest.approx(2.4)
    assert stats.profit_factor == pytest.approx(3.4 / 1.0, abs=0.01)
    assert stats.buy_hold_pct == 12.5


def test_max_drawdown_math():
    assert max_drawdown_pct([100, 120, 60]) == pytest.approx(50.0)
    assert max_drawdown_pct([100, 110, 121]) == 0.0


def test_build_report_aggregates():
    per_ticker = {
        "AAA": {
            "ticker": "AAA",
            "trades": [
                Trade("AAA", "2023-01-02", "2023-01-03", 100, 95, 115, 3, "2023-01-06", 115, "target", 4, 3.0, 15.0)
            ],
            "equity_curve": [],
            "buy_hold_pct": 20.0,
            "first_date": "2023-01-02",
            "last_date": "2023-06-01",
        },
        "BBB": {"ticker": "BBB", "trades": [], "equity_curve": [], "buy_hold_pct": -5.0},
    }
    report = build_report(per_ticker, stop_atr=1.5, reward_ratio=3.0, max_hold=10, period="5y")
    assert report["portfolio"]["trades"] == 1
    assert report["benchmark_buy_hold_pct"] == pytest.approx(7.5)
    assert report["window"]["start"] == "2023-01-02"
    assert len(report["per_ticker"]) == 2
    assert len(report["trades"]) == 1
