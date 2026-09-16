"""Offline rule-engine tests (no network, no API key required).

    pytest -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_advisor import AIAdvisor, _extract_json  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.scanner import TechnicalScanner, ema, rsi  # noqa: E402


def make_frame(*, trend="up", last_volume_multiplier=1.5, bars=140) -> pd.DataFrame:
    """Synthetic OHLCV frame with a controllable trend and volume spike."""
    rng = np.random.default_rng(7)
    drift = {"up": 0.35, "flat": 0.0, "down": -0.4}[trend]
    steps = rng.normal(drift, 1.1, bars).cumsum()
    close = pd.Series(80 + steps)
    volume = pd.Series(rng.integers(4_000_000, 6_000_000, bars), dtype="float64")
    volume.iloc[-1] = volume.iloc[-21:-1].mean() * last_volume_multiplier

    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close + 1.2,
            "Low": close - 1.2,
            "Close": close,
            "Volume": volume,
        }
    )


@pytest.fixture()
def settings():
    s = load_settings()
    s["indicators"]["min_avg_dollar_volume"] = 0
    s["ai"]["dry_run"] = True
    return s


def test_indicators_shape():
    series = pd.Series(np.linspace(10, 40, 60))
    assert len(ema(series, 20)) == len(series)
    assert ema(series, 20).iloc[-1] > ema(series, 50).iloc[-1]
    values = rsi(series, 14).dropna()
    assert values.between(0, 100).all()
    assert values.iloc[-1] == pytest.approx(100.0, abs=0.01)


def test_uptrend_triggers(settings):
    scanner = TechnicalScanner(settings)
    signal = scanner.evaluate("TEST", make_frame(trend="up", last_volume_multiplier=1.6))
    assert signal is not None
    assert signal.ema_fast > signal.ema_slow
    assert signal.volume_surge > 1.2
    assert signal.passed, signal.rejections


def test_downtrend_rejected(settings):
    scanner = TechnicalScanner(settings)
    signal = scanner.evaluate("TEST", make_frame(trend="down", last_volume_multiplier=1.6))
    assert signal is not None
    assert not signal.passed
    assert any("EMA" in r for r in signal.rejections)


def test_low_volume_rejected(settings):
    scanner = TechnicalScanner(settings)
    signal = scanner.evaluate("TEST", make_frame(trend="up", last_volume_multiplier=0.7))
    assert not signal.passed
    assert any("volume surge" in r for r in signal.rejections)


def test_insufficient_history_returns_none(settings):
    scanner = TechnicalScanner(settings)
    assert scanner.evaluate("TEST", make_frame(trend="up", bars=30)) is None


def test_rule_based_advisor_levels(settings):
    scanner = TechnicalScanner(settings)
    signal = scanner.evaluate("TEST", make_frame(trend="up", last_volume_multiplier=1.8))
    report = AIAdvisor(settings).review(signal)
    assert report.source == "rule-based"
    assert report.stop_loss < report.entry < report.target
    assert report.risk_reward >= 1.8
    assert 0 <= report.confidence <= 10


def test_extract_json_handles_fences_and_prose():
    assert _extract_json('{"action": "BUY"}')["action"] == "BUY"
    assert _extract_json('```json\n{"action": "WATCH"}\n```')["action"] == "WATCH"
    assert _extract_json('Sure!\n{"confidence": 7.5}\nHope that helps.')["confidence"] == 7.5
    with pytest.raises(ValueError):
        _extract_json("no json here")
