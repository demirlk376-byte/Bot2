"""
verify_conformance.py — fast_bt vektörel sinyalleri == ÜRETİM sınıfı sinyalleri?

Kritik güven sorusu: fast_bt stratejilerin AYRI (hızlı) kopyası. Canlı bot
ise ÜRETİM sınıflarını (DonchianStrategy/SqueezeStrategy) kullanıyor. İkisi
sapıyorsa fast_bt sonuçları YALAN ve bot testteki gibi çalışmaz.

Bu script aynı veride HER İKİSİNİ koşar (üretim sınıfı bar-bar, canlının
yaptığı gibi bounded pencereyle) ve sinyalleri bar-bar karşılaştırır. Birebir
eşleşme = fast_bt güvenilir + canlı bot testteki gibi çalışacak.

Kullanım (yerel BTC verisiyle):  python verify_conformance.py
"""
from __future__ import annotations
import glob
import numpy as np
import pandas as pd

from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy
from indicators import atr as atr_fn
import fast_bt


def load_btc():
    fr = []
    for f in sorted(glob.glob("BTCUSDT-1m-*.csv")):
        d = pd.read_csv(f); d.columns = ["ts","o","h","l","c","v","ct","qv","n","a","b","g"]
        fr.append(d[["ts","o","h","l","c","v"]].astype(float))
    m = pd.concat(fr).drop_duplicates("ts").sort_values("ts")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return m.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"}).drop(columns=["ts"])


def prod_donchian_signals(m):
    """Üretim DonchianStrategy, bar-bar, canlının beslediği pencereyle (260 4h)."""
    d4 = fast_bt.resample(m, "4h")
    strat = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200)
    atr4 = atr_fn(d4["high"], d4["low"], d4["close"], 14)
    sig = set()
    for i in range(260, len(d4)):
        sub = d4.iloc[max(0, i-259):i+1]
        a = atr4.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        s = strat.analyze(sub, float(a))
        if s.direction != 0:
            sig.add((d4.index[i], s.direction))
    return sig


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


def prod_squeeze_signals(m):
    """Üretim SqueezeStrategy, bar-bar, 120 barlık pencere (canlı get_candles(120))."""
    d1 = fast_bt.resample(m, "1h")
    strat = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    atr1 = atr_fn(d1["high"], d1["low"], d1["close"], 14)
    sig = set()
    for i in range(260, len(d1)):
        sub = d1.iloc[max(0, i-119):i+1]
        a = atr1.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        s = strat.analyze(sub, float(a))
        if s.direction != 0:
            sig.add((d1.index[i], s.direction))
    return sig


def fast_squeeze_signals(m):
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
    for i in np.where(release.values)[0]:
        if i < 260: continue
        dd = int(direction[i])
        agree = (dir4.values[i] and dd == 1) or ((not dir4.values[i]) and dd == -1)
        if agree:
            sig.add((d.index[i], dd))
    return sig


def compare(name, prod, fast):
    only_prod = prod - fast
    only_fast = fast - prod
    both = prod & fast
    print(f"\n=== {name} ===")
    print(f"  üretim sınıfı : {len(prod)} sinyal")
    print(f"  fast_bt       : {len(fast)} sinyal")
    print(f"  ORTAK         : {len(both)}")
    print(f"  yalnız üretim : {len(only_prod)}")
    print(f"  yalnız fast   : {len(only_fast)}")
    if not only_prod and not only_fast:
        print(f"  ✅ BİREBİR EŞLEŞME — fast_bt = üretim sınıfı, canlı testteki gibi çalışır")
    else:
        match_pct = len(both) / max(len(prod | fast), 1) * 100
        print(f"  ⚠️ %{match_pct:.1f} örtüşme — SAPMA VAR, güvenilmez")
        for s in sorted(only_prod)[:3]:
            print(f"    yalnız üretim: {s[0]} dir={s[1]}")
        for s in sorted(only_fast)[:3]:
            print(f"    yalnız fast:   {s[0]} dir={s[1]}")


def main():
    print("BTC yerel veri yükleniyor + iki yöntemle sinyaller...")
    m = load_btc()
    compare("DONCHIAN", prod_donchian_signals(m), fast_donchian_signals(m))
    compare("SQUEEZE", prod_squeeze_signals(m), fast_squeeze_signals(m))
    print("\n" + "="*60)
    print("Birebir eşleşme = fast_bt sonuçları GÜVENİLİR ve canlı bot")
    print("(üretim sınıflarını kullanır) testteki sinyallerin AYNISINI üretir.")


if __name__ == "__main__":
    main()
