"""
pairs_combined.py — "PAIRS'İ ÇÖZERSEK NE OLUR" sorusunun SAYISAL cevabı.

Bugün ölçülen her şey aynı takas doğrusuna çarptı: kâr eklemek, aylık kuyruğu tam olarak
aynı oranda ağırlaştırıyor (kuyruk SATMAK puan başına en fazla $23.6 kazandırıyor, geri
ALMAK en az $80'e mal oluyor). Sekiz eksen bu duvara çarptı.

PAIRS FARKLI OLABİLİR ÇÜNKÜ KORELASYONU NEGATİF (−0.362). Negatif korelasyonlu bir gelir
akışı, teorik olarak, kâr eklerken kuyruğu AZALTIR — bugün hiçbir şeyin başaramadığı şey.
Ama "teorik olarak" yetmez. Bu betik BİRLEŞİK portföyü ay ay kurup ölçüyor:
en kötü ay gerçekten iyileşiyor mu, yoksa bu da mı bir hikâye?

ÖLÇÜM: bot aylık PnL serisi + pairs aylık PnL serisi (k ölçeğinde) → birleşik seri.
maxDD birleşik AYLIK eşitlik eğrisinden hesaplanır (işlem-sırası değil — iki kolun işlemleri
farklı kadanslarda, tek bir sıralı seri kurmak yanıltıcı olurdu; ay bazı ortak paydadır).

DÜRÜSTLÜK NOTLARI:
 · k=0.70 pairs_margin.py'den geliyor (birleşik marjin, zamanın %99'unda bakiyenin %80'ini
   aşmasın kuralı). Tam ölçek (k=1.0) da tabloda var ama marjin sığmıyor — referans için.
 · pairs kârı nominalle DOĞRUSAL ölçeklenir, bu yüzden k ile çarpmak meşru.
 · Bu bir BACKTEST birleşimidir. Pairs'in kendi edge'i (+$532, PF1.63, 4/4 yıl, permütasyon
   p=0.006) ayrıca doğrulanmıştı; burada test edilen o değil, PORTFÖY ETKİSİ.
 · Aylık hizalama: iki seri de ay sonuna toplanır; bir kolun işlem yapmadığı ay 0 sayılır.

Kullanım:  py pairs_combined.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
import pairs_verify as P

K_FIT = 0.70          # pairs_margin.py'nin bulduğu sığdırma çarpanı


def bot_monthly(source):
    tr = []
    for c in A.DONCH: tr += A.gen("donchian", fast_bt.load(c, source=source))
    for c in A.SQZ:   tr += A.gen("squeeze", fast_bt.load(c, source=source))
    for c in A.BB_COINS: tr += A.gen_bb(fast_bt.load(c, source=source))
    taken = A.seat_select(tr)
    r = np.array([R for _, R, _ in taken]); sp = np.array([s for _, _, s in taken])
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    pnl = r * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0
    return (pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex])
            .groupby(level=0).sum()), float(pnl.sum()), len(r)


def pairs_monthly(source):
    px = P.load_px(source)
    pairs, _ = P.pick_pairs(px, P.NPAIRS)
    trs = []
    for a, b in pairs:
        trs += P.run_pair(px, a, b, 2.0, 0.5, 3.5)
    d = np.array([t["ret"] * P.BAL0 for t in trs])
    ts = [pd.Timestamp(t["ts"]) for t in trs]
    return (pd.Series(d, index=[x.tz_localize(None).to_period("M") for x in ts])
            .groupby(level=0).sum()), float(d.sum()), len(d), pairs


def stats(m, bal=A.BAL0):
    pct = m / bal * 100
    eq = bal + m.cumsum()
    peak = eq.cummax()
    dd = float(((peak - eq) / peak).max() * 100)
    return dict(tot=float(m.sum()), worst=float(pct.min()), best=float(pct.max()),
                mean=float(pct.mean()), posm=float((pct > 0).mean() * 100),
                dd=dd, n=len(m))


def show(tag, s, base=None):
    d = "" if base is None else f" {s['tot']-base['tot']:>+7.0f}"
    print(f"  {tag:<28s} {s['tot']:>+8.0f}{d} {s['mean']:>+8.1f} {s['worst']:>+9.1f} "
          f"{s['best']:>8.1f} {s['posm']:>8.0f} {s['dd']:>8.1f}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    bm, btot, bn = bot_monthly(source)
    pm, ptot, pn, pairs = pairs_monthly(source)

    print(f"\n{'=' * 96}")
    print("=== PAIRS'İ ÇÖZERSEK NE OLUR — birleşik portföy, ay bazında ===")
    print(f"  bot: {bn} işlem / ${btot:+.0f}   ·   pairs: {pn} işlem / ${ptot:+.0f} (tam ölçek)")
    print(f"  çiftler: {pairs}")
    ok = bn == 1579 and abs(btot - 1420.66) < 0.01
    print(f"  DOĞRULAMA: bot ankorla birebir mi → {'✓' if ok else '✗ SAPMA, sonuçlar geçersiz'}")
    if not ok:
        return
    okp = 450 <= ptot <= 620
    print(f"  DOĞRULAMA: pairs ledger'la (+$532) uyumlu mu → {'✓' if okp else '✗ SAPMA'}")
    if not okp:
        return

    idx = bm.index.union(pm.index)
    b = bm.reindex(idx, fill_value=0.0)
    p = pm.reindex(idx, fill_value=0.0)

    corr = float(np.corrcoef(b.values, p.values)[0, 1])
    print(f"\n  AYLIK PnL KORELASYONU: {corr:+.3f}")
    print(f"  (ledger −0.362 diyordu; bağımsız olarak yeniden hesaplandı)")

    hdr = (f"  {'senaryo':<28s} {'toplam$':>8s} {'Δ$':>7s} {'ort ay%':>8s} "
           f"{'EN KÖTÜ AY%':>9s} {'en iyi%':>8s} {'poz-ay%':>8s} {'maxDD%':>8s}")
    print(f"\n{hdr}")
    print("  " + "-" * (len(hdr) - 2))
    sb = stats(b)
    show("BOT TEK BAŞINA (bugünkü)", sb, sb)
    for k in (0.35, 0.50, K_FIT, 1.00):
        s = stats(b + p * k)
        tag = f"bot + pairs (k={k:.2f})" + ("  ← sığan" if abs(k - K_FIT) < 1e-9 else
                                            ("  ← marjin YETMEZ" if k > K_FIT else ""))
        show(tag, s, sb)
    print()
    show("PAIRS TEK BAŞINA (k=1)", stats(p))

    # ── ASIL SORU: kuyruk gerçekten iyileşiyor mu? ──
    sk = stats(b + p * K_FIT)
    print(f"\n  --- ASIL SORU: bugünkü takas doğrusunu KIRIYOR mu? ---")
    dk = sk["tot"] - sb["tot"]; dw = sk["worst"] - sb["worst"]
    print(f"  k={K_FIT}: kâr {dk:+.0f}$ · en kötü ay {sb['worst']:+.1f}% → {sk['worst']:+.1f}% "
          f"({dw:+.1f} puan)")
    if dk > 0 and dw >= 0:
        print(f"  ★ EVET — kâr ARTIYOR ve kuyruk KÖTÜLEŞMİYOR.")
        print(f"    Bugün test edilen 8 eksenin HİÇBİRİ bunu yapamadı; hepsi kârı kuyrukla")
        print(f"    satın alıyordu (puan başına $23.6 kazanç / $80 maliyet).")
        print(f"    Negatif korelasyon ({corr:+.3f}) beklendiği gibi çalışıyor.")
    elif dk > 0:
        print(f"  ~ kâr artıyor ama kuyruk {abs(dw):.1f} puan kötüleşiyor →")
        print(f"    puan başına ${dk/abs(dw):.0f} — bugünkü en iyi satış oranı $23.6'ydı.")
        print(f"    {'YİNE DE DAHA İYİ bir takas' if dk/abs(dw) > 23.6 else 'aynı doğru üzerinde'}")
    else:
        print(f"  ✗ kâr artmıyor — beklenen fayda ölçümde çıkmadı.")

    print(f"\n  --- YIL BAZINDA (birleşik, k={K_FIT}) ---")
    yb = b.groupby(lambda x: x.year).sum()
    yk = (b + p * K_FIT).groupby(lambda x: x.year).sum()
    print(f"  {'yıl':>6s} {'bot':>9s} {'birleşik':>10s} {'fark':>8s}")
    for y in sorted(yb.index):
        print(f"  {y:>6d} {yb[y]:>+9.0f} {yk[y]:>+10.0f} {yk[y]-yb[y]:>+8.0f}")

    print(f"\n  --- EN KÖTÜ 5 AY (bot tek başına vs birleşik) ---")
    comb = b + p * K_FIT
    worst_idx = (b / A.BAL0 * 100).nsmallest(5).index
    print(f"  {'ay':>10s} {'bot%':>8s} {'birleşik%':>10s} {'fark':>8s}")
    for m in worst_idx:
        bv = b[m] / A.BAL0 * 100; cv = comb[m] / A.BAL0 * 100
        print(f"  {str(m):>10s} {bv:>+8.1f} {cv:>+10.1f} {cv-bv:>+8.1f}")
    print(f"\n  (bot'un en kötü aylarında pairs ne yapmış — negatif korelasyonun")
    print(f"   gerçekten işe yarayıp yaramadığı EN NET burada görülür)")


if __name__ == "__main__":
    main()
