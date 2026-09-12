"""
coin_maliyet.py — coin başına NET getiri: kayma düşülünce hangi coin ölüyor?

FİKRİN KAYNAĞI (2026-09-12): oturum boyunca kanıtlandı ki GETİRİ elimizdeki
bilgiyle iyileştirilemiyor (4 bilgi kanalı, hepsi null). Ama MALİYET
ölçülebiliyor ve deterministik. Kaymanın R bedeli `15.85bp / stop_mesafesi`;
stop dar oldukça bedel katlanıyor.

⚠ BU, PERFORMANSA GÖRE COIN SEÇMEK DEĞİL. O denendi ve yürüyen-ileri testinde
   DÜŞTÜ (coin_expand; donchian coinleri 21 içinde ort sıra 4.6, seçim ileriye
   taşınmıyor). Buradaki kural bir TAHMİN değil bir MALİYET hesabı:
     · stop genişliği coinin YAPISAL özelliği (oynaklığından geliyor)
     · kayma/stop deterministik
     · karar geçmiş kâra DEĞİL, maliyetin edge'e oranına bakıyor

KURAL: kayma_R / sistem_edge > eşik ise coin/kol çifti PAHALI.

Kullanım:  py coin_maliyet.py [esik]     (varsayılan 0.60)
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

KAYMA_BP = 15.85     # kayma_denetim.py · 2026-09-09 · n=54 · [%95: 8.34, 23.37]
MIN_N = 20


def main():
    esik = float(sys.argv[1]) if len(sys.argv) > 1 else 0.60
    df = pd.read_csv("data/ay_analiz.csv")
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["kayma_R"] = (KAYMA_BP / 1e4) / df["slp"]
    df["net_R"] = df["R"] - df["kayma_R"]
    df["brut_$"] = df["R"] * df["eff"] * A.BAL0
    df["net_$"] = df["net_R"] * df["eff"] * A.BAL0
    edge = df["R"].mean()

    print(f"\n{'=' * 92}\n=== COIN BAŞINA MALİYET DENETİMİ ===")
    print(f"  sistem ort edge {edge:+.4f}R · giriş kayması {KAYMA_BP}bp · "
          f"eşik: kayma yükü > %{esik*100:.0f}\n")
    g = df.groupby(["kol", "coin"]).agg(
        n=("R", "size"), stop=("slp", "mean"), kayma_R=("kayma_R", "mean"),
        brut_R=("R", "mean"), net_R=("net_R", "mean"),
        brut=("brut_$", "sum"), net=("net_$", "sum")).reset_index()
    g["yuk"] = g["kayma_R"] / edge
    g = g.sort_values("yuk", ascending=False)
    print(f"  {'kol':<9s} {'coin':<5s} {'n':>4s} {'ort stop':>9s} {'kayma_R':>8s} "
          f"{'edge yükü':>10s} {'brüt R':>8s} {'NET R':>8s} {'NET $':>9s}")
    for _, r in g.iterrows():
        im = "  ⛔ PAHALI" if (r.yuk > esik and r.n >= MIN_N) else ""
        print(f"  {r.kol:<9s} {r.coin:<5s} {int(r.n):>4d} {r.stop*100:>8.2f}% "
              f"{r.kayma_R:>8.4f} {r.yuk*100:>9.1f}% {r.brut_R:>+8.4f} "
              f"{r.net_R:>+8.4f} {r.net:>+9.2f}{im}")
    pahali = g[(g.yuk > esik) & (g.n >= MIN_N)]
    print(f"\n  brüt ${g.brut.sum():+.2f} → kayma ${g.brut.sum()-g.net.sum():.2f} "
          f"(%{(g.brut.sum()-g.net.sum())/g.brut.sum()*100:.1f}) → NET ${g.net.sum():+.2f}")
    if len(pahali):
        print(f"  PAHALI: {', '.join(f'{r.coin}/{r.kol}' for _, r in pahali.iterrows())}"
              f" → çıkarılırsa net {-pahali.net.sum():+.2f} kazanılır "
              f"(${-pahali.net.sum()/3.24:.2f}/yıl)")
    else:
        print(f"  PAHALI coin YOK (eşik %{esik*100:.0f})")

    # ── yürüyen-ileri: kararı 1. yarıda ver, 2. yarıda ölç ──
    df = df.sort_values("cikis_ts").reset_index(drop=True)
    kes = df["cikis_ts"].iloc[len(df) // 2]
    h1, h2 = df[df.cikis_ts < kes], df[df.cikis_ts >= kes]
    k1 = h1.groupby(["kol", "coin"]).agg(kayma_R=("kayma_R", "mean"), n=("R", "size"))
    sec = set(k1[(k1.kayma_R / edge > esik) & (k1.n >= MIN_N)].index)
    print(f"\n  YÜRÜYEN-İLERİ (karar YALNIZ 1. yarıdan)")
    print(f"    1. yarıda pahalı: {[c for _, c in sec] or 'yok'}")
    if sec:
        m = h2.set_index(["kol", "coin"]).index.isin(sec)
        a = h2[m]
        print(f"    2. yarıda o coinler: {len(a)} işlem · brüt ${a['brut_$'].sum():+.2f} "
              f"· NET ${a['net_$'].sum():+.2f}")
        print(f"    → {'✓ karar İLERİYE TAŞINDI' if a['net_$'].sum() < 0 else '✗ TAŞINMADI'}")
    print(f"\n  ⚠ Bu kural kaymanın SABİT 15.85bp olduğunu varsayıyor (donchian")
    print(f"    girişlerinden ölçüldü, n=54). Coin bazında GERÇEK kayma hiç")
    print(f"    ölçülmedi — dar stoplu/küçük nominal işlemlerde farklı olabilir.")
    print(f"    Maker girişi squeeze'e taşınırsa bu tablonun tamamı değişir.")
    print(f"{'=' * 92}\n")


if __name__ == "__main__":
    main()
