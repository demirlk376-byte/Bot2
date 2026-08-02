"""
sizing_clean_test.py — Boyutlandırmanın KİRLETİLMEMİŞ testi: TÜM parametreler TRAIN'den.

NEDEN GEREKLİ (önceki denemenin dürüst teşhisi):
indicator_sizing_test + hurst_sizing_verify'da "Hurst50 tier k=0.6 → ΔTEST +$150" çıktı.
O rakam KİRLİ, çünkü seçim zinciri TEST bilgisiyle bulaşmış:
  1. HURST, önceki bir ajanın POST-HOC analizinde TEST rho +0.185 bulduğu için seçildi.
  2. N=50 penceresi o post-hoc bulgudan MİRAS alındı (TRAIN'den türetilmedi).
  3. k=0.6/tier, benim 30-kombinasyonluk taramamda EN BÜYÜK ΔTEST'i verdiği için öne çıktı.
Yani manşet rakam üç ayrı noktada TEST'e bakılarak seçildi = örneklem dışı DEĞİL.

Pencere sağlamlığı bunu zaten ele verdi: ΔTEST N30:+16 N50:+150 N80:+80 N100:−11 (plato YOK),
ve TRAIN'in en iyisi (N=80) TEST'in en iyisi (N=50) DEĞİL. Dürüst seçim N=80 derdi.

BU SCRIPT: gösterge × pencere × mod × k ızgarasının TAMAMINI kurar, argmax'ı YALNIZ TRAIN
toplamına göre seçer, sonra TEST'i BİR KEZ açar. Seçimden sonra TRAIN'e dönüş YOK.
Verimlilik: tüm gösterge/pencere değerleri sinyal başına TEK GEÇİŞTE hesaplanır.

KABUL BARI (güncellendi — eski bar büyüklük körüydü, $4'lük gürültüyü kabul etmişti):
  (a) TRAIN'de argmax  (b) ΔTEST > 0  (c) HER YIL > 0
  (d) BÜYÜKLÜK: ΔTEST tabanın en az %2'si (~$13) — ekonomik anlamlılık
  (e) DOZ-TEPKİ: aynı gösterge/pencerede k arttıkça ΔTEST monoton artmalı
  (f) permütasyon p < 0.05, ızgara boyutuna göre Šidák düzeltilmiş

Kullanım:  py sizing_clean_test.py local
"""
import sys, heapq, itertools
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
import indicator_sizing_test as IST
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy

RNG = np.random.default_rng(4242)
MIN_HIST = 50
WINDOWS = (20, 30, 50, 80, 100)
KS = (0.2, 0.4, 0.6)
MODES = ("lin", "tier")


def gen_all(m):
    """Donchian sinyalleri + HER gösterge/pencere değeri TEK geçişte."""
    tf, win, sl_a, rr, mh = DB.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    vol = d["volume"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * DB.FEE * e / sld
        cw = cl[:i + 1]
        vals = {}
        for N in WINDOWS:
            vals[f"hurst{N}"] = float(IST.hurst_rs(cw, N))
            vals[f"er{N}"] = float(IST.eff_ratio(cw, N))
            vals[f"vhf{N}"] = float(IST.vhf(cw, N))
        vals["volrat"] = float(vol[i] / max(vol[max(0, i - 20):i].mean(), 1e-9))
        vals["adx"] = float(adx_ser[i]) if np.isfinite(adx_ser[i]) else 20.0
        out.append((idx[i].value, idx[j], R, sld / e, "donchian", vals)); occ = j
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    trades = []
    for c in DB.DONCH: trades += gen_all(fast_bt.load(c, source=source))
    trades += IST.other_sleeves(source)
    taken = IST.seat_select(trades)
    n = len(taken)
    base = IST.evaluate(taken, np.ones(n))
    keys = [k for k in taken[0][5]] if taken[0][5] else []
    for t in taken:
        if t[5]: keys = list(t[5]); break
    grid = [(ind, mode, k) for ind in keys for mode in MODES for k in KS]
    print(f"\n{'='*104}\n=== BOYUTLANDIRMA — KİRLETİLMEMİŞ TEST (tüm parametreler TRAIN'den) ===")
    print(f"  TABAN: TRAIN ${base['train']:+.0f} | TEST ${base['test']:+.0f} | toplam ${base['tot']:+.0f}")
    print(f"  ızgara: {len(keys)} gösterge × {len(MODES)} mod × {len(KS)} k = {len(grid)} kombinasyon")
    print(f"  SEÇİM YALNIZ TRAIN'DEN. TEST bir kez, en sonda açılacak.\n")

    res = []
    for ind, mode, k in grid:
        m = IST.multipliers(taken, ind, k, mode)
        g = IST.budget_neutral_g(taken, m, base["avg_risk"])
        if g is None: continue
        s = IST.evaluate(taken, m, g)
        res.append(dict(ind=ind, mode=mode, k=k, g=g, s=s, m=m,
                        dtr=s["train"] - base["train"], dte=s["test"] - base["test"]))

    res.sort(key=lambda r: -r["dtr"])
    print(f"  --- TRAIN sıralaması (ilk 8) — SEÇİM BURADAN ---")
    print(f"  {'gösterge':>9s} {'mod':>5s} {'k':>4s} {'ΔTRAIN':>8s}")
    for r in res[:8]:
        print(f"  {r['ind']:>9s} {r['mode']:>5s} {r['k']:>4.1f} {r['dtr']:>+8.0f}")

    win = res[0]
    print(f"\n  ★ TRAIN ARGMAX: {win['ind']} / {win['mode']} / k={win['k']}  (ΔTRAIN ${win['dtr']:+.0f})")
    print(f"  >>> TEST ŞİMDİ AÇILIYOR (tek sefer, geri dönüş yok) <<<")
    s = win["s"]
    dy = {y: s["yrs"].get(y, 0) - base["yrs"].get(y, 0) for y in base["yrs"]}
    print(f"      ΔTEST ${win['dte']:+.0f}  |  yıl-yıl " + " ".join(f"{y}:{v:+.0f}" for y, v in dy.items()))

    # kabul bari
    ok_test = win["dte"] > 0
    ok_year = all(v > 0 for v in dy.values())
    ok_mag = win["dte"] > 0.02 * base["test"]
    same = [r for r in res if r["ind"] == win["ind"] and r["mode"] == win["mode"]]
    same.sort(key=lambda r: r["k"])
    dose = [r["dte"] for r in same]
    ok_dose = all(dose[i] <= dose[i + 1] for i in range(len(dose) - 1))
    print(f"\n  --- KABUL BARI ---")
    print(f"    (b) ΔTEST>0            : {'✓' if ok_test else '✗'}  (${win['dte']:+.0f})")
    print(f"    (c) HER YIL>0          : {'✓' if ok_year else '✗'}")
    print(f"    (d) BÜYÜKLÜK >%2 taban : {'✓' if ok_mag else '✗'}  (eşik ${0.02*base['test']:.0f})")
    print(f"    (e) DOZ-TEPKİ monoton  : {'✓' if ok_dose else '✗'}  (k arttıkça ΔTEST: "
          + " → ".join(f"{d:+.0f}" for d in dose) + ")")

    if not (ok_test and ok_year and ok_mag and ok_dose):
        print(f"\n  SONUÇ: RED — permütasyona gerek yok, temel şartlar sağlanmıyor.")
    else:
        print(f"\n  (f) PERMÜTASYON (2000 tur)...")
        donch = np.array([t[4] == "donchian" for t in taken])
        obs = win["dte"]; sims = []
        for _ in range(2000):
            mm = np.ones(n); mm[donch] = RNG.permutation(win["m"][donch])
            gg = IST.budget_neutral_g(taken, mm, base["avg_risk"])
            if gg is None: continue
            sims.append(IST.evaluate(taken, mm, gg)["test"] - base["test"])
        sims = np.array(sims)
        p = ((sims >= obs).sum() + 1) / (len(sims) + 1)
        psid = 1 - (1 - p) ** len(grid)
        print(f"      ham p={p:.4f} | Šidák({len(grid)}) p={psid:.4f}  "
              f"{'✓ GEÇTİ' if psid < 0.05 else '✗ DÜZELTME SONRASI ÖLÜ'}")
        print(f"\n  SONUÇ: {'★ KABUL' if psid < 0.05 else 'RED'}")

    # seffaflik: en iyi TEST ne olurdu (SECIMDE KULLANILMADI)
    best_te = max(res, key=lambda r: r["dte"])
    print(f"\n  [şeffaflık] TEST'in en iyisi {best_te['ind']}/{best_te['mode']}/k={best_te['k']} "
          f"ΔTEST ${best_te['dte']:+.0f} — TRAIN sırası {res.index(best_te)+1}/{len(res)}.")
    print(f"  TRAIN sıralaması TEST'i öngörüyorsa bu sıra küçük olmalı; büyükse seçim bilgi taşımıyor.")


if __name__ == "__main__":
    main()
