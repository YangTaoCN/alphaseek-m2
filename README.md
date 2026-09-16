# AlphaSeek-M2 📈

> A lightweight, low-power US stock screening & AI-assisted trading signal system tailored for Apple Silicon (MacBook Air / Pro) and powered by **DeepSeek API**.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![macOS Compatible](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-black.svg)]()

---

## 💡 Overview

Running heavy trading frameworks and local multi-billion-parameter LLMs locally on fanless machines like the **MacBook Air M2** can lead to rapid thermal throttling and heavy swap memory usage.

**AlphaSeek-M2** solves this with a **hybrid edge-cloud architecture**:

1. **Local Edge (MacBook Air M2)**: Fast, native, vectorized indicator calculations (`pandas` + `yfinance`, with `pandas-ta` supported when installed) with virtually zero CPU/battery drain.
2. **Cloud Brain (DeepSeek API)**: Deep reasoning via `deepseek-chat` or `deepseek-reasoner` to evaluate risk-reward ratios, stop-loss positions, and momentum confirmation only when technical triggers are met.
3. **Native Alerting**: Instant desktop notifications via macOS `osascript` or Telegram Bot without needing open browser tabs or Docker containers.

A 7-ticker daily scan finishes in **under 2 seconds** on an M2 Air, with **zero** API calls unless a setup actually triggers.

---

## 🚀 Key Features

- ⚡ **Optimized for M-Series Macs**: Zero background heating, instantaneous mathematical scans.
- 🎯 **Rule-First Strategy**: Strict hard technical rules (EMA crossovers, Volume surge, RSI sweet-spots) filter out 98% of noise before touching API credits.
- 🧠 **DeepSeek Reasoning Review**: Evaluates signal validity, calculates precise entry/stop-loss/take-profit targets, and detects sentiment red flags — with strict JSON output and a deterministic rule-based fallback if the API is down or out of balance.
- 🔔 **Native macOS Integration**: Direct push notifications via native AppleScript (`display notification`).
- ⏰ **Automated Scheduling**: Ready-to-use macOS `launchd` / `cron` configurations for pre-market and market-close execution.
- 🧾 **Auditable**: Every run appends to `logs/alphaseek.log` and writes a machine-readable `logs/reports/YYYY-MM-DD.json`.

---

## 📂 Project Structure

```text
alphaseek-m2/
├── config/
│   ├── settings.yaml       # Watchlists, indicator thresholds, API settings
│   └── .env.example        # Environment variables template
├── src/
│   ├── __init__.py
│   ├── config.py           # YAML + .env resolution, dotted-path access
│   ├── scanner.py          # Data fetcher & technical indicator engine
│   ├── ai_advisor.py       # DeepSeek API integration & prompt engine
│   └── notifier.py         # macOS notification & webhook dispatcher
├── deploy/
│   ├── com.alphaseek.m2.scan.plist   # launchd job template (weekdays 16:15)
│   └── install_launchd.sh            # one-command install/uninstall
├── tests/                  # Offline rule-engine tests (pytest)
├── examples/               # Sample scan output
├── logs/                   # Execution logs + JSON reports
├── main.py                 # Entry point
├── requirements.txt        # Python dependencies
└── README.md               # Project documentation
```

---

## 🛠️ Quick Start

### 1. Clone & Environment Setup

```bash
git clone https://github.com/YangTaoCN/alphaseek-m2.git
cd alphaseek-m2

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

> Requires **Python 3.10+**. On macOS the system `python3` is often 3.9 — use
> `python3.11 -m venv venv` (or a Homebrew Python) if `pip install` complains.

### 2. Configure Credentials

Create `.env` file in the project root:

```bash
cp config/.env.example .env
```

Edit `.env`:

```env
DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
DEEPSEEK_MODEL="deepseek-chat" # or "deepseek-reasoner"
```

### 3. Customize Watchlist & Rules

Modify `config/settings.yaml`:

```yaml
watchlist:
  - NVDA
  - AAPL
  - MSFT
  - TSLA
  - AMZN
  - SPY
  - QQQ

indicators:
  ema_fast: 20
  ema_slow: 50
  rsi_period: 14
  rsi_min: 45
  rsi_max: 68
  volume_surge_multiplier: 1.2

notifications:
  macos_desktop: true
  telegram_bot_token: ""
  telegram_chat_id: ""
```

### 4. Run Scan

```bash
python main.py
```

Useful flags:

| Flag | What it does |
| --- | --- |
| `--tickers NVDA AMD` | scan an ad-hoc list instead of the configured watchlist |
| `--dry-run` | skip DeepSeek, emit the ATR-anchored rule-based plan |
| `--no-notify` | terminal output only (no desktop / Telegram / webhook) |
| `--min-confidence 7.5` | only alert on strong setups |
| `--min-action BUY` | ignore `WATCH` reports when alerting |
| `--json` | dump the full JSON report to stdout |

> **Timing matters:** `yfinance` daily bars include the *in-progress* session, whose
> volume is still filling up. Intraday runs will therefore under-report volume
> surge — schedule the scan after the close (16:15 ET is the default below).

---

## 🧠 How the Filter Works

A ticker must clear **all** hard rules locally before any API credit is spent:

1. **Trend**: `EMA(fast) > EMA(slow)` **and** price above `EMA(slow)`.
2. **Momentum**: `RSI(rsi_period)` inside the sweet-spot band (`rsi_min`–`rsi_max`), i.e. expansion without being overbought.
3. **Participation**: today's volume ≥ `volume_surge_multiplier` × the average of the **previous 20 sessions** (today's spike is excluded from its own baseline).
4. **Liquidity**: 20-day average dollar volume above `min_avg_dollar_volume`.

Survivors get one DeepSeek call each, which returns strict JSON
(`action`, `confidence`, `entry`, `stop_loss`, `target`, `horizon_days`,
`rationale`, `risk_notes`, `red_flags`). Levels are sanity-checked in code:
a missing/inverted stop is rebuilt from `1.5 × ATR14`, and a target is rebuilt
to preserve at least 2:1 reward-to-risk.

Run the test suite offline (no network, no API key):

```bash
pip install pytest
pytest -q
```

---

## ⏰ macOS Automated Scheduling (launchd / cron)

To run the scan automatically 15 minutes after US market close (16:15 ET on weekdays):

### Recommended: `launchd`

```bash
./deploy/install_launchd.sh              # install + load the job
launchctl kickstart -k gui/$(id -u)/com.alphaseek.m2.scan   # test it now
./deploy/install_launchd.sh --uninstall  # remove it
```

`launchd` is preferred on Macs because the job also fires after the machine
wakes from sleep, which plain `cron` will silently skip.

### Using `crontab`

```bash
crontab -e
```

Add the following line (replace paths with your actual project directory and virtual environment Python):

```cron
15 16 * * 1-5 /Users/<YOUR_USER>/alphaseek-m2/venv/bin/python /Users/<YOUR_USER>/alphaseek-m2/main.py >> /Users/<YOUR_USER>/alphaseek-m2/logs/cron.log 2>&1
```

---

## 📊 Sample Output & Notification

### Terminal Log:

```text
[2026-09-16 16:15:02] [INFO] Fetching daily market data for 7 tickers...
[2026-09-16 16:15:05] [INFO] [TRIGGER] NVDA passed technical filter: EMA20 > EMA50 (+3.12% gap); RSI 56.4 inside 45-68 expansion zone; Volume surge 1.45x vs 20d average
[2026-09-16 16:15:08] [INFO] [AI REVIEW] NVDA: BUY conf=8.5 (model=deepseek-chat)
========================================
[NVDA Signal Report]
Action: BUY (Confidence: 8.5/10)
Current Price: $128.40
Stop Loss: $122.50 | Target: $140.00 (R:R 1.9:1)
Core Rationale: Consolidation breakout with 1.45x volume confirmation; RSI is in bullish expansion zone with strong upward momentum.
========================================
[2026-09-16 16:15:09] [INFO] [NOTIFY] Native macOS notification pushed (NVDA · BUY (8.5/10)).
```

A longer transcript (including rejected tickers and the JSON artifact) lives in
[`examples/sample_output.md`](examples/sample_output.md).

---

## ⚠️ Disclaimer

This project is for educational and research purposes only. It is **not** financial or investment advice. Algorithmic trading and stock investing carry inherent market risks. Always do your own due diligence before executing trades.

The AI review layer can be wrong, can hallucinate context, and has **no** access
to live news, earnings calendars, or filings — treat its output as one input
among many, never as a signal to trade blindly.

---

## 📄 License

Distributed under the [MIT License](LICENSE).
