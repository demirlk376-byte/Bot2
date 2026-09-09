"""
cap_tezi.py — CAP tavanının GERÇEK verimlilik mi yoksa kılık değiştirmiş
kaldıraç mı olduğunu sınar, ve mekanizmayı arar.

TEZ: CAP (POSITION_CAP_FRACTION) bir risk kontrolü değil, bir KIRPMA ARTEFAKTI.
  qty = min(risk$/stop%, CAP × bakiye / fiyat)
Stop DAR olduğunda hedef risk daha büyük nominal ister, CAP keser ve o işlem
hedeflenenden AZ risk alır. Yani en dar stoplu işlemlere en küçük bahsi koyuyoruz.

⚠ LEDGER TUZAĞI (sleeve_risk_test.py buna düştü): risk değiştiren her testte
   "daha çok risk = daha çok kâr" ölçmek kolaydır ve bu bir bulgu DEĞİLDİR.
   Bu betiğin birinci sınavı tam olarak o tuzağı kurar ve tezi ona sokar:
   AYNI ortalama gerçekleşen riske iki farklı yoldan çıkılır (CAP gevşetme vs
   düz RISKF artışı) ve kârlar kıyaslanır. CAP kazanmıyorsa tez çöker.

⚠ İKİNCİ TUZAK — NORMALİZASYON: R = (çıkış−giriş)/stop. Dar stopta aynı fiyat
   hareketi DAHA BÜYÜK R üretir. Ama bu yalnız ZAMAN AŞIMI çıkışları için
   geçerlidir; tp hep +RR, sl hep −1R'dir (sınırlı). İkinci sınav 'sure'
   çıkışlarını hariç tutar. Avantaj orada da duruyorsa GERÇEKTİR.

Kullanım:  py cap_tezi.py
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

VERI = "data/ay_analiz.csv"


def yukle():
    df = pd.read_csv(VERI)
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["ay"] = df["cikis_ts"].dt.tz_localize(None).dt.to_period("M")
    return df.sort_values("cikis_ts").reset_index(drop=True)


def olc(df, riskf, cap):
    eff = np.minimum(riskf, cap * df["slp"].values)
    pnl = df["R"].values * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=df["ay"].values).groupby(level=0).sum() / A.BAL0 * 100
    return {"kar": pnl.sum(), "risk": eff.mean() * 100,
            "dd": A.maxdd(np.concatenate([[A.BAL0], eq])), "kotu": ay.min()}


def esit_riskf(df, hedef_risk, cap=1.50):
    """Verilen ort riski CAP sabitken üreten RISKF'i ikili aramayla bul."""
    lo, hi = 0.001, 0.50
    for _ in range(80):
        mid = (lo + hi) / 2
        if olc(df, mid, cap)["risk"] < hedef_risk: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def sinav1(df):
    t = olc(df, A.CANLI_RISKF, A.CANLI_CAP)
    print(f"\n{'=' * 96}\n=== SINAV 1: VERİMLİLİK Mİ, KALDIRAÇ MI? ===")
    print(f"  TABAN  risk %{A.CANLI_RISKF*100:.2f} · CAP {A.CANLI_CAP}  →  "
          f"${t['kar']:+.2f} · ort gerçekleşen risk %{t['risk']:.4f}\n")
    print(f"  {'yol':<36s} {'ort risk':>9s} {'kâr $':>10s} {'Δ$':>8s} "
          f"{'maxDD':>7s} {'en kötü ay':>11s}")
    for cap in (2.0, 2.5, 3.0, 4.0):
        c = olc(df, A.CANLI_RISKF, cap)
        f = olc(df, esit_riskf(df, c["risk"]), A.CANLI_CAP)
        print(f"  {f'CAP {cap} (risk sabit)':<36s} {c['risk']:>8.4f}% {c['kar']:>+10.2f} "
              f"{c['kar']-t['kar']:>+8.2f} {c['dd']:>6.2f}% {c['kotu']:>10.2f}%")
        print(f"  {'  ↳ AYNI riski düz artışla':<36s} {f['risk']:>8.4f}% {f['kar']:>+10.2f} "
              f"{f['kar']-t['kar']:>+8.2f} {f['dd']:>6.2f}% {f['kotu']:>10.2f}%"
              f"   → CAP {'KAZANIYOR' if c['kar'] > f['kar'] else 'KAYBEDİYOR'} "
              f"(${c['kar']-f['kar']:+.2f})")
    print(f"\n  ⓘ En kötü ay sütununa bak: CAP yolu kuyruğu İYİLEŞTİRİRKEN düz risk")
    print(f"    artışı onu KÖTÜLEŞTİRİYOR. Aynı riskle zıt kuyruk davranışı, farkın")
    print(f"    kaldıraçtan değil DAĞILIMDAN geldiğinin işaretidir.")


def sinav2(df):
    print(f"\n{'=' * 96}\n=== SINAV 2: MEKANİZMA — dar stop neden daha iyi? ===")
    print(f"  Kol SABİT tutulur (yoksa 'dar stop' aslında 'squeeze' demek olabilir),")
    print(f"  ve 'sure' çıkışları AYRICA hariç tutulur (normalizasyon artefaktı sınavı).\n")
    for kol in ("squeeze", "donchian", "bb"):
        s = df[df["kol"] == kol].copy()
        if len(s) < 60: continue
        s["dilim"] = pd.qcut(s["slp"], 3, labels=["dar", "orta", "geniş"])
        print(f"  ── {kol} (n={len(s)}) ──")
        print(f"     {'dilim':<7s} {'stop%':>7s} {'TP oranı':>9s} {'ort R':>8s} "
              f"{'ort R (sure hariç)':>20s} {'%95 aralık':>18s}")
        for d in ("dar", "orta", "geniş"):
            v = s[s["dilim"] == d]
            w = v[v["cikis"] != "sure"]
            se = w["R"].std() / np.sqrt(len(w))
            print(f"     {d:<7s} {v['slp'].mean()*100:>6.2f}% "
                  f"{(v['cikis']=='tp').mean()*100:>8.1f}% {v['R'].mean():>+8.3f} "
                  f"{w['R'].mean():>+20.3f} "
                  f"[{w['R'].mean()-1.96*se:>+7.3f},{w['R'].mean()+1.96*se:>+7.3f}]")
        print()
    print(f"  ⓘ tp hep +RR, sl hep −1R olduğu için 'sure hariç' sütununda R SINIRLI.")
    print(f"    Orada da fark varsa avantaj isabet oranından gelir, ölçekten DEĞİL.")


if __name__ == "__main__":
    df = yukle()
    sinav1(df)
    sinav2(df)
    print(f"{'=' * 96}\n")
