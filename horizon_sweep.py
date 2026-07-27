"""
horizon_sweep.py — ÇOKLU HORİZON: profesyonel CTA standardı + kendi parametremizin denetimi.

KAYNAK (web araştırması, 2026-07): çoklu-lookback ensemble managed-futures endüstri standardı.
"Hiçbir tek horizon tüm ortamları yakalayamaz; hız çeşitliliği zamanlama riskini dağıtır."
Yavaş+hızlı trend karışımı Sharpe'ı artırıp drawdown'ı düşürüyor; farklı frekanslardaki TSMOM
düşük korelasyonlu.

BİZ TEK HORİZONDA ÇALIŞIYORUZ (kanal=40, 4h ≈ 6.7 gün). Bu araç iki şeyi yapar:
  1) ÖZ-DENETİM: 40 gerçekten iyi mi, yoksa ŞANSLI SEÇİM mi? Diğer horizonlar da çalışıyorsa
     parametre sağlam; SADECE 40 çalışıyorsa deploy'daki sistem PARAMETRE-KIRILGAN (kötü haber).
  2) ENSEMBLE ÖN-KOŞULU: horizonlar arası AYLIK KORELASYON. Düşükse harmanlama gerçek
     çeşitlendirme sağlar; yüksekse aynı şeyin kopyaları, harmanlamanın faydası olmaz.

Donchian mantığı VEKTÖRİZE (production sınıfıyla birebir: kanal = önceki N bar, mevcut HARİÇ →
rolling(N).max().shift(1); long: close>kanal_üst VE close>EMA200). kanal=40 satırı bilinen
donchian sonucuyla eşleşmeli = ÖZ-DENETİM.

Kullanım:  py horizon_sweep.py local
"""
import sys, itertools
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, ema as ema_fn

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.0
COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
CHANNELS = [20, 30, 40, 60, 80, 120]
SL_A, RR, MH = 2.0, 2.5, 30


def gen(m, channel):
    d = fast_bt.resample(m, "4h")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    ema200 = ema_fn(d["close"], 200).values
    # production DonchianStrategy ile birebir: önceki `channel` bar, mevcut HARİÇ
    ch_hi = d["high"].rolling(channel).max().shift(1).values
    ch_lo = d["low"].rolling(channel).min().shift(1).values
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i]) and np.isfinite(ema200[i])): continue
        c = cl[i]
        if c > ch_hi[i] and c > ema200[i]: d_ = 1
        elif c < ch_lo[i] and c < ema200[i]: d_ = -1
        else: continue
        e = c; sld = SL_A * a; slp = e - d_ * sld; tp = e + d_ * RR * sld; ep = None; j = i
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


def summarize(trs):
    r = np.array([t["R"] for t in trs])
    eff = np.minimum(RISKF, CAP * np.array([t["sl_pct"] for t in trs]))
    pnl = r * eff * BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    allq = np.concatenate([[BAL0], BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(allq); mdd = ((peak - allq) / peak).max() * 100
    ya = np.array([t["year"] for t in trs])
    yrs = {y: pnl[ya == y].sum() for y in sorted(set(ya))}
    mon = pd.Series(pnl, index=[pd.Timestamp(t["exit"]).to_period("M") for t in trs]).groupby(level=0).sum()
    return dict(n=len(r), pf=pf, wr=(r > 0).mean() * 100, tot=pnl.sum(), mdd=mdd, yrs=yrs, mon=mon)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    ms = {c: fast_bt.load(c, source=source) for c in COINS}
    print(f"\n{'='*104}\n=== HORİZON TARAMASI (donchian kanal, 7 coin, canlı boyut) — 40 şanslı seçim mi? ===")
    print(f"  {'kanal':>6s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'toplam$':>9s} {'maxDD%':>7s}  yıl-yıl                                    bayrak")
    res = {}
    for ch in CHANNELS:
        trs = []
        for c in COINS: trs += gen(ms[c], ch)
        s = summarize(trs); res[ch] = s
        pos = all(v > 0 for v in s["yrs"].values())
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        mark = "◄ DEPLOY" if ch == 40 else ""
        print(f"  {ch:>6d} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['tot']:>+9.0f} {s['mdd']:>7.1f}  {ys}  "
              f"{'HER-YIL+' if pos else 'karışık ':8s}{mark}")

    print(f"\n  --- HORİZONLAR ARASI AYLIK KORELASYON (ensemble faydası olur mu?) ---")
    hdr = "        " + " ".join(f"{c:>6d}" for c in CHANNELS)
    print(hdr)
    for a in CHANNELS:
        row = f"  {a:>5d} "
        for b in CHANNELS:
            j = pd.concat({"a": res[a]["mon"], "b": res[b]["mon"]}, axis=1).dropna()
            row += f" {j['a'].corr(j['b']):>6.2f}" if len(j) > 5 else "     —"
        print(row)

    # basit ensemble: her horizon eşit risk payı (risk/len), aylık serileri topla
    print(f"\n  --- ENSEMBLE (eşit risk payı, aylık seriler toplanır) ---")
    for combo in [(20, 40, 80), (20, 40, 60, 80), (30, 60, 120), tuple(CHANNELS)]:
        w = 1.0 / len(combo)
        s = None
        for ch in combo:
            m = res[ch]["mon"] * w
            s = m if s is None else s.add(m, fill_value=0.0)
        ya = np.array([p.year for p in s.index])
        yrs = {y: s.values[ya == y].sum() for y in sorted(set(ya))}
        eq = np.cumsum(s.values); pk = np.maximum.accumulate(np.concatenate([[0], eq]))
        mdd_d = (pk - np.concatenate([[0], eq])).max()
        pos = all(v > 0 for v in yrs.values())
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in yrs.items())
        print(f"  {str(combo):22s} toplam ${s.sum():>+7.0f}  en kötü ay ${s.min():>+6.0f}  maxDD ${mdd_d:>5.0f}  {ys}"
              f"  {'HER-YIL+' if pos else ''}")
    print(f"\n  40 tek başına: ${res[40]['tot']:+.0f} (karşılaştırma tabanı; ensemble bunu HER YIL geçmeli)")
    print(f"  Korelasyonlar YÜKSEKSE (>0.7) → horizonlar aynı şeyin kopyası, ensemble faydasız.")
    print(f"  SADECE 40 çalışıyorsa → deploy'daki sistem PARAMETRE-KIRILGAN (ciddi uyarı).")


if __name__ == "__main__":
    main()
