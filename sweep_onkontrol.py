"""
sweep_onkontrol.py — ON-KONTROL (deploy adayi DEGIL, sadece kapi acik mi olcumu).

nk_range.py sweep ucluşunu ZATEN olcmustu AMA uc sey FARKLI:
  (a) seviye = yuvarlanan N-bar ekstremi   (kullanici: TAKVIM PDH/PDL/PWH/PWL)
  (b) ihlal = "hi >= hh" (DOKUNMA da sayiliyor)  (kullanici: ANLIK IHLAL = gercek delme)
  (c) min delme derinligi hic taranmadi     (research_liquidity_sweep'te vardi ama 0.0 sabit)

Burada (a)+(b)+(c) birlikte olculuyor. DOZ-YANIT mantigi: "gercek sweep" bilgi tasiyorsa
delme derinligi arttikca ortalama R ARTMALI. Duz cikarsa bilgi yok (ledger'in MTF-theta testi).

Kayma = 15.85bp/stop_mesafesi DAHIL. Long/short AYRI (kisit 2). TEST dilimi >= 2025-01-01.
Kullanım: py sweep_onkontrol.py local
"""
import sys
import numpy as np
import pandas as pd
import fast_bt
from indicators import atr as atr_fn

ALL22 = ["AAVE","ADA","ALGO","ATOM","AVAX","BCH","BNB","BTC","DOGE","DOT","ETC",
         "ETH","ICP","LINK","LTC","NEAR","SOL","TRX","VET","XLM","XMR","XRP"]
FEE = 0.0001
KAYMA = 15.85 / 1e4
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
RR, MH, BUF = 1.667, 48, 0.25      # nk_range merkeziyle uyumlu; BUF = wick otesi tampon


def seviyeler(m1h, tf, periyot):
    """TAKVIM seviyesi: onceki TAM GUN/HAFTA yuksek-dusuk.
    label='left', closed='left' -> etiket periyodun BASI. shift(1) = ONCEKI tamamlanmis
    periyot, o etiket aninda BILINIYOR. ffill ile bara eslenir -> LOOKAHEAD YOK."""
    d = fast_bt.resample(m1h, tf)
    rule = "1D" if periyot == "D" else "W-MON"
    p = (m1h.resample(rule, label="left", closed="left")
             .agg({"high": "max", "low": "min"}).dropna())
    ph = p["high"].shift(1).reindex(d.index, method="ffill")
    pl = p["low"].shift(1).reindex(d.index, method="ffill")
    return d, ph.values, pl.values


def kos(d, PH, PL, derinlik):
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    at = atr_fn(d["high"], d["low"], d["close"], 14).values
    idx, n = d.index, len(cl)
    out, occ = [], -1
    for i in range(20, n - 1):
        if i <= occ:
            continue
        a = at[i]
        if not np.isfinite(a) or a <= 0 or not np.isfinite(PH[i]) or not np.isfinite(PL[i]):
            continue
        d_ = 0
        # LONG sweep: PDL'yi en az derinlik*ATR DELDI ama kapanis PDL'nin USTUNDE
        if lo[i] < PL[i] - derinlik * a and cl[i] > PL[i]:
            d_, sl = 1, lo[i] - BUF * a
        # SHORT sweep: PDH'yi deldi, kapanis altinda
        elif hi[i] > PH[i] + derinlik * a and cl[i] < PH[i]:
            d_, sl = -1, hi[i] + BUF * a
        if d_ == 0:
            continue
        e = cl[i]; sld = abs(e - sl)
        if sld <= 0:
            continue
        tp = e + d_ * RR * sld
        ep, j = None, i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, R, sld / e, d_))
        occ = j
    return out


def rapor(out, etiket):
    if len(out) < 20:
        print(f"  {etiket:<46} n={len(out)} (az)")
        return
    R = np.array([o[1] for o in out]); sp = np.array([o[2] for o in out])
    yn = np.array([o[3] for o in out]); gi = np.array([o[0] for o in out])
    Rk = R - KAYMA / sp
    def s(m):
        if m.sum() < 20: return f"n={m.sum():>5} —"
        r = Rk[m]; r0 = R[m]
        return (f"n={m.sum():>5} sl%={np.median(sp[m])*100:>5.2f} "
                f"HAM={r0.mean():+.4f} KAYMALI={r.mean():+.4f} "
                f"z={r.mean()/r.std(ddof=1)*np.sqrt(len(r)):+.2f}")
    L = yn == 1; T = gi >= SPLIT.value
    print(f"  {etiket:<24}\n    LONG      {s(L)}\n    LONG-TEST {s(L & T)}\n    SHORT     {s(~L)}")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in ALL22:
        try: raw[c] = fast_bt.load(c, source=src)
        except Exception: pass
    print(f"\nyuklenen: {len(raw)} coin | rr={RR} mh={MH} buf={BUF}xATR | kayma DAHIL")
    for periyot, tfs in [("D", ["4h"])]:
        for tf in tfs:
            hz = {}
            for c in raw:
                d, PH, PL = seviyeler(raw[c], tf, periyot)
                for dr in [0.0, 0.10, 0.25, 0.50]:
                    hz.setdefault(dr, []).extend(kos(d, PH, PL, dr))
            print(f"\n=== takvim seviyesi P{periyot}H/P{periyot}L · bar={tf} · DOZ-YANIT (delme derinligi) ===")
            for dr in [0.0, 0.10, 0.25, 0.50]:
                rapor(hz[dr], f"derinlik={dr:.2f}xATR")


if __name__ == "__main__":
    main()
