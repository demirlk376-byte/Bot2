# BTC Intraday/Swing Trading Engine (MEXC Futures)

Async Python trading bot for BTC/USDT:USDT perpetual futures on MEXC.
Paper trading first, then live. The strategy is **not** guessed — it was
derived empirically from 12 months of 1-minute data and validated with a
train/test split to avoid overfitting.

## TL;DR — what actually works

We tested standard approaches across **May 2025 → April 2026** (12 months,
525,600 1m candles). The honest findings:

| Approach | Result after costs |
|---|---|
| 5m trend-following (EMA/MACD crossover) | **Loses** — it's anti-edge |
| 5m mean reversion (BB/RSI) | **Loses** — edge < transaction cost |
| 5m breakout | **Loses** |
| **1h Bollinger mean reversion** | **Wins, in/out of sample** |

The core reason: on 5m, the predictive edge of indicators (~0.01–0.05% forward
return) is **smaller than the round-trip cost** (~0.08–0.12%). Only by moving
to the **1h timeframe with larger targets** does the edge clear costs.

## The validated edge

**Fade Bollinger-band extremes on the 1h timeframe.** When a 1h candle closes
*below* the lower band, go long; when it closes *above* the upper band, go short.

- Stop loss: **3 × ATR(14)**
- Take profit: **5 × ATR(14)** (R:R ≈ 1.67)
- Max hold: **48 hours** (force close)
- No higher-timeframe trend filter (adding one *reduced* returns — BB extremes
  are reversion points regardless of the macro trend)
- Risk: 2% of equity per trade, 1 position at a time, 5% daily loss circuit breaker

### Performance (production modules, $10k, 2% risk, 0.08% cost/trade)

| Period | Trades | Win rate | PnL | PF | Max DD |
|---|---|---|---|---|---|
| All 12 months | 242 | 47% | **+13.5%** | 1.11 | 11.7% |
| Train (May–Dec 2025) | 165 | 47% | +4.2% | 1.06 | 11.7% |
| Test (Jan–Apr 2026) | 77 | 47% | **+9.3%** | 1.21 | 9.8% |

For context, **buy-and-hold lost −18.9%** over the same 12 months. The bot was
net positive while BTC fell, with shallow drawdowns.

This is honest, modest, real edge — not a fantasy 1000% backtest. Win rate is
below 50%; profitability comes from winners (5×ATR) being larger than losers
(3×ATR).

## Reproduce the validation

```bash
pip install -r requirements.txt

python research_edge.py        # forward-return analysis: which signals predict?
python research_meanrev.py     # mean-reversion rules with train/test split
python research_viable.py      # cost sensitivity + timeframe sweep
python research_final.py       # robustness matrix for the winning rule
python production_backtest.py  # real strategy+risk modules → +13.5% over 12 months
```

## Run the bot

```bash
cp .env.example .env
# PAPER_MODE=true requires no API keys (real prices, simulated fills)
python main.py
```

For live trading set `PAPER_MODE=false` and add MEXC API keys with Futures
permission. **Validate in paper mode for several weeks first.**

## Architecture

```
main.py              Async orchestrator; on 1h candle close → MR signal → execute
config.py            .env → typed config (validated SL/TP/timeframe defaults)
exchange.py          PaperExchange (simulated) + LiveExchange (ccxt.pro MEXC)
data.py              REST + WebSocket candle feeds, 1h/4h buffers
indicators.py        EMA, MACD, Bollinger, RSI, ATR, ADX, S/R (numpy/pandas)
strategies/
  mean_reversion.py  THE validated edge: 1h Bollinger fade
  trend.py           Kept for reference (proven to lose on its own)
  breakout.py        Kept for reference
  signal_combiner.py Hybrid scoring (legacy — research showed it underperforms)
risk.py              Position sizing, ATR SL/TP, daily loss limit
execution.py         Pre-flight checks, order placement, max-hold close
portfolio.py         Position + P&L tracking
monitor.py           Rich terminal dashboard
telegram_bot.py      Trade alerts
database.py          SQLite trade log
production_backtest.py  Canonical backtest (uses production modules)
research_*.py        Edge discovery / validation scripts
```

## Honest caveats

- **One year of data, one asset.** The edge is real in this sample but markets
  change. Re-validate periodically.
- **Mean reversion fails in strong sustained trends** — the worst month was
  Oct 2025 (−6.4%) during a sharp directional crash.
- **Costs dominate.** The result assumes ~0.08% round trip (limit/maker entry).
  Pure market orders (~0.12%+) cut returns substantially.
- This is **not financial advice.** Trade at your own risk, start small.
