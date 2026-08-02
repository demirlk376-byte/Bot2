"""
pairs_verify.py — TEK HAYATTA KALANI YÜKSELTİLMİŞ BARLA YENİDEN SINA.

BAĞLAM: pairs spread, bu oturumda hem OOS hem her-yıl barajını geçen TEK bulgu
(z2.0/0.5/3.5: PF1.63 $+532, TRAIN+321 TEST+211, 4/4 yıl+, kitapla korr −0.362).
AMA **ESKİ BARLA** doğrulandı. Bugün bar yükseltildi çünkü eskisi:
  • büyüklük körüydü → $4'lük ADX gürültüsünü KABUL etti
  • permütasyon istemiyordu → Hurst boyutlandırma ham p=0.10 ile "geçmiş" görünüyordu
  • çoklu-test saymıyordu
Altyapı yazmadan ÖNCE pairs'i yeni barla sınamak zorundayım; yoksa sahte pozitife bina kurarım.

YENİ BAR:
  (a) TRAIN'de seç → TEST'te geç → HER YIL geç      [eski bar, korunuyor]
  (b) BÜYÜKLÜK: Δ tabanın ≥%2'si                     [yeni]
  (c) DOZ-TEPKİ: z eşiği sıkılaştıkça davranış tutarlı olmalı   [yeni]
  (d) PERMÜTASYON: aynı sayıda işlem, RASTGELE zamanlama → p<0.05  [yeni]
  (e) ÇOKLU TEST: taranan çift-sayısı × z-konfig sayısına göre Šidák   [yeni]
  (f) YOĞUNLAŞMA: kârın kaç işlemde toplandığı                  [yeni]

PERMÜTASYONUN ANLAMI BURADA KRİTİK: pairs'in iddiası "z-skoru DOĞRU ZAMANI söylüyor".
Null hipotez: aynı çiftlerde, aynı sayıda, aynı tutuş süresiyle ama RASTGELE zamanlarda
işlem açsak ne olurdu? Gerçek edge, z-zamanlamasının rastgeleyi anlamlı ölçüde yenmesidir.
Bu, "çiftler zaten kârlıydı" ile "z-skoru işe yarıyor" arasını ayırır — eski test bunu sormadı.

Kullanım:  py pairs_verify.py local
"""
import sys, itertools
import numpy as np, pandas as pd
import fast_bt

RNG = np.random.default_rng(7)
COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
FEE = 0.0001; BAL0 = 190.0
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
ZWIN = 60; NPAIRS = 8; MAXBARS = 20


def load_px(source):
    px = {}
    for c in COINS:
        try: px[c] = fast_bt.resample(fast_bt.load(c, source=source), "1d")["close"]
        except Exception: pass
    return pd.DataFrame(px).dropna(how="all").ffill()


def pick_pairs(px, n):
    """Çift seçimi YALNIZ eğitimden. pairs_spread.py ile BİREBİR aynı ölçü.

    KRİTİK: korelasyon log GETİRİLERDEN hesaplanır, log FİYATLARDAN DEĞİL.
    İlk yazdığımda seviye korelasyonu kullandım ve tamamen farklı çiftler seçildi
    (ledger'ın 8 çiftinden yalnız 2'si tuttu) → oturumun tek hayatta kalan bulgusunu
    yanlış gerekçeyle çürütmeye çok yaklaştım. Seviye korelasyonu SAHTEDİR: iki trendli
    seri her zaman yüksek korelasyon verir, ortalamaya dönüş hakkında hiçbir şey söylemez."""
    tr = px[px.index < TRAIN_END]
    lr = np.log(tr).diff().dropna()
    cands = []
    for a, b in itertools.combinations(lr.columns, 2):
        s = lr[[a, b]].dropna()
        if len(s) < 200: continue
        c = s[a].corr(s[b])
        if not np.isfinite(c): continue
        cands.append((c, a, b))
    cands.sort(key=lambda x: -x[0])
    return [(a, b) for _, a, b in cands[:n]], len(cands)


def run_pair(px, a, b, z_in, z_out, z_stop, rand=False):
    """rand=True → aynı SAYIDA ve aynı TUTUŞ süresiyle ama RASTGELE zamanlarda işlem."""
    lg = np.log(px[[a, b]].dropna())
    sp = lg[a] - lg[b]
    mu = sp.rolling(ZWIN).mean(); sd = sp.rolling(ZWIN).std()
    z = ((sp - mu) / sd).values
    idx = sp.index; ra = px[a].reindex(idx).values; rb = px[b].reindex(idx).values
    n = len(z)
    real = []
    i = ZWIN + 1
    while i < n - 1:
        if not np.isfinite(z[i]) or abs(z[i]) < z_in: i += 1; continue
        d_ = -1 if z[i] > 0 else +1
        ex = None
        for j in range(i + 1, min(i + 1 + MAXBARS, n)):
            if not np.isfinite(z[j]): continue
            if abs(z[j]) < z_out or abs(z[j]) > z_stop: ex = j; break
        if ex is None: ex = min(i + MAXBARS, n - 1)
        real.append((i, ex, d_))
        i = ex + 1
    if not rand:
        picks = real
    else:
        # aynı sayıda, aynı tutuş süresi dağılımı, RASTGELE başlangıç, çakışmasız
        picks = []; used = np.zeros(n, bool)
        for (i0, e0, d0) in real:
            hold = e0 - i0
            for _ in range(40):
                st = int(RNG.integers(ZWIN + 1, max(ZWIN + 2, n - hold - 1)))
                if not used[st:st + hold + 1].any():
                    used[st:st + hold + 1] = True
                    picks.append((st, st + hold, int(RNG.choice([-1, 1]))))
                    break
    out = []
    for (i0, e0, d_) in picks:
        r_a = d_ * (ra[e0] - ra[i0]) / ra[i0]
        r_b = -d_ * (rb[e0] - rb[i0]) / rb[i0]
        ret = (r_a + r_b) / 2 - 4 * FEE
        out.append({"ret": ret, "ts": idx[e0]})
    return out


def agg(trs):
    if not trs: return None
    d = np.array([t["ret"] * BAL0 for t in trs])
    ts = [pd.Timestamp(t["ts"]) for t in trs]
    ya = np.array([t.year for t in ts])
    gp = d[d > 0].sum(); gl = -d[d < 0].sum()
    tr = np.array([t < TRAIN_END for t in ts])
    return dict(n=len(d), pf=gp / max(gl, 1e-9), tot=float(d.sum()),
                train=float(d[tr].sum()), test=float(d[~tr].sum()), pnl=d,
                yrs={int(y): float(d[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    px = load_px(source)
    pairs, n_cand = pick_pairs(px, NPAIRS)
    print(f"\n{'='*100}\n=== PAIRS — YÜKSELTİLMİŞ BARLA YENİDEN SINAMA ===")
    print(f"  {len(px.columns)} coin → {n_cand} aday çift taranmış, EĞİTİMDEN {NPAIRS} seçildi")
    print(f"  çiftler: " + ", ".join(f"{a}/{b}" for a, b in pairs))

    CFGS = [(2.0, 0.0, 3.0), (2.0, 0.5, 3.5), (2.5, 0.5, 4.0), (3.0, 0.5, 4.5)]
    print(f"\n  --- (a) TRAIN/TEST + YIL-YIL --- ({len(CFGS)} z-konfig)")
    print(f"  {'z_in/out/stop':>14s} {'n':>5s} {'PF':>5s} {'TRAIN$':>8s} {'TEST$':>8s} {'toplam$':>9s}  yıl-yıl")
    results = {}
    for cfg in CFGS:
        trs = []
        for a, b in pairs: trs += run_pair(px, a, b, *cfg)
        s = agg(trs); results[cfg] = s
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        ok = s["test"] > 0 and all(v > 0 for v in s["yrs"].values())
        print(f"  {str(cfg):>14s} {s['n']:>5d} {s['pf']:>5.2f} {s['train']:>+8.0f} {s['test']:>+8.0f} "
              f"{s['tot']:>+9.0f}  {ys}  {'✓' if ok else '✗'}")

    best = (2.0, 0.5, 3.5)
    s = results[best]
    print(f"\n  ANA KONFİG {best}: toplam ${s['tot']:+.0f}, TEST ${s['test']:+.0f}")

    # (b) BUYUKLUK
    print(f"\n  --- (b) BÜYÜKLÜK ---")
    print(f"  kitap tabanı $1421; pairs katkısı ${s['tot']:+.0f} = tabanın %{s['tot']/1421*100:.0f}'i "
          f"→ {'✓ eşiğin (%2) çok üstünde' if s['tot'] > 0.02*1421 else '✗'}")

    # (c) DOZ-TEPKI
    print(f"\n  --- (c) DOZ-TEPKİ (z_in sıkılaştıkça) ---")
    for cfg in CFGS:
        print(f"      z_in={cfg[0]}: n={results[cfg]['n']:>4d} toplam ${results[cfg]['tot']:>+6.0f} "
              f"TEST ${results[cfg]['test']:>+6.0f}")
    print(f"      YORUM: z sıkılaştıkça n düşmeli; $ tutarlı azalmalı (aşırı sıkı = az işlem).")
    print(f"      İşaret DEĞİŞİYORSA ya da düzensizse → gürültü.")

    # (d) PERMUTASYON
    print(f"\n  --- (d) PERMÜTASYON (aynı sayı+tutuş, RASTGELE zamanlama, 500 tur) ---")
    print(f"      Null: 'çiftler zaten kârlıydı'. Gerçek edge: z-zamanlaması rastgeleyi yener.")
    obs = s["tot"]; sims = []
    for _ in range(500):
        trs = []
        for a, b in pairs: trs += run_pair(px, a, b, *best, rand=True)
        q = agg(trs)
        if q: sims.append(q["tot"])
    sims = np.array(sims)
    p = ((sims >= obs).sum() + 1) / (len(sims) + 1)
    n_tests = len(CFGS) * 3   # z-konfig × denenen çift-sayısı varyantı (4/6/8)
    psid = 1 - (1 - p) ** n_tests
    print(f"      rastgele: ort ${sims.mean():+.1f} sd ${sims.std():.1f} | gerçek ${obs:+.0f} "
          f"→ z={(obs-sims.mean())/max(sims.std(),1e-9):+.2f}")
    print(f"      ham p={p:.4f} | Šidák({n_tests}) p={psid:.4f}  "
          f"{'✓ GEÇTİ' if psid < 0.05 else '✗ ÖLÜ'}")

    # (f) YOGUNLASMA
    d = s["pnl"]; o = np.argsort(-d)
    print(f"\n  --- (f) YOĞUNLAŞMA ({s['n']} işlem) ---")
    for k in (3, 5, 10, 20):
        print(f"      en iyi {k:>2d} işlem kârın %{d[o[:k]].sum()/d.sum()*100:.0f}'ini taşıyor")

    print(f"\n  HÜKÜM: (d) belirleyici. Šidák sonrası p<0.05 değilse — diğer her şey geçse bile —")
    print(f"  pairs da 'z-zamanlaması gürültüden ayırt edilemiyor' kategorisine düşer ve")
    print(f"  ALT-HESAP YATIRIMI YAPILMAMALIDIR.")


if __name__ == "__main__":
    main()
