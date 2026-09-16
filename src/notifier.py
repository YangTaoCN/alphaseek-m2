"""macOS notification & webhook dispatcher.

Uses native AppleScript (`display notification`) so alerts show up in
Notification Center with no browser tab, daemon, or Docker container running.
Telegram and a generic JSON webhook are optional.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

import requests

log = logging.getLogger("alphaseek.notifier")

MAX_TITLE = 120
MAX_BODY = 500


@dataclass
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - logging only
        return f"{self.channel}={'ok' if self.ok else 'fail'}{' (' + self.detail + ')' if self.detail else ''}"


def _format_report(report) -> str:
    rr = report.risk_reward
    parts = [
        f"{report.action} · confidence {report.confidence:.1f}/10",
        f"Entry ${report.entry:.2f}",
        f"Stop ${report.stop_loss:.2f}",
        f"Target ${report.target:.2f} (R:R {rr:.1f}:1)",
    ]
    if report.rationale:
        parts.append(report.rationale)
    return "\n".join(parts)


class Notifier:
    def __init__(self, settings) -> None:
        cfg = settings.get("notifications", {})
        self.macos_desktop = bool(cfg.get("macos_desktop", True))
        self.telegram_token = str(cfg.get("telegram_bot_token") or "").strip()
        self.telegram_chat_id = str(cfg.get("telegram_chat_id") or "").strip()
        self.webhook_url = str(cfg.get("webhook_url") or "").strip()
        self.timeout = 15

    # -- channels ---------------------------------------------------------
    def notify(self, report, extra_lines: Optional[List[str]] = None) -> List[DeliveryResult]:
        """Send one signal report to every enabled channel."""
        title = f"{report.ticker} · {report.action} ({report.confidence:.1f}/10)"
        body = _format_report(report)
        if extra_lines:
            body += "\n" + "\n".join(extra_lines)

        results = [
            self._macos_desktop(title, body),
            self._telegram(title, body),
            self._webhook(report, title, body),
        ]
        return [r for r in results if r is not None]

    def send_summary(self, summary: str, title: str = "AlphaSeek-M2 scan") -> List[DeliveryResult]:
        results = [
            self._macos_desktop(title, summary),
            self._telegram(title, summary),
        ]
        return [r for r in results if r is not None]

    # -- implementation ---------------------------------------------------
    def _macos_desktop(self, title: str, body: str) -> Optional[DeliveryResult]:
        if not self.macos_desktop:
            return None
        if platform.system() != "Darwin" or not shutil.which("osascript"):
            log.info("[NOTIFY] macOS notification skipped (not on macOS).")
            return DeliveryResult("macos", False, "unsupported platform")

        script = (
            'display notification "{}" with title "{}" sound name "Glass"'.format(
                _applescript_escape(body[:MAX_BODY]), _applescript_escape(title[:MAX_TITLE])
            )
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                timeout=10,
            )
            log.info("[NOTIFY] Native macOS notification pushed (%s).", title)
            return DeliveryResult("macos", True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode(errors="ignore").strip()
            log.error("[NOTIFY] macOS notification failed: %s", detail)
            return DeliveryResult("macos", False, detail)
        except Exception as exc:
            log.error("[NOTIFY] macOS notification error: %s", exc)
            return DeliveryResult("macos", False, str(exc))

    def _telegram(self, title: str, body: str) -> Optional[DeliveryResult]:
        if not (self.telegram_token and self.telegram_chat_id):
            return None
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": f"*{title}*\n{body}",
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            log.info("[NOTIFY] Telegram alert sent.")
            return DeliveryResult("telegram", True)
        except Exception as exc:
            log.error("[NOTIFY] Telegram failed: %s", exc)
            return DeliveryResult("telegram", False, str(exc))

    def _webhook(self, report, title: str, body: str) -> Optional[DeliveryResult]:
        if not self.webhook_url:
            return None
        payload = {
            "text": f"{title}\n{body}",
            "title": title,
            "body": body,
            "report": report.to_dict() if hasattr(report, "to_dict") else None,
        }
        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload, default=str),
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            log.info("[NOTIFY] Webhook delivered.")
            return DeliveryResult("webhook", True)
        except Exception as exc:
            log.error("[NOTIFY] Webhook failed: %s", exc)
            return DeliveryResult("webhook", False, str(exc))


def _applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
