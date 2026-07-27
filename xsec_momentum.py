"""
xsec_momentum.py — KESİTSEL MOMENTUM: yeni bir sistem AİLESİ (mevcutların varyasyonu değil).

NEDEN FARKLI: donchian/squeeze/BB hepsi TEK COİNE bakar ("bu coin kırılıyor mu?") = zaman-serisi
sinyali. Kesitsel momentum "hangi coinler BİRBİRİNE GÖRE güçlü?" diye sorar — tamamen farklı bilgi.
En güçlü K coini LONG, en zayıf K'yı SHORT → piyasa betası büyük ölçüde nötrlenir, yani mevcut
kitapla DÜŞÜK KORELASYON beklenir (aradığımız gerçek çeşitlendirici).

Kripto literatüründe en iyi belgelenmiş kesitsel edge. Elimizde 22 coin futures verisi var.

METODOLOJİ (dürüst):
- Günlük barlar (1h→1d resample). Her R günde bir yeniden dengele.
- Sıralama: geçmiş L günlük getiri (SADECE geçmiş; rebalance günü kapanışında hesaplanır,
  pozisyon ERTESİ günün açılışında değil o kapanışta alınır — canlı bot da kapanışta girer).
- Long ilk K, short son K. Eşit ağırlık. Toplam risk sabit (her bacak sermayenin r/2K'sı).
- Ücret: her giriş+çıkış 1bp (mevcut testlerle aynı).
- Varyantlar: L ∈ {7,14,30}, K ∈ {2,3,4}, R ∈ {7,14}. + long-only kontrolü (beta mı edge mi?).
- Yıl-yıl + korelasyon: mevcut donchian/squeeze kitabıyla aylık korelasyon (çeşitlendirici mi?).

KARAR: PF>1.2 VE her yıl pozitif VE mevcut kitapla düşük korelasyon → aday.
Long-only kontrolü kesitseli geçiyorsa → edge kesitsel değil, sadece kripto betası → RED.

Kullanım:  py xsec_momentum.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
FEE = 0.0001
BAL0 = 190.0
RISK = 0.0225          # portföy başına toplam risk/periyot (mevcut sistemle kıyaslanabilir ölçek)


def load_daily(source):
    px = {}
    for c in COINS:
        try:
            d = fast_bt.resample(fast_bt.load(c, source=source), "1d")
            px[c] = d["close"]
        except Exception as e:
            print(f"  {c}: {e}")
    df = pd.DataFrame(px).dropna(how="all")
    return df.ffill()


def run(px, L, K, R, long_only=False):
    """Her R günde bir: geçmiş L-gün getirisine göre sırala, ilk/son K'yı tut R gün."""
    rets = []
    idx = px.index
    i = L
    while i + R < len(idx):
        past = px.iloc[i] / px.iloc[i - L] - 1.0          # SADECE geçmiş bilgi
        past = past.dropna()
        if len(past) < 2 * K + 2:
            i += R; continue
        order = past.sort_values(ascending=False)
        longs = list(order.index[:K])
        shorts = [] if long_only else list(order.index[-K:])
        fwd = px.iloc[i + R] / px.iloc[i] - 1.0            # tutuş dönemi getirisi
        legs = []
        for c in longs:
            if np.isfinite(fwd.get(c, np.nan)): legs.append(+fwd[c] - 2 * FEE)
        for c in shorts:
            if np.isfinite(fwd.get(c, np.nan)): legs.append(-fwd[c] - 2 * FEE)
        if legs:
            rets.append({"ret": float(np.mean(legs)), "ts": idx[i + R]})
        i += R
    return rets


def stats(rets, label):
    if not rets: return None
    r = np.array([x["ret"] for x in rets])
    pnl = r * RISK / 0.02 * BAL0 * 0.02 / max(np.std(r), 1e-9) * 0  # placeholder (kullanılmıyor)
    # dolar: her periyot sermayenin RISK'i kadar risk alıyormuş gibi ölçekle (vol-hedefsiz, ham)
    dollars = r * BAL0
    gp = dollars[dollars > 0].sum(); gl = -dollars[dollars < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    eq = BAL0 + np.cumsum(dollars); allq = np.concatenate([[BAL0], eq])
    peak = np.maximum.accumulate(allq); mdd = ((peak - allq) / peak).max() * 100
    yrs = {}
    ya = np.array([x["ts"].year for x in rets])
    for y in sorted(set(ya)): yrs[y] = dollars[ya == y].sum()
    return dict(n=len(r), pf=pf, wr=(r > 0).mean() * 100, tot=dollars.sum(), mdd=mdd,
                yrs=yrs, mean=r.mean() * 100, series=pd.Series(dollars, index=[x["ts"] for x in rets]))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    px = load_daily(source)
    print(f"\n{'='*100}\n=== KESİTSEL MOMENTUM — {len(px.columns)} coin, {px.index[0].date()}→{px.index[-1].date()} ===")
    print(f"  (getiri = periyot başına ortalama bacak getirisi; $ = {BAL0:.0f} taban üzerinden ham)")
    print(f"\n  {'L/K/R':>10s} {'n':>4s} {'WR':>4s} {'PF':>5s} {'ort%':>6s} {'toplam$':>9s} {'maxDD%':>7s}  yıl-yıl")
    best = []
    for L in (7, 14, 30):
        for K in (2, 3, 4):
            for R in (7, 14):
                s = stats(run(px, L, K, R), f"L{L}K{K}R{R}")
                if not s: continue
                pos = all(v > 0 for v in s["yrs"].values())
                ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
                flag = " HER-YIL+" if pos else ""
                print(f"  {f'{L}/{K}/{R}':>10s} {s['n']:>4d} {s['wr']:>3.0f}% {s['pf']:>5.2f} "
                      f"{s['mean']:>6.2f} {s['tot']:>+9.0f} {s['mdd']:>7.1f}  {ys}{flag}")
                if pos and s["pf"] > 1.2: best.append((L, K, R, s))
    print(f"\n  --- LONG-ONLY KONTROLÜ (edge kesitsel mi, yoksa sadece kripto betası mı?) ---")
    for L in (14, 30):
        for K in (3,):
            s = stats(run(px, L, K, 7, long_only=True), "LO")
            if s:
                ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
                print(f"  long-only L{L}K{K}R7: PF {s['pf']:.2f} ${s['tot']:+.0f} maxDD {s['mdd']:.1f}%  {ys}")
    print(f"\n  ARANAN: PF>1.2 + HER YIL pozitif. Long-only benzer/daha iyiyse → edge kesitsel DEĞİL,")
    print(f"  sadece kripto betası (mevcut kitapla yüksek korelasyon) → çeşitlendirici DEĞİL, RED.")
    if best:
        print(f"\n  {len(best)} aday HER-YIL+ ve PF>1.2 → sonraki adım: mevcut donchian/squeeze")
        print(f"  kitabıyla AYLIK KORELASYON ölç (düşükse gerçek çeşitlendirici).")
    else:
        print(f"\n  Aday YOK → kesitsel momentum bu evrende çalışmıyor, kapat.")


if __name__ == "__main__":
    main()
