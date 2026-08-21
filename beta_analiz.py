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
    """Aylık piyasa ölçüleri (12 coin eşit ağırlık):
      getiri : İŞARETLİ aylık getiri ortalaması  → beta'yı ölçer (yön bağımlılığı)
      mutlak : |aylık getiri| ortalaması          → BÜYÜKLÜK (yönden bağımsız)
      vol    : saatlik getirilerin aylık std'si   → oynaklık rejimi
    ⚠ 'mutlak' ile 'getiri' AYRI şeyler ve ayrı hipotezleri sınıyorlar:
      'piyasa yükselirse kazanır' (beta) ≠ 'sert hareket olursa kazanır' (büyüklük).
      Trend takipçisinden BÜYÜKLÜĞE bağımlılık beklenir; beta'ya değil."""
    g, mu, vo = {}, {}, {}
    for c in sorted(set(A.DONCH) | set(A.SQZ) | set(A.BB_COINS)):
        m = fast_bt.load(c, source=source)
        ay = m["close"].resample("MS").last().dropna()
        r = ay.pct_change()
        g[c] = r
        mu[c] = r.abs()
        sa = m["close"].pct_change()
        vo[c] = sa.resample("MS").std()
    return (pd.DataFrame(g).mean(axis=1) * 100.0,
            pd.DataFrame(mu).mean(axis=1) * 100.0,
            pd.DataFrame(vo).mean(axis=1) * 100.0)


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
    pi, pmut, pvol = piyasa_aylik(source)
    ort = sis.index.intersection(pi.index)
    sis = sis.loc[ort]; pi = pi.loc[ort].fillna(0.0)
    pmut = pmut.loc[ort].fillna(0.0); pvol = pvol.loc[ort].fillna(0.0)
    msk = np.isfinite(sis.values) & np.isfinite(pi.values) & np.isfinite(pmut.values)
    x = pi.values[msk]; y = sis.values[msk]
    xm = pmut.values[msk]; xv = pvol.values[msk]
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

    # ── [5] BÜYÜKLÜK: yön değil, HAREKET ŞİDDETİ ──
    print(f"\n{'='*104}\n=== [5] 'SERT HAREKET' HİPOTEZİ — yönden BAĞIMSIZ büyüklük ===")
    print(f"  Trend takipçisinden beklenen profil: yön ne olursa olsun BÜYÜK hareket")
    print(f"  iyi, yatay piyasa kötü. Beta bunu ölçmez — |getiri| ölçer.")
    for ad, xx in (("|piyasa getirisi|", xm), ("piyasa oynaklığı", xv)):
        b2, a2 = np.polyfit(xx, y, 1)
        t2 = a2 + b2*xx
        r22 = 1 - ((y-t2)**2).sum()/((y-y.mean())**2).sum()
        k2 = np.corrcoef(xx, y)[0,1]
        print(f"  {ad:<20s} eğim {b2:>+7.3f} · R² {r22*100:>5.1f}% · kor {k2:>+.3f}")
    q = np.median(xm)
    print(f"\n  {'hareket':<22s} {'ay':>4s} {'sistem ort':>12s} {'poz ay':>8s} {'toplam':>9s}")
    for ad, v in ((f"BÜYÜK (|ret|>{q:.1f}%)", y[xm > q]), (f"KÜÇÜK (|ret|<={q:.1f}%)", y[xm <= q])):
        if len(v):
            print(f"  {ad:<22s} {len(v):>4d} {v.mean():>+11.2f}% {(v>0).mean()*100:>7.0f}% "
                  f"{v.sum():>+8.1f}%")

    # ── [6] 2×2: YÖN × BÜYÜKLÜK ──
    print(f"\n{'='*104}\n=== [6] YÖN × BÜYÜKLÜK (sorunun tam cevabı) ===")
    print(f"  {'':<14s} {'BÜYÜK hareket':>18s} {'KÜÇÜK hareket':>18s}")
    for ad, ym in (("piyasa YUKARI", x > 0), ("piyasa AŞAĞI", x <= 0)):
        h = []
        for bm in (xm > q, xm <= q):
            v = y[ym & bm]
            h.append(f"{v.mean():+7.2f}% (n{len(v)})" if len(v) else "     — (n0)")
        print(f"  {ad:<14s} {h[0]:>18s} {h[1]:>18s}")
    print(f"\n  → Aynı satırda büyük/küçük FARKLIYSA: hareket şiddeti belirleyici.")
    print(f"    Aynı sütunda yukarı/aşağı FARKLIYSA: yön belirleyici (beta).")

    # ── [7] YALNIZ DONCHIAN ──
    dset = set(A.DONCH)
    dal = [(t[1], t[2], t[3]) for t in ham if t[5] in dset
           and (t[1], round(t[2], 9)) in alset]
    if len(dal) > 50:
        dp = np.array([a[1] for a in dal]) * np.minimum(
            A.RISKF, A.CAP*np.array([a[2] for a in dal])) * A.BAL0
        dex = pd.to_datetime([a[0] for a in dal], utc=True)
        dsis = pd.Series(dp, index=dex).groupby(pd.Grouper(freq="MS")).sum()/A.BAL0*100
        dsis = dsis.reindex(ort).fillna(0.0)
        yd = dsis.values[msk]
        bd, ad_ = np.polyfit(x, yd, 1)
        bmd, _ = np.polyfit(xm, yd, 1)
        print(f"\n{'='*104}\n=== [7] YALNIZ DONCHIAN (n={len(dal)}) ===")
        print(f"  işaretli getiriye beta : {bd:>+7.3f}")
        print(f"  |getiri|'ye eğim       : {bmd:>+7.3f}")
        print(f"  BÜYÜK hareket aylarında {yd[xm>q].mean():+.2f}% · "
              f"KÜÇÜK aylarda {yd[xm<=q].mean():+.2f}%")

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
