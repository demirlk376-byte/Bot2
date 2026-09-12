"""
dd_durdur.py — "bot %5 zarar edince rejim düzelene kadar dursun" fikrinin ölçümü.

⚠ NEDENSELLİK: duraklama kararı YALNIZ o ana kadar KAPANMIŞ işlemlerden
   hesaplanan equity ile veriliyor. Açık pozisyonların gerçekleşmemiş kârı
   sayılmıyor — canlıda da öyle olurdu (defter kapanınca yazıyor).

⚠ ÖNCEKİ RET VE MEKANİZMASI (pf_killswitch, 2026-07-27): 27 formun 27'si düştü.
   Kayıtlı sebep: "aylık PnL ortalamaya döner (otokorelasyon −0.345), kill-switch
   tam dipte küçültür, toparlanmayı küçük pozisyonla karşılar." Ayrıca `halt`
   formları KİLİTLENİYORDU: durunca yeni işlem kapanmaz → tetik göstergesi donar
   → bir daha açılmaz. Bu betikte o tuzak YOK, çünkü tetik equity ve equity
   duraklamada da sabit kalır ama TEPE de sabit kalır, yani oran donmaz.

   Kullanıcının versiyonunun farkı YENİDEN BAŞLAMA ŞARTI. Üç aile denenir:
   (a) sabit süre, (b) equity toparlanması, (c) "rejim düzeldi" (ADX/CHOP).

Kullanım:  py dd_durdur.py
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A


def yukle():
    df = pd.read_csv("data/ay_analiz.csv")
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["giris_ts"] = pd.to_datetime(df["giris"])
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["pnl"] = df["R"] * df["eff"] * A.BAL0
    return df.sort_values("giris_ts").reset_index(drop=True)


def simule(df, esik, kural, param):
    """esik: tepeden % düşüş (pozitif sayı). kural: 'sure'|'toparla'|'rejim'."""
    kapanislar = df[["cikis_ts", "pnl"]].sort_values("cikis_ts").values
    ki = 0
    eq = A.BAL0
    tepe = A.BAL0
    duraklama = False
    durak_bas = None
    alinan = []
    for i, r in df.iterrows():
        # o ana kadar KAPANMIŞ işlemleri equity'ye yaz (nedensel)
        while ki < len(kapanislar) and kapanislar[ki][0] <= r.giris_ts:
            eq += kapanislar[ki][1]; tepe = max(tepe, eq); ki += 1
        dd = (tepe - eq) / tepe if tepe > 0 else 0.0
        if not duraklama and dd >= esik:
            duraklama = True; durak_bas = r.giris_ts
        if duraklama:
            ac = False
            if kural == "sure":
                ac = (r.giris_ts - durak_bas) >= pd.Timedelta(days=param)
            elif kural == "toparla":
                ac = dd <= param
            elif kural == "rejim":
                ac = (r.adx14 >= param) if np.isfinite(r.adx14) else True
            if ac: duraklama = False
            else: continue
        alinan.append(i)
    return df.loc[alinan]


def olc(d):
    if len(d) < 50: return None
    s = d.sort_values("cikis_ts")
    pnl = s["pnl"].values
    eq = A.BAL0 + np.cumsum(pnl)
    ay = pd.Series(pnl, index=s["cikis_ts"].dt.tz_localize(None).dt.to_period("M").values
                   ).groupby(level=0).sum() / A.BAL0 * 100
    return {"n": len(s), "kar": pnl.sum(), "dd": A.maxdd(np.concatenate([[A.BAL0], eq])),
            "kotu": ay.min()}


def main():
    df = yukle()
    t = olc(df)
    print(f"\n{'=' * 96}\n=== DRAWDOWN TETİKLİ DURAKLAMA ===")
    print(f"  TABAN {t['n']} işlem · ${t['kar']:+.2f} · maxDD %{t['dd']:.2f} · "
          f"en kötü ay %{t['kotu']:.2f}\n")
    print(f"  {'tetik':>6s} {'yeniden başlama':<26s} {'kalan':>6s} {'atlanan':>8s} "
          f"{'atlananın $':>12s} {'Δ$':>9s} {'ΔmaxDD':>7s} {'Δkötüay':>8s}  BAR")
    kurallar = ([("sure", g, f"{g} gün sonra") for g in (1, 3, 7)] +
                [("toparla", p, f"DD %{p*100:.0f}'e inince") for p in (0.03, 0.01, 0.0)] +
                [("rejim", a, f"ADX >= {a} olunca") for a in (20, 25, 30)])
    n = 0
    for esik in (0.05, 0.10, 0.15, 0.20):
        for kural, param, ad in kurallar:
            d = simule(df, esik, kural, param)
            m = olc(d)
            if m is None: continue
            n += 1
            atl = t["n"] - m["n"]
            atl_pnl = t["kar"] - m["kar"]
            gec = (m["kar"] - t["kar"] >= 36 and m["kotu"] >= t["kotu"]
                   and m["dd"] - t["dd"] <= 2.0)
            print(f"  {esik*100:>5.0f}% {ad:<26s} {m['n']:>6d} {atl:>8d} "
                  f"{atl_pnl:>+12.2f} {m['kar']-t['kar']:>+9.2f} {m['dd']-t['dd']:>+7.2f} "
                  f"{m['kotu']-t['kotu']:>+8.2f}  {'✓ GEÇTİ' if gec else '✗'}")
    print(f"\n  {n} hücre denendi.")
    print(f"  ⓘ 'atlananın $' pozitifse duraklama KÂRLI işlemleri atlamış demektir.")
    print(f"    Bir duraklama ancak atladığı kümenin toplamı NEGATİFSE kazandırır.")
    print(f"{'=' * 96}\n")


if __name__ == "__main__":
    main()
