"""
breadth_expand.py — Yeni coin evrenini SEPET olarak test et (seçim TRAIN'den, karar TEST'ten).

breadth_test.py teşhisi: darboğaz sinyal, koltuk değil (7 koltuk zamanın %2.7'sinde dolu,
ortalama 2.56 pozisyon). Yani genişlik gerçek bir yön. Bu araç onu KANITA bağlar.

METODOLOJİ — bu oturumda 5 sahte pozitifi öldüren disiplinin aynısı:
  1. Aday coin = data/'da olup deploy'da OLMAYAN her coin.
  2. Her aday için donchian VE squeeze koşulur; coin TEK sleeve'e atanır (MEXC netted:
     coin başına tek pozisyon). Atama TRAIN'deki (2023-24) daha iyi sleeve'e göre.
  3. SEÇİM YALNIZCA TRAIN'DEN. Sıralama train $'ına göre; TEST (2025-26) hiç görülmez.
  4. Karar PORTFÖY seviyesinde: mevcut 11 coin (taban) vs taban+sepet, koltuk seçimi
     (MAX_POSITIONS=7) dahil. Tek tek coin "her yıl pozitif" olmak ZORUNDA DEĞİL — ekleyeceğimiz
     şey sepet, dolayısıyla test edilecek şey de sepetin PORTFÖYE katkısı.
  5. KABUL BARI (üçü birden): toplam artacak + HER YIL artacak + TEST yıllarında artacak.
     Biri bile bozulursa RED. (Toplam artışı tek başına yeterli değil — bu oturumda
     -MonTue/partial-TP/XS-momentum/long-only hep toplamda kazanıp yıl-yıl testinde öldü.)
  6. Koltuk baskısı raporlanır: sepet eklenince koltuklar dolmaya başlıyor mu? Doluyorsa
     genişliğin tavanına gelinmiş demektir (sonraki sınır sermaye/marjin).

Kullanım:  py breadth_expand.py local
"""
import sys, glob, os, heapq
import numpy as np, pandas as pd
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225; CAP = 1.25; MAXPOS = 7
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
SQZ = ["XRP", "DOGE", "TRX", "XLM"]
DEPLOYED = set(DONCH + SQZ) | {"LTC"}
CFG = {"donchian": ("4h", 259, 2.0, 2.5, 30), "squeeze": ("1h", 119, 2.0, 2.5, 48)}
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
MIN_HISTORY = pd.Timestamp("2023-04-30", tz="UTC")   # her-yıl testi için 2023 kapsamı şart
BASKET_SIZES = (3, 5, 8, 12, 16, 20)


def gen(sleeve, m):
    tf, win, sl_a, rr, mh = CFG[sleeve]
    d = fast_bt.resample(m, tf)
    if len(d) < 400: return []
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
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
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i], idx[j], R, sld / e)); occ = j
    return out


def seat_run(trades, maxpos=MAXPOS):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry, exit_ts, R, slp in ev:
        while openh and openh[0][0] <= entry: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((entry, exit_ts, R, slp))
    return taken


def pnl_of(rows):
    if not rows: return np.array([]), np.array([])
    r = np.array([t[2] for t in rows]); slp = np.array([t[3] for t in rows])
    yrs = np.array([t[1].year for t in rows])
    return r * np.minimum(RISKF, CAP * slp) * BAL0, yrs


def yearly(rows):
    p, y = pnl_of(rows)
    return {int(k): float(p[y == k].sum()) for k in sorted(set(y.tolist()))} if len(p) else {}


def occupancy_full(taken, maxpos=MAXPOS):
    ev = []
    for entry, exit_ts, _, _ in taken:
        ev.append((entry, +1)); ev.append((exit_ts, -1))
    ev.sort()
    cur = 0; prev = None; dur = {}
    for ts, delta in ev:
        if prev is not None and ts > prev:
            dur[cur] = dur.get(cur, 0.0) + (ts - prev).total_seconds()
        cur += delta; prev = ts
    tot = sum(dur.values()) or 1.0
    avg = sum(k * v for k, v in dur.items()) / tot
    return dur.get(maxpos, 0.0) / tot * 100, avg


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    have = sorted({os.path.basename(p).split("_fut_1h.csv")[0]
                   for p in glob.glob("data/*_fut_1h.csv")})
    cands = [c for c in have if c not in DEPLOYED]
    print(f"\n{'='*104}\n=== GENİŞLİK: sepet testi (seçim TRAIN 2023-24, karar TEST 2025-26) ===")
    print(f"  deploy'da: {len(DEPLOYED)} coin | data/'da toplam {len(have)} | ADAY: {len(cands)}")
    if not cands:
        print(f"\n  ADAY YOK. Önce VPS'te 'python3 fetch_universe.py' çalıştırıp veriyi çek+push et.")
        return
    print(f"  adaylar: {', '.join(cands)}")

    # ── Taban: mevcut deploy ──
    base_tr = []
    for c in DONCH: base_tr += gen("donchian", fast_bt.load(c, source=source))
    for c in SQZ: base_tr += gen("squeeze", fast_bt.load(c, source=source))
    base_taken = seat_run(base_tr)
    base_y = yearly(base_taken); base_tot = sum(base_y.values())
    b_full, b_avg = occupancy_full(base_taken)
    print(f"\n  TABAN: n={len(base_taken)} ${base_tot:+.0f} | koltuk dolu %{b_full:.1f} | ort {b_avg:.2f} poz")
    print(f"    yıl-yıl: " + " ".join(f"{y}:${v:+.0f}" for y, v in base_y.items()))

    # ── VERİ BÜTÜNLÜĞÜ: kırpılmış/delikli seri sessizce yanlış sonuç üretir ──
    # Aday dosyaları farklı zamanlarda/farklı yollarla inmiş olabilir. Kapsama ve
    # boşluk oranı GÖRÜNÜR olmalı; kötü veriyi teste sokup "sonuç" diye sunmayalım.
    print(f"\n  ─── VERİ BÜTÜNLÜĞÜ (kötü kapsama = güvenilmez sonuç) ───")
    print(f"  {'coin':<7s} {'ilk bar':<12s} {'son bar':<12s} {'bar':>7s} {'beklenen':>9s} "
          f"{'kapsama':>8s}  durum")
    ref_end = None
    for c in DONCH[:1]:
        ref_end = fast_bt.load(c, source=source).index[-1]
    good = []
    for c in cands:
        try: m = fast_bt.load(c, source=source)
        except SystemExit: continue
        first, last = m.index[0], m.index[-1]
        exp = int((last - first).total_seconds() // 3600) + 1
        cover = len(m) / max(exp, 1) * 100
        stale = (ref_end - last).days if ref_end is not None else 0
        bad = []
        if first > MIN_HISTORY: bad.append(f"geçmiş kısa({first.date()})")
        if cover < 97.0: bad.append(f"delikli(%{cover:.0f})")
        if stale > 7: bad.append(f"bayat({stale}g eski)")
        status = "✓ TEMİZ" if not bad else "✗ " + ", ".join(bad)
        print(f"  {c:<7s} {str(first.date()):<12s} {str(last.date()):<12s} {len(m):>7d} "
              f"{exp:>9d} {cover:>7.1f}%  {status}")
        if not bad: good.append(c)
    dropped = [c for c in cands if c not in good]
    if dropped:
        print(f"\n  ELENEN {len(dropped)} coin (veri kalitesi): {', '.join(dropped)}")
        print(f"  → bunlar teste ALINMIYOR; kötü veriden çıkan 'kâr' gerçek değildir.")
    cands = good
    if not cands:
        print(f"\n  Temiz veriye sahip aday KALMADI — genişlik testi yapılamaz.")
        return

    # ── Adayları hazırla: her coin TEK sleeve (TRAIN'e göre) ──
    print(f"\n  ─── aday değerlendirme (sleeve ataması + sıralama TRAIN'den) ───")
    print(f"  {'coin':<7s} {'sleeve':<9s} {'n':>5s} {'TRAIN$':>8s} {'test$(gizli)':>13s}")
    scored = []
    for c in cands:
        try: m = fast_bt.load(c, source=source)
        except SystemExit: continue
        best = None
        for sl in ("donchian", "squeeze"):
            tr = gen(sl, m)
            if len(tr) < 20: continue
            trn = [t for t in tr if t[1] < TRAIN_END]
            p, _ = pnl_of(trn)
            sc = float(p.sum()) if len(p) else -1e9
            if best is None or sc > best[0]: best = (sc, sl, tr)
        if best is None: continue
        sc, sl, tr = best
        tst = [t for t in tr if t[1] >= TRAIN_END]
        pt, _ = pnl_of(tst)
        scored.append((sc, c, sl, tr))
        print(f"  {c:<7s} {sl:<9s} {len(tr):>5d} {sc:>+8.0f} {float(pt.sum()):>+13.0f}")
    scored.sort(reverse=True, key=lambda t: t[0])

    # ── Sepet testleri ──
    print(f"\n  ─── SEPET TESTİ (taban + en iyi K aday, koltuk seçimi dahil) ───")
    print(f"  {'K':>3s} {'n':>5s} {'toplam$':>9s} {'Δtoplam':>9s} {'ΔTEST':>8s} {'dolu%':>6s} "
          f"{'ort':>5s}  yıl-yıl Δ")
    winners = []
    for K in BASKET_SIZES:
        if K > len(scored): break
        sel = scored[:K]
        allt = list(base_tr)
        for _, c, sl, tr in sel: allt += tr
        tk = seat_run(allt)
        y = yearly(tk); tot = sum(y.values())
        full, avg = occupancy_full(tk)
        dy = {k: y.get(k, 0.0) - base_y.get(k, 0.0) for k in sorted(set(y) | set(base_y))}
        d_test = sum(v for k, v in dy.items() if k >= 2025)
        every = all(v > 0 for v in dy.values())
        ok = every and d_test > 0 and tot > base_tot
        flag = " ★KABUL" if ok else (" (yıl bozuldu)" if not every else " (test-)")
        print(f"  {K:>3d} {len(tk):>5d} {tot:>+9.0f} {tot-base_tot:>+9.0f} {d_test:>+8.0f} "
              f"{full:>5.1f}% {avg:>5.2f}  " + " ".join(f"{k}:{v:+.0f}" for k, v in dy.items()) + flag)
        if ok: winners.append((K, tot - base_tot, [c for _, c, _, _ in sel], sel))

    print(f"\n  ─── SONUÇ ───")
    if not winners:
        print(f"  KABUL EDİLEN SEPET YOK. Genişlik bu adaylarla da kâr getirmiyor →")
        print(f"  ya adaylar zayıf (likidite tabanını düşürmeden daha çok coin gerek),")
        print(f"  ya da 11 coin bu sleeve'lerin taşıyabileceği evreni zaten kapsıyor.")
    else:
        K, gain, coins, sel = max(winners, key=lambda w: w[1])
        print(f"  EN İYİ: K={K} sepet, +${gain:.0f} (her yıl + TEST pozitif)")
        d_ = [c for _, c, s, _ in sel if s == "donchian"]
        s_ = [c for _, c, s, _ in sel if s == "squeeze"]
        print(f"    donchian'a: {', '.join(d_) if d_ else '—'}")
        print(f"    squeeze'e : {', '.join(s_) if s_ else '—'}")
        print(f"\n  DEPLOY (env, kod değişikliği YOK):")
        print(f"    SYMBOLS'a hepsini ekle; DONCHIAN_SYMBOLS'a {','.join(d_) if d_ else '(yok)'};")
        print(f"    SQUEEZE_SYMBOLS'a {','.join(s_) if s_ else '(yok)'}")
        print(f"  UYARI: koltuk doluluğu %{occupancy_full(seat_run(base_tr + [t for _,_,_,tr in sel for t in tr]))[0]:.1f}'e çıkıyor;")
        print(f"    %15'i aşarsa sonraki sınır MAX_POSITIONS ve o da marjin/sermaye demek.")


if __name__ == "__main__":
    main()
