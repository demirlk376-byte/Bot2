"""
power_exit.py — ÇIKIŞ MEKANİĞİ, 21× ölçüm gücüyle (22 coin × 4 zaman dilimi = 88 hücre).

NEDEN BU: filtre/indikatör ekseni kapandı (tetikleyici bilgiyi zaten çıkarıyor, ikinci
ölçüm bedava değil — işlem siliyor). Ama ÇIKIŞ hiç bu güçle sorulmadı. Trailing'in
mekanizması kanıtlanmıştı (ortalama R +%35, maksimum R 2.5→24.6); karar verilememesinin
tek sebebi kârın %73'ünün 24 işlemde toplanmasıydı. 88 hücre bu kuyruk sorununu çözer.

TASARIM = power_test.py ile aynı: koltuk seçimi YOK (portföy inşası, çıkış kalitesi
sorusunun parçası değil), occ VAR (MEXC netted mod), EMA200 kapısı, giriş donchian-40.
Tek değişen: pozisyondan NASIL çıkıldığı. R, HER ZAMAN başlangıç riskine (2×ATR) bölünür
→ varyantlar arası doğrudan karşılaştırılabilir.

BAR-İÇİ BELİRSİZLİK: bir barda hem stop hem hedef dokunulmuşsa hangisinin önce olduğunu
bilemeyiz. HER ZAMAN STOP'U ÖNCE sayıyoruz (kötümser). Trailing'i bu kural kayırmaz —
tersine, trailing daha çok stop dokunuşu ürettiği için trailing'i CEZALANDIRIR.

İKİ METRİK — ikincisi kritik:
 A) İşlem başına ortalama R — "bu çıkış daha mı iyi?"
 B) TUTULAN BAR BAŞINA R — "7 koltuk kısıtı altında daha mı iyi?" Günlük-trend bulgusu
    tam olarak burada ölmüştü ($0.44/koltuk-günü tabana karşı $0.08). Bir varyant A'da
    kazanıp B'de kaybediyorsa canlıda PARA KAYBETTİRİR.

KABUL BARI (ön-kayıt, gevşetilemez):
 1. işaret testi p < 0.0085 (6 karşılaştırma için Šidák düzeltmesi)
 2. havuzlanmış z > 1.96 AYNI yönde
 3. TRAIN ve TEST'te AYNI işaret
 4. 4 zaman diliminin en az 3'ünde aynı işaret
 5. bar-başına R de pozitif (koltuk maliyeti)
Beşi birden sağlanmazsa HÜKÜM: fark yok. Tek tek "umut verici" diye rapor etmek yok.

Kullanım:  py power_exit.py local
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
SIDAK = 1 - (1 - 0.05) ** (1 / 6)   # 6 karşılaştırma → 0.00851


def trig_donchian(d, n=40):
    hi = d["high"].rolling(n).max().shift(1).values
    lo = d["low"].rolling(n).min().shift(1).values
    c = d["close"].values
    return c > hi, c < lo


# ────────────────────────────── ÇIKIŞ VARYANTLARI ──────────────────────────────
# Her biri (yön, giriş, stop_mesafesi, bar dizileri, başlangıç indeksi) alır ve
# (çıkış_fiyatı, çıkış_bar_indeksi) döndürür. R dışarıda hesaplanır.

def ex_fixed(d_, c, sld, hi, lo, cl, a_ser, i, n, rr=RR):
    """TABAN: sabit stop 2×ATR, sabit hedef rr×SL, maxhold."""
    slp = c - d_ * sld
    tp = c + d_ * rr * sld
    for j in range(i + 1, min(i + 1 + MH, n)):
        if d_ == 1:
            if lo[j] <= slp: return slp, j
            if hi[j] >= tp: return tp, j
        else:
            if hi[j] >= slp: return slp, j
            if lo[j] <= tp: return tp, j
    j = min(i + MH, n - 1)
    return cl[j], j


def ex_trail(d_, c, sld, hi, lo, cl, a_ser, i, n, k=3.0):
    """CHANDELIER TRAIL: sabit hedef YOK. Stop, ulaşılan en iyi seviyeden k×ATR geride.
    Başlangıç stopu taban ile AYNI (2×ATR) — yani ilk risk aynı, R karşılaştırılabilir.
    Stop asla geri çekilmez (monoton). Bar-içi: önce stop kontrol, SONRA trail güncelle
    (aynı barda hem yeni zirve hem stop olamaz varsayımı yerine kötümser sıra)."""
    slp = c - d_ * sld
    best = c
    for j in range(i + 1, min(i + 1 + MH, n)):
        if d_ == 1:
            if lo[j] <= slp: return slp, j
            best = max(best, hi[j])
            aj = a_ser[j]
            if np.isfinite(aj) and aj > 0:
                slp = max(slp, best - k * aj)
        else:
            if hi[j] >= slp: return slp, j
            best = min(best, lo[j])
            aj = a_ser[j]
            if np.isfinite(aj) and aj > 0:
                slp = min(slp, best + k * aj)
    j = min(i + MH, n - 1)
    return cl[j], j


def ex_be(d_, c, sld, hi, lo, cl, a_ser, i, n):
    """BREAKEVEN: +1R dokununca stop girişe çekilir, hedef rr×SL kalır.
    Bar-içi kötümser: stop kontrolü ÖNCE, breakeven terfisi SONRA — yani +1R'ye
    dokunulan barda stop hâlâ eski yerinde sayılır (breakeven'ı kayırmaz)."""
    slp = c - d_ * sld
    tp = c + d_ * RR * sld
    armed = False
    for j in range(i + 1, min(i + 1 + MH, n)):
        if d_ == 1:
            if lo[j] <= slp: return slp, j
            if hi[j] >= tp: return tp, j
            if not armed and hi[j] >= c + sld:
                slp = max(slp, c); armed = True
        else:
            if hi[j] >= slp: return slp, j
            if lo[j] <= tp: return tp, j
            if not armed and lo[j] <= c - sld:
                slp = min(slp, c); armed = True
    j = min(i + MH, n - 1)
    return cl[j], j


VARIANTS = {
    "taban(rr2.5)":  lambda *a: ex_fixed(*a),
    "trail 3xATR":   lambda *a: ex_trail(*a, k=3.0),
    "trail 2xATR":   lambda *a: ex_trail(*a, k=2.0),
    "trail 4xATR":   lambda *a: ex_trail(*a, k=4.0),
    "breakeven@1R":  lambda *a: ex_be(*a),
    "hedef rr1.5":   lambda *a: ex_fixed(*a, rr=1.5),
    "hedef rr3.5":   lambda *a: ex_fixed(*a, rr=3.5),
}


def run(d, exit_fn):
    """occ'lu üretim, koltuk seçimi YOK.
    Dönüş: (R dizisi, giriş zamanları, tutulan bar sayıları)."""
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    e200 = ema_fn(d["close"], 200).values
    L, S = trig_donchian(d)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    Rs = []; ts = []; bars = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ or not np.isfinite(e200[i]):
            continue
        c = cl[i]; d_ = 0
        if L[i] and c > e200[i]: d_ = 1
        elif S[i] and c < e200[i]: d_ = -1
        if d_ == 0: continue
        sld = SL_A * a
        if not np.isfinite(sld) or sld <= 0: continue
        ep, j = exit_fn(d_, c, sld, hi, lo, cl, a_ser, i, n)
        Rs.append(d_ * (ep - c) / sld - 2 * FEE * c / sld)
        ts.append(idx[i]); bars.append(j - i); occ = j
    return (np.array(Rs), pd.DatetimeIndex(ts) if ts else pd.DatetimeIndex([]),
            np.array(bars, dtype=float))


def sign_p(w, n):
    if n == 0: return 1.0
    if w >= n / 2:
        p = 2 * sum(comb(n, k) for k in range(w, n + 1)) / (2 ** n)
    else:
        p = 2 * sum(comb(n, k) for k in range(0, w + 1)) / (2 ** n)
    return min(1.0, p)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in COINS:
        try:
            raw[c] = fast_bt.load(c, source=source)
        except SystemExit:
            pass

    print(f"\n{'=' * 104}")
    print(f"=== ÇIKIŞ MEKANİĞİ — ÖLÇÜM GÜCÜ TESTİ ({len(raw)} coin × {len(TFS)} tf) ===")
    print(f"  Giriş sabit (donchian-40 + EMA200). Sadece ÇIKIŞ değişiyor.")
    print(f"  Šidák düzeltilmiş eşik: p < {SIDAK:.5f} (6 karşılaştırma)")

    names = list(VARIANTS)
    # res[name] = {"cells": {(tf,coin): (meanR, meanBar)}, "R": [...], "T": [...], "B": [...]}
    res = {nm: {"cells": {}, "R": [], "T": [], "B": []} for nm in names}

    for tf in TFS:
        for c, m in raw.items():
            d = fast_bt.resample(m, tf)
            if len(d) < 400: continue
            out = {}
            ok = True
            for nm in names:
                R, T, B = run(d, VARIANTS[nm])
                if len(R) < 20: ok = False; break
                out[nm] = (R, T, B)
            if not ok: continue
            for nm in names:
                R, T, B = out[nm]
                res[nm]["cells"][(tf, c)] = (float(R.mean()), float(B.mean()))
                res[nm]["R"].append(R); res[nm]["T"].append(T); res[nm]["B"].append(B)

    ncell = len(res[names[0]]["cells"])
    if ncell == 0:
        print("  hücre yok"); return

    P = {}
    for nm in names:
        R = np.concatenate(res[nm]["R"]); B = np.concatenate(res[nm]["B"])
        T = res[nm]["T"][0].append(res[nm]["T"][1:]) if len(res[nm]["T"]) > 1 else res[nm]["T"][0]
        P[nm] = (R, T, B)

    base = names[0]
    Rb, Tb, Bb = P[base]
    print(f"\n  ÖRNEKLEM: {ncell} hücre × {len(names)} varyant | taban {len(Rb)} işlem")
    print(f"  (canlı config karşılaştırması 1579 işlemdi → ~{len(Rb) // 1579}× daha büyük)")

    print(f"\n  --- TABAN ---")
    print(f"      {base}: ort {Rb.mean():+.4f}R  (n={len(Rb)}, sd {Rb.std(ddof=1):.3f})  "
          f"ort tutuş {Bb.mean():.1f} bar  →  {Rb.mean() / Bb.mean():+.5f} R/bar")

    print(f"\n  --- VARYANTLAR (hepsi tabana karşı) ---")
    hdr = (f"  {'varyant':<14s} {'ort R':>9s} {'fark':>8s} {'z':>6s} "
           f"{'hücre':>9s} {'p(işaret)':>10s} {'bar':>6s} {'R/bar':>9s} {'Δ R/bar':>9s}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))

    verdicts = {}
    for nm in names[1:]:
        R, T, B = P[nm]
        se = np.sqrt(R.var(ddof=1) / len(R) + Rb.var(ddof=1) / len(Rb))
        diff = R.mean() - Rb.mean()
        z = diff / se if se > 0 else 0.0
        w = sum(1 for k, (mr, _) in res[nm]["cells"].items()
                if mr > res[base]["cells"][k][0])
        p = sign_p(w, ncell)
        rpb = R.mean() / B.mean(); rpb_b = Rb.mean() / Bb.mean()
        print(f"  {nm:<14s} {R.mean():>+9.4f} {diff:>+8.4f} {z:>+6.2f} "
              f"{w:>5d}/{ncell:<3d} {p:>10.5f} {B.mean():>6.1f} {rpb:>+9.5f} "
              f"{rpb - rpb_b:>+9.5f}")
        verdicts[nm] = dict(z=z, p=p, diff=diff, rpb_d=rpb - rpb_b)

    # ── TUTARLILIK: zaman dilimi ──
    print(f"\n  --- TUTARLILIK: zaman dilimi bazında (kaç hücrede tabanı geçiyor) ---")
    print(f"  {'varyant':<14s} " + " ".join(f"{tf:>8s}" for tf in TFS))
    for nm in names[1:]:
        row = []
        agree = 0
        for tf in TFS:
            ks = [k for k in res[nm]["cells"] if k[0] == tf]
            if not ks: row.append("     -/-"); continue
            w = sum(1 for k in ks if res[nm]["cells"][k][0] > res[base]["cells"][k][0])
            row.append(f"{w:>4d}/{len(ks):<3d}")
            if (w > len(ks) / 2) == (verdicts[nm]["diff"] > 0): agree += 1
        verdicts[nm]["tf_agree"] = agree
        print(f"  {nm:<14s} " + " ".join(row) + f"   (yön uyumu {agree}/{len(TFS)})")

    # ── TUTARLILIK: dönem ──
    print(f"\n  --- TUTARLILIK: dönem bazında (TRAIN < 2025-01-01 ≤ TEST) ---")
    print(f"  {'varyant':<14s} {'TRAIN fark':>12s} {'TEST fark':>12s} {'işaret':>8s}")
    for nm in names[1:]:
        R, T, B = P[nm]
        parts = []
        for msk_v, msk_b in ((T < TRAIN_END, Tb < TRAIN_END), (T >= TRAIN_END, Tb >= TRAIN_END)):
            rv, rb = R[msk_v], Rb[msk_b]
            parts.append(rv.mean() - rb.mean() if len(rv) >= 50 and len(rb) >= 50 else np.nan)
        same = (np.isfinite(parts[0]) and np.isfinite(parts[1])
                and np.sign(parts[0]) == np.sign(parts[1]))
        verdicts[nm]["period_same"] = bool(same)
        print(f"  {nm:<14s} {parts[0]:>+12.4f} {parts[1]:>+12.4f} {'AYNI' if same else 'FARKLI':>8s}")

    # ── HÜKÜM ──
    print(f"\n  --- HÜKÜM (5 şartın HEPSİ gerekli, ön-kayıt) ---")
    winner = None
    for nm in names[1:]:
        v = verdicts[nm]
        ok = [v["p"] < SIDAK, abs(v["z"]) > 1.96, v["period_same"],
              v["tf_agree"] >= 3, v["rpb_d"] > 0 if v["diff"] > 0 else False]
        tag = "★ GEÇTİ" if all(ok) else "✗"
        why = []
        if not ok[0]: why.append(f"p={v['p']:.4f}")
        if not ok[1]: why.append(f"z={v['z']:+.2f}")
        if not ok[2]: why.append("dönem işareti farklı")
        if not ok[3]: why.append(f"tf uyumu {v['tf_agree']}/4")
        if not ok[4]: why.append(f"R/bar {v['rpb_d']:+.5f}")
        print(f"  {tag:<8s} {nm:<14s} {'— ' + ', '.join(why) if why else 'beş şart da sağlandı'}")
        if all(ok) and v["diff"] > 0:
            winner = nm
    print(f"\n  SONUÇ: {'DEPLOY ADAYI → ' + winner if winner else 'hiçbir varyant barı geçmedi — mevcut çıkış korunur.'}")


if __name__ == "__main__":
    main()
