"""
tavan_beceri.py — "kâhin $3070 kazanıyor" ile "biz ne kazanırız" ARASINDAKİ FARK.

NEDEN VAR: gün bazında mükemmel kâhinin tavanı +$2922 çıktı ve bu rakam
"orada duran para" gibi okundu. DEĞİL. Tavan, geleceği KESİN bilenin kazancıdır
(AUC = 1.00). Ulaşılabilir kazanç dedektörün BECERİSİNE bağlıdır ve beceri
sıfırken gün atlamak PARA KAYBETTİRİR — çünkü kazançlı günler de atlanır.

Bu betik o eğriyi çizer: AUC → ulaşılabilir $.

⚠ DOĞRU TABAN AUC 0.50 SATIRIDIR, sıfır değil. Günlerin %53'ü zararlı olduğu
   için rastgele gün atlamak bile "zarar sildi" gibi görünebilir; gerçek ölçüt
   aynı sayıda RASTGELE günü ne kadar yendiğindir.

Kullanım:  py tavan_beceri.py
"""
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A

TOHUM = 20260909
TEKRAR = 400
OLCULEN_AUC = 0.47      # ay-dışı çapraz doğrulama, 17 fiyat özelliği + BTC (2026-09-09)


def auc(skor, etiket):
    r = pd.Series(skor).rank().values
    n1 = etiket.sum(); n0 = len(etiket) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    return (r[etiket].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def main():
    df = pd.read_csv("data/ay_analiz.csv")
    if len(df) != 1579:
        print(f"✗ {len(df)} satır, 1579 bekleniyordu"); sys.exit(2)
    df["giris_ts"] = pd.to_datetime(df["giris"])
    df["gun"] = df["giris_ts"].dt.tz_localize(None).dt.date
    g = df.groupby("gun").apply(lambda x: (x["R"] * x["eff"] * A.BAL0).sum())
    kayip = (g.values < 0)
    rng = np.random.default_rng(TOHUM)

    print(f"\n{'=' * 88}")
    print(f"=== BECERİ → ULAŞILABİLİR KAZANÇ ===")
    print(f"  taban ${g.sum():+.2f} · {len(g)} gün · {int(kayip.sum())} zararlı "
          f"(%{kayip.mean()*100:.0f})")
    print(f"  MÜKEMMEL KÂHİN (AUC 1.00): ${-g[g < 0].sum():+.2f}  ← ULAŞILAMAZ TAVAN\n")
    print(f"  {'AUC':>6s} {'atla %10':>10s} {'atla %20':>10s} {'atla %30':>10s} "
          f"{'atla %50':>10s}   yorum")
    for d, not_ in ((0.0, "beceri YOK = rastgele"), (0.18, ""), (0.37, "ölçülen en iyi (iç-örnek)"),
                    (0.57, ""), (0.80, ""), (1.05, ""), (3.0, "≈mükemmele yakın")):
        kaz = {p: [] for p in (0.10, 0.20, 0.30, 0.50)}
        a_olc = []
        for _ in range(TEKRAR):
            skor = d * kayip + rng.standard_normal(len(g))
            a_olc.append(auc(skor, kayip))
            sira = np.argsort(-skor)
            for p in kaz:
                kaz[p].append(-g.values[sira[:int(len(g) * p)]].sum())
        print(f"  {np.mean(a_olc):>6.3f} " +
              " ".join(f"{np.mean(kaz[p]):>+10.2f}" for p in (0.10, 0.20, 0.30, 0.50)) +
              (f"   {not_}" if not_ else ""))

    print(f"\n  {'—' * 80}\n  NASIL OKUNMALI")
    print(f"    · AUC 0.50 satırı NEGATİF: beceri yokken gün atlamak para KAYBETTİRİR,")
    print(f"      çünkü kazançlı günler de atlanır. Doğru taban budur, sıfır değil.")
    print(f"    · Bugüne kadar ÖLÇÜLEN ayrım gücü: iç-örnek 0.60, ay-dışı çapraz")
    print(f"      doğrulamada {OLCULEN_AUC} — yani yazı-turadan KÖTÜ.")
    print(f"    · Tavana ($2922) yaklaşmak AUC ~0.98 ister. 0.47 ile 0.98 arası")
    print(f"      daha çok veri kaynağıyla kapanmaz; kapanacak olsaydı 0.47 zaten")
    print(f"      0.55 olurdu.")
    print(f"    · Bu tablo VERİ KAYNAĞINDAN BAĞIMSIZDIR. Hangi siteden ne çekilirse")
    print(f"      çekilsin, katkısı yalnız AUC üzerinden geçer.")
    print(f"{'=' * 88}\n")


if __name__ == "__main__":
    main()
