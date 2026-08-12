"""
regime_korelasyon.py — DOĞRU TEST: korelasyon işlem R'sini değil PORTFÖY RİSKİNİ vurur.

⚠️ ÖNCEKİ TESTİM YANLIŞ SORUYU SORDU. regime_teshis.py korel20'yi işlem seviyesinde
R'ye karşı sınadı, eşiği geçmedi, ben de "korelasyon ayrıştırmıyor" dedim. Bu YANLIŞTI.
Yüksek korelasyon tek bir işlemi kötüleştirmez — YEDİ POZİSYONU AYNI BAHSE ÇEVİRİR.
Etkisi ortalama R'de değil, portföyün GÜNLÜK OYNAKLIĞINDA ve kuyruğunda görünür.
Doğru test bu betikte.

İKİ BÖLÜM:

[A] TEŞHİS — günlük portföy sonucu, korelasyon dilimlerine göre.
    n≈1300 gün (40 ayın 30 katı güç). Bakılan: ortalama günlük PnL DEĞİL (o zaten
    işlem seviyesinde ölçüldü), asıl bakılan GÜNLÜK PnL'İN STANDART SAPMASI ve
    kuyruk (en kötü gün, negatif gün oranı). Hipotez doğruysa yüksek korelasyon
    diliminde ortalama benzer ama YAYILMA belirgin şekilde büyük olmalı.
    Ayrıca eşzamanlı açık pozisyon sayısı da dilim başına raporlanıyor — yüksek
    korelasyonda daha çok pozisyon açıksa etki iki katına çıkar.

[B] KOŞULLU KOLTUK — korelasyon eşiğin üstündeyken MAXPOS düşürülür.
    Bu, bugüne kadar reddedilen "maruziyet tavanı" eksenlerinden YAPISAL OLARAK farklı:
     · İşlem KALİTESİNE bakmıyor → kapı testini öldüren "kesilen işlemler hâlâ kârlı"
       sorunu burada YOK. Kesilen şey işlem değil, EŞZAMANLILIK.
     · Statik MAX_POSITIONS düşürme test edilip reddedilmişti ama o KOŞULSUZDU;
       faydası düşük korelasyon günlerinde erirdi. Bu koşullu.
    Eşik YALNIZ TRAIN'den. Walk-forward dahil.

ÖN-KAYITLI KABUL KURALI (önceden yazıldı, sonuç görülmeden):
 · Out-of-sample VE walk-forward'ın İKİSİNDE birden en kötü ay iyileşecek
   (ya da en azından kötüleşmeyecek) VE
 · doz-yanıtı monoton olacak (daha sıkı koltuk → daha çok kuyruk koruması) VE
 · kâr kaybı, ölçülen koruma fiyatını ($80/puan) geçmeyecek.
Üçünden biri tutmazsa REDDEDİLİR.

Kullanım:  py regime_korelasyon.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

TUM = A.DONCH + A.SQZ + A.BB_COINS
BOL = pd.Timestamp("2025-01-01")
CAP_YENI = 1.50


def _naive(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx


def korelasyon_serisi(source):
    """Coinler arası 20 günlük ORTALAMA İKİLİ KORELASYON. shift(1) — lookahead yok."""
    ser = {}
    for c in TUM:
        ser[c] = fast_bt.load(c, source=source)["close"].resample("1D").last()
    px = pd.DataFrame(ser).dropna(how="all").ffill()
    px.index = _naive(px.index)
    ret = px.pct_change()
    R = ret.values; n = R.shape[1]
    iu = np.triu_indices(n, 1)
    out = []
    for i in range(len(ret)):
        if i < 20:
            out.append(np.nan); continue
        W = R[i - 19:i + 1]
        if np.isnan(W).any():
            W = pd.DataFrame(W).ffill().bfill().values
        C = np.corrcoef(W, rowvar=False)
        out.append(np.nanmean(C[iu]))
    return pd.Series(out, index=ret.index).shift(1)


def havuz(source):
    """Koltuk seçiminden ÖNCEKİ tam sinyal havuzu, KARARLI sırada.
    (pandas quicksort kararsız; A.seat_select Python'un kararlı `sorted`'ını kullanıyor.)"""
    ham = []
    for c in A.DONCH:
        for t in A.gen("donchian", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.SQZ:
        for t in A.gen("squeeze", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1].value, t[2], t[3]))
    return sorted(ham, key=lambda z: z[0])          # kararlı


def koltuk(ham, kor=None, esik=None, dar=None):
    """Koltuk seçimi. kor/esik/dar verilirse: korelasyon eşiğin ÜSTÜNDEYKEN MAXPOS=dar."""
    openh = []; ctr = 0; al = []
    for e_ns, x_ns, R, slp in ham:
        while openh and openh[0][0] <= e_ns: heapq.heappop(openh)
        limit = A.MAXPOS
        if kor is not None and esik is not None and np.isfinite(esik):
            g = pd.Timestamp(e_ns).normalize()
            k = kor.get(g, np.nan)
            if np.isfinite(k) and k >= esik:
                limit = dar
        if len(openh) < limit:
            ctr += 1
            heapq.heappush(openh, (x_ns, ctr))
            al.append((e_ns, x_ns, R, slp))
    return al


def metrik(al, cap=CAP_YENI):
    if not al:
        return dict(n=0, tot=0.0, pf=0.0, wr=0.0, ortR=0.0, dd=0.0, worst=0.0,
                    negay=0, ay=0, yr={})
    r = np.array([a[2] for a in al]); sp = np.array([a[3] for a in al])
    eff = np.minimum(A.RISKF, cap * sp)
    pnl = r * eff * A.BAL0
    ex = [pd.Timestamp(a[1]) for a in al]
    sira = np.argsort([a[1] for a in al])
    eq = A.BAL0 + np.cumsum(pnl[sira])
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), negay=int((mon < 0).sum()), ay=len(mon),
                yr={int(k): float(v) for k, v in yr.items()})


def gunluk_tablo(al, kor, cap=CAP_YENI):
    """Günlük portföy PnL'i (çıkış gününe atfen) + o günün korelasyonu + açık poz. sayısı."""
    r = np.array([a[2] for a in al]); sp = np.array([a[3] for a in al])
    pnl = r * np.minimum(A.RISKF, cap * sp) * A.BAL0
    gun = [pd.Timestamp(a[1]).normalize() for a in al]
    g = pd.Series(pnl).groupby(gun).sum()

    # eşzamanlı açık pozisyon: her gün için açık olan işlem sayısı
    acik = {}
    for a in al:
        for d in pd.date_range(pd.Timestamp(a[0]).normalize(),
                               pd.Timestamp(a[1]).normalize(), freq="D"):
            acik[d] = acik.get(d, 0) + 1
    ac = pd.Series(acik)

    df = pd.DataFrame({"pnl": g}).join(pd.DataFrame({"kor": kor}), how="left")
    df["acik"] = ac.reindex(df.index)
    return df.dropna(subset=["kor"])


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    kor_s = korelasyon_serisi(source)
    kor_d = kor_s.to_dict()
    ham = havuz(source)

    tam = koltuk(ham)
    kon = metrik(tam, cap=A.CAP)
    ok = len(tam) == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"\n{'=' * 118}")
    print("=== KORELASYON REJİMİ — doğru test: portföy riski, işlem R'si değil ===")
    print(f"  KONTROL: {len(tam)} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        print(f"    sayı {'tutuyor' if len(tam)==1579 else 'TUTMUYOR'}, "
              f"fark {kon['tot']-1420.66:+.2f}$")
        return

    # ── [A] TEŞHİS ──
    gt = gunluk_tablo(tam, kor_s)
    gt["dilim"] = pd.qcut(gt["kor"], 5, labels=False, duplicates="drop")
    print(f"\n[A] TEŞHİS — {len(gt)} işlem günü, korelasyon dilimlerine göre")
    print(f"    Hipotez: yüksek korelasyonda ORTALAMA benzer ama YAYILMA büyük olmalı.")
    print(f"\n    {'dilim':>6s} {'kor':>7s} {'gün':>5s} {'ort PnL$':>9s} {'std PnL$':>9s} "
          f"{'en kötü gün$':>13s} {'neg gün%':>9s} {'ort açık poz':>13s}")
    for q in range(5):
        s = gt[gt.dilim == q]
        print(f"    {'Q'+str(q+1):>6s} {s['kor'].mean():>7.3f} {len(s):>5d} "
              f"{s['pnl'].mean():>+9.2f} {s['pnl'].std():>9.2f} {s['pnl'].min():>+13.2f} "
              f"{(s['pnl']<0).mean()*100:>8.0f}% {s['acik'].mean():>13.2f}")
    q1 = gt[gt.dilim == 0]["pnl"]; q5 = gt[gt.dilim == 4]["pnl"]
    # varyans oranı testi (F): yayılma gerçekten farklı mı
    F = q5.var(ddof=1) / q1.var(ddof=1)
    print(f"\n    YAYILMA ORANI Q5/Q1 = {F:.2f}  "
          f"({'✓ yüksek korelasyonda oynaklık BELİRGİN daha büyük' if F > 1.25 else '✗ yayılma farkı yok'})")
    print(f"    ortalama farkı: Q5 {q5.mean():+.2f}$ vs Q1 {q1.mean():+.2f}$")
    # TRAIN/TEST
    for ad, alt in (("TRAIN", gt[gt.index < BOL]), ("TEST", gt[gt.index >= BOL])):
        if len(alt) < 100: continue
        a1 = alt[alt.dilim == 0]["pnl"]; a5 = alt[alt.dilim == 4]["pnl"]
        if len(a1) > 10 and len(a5) > 10:
            print(f"    {ad:<5s} yayılma oranı {a5.var(ddof=1)/a1.var(ddof=1):.2f}  "
                  f"en kötü gün Q5 {a5.min():+.2f}$ vs Q1 {a1.min():+.2f}$")

    # ── [B] KOŞULLU KOLTUK ──
    taban = metrik(tam)
    print(f"\n[B] KOŞULLU KOLTUK — korelasyon eşiğin üstündeyken MAXPOS düşürülür")
    print(f"    (eşik YALNIZ TRAIN'den; taban: {taban['n']} işlem ${taban['tot']:+.0f} "
          f"maxDD {taban['dd']:.1f} en kötü ay {taban['worst']:+.1f} "
          f"{taban['negay']}/{taban['ay']} neg)")
    print(f"\n    {'eşik(TRAIN%)':>13s} {'dar MAXPOS':>11s} {'işlem':>6s} {'netPnL$':>9s} "
          f"{'Δ$':>7s} {'PF':>5s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg/ay':>7s} {'$/puan':>8s}")
    egitim_kor = kor_s[kor_s.index < BOL].dropna()
    sonuc = {}
    for qq in (0.60, 0.70, 0.80):
        esik = float(egitim_kor.quantile(qq))
        for dar in (3, 4, 5, 6):
            al = koltuk(ham, kor_d, esik, dar)
            v = metrik(al); sonuc[(qq, dar)] = v
            dw = v["worst"] - taban["worst"]
            dt = v["tot"] - taban["tot"]
            fiyat = f"{-dt/dw:>8.0f}" if dw > 0.05 else f"{'—':>8s}"
            print(f"    {qq*100:>12.0f}% {dar:>11d} {v['n']:>6d} {v['tot']:>+9.0f} "
                  f"{dt:>+7.0f} {v['pf']:>5.2f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
                  f"{v['negay']:>3d}/{v['ay']:<3d} {fiyat}")

    # ── WALK-FORWARD ──
    print(f"\n[C] WALK-FORWARD — eşik her yıl YALNIZ önceki yıllardan")
    for qq in (0.70, 0.80):
        for dar in (4, 5):
            print(f"\n    eşik %{qq*100:.0f} · dar MAXPOS={dar}")
            print(f"      {'yıl':>6s} {'kapısız$':>10s} {'koşullu$':>10s} {'Δ$':>7s} "
                  f"{'kötü ay(k)':>11s} {'kötü ay(ş)':>11s}")
            tk = tp = 0.0
            for yil in (2024, 2025, 2026):
                bas = pd.Timestamp(f"{yil}-01-01"); son = pd.Timestamp(f"{yil+1}-01-01")
                dilim = [h for h in ham
                         if bas.value <= h[0] < son.value]
                if len(dilim) < 20: continue
                gec = kor_s[kor_s.index < bas].dropna()
                if len(gec) < 100: continue
                esik = float(gec.quantile(qq))
                a = metrik(koltuk(dilim)); b = metrik(koltuk(dilim, kor_d, esik, dar))
                tk += a["tot"]; tp += b["tot"]
                print(f"      {yil:>6d} {a['tot']:>+10.0f} {b['tot']:>+10.0f} "
                      f"{b['tot']-a['tot']:>+7.0f} {a['worst']:>+11.1f} {b['worst']:>+11.1f}")
            print(f"      {'TOPLAM':>6s} {tk:>+10.0f} {tp:>+10.0f} {tp-tk:>+7.0f}")

    print(f"\n{'=' * 118}\n=== NASIL OKUNUR ===")
    print(f"  · [A] hipotezi doğrularsa (yayılma oranı >1.25) mekanizma GERÇEK demektir:")
    print(f"    yüksek korelasyonda 7 pozisyon = 1 bahis, portföy oynaklığı şişiyor.")
    print(f"  · [B]/[C] o mekanizmayı PARAYA çevirebiliyor muyuz sorusudur. [A] doğru")
    print(f"    çıkıp [B] boş çıkabilir — mekanizma gerçek ama kullanılabilir değil demektir.")
    print(f"  · '$/puan' = en kötü ayı 1 puan iyileştirmenin maliyeti. Ölçülen piyasa")
    print(f"    fiyatı ≥$80/puan; bunun ALTI ucuz sayılır.")


if __name__ == "__main__":
    main()
