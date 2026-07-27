"""
portfolio_sim.py — Donchian ALT-PORTFÖYÜ koltuk-kısıtıyla simüle et (canlı-doğru).

coin_expand her coini İZOLE test etti (kendi occ slotu). Canlıda tüm donchian coinleri
ORTAK MAX_POSITIONS koltuklarını paylaşır → yeni coin eklemek koltuk için REKABET yaratır.
Bu araç gerçek soruyu yanıtlar: koltuk-kısıtı altında yeni coin portföye NE KATAR?

Yöntem:
  1) Her coin için donchian(rr2.5+MTF) işlemleri üret: (giriş_ts, çıkış_ts, R, yıl).
  2) Portföy sim: tüm işlemleri giriş zamanına göre sırala; bir işlem yalnızca o an
     BOŞ koltuk varsa açılır (koltuk çıkış_ts'de boşalır) — canlı seat mantığı.
  3) Metrikler: total $, PF, maxDD ($ equity eğrisinden), yıl-yıl, max-eşzamanlı poz.
  Karşılaştır: baseline(mevcut 5) vs +ICP+BNB vs +hepsi, MAX_POSITIONS ∈ {2,3,4,5,8}.

Koltuk düşükse (2-3) ve max-eşzamanlı ona değmiyorsa → kısıt bağlamıyor, izole ≈ portföy.

Kullanım:  py portfolio_sim.py local
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
TF, WIN, SL_A, RR, MH = "4h", 259, 2.0, 2.5, 30
CURRENT = ["SOL", "ETH", "ADA", "NEAR", "BCH"]
ADD_CORE = ["ICP", "BNB"]
ADD_ALL = ["ICP", "BNB", "DOT", "AVAX", "VET"]


def gen(coin, m):
    """Donchian(rr2.5+MTF) işlemleri: (entry_ts, exit_ts, R, year)."""
    d = fast_bt.resample(m, TF)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    # CANLI-BİREBİR MTF (lookahead YOK): canlı d1d=df_4h.resample("1D").close.last() +
    # ewm20 dahil-bugün; cebirsel olarak == kapanış > DÜNE kadar tamamlanmış EMA20.
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - WIN):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = SL_A * a; slp = e - d_ * sld; tp = e + d_ * RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i], idx[j], R, idx[i].year)); occ = j
    return out


def portfolio(all_tr, max_pos):
    """Giriş sırasına göre koltuk-kısıtlı seçim. Dönüş: alınan işlemler (exit_ts,R,year)."""
    ev = sorted(all_tr, key=lambda t: t[0])   # entry_ts
    open_exits = []   # açık pozisyonların çıkış zamanları
    taken = []
    for entry_ts, exit_ts, R, yr in ev:
        open_exits = [x for x in open_exits if x > entry_ts]   # boşalan koltuklar
        if len(open_exits) < max_pos:
            open_exits.append(exit_ts)
            taken.append((exit_ts, R, yr))
    # max eşzamanlı (sweep-line)
    pts = sorted([(t[0], +1) for t in [(e, s) for e, s, _, _ in ev]])  # placeholder
    return taken


def max_concurrent(taken_entryexit):
    evs = []
    for entry_ts, exit_ts in taken_entryexit:
        evs.append((entry_ts, +1)); evs.append((exit_ts, -1))
    evs.sort(key=lambda x: (x[0], x[1]))   # çıkış(-1) girişten(+1) önce eşit ts'de
    cur = mx = 0
    for _, dv in evs:
        cur += dv; mx = max(mx, cur)
    return mx


def metrics(taken):
    if not taken: return "yok"
    taken = sorted(taken, key=lambda t: t[0])   # exit_ts sırası (realized equity)
    r = np.array([t[1] for t in taken])
    dollars = r * BAL * RISK
    eq = np.cumsum(dollars); peak = np.maximum.accumulate(eq)
    mdd = (peak - eq).max()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    years = sorted(set(t[2] for t in taken))
    yv = " ".join(f"{y}:${sum(t[1] for t in taken if t[2]==y)*BAL*RISK:+.0f}" for y in years)
    return (f"n={len(r):>4d} PF{pf:4.2f} ${eq[-1]:+8.2f}  maxDD${mdd:6.1f} "
            f"({mdd/BAL*100:4.1f}% hesap)  [{yv}]")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    allcoins = sorted(set(CURRENT + ADD_ALL))
    trades = {}
    for c in allcoins:
        try: trades[c] = gen(c, fast_bt.load(c, source=source))
        except Exception as e: print(f"  {c}: {e}"); trades[c] = []
    sets = {
        "baseline(5)":   CURRENT,
        "+ICP+BNB(7)":   CURRENT + ADD_CORE,
        "+hepsi(10)":    CURRENT + ADD_ALL,
    }
    for mp in (2, 3, 4, 5, 8):
        print(f"\n{'='*78}\n=== MAX_POSITIONS = {mp} (donchian alt-portföyü) ===")
        for name, coins in sets.items():
            pool = [t for c in coins for t in trades[c]]
            # koltuk-kısıtlı seçim + entry/exit sakla (max-eşzamanlı için)
            ev = sorted(pool, key=lambda t: t[0]); open_exits = []; taken = []; taken_ee = []
            for entry_ts, exit_ts, R, yr in ev:
                open_exits = [x for x in open_exits if x > entry_ts]
                if len(open_exits) < mp:
                    open_exits.append(exit_ts); taken.append((exit_ts, R, yr)); taken_ee.append((entry_ts, exit_ts))
            mc = max_concurrent(taken_ee)
            print(f"  {name:14s} maxEş={mc}: {metrics(taken)}")
    print("\n  maxEş < MAX_POS ise kısıt BAĞLAMIYOR (izole≈portföy). Ekleme total$ ve maxDD'yi")
    print("  nasıl değiştiriyor? total artıp maxDD% kabul edilebilirse ekleme değer.")


if __name__ == "__main__":
    main()
