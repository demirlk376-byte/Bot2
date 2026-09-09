"""
kol_agirlik.py — KOL AĞIRLIĞI: filtrelemeden, boyutlandırarak.

Neden bu eksen ayrı: "silmek" ile "küçültmek" farklı şeylerdir. Ledger'ın
"ne silinirse silinsin silmek negatif beklentidir" bulgusu SİLMEYE dair.
Ağırlıklandırma hiçbir işlemi silmiyor, sadece boyutu değiştiriyor —
kullanıcının "iyi aylara dokunma" şartını doğal olarak sağlıyor.

Gözlem (ay_analiz.csv): kötü aylarda squeeze POZİTİF (+$50.78), donchian
zararın tamamı (−$239.17), bb küçük negatif (−$45.77).

⚠ RİSK EŞİTLEME — ledger'da `sleeve_risk_test.py` tam bu tuzağa düştü:
risk değiştiren her test TOPLAM RİSKİ SABİT tutmalı, yoksa ölçtüğün şey
"daha çok risk = daha çok kâr"dır ve bu bir bulgu değildir.
Burada ağırlıklar, toplam maruziyet (Σ eff) DEĞİŞMEYECEK şekilde
yeniden normalize ediliyor. Kontrol satırı çıktıda basılıyor.

⚠ MARJİN: ağırlık büyütmek nominal büyütür. Σ eff sabit tutulduğu için
toplam marjin de sabit kalır, ama TEK BİR kolun tepe marjini artabilir.
Çıktı kol başına tepe eşzamanlı maruziyeti de veriyor.

Kullanım:  py kol_agirlik.py
"""
import itertools
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

VERI = "data/ay_analiz.csv"
IZGARA = [0.5, 0.75, 1.0, 1.25, 1.5]


def yukle():
    df = pd.read_csv(VERI)
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["ay"] = df["cikis_ts"].dt.tz_localize(None).dt.to_period("M")
    return df.sort_values("cikis_ts").reset_index(drop=True)


def olc(df, eff):
    pnl = df["R"].values * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=df["ay"].values).groupby(level=0).sum() / A.BAL0 * 100
    yil = pd.Series(pnl, index=df["cikis_ts"].dt.year.values).groupby(level=0).sum()
    return {"kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu_ay": ay.min(), "poz_ay": (ay > 0).mean() * 100,
            "risk": eff.sum(), "yil": yil,
            "pf": pnl[pnl > 0].sum() / max(-pnl[pnl < 0].sum(), 1e-9)}


def agirlikli(df, w):
    """Kol ağırlıkları uygula, TOPLAM RİSKİ sabit tutacak şekilde normalize et."""
    e = df["eff"].values.copy()
    ham = e * df["kol"].map(w).values
    return ham * (e.sum() / ham.sum())          # ← risk eşitleme


def main():
    df = yukle()
    taban = olc(df, df["eff"].values)
    print(f"\n{'=' * 96}")
    print(f"=== KOL AĞIRLIĞI (risk-eşitlemeli) ===")
    print(f"  TABAN  ${taban['kar']:+.2f} · maxDD %{taban['dd']:.2f} · "
          f"en kötü ay %{taban['kotu_ay']:.2f} · PF {taban['pf']:.2f} · Σrisk {taban['risk']:.3f}")
    n = df.groupby("kol").size()
    print(f"  işlem: " + " · ".join(f"{k} {v}" for k, v in n.items()))
    print(f"\n  {'donch':>6s} {'sqz':>5s} {'bb':>5s} {'Σrisk':>7s} {'kâr $':>9s} "
          f"{'Δ$':>8s} {'maxDD':>7s} {'en kötü ay':>11s} {'Δkötüay':>8s} {'PF':>5s}  bar")
    kayit = []
    for wd, ws, wb in itertools.product(IZGARA, repeat=3):
        if wd == ws == wb: 
            if wd != 1.0: continue
        w = {"donchian": wd, "squeeze": ws, "bb": wb}
        e = agirlikli(df, w)
        m = olc(df, e)
        if abs(m["risk"] - taban["risk"]) > 1e-9:
            print(f"  ✗ RİSK EŞİTLEME BOZUK: {m['risk']:.6f} vs {taban['risk']:.6f}"); sys.exit(2)
        d_kar = m["kar"] - taban["kar"]; d_kotu = m["kotu_ay"] - taban["kotu_ay"]
        yil_t = taban["yil"].reindex(m["yil"].index).fillna(0)
        en_kotu_yil = ((m["yil"] - yil_t) / yil_t.abs().replace(0, np.nan) * 100).min()
        gecti = (d_kar >= 28.0 * A.CANLI_OLCEK and d_kotu >= -1e-9
                 and m["dd"] - taban["dd"] <= 2.0
                 and (np.isnan(en_kotu_yil) or en_kotu_yil >= -10.0))
        kayit.append({"w": (wd, ws, wb), "d_kar": d_kar, "d_kotu": d_kotu,
                      "dd": m["dd"], "kar": m["kar"], "pf": m["pf"], "gecti": gecti})
        if gecti or (wd, ws, wb) in [(1.0, 1.0, 1.0)] or d_kotu > 2.0:
            print(f"  {wd:>6.2f} {ws:>5.2f} {wb:>5.2f} {m['risk']:>7.3f} {m['kar']:>+9.2f} "
                  f"{d_kar:>+8.2f} {m['dd']:>6.2f}% {m['kotu_ay']:>10.2f}% {d_kotu:>+8.2f} "
                  f"{m['pf']:>5.2f}  {'✓ GEÇTİ' if gecti else ''}")

    g = [k for k in kayit if k["gecti"]]
    print(f"\n  {len(kayit)} kombinasyon denendi · {len(g)} tanesi barı geçti")
    if not g:
        en_kar = max(kayit, key=lambda k: k["d_kar"])
        en_kotu = max(kayit, key=lambda k: k["d_kotu"])
        print(f"  en çok KÂR getiren : donch {en_kar['w'][0]} sqz {en_kar['w'][1]} bb {en_kar['w'][2]}"
              f"  → Δ${en_kar['d_kar']:+.2f}, Δkötüay {en_kar['d_kotu']:+.2f}")
        print(f"  en çok KÖTÜ AY düzelten: donch {en_kotu['w'][0]} sqz {en_kotu['w'][1]} "
              f"bb {en_kotu['w'][2]}  → Δ${en_kotu['d_kar']:+.2f}, Δkötüay {en_kotu['d_kotu']:+.2f}")
        print(f"\n  ⚠ {len(kayit)} hücre tarandı. Saf gürültüde bile en iyi hücrenin iyi")
        print(f"    görünmesi BEKLENİR. Geçen olsaydı bile walk-forward şart olurdu.")
    print(f"{'=' * 96}\n")


if __name__ == "__main__" and "--dayan" not in sys.argv:
    main()


# ─────────────────────── DAYANIKLILIK (ayrı giriş) ───────────────────────
def dayaniklilik():
    """121 hücrenin en iyisi şansa mı iyi görünüyor? Üç ayrı sınav.

    Bir ızgaranın en iyi hücresini raporlamak, saf gürültüde bile 'bulgu'
    üretir. Bu yüzden hücreyi DEĞİL, DOZ-YANITI ve OOS'u sınıyoruz.
    """
    df = yukle()
    taban = olc(df, df["eff"].values)
    aday = {"donchian": 0.75, "squeeze": 1.50, "bb": 0.50}

    print(f"\n{'=' * 96}\n=== ADAY DAYANIKLILIK SINAVI ===")
    print(f"  aday: donch {aday['donchian']} · sqz {aday['squeeze']} · bb {aday['bb']}")

    # 1) DOZ-YANIT: squeeze ağırlığı monoton mu? Zikzak = overfit.
    print(f"\n  [1] DOZ-YANIT — squeeze ağırlığı süpürülüyor (donch 0.75, bb 0.50 sabit)")
    print(f"      {'sqz':>5s} {'Δ$':>9s} {'en kötü ay':>11s} {'Δkötüay':>9s} {'maxDD':>7s}")
    # ⚠ "monoton mu" YANLIŞ SORU. Doz-yanıtın tepe yapması mekanik olarak
    # beklenir: squeeze payı büyüdükçe bir noktadan sonra EN KÖTÜ AY squeeze'in
    # kendi kötü ayı olur. Aranan şey TEK TEPELİ (unimodal) düzgün bir eğri;
    # kaçınılan şey İŞARET DEĞİŞTİREN ZİKZAK (aç-kapa-aç), ki o overfit işaretidir.
    dizi = []
    for ws in (0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
        m = olc(df, agirlikli(df, {**aday, "squeeze": ws}))
        d = m["kotu_ay"] - taban["kotu_ay"]
        dizi.append((ws, d))
        print(f"      {ws:>5.2f} {m['kar']-taban['kar']:>+9.2f} {m['kotu_ay']:>10.2f}% "
              f"{d:>+9.2f} {m['dd']:>6.2f}%")
    v = [d for _, d in dizi]
    fark = np.diff(v)
    isaret_don = int((np.diff(np.sign(fark[np.abs(fark) > 1e-9])) != 0).sum())
    tepe = int(np.argmax(v))
    if isaret_don == 0:
        hkm = "✓ MONOTON"
    elif isaret_don == 1:
        hkm = (f"✓ TEK TEPELİ (tepe sqz={dizi[tepe][0]}) — mekanik olarak beklenen şekil; "
               f"zikzak DEĞİL")
    else:
        hkm = f"✗ ZİKZAK ({isaret_don} işaret dönüşü) — overfit işareti"
    print(f"      → {hkm}")
    if isaret_don == 1 and tepe in (0, len(v) - 1):
        print(f"        ⚠ tepe ızgaranın UCUNDA — gerçek optimum dışarıda olabilir")
    elif isaret_don == 1:
        print(f"        ⚠ tepe TAM taradığım ızgara noktasında. Bu, iç optimumun")
        print(f"          doğal sonucu da olabilir, ızgaraya aşırı uyum da. Hükmü")
        print(f"          walk-forward verir, bu eğri değil.")

    # 2) TEK AY MI: iyileşme yalnız en kötü aydan mı geliyor?
    e = agirlikli(df, aday)
    ay_t = pd.Series(df["R"].values * df["eff"].values * A.BAL0,
                     index=df["ay"].values).groupby(level=0).sum() / A.BAL0 * 100
    ay_y = pd.Series(df["R"].values * e * A.BAL0,
                     index=df["ay"].values).groupby(level=0).sum() / A.BAL0 * 100
    fark = ay_y - ay_t
    kotu = ay_t[ay_t <= 0].index
    print(f"\n  [2] GENİŞLİK — iyileşme kaç aya yayılmış?")
    print(f"      8 kötü ayın {int((fark[kotu] > 0).sum())}'i iyileşti, "
          f"{int((fark[kotu] < 0).sum())}'i kötüleşti")
    print(f"      kötü aylarda ort değişim %{fark[kotu].mean():+.2f} · "
          f"iyi aylarda ort değişim %{fark[ay_t > 0].mean():+.2f}")
    en5 = ay_t.nsmallest(5)
    print(f"      en kötü 5 ay:")
    for a in en5.index:
        print(f"        {a}  %{ay_t[a]:+7.2f} → %{ay_y[a]:+7.2f}  ({fark[a]:+.2f})")

    # 3) WALK-FORWARD: ağırlığı YALNIZ eğitimde seç, testte ölç.
    print(f"\n  [3] WALK-FORWARD — ağırlık yalnız eğitimde seçildi, testte ölçüldü")
    aylar = sorted(df["ay"].unique())
    for bol in (0.5, 0.6, 0.7):
        k = int(len(aylar) * bol)
        egt = df[df["ay"].isin(aylar[:k])]; tst = df[df["ay"].isin(aylar[k:])]
        if len(tst) < 100: continue
        # eğitimde EN KÖTÜ AYI en çok düzelten ağırlığı seç (bar ile aynı hedef)
        en_iyi, en_skor = None, -9e9
        for wd, ws, wb in itertools.product(IZGARA, repeat=3):
            w = {"donchian": wd, "squeeze": ws, "bb": wb}
            m = olc(egt, agirlikli(egt, w))
            t = olc(egt, egt["eff"].values)
            skor = (m["kotu_ay"] - t["kotu_ay"]) - max(0.0, (t["kar"] - m["kar"]) / 55.0)
            if skor > en_skor: en_skor, en_iyi = skor, w
        mt = olc(tst, tst["eff"].values)
        my = olc(tst, agirlikli(tst, en_iyi))
        d_kar = my["kar"] - mt["kar"]; d_kotu = my["kotu_ay"] - mt["kotu_ay"]
        fiyat = (-d_kar / d_kotu) if d_kotu > 0.01 else float("nan")
        print(f"      %{bol*100:.0f} eğitim → seçilen donch {en_iyi['donchian']} "
              f"sqz {en_iyi['squeeze']} bb {en_iyi['bb']}")
        print(f"        OOS: Δ${d_kar:+8.2f} · Δkötüay {d_kotu:+6.2f} puan · "
              f"puan başı ${fiyat:.2f}" if d_kotu > 0.01 else
              f"        OOS: Δ${d_kar:+8.2f} · Δkötüay {d_kotu:+6.2f} puan · KÖTÜLEŞTİ")
    print(f"{'=' * 96}\n")


if __name__ == "__main__" and "--dayan" in sys.argv:
    dayaniklilik()
