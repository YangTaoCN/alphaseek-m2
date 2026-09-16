"""Configuration loading for AlphaSeek-M2.

Resolution order (later wins):
  1. config/settings.yaml defaults
  2. environment variables (optionally loaded from a project-root .env)
  3. CLI overrides applied in main.py
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"

DEFAULTS: Dict[str, Any] = {
    "watchlist": ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "SPY", "QQQ"],
    "indicators": {
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_period": 14,
        "rsi_min": 45,
        "rsi_max": 68,
        "volume_surge_multiplier": 1.2,
        "lookback_days": 200,
        "min_avg_dollar_volume": 20_000_000,
    },
    "ai": {
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "temperature": 0.2,
        "max_tokens": 1200,
        "timeout_seconds": 90,
        "dry_run": False,
    },
    "notifications": {
        "macos_desktop": True,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "webhook_url": "",
        "min_confidence": 6.0,
    },
    "output": {
        "log_dir": "logs",
        "save_json_report": True,
    },
}

_ENV_OVERRIDES = {
    "DEEPSEEK_MODEL": ("ai", "model"),
    "DEEPSEEK_BASE_URL": ("ai", "base_url"),
    "TELEGRAM_BOT_TOKEN": ("notifications", "telegram_bot_token"),
    "TELEGRAM_CHAT_ID": ("notifications", "telegram_chat_id"),
    "WEBHOOK_URL": ("notifications", "webhook_url"),
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_dotenv() -> None:
    """Load .env without hard-depending on python-dotenv."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class Settings:
    """Thin dict-backed settings object with dotted access."""

    def __init__(self, data: Dict[str, Any], config_path: Path | None = None) -> None:
        self._data = data
        self.config_path = config_path

    # -- access -----------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def as_dict(self) -> Dict[str, Any]:
        return self._data

    @property
    def watchlist(self) -> list[str]:
        return [str(t).strip().upper() for t in self._data.get("watchlist", []) if str(t).strip()]

    @property
    def api_key(self) -> str:
        return os.environ.get("DEEPSEEK_API_KEY", "").strip()

    @property
    def log_dir(self) -> Path:
        path = Path(self.get("output.log_dir", "logs"))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    """Load YAML config, merge env overrides, return a Settings object."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    file_data: Dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            file_data = yaml.safe_load(handle) or {}
    else:
        file_data = {}

    data = _deep_merge(DEFAULTS, file_data)

    _load_dotenv()
    for env_key, (section, field) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_key, "").strip()
        if value:
            data.setdefault(section, {})[field] = value

    return Settings(data, config_path=path)
