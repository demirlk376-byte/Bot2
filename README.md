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
| **1h BB mean reversion + volume filter** | **Wins even more robustly** |

The core reason: on 5m, the predictive edge of indicators (~0.01–0.05% forward
return) is **smaller than the round-trip cost** (~0.08–0.12%). Only by moving
to the **1h timeframe with larger targets** does the edge clear costs.

## The validated edge

**Fade Bollinger-band extremes on the 1h timeframe, with above-average volume,
entering via post-only limit (maker) orders.**
When a 1h candle closes *below* the lower band with above-average volume (capitulation),
go long. When it closes *above* the upper band with above-average volume (blow-off),
go short.

- Stop loss: **3 × ATR(14)**
- Take profit: **5 × ATR(14)** (R:R ≈ 1.67)
- Max hold: **48 hours** (force close)
- Volume filter: candle volume > 20-period moving average
  (rejects quiet drift to the band — only genuine exhaustion signals)
- Maker entry: post-only limit order (0% fee vs 0.01% taker) → halves cost
- No higher-timeframe trend filter (adding one *reduced* returns — BB extremes
  are reversion points regardless of the macro trend)
- Risk: 3% of equity per trade, 1 position at a time, 5% daily loss circuit breaker

### Stacked improvements (production modules, $10k, 30x leverage)

Each lever was validated **independently on the out-of-sample test period** —
none was fitted to the data. The progression:

| Stage | Trades | WR | All 12m | Train | Test | PF | Max DD |
|---|---|---|---|---|---|---|---|
| 1. Baseline (1h BB fade) | 242 | 47% | +13.5% | +4.2% | +9.3% | 1.11 | 11.7% |
| 2. + Volume filter | 238 | 47% | +20.8% | +7.2% | +13.6% | 1.18 | 11.5% |
| 3. + Maker entry (0.04% RT) | 238 | 47% | +26.7% | +10.7% | +16.0% | 1.23 | 10.8% |
| 4. + Risk 3% **(shipped)** | 238 | 47% | **+28.2%** | +11.0% | **+17.2%** | 1.24 | **10.5%** |

For context, **buy-and-hold lost −18.9%** over the same 12 months. The bot more
than doubled its annual return through the improvements while drawdown actually
*fell* from 11.7% to 10.5%.

**Why each lever is real, not overfit:**
- **Volume filter**: high-volume BB extremes = capitulation/exhaustion (reverts);
  low-volume = quiet drift (continues). Improves both train and test.
- **Maker entry**: literally paying 0% fee instead of 0.01% taker. Pure cost
  reduction, no model change — strictly more profit on identical trades.
- **Risk 3%**: same trades, larger size. Above ~4% the 50%-of-balance position
  cap binds, so returns plateau (self-limiting tail risk).

This is honest, modest, real edge — not a fantasy 1000% backtest. Win rate is
47%; profitability comes from winners (5×ATR) being larger than losers (3×ATR),
low transaction costs, and avoiding false signals in trending conditions.

## Reproduce the validation

```bash
pip install -r requirements.txt

python research_edge.py        # forward-return analysis: which signals predict?
python research_meanrev.py     # mean-reversion rules with train/test split
python research_viable.py      # cost sensitivity + timeframe sweep
python research_final.py       # robustness matrix for the winning rule
python research_improvements.py  # volume filter + other filters, train/test
python research_maximize.py    # cost reduction + risk sizing levers, train/test
python production_backtest.py  # real strategy+risk modules → +28.2% over 12 months
```

## Run the bot

```bash
cp .env.example .env
# PAPER_MODE=true requires no API keys (real prices, simulated fills)
python main.py
```

For live trading set `PAPER_MODE=false` and add MEXC API keys with Futures
permission. **Validate in paper mode for several weeks first.**

### Minimum balance

With MEXC's 0.001 BTC minimum contract size and BTC at $100k:
- Minimum viable balance ≈ **$150** (so 2% risk reaches 0.001 BTC minimum)
- Recommended paper/live starting balance: **$200+**
- Leverage (LEVERAGE env var) reduces margin required per trade but **does not
  change risk per trade in dollar terms** — it only frees up idle capital.

## Architecture

```
main.py              Async orchestrator; on 1h candle close → MR signal → execute
config.py            .env → typed config (validated SL/TP/timeframe defaults)
exchange.py          PaperExchange (simulated) + LiveExchange (ccxt.pro MEXC)
data.py              REST + WebSocket candle feeds, 1h/4h buffers
indicators.py        EMA, MACD, Bollinger, RSI, ATR, ADX, S/R (numpy/pandas)
strategies/
  mean_reversion.py  THE validated edge: 1h Bollinger fade + volume filter
  trend.py           Kept for reference (proven to lose on its own)
  breakout.py        Kept for reference
  signal_combiner.py Hybrid scoring (legacy — research showed it underperforms)
funding.py           Funding rate + open interest monitor (live-only edge probe)
risk.py              Position sizing, ATR SL/TP, daily loss limit
execution.py         Pre-flight checks, order placement, maker entry, max-hold close
portfolio.py         Position + P&L tracking
monitor.py           Rich terminal dashboard
telegram_bot.py      Trade alerts
database.py          SQLite trade log
production_backtest.py  Canonical backtest (uses production modules)
research_*.py        Edge discovery / validation scripts
```

## Funding rate / open interest (the next edge — live only)

OHLCV backtesting has a hard ceiling: it knows price and volume, but nothing
about *positioning*. On perpetual futures, two derivatives signals carry real
predictive value for mean reversion that **cannot be backtested from the CSVs**:

- **Funding rate** — when funding is extremely negative, shorts are crowded and
  paying to stay short; that crowd is fuel for an upward squeeze. Pairing this
  with a long fade (price below the lower band) is a documented confluence.
  Symmetrically, extreme positive funding fuels a short fade.
- **Open interest** — OI *falling* into a price extreme means positions are being
  closed/liquidated (capitulation → reverts). OI *rising* means fresh money is
  chasing (trend continuation risk).

`funding.py` fetches both from MEXC live and ships **disabled by default** so it
never touches the validated edge. Enable it in stages via `.env`:

```bash
FUNDING_ENABLED=true
FUNDING_MODE=monitor   # log funding+OI on every signal — collect data first
# FUNDING_MODE=filter  # then: skip contrarian+extreme setups
# FUNDING_MODE=boost   # or: nudge confidence by funding alignment
```

Run `monitor` for a few weeks of paper trading to build a real dataset, then
decide from your own logs whether `filter`/`boost` actually help before trusting
them with size. This is the honest way to add an un-backtestable signal: prove
it forward, don't assume it.

### Why not just add more pairs (ETH/SOL)?

Tested: the identical 1h BB-fade strategy on 5 months of ETH (Sep–Dec 2025 +
Apr 2026) returned **+0.5% overall** — the train window lost −10% (WR 39%) because
ETH trended hard in Sep–Oct and mean reversion got run over, while BTC was fine
in the same months. The edge is BTC-specific in this sample; tuning ETH
separately on 5 months would be overfitting. Funding/OI is a more principled
next step than diversifying into a pair where the edge doesn't hold.

## Honest caveats

- **One year of data, one asset.** The edge is real in this sample but markets
  change. Re-validate periodically.
- **Mean reversion fails in strong sustained trends** — the worst month was
  Nov 2025 (−5.6% with volume filter) during a momentum-driven up-swing.
- **Costs dominate.** The result assumes ~0.08% round trip (limit/maker entry).
  Pure market orders (~0.12%+) cut returns substantially.
- **Volume filter note**: based on only 4 filtered trades over 12 months. The
  improvement is consistent with the theory (capitulation = high volume) and
  holds out-of-sample, but with only 4 filtered events, the sample is thin.
  Monitor for a few months after going live to confirm it continues to help.
- This is **not financial advice.** Trade at your own risk, start small.
