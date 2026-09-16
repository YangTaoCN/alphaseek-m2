"""Data fetcher & technical indicator engine.

Runs entirely on-device: yfinance for daily OHLCV, vectorized pandas for
indicators. No LLM, no API credits, negligible CPU/battery cost on Apple
Silicon (a 7-ticker daily scan completes in a couple of seconds).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

log = logging.getLogger("alphaseek.scanner")


# ---------------------------------------------------------------------------
# Indicators (pure pandas — pandas-ta compatible when installed)
# ---------------------------------------------------------------------------
def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    out = 100 - (100 / (1 + rs))
    # if avg_loss == 0 the stock only went up -> RSI 100
    return out.fillna(100.0).where(avg_gain.notna(), other=pd.NA)


def true_range(frame: pd.DataFrame) -> pd.Series:
    prev_close = frame["Close"].shift(1)
    ranges = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - prev_close).abs(),
            (frame["Low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(frame).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    """Technical snapshot for one ticker after the hard-rule filter."""

    ticker: str
    price: float
    prev_close: float
    change_pct: float
    ema_fast: float
    ema_slow: float
    ema_gap_pct: float
    rsi: float
    volume: float
    avg_volume: float
    volume_surge: float
    atr: float
    avg_dollar_volume: float
    passed: bool = False
    reasons: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "SKIP"

    def one_line(self) -> str:
        return (
            f"[{self.status}] {self.ticker}: price={self.price:.2f} "
            f"rsi={self.rsi:.1f} vol={self.volume_surge:.2f}x "
            f"ema_gap={self.ema_gap_pct:+.2f}% chg={self.change_pct:+.2f}%"
        )


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------
class TechnicalScanner:
    """Fetch daily bars and evaluate hard technical rules."""

    def __init__(self, settings) -> None:
        self.settings = settings

    # -- data -------------------------------------------------------------
    def fetch_history(self, tickers: Iterable[str]) -> Dict[str, pd.DataFrame]:
        """Return {ticker: OHLCV DataFrame} for the requested symbols."""
        import yfinance as yf

        tickers = list(dict.fromkeys(tickers))
        if not tickers:
            return {}

        lookback = int(self.settings.get("indicators.lookback_days", 200))
        # calendar padding so we still get `lookback` trading bars
        period_days = int(lookback * 1.6) + 30
        log.info("Fetching daily market data for %d tickers...", len(tickers))

        raw = yf.download(
            tickers=" ".join(tickers),
            period=f"{period_days}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )

        frames: Dict[str, pd.DataFrame] = {}
        if raw is None or raw.empty:
            return frames

        if isinstance(raw.columns, pd.MultiIndex):
            for ticker in tickers:
                if ticker in raw.columns.get_level_values(0):
                    frame = raw[ticker].dropna(how="all")
                    if not frame.empty:
                        frames[ticker] = frame
        else:
            # single-ticker download returns flat columns
            frames[tickers[0]] = raw.dropna(how="all")

        missing = [t for t in tickers if t not in frames]
        if missing:
            log.warning("No data returned for: %s", ", ".join(missing))
        return frames

    # -- evaluation -------------------------------------------------------
    def evaluate(self, ticker: str, frame: pd.DataFrame) -> Optional[Signal]:
        cfg = self.settings.get("indicators", {})
        ema_fast_len = int(cfg.get("ema_fast", 20))
        ema_slow_len = int(cfg.get("ema_slow", 50))
        rsi_period = int(cfg.get("rsi_period", 14))
        rsi_min = float(cfg.get("rsi_min", 45))
        rsi_max = float(cfg.get("rsi_max", 68))
        vol_mult = float(cfg.get("volume_surge_multiplier", 1.2))
        min_dollar_vol = float(cfg.get("min_avg_dollar_volume", 0))

        min_bars = max(ema_slow_len, rsi_period) + 30
        if frame is None or len(frame.dropna()) < min_bars:
            log.warning("%s: insufficient history (%s bars)", ticker, 0 if frame is None else len(frame))
            return None

        frame = frame.dropna().copy()
        close = frame["Close"]
        volume = frame["Volume"]

        ema_fast = ema(close, ema_fast_len)
        ema_slow = ema(close, ema_slow_len)
        rsi_series = rsi(close, rsi_period)
        atr_series = atr(frame, rsi_period)

        price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        change_pct = (price / prev_close - 1) * 100 if prev_close else 0.0
        vol_today = float(volume.iloc[-1])
        # surge vs the 20 sessions *before* today (excludes today's spike)
        baseline_window = volume.iloc[-21:-1]
        avg_volume = float(baseline_window.mean()) if len(baseline_window) else float(volume.mean())
        volume_surge = vol_today / avg_volume if avg_volume else 0.0
        avg_dollar_volume = float((close.iloc[-21:-1] * volume.iloc[-21:-1]).mean()) if len(close) > 21 else price * avg_volume

        sig = Signal(
            ticker=ticker,
            price=price,
            prev_close=prev_close,
            change_pct=change_pct,
            ema_fast=float(ema_fast.iloc[-1]),
            ema_slow=float(ema_slow.iloc[-1]),
            ema_gap_pct=(float(ema_fast.iloc[-1]) / float(ema_slow.iloc[-1]) - 1) * 100
            if float(ema_slow.iloc[-1])
            else 0.0,
            rsi=float(rsi_series.iloc[-1]),
            volume=vol_today,
            avg_volume=avg_volume,
            volume_surge=volume_surge,
            atr=float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0.0,
            avg_dollar_volume=avg_dollar_volume,
        )

        # -- hard rules ---------------------------------------------------
        if sig.ema_fast <= sig.ema_slow:
            sig.rejections.append(f"EMA{ema_fast_len} <= EMA{ema_slow_len} (no bullish trend)")
        if price < sig.ema_slow:
            sig.rejections.append(f"price below EMA{ema_slow_len}")
        if not (rsi_min <= sig.rsi <= rsi_max):
            sig.rejections.append(f"RSI {sig.rsi:.1f} outside sweet-spot {rsi_min:g}-{rsi_max:g}")
        if sig.volume_surge < vol_mult:
            sig.rejections.append(f"volume surge {sig.volume_surge:.2f}x < {vol_mult:g}x")
        if min_dollar_vol and sig.avg_dollar_volume < min_dollar_vol:
            sig.rejections.append(f"avg dollar volume {sig.avg_dollar_volume/1e6:.1f}M below floor")

        sig.passed = not sig.rejections
        if sig.passed:
            sig.reasons = [
                f"EMA{ema_fast_len} > EMA{ema_slow_len} (+{sig.ema_gap_pct:.2f}% gap)",
                f"RSI {sig.rsi:.1f} inside {rsi_min:g}-{rsi_max:g} expansion zone",
                f"Volume surge {sig.volume_surge:.2f}x vs 20d average",
                f"Price above EMA{ema_slow_len} and EMA{ema_fast_len}",
            ]
        return sig

    def scan(self, tickers: Optional[Iterable[str]] = None) -> List[Signal]:
        tickers = list(tickers) if tickers else self.settings.watchlist
        frames = self.fetch_history(tickers)
        signals: List[Signal] = []
        for ticker in tickers:
            frame = frames.get(ticker)
            if frame is None:
                continue
            try:
                sig = self.evaluate(ticker, frame)
            except Exception as exc:  # keep one bad ticker from killing the scan
                log.error("%s: evaluation failed (%s)", ticker, exc)
                continue
            if sig is None:
                continue
            signals.append(sig)
            if sig.passed:
                log.info(
                    "[TRIGGER] %s passed technical filter: %s",
                    sig.ticker,
                    "; ".join(sig.reasons),
                )
            else:
                log.info(
                    "[SKIP] %s: rsi=%.1f vol=%.2fx ema_gap=%+.2f%% -> %s",
                    sig.ticker,
                    sig.rsi,
                    sig.volume_surge,
                    sig.ema_gap_pct,
                    ", ".join(sig.rejections),
                )
        return signals
