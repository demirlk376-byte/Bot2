"""
wknd_bb_phase2.py — FAZ 2: "Hafta-sonu BB kolunun coin genislemesi" TAM URETIM TESTI

ADAY (Faz-1'den): canlida BB_WEEKDAY_ENABLED=false + BB_SYMBOLS=LTC olarak calisan
hafta-sonu mean-reversion kolunu 11 deploy coinine acmak.

CANLI TABAN (RESEARCH_LEDGER "CANLI DURUM", satir 913):
  donchian 7 (SOL,ETH,ADA,NEAR,BCH,ICP,BNB) + squeeze 4 (XRP,DOGE,TRX,XLM) + BB(LTC hafta sonu)
  MAX_POSITIONS=7 (execution.py:349-353 -> TUM sleeve'ler AYNI koltuk havuzunu paylasir)
  RISK_SCALE=1.125 => %2.25/islem, POSITION_CAP_FRACTION=1.25

METODOLOJI (zorunlu maddelerin hepsi):
  1. fast_bt.load(coin,"local") + fast_bt.resample
  2. deployed_backtest config'i aynen (DONCH/SQZ/CFG/BAL0/FEE/RISKF/CAP/MAXPOS)
  3. occ=j her sleeve+coin icin (bir coin ayni anda TEK pozisyon)
  4. LOOKAHEAD YOK — tum gostergeler i barinin kapanisinda bilinen 120-barlik pencereden
     (breakout MTF'i DB.gen icinde canli-birebir .shift(1) formunda)
  5. eff=min(RISKF, CAP*sl_pct); pnl=R*eff*BAL0
  6. koltuk secimi giris zamanina gore, MAXPOS=7
  7. filtre SINYAL ANINDA; elenen sinyal occ'u ILERLETMEZ

Kullanim:
  python wknd_bb_phase2.py            # tam kosu
  python wknd_bb_phase2.py --quick    # sadece bolum 0-3 (dogrulama + taban + aday)
"""
from __future__ import annotations

import dataclasses
import heapq
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, adx as adx_fn, bollinger_bands

BAL0 = DB.BAL0      # 190.0
FEE = DB.FEE        # 0.0001
RISKF = DB.RISKF    # 0.0225
CAP = DB.CAP        # 1.25
MAXPOS = DB.MAXPOS  # 7

DONCH = DB.DONCH
SQZ = DB.SQZ
COINS = DONCH + SQZ          # 11 deploy coini
LIVE_BB = ["LTC"]            # canlida acik olan tek BB coini

SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"

# canli BB kolu parametreleri (.env.example: SL 3xATR, RR_RATIO=1.667, MAX_HOLD_CANDLES=48,
# SNIPER_MIN_GRADE=2, BB_PERIOD=20/BB_STD=2.0 varsayilan, regime trending ADX>=28 blok)
DEF = dict(bbp=20, bbs=2.0, volf=True, sniper=2, adxmax=28.0,
           sl=3.0, rr=1.667, mh=48, days=(5, 6))


# ════════════════════════════════════════════════════════════════════════════
# veri + onbellekler
# ════════════════════════════════════════════════════════════════════════════
_RAW, _RES, _WIN, _ANA, _CAND, _STR = {}, {}, {}, {}, {}, {}
_INDCACHE = os.path.join(SCR, "p2_ind.pkl")


def load_ind():
    """Pencere-yerel ATR/ADX + URETIM analyze sonuclarini diske kalici onbellek.
    Sadece HIZ icindir — deger uretmez, sadece tekrar hesaplamayi onler."""
    global _WIN, _ANA
    if os.path.exists(_INDCACHE):
        with open(_INDCACHE, "rb") as f:
            _WIN, _ANA = pickle.load(f)
        print(f"  [onbellek] win={sum(len(v) for v in _WIN.values())} "
              f"analyze={sum(len(v) for v in _ANA.values())}", flush=True)


def save_ind():
    with open(_INDCACHE, "wb") as f:
        pickle.dump((_WIN, _ANA), f)


def raw(c):
    if c not in _RAW:
        _RAW[c] = fast_bt.load(c, source="local")
    return _RAW[c]


def res(c):
    if c not in _RES:
        _RES[c] = fast_bt.resample(raw(c), "1h")
    return _RES[c]


def strat(bbp, bbs, volf):
    """URETIM sinifi. sniper_min_grade=0 -> yon + grade AYRI alinir; bu, sinifin
    kendi 'grade < min -> direction 0' mantiginin BIREBIR ayrisimidir (bkz. bolum 0)."""
    k = (bbp, bbs, volf)
    if k not in _STR:
        from config import load_config
        from strategies.mean_reversion import MeanReversionStrategy
        cfg = dataclasses.replace(load_config().strategy,
                                  bb_period=bbp, bb_std=bbs,
                                  vol_filter_enabled=volf, sniper_min_grade=0)
        _STR[k] = MeanReversionStrategy(cfg)
    return _STR[k]


def cand_bars(c, bbp, bbs, volf):
    """Ucuz on-eleme. BB rolling(bbp) 120-barlik pencerede tam-seri ile BAYT-DENK
    (pencere >= bbp). Hacim filtresi de rolling(20) -> ayni gerekce."""
    k = (c, bbp, bbs, volf)
    if k not in _CAND:
        d = res(c)
        up_b, _m, lo_b = bollinger_bands(d["close"], bbp, bbs)
        cl = d["close"].values
        out = (cl < lo_b.values) | (cl > up_b.values)
        if volf:
            vma = d["volume"].rolling(20).mean().values
            out &= ~(np.isfinite(vma) & (d["volume"].values < vma))
        _CAND[k] = np.where(out)[0]
    return _CAND[k]


def win_ind(c, i):
    """Pencere-yerel ATR/ADX (canli get_candles(120)). Parametreden BAGIMSIZ -> global cache."""
    w = _WIN.setdefault(c, {})
    if i not in w:
        d = res(c)
        sub = d.iloc[max(0, i - 119):i + 1]
        a = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        x = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        w[i] = (float(a) if np.isfinite(a) else np.nan,
                float(x) if np.isfinite(x) else 20.0)
    return w[i]


def analyze(c, i, bbp, bbs, volf):
    """URETIM MeanReversionStrategy.analyze + _sniper_grade. (dir, grade)."""
    k = (c, bbp, bbs, volf)
    a = _ANA.setdefault(k, {})
    if i not in a:
        s = strat(bbp, bbs, volf)
        sub = res(c).iloc[max(0, i - 119):i + 1]
        sg = s.analyze(sub)
        if sg.direction == 0:
            a[i] = (0, -1)
        else:
            g, _ = s._sniper_grade(sub, sg.bb_pos, sg.direction)
            a[i] = (sg.direction, g)
    return a[i]


# ════════════════════════════════════════════════════════════════════════════
# BB kolu uretici (parametrik, canli-birebir)
# ════════════════════════════════════════════════════════════════════════════
def gen_bb(c, p):
    d = res(c)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    days = set(p["days"])
    out = []; occ = -1
    for i in cand_bars(c, p["bbp"], p["bbs"], p["volf"]):
        i = int(i)
        if i < 260 or i >= n - 1:
            continue
        if i <= occ:                      # coin basina TEK pozisyon
            continue
        ts = idx[i]
        if ts.weekday() not in days:      # gun kapisi SINYAL ANINDA, occ ilerlemez
            continue
        av, adxv = win_ind(c, i)
        if not np.isfinite(av) or av <= 0:
            continue
        if adxv >= p["adxmax"]:           # bb_allowed: trending blok (canli live_gates)
            continue
        d_, g = analyze(c, i, p["bbp"], p["bbs"], p["volf"])
        if d_ == 0 or g < p["sniper"]:
            continue
        sld = p["sl"] * av
        e = cl[i]; slp = e - d_ * sld; tp = e + d_ * p["rr"] * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + p["mh"], n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + p["mh"], n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, idx[i], idx[j], R, sld / e))
        occ = j                           # ZORUNLU
    return out


_BBCACHE = {}


def bb_sleeve(coins, p):
    key = (tuple(coins), tuple(sorted(p.items())))
    if key not in _BBCACHE:
        t = []
        for c in coins:
            t += gen_bb(c, p)
        _BBCACHE[key] = t
    return _BBCACHE[key]


def P(**kw):
    q = dict(DEF); q.update(kw); return q


# ════════════════════════════════════════════════════════════════════════════
# breakout tabani (deployed_backtest.gen aynen)
# ════════════════════════════════════════════════════════════════════════════
_BOCACHE = os.path.join(SCR, "p2_breakout.pkl")


def breakout_by_coin():
    """{coin: [(entry_ns, entry_ts, exit_ts, R, slp)]} — deployed_backtest.gen aynen."""
    if os.path.exists(_BOCACHE):
        with open(_BOCACHE, "rb") as f:
            return pickle.load(f)
    t = {}
    for c, sl in [(x, "donchian") for x in DONCH] + [(x, "squeeze") for x in SQZ]:
        t[c] = [(ns, pd.Timestamp(ns, tz="UTC"), ex, R, sp) for ns, ex, R, sp in DB.gen(sl, raw(c))]
    with open(_BOCACHE, "wb") as f:
        pickle.dump(t, f)
    return t


def breakout():
    bc = breakout_by_coin()
    return [x for c in COINS for x in bc[c]]


# ════════════════════════════════════════════════════════════════════════════
# koltuk + metrik
# ════════════════════════════════════════════════════════════════════════════
def seat_select(trades, maxpos=MAXPOS):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for entry_ns, entry_ts, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns:
            heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((entry_ts, exit_ts, R, slp))
    return sorted(taken, key=lambda t: t[1])


def frame(taken):
    if not taken:
        return pd.DataFrame(columns=["entry", "exit", "R", "slp", "pnl", "mx", "yx"])
    df = pd.DataFrame(taken, columns=["entry", "exit", "R", "slp"])
    eff = np.minimum(RISKF, CAP * df["slp"].values)
    df["pnl"] = df["R"].values * eff * BAL0
    df["mx"] = [t.tz_localize(None).to_period("M") for t in df["exit"]]
    df["yx"] = [t.year for t in df["exit"]]
    return df


def port(trades, maxpos=MAXPOS):
    return frame(seat_select(trades, maxpos))


def mdd(df):
    if not len(df):
        return 0.0
    eq = BAL0 + np.cumsum(df["pnl"].values)
    eq = np.concatenate([[BAL0], eq])
    peak = np.maximum.accumulate(eq)
    return float(((peak - eq) / peak).max() * 100)


def desc(df, lbl):
    if not len(df):
        print(f"  {lbl:34s} islem yok"); return
    r = df["R"].values
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 99.0
    mon = df.groupby("mx")["pnl"].sum()
    print(f"  {lbl:34s} n={len(r):>4d} WR{(r>0).mean()*100:>3.0f}% PF{pf:5.2f} "
          f"${df['pnl'].sum():+8.2f}  maxDD{mdd(df):5.1f}%  enkotuAy${mon.min():+7.2f}")


def yrs(df):
    return df.groupby("yx")["pnl"].sum() if len(df) else pd.Series(dtype=float)


ALLY = [2023, 2024, 2025, 2026]


def delta_line(base, comb):
    yb, yc = yrs(base), yrs(comb)
    d = {y: yc.get(y, 0.0) - yb.get(y, 0.0) for y in ALLY}
    tot = comb["pnl"].sum() - base["pnl"].sum()
    ok = tot > 0 and all(v > 0 for v in d.values())
    return tot, d, ok


def show_delta(tag, base, comb, indent="  "):
    tot, d, ok = delta_line(base, comb)
    s = " ".join(f"{y}:{d[y]:+7.2f}" for y in ALLY)
    print(f"{indent}{tag:38s} d=${tot:+8.2f}  {s}  {'GECTI' if ok else 'KALDI'}")
    return tot, d, ok


# ════════════════════════════════════════════════════════════════════════════
def sec0_verify(bo, bb11):
    print("=" * 100)
    print("[0] METODOLOJI DOGRULAMA — Faz-1 sayilari bu motorda birebir cikiyor mu?")
    print("=" * 100)
    base = port(bo)
    print(f"  breakout tabani : n={len(base)}  ${base['pnl'].sum():+.2f}   (Faz-1: n=1421, $+1285.55)")
    yb = yrs(base)
    print(f"    yil-yil: " + "  ".join(f"{y}:{yb.get(y,0):+.2f}" for y in ALLY)
          + "   (Faz-1: +307/+403/+398/+178)")
    s = port(bb11)
    print(f"  hafta-sonu BB 11 coin (tek basina): n={len(s)}  ${s['pnl'].sum():+.2f}"
          f"   (Faz-1: n=1541, $+275.30)")
    comb = port(bo + bb11)
    t, d, ok = delta_line(base, comb)
    print(f"  birlesik delta  : ${t:+.2f}   (Faz-1: $+244.80)")
    print(f"    yil-yil delta : " + "  ".join(f"{y}:{d[y]:+.2f}" for y in ALLY)
          + "   (Faz-1: -27.66/+99.51/+122.53/+50.41)")
    # sniper ayrisimi ispati: sinifin kendi min_grade'i ile ayni mi
    from config import load_config
    from strategies.mean_reversion import MeanReversionStrategy
    cfg2 = dataclasses.replace(load_config().strategy, sniper_min_grade=2)
    s2 = MeanReversionStrategy(cfg2)
    d0 = res("SOL"); nchk = 0; bad = 0
    for i in cand_bars("SOL", 20, 2.0, True):
        i = int(i)
        if i < 260 or i >= len(d0) - 1 or d0.index[i].weekday() < 5:
            continue
        sub = d0.iloc[i - 119:i + 1]
        dir_prod = s2.analyze(sub).direction
        dd, g = analyze("SOL", i, 20, 2.0, True)
        dir_ours = dd if g >= 2 else 0
        nchk += 1
        bad += int(dir_prod != dir_ours)
    print(f"  sniper ayrisim ispati (SOL hafta-sonu aday bar): {nchk} bar, uyusmazlik={bad} "
          f"-> {'BIREBIR' if bad == 0 else 'HATA'}")
    return base


# ════════════════════════════════════════════════════════════════════════════
def main():
    t0 = time.time()
    want = {a for a in sys.argv[1:] if not a.startswith("-")} or {"0", "1", "2", "3", "4", "5", "6"}
    quick = "--quick" in sys.argv
    if quick:
        want = {"0", "1", "2"}
    print("#" * 100)
    print(f"# FAZ 2 — HAFTA-SONU BB COIN GENISLEMESI: TAM URETIM TESTI  [bolum {sorted(want)}]")
    print("#" * 100)
    load_ind()

    bo = breakout()
    bb11 = bb_sleeve(COINS, P())
    bbltc = bb_sleeve(LIVE_BB, P())

    base_bo = sec0_verify(bo, bb11) if "0" in want else port(bo)
    save_ind()

    # ── [1] GERCEK TABAN: canlida BB LTC hafta sonu ZATEN acik ────────────────
    print("\n" + "=" * 100)
    print("[1] TABANLAR — 'coin genislemesi' adayinin DURUST tabani BB(LTC) DAHIL olandir")
    print("=" * 100)
    base_live = port(bo + bbltc)
    desc(base_bo, "T0 breakout SADECE")
    desc(base_live, "T1 breakout + BB(LTC) = CANLI")
    desc(port(bbltc), "   BB(LTC) tek basina")
    print(f"  T0 yil-yil: " + "  ".join(f"{y}:{yrs(base_bo).get(y,0):+8.2f}" for y in ALLY))
    print(f"  T1 yil-yil: " + "  ".join(f"{y}:{yrs(base_live).get(y,0):+8.2f}" for y in ALLY))
    show_delta("LTC->hicbir sey (T0 vs T1)", base_bo, base_live)

    # ── [2] ADAY, varsayilan parametre ────────────────────────────────────────
    print("\n" + "=" * 100)
    print("[2] ADAY (varsayilan canli parametreler) — YAN YANA, AYNI MOTOR")
    print("=" * 100)
    cand11 = port(bo + bb11)
    cand12 = port(bo + bb11 + bbltc)
    desc(base_bo, "T0 breakout")
    desc(base_live, "T1 CANLI (breakout+BB LTC)")
    desc(cand11, "A1 breakout + BB 11 coin")
    desc(cand12, "A2 breakout + BB 11 coin + LTC (12)")
    print()
    show_delta("A1 vs T0 (Faz-1 karsilastirmasi)", base_bo, cand11)
    show_delta("A1 vs T1 (GERCEK: LTC yerine 11)", base_live, cand11)
    show_delta("A2 vs T1 (GERCEK: 11 EKLE, LTC kal)", base_live, cand12)
    comb = cand11        # ADAY portfoyu (bolum 5-6 bunu kullanir)

    # ── [3] PARAMETRE TARAMASI ────────────────────────────────────────────────
    if "3" in want:
      print("\n" + "=" * 100)
      print("[3] PARAMETRE TARAMASI — tek sansli nokta mi, BANT mi?")
      print("    her satir: BB 11 coin, o parametreyle; delta = CANLI taban T1'e gore")
      print("    (varsayilan satir *** ile isaretli)")
      print("=" * 100)
      sweeps = [
          ("BB std", "bbs", [1.6, 1.8, 2.0, 2.2, 2.5, 3.0]),
          ("BB period", "bbp", [10, 14, 20, 26, 30]),
          ("SL xATR", "sl", [2.0, 2.5, 3.0, 3.5, 4.0]),
          ("RR", "rr", [1.0, 1.333, 1.667, 2.0, 2.5]),
          ("max-hold", "mh", [12, 24, 48, 72, 96]),
          ("ADX kapi", "adxmax", [22.0, 24.0, 26.0, 28.0, 30.0, 35.0, 1e9]),
          ("sniper grade", "sniper", [0, 1, 2, 3]),
          ("vol filtresi", "volf", [True, False]),
          ("gun kumesi", "days", [(5, 6), (5,), (6,), (4, 5, 6), (0, 1, 2, 3, 4),
                                  (0, 1, 2, 3, 4, 5, 6)]),
      ]
      results = []
      print(f"    {'varyant':22s} {'dT1':>9s} {'dT0':>9s}  {'yil-yil delta (T1 tabanina gore)':46s} "
            f"{'DD%':>6s} {'kotuAy':>8s}")
      only = [a.split("=",1)[1].split(",") for a in sys.argv if a.startswith("--dims=")]
      if only: sweeps = [x for x in sweeps if x[1] in only[0]]
      for nm, key, vals in sweeps:
          print(f"  --- {nm} ---", flush=True)
          for v in vals:
              p = P(**{key: v})
              cmb = port(bo + bb_sleeve(COINS, p))
              tot, d, ok = delta_line(base_live, cmb)
              tot0, d0, ok0 = delta_line(base_bo, cmb)
              mon = cmb.groupby("mx")["pnl"].sum()
              star = "*" if v == DEF[key] else " "
              print(f"   {star}{key + '=' + str(v):22s} {tot:>+9.2f} {tot0:>+9.2f}  "
                    + " ".join(f"{y%100}:{d[y]:+7.2f}" for y in ALLY)
                    + f"  {'GECTI' if ok else 'KALDI'} {mdd(cmb):>5.1f} {mon.min():>+8.2f}", flush=True)
              results.append((nm, key, v, tot, d, ok, tot0, ok0))
          save_ind()
      npos = sum(1 for r in results if r[3] > 0)
      npass = sum(1 for r in results if r[5])
      npos0 = sum(1 for r in results if r[6] > 0)
      npass0 = sum(1 for r in results if r[7])
      print(f"\n  TARAMA OZETI ({len(results)} varyant)")
      print(f"    GERCEK taban T1 (canli, BB-LTC dahil): toplam-pozitif {npos} ({npos/len(results)*100:.0f}%)"
            f" | HER-YIL-pozitif {npass} ({npass/len(results)*100:.0f}%)")
      print(f"    Faz-1 tabani T0 (breakout salt)      : toplam-pozitif {npos0} ({npos0/len(results)*100:.0f}%)"
            f" | HER-YIL-pozitif {npass0} ({npass0/len(results)*100:.0f}%)")
      if npass:
          print("  T1 tabaninda KABUL BARINI GECEN VARYANTLAR:")
          for nm, key, v, tot, d, ok, t0, o0 in results:
              if ok:
                  print(f"    {key}={v}  d=${tot:+.2f}  " + " ".join(f"{y}:{d[y]:+.1f}" for y in ALLY))
      else:
          print("  T1 tabaninda KABUL BARINI GECEN VARYANT: YOK (0/%d)" % len(results))
      if npass0:
          print("  (referans) FAZ-1 TABANI T0 ile geciyor gorunen varyantlar — bu taban YANLIS,")
          print("   cunku canlida BB(LTC) ZATEN acik; T0 adaya LTC'nin yoklugunu da KREDI yaziyor:")
          for nm, key, v, tot, d, ok, t0, o0 in results:
              if o0:
                  print(f"    {key}={v}  dT0=${t0:+.2f} (GECTI)  ama dT1=${tot:+.2f} "
                        f"{'GECTI' if ok else 'KALDI'}")

      # 2-D: tek eksende sag bant, iki eksende de dayanikli mi?
      print("\n  --- 2-D (SL x RR) kontrol: tek eksen bandi 2-D'de de duruyor mu? ---")
      print(f"    {'':10s}" + "".join(f"{('rr='+str(r)):>13s}" for r in [1.333, 1.667, 2.0]))
      for sl in [2.5, 3.0, 3.5]:
          row = f"    sl={sl:<6.1f}"
          for rr in [1.333, 1.667, 2.0]:
              cmb = port(bo + bb_sleeve(COINS, P(sl=sl, rr=rr)))
              tot, d, ok = delta_line(base_live, cmb)
              row += f"{tot:>+9.1f}{'(G)' if ok else '   '}"
          print(row)
      save_ind()
    if "4" in want:
      # ── [4] KOLTUK MALIYETI ───────────────────────────────
      print("\n" + "=" * 100)
      print("[4] KOLTUK PAYLASIM MALIYETI (canli: execution.py:349 -> TEK havuz, MAXPOS=7)")
      print("=" * 100)
      solo = port(bb11)
      print(f"  BB 11 coin TEK BASINA (kendi 7 koltugu)          : ${solo['pnl'].sum():+8.2f} n={len(solo)}")
      tot7, _, ok7 = delta_line(base_live, port(bo + bb11))
      print(f"  ORTAK havuz MAXPOS=7 (CANLI-DOGRU)  delta        : ${tot7:+8.2f}  {'GECTI' if ok7 else 'KALDI'}")
      for mp in (8, 9, 11):
          b2 = port(bo + bbltc, mp); c2 = port(bo + bb11, mp)
          tot, d, ok = delta_line(b2, c2)
          print(f"  ORTAK havuz MAXPOS={mp} (taban da {mp})  delta        : ${tot:+8.2f}  "
                + " ".join(f"{y}:{d[y]:+6.1f}" for y in ALLY) + f"  {'GECTI' if ok else 'KALDI'}")
      # tamamen ayri havuz: breakout kendi 7'si + BB kendi 7'si (hipotetik, MAX_POSITIONS
      # artirmayi gerektirir; canlida BOYLE DEGIL). Taban da ayni semada olcuulur.
      ltc = port(bbltc)
      ysolo = yrs(solo); yltc = yrs(ltc)
      dsep = {y: ysolo.get(y, 0) - yltc.get(y, 0) for y in ALLY}
      tsep = solo["pnl"].sum() - ltc["pnl"].sum()
      print(f"  TAMAMEN AYRI havuz (breakout 7 + BB 7, hipotetik MAX_POSITIONS=14):")
      print(f"      delta ${tsep:+8.2f}  " + " ".join(f"{y}:{dsep[y]:+6.1f}" for y in ALLY)
            + f"  {'GECTI' if tsep > 0 and all(v > 0 for v in dsep.values()) else 'KALDI'}")
      print(f"      -> koltuk cakismasi maliyeti = ${tsep - tot7:.2f} (ayri - ortak)")
    if "5" in want:

      # ── [5] KIRILGANLIK ───────────────────────────────────────────────────────
      print("\n" + "=" * 100)
      print("[5] KIRILGANLIK TESTLERI")
      print("=" * 100)
      mb = base_live.groupby("mx")["pnl"].sum()
      mc = comb.groupby("mx")["pnl"].sum()
      allm = sorted(set(mb.index) | set(mc.index))
      dm = (mc.reindex(allm).fillna(0) - mb.reindex(allm).fillna(0))

      print("\n  [5a] Aylik delta serisi ozeti")
      print(f"    ay sayisi={len(dm)}  pozitif ay={(dm>0).sum()}  ort=${dm.mean():+.2f}  "
            f"medyan=${dm.median():+.2f}  std=${dm.std():.2f}")
      top = dm.sort_values(ascending=False)
      print(f"    en iyi 3 ay : " + ", ".join(f"{m} ${v:+.0f}" for m, v in top.head(3).items())
            + f"  = toplamin %{top.head(3).sum()/dm.sum()*100:.0f}'i")
      print(f"    en kotu 3 ay: " + ", ".join(f"{m} ${v:+.0f}" for m, v in top.tail(3).items()))
      rest = dm.drop(top.head(3).index)
      yrest = {}
      for m, v in rest.items():
          yrest[m.year] = yrest.get(m.year, 0.0) + v
      print(f"    EN IYI 3 AY CIKARILINCA: toplam ${rest.sum():+.2f}  "
            + " ".join(f"{y}:{yrest.get(y,0):+6.1f}" for y in ALLY))

      print("\n  [5b] Ay-bloklu bootstrap — 2023'un -$'i gurultu mu? (10000 cekim, seed 7)")
      rng = np.random.default_rng(7)
      vals = dm.values
      ycount = {}
      for m in dm.index:
          ycount[m.year] = ycount.get(m.year, 0) + 1
      B = 10000
      dist = {}
      for y in ALLY:
          k = ycount.get(y, 0)
          draws = rng.choice(vals, size=(B, k), replace=True).sum(axis=1)
          dist[y] = draws
          obs = dm[[m for m in dm.index if m.year == y]].sum()
          print(f"    {y}: {k:>2d} ay  gozlenen ${obs:+7.2f}  "
                f"bootstrap ort ${draws.mean():+6.2f}  P(<0)={np.mean(draws<0)*100:4.1f}%  "
                f"[%5-%95: ${np.percentile(draws,5):+.0f} .. ${np.percentile(draws,95):+.0f}]")
      allpos = np.ones(B, dtype=bool)
      for y in ALLY:
          allpos &= dist[y] > 0
      print(f"    -> Aylar degistirilebilir varsayimi altinda P(4/4 yil pozitif) = {allpos.mean()*100:.1f}%")
      print(f"       (yani gozlenen aylik dagilimin KENDISI ile bile 4/4 bariini gecme olasiligi bu kadar)")
      tot_bs = rng.choice(vals, size=(B, len(vals)), replace=True).sum(axis=1)
      print(f"    -> TOPLAM delta bootstrap: ort ${tot_bs.mean():+.2f}  P(<0)={np.mean(tot_bs<0)*100:.1f}%  "
            f"[%5-%95: ${np.percentile(tot_bs,5):+.0f} .. ${np.percentile(tot_bs,95):+.0f}]")

      print("\n  [5c] Coin-birakma (jackknife): her coin tek tek CIKARILINCA delta")
      for c in COINS:
          sub = [x for x in COINS if x != c]
          cc = port(bo + bb_sleeve(sub, P()))
          tot, d, ok = delta_line(base_live, cc)
          print(f"    -{c:5s}: d=${tot:+7.2f}  " + " ".join(f"{y}:{d[y]:+6.1f}" for y in ALLY)
                + f"  {'GECTI' if ok else 'KALDI'}")

      print("\n  [5d] NESNEL alt-kume (performansa BAKMADAN): likiditeye gore siralama")
      print("       olcut = 2023 takvim yilindaki medyan saatlik dolar hacmi (SECIM PENCERESI")
      print("       ornegin ONUNDE -> ileriye dogru lookahead yok)")
      liq = {}
      for c in COINS:
          d = res(c)
          w = d[d.index.year == 2023]
          liq[c] = float((w["close"] * w["volume"]).median())
      order = sorted(COINS, key=lambda c: -liq[c])
      print("       siralama: " + ", ".join(f"{c}(${liq[c]/1e6:.2f}M)" for c in order))
      for k in (3, 5, 7, 9, 11):
          sub = order[:k]
          cc = port(bo + bb_sleeve(sub, P()))
          tot, d, ok = delta_line(base_live, cc)
          print(f"    en likit {k:>2d}: d=${tot:+7.2f}  " + " ".join(f"{y}:{d[y]:+6.1f}" for y in ALLY)
                + f"  {'GECTI' if ok else 'KALDI'}")

      print("\n  [5e] Zaman-bolmeli: ilk yari (2023-2024) vs ikinci yari (2025-2026)")
      for lo_, hi_ in ((2023, 2024), (2025, 2026)):
          s = sum(dm[[m for m in dm.index if lo_ <= m.year <= hi_]])
          print(f"    {lo_}-{hi_}: ${s:+.2f}")

      print("\n  [5f] TEK-TEK EKLEME: canli tabana (T1) sadece o coinin BB'si eklenirse")
      single = []
      for c in COINS:
          cc = port(bo + bbltc + bb_sleeve([c], P()))
          tot, d, ok = delta_line(base_live, cc)
          single.append((c, tot, d, ok))
      for c, tot, d, ok in sorted(single, key=lambda x: -x[1]):
          print(f"    +{c:5s}: d=${tot:+7.2f}  " + " ".join(f"{y}:{d[y]:+6.1f}" for y in ALLY)
                + f"  {'GECTI' if ok else 'KALDI'}")
      print(f"    -> tek basina KABUL BARINI gecen coin: {sum(1 for x in single if x[3])}/{len(COINS)}")

      print("\n  [5g] AYNI-COIN CAKISMASI (canlida BB slot='SYM', donchian slot='SYM:donchian'")
      print("       -> ayni coinde ES ZAMANLI iki pozisyon MUMKUN; ledger 1145: mevcut deploy'da")
      print("       kesisim BOS idi, genisleme bunu BOZAR. Ne kadar?)")
      bo_by = {c: [(en, ex) for _n, en, ex, _R, _s in v] for c, v in breakout_by_coin().items()}
      ov = 0; tot_bb = 0
      for c in COINS:
          iv = bo_by[c]
          for _ns, en, ex, R, sp in gen_bb(c, P()):
              tot_bb += 1
              if any(a <= ex and en <= b for a, b in iv):
                  ov += 1
      print(f"    hafta-sonu BB islemi {tot_bb}, ayni coinde breakout ile ZAMAN CAKISAN: {ov} "
            f"(%{ov/tot_bb*100:.0f})")
      print(f"    -> bu kadar islem canlida ayni coinde CIFT notional demek (koltuk modeli")
      print(f"       bunu sayiyor ama korelasyon/marjin riskini FIYATLAMIYOR).")
    if "6" in want:

      # ── [6] RISK ETKISI ───────────────────────────────────────────────────────
      print("\n" + "=" * 100)
      print("[6] RISK: maxDD ve en kotu ay etkisi")
      print("=" * 100)
      for nm, df in (("T0 breakout", base_bo), ("T1 CANLI", base_live), ("A1 aday(11)", comb)):
          mon = df.groupby("mx")["pnl"].sum()
          print(f"  {nm:16s} toplam ${df['pnl'].sum():+8.2f}  maxDD {mdd(df):5.2f}%  "
                f"en kotu ay ${mon.min():+7.2f} ({mon.idxmin()})  "
                f"poz-ay {(mon>0).mean()*100:.0f}%  n={len(df)}")
      mB = base_live.groupby("mx")["pnl"].sum(); mC = comb.groupby("mx")["pnl"].sum()
      print(f"  -> maxDD degisimi: {mdd(base_live):.2f}% -> {mdd(comb):.2f}% "
            f"({mdd(comb)-mdd(base_live):+.2f} puan)")
      print(f"  -> en kotu ay    : ${mB.min():+.2f} -> ${mC.min():+.2f} ({mC.min()-mB.min():+.2f})")
      print(f"  -> ayni ay ({mB.idxmin()}) aday altinda: ${mC.get(mB.idxmin(),0):+.2f}")

    save_ind()
    print(f"\n[toplam sure {time.time()-t0:.0f}s]")


if __name__ == "__main__":
    main()
