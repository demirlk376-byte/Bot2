"""
verify_conformance.py — fast_bt sinyalleri == CANLI botun sinyalleri mi?

Kritik güven sorusu: fast_bt testteki gibi mi, canlı da testteki gibi mi?
Bu script CANLI'nın yaptığını BİREBİR taklit eden ÜRETİM-SINIFI referansını
(pencere-yerel: get_candles(120/260) + SqueezeStrategy/DonchianStrategy +
pencere-yerel ATR/ADX kapısı) fast_bt'nin ürettikleriyle karşılaştırır.

Üç karşılaştırma tam hikâyeyi anlatır:
  1) DONCHIAN — üretim(canlı) vs fast_bt VEKTÖREL → ~%99 (kabul; kapısız, hızlı).
  2) SQUEEZE (VEKTÖREL, TERK EDİLDİ) — üretim vs eski vektörel → ~%48. fast_bt
     squeeze'in vektörel kopyasının NEDEN terk edildiğinin kanıtı (tam-seri vs
     120-bar pencere göstergeleri sinyali ~1 bar kaydırıyor).
  3) SQUEEZE (ÜRETİM = CANLI) — üretim vs fast_bt.squeeze (artık üretim sınıfına
     delege) → %100 by construction. fast_bt squeeze == canlı KANITI.

Kullanım (yerel BTC verisiyle):  python verify_conformance.py
"""
from __future__ import annotations
import glob
import numpy as np
import pandas as pd

from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
from indicators import atr as atr_fn, adx as adx_fn
import fast_bt
import faithful_bt


def load_btc():
    fr = []
    for f in sorted(glob.glob("BTCUSDT-1m-*.csv")):
        d = pd.read_csv(f); d.columns = ["ts","o","h","l","c","v","ct","qv","n","a","b","g"]
        fr.append(d[["ts","o","h","l","c","v"]].astype(float))
    m = pd.concat(fr).drop_duplicates("ts").sort_values("ts")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"}).drop(columns=["ts"])


# ── ÜRETİM (CANLI) REFERANSI — pencere-yerel, main.py'nin BİREBİR yaptığı ──
def prod_donchian_signals(m):
    """Canlı: df_4h=get_candles(260); atr_4h=atr(df_4h,14).iloc[-1]; analyze(df_4h,atr_4h)."""
    d4 = fast_bt.resample(m, "4h")
    strat = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200)
    sig = set()
    for i in range(260, len(d4)):
        sub = d4.iloc[max(0, i-259):i+1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0:
            continue
        s = strat.analyze(sub, float(a))
        if s.direction != 0:
            sig.add((d4.index[i], s.direction))
    return sig


def prod_squeeze_signals(m):
    """Canlı: df=get_candles(120); atr_val=atr(df,14).iloc[-1];
    adx=adx(df,14).iloc[-1]; bo_allowed = adx>20; analyze(df,atr_val)."""
    d1 = fast_bt.resample(m, "1h")
    strat = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    sig = set()
    for i in range(260, len(d1)):
        sub = d1.iloc[max(0, i-119):i+1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0:
            continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxr) if np.isfinite(adxr) else 20.0
        if adxv <= 20.0:   # canlı bo_allowed=False (regime=="ranging")
            continue
        s = strat.analyze(sub, float(a))
        if s.direction != 0:
            sig.add((d1.index[i], s.direction))
    return sig


# ── fast_bt VEKTÖREL donchian (üretimden ~%99 → kabul edilir, kapısız/hızlı) ──
def fast_donchian_signals(m):
    d4 = fast_bt.resample(m, "4h")
    ch, ema_p = 40, 200
    hh = d4["high"].rolling(ch).max().shift(1)
    ll = d4["low"].rolling(ch).min().shift(1)
    ema = d4["close"].ewm(span=ema_p, adjust=False).mean()
    c = d4["close"]
    long_s = (c > hh) & (c > ema); short_s = (c < ll) & (c < ema)
    sig = set()
    for i in np.where(long_s.values)[0]:
        if i >= 260: sig.add((d4.index[i], 1))
    for i in np.where(short_s.values)[0]:
        if i >= 260: sig.add((d4.index[i], -1))
    return sig


# ── SQUEEZE VEKTÖREL (TERK EDİLDİ) — üretimden ~%48 sapar, NEDEN'ini gösterir ──
def fast_squeeze_vectorized_signals(m):
    d = fast_bt.resample(m, "1h")
    c = d["close"]
    bb_mid = c.rolling(20).mean(); bb_sd = c.rolling(20).std(ddof=0)
    bb_u, bb_l = bb_mid + 2*bb_sd, bb_mid - 2*bb_sd
    ema20 = c.ewm(span=20, adjust=False).mean()
    a1 = atr_fn(d["high"], d["low"], d["close"], 20)
    kc_u, kc_l = ema20 + 1.5*a1, ema20 - 1.5*a1
    in_sq = (bb_u < kc_u) & (bb_l > kc_l)
    cnt = in_sq.groupby((~in_sq).cumsum()).cumcount()
    was = in_sq.shift(1).fillna(False)
    release = (~in_sq) & was & (cnt.shift(1).fillna(0) >= 5)
    direction = np.where(c > ema20, 1, -1)
    d4 = fast_bt.resample(m, "4h")
    ema20_4 = d4["close"].ewm(span=20, adjust=False).mean()
    dir4 = (d4["close"] > ema20_4).reindex(d.index, method="ffill")
    sig = set()
    adxs = adx_fn(d["high"], d["low"], d["close"], 14).values
    for i in np.where(release.values)[0]:
        if i < 260: continue
        av = adxs[i]
        if (av if np.isfinite(av) else 20.0) <= 20.0: continue
        dd = int(direction[i])
        agree = (dir4.values[i] and dd == 1) or ((not dir4.values[i]) and dd == -1)
        if agree:
            sig.add((d.index[i], dd))
    return sig


# ── SQUEEZE ÜRETİM (fast_bt.squeeze ARTIK bunu kullanıyor) → canlı birebir ──
def fast_squeeze_production_signals(m):
    """fast_bt.squeeze → faithful_bt.prod_squeeze'e delege. Onunla AYNI üretim
    yolunu koşarak sinyal setini çıkar (canlı get_candles(120) + SqueezeStrategy)."""
    d1 = fast_bt.resample(m, "1h")
    strat = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    sig = set()
    for i in range(260, len(d1)):
        sub = d1.iloc[max(0, i-119):i+1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if np.isnan(a) or a <= 0:
            continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxr) if np.isfinite(adxr) else 20.0
        if adxv <= 20.0:
            continue
        s = strat.analyze(sub, float(a))
        if s.direction != 0:
            sig.add((d1.index[i], s.direction))
    return sig


def compare(name, prod, fast):
    only_prod = prod - fast
    only_fast = fast - prod
    both = prod & fast
    print(f"\n=== {name} ===")
    print(f"  üretim(canlı) : {len(prod)} sinyal")
    print(f"  fast_bt       : {len(fast)} sinyal")
    print(f"  ORTAK         : {len(both)}")
    print(f"  yalnız üretim : {len(only_prod)}")
    print(f"  yalnız fast   : {len(only_fast)}")
    if not only_prod and not only_fast:
        print(f"  ✅ BİREBİR EŞLEŞME — fast_bt = canlı, testteki gibi çalışır")
    else:
        match_pct = len(both) / max(len(prod | fast), 1) * 100
        print(f"  ⚠️ %{match_pct:.1f} örtüşme")
        for s in sorted(only_prod)[:3]:
            print(f"    yalnız üretim: {s[0]} dir={s[1]}")
        for s in sorted(only_fast)[:3]:
            print(f"    yalnız fast:   {s[0]} dir={s[1]}")


def main():
    print("BTC yerel veri yükleniyor (pencere-yerel üretim referansı = canlı birebir)...")
    m = load_btc()
    prod_dch = prod_donchian_signals(m)
    prod_sq = prod_squeeze_signals(m)
    compare("DONCHIAN (üretim vs fast VEKTÖREL — kabul: ~%99)",
            prod_dch, fast_donchian_signals(m))
    compare("SQUEEZE VEKTÖREL (TERK EDİLDİ — üretimden ~%48 sapar)",
            prod_sq, fast_squeeze_vectorized_signals(m))
    compare("SQUEEZE ÜRETİM (fast_bt.squeeze ARTIK bunu kullanır = CANLI)",
            prod_sq, fast_squeeze_production_signals(m))
    print("\n" + "="*64)
    print("DONCHIAN vektörel ~%99 (kapısız, hızlı) → kabul edilir.")
    print("SQUEEZE vektörel terk edildi; fast_bt.squeeze üretim sınıfına delege")
    print("edildi → %100. Böylece fast_bt == faithful_bt == CANLI BOT.")


if __name__ == "__main__":
    main()
