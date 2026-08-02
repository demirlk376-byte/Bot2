HYP = 'H1'
"""
power_test.py — ÖLÇÜM GÜCÜNÜ 10× ARTIR: 22 coin × 4 zaman dilimi × eşleştirilmiş karşılaştırma.

SORUN (bugün teşhis edildi): 1579 işlemle bir varyantın %10 daha iyi olduğunu kanıtlamak için
~12.700 işlem gerekiyor. 8 kat eksiğiz. Bu yüzden 8 bağımsız ailede TRAIN→TEST transferi yok:
varyant düzeyinde GÜRÜLTÜ ölçüyoruz.

ASIL FARK ETTİĞİM: darboğaz veri değil, ÖLÇÜM TASARIMI. Üç israf:
 1. 7 coin kullandım — elimde 22 coin var. Coin eklemek DEPLOY için koltuk yüzünden işe
    yaramıyordu; ama ÖLÇÜM için koltuk diye bir kısıt YOK. Bu ikisini karıştırmışım.
 2. Tek zaman dilimi (4h). 2h/4h/6h/12h ayrı (kısmen bağımsız) örnekler verir.
 3. PORTFÖY TOPLAMI karşılaştırdım. Koltuk seçimi, sorumuzla ilgisi olmayan devasa bir gürültü
    ekliyor (hangi işlemin koltuk bulduğu tetikleyici kalitesinden bağımsız). Eşleştirilmiş
    işlem-bazlı karşılaştırma bu gürültüyü tamamen ortadan kaldırır.

TASARIM: her (coin, tf) hücresinde iki tetikleyici AYNI kurallarla koşulur (EMA200 kapısı,
SL 2×ATR, rr 2.5, maxhold 30, occ). Koltuk seçimi YOK — bu bir portföy inşası aracı, tetikleyici
kalitesi sorusunun parçası değil.

İKİ TEST:
 A) İŞARET TESTİ (parametrik olmayan, güçlü): 22×4 = 88 hücrenin kaçında Bollinger kazanıyor?
    Hepsi eşdeğerse beklenen 44. Binom testi. Büyüklükten bağımsız, aykırı değerlere dayanıklı.
 B) HAVUZLANMIŞ ORTALAMA R FARKI + standart hata: tüm işlemler birleştirilerek.

DÜRÜSTLÜK: bu bir ÖLÇÜM, deploy kararı değil. Bollinger kazansa bile canlıya almak AYRI bir
karardır (kod riski, ön-kayıt H1'in şartları). Amaç "bilmiyoruz"u "biliyoruz"a çevirmek.

Kullanım:  py power_test.py local
"""
import sys
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, ema as ema_fn

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
TFS = ["2h", "4h", "6h", "12h"]
FEE = 0.0001; SL_A, RR, MH = 2.0, 2.5, 30
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")


def trig_donchian(d, n=40):
    hi = d["high"].rolling(n).max().shift(1).values
    lo = d["low"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


def trig_bollinger(d, n=20, k=2.0):
    m = d["close"].rolling(n).mean().shift(1).values
    s = d["close"].rolling(n).std().shift(1).values
    c = d["close"].values
    return c > m + k * s, c < m - k * s


def run(d, trig, stop="atr"):
    """occ'lu üretim, koltuk seçimi YOK. Dönüş: (R dizisi, giriş zamanı dizisi)."""
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    e200 = ema_fn(d["close"], 200).values
    L, S = trig(d)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    Rs = []; ts = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ or not np.isfinite(e200[i]): continue
        c = cl[i]; d_ = 0
        if L[i] and c > e200[i]: d_ = 1
        elif S[i] and c < e200[i]: d_ = -1
        if d_ == 0: continue
        sld = (SL_A * a) if stop == "atr" else (0.04 * c)
        if not np.isfinite(sld) or sld <= 0: continue
        slp = c - d_ * sld; tp = c + d_ * RR * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        Rs.append(d_ * (ep - c) / sld - 2 * FEE * c / sld); ts.append(idx[i]); occ = j
    return np.array(Rs), pd.DatetimeIndex(ts) if ts else pd.DatetimeIndex([])


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    global HYP
    HYP = sys.argv[2] if len(sys.argv) > 2 else "H1"
    A, B_ = ("donchian", "bollinger") if HYP == "H1" else ("2xATR stop", "%4 stop")
    raw = {}
    for c in COINS:
        try: raw[c] = fast_bt.load(c, source=source)
        except SystemExit: pass
    print(f"\n{'='*104}\n=== ÖLÇÜM GÜCÜ TESTİ — {len(raw)} coin × {len(TFS)} zaman dilimi ===")
    print(f"  HİPOTEZ {HYP}: {B_} > {A} ? (koltuk seçimi YOK — ölçüm, deploy değil)")

    cells = []
    all_d = []; all_b = []; all_dt = []; all_bt = []
    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400: continue
            if HYP == "H1":
                Rd, td = run(d, trig_donchian); Rb, tb = run(d, trig_bollinger)
            else:
                Rd, td = run(d, trig_donchian, "atr"); Rb, tb = run(d, trig_donchian, "pct")
            if len(Rd) < 20 or len(Rb) < 20: continue
            cells.append(dict(tf=tf, coin=c, nd=len(Rd), nb=len(Rb),
                              md=float(Rd.mean()), mb=float(Rb.mean())))
            all_d.append(Rd); all_b.append(Rb); all_dt.append(td); all_bt.append(tb)
    if not cells:
        print("  hücre yok"); return
    df = pd.DataFrame(cells)
    df["fark"] = df.mb - df.md
    D = np.concatenate(all_d); B = np.concatenate(all_b)
    DT = all_dt[0].append(all_dt[1:]) if len(all_dt) > 1 else all_dt[0]
    BT = all_bt[0].append(all_bt[1:]) if len(all_bt) > 1 else all_bt[0]

    print(f"\n  ÖRNEKLEM: {len(df)} hücre | donchian {len(D)} işlem | bollinger {len(B)} işlem")
    print(f"  (canlı config karşılaştırması 1579 işlemdi → ~{ (len(D)+len(B))//1579 }× daha büyük)")

    # ── A) İŞARET TESTİ ──
    w = int((df.fark > 0).sum()); n = len(df)
    from math import comb
    p_two = 2 * sum(comb(n, k) for k in range(w, n + 1)) / (2 ** n) if w >= n / 2 else \
            2 * sum(comb(n, k) for k in range(0, w + 1)) / (2 ** n)
    p_two = min(1.0, p_two)
    print(f"\n  --- A) İŞARET TESTİ (hücre bazında, büyüklükten bağımsız) ---")
    print(f"      {B_} {w}/{n} hücrede kazanıyor (eşdeğer olsalar beklenen {n/2:.0f})")
    print(f"      iki yönlü binom p = {p_two:.5f}  {'✓ ANLAMLI' if p_two < 0.05 else '✗ anlamsız'}")

    # ── B) HAVUZLANMIŞ ORTALAMA R ──
    se = np.sqrt(D.var(ddof=1) / len(D) + B.var(ddof=1) / len(B))
    diff = B.mean() - D.mean()
    print(f"\n  --- B) HAVUZLANMIŞ ORTALAMA R ---")
    print(f"      {A:<9s} ort {D.mean():+.4f}R (n={len(D)}, sd {D.std(ddof=1):.3f})")
    print(f"      {B_:<10s} ort {B.mean():+.4f}R (n={len(B)}, sd {B.std(ddof=1):.3f})")
    print(f"      fark {diff:+.4f}R ± {se:.4f} → z = {diff/se:+.2f}  "
          f"{'✓ ANLAMLI' if abs(diff/se) > 1.96 else '✗ anlamsız'}")

    # ── ZAMAN DİLİMİ ve DÖNEM KIRILIMI (tutarlılık) ──
    print(f"\n  --- TUTARLILIK: zaman dilimi bazında ---")
    print(f"  {'tf':>4s} {'hücre':>6s} {'bolli kazanan':>14s} {'ort fark R':>11s}")
    for tf in TFS:
        s = df[df.tf == tf]
        if not len(s): continue
        print(f"  {tf:>4s} {len(s):>6d} {int((s.fark>0).sum()):>10d}/{len(s):<3d} {s.fark.mean():>+11.4f}")

    print(f"\n  --- TUTARLILIK: dönem bazında (aynı havuz, TRAIN vs TEST) ---")
    for lbl, msk_d, msk_b in (("TRAIN", DT < TRAIN_END, BT < TRAIN_END),
                              ("TEST ", DT >= TRAIN_END, BT >= TRAIN_END)):
        dd = D[msk_d]; bb = B[msk_b]
        if len(dd) < 50 or len(bb) < 50: continue
        s2 = np.sqrt(dd.var(ddof=1)/len(dd) + bb.var(ddof=1)/len(bb))
        print(f"      {lbl}: donchian {dd.mean():+.4f}R (n={len(dd)}) | "
              f"bollinger {bb.mean():+.4f}R (n={len(bb)}) | fark {bb.mean()-dd.mean():+.4f}R "
              f"z={(bb.mean()-dd.mean())/s2:+.2f}")

    print(f"\n  --- EN İYİ/EN KÖTÜ 5 HÜCRE (aykırı bağımlılığı var mı) ---")
    t = df.sort_values("fark")
    for _, r in pd.concat([t.head(3), t.tail(3)]).iterrows():
        print(f"      {r.coin:>5s}/{r.tf:<4s} donchian {r.md:+.3f}R (n{int(r.nd)}) → "
              f"bollinger {r.mb:+.3f}R (n{int(r.nb)})  fark {r.fark:+.3f}R")

    print(f"\n  HÜKÜM: A ve B'nin İKİSİ de anlamlıysa ve zaman dilimi/dönem kırılımı TUTARLIYSA,")
    print(f"  soru artık 'bilmiyoruz' değil. Aksi halde 10× örneklemle bile ayırt edilemiyor demektir —")
    print(f"  ki bu da kesin bir cevaptır: fark YOKSA mevcut sistemi değiştirmek için sebep yok.")


if __name__ == "__main__":
    main()
