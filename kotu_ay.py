"""
kotu_ay.py — "boğadan sonra dökülüyor" hipotezini TEST et + riski büyütme
             kararı için EN KÖTÜ AYLARIN anatomisi.

KULLANICI: "bot boğalarda iyi çalışıyor onu anladık ama boğadan sonraki
süreçte dökülüyor, onu durdurabilmemiz lazım."

⚠ ÖLÇÜM BUNU DESTEKLEMİYOR (beta_analiz.py): piyasa AŞAĞI aylarda sistem
  ortalama +%17.19 ve o ayların %76'sı POZİTİF. Long +0.2585R / short
  +0.2176R, güven aralıkları iç içe. Yani "ayı piyasasında dökülüyor" YANLIŞ.

  Ama kullanıcının YAŞADIĞI şey gerçek: +%100 koşu, ardından tek hamlede
  −%27. O halde suçlu "ayı" değil, DÖNÜŞ ANI olabilir. Bu FARKLI bir hipotez
  ve ayrıca test edilmeli:
      H: kötü aylar, GÜÇLÜ YUKARI aylardan SONRA gelir.

⚠ regime_sans.py kötü ayların genel olarak öngörülemediğini 10.000
  permütasyonla göstermişti. Bu test onun ALT KÜMESİ değil: orada "kötü ay
  tahmin edilebilir mi" soruluyordu, burada TEK BİR spesifik öncül
  (önceki ayın güçlü yukarı olması) sınanıyor. Sonuç negatifse hipotez
  kapanır; pozitifse öngörülebilir TEK bir işaret bulmuşuz demektir.

İKİNCİ İŞ — RİSK KARARI: en kötü ayların bugünkü bakiyede DOLAR karşılığı,
1x / 1.5x / 2x risk seviyelerinde. Riski büyütmeden önce görülmesi gereken şey.

Kullanım:  python3 kotu_ay.py local [equity]
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt

BAL = 190.0


def aylik_seri(source):
    """Ankorun aylık PnL'i (% bazında) + piyasanın aylık getirisi."""
    trades = []
    for c in A.DONCH:
        trades += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:
        trades += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS:
        trades += A.gen_bb(fast_bt.load(c, source=source))
    taken = A.seat_select(trades)
    r = np.array([R for _, R, _ in taken]); slp = np.array([s for _, _, s in taken])
    pnl = r * np.minimum(A.RISKF, A.CAP * slp) * BAL
    ex = [pd.Timestamp(x).tz_localize(None) for x, _, _ in taken]
    ser = pd.Series(pnl, index=ex).sort_index()
    ay = ser.groupby(ser.index.to_period("M")).sum() / BAL * 100

    kap = {}
    for c in A.DONCH + A.SQZ + A.BB_COINS:
        m = fast_bt.load(c, source=source)
        g = m["close"].resample("1ME").last()
        kap[c] = g.pct_change() * 100
    piy = pd.DataFrame(kap).mean(axis=1)
    piy.index = piy.index.to_period("M")
    return ay, piy, ser, len(taken), pnl.sum()


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    equity = float(sys.argv[2]) if len(sys.argv) > 2 else 307.44
    print("kotu_ay.py — 'boğadan sonra dökülüyor' testi + risk kararı anatomisi\n")
    ay, piy, ser, n, tot = aylik_seri(source)
    ok = (n == 1579) and abs(tot - 1420.66) < 0.5
    print(f"  DOĞRULAMA: {n} işlem / ${tot:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — hüküm YOK.")

    ort = ay.reindex(sorted(set(ay.index) & set(piy.index)))
    pi = piy.reindex(ort.index)
    onceki = pi.shift(1)

    # ── [1] EN KÖTÜ AYLAR ────────────────────────────────────────────────────
    print(f"\n{'='*72}\n[1] EN KÖTÜ 8 AY — ne oldu, öncesinde ne vardı?\n{'='*72}")
    print(f"  {'ay':>8s} {'sistem':>9s} {'o ay piyasa':>12s} {'ÖNCEKİ ay piyasa':>17s}")
    for a in ort.nsmallest(8).index:
        print(f"  {str(a):>8s} {ort[a]:>+8.1f}% {pi.get(a, np.nan):>+11.1f}% "
              f"{onceki.get(a, np.nan):>+16.1f}%")

    # ── [2] HİPOTEZ TESTİ ────────────────────────────────────────────────────
    print(f"\n{'='*72}\n[2] HİPOTEZ: kötü aylar GÜÇLÜ YUKARI aylardan SONRA gelir\n{'='*72}")
    m = onceki.notna() & ort.notna()
    x = onceki[m].values; y = ort[m].values
    def _rank(v):
        o = np.argsort(v, kind="mergesort"); r = np.empty(len(v), float)
        r[o] = np.arange(1, len(v) + 1); return r
    rho = np.corrcoef(_rank(x), _rank(y))[0, 1]
    nn = len(x); t = rho * np.sqrt((nn - 2) / max(1e-12, 1 - rho ** 2))
    import math
    p = 2 * 0.5 * (1.0 - math.erf(abs(t) / math.sqrt(2)))
    print(f"  Spearman(ÖNCEKİ ay piyasa getirisi , BU ay sistem) = {rho:+.4f}")
    print(f"    t={t:+.2f} · p={p:.4f} · n={nn}")
    esik = np.percentile(x, 75)
    guclu = y[x >= esik]; digger = y[x < esik]
    se = np.sqrt(guclu.var(ddof=1)/len(guclu) + digger.var(ddof=1)/len(digger))
    z = (guclu.mean() - digger.mean()) / se
    print(f"\n  önceki ay GÜÇLÜ yukarı (üst çeyrek, ≥%{esik:.1f}): "
          f"n={len(guclu)} · sistem ort {guclu.mean():+.1f}%")
    print(f"  diğer aylar:                                   "
          f"n={len(digger)} · sistem ort {digger.mean():+.1f}%")
    print(f"  fark {guclu.mean()-digger.mean():+.1f} puan · z={z:+.2f}")
    if p < 0.05 and rho < 0:
        print(f"\n  → ✓ HİPOTEZ DESTEKLENDİ: güçlü yukarı aydan sonra sistem kötü.")
        print(f"    Bu ÖNGÖRÜLEBİLİR bir işaret — üzerine kural kurulabilir.")
    else:
        print(f"\n  → ✗ HİPOTEZ DESTEKLENMEDİ. Önceki ayın yönü bu ayı AÇIKLAMIYOR.")
        print(f"    Yaşanan −%27, 'boğadan sonrası' değil KUYRUK olayı: aynı")
        print(f"    yönde açık pozisyonlar tek hamlede stoplandı. Bu her rejimde")
        print(f"    olabilir ve 34 kapanan eksen onu ucuza önlemenin yolu")
        print(f"    olmadığını gösterdi.")

    # ── [3] KÖTÜ AY NASIL OLUŞUYOR ───────────────────────────────────────────
    print(f"\n{'='*72}\n[3] KÖTÜ AY NASIL OLUŞUYOR — yavaş kanama mı, tek hamle mi?\n{'='*72}")
    for a in ort.nsmallest(3).index:
        ts = ser[ser.index.to_period("M") == a]
        gun = ts.groupby(ts.index.date).sum().sort_values()
        top = gun.head(3).sum(); hep = ts.sum()
        print(f"  {a}: toplam ${hep:+.2f} · {len(gun)} işlem günü")
        print(f"      en kötü 3 gün ${top:+.2f} = ayın %{top/hep*100:.0f}'i")

    # ── [4] RİSK KARARI ──────────────────────────────────────────────────────
    print(f"\n{'='*72}\n[4] RİSK KARARI — bugünkü ${equity:.0f} bakiyede DOLAR\n{'='*72}")
    print(f"  Ankorun aylık dağılımı, sabit-oran modelinde boyutla DOĞRUSAL.")
    print(f"  {'ölçek':>7s} {'ort ay':>9s} {'en kötü ay':>12s} {'alt %5 ay':>12s} {'maxDD':>9s}")
    dd = 24.4
    for f in (1.0, 1.5, 2.0):
        print(f"  {f:>6.1f}x {ort.mean()/100*equity*f:>+8.0f}$ "
              f"{ort.min()/100*equity*f:>+11.0f}$ "
              f"{np.percentile(ort,5)/100*equity*f:>+11.0f}$ "
              f"{-dd/100*equity*f:>+8.0f}$")
    print(f"\n  ⚠ 'en kötü ay' 40 ayın EN KÖTÜSÜ — yani ~3.3 yılda bir beklenir.")
    print(f"    'alt %5' ise 20 ayda bir. Riski büyütmek bu iki sayıyı da")
    print(f"    AYNI oranda büyütür; beklenen kârı da öyle. Oran DEĞİŞMEZ.")
    print(f"  ⚠ Ağustos'ta yaşanan −$102 idi. Yukarıdaki 2.0x satırındaki")
    print(f"    'en kötü ay' rakamıyla karşılaştır — katlanabilir mi?")


if __name__ == "__main__":
    main()
