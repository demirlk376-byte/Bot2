"""
fade_test.py — BREAKOUT FADE: kendi bulgumuzu ters çevirip çeşitlendirici ara (hedge mode GEREKMEZ).

GEREKÇE (bugün kendi verimizle kanıtlandı):
  - Donchian breakout'larının %76.5'i 1R'ye BİLE ulaşmadan sönüyor (mfe_anatomy).
  - Kötü aylar = CHOP ayları: düşük ADX, fiyat önceki-40 kanalın içinde sıkışmış (worst_month/regime).
→ HİPOTEZ: "kanal kırıldı AMA ADX DÜŞÜK (trend yok)" durumunda kırılımı TAKİP etmek yerine FADE et.
  Yapısal olarak trend-takibiyle TERS korelasyon beklenir → bizim kaybettiğimiz rejimde kazanır.

ÇAKIŞMA YOK: sadece SERBEST coinlerde (deploy'da kullanılmayan 10 coin) → hedge mode gerekmez,
kod değişikliği pairs'teki gibi karmaşık değil (tek bacak, normal SL/TP, mevcut altyapıyla aynı).

KURULUM (donchian'ın aynası):
  Giriş: close > kanal_üst (kırılım) VE ADX < eşik → SHORT (fade). close < kanal_alt VE ADX<eşik → LONG.
  SL = k×ATR, TP = rr × SL. Mean-reversion olduğu için rr DÜŞÜK denenir (1.0/1.5) + trend'in 2.5'i.
  Coin başına tek pozisyon (occ), canlı boyut (notional tavanı dahil).

DÜRÜSTLÜK: bu bizim verimizden doğan bir hipotez → overfit riski var. Bu yüzden
(a) parametre taranıyor ama HER YIL pozitif + TEST(2025-26) pozitif şartı,
(b) kitapla AYLIK KORELASYON ölçülüyor (çeşitlendirici mi, yoksa sadece başka bir kâr akışı mı),
(c) ADX eşiği yükseldikçe monotonik davranış bekleniyor (yoksa gürültü).

Kullanım:  py fade_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.0
DEPLOYED = {"ADA", "BCH", "BNB", "DOGE", "ETH", "ICP", "LTC", "NEAR", "SOL", "TRX", "XLM", "XRP"}
FREE = ["AAVE", "ALGO", "ATOM", "AVAX", "BTC", "DOT", "ETC", "LINK", "VET", "XMR"]
CHANNEL, SL_A, MH = 40, 2.0, 30


def gen(m, adx_max, rr, tf="4h"):
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    ch_hi = d["high"].rolling(CHANNEL).max().shift(1).values
    ch_lo = d["low"].rolling(CHANNEL).min().shift(1).values
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i])): continue
        ax = adx_ser[i]
        if not np.isfinite(ax) or ax >= adx_max: continue    # SADECE trendsiz rejim
        c = cl[i]
        if c > ch_hi[i]: d_ = -1        # yukarı kırılım + trend yok → FADE (short)
        elif c < ch_lo[i]: d_ = +1      # aşağı kırılım + trend yok → FADE (long)
        else: continue
        e = c; sld = SL_A * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append({"R": R, "sl_pct": sld / e, "exit": idx[j], "year": idx[i].year}); occ = j
    return out


def summ(trs):
    if not trs: return None
    r = np.array([t["R"] for t in trs])
    eff = np.minimum(RISKF, CAP * np.array([t["sl_pct"] for t in trs]))
    pnl = r * eff * BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    ya = np.array([t["year"] for t in trs])
    yrs = {y: pnl[ya == y].sum() for y in sorted(set(ya))}
    mon = pd.Series(pnl, index=[pd.Timestamp(t["exit"]).to_period("M") for t in trs]).groupby(level=0).sum()
    return dict(n=len(r), pf=pf, wr=(r > 0).mean() * 100, tot=pnl.sum(), yrs=yrs, mon=mon,
                test=pnl[ya >= 2025].sum())


def book_monthly():
    import deployed_backtest as DB
    tr = []
    for c in DB.DONCH: tr += DB.gen("donchian", fast_bt.load(c, source="local"))
    for c in DB.SQZ: tr += DB.gen("squeeze", fast_bt.load(c, source="local"))
    taken = DB.seat_select(tr)
    r = np.array([R for _, R, _ in taken]); sl = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(DB.RISKF, DB.CAP * sl) * DB.BAL0
    return pd.Series(pnl, index=[pd.Timestamp(x).to_period("M") for x, _, _ in taken]).groupby(level=0).sum()


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    ms = {c: fast_bt.load(c, source=source) for c in FREE}
    print(f"\n{'='*104}\n=== BREAKOUT FADE (trendsiz rejim, {len(FREE)} SERBEST coin — çakışma YOK) ===")
    print(f"  {'ADX<':>5s} {'rr':>4s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s} {'TEST$':>7s}  yıl-yıl                              bayrak")
    results = {}
    for adx_max in (15, 20, 25):
        for rr in (1.0, 1.5, 2.5):
            trs = []
            for c in FREE: trs += gen(ms[c], adx_max, rr)
            s = summ(trs)
            if not s: continue
            results[(adx_max, rr)] = s
            pos = all(v > 0 for v in s["yrs"].values())
            ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
            flag = "HER-YIL+" if pos else ""
            if pos and s["test"] > 0: flag += " ★"
            print(f"  {adx_max:>5d} {rr:>4.1f} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} "
                  f"{s['tot']:>+9.0f} {s['test']:>+7.0f}  {ys}  {flag}")
    # korelasyon: en iyi adaylar
    bk = book_monthly()
    print(f"\n  --- KİTAPLA AYLIK KORELASYON (çeşitlendirici mi?) ---")
    for key, s in sorted(results.items(), key=lambda kv: -kv[1]["tot"])[:5]:
        j = pd.concat({"f": s["mon"], "b": bk}, axis=1).dropna()
        if len(j) < 10: continue
        corr = j["f"].corr(j["b"])
        bad = j[j["b"] < 0]
        print(f"  ADX<{key[0]} rr{key[1]}: korr {corr:+.2f} | kitabın kayıp aylarında ${bad['f'].sum():+.0f} "
              f"({(bad['f']>0).sum()}/{len(bad)} ay pozitif) | birlikte ${(j['f']+j['b']).sum():+.0f} vs kitap ${j['b'].sum():+.0f}")
    print(f"\n  ARANAN: HER-YIL+ VE TEST(2025-26)+ VE kitapla korr < +0.3 → gerçek çeşitlendirici.")
    print(f"  ADX eşiği yükseldikçe monotonik bozulma bekleniyor (trend arttıkça fade kötüleşmeli);")
    print(f"  monotonik DEĞİLSE gürültü olabilir.")


if __name__ == "__main__":
    main()
