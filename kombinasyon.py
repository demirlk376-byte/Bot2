"""
kombinasyon.py — KAYBEDEN İŞLEMLERİN ORTAK KOŞUL BİRLEŞİMLERİ (makine taraması).

BUGÜNE KADAR ÖZELLİKLER TEK TEK test edildi (kok_neden.py, fake_kirilim.py) ve hiçbiri
dört şartı geçmedi. AMA İKİLİ/ÜÇLÜ BİRLEŞİMLERE HİÇ BAKILMADI. Tek başına zararsız iki
koşul BİRLİKTE zararlı olabilir — bu gerçekten yapılmamış bir arama.

⚠️ VERİ SINIRI — 15M YOK: elimizdeki geçmiş 1 SAATLİK bar. 15 dakikalık veri yok.
Donchian 4h'de işlem yaptığı için ona 1H TREND verilebiliyor (gerçekten yeni bilgi).
Squeeze zaten 1h'de olduğundan ona daha ince dilim verilemiyor. Bu, kullanıcının
istediği listeden EKSİK kalan tek kalem.

⚠️⚠️ BU BETİĞİN EN BÜYÜK TEHLİKESİ: ÇOKLU TEST.
~1800 hücre taranıyor. Gerçek ortalama R = +0.237 ve σ_R = 1.465 iken, n=30'luk bir
hücrenin ortalamasının ŞANSLA negatif çıkma olasılığı ~%18'dir. Yani hiçbir gerçek
sinyal olmasa bile ~300 hücre "zararlı" görünür. Ham "negatif ortalama" ARAMASI
BU YÜZDEN İŞE YARAMAZ.

TASARIM — üç kademeli, her kademede beklenen yanlış-pozitif sayısı YAZDIRILIYOR:
  K1 ADAY (yalnız TRAIN): n≥30 VE TRAIN z < −2.0
     Gerçek sinyal yokken bir hücrenin bunu geçme olasılığı ~%0.2 → ~4 yanlış aday.
  K2 DOĞRULAMA (TEST): TEST'te de ortalama R < 0 ve n≥15.
     Yanlış adayların ~yarısı burada elenir → ~2 kalır.
  K3 WALK-FORWARD: kalan her aday KAPI olarak uygulanır, eşik YALNIZ geçmişten.
     Kullanıcının kabul kuralı: PnL veya PF artmıyorsa REDDET; maxDD düşerken
     expectancy/PF korunuyorsa KABUL.

KULLANICI KISITLARI (hepsi uygulandı):
 · Ay/tarih/yıl KURAL DEĞİŞKENİ DEĞİL — yalnız TRAIN/TEST ayrımı ve raporlama için.
 · Yeni indikatör YOK — sadece sistemde zaten olanlar: ATR, ADX, EMA, kanal, hacim.
 · Eşik optimizasyonu YOK — sınıflar TRAIN üçlük dilimlerinden, kâra bakılmadan.
 · Negatif aylar doğrudan filtrelenmiyor.

Kullanım:  py kombinasyon.py local
"""
import heapq
import itertools
import sys
from statistics import NormalDist

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BOL = pd.Timestamp("2025-01-01")
CAP = 1.50
MIN_N_TR = 30
MIN_N_TE = 15
Z_ESIK = -2.0


def _naive(idx):
    return idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx


def gen_full(sleeve, m, saatlik):
    """A.gen + TÜM özellikler. Eşdeğerliği main()'de kanıtlanır.
    saatlik: 1h kapanış serisi (donchian için daha İNCE zaman dilimi trendi)."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    op = d["open"].values; hi = d["high"].values; lo = d["low"].values
    cl = d["close"].values; vo = d["volume"].values
    volma = pd.Series(vo).rolling(20).mean().values
    idx = d.index; n = len(cl)
    # 1H trend (yalnız donchian için anlamlı — 4h koluna daha İNCE dilim)
    s1 = saatlik["close"]
    e1 = s1.ewm(span=20, adjust=False).mean()
    tr1 = (s1 > e1).astype(int)
    tr1.index = _naive(tr1.index)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld

        rng = hi[i] - lo[i]
        ch_h = float(getattr(sg, "channel_high", 0.0) or 0.0)
        ch_l = float(getattr(sg, "channel_low", 0.0) or 0.0)
        sinir = (ch_h if d_ == 1 else ch_l) if (ch_h > 0 and ch_l > 0) else 0.0
        ts = _naive(pd.DatetimeIndex([idx[i]]))[0]
        # 1H trend girişteki yönle UYUMLU mu
        pos1 = tr1.index.searchsorted(ts, side="right") - 1
        t1 = int(tr1.values[pos1]) if pos1 >= 0 else -1
        uyum1 = (1 if ((d_ == 1 and t1 == 1) or (d_ == -1 and t1 == 0)) else 0) if t1 >= 0 else -1
        # kırılım sonrası davranış
        k = i + 1
        iceri = int(((cl[k] < sinir) if d_ == 1 else (cl[k] > sinir))) if sinir > 0 else -1

        out.append(dict(
            kol=sleeve, e=idx[i].value, x=idx[j].value, R=R, slp=sld / e,
            yon=("long" if d_ == 1 else "short"),
            saat=int(ts.hour), giris=ts,
            atr_pct=a / e,
            kanal_gen=(ch_h - ch_l) / a if sinir > 0 else np.nan,
            tasma=(((cl[i] - ch_h) if d_ == 1 else (ch_l - cl[i])) / a) if sinir > 0 else np.nan,
            govde=abs(cl[i] - op[i]) / rng if rng > 0 else np.nan,
            hacim=vo[i] / volma[i] if np.isfinite(volma[i]) and volma[i] > 0 else np.nan,
            adx=adx_ser[i], uyum1h=uyum1, geri_donus=iceri,
        ))
        occ = j
    return out


def koltuk(rows):
    ev = sorted(rows, key=lambda z: z["e"])
    oh = []; ctr = 0; al = []
    for r in ev:
        while oh and oh[0][0] <= r["e"]: heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (r["x"], ctr)); al.append(r)
    return al


def metrik(rows, cap=CAP):
    if not rows:
        return dict(n=0, tot=0.0, pf=0.0, ortR=0.0, dd=0.0, worst=0.0)
    r = np.array([q["R"] for q in rows]); sp = np.array([q["slp"] for q in rows])
    pnl = r * np.minimum(A.RISKF, cap * sp) * A.BAL0
    ex = [pd.Timestamp(q["x"]) for q in rows]
    sira = np.argsort([q["x"] for q in rows])
    eq = A.BAL0 + np.cumsum(pnl[sira])
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(rows), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ham = []; sapma = 0
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            m = fast_bt.load(c, source=source)
            ref = A.gen(kol, m); mine = gen_full(kol, m, m)
            if len(ref) != len(mine) or any(
                    r[0] != q["e"] or r[1].value != q["x"] or abs(r[2] - q["R"]) > 1e-12
                    for r, q in zip(ref, mine)):
                sapma += 1
            ham += mine
    for c in A.BB_COINS:
        for t in A.gen_bb(fast_bt.load(c, source=source)):
            ham.append(dict(kol="bb", e=t[0], x=t[1].value, R=t[2], slp=t[3],
                            yon="—", saat=int(_naive(pd.DatetimeIndex([pd.Timestamp(t[0])]))[0].hour),
                            giris=_naive(pd.DatetimeIndex([pd.Timestamp(t[0])]))[0],
                            atr_pct=np.nan, kanal_gen=np.nan, tasma=np.nan, govde=np.nan,
                            hacim=np.nan, adx=np.nan, uyum1h=-1, geri_donus=-1))

    print(f"\n{'=' * 118}")
    print("=== KAYBEDEN İŞLEMLERİN KOŞUL BİRLEŞİMLERİ — makine taraması ===")
    print(f"  EŞDEĞERLİK: {'✓ BİREBİR' if sapma == 0 else f'✗ {sapma} coinde SAPMA'}")
    if sapma:
        print("  HİÇBİR SAYI OKUNMAZ."); return
    al = koltuk(ham)
    kon = metrik(al, cap=A.CAP)
    ok = kon["n"] == 1579 and abs(kon["tot"] - 1420.66) < 0.01
    print(f"  KONTROL: {kon['n']} işlem / ${kon['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA'}")
    if not ok:
        return
    print(f"  ⚠ 15M trend YOK (veri 1h bar). Donchian'a 1H trend uyumu verildi.")

    df = pd.DataFrame(al)
    tr = df[df.giris < BOL]; te = df[df.giris >= BOL]
    taban = metrik(al)

    # ── ÖZELLİKLERİ AYRIKLAŞTIR (sınırlar YALNIZ TRAIN'den) ──
    sur = ["atr_pct", "kanal_gen", "tasma", "govde", "hacim", "adx"]
    kat = {}
    for v in sur:
        q = tr[v].dropna().quantile([1/3, 2/3]).values
        if len(q) < 2 or not np.isfinite(q).all():
            continue
        kat[v] = pd.cut(df[v], [-np.inf, q[0], q[1], np.inf],
                        labels=[f"{v}:düşük", f"{v}:orta", f"{v}:yüksek"])
    kat["kol"] = df["kol"].map(lambda z: f"kol:{z}")
    kat["yon"] = df["yon"].map(lambda z: f"yon:{z}")
    kat["saat"] = pd.cut(df["saat"], [-1, 5, 11, 17, 23],
                         labels=["saat:00-05", "saat:06-11", "saat:12-17", "saat:18-23"])
    kat["uyum1h"] = df["uyum1h"].map({1: "1h:uyumlu", 0: "1h:ters", -1: "1h:yok"})
    kat["geri_donus"] = df["geri_donus"].map({1: "gd:döndü", 0: "gd:dönmedi", -1: "gd:yok"})
    K = pd.DataFrame(kat).astype("object")
    ozellikler = list(K.columns)
    print(f"  {len(ozellikler)} özellik ayrıklaştırıldı (sınırlar YALNIZ TRAIN'den)")

    # ── K1: ADAY ARAMA (yalnız TRAIN) ──
    sigma = float(df["R"].std(ddof=1))
    hucreler = []
    for k in (1, 2, 3):
        for kombo in itertools.combinations(ozellikler, k):
            g = K.loc[tr.index, list(kombo)]
            for anahtar, grp in tr.groupby([g[c] for c in kombo], observed=True):
                if len(grp) < MIN_N_TR:
                    continue
                se = grp["R"].std(ddof=1) / np.sqrt(len(grp))
                if se <= 0:
                    continue
                z = grp["R"].mean() / se
                hucreler.append((kombo, anahtar if isinstance(anahtar, tuple) else (anahtar,),
                                 len(grp), float(grp["R"].mean()), float(z)))
    toplam = len(hucreler)
    p_gecme = NormalDist().cdf(Z_ESIK)          # tek hücrenin şansla geçme olasılığı
    adaylar = [h for h in hucreler if h[4] < Z_ESIK]
    print(f"\n[K1] ADAY ARAMA — yalnız TRAIN, n≥{MIN_N_TR} ve z<{Z_ESIK}")
    print(f"     taranan hücre: {toplam}")
    print(f"     ŞANSLA geçmesi beklenen: ~{toplam*p_gecme:.1f}")
    print(f"     GERÇEKTE geçen: {len(adaylar)}")
    if len(adaylar) <= toplam * p_gecme * 1.5:
        print(f"     → Bulunan aday sayısı ŞANS BEKLENTİSİYLE AYNI DÜZEYDE.")
        print(f"       Yani ortada gerçek bir desen olduğuna dair kanıt YOK.")

    # ── K2: TEST DOĞRULAMA ──
    gecen = []
    for kombo, anahtar, ntr, ortr, z in sorted(adaylar, key=lambda h: h[4])[:40]:
        maske = np.ones(len(te), dtype=bool)
        for c, a_ in zip(kombo, anahtar):
            maske &= (K.loc[te.index, c].values == a_)
        alt = te[maske]
        if len(alt) < MIN_N_TE:
            continue
        if alt["R"].mean() < 0:
            gecen.append((kombo, anahtar, ntr, ortr, z, len(alt), float(alt["R"].mean())))
    print(f"\n[K2] TEST DOĞRULAMA — aynı hücre TEST'te de negatif mi (n≥{MIN_N_TE})")
    print(f"     doğrulanan: {len(gecen)} / {len(adaylar)}")
    if gecen:
        print(f"\n     {'koşul':<52s} {'TRAIN n':>8s} {'TRAIN R':>8s} {'z':>6s} "
              f"{'TEST n':>7s} {'TEST R':>8s}")
        for kombo, anahtar, ntr, ortr, z, nte, orte in gecen:
            print(f"     {' + '.join(str(a) for a in anahtar):<52s} {ntr:>8d} "
                  f"{ortr:>+8.3f} {z:>+6.2f} {nte:>7d} {orte:>+8.3f}")

    # ── K3: WALK-FORWARD KAPI ──
    print(f"\n[K3] WALK-FORWARD — her aday KAPI olarak (o koşul varsa işlem YOK)")
    if not gecen:
        print("     Doğrulanan aday yok — test edilecek kapı yok.")
    else:
        print(f"     {'koşul':<40s} {'yıl':>6s} {'kapısız$':>9s} {'kapılı$':>9s} "
              f"{'Δ$':>7s} {'PF':>6s} {'maxDD%':>7s}")
        for kombo, anahtar, *_ in gecen[:5]:
            ad = " + ".join(str(a) for a in anahtar)
            tk = tp = 0.0
            for yil in (2024, 2025, 2026):
                b = pd.Timestamp(f"{yil}-01-01"); s2 = pd.Timestamp(f"{yil+1}-01-01")
                idx_y = df.index[(df.giris >= b) & (df.giris < s2)]
                if len(idx_y) < 20:
                    continue
                kes = np.ones(len(idx_y), dtype=bool)
                for c, a_ in zip(kombo, anahtar):
                    kes &= (K.loc[idx_y, c].values == a_)
                t0 = [df.loc[i].to_dict() for i in idx_y]
                t1 = [df.loc[i].to_dict() for i, kk in zip(idx_y, kes) if not kk]
                x = metrik(koltuk(t0)); y = metrik(koltuk(t1))
                tk += x["tot"]; tp += y["tot"]
                print(f"     {ad[:40]:<40s} {yil:>6d} {x['tot']:>+9.0f} {y['tot']:>+9.0f} "
                      f"{y['tot']-x['tot']:>+7.0f} {y['pf']:>6.2f} {y['dd']:>7.1f}")
            print(f"     {'':<40s} {'TOPLAM':>6s} {tk:>+9.0f} {tp:>+9.0f} {tp-tk:>+7.0f}")

    print(f"\n{'=' * 118}\n=== NASIL OKUNUR ===")
    print(f"  · [K1] 'şansla beklenen' ile 'gerçekte geçen' YAKINSA ortada desen YOKTUR.")
    print(f"    Bu, taramanın en önemli satırıdır — ham 'negatif hücre buldum' anlamsızdır.")
    print(f"  · Kullanıcı kuralı: PnL veya PF artmıyorsa REDDET; maxDD düşerken")
    print(f"    expectancy/PF korunuyorsa kabul. [K3] toplam satırına bakılır.")
    print(f"  · 15M trend veride YOK; donchian'a 1H trend uyumu ('1h:uyumlu/ters') verildi.")


if __name__ == "__main__":
    main()
