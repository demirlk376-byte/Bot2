"""
oynaklik_kapisi.py — "kaybettiğimiz dönemleri önleyebilir miyiz?" sorusunun
                     ELEME DEĞİL, BOYUTLANDIRMA cevabı.

4u ÖLÇTÜ: sistemin kazancını belirleyen şey piyasanın YÖNÜ değil ŞİDDETİ.
    BÜYÜK hareket ayları: +%27.56  ·  KÜÇÜK: +%9.82  (donchian: +24.21 vs +3.04)

AMA ELEMEK ÇALIŞMAZ: küçük-hareket ayları POZİTİF (+%9.82). Araştırma kuralı 1
gereği kesecek zarar yok. Geriye tek yol kalıyor: kesmek değil, KÜÇÜLTMEK.

⚠ ÖNCE ŞU SORU CEVAPLANMALI — yoksa gerisi hayal:
    ŞİDDET ÖNCEDEN BİLİNEBİLİR Mİ?
4u'daki ölçüm AYNI ayın |getirisi|ni kullanıyor; bu EŞZAMANLI, öngörücü değil.
Oynaklık kümelenmesi finansın sağlam olgularından biri ama VARSAYIM olarak
kullanılamaz. Bu araç sırayla sorar:

  [1] ÖNGÖRÜ — girişten ÖNCEKİ pencerede ölçülen piyasa oynaklığı, o işlemin
      R'siyle ilişkili mi? (lookahead YOK: yalnız giriş barına kadar veri)
  [2] GEREK ŞARTI — düşük-oynaklık dilimlerinin ortalama R'si NEGATİF mi?
      Değilse eleme kesin ölü; boyutlandırma da ancak marjinal olabilir.
  [3] BOYUTLANDIRMA — riski oynaklığa göre ölçekleyince ne oluyor?
      Ölçüt: drawdown-normalize kâr (aynı acıya katlanarak ne kazanırdık).

⚠ ÖN-KAYIT (sonucu görmeden yazıldı): aday, normalize kârı tabandan >%5
  iyileştirmeli VE en kötü ay kötüleşmemeli. Ham kâr düşüşü tek başına ret
  sebebi değil — amaç kuyruk kısmak.

Kullanım:  python3 oynaklik_kapisi.py local
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt

BAL = 190.0
PENCERE_GUN = 30            # oynaklık penceresi (gün) — girişten ÖNCEKİ veri


def piyasa_oynaklik(source, coinler):
    """12 coin'in ortalama GÜNLÜK getirisinden hareket eden piyasa serisi ve
    onun KAYAN oynaklığı. Her nokta YALNIZ o ana kadarki veriyi kullanır
    (rolling + shift(1)) → lookahead YOK."""
    seri = {}
    for c in coinler:
        m = fast_bt.load(c, source=source)
        g = m["close"].resample("1D").last().dropna()
        seri[c] = g.pct_change()
    df = pd.DataFrame(seri).dropna(how="all")
    piyasa = df.mean(axis=1)                       # eşit ağırlıklı sepet
    # ⚠ shift(1): bugünün getirisi bugünün oynaklığına GİRMEZ.
    vol = piyasa.rolling(PENCERE_GUN).std().shift(1)
    return piyasa, vol


def islemler(source):
    ham = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1], t[2], t[3], "donchian"))
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1], t[2], t[3], "squeeze"))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1], t[2], t[3], "bb"))
    return sorted(ham, key=lambda t: t[0])


def koltuk(ham, olcek=None):
    """MAX_POSITIONS koltuk seçimi. olcek: giriş zamanı → risk çarpanı."""
    openh = []; alinan = []; ctr = 0
    for e_ns, x_ts, R, slp, sleeve in ham:
        while openh and openh[0][0].value <= e_ns:
            heapq.heappop(openh)
        if len(openh) >= A.MAXPOS:
            continue
        ctr += 1
        heapq.heappush(openh, (x_ts, ctr, R))
        k = 1.0 if olcek is None else olcek(e_ns)
        alinan.append((x_ts, R, slp, k))
    return sorted(alinan, key=lambda t: t[0])


def olc(alinan):
    r = np.array([t[1] for t in alinan])
    slp = np.array([t[2] for t in alinan])
    k = np.array([t[3] for t in alinan])
    eff = np.minimum(A.RISKF, A.CAP * slp) * k
    pnl = r * eff * BAL
    eq = BAL + np.cumsum(pnl)
    e = np.concatenate([[BAL], eq])
    peak = np.maximum.accumulate(e)
    dd = ((peak - e) / peak).max() * 100
    exits = [pd.Timestamp(t[0]) for t in alinan]
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M")
                                for x in exits]).groupby(level=0).sum() / BAL * 100
    return pnl.sum(), dd, mon.min(), len(alinan)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("oynaklik_kapisi.py — şiddet ÖNCEDEN bilinebilir mi, bilinirse işe yarar mı?\n")
    coinler = A.DONCH + A.SQZ + A.BB_COINS
    piyasa, vol = piyasa_oynaklik(source, coinler)
    ham = islemler(source)

    taban = koltuk(ham)
    t_kar, t_dd, t_ay, t_n = olc(taban)
    ok = (t_n == 1579) and abs(t_kar - 1420.66) < 0.5
    print(f"  DOĞRULAMA: {t_n} işlem / ${t_kar:+.2f} → "
          f"{'✓ ANKORLA BİREBİR' if ok else '⛔ ANKORDAN SAPTI'}")
    if not ok:
        raise SystemExit("  Ankor tutmuyor — bu araçla hüküm verilemez.")

    # her işleme GİRİŞ ANINDAKİ (öncesine ait) oynaklığı eşle
    gt = pd.DatetimeIndex([pd.Timestamp(t[0], tz="UTC") for t in ham])
    v = vol.reindex(gt.normalize(), method="ffill").values
    ge = {t[0]: vv for t, vv in zip(ham, v)}

    al = koltuk(ham)
    gv = np.array([ge[k] for k in
                   [t[0] for t in ham if True]][:0]) if False else None
    # alınanların oynaklığı (koltuk seçimi giriş ns'sini kaybediyor → yeniden kur)
    alinan_ns = []
    openh = []; ctr = 0
    for e_ns, x_ts, R, slp, sleeve in ham:
        while openh and openh[0][0].value <= e_ns:
            heapq.heappop(openh)
        if len(openh) >= A.MAXPOS:
            continue
        ctr += 1
        heapq.heappush(openh, (x_ts, ctr, R))
        alinan_ns.append((e_ns, x_ts, R, slp, ge.get(e_ns, np.nan)))
    R_all = np.array([t[2] for t in alinan_ns])
    V_all = np.array([t[4] for t in alinan_ns], float)
    m = np.isfinite(V_all)
    print(f"  {m.sum()}/{len(V_all)} işlemde giriş-öncesi oynaklık okunabildi")

    # ── [1] ÖNGÖRÜ ───────────────────────────────────────────────────────────
    print(f"\n{'='*74}\n[1] ÖNGÖRÜ — giriş ÖNCESİ oynaklık, işlemin R'siyle ilişkili mi?\n{'='*74}")
    def _rank(x):
        o = np.argsort(x, kind="mergesort"); r = np.empty(len(x), float)
        r[o] = np.arange(1, len(x) + 1); return r
    rho = np.corrcoef(_rank(V_all[m]), _rank(R_all[m]))[0, 1]
    n = int(m.sum())
    t = rho * np.sqrt((n - 2) / max(1e-12, 1 - rho ** 2))
    import math
    p = 2 * 0.5 * (1.0 - math.erf(abs(t) / math.sqrt(2)))
    print(f"  Spearman(giriş öncesi oynaklık, R) = {rho:+.4f}  (t={t:+.2f}, p={p:.4f}, n={n})")
    print(f"  {'→ İLİŞKİ VAR' if p < 0.05 else '→ İLİŞKİ YOK — şiddet ÖNCEDEN bilinemiyor'}")

    # ── [2] GEREK ŞARTI ──────────────────────────────────────────────────────
    print(f"\n{'='*74}\n[2] GEREK ŞARTI — düşük-oynaklık dilimi NEGATİF mi?\n{'='*74}")
    kes = np.percentile(V_all[m], [20, 40, 60, 80])
    grup = np.digitize(V_all[m], kes)
    Rm = R_all[m]
    print(f"  {'dilim':<18s}{'n':>6s} {'oynaklık':>10s} {'ort R':>9s} {'alt güven':>11s}")
    negatif = False
    for q in range(5):
        sel = grup == q
        if sel.sum() < 5: continue
        rr = Rm[sel]
        se = rr.std(ddof=1) / np.sqrt(len(rr))
        alt = rr.mean() - 1.96 * se
        if alt > 0: isaret = ""
        elif rr.mean() < 0: isaret = "  ← NEGATİF"; negatif = True
        else: isaret = "  (sıfırdan ayrılamıyor)"
        print(f"  Q{q+1}{' (en sakin)' if q==0 else ' (en oynak)' if q==4 else '':<14s}"
              f"{sel.sum():>6d} {V_all[m][sel].mean()*100:>9.2f}% "
              f"{rr.mean():>+9.4f} {alt:>+11.4f}{isaret}")
    print(f"\n  {'→ Negatif dilim VAR' if negatif else '→ HİÇBİR dilim negatif değil.'}")
    if not negatif:
        print(f"     Eleme KESİN ölü (kural 1). Boyutlandırma da ancak")
        print(f"     kuyruk kısarak değer üretebilir — aşağıda ölçülüyor.")

    # ── [3] BOYUTLANDIRMA ────────────────────────────────────────────────────
    print(f"\n{'='*74}\n[3] BOYUTLANDIRMA — riski oynaklığa göre ölçekle\n{'='*74}")
    print(f"  ÖLÇÜT: normalize kâr = kâr × (maxDD_taban / maxDD_aday)")
    print(f"  ÖN-KAYIT: normalize kâr >%5 iyileşmeli VE en kötü ay kötüleşmemeli\n")
    med = np.nanmedian(V_all[m])
    print(f"  {'kural':<34s}{'işlem':>6s} {'kâr$':>8s} {'Δ$':>7s} "
          f"{'maxDD':>7s} {'kötü ay':>8s} {'NORM':>7s} {'Δnorm':>7s}  BAR")
    print(f"  {'TABAN (sabit risk)':<34s}{t_n:>6d} {t_kar:>+8.0f} {0:>7.0f} "
          f"{t_dd:>7.1f} {t_ay:>8.1f} {t_kar:>7.0f} {0:>7.0f}")
    adaylar = [
        ("düşük vol'de 0.5×", lambda vv: 0.5 if vv < med else 1.0),
        ("düşük vol'de 0.75×", lambda vv: 0.75 if vv < med else 1.0),
        ("yüksek vol'de 1.25×", lambda vv: 1.25 if vv >= med else 1.0),
        ("düşük 0.5× · yüksek 1.5×", lambda vv: 0.5 if vv < med else 1.5),
        ("vol ile ORANTILI (kırpılmış)",
         lambda vv: float(np.clip(vv / med, 0.5, 1.5))),
    ]
    for ad, fn in adaylar:
        yeni = [(x, R, slp, (fn(vv) if np.isfinite(vv) else 1.0))
                for _e, x, R, slp, vv in alinan_ns]
        yeni.sort(key=lambda t: t[0])
        k2, dd2, ay2, n2 = olc(yeni)
        norm = k2 * (t_dd / dd2) if dd2 > 0 else k2
        bar = ("✓ GEÇTİ" if (norm > t_kar * 1.05 and ay2 >= t_ay - 0.05)
               else ("✗ ay↓" if ay2 < t_ay - 0.05 else "✗ norm yetersiz"))
        print(f"  {ad:<34s}{n2:>6d} {k2:>+8.0f} {k2-t_kar:>+7.0f} "
              f"{dd2:>7.1f} {ay2:>8.1f} {norm:>7.0f} {norm-t_kar:>+7.0f}  {bar}")

    print(f"\n{'='*74}\nHÜKÜM\n{'='*74}")
    print(f"  Yukarıdaki tabloda ✓ GEÇTİ yoksa: şiddet önceden ölçülse bile")
    print(f"  ona göre boyutlandırmak kazandırmıyor demektir. O zaman")
    print(f"  'kaybettiğimiz dönemleri önleme' ekseni KAPANIR.")


if __name__ == "__main__":
    main()
