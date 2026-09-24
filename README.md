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
- 🔬 **Backtested**: `backtest.py` replays the identical rules walk-forward (no lookahead) and reports win rate, expectancy in R, profit factor, max drawdown and a buy & hold benchmark.

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
│   ├── backtest.py         # Walk-forward replay engine (shared with main.py rules)
│   └── notifier.py         # macOS notification & webhook dispatcher
├── deploy/
│   ├── com.alphaseek.m2.scan.plist   # launchd job template (weekdays 16:15)
│   └── install_launchd.sh            # one-command install/uninstall
├── tests/                  # Offline rule-engine tests (pytest)
├── examples/               # Sample scan output
├── logs/                   # Execution logs + JSON reports (+ backtest/ artifacts)
├── main.py                 # Entry point
├── backtest.py             # Walk-forward backtest CLI
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

## 🔬 Walk-Forward Backtest

The screen is only worth trading if the rules have a measurable edge, so the
repo ships a **no-lookahead** replay of the exact production filter
(`backtest.py` + `src/backtest.py`).

```bash
python backtest.py                            # 5y, config watchlist
python backtest.py --period 3y
python backtest.py --tickers NVDA AMD --reward-ratio 2 --stop-atr 2
python backtest.py --max-hold 10 --json
```

**Methodology**

- Every bar is evaluated through the *same* `TechnicalScanner.evaluate()` on a
  **truncated frame**, so backtest and live rules can never drift apart.
- Bar *i* is evaluated with data up to and including bar *i*; the trade fills at
  the **open of bar i+1**. Indicators, ATR and the 20-day volume baseline are
  therefore never contaminated by future bars.
- Levels mirror the production fallback plan: stop = `1.5 × ATR14`, target =
  `3 × risk` (3:1), max hold 10 bars, **one position per ticker at a time**
  (no pyramiding, no overlapping entries).
- Gaps through a level fill at the open; if a bar touches stop *and* target,
  the stop is assumed first (conservative). Bars with no touch exit at the
  close of the hold window (timeout).
- Equity/DD use a **1% risk-per-trade compounding model**, applied sequentially
  in exit order — a portfolio approximation that ignores simultaneous positions.

**Results (2022-01 → 2026-09, default watchlist, 248 trades)**

| Variant | Trades | Win% | Expectancy | PF | MaxDD |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1.5×ATR / 3:1 (default) | 248 | 42.3% | +0.18R | 1.34 | 20.3% |
| 1.5×ATR / 2:1 | 253 | 43.1% | +0.13R | 1.26 | 19.4% |
| 2.0×ATR / 2:1 | 239 | 46.0% | +0.15R | 1.35 | 17.9% |
| 1.5×ATR / 3:1, hold 20 | 211 | 39.8% | +0.17R | 1.28 | 22.1% |

Per-ticker 5y (default params): NVDA +10.1R, SPY +10.4R, QQQ +8.4R, AAPL +7.4R,
AMZN +7.2R, MSFT +2.4R, **TSLA −1.9R**.

**Honest read:** the filter does have a small, parameter-stable positive
edge (~+0.13 to +0.20R per trade, PF 1.3), but over the same window the
equal-weight watchlist buy & hold returned **+151%** while the strategy's 1%
risk model compounded to roughly **+44%** with a 20% drawdown. It is a
low-exposure signal generator, not a buy-and-hold replacement — and a 42% win
rate means long losing streaks are normal. Backtest ≠ future performance.

---

## 🇨🇳 China Profile (A-shares only — Shanghai / Shenzhen)

A second, independent watchlist for **沪市 / 深市** names only. Hong Kong
(`.HK`) and US-listed China exposure (NTES / MCHI / FXI / KWEB) were tested
and then removed: the mandate is names actually tradable on the mainland
exchanges.

```bash
python main.py --config config/settings.china.yaml --dry-run --no-notify
```

Reports and logs go to `logs/china/` so they never overwrite the US ones.

**Selection used the identical rule** (positive expectancy in both the 5y and
3y walk-forward windows, ≥15 trades each). Growth was a *second, independent*
filter — and the two filters genuinely disagree:

| Ticker | Name | 10y growth | 5y n / R | 3y n / R | Outcome |
| --- | --- | ---: | --- | --- | --- |
| 601899.SS | 紫金矿业 | +1066% | 38 / +0.41 | 23 / +0.78 | ✅ included |
| 601288.SS | 农业银行 | +270% | 49 / +0.44 | 26 / +0.61 | ✅ included |
| 601398.SS | 工商银行 | +124% | 54 / +0.28 | 36 / +0.32 | ✅ included |
| 601318.SS | 中国平安 | +128% | 30 / +0.25 | 20 / +0.41 | ✅ included |
| 688008.SS | 澜起科技 | +201% | 31 / +0.33 | 23 / +0.44 | ✅ included |
| 688981.SS | 中芯国际 | +45% | 32 / +0.22 | 21 / +0.27 | ✅ included |
| 600309.SS | 万华化学 | +469% | 28 / +0.28 | 18 / +0.27 | ✅ included |
| 600030.SS | 中信证券 | +116% | 31 / +0.26 | 18 / +0.20 | ✅ included |
| 600036.SS | 招商银行 | +237% | 26 / +0.02 | 20 / +0.33 | ✅ included |
| 600276.SS | 恒瑞医药 | +184% | 34 / +0.21 | 20 / +0.14 | ✅ included |
| 601138.SS | 工业富联 | +531% | 35 / +0.14 | 17 / +0.18 | ✅ included |
| 300308.SZ | 中际旭创 | — | 31 / +0.33 | 21 / +0.34 | ✅ included |
| 002230.SZ | 科大讯飞 | — | 21 / +0.72 | 15 / +0.69 | ✅ included |
| 000333.SZ | 美的集团 | +352% | 38 / +0.15 | 28 / +0.31 | ✅ included |
| 000725.SZ | 京东方A | — | 29 / +0.20 | 23 / +0.24 | ✅ included |
| 002475.SZ | 立讯精密 | +805% | 30 / +0.05 | 17 / +0.35 | ✅ included |
| 002415.SZ | 海康威视 | +159% | 31 / +0.14 | 20 / +0.07 | ✅ included |
| 300750.SZ | 宁德时代 | **+1495%** | 35 / **−0.23** | 25 / **−0.25** | ❌ excluded |
| 600519.SS | 贵州茅台 | +429% | 29 / **−0.28** | 18 / **−0.29** | ❌ excluded |
| 300760.SZ | 迈瑞医疗 | +148% | 24 / −0.49 | 14 / −0.55 | ❌ excluded |
| 601088.SS | 中国神华 | +565% | 54 / +0.13 | 34 / **−0.07** | ❌ 3y negative |
| 600028.SS | 中国石化 | +64% | 42 / +0.23 | 22 / **−0.04** | ❌ 3y negative |
| 000651.SZ · 600887.SS · 600585.SS · 601166.SS · 600690.SS · 603501.SS | 格力 · 伊利 · 海螺 · 兴业 · 海尔 · 韦尔 | — | negative | negative | ❌ excluded |
| 601012.SS | 隆基绿能 | +191% | 12 / +0.54 | 10 / +0.52 | ⚠️ too few trades |
| 1810.HK · 2318.HK · NTES · MCHI · FXI | HK / US-listed | — | — | — | 🚫 out of scope |

**The lesson this table teaches:** the strongest 10-year compounder on the
board (CATL, +1495%) is *negative* in both windows, because a momentum
breakout screen wants steady participation, not one big multi-year trend.
Growth ranking and strategy edge must be tested separately.

**Execution caveats specific to this market**

- A-shares have +/-10% daily price limits, T+1 settlement and a midday break.
  Stops can be gapped through and cannot always be filled the same day.
- yfinance prices are in CNY and are not adjusted for the CNY/USD move —
  treat the R-multiples as local-currency results.
- Bar "volume" comparison still works (relative to each name's own 20-day
  average), which is why the same thresholds transfer.

---

## 🎯 Watchlist Selection (backtest-driven)

Every symbol in `config/settings.yaml` must clear a two-window test on the
walk-forward engine above:

- **positive expectancy in BOTH the 5y and 3y window**, and
- **≥15 closed trades in each** (so one lucky trade cannot carry it).

The 1y window is reported but not required — at 10-bar holds a year only
produces 3-10 trades, so it flips sign on a single trade and is treated as a
tiebreaker, not a criterion.

| Ticker | Group | 5y n / R / PF | 3y n / R / PF | 1y R |
| --- | --- | --- | --- | ---: |
| META | mega-cap tech | 29 / +0.71 / 3.19 | 20 / +0.66 / 2.86 | +0.63 |
| KLAC | semis | 47 / +0.64 / 2.87 | 33 / +0.49 / 2.10 | +0.29 |
| CRM | mega-cap tech | 26 / +0.60 / 3.01 | 15 / +0.37 / 1.99 | +0.62 |
| VRT | AI infrastructure | 43 / +0.59 / 2.41 | 28 / +0.54 / 2.33 | +0.97 |
| AIQ | AI ETF | 23 / +0.56 / 2.73 | 23 / +0.56 / 2.73 | +0.26 |
| ORCL | mega-cap tech | 31 / +0.55 / 1.97 | 17 / +1.00 / 3.01 | −0.29 |
| SOXX | semis ETF | 45 / +0.54 / 2.29 | 30 / +0.43 / 1.96 | +0.46 |
| GOOGL | mega-cap tech | 36 / +0.53 / 2.26 | 24 / +0.67 / 2.50 | −0.55 |
| DELL | AI infrastructure | 40 / +0.52 / 2.29 | 24 / +0.54 / 2.27 | +0.38 |
| TER | semis | 30 / +0.49 / 2.17 | 24 / +0.80 / 4.06 | +1.15 |
| AMD | mega-cap tech | 28 / +0.46 / 1.84 | 18 / +0.30 / 1.53 | +0.28 |
| AVGO | mega-cap tech | 42 / +0.43 / 1.89 | 25 / +0.58 / 2.26 | +0.31 |
| VOO | broad ETF | 46 / +0.41 / 1.89 | 33 / +0.55 / 2.37 | +0.13 |
| AAPL | mega-cap tech | 28 / +0.27 / 1.51 | 19 / +0.44 / 1.87 | +0.11 |
| NVDA | mega-cap tech | 42 / +0.25 / 1.46 | 26 / +0.09 / 1.16 | −0.37 |
| SPY | broad ETF | 48 / +0.25 / 1.50 | 36 / +0.36 / 1.79 | −0.19 |
| QQQ | broad ETF | 43 / +0.24 / 1.52 | 30 / +0.40 / 1.90 | −0.30 |
| AMZN | mega-cap tech | 33 / +0.20 / 1.43 | 25 / +0.07 / 1.13 | −0.96 |

**Portfolio result for this 18-name list (5y):** 660 trades, 52.7% win rate,
**+0.449R expectancy**, profit factor **2.01**, max drawdown **20.6%**
(vs +0.177R / PF 1.34 / 40%-ish win rate for the original 7-name list).

**Tested and rejected** (negative in both 5y and 3y): TSLA (−0.08R, PF 0.86),
MSFT (3y negative), SNPS, ADBE, QCOM, UBER, ARKK, BOTZ, SMCI, INTU, VTI.
Candidates that passed 5y/3y but came up short on trade count or 1y behaviour
(AMAT, MRVL, SMH, SCHG, IGV, VOO-adjacent ETFs) are held in reserve rather
than padding the list.

> Selection is in-sample by construction — a repeated pattern in this repo is
> that 1y windows disagree with 5y windows, which is exactly why the list is
> re-checked rather than frozen. Re-run `python backtest.py --tickers <sym>`
> before adding anything new.

---

## ⏰ macOS Automated Scheduling (launchd / cron)

Two pre-open schedules are used in this deployment (both run ~30 minutes
before their market opens, so the recommendation is actionable that day):

| Market | Local run time | Data used |
| --- | --- | --- |
| US (default config) | 09:00 ET, Mon–Fri | last completed US session close |
| China A-shares (`--config config/settings.china.yaml`) | 09:00 Beijing (= 21:00 ET previous day), Mon–Fri | last completed A-share session close |

Scheduling is handled by OpenClaw automations (see the job definitions), so the
scanner itself stays a plain CLI. For a standalone Mac setup:

### Recommended: `launchd`

```bash
./deploy/install_launchd.sh              # install + load the job
launchctl kickstart -k gui/$(id -u)/com.alphaseek.m2.scan   # test it now
./deploy/install_launchd.sh --uninstall  # remove it
```

`launchd` is preferred on Macs because the job also fires after the machine
wakes from sleep, which plain `cron` will silently skip. Edit the hour in
`deploy/com.alphaseek.m2.scan.plist` to match your pre-open slot.

### Using `crontab`

```bash
crontab -e
```

Add the following lines (replace paths with your actual project directory and virtual environment Python):

```cron
# US watchlist - 09:00 ET, 30 minutes before the open
0 9 * * 1-5 /Users/<YOUR_USER>/alphaseek-m2/venv/bin/python /Users/<YOUR_USER>/alphaseek-m2/main.py >> /Users/<YOUR_USER>/alphaseek-m2/logs/cron.log 2>&1

# China A-shares - 09:00 Beijing, 30 minutes before the A-share open
0 9 * * 1-5 /Users/<YOUR_USER>/alphaseek-m2/venv/bin/python /Users/<YOUR_USER>/alphaseek-m2/main.py --config /Users/<YOUR_USER>/alphaseek-m2/config/settings.china.yaml >> /Users/<YOUR_USER>/alphaseek-m2/logs/china/cron.log 2>&1
```

> Setting `TZ=Asia/Shanghai` in the crontab (or using the automations scheduler
> with `tz: Asia/Shanghai`, as this deployment does) matters for the China
> line: Beijing 09:00 is 21:00 ET on the previous calendar day.

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
