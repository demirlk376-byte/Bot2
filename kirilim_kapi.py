"""
kirilim_kapi.py — ADIM 2: sahte-kırılım adaylarını KAPIYA çevirip ölç.

fake_kirilim.py teşhisi (eşdeğerlik + kontrol geçti, 1579/$1420.66):
  · donchian: HİÇBİR özellik negatif dilim üretmedi. Klasik sahte-kırılım imzası
    kapanis_yeri z=-0.00 — TAM SIFIR. Kırılım kolu için sahte kırılım, giriş barından
    ayırt EDİLEMİYOR.
  · donchian atr_orani z=+2.15 (TR +0.280 / TE +0.305): oynaklık GENİŞLERKEN olan
    kırılımlar (+0.383R) daralırken olanlardan (+0.072R) 5 kat iyi. Ama Q1 bile
    POZİTİF → kesmek kârlı işlem keser.
  · squeeze govde z=-2.10, Q5 = -0.243 ← BUGÜNÜN TEK NEGATİF ALT KÜMESİ.
    Mekanizma: squeeze sıkışmadan çıkıştır; dev gövdeli bir mumda girmek hareketin
    ZATEN OLDUĞU anlamına gelir — tükenişe giriliyor.

İKİ KAPI ÖLÇÜLÜYOR:
  sq_govde   : squeeze, gövde oranı eşiğin ÜSTÜNDEyse ATLA  (negatif dilimi kes)
  dn_atr     : donchian, atr_orani eşiğin ALTINDAysa ATLA    (en zayıf dilimi kes)
              ← bunun negatif dilimi YOK; rejim kapısındaki duvara çarpması BEKLENİYOR.
                Kontrol amaçlı: "negatif dilim şart mı" sorusunu doğrudan test eder.

YÖNTEM (regime_kapi.py ile aynı — 23 ekseni reddeden disiplin):
 · Eşik kârı ENİYİLEYEREK seçilmez. Önceden kayıtlı kural: "o dilimi at".
   Kesim noktası YALNIZ TRAIN verisinin yüzdeliğinden; TEST'e hiç bakılmaz.
 · Üç ölçüm: tam dönem (iyimser, karar için DEĞİL) · out-of-sample · walk-forward.
 · Kapı KOLTUK SEÇİMİNDEN ÖNCE uygulanır (atılan işlem koltuğu boşaltır).
 · Doz-yanıtı: %10/%20/%30. Gerçek etki monoton olmalı.

ÖN-KAYITLI BAR: Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek · maxDD +2 puandan fazla
artmayacak · EN KÖTÜ AY KÖTÜLEŞMEYECEK.

Kullanım:  py kirilim_kapi.py local
"""
import heapq
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from fake_kirilim import gen_oz          # eşdeğerliği fake_kirilim'de KANITLANDI

BOL = pd.Timestamp("2025-01-01")
CAP_YENI = 1.50

KAPILAR = {
    "sq_govde": ("squeeze",  "govde",     "ust"),   # büyük gövde → tükeniş → ATLA
    "dn_atr":   ("donchian", "atr_orani", "alt"),   # oynaklık daralıyor → gürültü → ATLA
}


def havuz(source):
    ham = []; sapma = 0
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            m = fast_bt.load(c, source=source)
            ref = A.gen(kol, m); mine = gen_oz(kol, m)
            if len(ref) != len(mine) or any(
                    r[0] != k[0] or r[1] != k[1] or abs(r[2] - k[2]) > 1e-12
                    or abs(r[3] - k[3]) > 1e-12 for r, k in zip(ref, mine)):
                sapma += 1
            for t in mine:
                ham.append({"kol": kol, "e": t[0], "x": t[1].value, "R": t[2],
                            "slp": t[3], **t[4]})
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append({"kol": "bb", "e": t[0], "x": t[1].value, "R": t[2], "slp": t[3]})
    df = pd.DataFrame(ham).sort_values("e", kind="mergesort").reset_index(drop=True)
    df["giris"] = pd.to_datetime(df["e"])
    return df, sapma


def koltuk(df):
    oh = []; ctr = 0; al = []
    for r in df.itertuples():
        while oh and oh[0][0] <= r.e: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (r.x, ctr))
            al.append((r.x, r.R, r.slp))
    return al


def metrik(al, cap=CAP_YENI):
    if not al:
        return dict(n=0, tot=0.0, pf=0.0, wr=0.0, ortR=0.0, dd=0.0, worst=0.0,
                    negay=0, ay=0, yr={})
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    pnl = r * np.minimum(A.RISKF, cap * sp) * A.BAL0
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), negay=int((mon < 0).sum()), ay=len(mon),
                yr={int(k): float(v) for k, v in yr.items()})


def esikler(df, secim, kesim, bitis):
    eg = df[df["giris"] < bitis]
    out = {}
    for ad in secim:
        kol, dgs, yon = KAPILAR[ad]
        v = eg[eg["kol"] == kol][dgs].dropna()
        out[ad] = (float(v.quantile(1 - kesim)) if yon == "ust"
                   else float(v.quantile(kesim))) if len(v) >= 50 else np.nan
    return out


def uygula(df, secim, es):
    tut = np.ones(len(df), dtype=bool)
    for ad in secim:
        kol, dgs, yon = KAPILAR[ad]
        e = es.get(ad)
        if e is None or not np.isfinite(e):
            continue
        hedef = (df["kol"] == kol).values
        v = df[dgs].values if dgs in df else np.full(len(df), np.nan)
        kes = hedef & np.isfinite(v) & ((v >= e) if yon == "ust" else (v <= e))
        tut &= ~kes
    return df[tut]


def yaz(ad, m, taban=None):
    d = f"{m['tot']-taban['tot']:+7.0f}" if taban else f"{'—':>7s}"
    print(f"  {ad:<24s} {m['n']:>6d} {m['tot']:>+9.0f} {d} {m['pf']:>6.2f} "
          f"{m['wr']:>6.1f} {m['ortR']:>+7.3f} {m['dd']:>7.1f} {m['worst']:>+9.1f} "
          f"{m['negay']:>3d}/{m['ay']:<3d}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    df, sapma = havuz(source)
    print(f"\n{'=' * 118}")
    print("=== ADIM 2: SAHTE-KIRILIM KAPISI — eşik YALNIZ TRAIN'den ===")
    print(f"  EŞDEĞERLİK: {'✓ BİREBİR' if sapma == 0 else f'✗ {sapma} coinde SAPMA'}")
    if sapma:
        return
    tam = koltuk(df)
    kon = metrik(tam, cap=A.CAP)
    ok = len(tam) == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"  KONTROL: {len(tam)} işlem / ${kon['tot']:+.2f} → {'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        print(f"    sayı {'tutuyor' if len(tam)==1579 else 'TUTMUYOR'}, "
              f"fark {kon['tot']-1420.66:+.2f}$")
        return

    bas = (f"\n  {'yapılandırma':<24s} {'işlem':>6s} {'netPnL$':>9s} {'Δ$':>7s} {'PF':>6s} "
           f"{'WR%':>6s} {'ortR':>7s} {'maxDD%':>7s} {'kötü ay%':>9s} {'neg/ay':>7s}")
    kombo = [(["sq_govde"], "sq_govde"), (["dn_atr"], "dn_atr"),
             (["sq_govde", "dn_atr"], "ikisi")]

    taban = metrik(koltuk(df))
    print(f"\n[1] TAM DÖNEM — eşik TÜM veriden (⚠ iyimser, karar için DEĞİL)")
    print(bas); yaz("kapısız (taban)", taban)
    for k in (0.10, 0.20, 0.30):
        es = esikler(df, KAPILAR, k, pd.Timestamp("2099-01-01"))
        for sec, ad in kombo:
            yaz(f"{ad} %{k*100:.0f}", metrik(koltuk(uygula(df, sec, es))), taban)

    te = df[df["giris"] >= BOL]
    t_taban = metrik(koltuk(te))
    print(f"\n[2] OUT-OF-SAMPLE — eşik YALNIZ TRAIN(<2025)'den, sonuç TEST(>=2025)'te")
    print(bas); yaz("kapısız (TEST tabanı)", t_taban)
    for k in (0.10, 0.20, 0.30):
        es = esikler(df, KAPILAR, k, BOL)
        for sec, ad in kombo:
            yaz(f"{ad} %{k*100:.0f}", metrik(koltuk(uygula(te, sec, es))), t_taban)

    print(f"\n[3] WALK-FORWARD — eşik her yıl YALNIZ önceki yıllardan")
    for sec, ad in kombo:
        for k in (0.20,):
            print(f"\n  {ad} · kesim %{k*100:.0f}")
            print(f"    {'yıl':>6s} {'kapısız$':>10s} {'kapılı$':>10s} {'Δ$':>7s} "
                  f"{'atılan':>7s} {'kötü ay(k)':>11s} {'kötü ay(ş)':>11s}")
            tk = tp = 0.0
            for yil in (2024, 2025, 2026):
                b = pd.Timestamp(f"{yil}-01-01"); s = pd.Timestamp(f"{yil+1}-01-01")
                dil = df[(df["giris"] >= b) & (df["giris"] < s)]
                if len(dil) < 20:
                    continue
                es = esikler(df, sec, k, b)
                x = metrik(koltuk(dil)); y = metrik(koltuk(uygula(dil, sec, es)))
                tk += x["tot"]; tp += y["tot"]
                print(f"    {yil:>6d} {x['tot']:>+10.0f} {y['tot']:>+10.0f} "
                      f"{y['tot']-x['tot']:>+7.0f} {x['n']-y['n']:>7d} "
                      f"{x['worst']:>+11.1f} {y['worst']:>+11.1f}")
            print(f"    {'TOPLAM':>6s} {tk:>+10.0f} {tp:>+10.0f} {tp-tk:>+7.0f}")

    print(f"\n{'=' * 118}\n=== NASIL OKUNUR ===")
    print("  · dn_atr'ın NEGATİF dilimi YOK — kontrol olarak ölçülüyor. Çökerse")
    print("    'filtre için negatif alt küme ŞART' tezi doğrulanmış olur.")
    print("  · sq_govde'nin negatif dilimi VAR (Q5=-0.243). Asıl aday bu.")
    print("  · [1] iyimser. Karar [2] ve [3]'ten çıkar; ikisinde birden tutmalı.")
    print("  · Doz-yanıtı %10→%20→%30 monoton olmalı; zikzak = gürültü.")


if __name__ == "__main__":
    main()
