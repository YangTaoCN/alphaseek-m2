"""Walk-forward backtest for the AlphaSeek-M2 hard-rule screen.

Design goals
------------
1. **Same rules as production.** Every bar is evaluated through
   `TechnicalScanner.evaluate` on a *truncated* frame, so the live filter and
   the backtest can never drift apart.
2. **No lookahead.** Bar *i* is evaluated with data up to and including bar *i*;
   the trade is filled at the **open of bar i+1**. Indicators, ATR and volume
   baselines are all shifted implicitly by the truncation.
3. **Production-shaped risk.** Levels mirror the deterministic fallback plan in
   `ai_advisor._rule_based`: stop = 1.5 x ATR14, target = stop x `reward_ratio`
   (default 3.0 -> R:R 3:1), max hold 10 bars, one position per ticker at a
   time (no pyramiding, no overlapping entries).

Outputs trade-level detail plus per-ticker and aggregate statistics
(win rate, expectancy in R, profit factor, max drawdown) and a buy & hold
benchmark over the identical window.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .scanner import TechnicalScanner

log = logging.getLogger("alphaseek.backtest")

DEFAULT_STOP_ATR = 1.5
DEFAULT_REWARD_RATIO = 3.0
DEFAULT_MAX_HOLD = 10
DEFAULT_RISK_PCT = 0.01


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    ticker: str
    signal_date: str
    entry_date: str
    entry_price: float
    stop: float
    target: float
    atr: float
    exit_date: str
    exit_price: float
    exit_reason: str  # target | stop | timeout
    bars_held: int
    r_multiple: float
    return_pct: float

    @property
    def is_win(self) -> bool:
        return self.r_multiple > 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TickerStats:
    ticker: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    win_rate: float = 0.0
    avg_r: float = 0.0
    expectancy_r: float = 0.0
    total_r: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    buy_hold_pct: float = 0.0
    avg_bars_held: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
def simulate_ticker(
    scanner: TechnicalScanner,
    ticker: str,
    frame: pd.DataFrame,
    *,
    stop_atr: float = DEFAULT_STOP_ATR,
    reward_ratio: float = DEFAULT_REWARD_RATIO,
    max_hold: int = DEFAULT_MAX_HOLD,
    risk_pct: float = DEFAULT_RISK_PCT,
    starting_equity: float = 100_000.0,
) -> Dict[str, Any]:
    """Replay one ticker bar by bar. Returns trades + equity curve."""
    frame = frame.dropna().copy()
    n = len(frame)
    cfg = scanner.settings.get("indicators", {})
    min_bars = max(int(cfg.get("ema_slow", 50)), int(cfg.get("rsi_period", 14))) + 30

    trades: List[Trade] = []
    if n < min_bars + 2:
        return {"ticker": ticker, "trades": trades, "equity_curve": [], "buy_hold_pct": 0.0}

    equity = starting_equity
    equity_curve: List[Dict[str, Any]] = [
        {"date": _stamp(frame.index[min_bars]), "equity": equity}
    ]

    opens = frame["Open"].to_numpy()
    highs = frame["High"].to_numpy()
    lows = frame["Low"].to_numpy()
    closes = frame["Close"].to_numpy()
    index = frame.index

    i = min_bars
    while i < n - 1:
        signal = scanner.evaluate(ticker, frame.iloc[: i + 1])
        if signal is None or not signal.passed:
            i += 1
            continue

        entry_i = i + 1
        entry_price = float(opens[entry_i])
        if not entry_price or entry_price <= 0:
            i += 1
            continue

        atr = signal.atr or entry_price * 0.02
        stop = entry_price - stop_atr * atr
        target = entry_price + stop_atr * reward_ratio * atr
        if stop <= 0 or stop >= entry_price:
            i += 1
            continue

        exit_i, exit_price, reason = _resolve_exit(
            opens, highs, lows, closes, entry_i, stop, target, max_hold, n
        )

        r_multiple = (exit_price - entry_price) / (entry_price - stop)
        trades.append(
            Trade(
                ticker=ticker,
                signal_date=_stamp(index[i]),
                entry_date=_stamp(index[entry_i]),
                entry_price=round(entry_price, 4),
                stop=round(stop, 4),
                target=round(target, 4),
                atr=round(float(atr), 4),
                exit_date=_stamp(index[exit_i]),
                exit_price=round(exit_price, 4),
                exit_reason=reason,
                bars_held=int(exit_i - entry_i + 1),
                r_multiple=round(r_multiple, 4),
                return_pct=round((exit_price / entry_price - 1) * 100, 4),
            )
        )

        equity *= 1 + risk_pct * r_multiple
        equity_curve.append({"date": _stamp(index[exit_i]), "equity": round(equity, 2)})
        i = exit_i + 1  # one position per ticker at a time

    buy_hold_ref_i = min_bars
    buy_hold_pct = (closes[-1] / closes[buy_hold_ref_i] - 1) * 100 if closes[buy_hold_ref_i] else 0.0

    return {
        "ticker": ticker,
        "trades": trades,
        "equity_curve": equity_curve,
        "buy_hold_pct": round(float(buy_hold_pct), 2),
        "first_date": _stamp(index[buy_hold_ref_i]),
        "last_date": _stamp(index[-1]),
        "bars": n,
    }


def _resolve_exit(
    opens,
    highs,
    lows,
    closes,
    entry_i: int,
    stop: float,
    target: float,
    max_hold: int,
    n: int,
) -> tuple[int, float, str]:
    """First-touch exit logic. Gaps fill at the open; stop wins ties."""
    last_i = min(entry_i + max_hold - 1, n - 1)
    for j in range(entry_i, last_i + 1):
        if opens[j] <= stop:
            return j, float(opens[j]), "stop"
        if opens[j] >= target:
            return j, float(opens[j]), "target"
        if lows[j] <= stop:
            return j, stop, "stop"
        if highs[j] >= target:
            return j, target, "target"
    return last_i, float(closes[last_i]), "timeout"


def _stamp(value) -> str:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:  # pragma: no cover - defensive
        return str(value)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def summarize_trades(ticker: str, trades: Sequence[Trade], buy_hold_pct: float = 0.0) -> TickerStats:
    stats = TickerStats(ticker=ticker, buy_hold_pct=round(buy_hold_pct, 2))
    if not trades:
        return stats

    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]

    stats.trades = len(trades)
    stats.wins = len(wins)
    stats.losses = len([t for t in trades if t.r_multiple <= 0 and t.exit_reason != "timeout"])
    stats.timeouts = len([t for t in trades if t.exit_reason == "timeout"])
    stats.win_rate = round(len(wins) / len(trades) * 100, 1)
    stats.avg_r = round(sum(rs) / len(rs), 3)
    stats.expectancy_r = stats.avg_r
    stats.total_r = round(sum(rs), 2)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    stats.profit_factor = round(gross_win / gross_loss, 2) if gross_loss else float("inf")
    stats.avg_bars_held = round(sum(t.bars_held for t in trades) / len(trades), 1)
    stats.max_drawdown_pct = round(max_drawdown_pct(_equity_from_trades(trades)), 2)
    return stats


def _equity_from_trades(trades: Sequence[Trade], risk_pct: float = DEFAULT_RISK_PCT) -> List[float]:
    equity = 100_000.0
    curve = [equity]
    for trade in sorted(trades, key=lambda t: t.exit_date):
        equity *= 1 + risk_pct * trade.r_multiple
        curve.append(equity)
    return curve


def max_drawdown_pct(curve: Sequence[float]) -> float:
    peak = float("-inf")
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak * 100)
    return abs(worst)


def build_report(
    per_ticker: Dict[str, Dict[str, Any]],
    *,
    stop_atr: float,
    reward_ratio: float,
    max_hold: int,
    period: str,
) -> Dict[str, Any]:
    """Aggregate per-ticker results into a portfolio-level report."""
    all_trades: List[Trade] = []
    ticker_stats: List[TickerStats] = []
    for ticker, result in per_ticker.items():
        trades = result["trades"]
        all_trades.extend(trades)
        ticker_stats.append(summarize_trades(ticker, trades, result.get("buy_hold_pct", 0.0)))

    overall = summarize_trades("PORTFOLIO", all_trades)
    portfolio_curve = _equity_from_trades(all_trades)
    overall.max_drawdown_pct = round(max_drawdown_pct(portfolio_curve), 2)

    bench = [s.buy_hold_pct for s in ticker_stats]
    first_dates = [r.get("first_date") for r in per_ticker.values() if r.get("first_date")]
    last_dates = [r.get("last_date") for r in per_ticker.values() if r.get("last_date")]

    return {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "period": period,
        "parameters": {
            "stop_atr": stop_atr,
            "reward_ratio": reward_ratio,
            "max_hold_bars": max_hold,
            "risk_per_trade_pct": DEFAULT_RISK_PCT * 100,
        },
        "window": {
            "start": min(first_dates) if first_dates else None,
            "end": max(last_dates) if last_dates else None,
        },
        "portfolio": overall.to_dict(),
        "portfolio_equity_curve": portfolio_curve,
        "benchmark_buy_hold_pct": round(sum(bench) / len(bench), 2) if bench else 0.0,
        "per_ticker": [s.to_dict() for s in ticker_stats],
        "trades": [t.to_dict() for t in all_trades],
    }


def render_markdown(report: Dict[str, Any], *, max_trades: int = 20) -> str:
    p = report["portfolio"]
    params = report["parameters"]
    window = report["window"]
    lines: List[str] = []
    lines.append("# AlphaSeek-M2 — walk-forward backtest")
    lines.append("")
    lines.append(
        f"Window: **{window.get('start')} → {window.get('end')}** ({report['period']}) · "
        f"stop {params['stop_atr']}xATR · target {params['reward_ratio']}x risk · "
        f"max hold {params['max_hold_bars']} bars · risk {params['risk_per_trade_pct']}%/trade"
    )
    lines.append("")
    lines.append("## Portfolio")
    lines.append("")
    lines.append(f"- Trades: **{p['trades']}** ({p['wins']}W / {p['losses']}L / {p['timeouts']} timeout)")
    lines.append(f"- Win rate: **{p['win_rate']}%**")
    lines.append(f"- Expectancy: **{p['expectancy_r']}R** per trade · total {p['total_r']}R")
    pf = "∞" if p["profit_factor"] == float("inf") else p["profit_factor"]
    lines.append(f"- Profit factor: **{pf}** · max drawdown **{p['max_drawdown_pct']}%** (1% risk/trade model)")
    lines.append(f"- Avg hold: {p['avg_bars_held']} bars")
    lines.append(
        f"- Buy & hold benchmark (equal-weight watchlist): **{report['benchmark_buy_hold_pct']}%**"
    )
    lines.append("")
    lines.append("## Per ticker")
    lines.append("")
    lines.append("| Ticker | Trades | Win% | Avg R | Total R | PF | MaxDD% | B&H% |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for s in report["per_ticker"]:
        pf = "∞" if s["profit_factor"] == float("inf") else s["profit_factor"]
        lines.append(
            f"| {s['ticker']} | {s['trades']} | {s['win_rate']} | {s['avg_r']} | "
            f"{s['total_r']} | {pf} | {s['max_drawdown_pct']} | {s['buy_hold_pct']} |"
        )
    lines.append("")

    trades = report["trades"]
    if trades:
        lines.append(f"## Trade log ({len(trades)} trades, showing first {min(max_trades, len(trades))})")
        lines.append("")
        lines.append("| Ticker | Signal | Entry | Exit | Reason | Bars | R | Ret% |")
        lines.append("| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |")
        for t in trades[:max_trades]:
            lines.append(
                f"| {t['ticker']} | {t['signal_date']} | {t['entry_price']:.2f} "
                f"({t['entry_date']}) | {t['exit_price']:.2f} ({t['exit_date']}) | "
                f"{t['exit_reason']} | {t['bars_held']} | {t['r_multiple']:+.2f} | {t['return_pct']:+.2f} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def fetch_history(tickers: Iterable[str], period: str = "5y") -> Dict[str, pd.DataFrame]:
    import yfinance as yf

    tickers = list(dict.fromkeys(tickers))
    raw = yf.download(
        tickers=" ".join(tickers),
        period=period,
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
        frames[tickers[0]] = raw.dropna(how="all")
    missing = [t for t in tickers if t not in frames]
    if missing:
        log.warning("No data returned for: %s", ", ".join(missing))
    return frames


def run_backtest(
    settings,
    tickers: Optional[Iterable[str]] = None,
    *,
    period: str = "5y",
    stop_atr: float = DEFAULT_STOP_ATR,
    reward_ratio: float = DEFAULT_REWARD_RATIO,
    max_hold: int = DEFAULT_MAX_HOLD,
    frames: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, Any]:
    tickers = list(tickers) if tickers else settings.watchlist
    frames = frames if frames is not None else fetch_history(tickers, period)
    scanner = TechnicalScanner(settings)

    per_ticker: Dict[str, Dict[str, Any]] = {}
    for ticker in tickers:
        frame = frames.get(ticker)
        if frame is None or frame.empty:
            continue
        per_ticker[ticker] = simulate_ticker(
            scanner,
            ticker,
            frame,
            stop_atr=stop_atr,
            reward_ratio=reward_ratio,
            max_hold=max_hold,
        )

    return build_report(
        per_ticker,
        stop_atr=stop_atr,
        reward_ratio=reward_ratio,
        max_hold=max_hold,
        period=period,
    )
