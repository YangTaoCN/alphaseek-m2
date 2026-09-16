#!/usr/bin/env python3
"""AlphaSeek-M2 entry point.

    python main.py                        # scan config/settings.yaml watchlist
    python main.py --tickers NVDA AMD     # ad-hoc scan
    python main.py --dry-run              # skip DeepSeek, rule-based plans only
    python main.py --no-notify            # terminal output only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Allow `python main.py` from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import __version__  # noqa: E402
from src.ai_advisor import AIAdvisor  # noqa: E402
from src.config import load_settings  # noqa: E402
from src.notifier import Notifier  # noqa: E402
from src.scanner import TechnicalScanner  # noqa: E402

log = logging.getLogger("alphaseek")


def setup_logging(log_dir: Path, level: str = "INFO", to_file: bool = True) -> Path | None:
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger("alphaseek")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path = None
    if to_file:
        log_path = log_dir / "alphaseek.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    return log_path


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="alphaseek-m2",
        description="Lightweight US stock screener + DeepSeek signal advisor for Apple Silicon Macs.",
    )
    parser.add_argument("--config", default=None, help="path to settings.yaml (default: config/settings.yaml)")
    parser.add_argument("--tickers", nargs="+", default=None, help="override the configured watchlist")
    parser.add_argument("--dry-run", action="store_true", help="skip DeepSeek calls; use rule-based plans")
    parser.add_argument("--no-notify", action="store_true", help="do not send desktop/telegram/webhook alerts")
    parser.add_argument("--min-confidence", type=float, default=None, help="override notifications.min_confidence")
    parser.add_argument(
        "--min-action",
        choices=["BUY", "WATCH", "SKIP"],
        default=None,
        help="only notify for reports at or above this action level",
    )
    parser.add_argument("--json", action="store_true", help="print a machine-readable JSON summary to stdout")
    parser.add_argument("--log-level", default="INFO", help="DEBUG | INFO | WARNING | ERROR")
    parser.add_argument("--version", action="version", version=f"AlphaSeek-M2 {__version__}")
    return parser.parse_args(argv)


ACTION_RANK = {"SKIP": 0, "WATCH": 1, "BUY": 2}


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = load_settings(args.config)
    if args.dry_run:
        settings["ai"]["dry_run"] = True

    log_path = setup_logging(settings.log_dir, args.log_level)
    started = datetime.now()
    log.info("AlphaSeek-M2 %s starting (pid=%d)", __version__, os.getpid())

    watchlist = args.tickers or settings.watchlist
    if not watchlist:
        log.error("Empty watchlist. Add tickers to config/settings.yaml or pass --tickers.")
        return 2

    # 1) local hard-rule filter ------------------------------------------
    scanner = TechnicalScanner(settings)
    signals = scanner.scan(watchlist)
    triggers = [s for s in signals if s.passed]

    if not signals:
        log.warning("No market data retrieved. Check your network connection / tickers.")
        return 1

    log.info(
        "Scan complete: %d/%d tickers passed the hard-rule filter.",
        len(triggers),
        len(signals),
    )

    # 2) cloud brain on survivors only -----------------------------------
    advisor = AIAdvisor(settings)
    notifier = Notifier(settings)

    min_confidence = (
        args.min_confidence
        if args.min_confidence is not None
        else float(settings.get("notifications.min_confidence", 6.0))
    )
    min_action = args.min_action or "WATCH"

    reports = []
    for signal in triggers:
        report = advisor.review(signal)
        print(report.render())
        reports.append(report)

    # 3) notify -----------------------------------------------------------
    delivered = []
    for report in reports:
        notify_worthy = (
            report.confidence >= min_confidence
            and ACTION_RANK.get(report.action, 0) >= ACTION_RANK.get(min_action, 1)
        )
        if args.no_notify:
            log.info("[NOTIFY] suppressed by --no-notify for %s.", report.ticker)
            continue
        if not notify_worthy:
            log.info(
                "[NOTIFY] skipped %s (%s, conf %.1f < %.1f).",
                report.ticker,
                report.action,
                report.confidence,
                min_confidence,
            )
            continue
        results = notifier.notify(report)
        delivered.append({"ticker": report.ticker, "channels": [str(r) for r in results]})

    if not triggers:
        summary = (
            f"No setups passed today. Scanned {len(signals)} tickers; "
            "tightest miss logged below."
        )
        closest = sorted(signals, key=lambda s: s.volume_surge, reverse=True)[:3]
        for sig in closest:
            log.info("[SUMMARY] %s", sig.one_line())

    # 4) persist ----------------------------------------------------------
    elapsed = (datetime.now() - started).total_seconds()
    report_doc = {
        "generated_at": started.isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 2),
        "watchlist": watchlist,
        "model": advisor.model,
        "dry_run": not advisor.enabled,
        "scanned": [s.to_dict() for s in signals],
        "triggers": [s.ticker for s in triggers],
        "reports": [r.to_dict() for r in reports],
        "delivered": delivered,
    }

    if settings.get("output.save_json_report", True):
        reports_dir = settings.log_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = started.strftime("%Y-%m-%d")
        out_path = reports_dir / f"{stamp}.json"
        out_path.write_text(json.dumps(report_doc, indent=2, default=str), encoding="utf-8")
        log.info("Report written to %s", out_path)

    if args.json:
        print(json.dumps(report_doc, indent=2, default=str))

    log.info(
        "Run finished in %.1fs: %d scanned, %d triggered, %d alerted.",
        elapsed,
        len(signals),
        len(triggers),
        len(delivered),
    )
    if log_path:
        log.debug("Log file: %s", log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
