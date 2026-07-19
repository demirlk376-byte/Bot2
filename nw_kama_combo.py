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


def simulate(df, entries, max_hold):
    hi = df["high"].values; lo = df["low"].values; cl = df["close"].values
    idx = df.index; n = len(cl)
    a = atr_fn(df["high"], df["low"], df["close"], 14).values
    tr = []; occ = -1
    for (i, d) in entries:
        if i <= occ or i >= n - 1 or np.isnan(a[i]) or a[i] <= 0:
            continue
        e = cl[i]; sld = SL_ATR * a[i]
        sl = e - d * sld; tp = e + d * TP_ATR * a[i]; ep = None; j = i
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
        tr.append({"r": R, "year": idx[i].year}); occ = j
    return tr


def rep(coin, tf, tr):
    if not tr:
        print(f"  {coin:5s} {tf:3s}  işlem yok (confluence hiç tetiklenmedi)", flush=True)
        return None
    r = np.array([t["r"] for t in tr]); yrs = np.array([t["year"] for t in tr])
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    usd = r.sum() * BAL * RISK
    per = {}
    line = f"  {coin:5s} {tf:3s}  n={len(r):>3d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${usd:+7.2f}"
    yrbits = []
    for yr in sorted(set(yrs.tolist())):
        ry = r[yrs == yr]; g1 = ry[ry > 0].sum(); g2 = -ry[ry < 0].sum()
        pfy = g1 / g2 if g2 > 0 else 9.99
        per[yr] = ry.sum() * BAL * RISK
        yrbits.append(f"{yr}:${per[yr]:+.0f}(PF{pfy:.2f})")
    print(line + "   " + " ".join(yrbits), flush=True)
    return dict(coin=coin, tf=tf, n=len(r), pf=pf, usd=usd,
                yrs_pos=all(v > 0 for v in per.values()))


def main():
    coins = [c.strip().upper() for c in (sys.argv[1] if len(sys.argv) > 1 else "BTC").split(",")]
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    print(f"NW+KAMA CONFLUENCE (ikisi de aynı yön) — {coins} @ {TFS}")
    print(f"NW(h{NW_H},win{NW_WIN},x{NW_MULT}) KAMA(er{KAMA_ER}) SL{SL_ATR}ATR TP{TP_ATR}ATR")
    summary = []
    for coin in coins:
        print(f"\n{'='*72}\n=== {coin} ===", flush=True)
        try:
            m = fast_bt.load(coin, source=source)
        except Exception as e:
            print(f"  {coin} veri hatası: {e}", flush=True); continue
        for tf in TFS:
            d = fast_bt.resample(m, tf)
            row = rep(coin, tf, simulate(d, combo_signals(d), TF_MAXHOLD[tf]))
            if row:
                summary.append(row)
    # ── Özet ──
    print(f"\n{'='*72}\n=== ÖZET — NW+KAMA confluence (araştırma, canlı sınıfı yok) ===", flush=True)
    if not summary:
        print("  Hiç işlem yok — confluence çok seçici (NW dip + KAMA trend nadir çakışıyor).")
        print("  Gevşetme seçenekleri: KAMA'yı sadece eğim (close şartsız), ya da N-bar tolerans.")
        return
    for row in sorted(summary, key=lambda x: -x["usd"]):
        flag = "✅her yıl+" if row["yrs_pos"] else ""
        print(f"  {row['coin']:5s} {row['tf']:3s}  ${row['usd']:+7.2f}  PF{row['pf']:.2f}  n={row['n']:<3d} {flag}", flush=True)
    tot = sum(r["usd"] for r in summary)
    print(f"\n  Toplam (tüm coin×TF): ${tot:+.2f}")
    print("  PF>1.3 + makul n + çok coinde + olan TF'ler umut verici. İyi çıkarsa üretim sınıfı.")


if __name__ == "__main__":
    main()
