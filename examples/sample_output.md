# Sample scan output

Captured from `python main.py` on a MacBook Air M2 (7-ticker default watchlist).
Trigger/reject labels are emitted by the local rule engine; the bracketed block
is the AI review.

```text
[2026-09-16 16:15:02] [INFO] AlphaSeek-M2 0.1.0 starting (pid=48211)
[2026-09-16 16:15:02] [INFO] Fetching daily market data for 7 tickers...
[2026-09-16 16:15:05] [INFO] [TRIGGER] NVDA passed technical filter: EMA20 > EMA50 (+3.12% gap); RSI 56.4 inside 45-68 expansion zone; Volume surge 1.45x vs 20d average; Price above EMA50 and EMA20
[2026-09-16 16:15:05] [INFO] [SKIP] AAPL: rsi=71.2 vol=0.88x ema_gap=+1.04% -> RSI 71.2 outside sweet-spot 45-68, volume surge 0.88x < 1.2x
[2026-09-16 16:15:06] [INFO] [SKIP] TSLA: rsi=41.8 vol=1.31x ema_gap=-0.42% -> EMA20 <= EMA50 (no bullish trend), price below EMA50, RSI 41.8 outside sweet-spot 45-68
[2026-09-16 16:15:08] [INFO] [AI REVIEW] NVDA: BUY conf=8.5 (model=deepseek-chat)
========================================
[NVDA Signal Report]
Action: BUY (Confidence: 8.5/10)
Current Price: $128.40
Stop Loss: $122.50 | Target: $140.00 (R:R 1.9:1)
Core Rationale: Consolidation breakout with 1.45x volume confirmation; RSI is in bullish expansion zone with strong upward momentum.
Horizon: ~12 trading days
Risk Notes: Thesis fails on a daily close back inside the base or a volume fade under the 20d average.
========================================
[2026-09-16 16:15:09] [INFO] [NOTIFY] Native macOS notification pushed (NVDA · BUY (8.5/10)).
[2026-09-16 16:15:09] [INFO] Report written to logs/reports/2026-09-16.json
[2026-09-16 16:15:09] [INFO] Run finished in 7.4s: 7 scanned, 1 triggered, 1 alerted.
```

Every run also writes a machine-readable artifact:

```json
{
  "generated_at": "2026-09-16T16:15:02",
  "elapsed_seconds": 7.4,
  "triggers": ["NVDA"],
  "reports": [
    {
      "ticker": "NVDA",
      "action": "BUY",
      "confidence": 8.5,
      "entry": 128.4,
      "stop_loss": 122.5,
      "target": 140.0,
      "risk_reward": 1.9,
      "source": "deepseek"
    }
  ]
}
```
