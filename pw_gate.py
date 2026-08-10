"""
pw_gate.py — EMA200 TREND KAPISI HAK EDİYOR MU? (canlı bir bileşen, HİÇ denetlenmedi)

NEDEN ŞİMDİ — iki bulgu bu soruyu zorunlu kıldı:
 1. Bu oturumda 290 gösterge/filtre denemesi çöktü ve mekanizma anlaşıldı: filtreler işlem
    SİLEREK bedel ödetiyor, permütasyon NE silinirse silinsin silmenin negatif beklenti
    olduğunu gösterdi. Eğer bu genelse, EMA200 kapısı da ZARARLI olabilir — yani KALDIRMAK
    kazandırabilir. Bu, "bir şey EKLEMEK" yerine "ÇIKARMAK" olduğu için bugünkü tüm
    denemelerden farklı bir hipotez.
 2. xau_mech_test bugün şunu ölçtü: kırılım sonrası sürüklenme YUKARI +0.63%, AŞAĞI +0.57%
    — AYNI işaret, yani yönsüz. Momentum imzası 22 coinin yalnız 3'ünde. AMA üretim kolu
    iki yönde de kârlı (LONG +0.288R, SHORT +0.185R). Çelişkinin en olası çözümü: KAPILAR
    (EMA200 + günlük MTF) gerçek iş yapıyor ve kârlı alt kümeyi seçiyor. Bu ölçülmeli.

YÖNTEM: H1/H2'yi kapatan 88 hücreli iskelet (22 coin × 4 tf), koltuk seçimi YOK, occ VAR.
Filtre ÜRETİM SIRASINDA uygulanıyor (post-hoc DEĞİL — elenen sinyal occ'u meşgul etmez;
post-hoc filtrelemek bu depoda daha önce SAHTE iyileşme üretmişti).

VARYANTLAR: kapı yok · EMA200 (canlı) · EMA100 · EMA50 · EMA200 EĞİMİ (fiyat yerine yön)
Dört sahtelik testi: işaret · havuzlanmış z · YÖN ayrımı · DÖNEM ayrımı.

DİKKAT — KAPISIZ VERSİYON DAHA ÇOK İŞLEM ÜRETİR: bu, occ dinamiğini de değiştirir
(daha erken giren bir işlem sonrakini bloke eder). Bu YAPIsal ve doğru; karşılaştırma
"aynı işlemler + filtre" değil, "iki farklı kol" olarak okunmalı.

Kullanım:  py pw_gate.py local
"""
import sys
from math import comb

import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn, ema as ema_fn

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
TFS = ["2h", "4h", "6h", "12h"]
FEE = 0.0001
SL_A, RR, MH = 2.0, 2.5, 30
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")


def run(d, gate):
    """gate: None | ("price", n) | ("slope", n)
    ("price", n) → canlı davranış: long için kapanış > EMA_n
    ("slope", n) → EMA_n yükseliyorsa long (fiyat seviyesi yerine YÖN)"""
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    ch_hi = d["high"].rolling(40).max().shift(1).values
    ch_lo = d["low"].rolling(40).min().shift(1).values
    idx = d.index; n = len(cl)
    if gate is None:
        gv = None
    else:
        kind, per = gate
        e = ema_fn(d["close"], per).values
        gv = e if kind == "price" else np.concatenate([[np.nan], np.diff(e)])
    Rs = []; ts = []; ds = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        c = cl[i]; d_ = 0
        if np.isfinite(ch_hi[i]) and c > ch_hi[i]: d_ = 1
        elif np.isfinite(ch_lo[i]) and c < ch_lo[i]: d_ = -1
        if d_ == 0: continue
        if gv is not None:
            if not np.isfinite(gv[i]): continue
            ok = (c > gv[i]) if gate[0] == "price" else (gv[i] > 0)
            if d_ == 1 and not ok: continue
            if d_ == -1 and ok: continue
        sld = SL_A * a
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
        Rs.append(d_ * (ep - c) / sld - 2 * FEE * c / sld)
        ts.append(idx[i]); ds.append(d_); occ = j
    return (np.array(Rs), pd.DatetimeIndex(ts) if ts else pd.DatetimeIndex([]),
            np.array(ds, int))


def sign_p(w, n):
    if n == 0: return 1.0
    p = (2 * sum(comb(n, k) for k in range(w, n + 1)) / 2 ** n) if w >= n / 2 else \
        (2 * sum(comb(n, k) for k in range(0, w + 1)) / 2 ** n)
    return min(1.0, p)


VAR = {
    "EMA200 (CANLI)": ("price", 200),
    "kapı YOK":       None,
    "EMA100":         ("price", 100),
    "EMA50":          ("price", 50),
    "EMA200 EĞİMİ":   ("slope", 200),
}
BASE = "EMA200 (CANLI)"


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in COINS:
        try: raw[c] = fast_bt.load(c, source=source)
        except SystemExit: pass

    names = list(VAR)
    print(f"\n{'=' * 100}")
    print(f"=== EMA200 TREND KAPISI DENETİMİ — {len(raw)} coin × {len(TFS)} tf ===")
    print("  Hipotez: kapıyı KALDIRMAK kazandırabilir (filtreler işlem silerek zarar veriyor).")
    print("  Karşı hipotez: kapılar kârlı alt kümeyi seçiyor (xau_mech çelişkisinin çözümü).")

    cells = {nm: {} for nm in names}
    pool = {nm: {"R": [], "T": [], "D": []} for nm in names}
    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400: continue
            out = {nm: run(d, VAR[nm]) for nm in names}
            if any(len(out[nm][0]) < 20 for nm in names): continue
            for nm in names:
                R, T, D = out[nm]
                cells[nm][(tf, c)] = float(R.mean())
                pool[nm]["R"].append(R); pool[nm]["T"].append(T); pool[nm]["D"].append(D)

    ncell = len(cells[BASE])
    if ncell == 0:
        print("  hücre yok"); return
    P = {}
    for nm in names:
        Ts = pool[nm]["T"]
        P[nm] = (np.concatenate(pool[nm]["R"]),
                 Ts[0].append(Ts[1:]) if len(Ts) > 1 else Ts[0],
                 np.concatenate(pool[nm]["D"]))
    Rb, Tb, Db = P[BASE]
    print(f"\n  ÖRNEKLEM: {ncell} hücre · taban(EMA200) {len(Rb)} işlem")

    print(f"\n  {'varyant':<16s} {'işlem':>6s} {'ort R':>9s} {'fark':>8s} {'z':>6s} "
          f"{'hücre':>9s} {'p':>8s} | {'LONG R':>8s} {'SHORT R':>8s} | {'TRAIN':>8s} {'TEST':>8s}")
    print("  " + "-" * 108)
    for nm in names:
        R, T, D = P[nm]
        se = np.sqrt(R.var(ddof=1) / len(R) + Rb.var(ddof=1) / len(Rb)) if nm != BASE else 1
        diff = R.mean() - Rb.mean()
        z = diff / se if nm != BASE and se > 0 else 0.0
        w = sum(1 for k in cells[nm] if cells[nm][k] > cells[BASE][k])
        p = sign_p(w, ncell) if nm != BASE else 1.0
        lr = R[D == 1].mean() if (D == 1).any() else np.nan
        sr = R[D == -1].mean() if (D == -1).any() else np.nan
        tr = R[T < TRAIN_END].mean() if (T < TRAIN_END).any() else np.nan
        te = R[T >= TRAIN_END].mean() if (T >= TRAIN_END).any() else np.nan
        mark = "  ← CANLI" if nm == BASE else ""
        print(f"  {nm:<16s} {len(R):>6d} {R.mean():>+9.4f} {diff:>+8.4f} {z:>+6.2f} "
              f"{w:>5d}/{ncell:<3d} {p:>8.4f} | {lr:>+8.4f} {sr:>+8.4f} | "
              f"{tr:>+8.4f} {te:>+8.4f}{mark}")

    print(f"\n  --- KAPI NE KADAR ELİYOR ---")
    ng = len(P['kapı YOK'][0])
    print(f"      kapı YOK {ng} işlem → EMA200 {len(Rb)} işlem "
          f"(%{(1-len(Rb)/ng)*100:.0f} eleniyor)")

    print(f"\n  HÜKÜM: 'kapı YOK' satırının farkı POZİTİF ve z>1.96 ise kapı ZARARLI →")
    print(f"  kaldırmak kazandırır (env-only değişiklik, kod yok). NEGATİF ise kapı")
    print(f"  gerçek iş yapıyor demektir — ve xau_mech'teki çelişki böylece açıklanır.")


if __name__ == "__main__":
    main()
