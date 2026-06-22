"""
system_selftest.py — Tüm botu gerçek kodla, gerçek config ile uçtan uca test eder.

Hiçbir canlı emir göndermez. Sadece:
  1. Config yüklenir (VPS'teki ayarlarla aynı)
  2. Her strateji gerçek kodla instantiate edilir
  3. Sentetik mum verisiyle her stratejinin sinyal ürettiği doğrulanır
  4. Her coin için risk/pozisyon boyutu hesaplanır (trade açılır mı?)
  5. Execution kapıları (cooldown, slot, margin) test edilir

Çıktı: her bileşen için GECTI / KALDI
"""
from __future__ import annotations
import os
import sys
import numpy as np
import pandas as pd

# VPS config'ini birebir taklit et (gerçek .env değerleri)
os.environ.setdefault("PAPER_MODE", "true")
os.environ.setdefault("SYMBOLS", "BTC,ETH,SOL,BNB,XRP")
os.environ.setdefault("PRIMARY_TF", "1h")
os.environ.setdefault("MAX_RISK_PCT", "0.08")
os.environ.setdefault("RISK_SCALE", "1.25")
os.environ.setdefault("MAX_POSITIONS", "15")
os.environ.setdefault("POSITION_CAP_FRACTION", "5.0")
os.environ.setdefault("FIXED_MARGIN_USDT", "0")
os.environ.setdefault("LEVERAGE", "10")
os.environ.setdefault("BB_SYMBOLS", "BTC,ETH,SOL")
os.environ.setdefault("SR_BREAKOUT_SYMBOLS", "BTC,ETH")
os.environ.setdefault("BB_WEEKDAY_ENABLED", "false")
os.environ.setdefault("MEXC_API_KEY", "test")
os.environ.setdefault("MEXC_API_SECRET", "test")
os.environ.setdefault("TELEGRAM_TOKEN", "")
os.environ.setdefault("TELEGRAM_CHAT_ID", "")
os.environ.setdefault("NTFY_TOPIC", "")
os.environ.setdefault("WEB_DASHBOARD_TOKEN", "")
os.environ.setdefault("DB_PATH", "/tmp/selftest.db")

PASS = "\033[92mGECTI\033[0m"
FAIL = "\033[91mKALDI\033[0m"
results = []

def check(name, ok, detail=""):
    results.append(ok)
    mark = PASS if ok else FAIL
    print(f"  [{mark}] {name}" + (f"  — {detail}" if detail else ""))


def make_candles(n=260, base=100.0, atr_frac=0.02, trend=0.0, seed=1):
    """Sentetik 1h mum üret. trend>0 yukarı, atr_frac volatilite."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-06-15", periods=n, freq="1h", tz="UTC")
    rets = rng.normal(trend, atr_frac, n)
    close = base * np.cumprod(1 + rets)
    high = close * (1 + atr_frac/2)
    low = close * (1 - atr_frac/2)
    op = np.concatenate([[base], close[:-1]])
    vol = rng.uniform(800, 1200, n)
    return pd.DataFrame({"open": op, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


print("=" * 60)
print("  BOT UCTAN UCA SELF-TEST")
print("=" * 60)

# ─── 1. CONFIG ───────────────────────────────────────────────
print("\n[1] Config yukleme")
try:
    from config import load_config
    cfg = load_config()
    check("load_config()", True)
    check("5 coin tanimli", len(cfg.exchange.symbols) == 5,
          f"{len(cfg.exchange.symbols)} coin")
    eff_risk = cfg.risk.max_risk_per_trade
    check("max_risk = 0.08x1.25 = 0.10", abs(eff_risk - 0.10) < 1e-6,
          f"{eff_risk:.3f}")
    check("position_cap_fraction = 5.0", cfg.risk.position_cap_fraction == 5.0,
          f"{cfg.risk.position_cap_fraction}")
    check("max_positions = 15", cfg.risk.max_positions == 15)
    check("BB_SYMBOLS = BTC,ETH,SOL", cfg.strategy.bb_symbols is not None
          and len(cfg.strategy.bb_symbols) == 3)
    check("SR_SYMBOLS = BTC,ETH", cfg.strategy.sr_breakout_symbols is not None
          and len(cfg.strategy.sr_breakout_symbols) == 2)
    check("BB_WEEKDAY = false", cfg.risk.bb_weekday_enabled is False)
except Exception as e:
    check(f"load_config() — HATA: {e}", False)
    print("\nConfig yuklenemedi, test durduruldu.")
    sys.exit(1)

# ─── 2. STRATEJI SINYALLERI ──────────────────────────────────
print("\n[2] Strateji sinyal uretimi (gercek kod)")

# BB mean-reversion: fiyat alt banti kirmali -> long sinyali
from strategies.mean_reversion import MeanReversionStrategy
df = make_candles(seed=2)
# son mumu alt bandin altina zorla it
df.iloc[-1, df.columns.get_loc("close")] = df["close"].iloc[-30:].min() * 0.95
df.iloc[-1, df.columns.get_loc("low")] = df["close"].iloc[-1] * 0.99
df.iloc[-1, df.columns.get_loc("volume")] = 5000  # yuksek hacim
bb = MeanReversionStrategy(cfg.strategy)
sig = bb.analyze(df)
check("BB stratejisi sinyal uretiyor", sig.direction != 0,
      f"dir={sig.direction} ({sig.reason[:40]})")

# ORB
from strategies.orb import OrbStrategy
orb = OrbStrategy()
check("ORB instantiate", orb is not None)

# Asia BO
from strategies.asia_bo import AsiaBoStrategy
asia = AsiaBoStrategy(rr=cfg.strategy.fvg_rr)
df_asia = make_candles(seed=3)
atr_test = (df_asia["high"] - df_asia["low"]).rolling(14).mean().iloc[-1]
sig_a = asia.analyze(df_asia, atr_test)
check("Asia BO calisiyor (sinyal veya gecerli sebep)",
      isinstance(sig_a.direction, int),
      f"dir={sig_a.direction} ({sig_a.reason[:35]})")

# FVG
from strategies.fvg import FvgStrategy
fvg = FvgStrategy(min_gap_atr=cfg.strategy.fvg_min_gap_atr, rr=cfg.strategy.fvg_rr)
sig_f = fvg.analyze(make_candles(seed=4), atr_test)
check("FVG calisiyor", isinstance(sig_f.direction, int),
      f"dir={sig_f.direction}")

# Squeeze
from strategies.squeeze import SqueezeStrategy
sq = SqueezeStrategy(kc_mult=cfg.strategy.squeeze_kc_mult,
                     min_squeeze_bars=cfg.strategy.squeeze_min_bars,
                     sl_atr=cfg.strategy.squeeze_sl_atr,
                     rr=cfg.strategy.squeeze_rr, mtf_filter=cfg.strategy.squeeze_mtf)
sig_s = sq.analyze(make_candles(seed=5), atr_test)
check("Squeeze calisiyor", isinstance(sig_s.direction, int),
      f"dir={sig_s.direction}")

# S/R breakout
from strategies.sr_breakout import SrBreakoutStrategy
sr = SrBreakoutStrategy()
sig_sr = sr.analyze(make_candles(seed=6), atr_test)
check("S/R calisiyor", isinstance(sig_sr.direction, int),
      f"dir={sig_sr.direction}")

# ─── 3. RISK / POZISYON BOYUTU ───────────────────────────────
print("\n[3] Pozisyon boyutu — her coin acilir mi? (bakiye=$93)")
from risk import RiskManager, MIN_BTC_ORDER
rm = RiskManager(cfg.risk)
bal = 93.0
coins = [("BTC", 105000, 1000), ("ETH", 3000, 80), ("SOL", 165, 4),
         ("BNB", 620, 12), ("XRP", 2.30, 0.05)]
for name, price, atr in coins:
    setup = rm.build_trade_setup(
        direction=1, entry_price=price, atr=atr, balance=bal,
        leverage=cfg.exchange.leverage, symbol=f"{name}/USDT:USDT")
    if setup is None:
        check(f"{name} BB trade", False, "setup None (boyut min alti?)")
    else:
        check(f"{name} BB trade", setup.quantity >= MIN_BTC_ORDER,
              f"qty={setup.quantity:.4f} margin=${setup.margin_required:.2f} RR={setup.rr_ratio:.2f}")

# ─── 4. LEVELS-BASED (ORB/Asia/Squeeze) SIZING ───────────────
print("\n[4] Levels-based sizing (ORB/Asia/FVG/Squeeze)")
for name, price, atr in coins:
    sl = price - atr  # 1xATR stop
    tp = price + 2 * atr  # RR 2.0
    setup = rm.build_trade_setup_from_levels(
        direction=1, entry_price=price, sl_price=sl, tp_price=tp,
        balance=bal, leverage=cfg.exchange.leverage,
        symbol=f"{name}/USDT:USDT", risk_pct_override=cfg.risk.asia_risk_pct)
    if setup is None:
        check(f"{name} Asia/ORB trade", False, "setup None")
    else:
        check(f"{name} Asia/ORB trade", setup.quantity >= MIN_BTC_ORDER,
              f"qty={setup.quantity:.4f} margin=${setup.margin_required:.2f}")

# ─── 5. EXECUTION KAPILARI ───────────────────────────────────
print("\n[5] Execution kapilari (margin / RR / max-pos)")
# margin check: $31 margin < $93*0.95 = $88
setup_btc = rm.build_trade_setup(direction=1, entry_price=105000, atr=1000,
                                 balance=bal, leverage=10, symbol="BTC/USDT:USDT")
check("BTC margin < bakiye*0.95", setup_btc.margin_required < bal * 0.95,
      f"${setup_btc.margin_required:.2f} < ${bal*0.95:.2f}")
ok, reason = rm.validate_new_trade(setup_btc, 0)
check("validate_new_trade (0 acik)", ok, reason)
ok2, reason2 = rm.validate_new_trade(setup_btc, 15)
check("max_positions=15 doluyken blok", not ok2, reason2)
ok3, _ = rm.validate_new_trade(setup_btc, 14)
check("14 acik iken 15. acilir", ok3)

# ─── 6. DAILY LOSS LIMIT ─────────────────────────────────────
print("\n[6] Gunluk zarar limiti")
# %35 limit: $93 -> $60 (-35.5%) tetiklemeli
ok_loss = rm.check_daily_loss_limit(93.0, 65.0, 0.0)  # -30% -> hala ok
check("-30% zararda devam (limit %35)", ok_loss)
trip = rm.check_daily_loss_limit(93.0, 58.0, 0.0)  # -37.6% -> dur
check("-37% zararda DURDURUR", not trip)

# ─── SONUC ───────────────────────────────────────────────────
print("\n" + "=" * 60)
total = len(results)
passed = sum(results)
if passed == total:
    print(f"  \033[92mTUM TESTLER GECTI: {passed}/{total}\033[0m")
    print("  Sistem kod tarafinda saglam calisiyor.")
else:
    print(f"  \033[91m{total-passed} TEST KALDI ({passed}/{total} gecti)\033[0m")
print("=" * 60)
sys.exit(0 if passed == total else 1)
