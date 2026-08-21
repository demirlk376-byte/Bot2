"""
beta_analiz.py — "BOT NEDEN ATAK YAPTI, NE ZAMAN BATAR?"

KULLANICININ SORUSU DOĞRU SORU: "şans" demek yetmez. Hangi KOŞULDA kazandığını
bilirsek, o koşulun tersi geldiğinde anlarız.

BUGÜNE KADAR SORULMAYAN ŞEY — ve şu an 6 pozisyonun 6'sı LONG:
    Bu sistem PİYASA YÜKSELİRKEN mi para kazanıyor?
Eğer kâr büyük ölçüde piyasa betasından geliyorsa, "ne zaman batar" sorusunun
cevabı nettir: alt-coin piyasası düştüğünde. Ve bu ÖNCEDEN TAHMİN edilemez ama
ANLIK OLARAK ÖLÇÜLEBİLİR — yani "şu an rüzgâr tersine döndü" denebilir.

⚠ BU, KAPANMIŞ 18 EKSENDEN FARKLI BİR SORU. Onlar İŞLEM seviyesindeydi:
"hangi sinyal kötü?" Bu DÖNEM seviyesinde: "hangi piyasa halinde sistem kazanıyor?"
regime_sans.py kötü AYLARIN tahmin edilemediğini gösterdi (p=0.32/0.53). Ama
"tahmin edilemez" ile "açıklanamaz" farklı şeyler. Beta açıklayıcıdır, öngörücü
değil — ve bu soru için açıklama yeterli.

ÖLÇÜLENLER:
 [1] Aylık portföy PnL'i ile PİYASA aylık getirisi (12 coin ortalaması) regresyonu
     → alfa (piyasadan bağımsız kazanç) · beta (piyasaya bağımlılık) · R²
 [2] Piyasa YUKARI vs AŞAĞI aylarda sistem ne yapıyor
 [3] LONG vs SHORT işlemlerin ayrı performansı — beta'nın ikinci kanıtı
 [4] Kârın ne kadarı piyasanın yükseldiği aylardan geldi
 [5] ŞU ANKİ dönem bu eksende nerede duruyor

HÜKÜM NASIL OKUNUR:
 • beta yüksek + R² yüksek → sistem uzun-beta. Alt piyasası düşerse batar.
   O zaman izlenecek şey basit ve GÖZLENEBİLİR: piyasa geniş trendi.
 • beta düşük + alfa pozitif → sistem piyasadan bağımsız kazanıyor. O zaman
   "ne zaman batar" sorusunun basit bir cevabı YOK ve şans açıklaması güçlenir.

Kullanım (VPS'te):
    nohup python3 -u beta_analiz.py local > /tmp/beta.log 2>&1 & disown
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from yon_kapi import gen_yonlu, gen_bb_yonlu, koltuk_yonlu


def piyasa_aylik(source):
    """12 coinin AYLIK getirisinin ortalaması = 'piyasa'. Eşit ağırlık."""
    ser = {}
    for c in sorted(set(A.DONCH) | set(A.SQZ) | set(A.BB_COINS)):
        m = fast_bt.load(c, source=source)
        ay = m["close"].resample("MS").last().dropna()
        ser[c] = ay.pct_change()
    df = pd.DataFrame(ser)
    return df.mean(axis=1) * 100.0        # % cinsinden


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("=" * 104)
    print("=== BOT NEDEN ATAK YAPTI, NE ZAMAN BATAR? — piyasa betası ölçümü ===")
    print("  6 pozisyonun 6'sı long. Soru: kâr piyasa yükselişinden mi geliyor?")

    ham = []
    for c in A.DONCH:
        ham += gen_yonlu("donchian", fast_bt.load(c, source=source), c)
    for c in A.SQZ:
        ham += gen_yonlu("squeeze", fast_bt.load(c, source=source), c)
    for c in A.BB_COINS:
        ham += gen_bb_yonlu(fast_bt.load(c, source=source), c)
    al, _ = koltuk_yonlu(ham, 0, None)

    # ankor kontrolü
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    pnl = r * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0
    ok = len(al) == 1579 and abs(pnl.sum() - 1420.66) < 1.0
    print(f"\n  DOĞRULAMA (ankor): {len(al)} işlem / ${pnl.sum():+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — git checkout -- data/'}")
    if not ok:
        return

    ex = pd.to_datetime([a[0] for a in al], utc=True)
    sis = pd.Series(pnl, index=ex).groupby(pd.Grouper(freq="MS")).sum() / A.BAL0 * 100
    pi = piyasa_aylik(source)
    ort = sis.index.intersection(pi.index)
    sis = sis.loc[ort]; pi = pi.loc[ort].fillna(0.0)
    msk = np.isfinite(sis.values) & np.isfinite(pi.values)
    x = pi.values[msk]; y = sis.values[msk]
    print(f"  eşleşen ay sayısı: {len(x)}")

    # ── [1] REGRESYON ──
    b, a0 = np.polyfit(x, y, 1)
    tah = a0 + b * x
    r2 = 1 - ((y - tah) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    kor = np.corrcoef(x, y)[0, 1]
    sb = np.sqrt(((y - tah) ** 2).sum() / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
    print(f"\n{'='*104}\n=== [1] REGRESYON: sistem_aylık = alfa + beta × piyasa_aylık ===")
    print(f"  alfa (piyasadan BAĞIMSIZ aylık kazanç) : {a0:+.2f}% / ay")
    print(f"  beta (piyasaya BAĞIMLILIK)             : {b:+.3f}  [%95: "
          f"{b-1.96*sb:+.3f}, {b+1.96*sb:+.3f}]")
    print(f"  R² (piyasanın açıkladığı oran)         : {r2*100:.1f}%")
    print(f"  korelasyon                             : {kor:+.3f}")

    # ── [2] PİYASA YUKARI vs AŞAĞI ──
    up, dn = y[x > 0], y[x <= 0]
    print(f"\n{'='*104}\n=== [2] PİYASA YUKARI vs AŞAĞI AYLAR ===")
    print(f"  {'piyasa':<16s} {'ay':>4s} {'sistem ort':>12s} {'pozitif ay':>12s} {'toplam':>9s}")
    for ad, v in (("YUKARI (>0)", up), ("AŞAĞI (<=0)", dn)):
        if len(v):
            print(f"  {ad:<16s} {len(v):>4d} {v.mean():>+11.2f}% "
                  f"{(v>0).mean()*100:>11.0f}% {v.sum():>+8.1f}%")
    if len(up) > 1 and len(dn) > 1:
        z = (up.mean()-dn.mean())/np.sqrt(up.var(ddof=1)/len(up)+dn.var(ddof=1)/len(dn))
        print(f"  ayrışma z = {z:+.2f}")

    # ── [3] LONG vs SHORT ──
    yon = np.array([t[4] for t in ham])
    alset = set((a[0], round(a[1], 9)) for a in al)
    lr = [t[2] for t in ham if t[4] > 0 and (t[1], round(t[2], 9)) in alset]
    sr = [t[2] for t in ham if t[4] < 0 and (t[1], round(t[2], 9)) in alset]
    print(f"\n{'='*104}\n=== [3] LONG vs SHORT (beta'nın ikinci kanıtı) ===")
    for ad, v in (("LONG", lr), ("SHORT", sr)):
        v = np.array(v)
        if len(v) > 5:
            pf = v[v>0].sum()/max(-v[v<=0].sum(), 1e-9)
            se = v.std(ddof=1)/np.sqrt(len(v))
            print(f"  {ad:<6s} n={len(v):>5d}  ort R {v.mean():>+7.4f} "
                  f"[{v.mean()-1.96*se:+.4f},{v.mean()+1.96*se:+.4f}]  PF {pf:.2f}")

    # ── [4] KÂRIN KAYNAĞI ──
    print(f"\n{'='*104}\n=== [4] KÂRIN NE KADARI PİYASA YÜKSELİRKEN GELDİ ===")
    tp = y.sum()
    print(f"  toplam {tp:+.1f}% · piyasa yukarı aylardan {up.sum():+.1f}% "
          f"(%{up.sum()/tp*100 if tp else 0:.0f}) · aşağı aylardan {dn.sum():+.1f}%")

    # ── HÜKÜM ──
    print(f"\n{'='*104}\n=== HÜKÜM ===")
    guclu = (b > 0.5) and (r2 > 0.25)
    if guclu:
        print(f"  ⛔ SİSTEM UZUN-BETA. Kârın büyük kısmı piyasa yükselişinden geliyor.")
        print(f"     'Ne zaman batar' sorusunun cevabı: ALT PİYASASI DÜŞTÜĞÜNDE.")
        print(f"     Bu ÖNGÖRÜLEMEZ ama ANLIK ÖLÇÜLEBİLİR — izlenecek tek şey:")
        print(f"     12 coinin ortalama aylık getirisi. Negatife dönüyorsa rüzgâr terse döndü.")
        print(f"     Beta {b:.2f} → piyasa %10 düşerse sistem ~%{abs(b*10):.0f} kaybeder.")
    elif b > 0.2:
        print(f"  ~ ORTA DERECEDE beta ({b:.2f}), R² {r2*100:.0f}%. Piyasa etkili ama")
        print(f"    tek belirleyici değil. Kötü piyasada sistem zarar eder ama batmaz.")
    else:
        print(f"  ✓ BETA DÜŞÜK ({b:.2f}), R² {r2*100:.0f}%. Sistem piyasa yönünden")
        print(f"    büyük ölçüde BAĞIMSIZ kazanıyor (alfa {a0:+.2f}%/ay).")
        print(f"    Bu, 'ne zaman batar' sorusunun BASİT bir cevabı OLMADIĞI anlamına gelir:")
        print(f"    iyi ve kötü dönemler piyasa yönüyle açıklanmıyor → şans açıklaması güçleniyor.")
    print(f"\n  ⚠ Beta AÇIKLAYICIDIR, ÖNGÖRÜCÜ DEĞİL. 'Piyasa düşerse kaybederiz' demek,")
    print(f"    'piyasanın ne zaman düşeceğini biliyoruz' demek DEĞİL. regime_sans.py")
    print(f"    kötü ayların önceden tahmin edilemediğini 10.000 permütasyonla gösterdi.")


if __name__ == "__main__":
    main()
