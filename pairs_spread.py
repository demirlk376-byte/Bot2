"""
pairs_spread.py — YENİ SİSTEM AİLESİ #2: SPREAD / PAIRS (piyasa-nötr mean-reversion).

NEDEN BU: aradığımız şey DÜŞÜK KORELASYONLU ikinci bir kâr akışı. Kesitsel momentum bunu
veremedi (long-only onu geçti = edge aslında betaydı). Spread'de bu sorun YAPISAL olarak yok:
iki korelasyonlu coinin ORANINI trade edersin; kripto toptan yükselse de düşse de fark etmez.

MANTIK: corr(A,B) yüksek çiftlerde log(A/B) ortalamaya döner. Oran z-skoru aşırı gerilince
A'yı short/B'yi long (veya tersi), z sıfıra dönünce kapat.

DÜRÜST METODOLOJİ (bu ailede lookahead ve overfit tuzakları çok yaygın):
- Çift SEÇİMİ sadece EĞİTİM penceresinden (2023-2024): orada en yüksek korelasyonlu N çift.
  Test (2025-2026) çift seçimini ETKİLEMEZ. (Aksi = klasik pairs lookahead hatası.)
- z-skoru ROLLING pencereden (sadece geçmiş), tüm-seri istatistikten DEĞİL.
- Giriş |z|>Z_IN, çıkış |z|<Z_OUT, zaman-aşımı ve z-stop (|z|>Z_STOP = ilişki bozuldu, kes).
- Ücret her bacak giriş+çıkış. İki bacak = 4 işlem ücreti.
- Rapor: TRAIN vs TEST ayrı + yıl-yıl. TEST'te çalışmıyorsa RED (train hep güzel görünür).

Kullanım:  py pairs_spread.py local
"""
import sys, itertools
import numpy as np, pandas as pd
import fast_bt

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
FEE = 0.0001; BAL0 = 190.0
TRAIN_END = "2025-01-01"      # çift seçimi SADECE bundan öncesinden
ZWIN = 60                     # z-skoru rolling penceresi (bar)
NPAIRS = 8


def load_px(source, tf):
    px = {}
    for c in COINS:
        try: px[c] = fast_bt.resample(fast_bt.load(c, source=source), tf)["close"]
        except Exception: pass
    return pd.DataFrame(px).dropna(how="all").ffill()


def pick_pairs(px, n=NPAIRS):
    """Çiftleri SADECE eğitim penceresinden seç (test'i etkilemez)."""
    tr = px[px.index < TRAIN_END]
    lr = np.log(tr).diff().dropna()
    best = []
    for a, b in itertools.combinations(lr.columns, 2):
        s = lr[[a, b]].dropna()
        if len(s) < 200: continue
        c = s[a].corr(s[b])
        if not np.isfinite(c): continue
        # spread'in ortalamaya dönüşü: log oranın rolling z'sinin lag-1 otokorelasyonu düşük olmalı
        sp = np.log(tr[a] / tr[b]).dropna()
        if len(sp) < 200: continue
        ac = sp.diff().dropna().autocorr(1)
        best.append((c, a, b, ac))
    best.sort(key=lambda x: -x[0])
    return [(a, b) for c, a, b, ac in best[:n]], best[:n]


def run_pair(px, a, b, z_in, z_out, z_stop, maxbars):
    sp = np.log(px[a] / px[b]).dropna()
    mu = sp.rolling(ZWIN).mean(); sd = sp.rolling(ZWIN).std()
    z = ((sp - mu) / sd)                      # SADECE geçmiş pencere
    idx = sp.index; zz = z.values; n = len(zz)
    ra = px[a].reindex(idx).values; rb = px[b].reindex(idx).values
    out = []; i = ZWIN + 1
    while i < n - 1:
        if not np.isfinite(zz[i]): i += 1; continue
        if abs(zz[i]) < z_in: i += 1; continue
        d_ = -1 if zz[i] > 0 else +1          # z>0 → spread geniş → A short/B long
        ea, eb = ra[i], rb[i]
        j = i; exit_j = None
        for j in range(i + 1, min(i + 1 + maxbars, n)):
            if not np.isfinite(zz[j]): continue
            if abs(zz[j]) < z_out: exit_j = j; break          # normale döndü → kapat
            if abs(zz[j]) > z_stop: exit_j = j; break         # ilişki bozuldu → kes
        if exit_j is None: exit_j = min(i + maxbars, n - 1)
        xa, xb = ra[exit_j], rb[exit_j]
        # d_=+1: A long, B short | d_=-1: A short, B long. Her bacak eşit nominal.
        r_a = d_ * (xa - ea) / ea
        r_b = -d_ * (xb - eb) / eb
        ret = (r_a + r_b) / 2 - 4 * FEE       # 2 bacak × giriş+çıkış
        out.append({"ret": ret, "ts": idx[exit_j], "bars": exit_j - i})
        i = exit_j + 1
    return out


def rep(rs, label):
    if not rs: print(f"  {label:22s} işlem yok"); return None
    r = np.array([x["ret"] for x in rs]); dollars = r * BAL0
    gp = dollars[dollars > 0].sum(); gl = -dollars[dollars < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    ya = np.array([x["ts"].year for x in rs])
    yrs = {y: dollars[ya == y].sum() for y in sorted(set(ya))}
    ys = " ".join(f"{y}:${v:+.0f}" for y, v in yrs.items())
    tr_m = ya < 2025; te_m = ya >= 2025
    print(f"  {label:22s} n={len(r):>4d} WR{(r>0).mean()*100:>3.0f}% PF{pf:5.2f} ${dollars.sum():>+7.0f} "
          f"| TRAIN ${dollars[tr_m].sum():>+6.0f} TEST ${dollars[te_m].sum():>+6.0f} | {ys}")
    return dict(pf=pf, tot=dollars.sum(), test=dollars[te_m].sum(), yrs=yrs)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    for tf, maxbars in (("4h", 60), ("1d", 20)):
        px = load_px(source, tf)
        pairs, info = pick_pairs(px)
        print(f"\n{'='*104}\n=== PAIRS SPREAD — {tf} barlar, çiftler SADECE 2023-24'ten seçildi ===")
        print("  seçilen çiftler (eğitim korelasyonu): " +
              ", ".join(f"{a}/{b}({c:.2f})" for c, a, b, ac in info))
        for z_in, z_out, z_stop in ((2.0, 0.5, 3.5), (2.5, 0.5, 4.0), (2.0, 0.0, 3.0)):
            allr = []
            for a, b in pairs:
                try: allr += run_pair(px, a, b, z_in, z_out, z_stop, maxbars)
                except Exception: pass
            rep(allr, f"z_in{z_in} out{z_out} stop{z_stop}")
    print("\n  KARAR: TEST (2025-26) penceresinde PF>1.2 ve pozitif olmalı. TRAIN güzel/TEST kötü =")
    print("  çift seçimi + parametre uydurması → RED. TEST'te de çalışıyorsa → korelasyon ölç.")


if __name__ == "__main__":
    main()
