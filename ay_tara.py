"""
ay_tara.py — kötü-ay aday filtreleri için TEK HAKEM.

Neden tek hakem: aynı fikri üç ayrı betikte üç ayrı yöntemle ölçersek üç ayrı
sayı çıkar ve hangisinin doğru olduğunu tartışmaya başlarız. Burada yöntem BİR
kez yazıldı; her aday aynı testten geçiyor.

ADAY = pandas sorgusu. Sorguya UYAN işlemler SİLİNİR (filtre onları eler).

ÖN-KAYITLI BAR (ledger'daki barın canlı ölçeğine taşınmış hâli):
  1. Δ$ ≥ +36            (ledger +28 × canlı ölçek 1.293)
  2. en kötü ay KÖTÜLEŞMEYECEK
  3. maxDD +2 puandan fazla artmayacak
  4. hiçbir yıl %10'dan fazla kötüleşmeyecek
Ek olarak kullanıcının şartı:
  5. İYİ AYLARA DOKUNMA — iyi aylardan silinen işlem oranı ≤ %5

⚠ İKİ KONTROL, ikisi de zorunlu:

  A) NEGATİFLİK: silinen alt kümenin ort R'si NEGATİF olmalı. Pozitif ortalamalı
     bir kümeyi silmek tanımı gereği para kaybettirir. Gerekli ama YETERLİ DEĞİL.

  B) PERMÜTASYON: aynı SAYIDA işlemi RASTGELE silmekle kıyas. Ledger'ın 290
     denemelik bulgusu: "ne silinirse silinsin, silmek negatif beklentidir."
     Yani bir filtrenin rastgele silmeyi yenmesi gerekir, sıfırı değil.
     Rastgele dağılımın %95'ini geçemeyen aday GÜRÜLTÜDÜR.

Kullanım:
  py ay_tara.py "adx14 < 20"
  py ay_tara.py --liste dosya.txt        # her satır bir aday
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

VERI = "data/ay_analiz.csv"
BAL0 = A.BAL0
PERM = 4000
TOHUM = 20260909
BAR_KAR = 28.0 * A.CANLI_OLCEK      # +36.2
IYI_AY_TAVAN = 0.05                 # iyi aylardan en fazla %5 silinebilir


def yukle():
    try:
        df = pd.read_csv(VERI)
    except OSError as e:
        print(f"✗ {VERI} okunamadı: {e}\n  Önce: python3 ay_veri.py local")
        sys.exit(2)
    if len(df) != 1579:
        print(f"✗ {VERI} {len(df)} satır, 1579 bekleniyordu. Yeniden üret.")
        sys.exit(2)
    df["cikis_ts"] = pd.to_datetime(df["cikis_ts"])
    df["ay_p"] = df["cikis_ts"].dt.tz_localize(None).dt.to_period("M")
    return df.sort_values("cikis_ts").reset_index(drop=True)


def olc(df, mask_tut):
    """mask_tut=True olan işlemlerle portföy ölçüleri. Sıra ÇIKIŞ sırası."""
    d = df[mask_tut]
    if len(d) < 50:
        return None
    pnl = (d["R"] * d["eff"] * BAL0).values
    eq = BAL0 + np.cumsum(pnl)
    dd = A.maxdd(np.concatenate([[BAL0], eq]))
    ay = pd.Series(pnl, index=d["ay_p"].values).groupby(level=0).sum() / BAL0 * 100
    yil = pd.Series(pnl, index=d["cikis_ts"].dt.year.values).groupby(level=0).sum()
    return {"kar": pnl.sum(), "dd": dd, "kotu_ay": ay.min(), "n": len(d),
            "ay": ay, "yil": yil, "pf": pnl[pnl > 0].sum() / max(-pnl[pnl < 0].sum(), 1e-9),
            "wr": (d["R"] > 0).mean() * 100}


def degerlendir(df, taban, iyi_aylar, kotu_aylar, sorgu, rng, sessiz=False):
    try:
        sil = df.eval(sorgu).values
    except Exception as e:
        print(f"  ✗ '{sorgu}' → sorgu hatası: {type(e).__name__}: {e}")
        return None
    sil = np.asarray(sil, dtype=bool)
    if sil.sum() == 0:
        if not sessiz: print(f"  ⊘ '{sorgu}' hiçbir işlemi silmiyor")
        return None
    if sil.all():
        if not sessiz: print(f"  ⊘ '{sorgu}' HER İŞLEMİ siliyor")
        return None

    yeni = olc(df, ~sil)
    if yeni is None:
        if not sessiz: print(f"  ⊘ '{sorgu}' geriye 50'den az işlem bırakıyor")
        return None

    silinen = df[sil]
    r_sil = silinen["R"].mean()
    ay_ort = df["ay_p"].values
    iyi_sil = sil[np.isin(ay_ort, iyi_aylar)].mean() if len(iyi_aylar) else 0.0
    kotu_sil = sil[np.isin(ay_ort, kotu_aylar)].mean() if len(kotu_aylar) else 0.0

    # PERMÜTASYON: aynı sayıda RASTGELE silme
    k = int(sil.sum()); n = len(df)
    perm = np.empty(PERM)
    for t in range(PERM):
        m = np.ones(n, dtype=bool)
        m[rng.choice(n, size=k, replace=False)] = False
        p = (df["R"].values * df["eff"].values * BAL0)[m]
        perm[t] = p.sum()
    yuzdelik = (perm < yeni["kar"]).mean() * 100

    d_kar = yeni["kar"] - taban["kar"]
    d_dd = yeni["dd"] - taban["dd"]
    d_kotu = yeni["kotu_ay"] - taban["kotu_ay"]
    yil_ort = taban["yil"].reindex(yeni["yil"].index).fillna(0)
    d_yil = (yeni["yil"] - yil_ort) / yil_ort.abs().replace(0, np.nan) * 100
    en_kotu_yil = d_yil.min() if len(d_yil) else 0.0

    gecti = (d_kar >= BAR_KAR and d_kotu >= -1e-9 and d_dd <= 2.0
             and (en_kotu_yil >= -10.0 or np.isnan(en_kotu_yil))
             and iyi_sil <= IYI_AY_TAVAN and r_sil < 0 and yuzdelik >= 95.0)

    return {"sorgu": sorgu, "sil_n": k, "sil_pct": k / n * 100, "r_sil": r_sil,
            "iyi_sil": iyi_sil * 100, "kotu_sil": kotu_sil * 100,
            "d_kar": d_kar, "d_dd": d_dd, "d_kotu": d_kotu,
            "kotu_ay": yeni["kotu_ay"], "pf": yeni["pf"], "wr": yeni["wr"],
            "perm_yuzdelik": yuzdelik, "perm_ort": perm.mean() - taban["kar"],
            "en_kotu_yil": en_kotu_yil, "gecti": gecti}


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    df = yukle()
    rng = np.random.default_rng(TOHUM)
    taban = olc(df, np.ones(len(df), dtype=bool))
    ay = taban["ay"]
    iyi_aylar = ay[ay > 0].index.values
    kotu_aylar = ay[ay <= 0].index.values

    print(f"\n{'=' * 104}")
    print(f"=== ADAY TARAMASI ===   taban: {taban['n']} işlem · ${taban['kar']:+.2f} · "
          f"maxDD %{taban['dd']:.2f} · en kötü ay %{taban['kotu_ay']:.2f} · PF {taban['pf']:.2f}")
    print(f"  ay: {len(ay)} toplam · iyi {len(iyi_aylar)} · kötü {len(kotu_aylar)}   "
          f"(kötü aylar: {', '.join(str(x) for x in kotu_aylar)})")
    print(f"  BAR: Δ$≥{BAR_KAR:+.0f} · en kötü ay kötüleşmesin · maxDD ≤+2p · yıl ≥−%10")
    print(f"       · iyi aylardan silme ≤%{IYI_AY_TAVAN*100:.0f} · silinen ort R<0 · perm ≥%95\n")

    if sys.argv[1] == "--liste":
        adaylar = [x.strip() for x in open(sys.argv[2], encoding="utf-8")
                   if x.strip() and not x.strip().startswith("#")]
    else:
        adaylar = [" ".join(sys.argv[1:])]

    print(f"  {'aday':<42s} {'sil%':>5s} {'ortR':>6s} {'iyi%':>5s} {'kötü%':>6s} "
          f"{'Δ$':>8s} {'ΔmaxDD':>7s} {'Δkötüay':>8s} {'perm%':>6s}  BAR")
    sonuc = []
    for q in adaylar:
        r = degerlendir(df, taban, iyi_aylar, kotu_aylar, q, rng)
        if r is None: continue
        sonuc.append(r)
        print(f"  {q[:42]:<42s} {r['sil_pct']:>4.1f}% {r['r_sil']:>+6.3f} "
              f"{r['iyi_sil']:>4.1f}% {r['kotu_sil']:>5.1f}% {r['d_kar']:>+8.2f} "
              f"{r['d_dd']:>+7.2f} {r['d_kotu']:>+8.2f} {r['perm_yuzdelik']:>5.1f}%  "
              f"{'✓ GEÇTİ' if r['gecti'] else '✗'}")

    gecen = [r for r in sonuc if r["gecti"]]
    print(f"\n  {len(gecen)}/{len(sonuc)} aday barı geçti.")
    if not gecen:
        print(f"  Not: 'Δ$' sütunu rastgele silmeye göre DEĞİL, tabana göre. Rastgele")
        print(f"  silmenin ortalama etkisi bu boyutta ${np.mean([r['perm_ort'] for r in sonuc]):+.0f}.")
        print(f"  Bir adayın anlamlı olması için perm% ≥95 OLMALI — yoksa aynı sayıda")
        print(f"  rastgele işlem silmekten farkı yok.")
    print(f"{'=' * 104}\n")


if __name__ == "__main__":
    main()
