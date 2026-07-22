"""
bb_expand.py — BB/mean-reversion sleeve'ini tüm coinlerde tara (faithful=byte-exact, yıl-yıl).

NEDEN: eklediğimiz her şey (donchian coinleri) TREND + korelasyonlu → mutlak $ artar ama DD
çeşitlenmez. Portföy DD'sini GERÇEKTEN düşüren tek şey DÜŞÜK-KORELASYONLU getiri akışı.
BB = hafta-sonu mean-reversion (ADX<28 ranging, SL3ATR rr1.667) → trend sleeve'leriyle yapısal
olarak düşük korelasyonlu (farklı zaman + ters mantık). Robust BB coin'leri = gerçek DD-düşürücü.

prod_bb faithful (canlı MeanReversionStrategy + simtrades, byte-exact — yaklaşıklık YOK).
Aday = HER YIL pozitif + ÇAKIŞMASIZ (donchian/squeeze'de olmayan coin, netted tek-pozisyon).

Kullanım:  py bb_expand.py local
"""
import sys
import numpy as np
import fast_bt
import faithful_bt

BAL = 190.0; RISK = 0.02
DONCH = {"SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"}
SQZ = {"XRP", "DOGE", "TRX", "XLM"}
BB_NOW = {"LTC"}
ALL = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
       "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]


def summ(tr):
    if not tr: return "yok", [], False
    r = np.array([t["r"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    ys = sorted(set(t["year"] for t in tr))
    yv = [(y, sum(t["r"] for t in tr if t["year"] == y) * BAL * RISK) for y in ys]
    every = all(v > 0 for _, v in yv)
    s = f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"
    return s, yv, every


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    robust_free = []; robust_used = []
    for c in ALL:
        try: m = fast_bt.load(c, source=source)
        except Exception as e: print(f"  {c}: yüklenemedi {e}"); continue
        tr = faithful_bt.prod_bb(m, weekend_only=True)
        s, yv, every = summ(tr)
        used = c in DONCH or c in SQZ or c in BB_NOW
        where = ("[donchian]" if c in DONCH else "[squeeze]" if c in SQZ else "[BB-şu an]" if c in BB_NOW else "[BOŞ]")
        tag = "✅HER-YIL+" if every else "  karışık"
        yrs = " ".join(f"{y}:${v:+.0f}" for y, v in yv)
        tot = sum(v for _, v in yv)
        print(f"  {c:5s} {where:11s} {tag}: {s}   [{yrs}]")
        if every and tot > 0:
            (robust_used if used else robust_free).append((c, tot))
    print(f"\n{'='*72}\n=== BB ROBUST (HER YIL +) ===")
    print(f"  ÇAKIŞMASIZ (eklenebilir, DD-düşürücü aday): " +
          (", ".join(f"{c}(${t:+.0f})" for c, t in sorted(robust_free, key=lambda x: -x[1])) or "— yok"))
    print(f"  Meşgul (bilgi; sleeve değişimi gerekir): " +
          (", ".join(f"{c}(${t:+.0f})" for c, t in sorted(robust_used, key=lambda x: -x[1])) or "— yok"))
    print("\n  BB hafta-sonu = trend sleeve'leriyle düşük-korelasyon → robust çakışmasız coin eklemek")
    print("  mutlak $ + risk-ayarlı (DD↓) katkı yapar. Aday → filter_test/faithful + portfolio_sim ile doğrula.")


if __name__ == "__main__":
    main()
