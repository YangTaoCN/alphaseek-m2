#!/usr/bin/env python3
"""AlphaSeek-M2 walk-forward backtest entry point.

    python backtest.py                       # 5y, config watchlist, 1.5xATR stop / 3:1 R
    python backtest.py --period 3y
    python backtest.py --tickers NVDA AMD
    python backtest.py --stop-atr 1.5 --reward-ratio 2 --max-hold 10
    python backtest.py --json                # machine-readable summary on stdout
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import __version__  # noqa: E402
from src.backtest import render_markdown, run_backtest  # noqa: E402
from src.config import load_settings  # noqa: E402

log = logging.getLogger("alphaseek.backtest.cli")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="alphaseek-m2-backtest",
        description="Walk-forward backtest of the AlphaSeek-M2 hard-rule screen.",
    )
    parser.add_argument("--config", default=None, help="path to settings.yaml")
    parser.add_argument("--tickers", nargs="+", default=None, help="override the configured watchlist")
    parser.add_argument("--period", default="5y", help="yfinance period, e.g. 1y / 3y / 5y / 10y")
    parser.add_argument("--stop-atr", type=float, default=1.5, help="stop distance in ATR (default 1.5)")
    parser.add_argument("--reward-ratio", type=float, default=3.0, help="target as a multiple of risk (default 3.0)")
    parser.add_argument("--max-hold", type=int, default=10, help="max bars in a trade before a timeout exit")
    parser.add_argument("--json", action="store_true", help="print the full JSON report to stdout")
    parser.add_argument("--out", default=None, help="write the markdown report to this path")
    parser.add_argument("--log-level", default="WARNING", help="DEBUG | INFO | WARNING | ERROR")
    parser.add_argument("--version", action="version", version=f"AlphaSeek-M2 {__version__}")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )
    settings = load_settings(args.config)

    report = run_backtest(
        settings,
        args.tickers,
        period=args.period,
        stop_atr=args.stop_atr,
        reward_ratio=args.reward_ratio,
        max_hold=args.max_hold,
    )

    markdown = render_markdown(report)
    print(markdown)

    stamp = datetime.now().strftime("%Y-%m-%d")
    out_dir = settings.log_dir / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = Path(args.out) if args.out else out_dir / f"{stamp}.md"
    md_path.write_text(markdown, encoding="utf-8")
    json_path = out_dir / f"{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log.info("Reports written to %s and %s", md_path, json_path)

    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "trades"}, indent=2, default=str))

    if not report["trades"]:
        print("\n(no trades triggered in this window)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
