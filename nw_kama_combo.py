"""
nw_kama_combo.py — NW + KAMA BİRLEŞİK tek strateji (confluence).
SADECE İKİSİ DE aynı yönde sinyal verince girer:
  • NW (Nadaraya-Watson, causal kernel mean-reversion): close alt banda inince
    long, üst bandı aşınca short (aşırı satım/alım).
  • KAMA (Kaufman adaptif MA, trend): close KAMA üstünde ve KAMA yükseliyorsa
    long-yön, close KAMA altında ve KAMA düşüyorsa short-yön.
  → LONG: NW long VE KAMA long-yön.  SHORT: NW short VE KAMA short-yön.
    ("trend yönünde dip/tepe" — mean-rev'i trend filtresiyle birleştirir.)

ARAŞTIRMA backtest'i: look-ahead YOK (NW+KAMA causal), giriş sinyal barı
close'unda, ATR SL/TP, taker fee iki bacak, kötümser intrabar (SL önce),
max-hold. Canlı SINIFI yok — iyi çıkarsa üretim sınıfı yazıp canlı-birebir yaparız.

TF: 4h, 1d, 2d (1h cache'ten resample). Veri: MEXC VADELİ (cache).
Kullanım:
  python nw_kama_combo.py SOL,ETH,XRP,DOGE          # VPS (MEXC fetch + cache)
  py nw_kama_combo.py SOL,ETH,XRP,DOGE local         # PC (cache, ÇEVRİMDIŞI)
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn

BAL = 190.0
FEE = 0.0001
RISK = 0.02

# Strateji parametreleri (v1 — makul başlangıç, sonra grid'leyebiliriz)
NW_H, NW_WIN, NW_MULT = 8.0, 50, 2.0
KAMA_ER, KAMA_FAST, KAMA_SLOW = 10, 2, 30
KAMA_TREND_N = 10   # KAMA trend yönü = KAMA[t] vs KAMA[t-N] (tek-bar eğim değil; tek
#                     barlık dip geniş trendi çevirmesin diye — yoksa confluence hiç fire etmiyor)
SL_ATR, TP_ATR = 3.0, 5.0
# TF başına max-hold (bar): 4h→30 (5g), 1d→20 (20g), 2d→12 (24g)
TF_MAXHOLD = {"4h": 30, "1d": 20, "2d": 12}
TFS = ["4h", "1d", "2d"]


def nadaraya_causal(close, h=NW_H, window=NW_WIN):
    """Endpoint (causal) NW — yhat[t] sadece t'ye kadarki barları kullanır (repaint yok)."""
    n = len(close); yhat = np.full(n, np.nan)
    k = np.arange(window); w = np.exp(-(k ** 2) / (2 * h * h)); ws = w.sum()
    for t in range(window - 1, n):
        seg = close[t - window + 1:t + 1][::-1]
        yhat[t] = float((seg * w).sum() / ws)
    return yhat


def kama(close, er=KAMA_ER, fast=KAMA_FAST, slow=KAMA_SLOW):
    n = len(close); out = np.full(n, np.nan)
    fsc = 2.0 / (fast + 1); ssc = 2.0 / (slow + 1)
    for t in range(er, n):
        change = abs(close[t] - close[t - er])
        vol = np.abs(np.diff(close[t - er:t + 1])).sum()
        e = change / vol if vol > 0 else 0.0
        sc = (e * (fsc - ssc) + ssc) ** 2
        prev = out[t - 1] if not np.isnan(out[t - 1]) else close[t - 1]
        out[t] = prev + sc * (close[t] - prev)
    return out


def combo_signals(df):
    """İkisi de aynı yönde → sinyal. NW mean-rev + KAMA trend confluence."""
    close = df["close"].values
    yhat = nadaraya_causal(close)
    mae = pd.Series(np.abs(close - yhat)).rolling(NW_WIN).mean().values
    k = kama(close)
    out = []
    for t in range(KAMA_TREND_N, len(close)):
        if np.isnan(yhat[t]) or np.isnan(mae[t]) or mae[t] <= 0 or np.isnan(k[t]) or np.isnan(k[t - KAMA_TREND_N]):
            continue
        upper = yhat[t] + NW_MULT * mae[t]; lower = yhat[t] - NW_MULT * mae[t]
        nw = 1 if close[t] < lower else (-1 if close[t] > upper else 0)
        kd = 1 if k[t] > k[t - KAMA_TREND_N] else (-1 if k[t] < k[t - KAMA_TREND_N] else 0)   # N-bar trend yönü
        # LONG: NW dip (aşırı satım) VE KAMA yükseliyor (trend yukarı) = trend yönünde dipten al
        # SHORT: NW tepe (aşırı alım) VE KAMA düşüyor = trend yönünde tepeden sat
        if nw == 1 and kd == 1:
            out.append((t, 1))
        elif nw == -1 and kd == -1:
            out.append((t, -1))
    return out


def nw_only_signals(df):
    """SADECE NW (orijinal): close alt banda inince long, üst bandı aşınca short."""
    close = df["close"].values
    yhat = nadaraya_causal(close)
    mae = pd.Series(np.abs(close - yhat)).rolling(NW_WIN).mean().values
    out = []
    for t in range(len(close)):
        if np.isnan(yhat[t]) or np.isnan(mae[t]) or mae[t] <= 0:
            continue
        if close[t] < yhat[t] - NW_MULT * mae[t]:
            out.append((t, 1))
        elif close[t] > yhat[t] + NW_MULT * mae[t]:
            out.append((t, -1))
    return out


def kama_only_signals(df):
    """SADECE KAMA (orijinal): close yükselen KAMA'yı yukarı keserse long,
    düşen KAMA'yı aşağı keserse short (trend-takip)."""
    close = df["close"].values
    k = kama(close)
    out = []
    for t in range(1, len(close)):
        if np.isnan(k[t]) or np.isnan(k[t - 1]):
            continue
        up = k[t] > k[t - 1]
        cross_up = close[t - 1] <= k[t - 1] and close[t] > k[t]
        cross_dn = close[t - 1] >= k[t - 1] and close[t] < k[t]
        if cross_up and up:
            out.append((t, 1))
        elif cross_dn and not up:
            out.append((t, -1))
    return out


# strateji → (sinyal fonksiyonu, SL×ATR, TP×ATR)  — orijinal araştırmadaki çıkışlar
STRATS = {
    "nw":    (nw_only_signals,   3.0, 5.0),   # mean-rev: SL3 TP5 (BB gibi)
    "kama":  (kama_only_signals, 2.0, 4.0),   # trend: SL2 TP4 (RR2)
    "combo": (combo_signals,     3.0, 5.0),   # confluence
}


def simulate(df, entries, max_hold, sl_atr, tp_atr):
    hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    idx = df.index; n = len(cl)
    a = atr_fn(df["high"], df["low"], df["close"], 14).values
    tr = []; occ = -1
    for (i, d) in entries:
        if i <= occ or i >= n - 1 or np.isnan(a[i]) or a[i] <= 0:
            continue
        e = cl[i]; sld = sl_atr * a[i]
        sl = e - d * sld; tp = e + d * tp_atr * a[i]; ep = None; j = i
        for j in range(i + 1, min(i + 1 + max_hold, n)):
            if d == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + max_hold, n - 1); ep = cl[j]
        R = d * (ep - e) / sld - 2 * FEE * e / sld   # R = SL-mesafesi biriminde
        tr.append({"r": R, "year": idx[i].year, "dir": d}); occ = j
    return tr


def rep(strat, coin, tf, tr):
    if not tr:
        print(f"    {strat:5s} {coin:5s} {tf:3s}  işlem yok", flush=True)
        return None
    r = np.array([t["r"] for t in tr]); yrs = np.array([t["year"] for t in tr])
    dirs = np.array([t["dir"] for t in tr])
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    usd = r.sum() * BAL * RISK
    per = {}
    for yr in sorted(set(yrs.tolist())):
        ry = r[yrs == yr]; per[yr] = ry.sum() * BAL * RISK
    l = r[dirs == 1]; s = r[dirs == -1]
    l_usd = l.sum() * BAL * RISK if len(l) else 0.0
    s_usd = s.sum() * BAL * RISK if len(s) else 0.0
    print(f"    {strat:5s} {coin:5s} {tf:3s}  n={len(r):>3d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} "
          f"${usd:+7.2f}   L${l_usd:+6.1f}(n{len(l)}) S${s_usd:+6.1f}(n{len(s)})", flush=True)
    return dict(strat=strat, coin=coin, tf=tf, n=len(r), pf=pf, usd=usd,
                l_usd=l_usd, s_usd=s_usd, yrs_pos=all(v > 0 for v in per.values()))


def main():
    coins = [c.strip().upper() for c in (sys.argv[1] if len(sys.argv) > 1 else "BTC").split(",")]
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    print(f"NW / KAMA / COMBO — AYRI AYRI test (strateji mi kötü, combo kurgusu mu?)")
    print(f"{coins} @ {TFS}  NW(h{NW_H},win{NW_WIN},x{NW_MULT}) KAMA(er{KAMA_ER},trendN{KAMA_TREND_N})")
    summary = []
    for coin in coins:
        print(f"\n{'='*74}\n=== {coin} ===", flush=True)
        try:
            m = fast_bt.load(coin, source=source)
        except Exception as e:
            print(f"  {coin} veri hatası: {e}", flush=True); continue
        for tf in TFS:
            d = fast_bt.resample(m, tf)
            for sname, (fn, sl_a, tp_a) in STRATS.items():
                row = rep(sname, coin, tf, simulate(d, fn(d), TF_MAXHOLD[tf], sl_a, tp_a))
                if row:
                    summary.append(row)
    # ── Özet: her strateji için toplam + en iyi hücre ──
    print(f"\n{'='*74}\n=== ÖZET — strateji karşılaştırması (araştırma; hepsi canlı sınıfsız) ===", flush=True)
    for sname in STRATS:
        rows = [r for r in summary if r["strat"] == sname]
        if not rows:
            print(f"  {sname:5s}: işlem yok"); continue
        tot = sum(r["usd"] for r in rows)
        lt = sum(r["l_usd"] for r in rows); st = sum(r["s_usd"] for r in rows)
        best = max(rows, key=lambda x: x["usd"])
        npos = sum(1 for r in rows if r["usd"] > 0)
        print(f"  {sname:5s}: TOPLAM ${tot:+7.2f}  (LONG ${lt:+.0f} / SHORT ${st:+.0f})  "
              f"pozitif hücre {npos}/{len(rows)}  en iyi: {best['coin']}{best['tf']} ${best['usd']:+.1f}PF{best['pf']:.2f}", flush=True)
        # her strateji için TF bazında long-only
        for tf in TFS:
            trows = [r for r in rows if r["tf"] == tf]
            if trows:
                print(f"         {tf}: ${sum(r['usd'] for r in trows):+7.2f}  (LONG ${sum(r['l_usd'] for r in trows):+.0f})", flush=True)
    print("\n  Bir strateji TEK BAŞINA çok coinde + / PF>1.3 ise → o iyi, combo kurgum kötüymüş.")
    print("  Üçü de zayıfsa → NW/KAMA ailesi bu coinlerde edge vermiyor, kapatırız.")


if __name__ == "__main__":
    main()
