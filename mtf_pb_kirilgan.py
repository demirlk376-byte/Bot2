"""
mtf_pb_kirilgan.py — en iyi hücrenin +$139'u KIRILGAN MI?
  · coin-coin, yıl-yıl dağılım
  · jackknife: her coini tek tek çıkar
  · rastgele %9 işlem düşür (koltuk kaybının taklidi) → dağılım
Ayrıca: aday kolun aylık PnL oynaklığının kitaba etkisi.
"""
import numpy as np, pandas as pd
import deployed_backtest as A
import mtf_pullback as P
from mtf_pb_tara import COINS, veri
from mtf_pb_taban import ham_taban, strip, olc

KW = dict(trend="T1", tetik="rsi", stop=("swing", 10), rr=2.5)


def usd(t):
    R = np.array([x[2] for x in t]); sp = np.array([x[3] for x in t])
    return (R * np.minimum(A.CANLI_RISKF, A.CANLI_CAP * sp) * A.BAL0)


def main():
    V = veri()
    per = {c: P.uret(c, V[c], **KW) for c in COINS}
    print("  --- COIN-COIN (T1/rsi/swing10/rr2.5) ---")
    for c in COINS:
        p = usd(per[c]); print(f"    {c:5s} n={len(p):4d}  ${p.sum():+8.2f}")
    allt = [x for c in COINS for x in per[c]]
    p = usd(allt); ex = pd.to_datetime([x[1] for x in allt])
    print(f"    TOPLAM n={len(allt)}  ${p.sum():+.2f}")
    yil = pd.Series(p, index=ex.year).groupby(level=0).sum()
    print("  --- YIL-YIL ---")
    for y, v in yil.items(): print(f"    {y}: ${v:+8.2f}")
    print("  --- JACKKNIFE (coin çıkar) ---")
    for c in COINS:
        r = [x for cc in COINS if cc != c for x in per[cc]]
        print(f"    -{c:5s} → ${usd(r).sum():+8.2f}")
    print("  --- RASTGELE %9 İŞLEM DÜŞÜR (koltuk kaybının taklidi, 200 tekrar) ---")
    rng = np.random.default_rng(7); k = int(len(allt) * 0.91)
    s = np.array([usd([allt[i] for i in rng.choice(len(allt), k, replace=False)]).sum()
                  for _ in range(200)])
    print(f"    ${s.mean():+.2f} ± {s.std():.2f}   aralık {s.min():+.0f}..{s.max():+.0f}")
    print(f"    → tam örneklem +${p.sum():.0f}; %9 düşürmek sonucu ±${s.std():.0f} oynatıyor.")
    print("  --- AYLIK OYNAKLIK ---")
    ay = pd.Series(p, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()
    d = ham_taban(); T = olc(A.seat_select(strip(d["donch"])+strip(d["sqz"])+strip(d["bb"])))
    kit = T["ay"] * A.BAL0 / 100
    print(f"    kol  : aylık ort ${ay.mean():+.2f} std ${ay.std():.2f}  en kötü ${ay.min():+.2f}")
    print(f"    kitap: aylık ort ${kit.mean():+.2f} std ${kit.std():.2f}  en kötü ${kit.min():+.2f}")


if __name__ == "__main__":
    main()
