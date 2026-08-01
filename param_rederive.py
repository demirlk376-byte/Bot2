"""
param_rederive.py — ÇEKİRDEK PARAMETRELERİ DÜRÜSTÇE YENİDEN TÜRET.

NEDEN: donchian'ın (kanal=40, SL=2xATR, rr=2.5, maxhold=30) ve squeeze'in
(SL=2xATR, rr=2.5, maxhold=48) parametreleri UZUN ÖNCE, occ hatası ve MTF
lookahead DÜZELTİLMEDEN önce seçilmişti. Bu dosya onları temiz araçlarla,
KATI TRAIN/TEST ayrımıyla yeniden türetir.

DİSİPLİN:
  * SEÇİM YALNIZ TRAIN (çıkış yılı 2023-2024) toplam $'ına göre.
  * TEST (2025-2026) seçimden SONRA bir kez ölçülür. Kötüyse RED; geri dönüş YOK.
  * Her sleeve AYRI taranır, diğerleri taban parametresinde KALIR.
  * Kombinasyon sayısı raporlanır (çoklu-karşılaştırma / şans riski).
  * PLATO analizi: seçilen noktanın ±1 adım komşuları da iyi mi?
  * KALDIRAÇ KONTROLÜ: sl_atr değişimi ortalama dağıtılan riski değiştirir
    (eff = min(RISKF, CAP*sl_pct)). Her aday için ort risk raporlanır.

MEKANİK: deployed_backtest.gen/gen_bb/seat_select ile BYTE-DENK olduğu
--verify ile kanıtlanır (n=1579 / $1421 / yıl-yıl). Hız için donchian sinyali
vektörleştirildi (pencere-yerel EMA200 kapalı-form düzeltmeyle birebir),
squeeze sinyali üretim sınıfıyla bir kez üretilip önbelleğe alınır.

Kullanım:
  python param_rederive.py verify      # sadece taban doğrulama
  python param_rederive.py donchian    # donchian taraması
  python param_rederive.py squeeze     # squeeze taraması
  python param_rederive.py all
"""
from __future__ import annotations
import sys, os, pickle, heapq, itertools, time
import numpy as np, pandas as pd

import fast_bt
from indicators import atr as atr_fn, adx as adx_fn
from strategies.squeeze import SqueezeStrategy
import deployed_backtest as DB

BAL0, FEE, RISKF, CAP, MAXPOS = 190.0, 0.0001, 0.0225, 1.25, 7
DONCH = DB.DONCH          # SOL ETH ADA NEAR BCH ICP BNB
SQZ = DB.SQZ              # XRP DOGE TRX XLM
BB_COINS = DB.BB_COINS    # LTC

# TABAN parametreler
BASE_D = dict(channel=40, sl_atr=2.0, rr=2.5, mh=30)
BASE_S = dict(sl_atr=2.0, rr=2.5, mh=48)

CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
os.makedirs(CACHE, exist_ok=True)

TRAIN_YEARS = (2023, 2024)
TEST_YEARS = (2025, 2026)
BASE_YEAR = {2023: 320.7, 2024: 457.0, 2025: 447.0, 2026: 195.0}   # ölçümle güncellenecek


# ───────────────────────── veri / gösterge ─────────────────────────
_MCACHE = {}
def M(coin):
    if coin not in _MCACHE:
        _MCACHE[coin] = fast_bt.load(coin, source="local")
    return _MCACHE[coin]


class Bars:
    """Bir coin+tf için sabit diziler (sinyalden bağımsız)."""
    def __init__(self, m, tf):
        d = fast_bt.resample(m, tf)
        self.d = d
        self.hi = d["high"].values; self.lo = d["low"].values; self.cl = d["close"].values
        # DİKKAT: pandas 3'te index dtype datetime64[us] olabiliyor; .values.astype(int64)
        # MİKRO-saniye verir ama deployed_backtest idx[i].value = NANO-saniye kullanır.
        # Karıştırmak koltuk seçimini bozuyordu (ilk denemede n=1584/$1399 çıkmıştı).
        self.idx = d.index.values.astype("datetime64[ns]").astype("int64")   # ns
        self.n = len(self.cl)
        self.atr = atr_fn(d["high"], d["low"], d["close"], 14).values


def donch_candidates(bars: Bars, channel: int):
    """deployed_backtest.gen'in donchian sinyal üretimiyle BİREBİR, vektörel.

    Kritik incelik: canlı/gen, analyze'a 260-BARLIK PENCERE verir; EMA200 o
    pencere içinde baştan başlar. Tam-seri EMA ile aynı DEĞİLDİR. Kapalı form:
      pencere [s..i], W=260, a=2/201, b=1-a
      E(i) = F(i) + b^(W-1) * (x[s] - F(s)),  F = tam-seri ewm(adjust=False)
    (türev: F(i) = b^i x0 + Σ a b^(i-t) x_t  ve  E(i) = b^(W-1) x_s + Σ_{t>s} a b^(i-t) x_t)
    """
    d = bars.d; n = bars.n
    close = bars.cl
    W = 260
    a = 2.0 / 201.0; b = 1.0 - a
    F = d["close"].ewm(span=200, adjust=False).mean().values
    ema_loc = np.full(n, np.nan)
    ii = np.arange(W - 1, n); s = ii - (W - 1)
    ema_loc[ii] = F[ii] + (b ** (W - 1)) * (close[s] - F[s])

    ch_hi = pd.Series(bars.hi).rolling(channel).max().shift(1).values
    ch_lo = pd.Series(bars.lo).rolling(channel).min().shift(1).values

    # canlı-birebir MTF (lookahead YOK)
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = close > _dprev

    ok_atr = np.isfinite(bars.atr) & (bars.atr > 0)
    degen = ~(ch_hi > ch_lo)
    lng = (close > ch_hi) & (close > ema_loc) & ~degen
    sht = (close < ch_lo) & (close < ema_loc) & ~degen & ~lng
    direction = np.where(lng, 1, np.where(sht, -1, 0))
    # MTF kapısı: long ise gün-trendi yukarı, short ise aşağı olmalı
    mtf_ok = np.where(direction == 1, up, np.where(direction == -1, ~up, False))

    sel = np.zeros(n, bool)
    sel[260:n - 1] = True
    sel &= ok_atr & (direction != 0) & mtf_ok
    ci = np.where(sel)[0]
    return ci, direction[ci].astype(np.int64), bars.atr[ci]


def sqz_candidates(coin):
    """squeeze sinyalleri — ÜRETİM sınıfı (pencere-yerel), bir kez üretilip önbelleğe.
    sl_atr/rr/maxhold sinyal YÖNÜNÜ etkilemez (SqueezeStrategy'de yön, sl/tp'den
    ÖNCE belirlenir) → tarama boyunca aday listesi sabittir."""
    p = os.path.join(CACHE, f"sqzcand_{coin}.pkl")
    if os.path.exists(p):
        with open(p, "rb") as f: return pickle.load(f)
    bars = BARS_S[coin]
    d = bars.d; n = bars.n
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    s = SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True)
    ci = []; cd = []; ca = []
    for i in range(260, n - 1):
        av = bars.atr[i]
        if not np.isfinite(av) or av <= 0: continue
        xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
        if xv <= 20.0: continue
        dr = s.analyze(d.iloc[max(0, i - 119):i + 1], float(av)).direction
        if dr == 0: continue
        ci.append(i); cd.append(dr); ca.append(av)
    out = (np.array(ci, np.int64), np.array(cd, np.int64), np.array(ca, float))
    with open(p, "wb") as f: pickle.dump(out, f)
    return out


# ───────────────────────── simülasyon ─────────────────────────
def simulate(cand, bars: Bars, sl_a, rr, mh):
    """occ = j (coin başına TEK pozisyon). Elenen sinyal occ'u İLERLETMEZ —
    aday listesi zaten kapılardan geçmiş olanlardır."""
    ci, cd, ca = cand
    hi, lo, cl, idx, n = bars.hi, bars.lo, bars.cl, bars.idx, bars.n
    out = []; occ = -1; BIG = 1 << 60
    for k in range(len(ci)):
        i = int(ci[k])
        if i <= occ: continue
        d_ = int(cd[k]); av = float(ca[k])
        sld = sl_a * av; e = cl[i]
        slp = e - d_ * sld; tp = e + d_ * rr * sld
        hh = min(i + 1 + mh, n)
        wl = lo[i + 1:hh]; wh = hi[i + 1:hh]
        if d_ == 1:
            m_sl = wl <= slp; m_tp = wh >= tp
        else:
            m_sl = wh >= slp; m_tp = wl <= tp
        k_sl = int(m_sl.argmax()) if m_sl.any() else BIG
        k_tp = int(m_tp.argmax()) if m_tp.any() else BIG
        if k_sl <= k_tp and k_sl < BIG:
            j = i + 1 + k_sl; ep = slp
        elif k_tp < BIG:
            j = i + 1 + k_tp; ep = tp
        else:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((int(idx[i]), int(idx[j]), R, sld / e))
        occ = j
    return out


def seat_select(trades):
    """GİRİŞ zamanına göre koltuk, MAXPOS=7, TÜM sleeve'ler AYNI havuz."""
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for ent, ext, R, slp in ev:
        while openh and openh[0][0] <= ent: heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1; heapq.heappush(openh, (ext, ctr, R)); taken.append((ext, R, slp))
    return sorted(taken, key=lambda t: t[0])


def evaluate(trades):
    taken = seat_select(trades)
    r = np.array([t[1] for t in taken]); sp = np.array([t[2] for t in taken])
    yr = np.array([pd.Timestamp(t[0]).year for t in taken])
    eff = np.minimum(RISKF, CAP * sp)
    pnl = r * eff * BAL0
    per_year = {int(y): float(pnl[yr == y].sum()) for y in np.unique(yr)}
    tr = float(sum(v for y, v in per_year.items() if y in TRAIN_YEARS))
    te = float(sum(v for y, v in per_year.items() if y in TEST_YEARS))
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), tot=float(pnl.sum()), train=tr, test=te, year=per_year,
                pf=float(gp / gl) if gl > 0 else 99.0, wr=float((r > 0).mean() * 100),
                avg_risk=float(eff.mean() * 100))


# ───────────────────────── kurulum ─────────────────────────
print("veri yükleniyor...")
BARS_D = {c: Bars(M(c), "4h") for c in DONCH}
BARS_S = {c: Bars(M(c), "1h") for c in SQZ}

_BBC = os.path.join(CACHE, "bbtrades.pkl")
if os.path.exists(_BBC):
    with open(_BBC, "rb") as f: BB_TRADES = pickle.load(f)
else:
    BB_TRADES = []
    for c in BB_COINS:
        BB_TRADES += [(int(t[0]), int(pd.Timestamp(t[1]).value), t[2], t[3])
                      for t in DB.gen_bb(M(c))]
    with open(_BBC, "wb") as f: pickle.dump(BB_TRADES, f)

_SQC = {c: sqz_candidates(c) for c in SQZ}
_DCAND = {}
def dcand(coin, ch):
    if (coin, ch) not in _DCAND:
        _DCAND[(coin, ch)] = donch_candidates(BARS_D[coin], ch)
    return _DCAND[(coin, ch)]


def donch_trades(channel, sl_atr, rr, mh):
    out = []
    for c in DONCH: out += simulate(dcand(c, channel), BARS_D[c], sl_atr, rr, mh)
    return out


def sqz_trades(sl_atr, rr, mh):
    out = []
    for c in SQZ: out += simulate(_SQC[c], BARS_S[c], sl_atr, rr, mh)
    return out


def portfolio(dp, sp):
    return donch_trades(dp["channel"], dp["sl_atr"], dp["rr"], dp["mh"]) \
         + sqz_trades(sp["sl_atr"], sp["rr"], sp["mh"]) + BB_TRADES


# ───────────────────────── 1) DOĞRULAMA ─────────────────────────
def verify():
    print("\n" + "=" * 74)
    print("1) TABAN DOĞRULAMA — bu motor deployed_backtest ile birebir mi?")
    print("=" * 74)
    ok = True
    # a) sinyal-seviyesi birebirlik (donchian, SOL)
    ref = DB.gen("donchian", M("SOL"))
    mine = simulate(dcand("SOL", 40), BARS_D["SOL"], 2.0, 2.5, 30)
    same = len(ref) == len(mine) and all(
        int(a[0]) == b[0] and int(pd.Timestamp(a[1]).value) == b[1]
        and abs(a[2] - b[2]) < 1e-12 and abs(a[3] - b[3]) < 1e-12
        for a, b in zip(ref, mine))
    print(f"  donchian/SOL işlem-işlem denk: {same}  (ref {len(ref)} / bu {len(mine)})")
    ok &= same
    ref = DB.gen("squeeze", M("XRP"))
    mine = simulate(_SQC["XRP"], BARS_S["XRP"], 2.0, 2.5, 48)
    same = len(ref) == len(mine) and all(
        int(a[0]) == b[0] and int(pd.Timestamp(a[1]).value) == b[1]
        and abs(a[2] - b[2]) < 1e-12 for a, b in zip(ref, mine))
    print(f"  squeeze/XRP  işlem-işlem denk: {same}  (ref {len(ref)} / bu {len(mine)})")
    ok &= same
    # b) portföy seviyesi
    e = evaluate(portfolio(BASE_D, BASE_S))
    print(f"\n  TABAN: n={e['n']} (bek. 1579) | PF {e['pf']:.2f} (1.45) | WR {e['wr']:.0f}% (44)")
    print(f"         toplam ${e['tot']:+.0f} (bek. +1421) | ort risk {e['avg_risk']:.2f}% (2.13)")
    print(f"         yıl-yıl: " + " ".join(f"{y}:{v:+.0f}" for y, v in sorted(e['year'].items())))
    hit = (e['n'] == 1579 and abs(e['tot'] - 1421) < 1.5)
    print(f"  → TABAN YENİDEN ÜRETİLDİ: {hit and ok}")
    for y, v in e["year"].items(): BASE_YEAR[y] = v
    return (hit and ok), e


# ───────────────────────── 2) TARAMA ─────────────────────────
def sweep_donchian(base):
    grid_ch = [20, 30, 40, 60, 80]
    grid_sl = [1.5, 2.0, 2.5, 3.0]
    grid_rr = [1.5, 2.0, 2.5, 3.0, 4.0]
    grid_mh = [20, 30, 45, 60]
    combos = list(itertools.product(grid_ch, grid_sl, grid_rr, grid_mh))
    print("\n" + "=" * 74)
    print(f"2) DONCHIAN TARAMASI — {len(combos)} kombinasyon "
          f"(squeeze+BB TABANDA sabit). SEÇİM YALNIZ TRAIN 2023-2024.")
    print("=" * 74)
    sq = sqz_trades(**BASE_S)
    res = {}
    t0 = time.time()
    for k, (ch, sl, rr, mh) in enumerate(combos):
        tr = donch_trades(ch, sl, rr, mh) + sq + BB_TRADES
        res[(ch, sl, rr, mh)] = evaluate(tr)
        if k % 50 == 0: print(f"    {k}/{len(combos)} ({time.time()-t0:.0f}s)", flush=True)
    return combos, res, grid_ch, grid_sl, grid_rr, grid_mh


def sweep_squeeze(base):
    grid_sl = [1.5, 2.0, 2.5]
    grid_rr = [2.0, 2.5, 3.0]
    grid_mh = [24, 48, 72]
    combos = list(itertools.product(grid_sl, grid_rr, grid_mh))
    print("\n" + "=" * 74)
    print(f"3) SQUEEZE TARAMASI — {len(combos)} kombinasyon "
          f"(donchian+BB TABANDA sabit). SEÇİM YALNIZ TRAIN 2023-2024.")
    print("=" * 74)
    dn = donch_trades(**BASE_D)
    res = {}
    for sl, rr, mh in combos:
        res[(sl, rr, mh)] = evaluate(dn + sqz_trades(sl, rr, mh) + BB_TRADES)
    return combos, res, grid_sl, grid_rr, grid_mh


def report(name, res, base_key, grids):
    keys = list(res.keys())
    keys.sort(key=lambda k: -res[k]["train"])
    print(f"\n  --- {name}: TRAIN sıralaması (ilk 12) ---")
    print(f"    {'params':<24} {'TRAIN$':>8} {'ort risk':>9} {'n':>5}")
    for k in keys[:12]:
        e = res[k]
        star = "  <-- TABAN" if k == base_key else ""
        print(f"    {str(k):<24} {e['train']:+8.0f} {e['avg_risk']:8.2f}% {e['n']:5d}{star}")
    bt = res[base_key]["train"]
    rank = keys.index(base_key) + 1
    print(f"    TABAN {base_key}: TRAIN {bt:+.0f}, sıra {rank}/{len(keys)}")

    best = keys[0]
    print(f"\n  --- {name}: TRAIN SEÇİMİ = {best} ---")
    e = res[best]
    print(f"    TRAIN ${e['train']:+.0f} (taban ${bt:+.0f}, fark {e['train']-bt:+.0f})")

    # PLATO: ±1 adım komşular
    print(f"\n  --- {name}: PLATO ANALİZİ (±1 adım komşular, TRAIN$) ---")
    nb = []
    for ax in range(len(grids)):
        g = grids[ax]; pos = g.index(best[ax])
        for dpos in (-1, 1):
            q = pos + dpos
            if 0 <= q < len(g):
                kk = list(best); kk[ax] = g[q]; kk = tuple(kk)
                if kk in res:
                    nb.append((kk, res[kk]["train"]))
    for kk, v in nb:
        print(f"      {str(kk):<24} {v:+8.0f}   ({v - e['train']:+.0f} vs tepe)")
    nbm = float(np.mean([v for _, v in nb]))
    allm = float(np.mean([res[k]["train"] for k in res]))
    print(f"      komşu ORTALAMASI {nbm:+.0f} | tepe {e['train']:+.0f} | "
          f"tüm ızgara ort {allm:+.0f}")
    print(f"      komşu/tepe oranı {nbm/e['train']*100:.0f}%  "
          f"(>%85 = plato, <%70 = tek tepe/gürültü)")
    return best, res[best], nb, nbm, allm


def final_test(name, best, e, base_eval):
    print(f"\n  --- {name}: ŞİMDİ (ve ancak şimdi) TEST AÇILIYOR ---")
    print(f"    {'':<10} {'TRAIN$':>8} {'TEST$':>8} {'TOPLAM$':>8} {'ort risk':>9} {'n':>5} {'PF':>5}")
    print(f"    {'TABAN':<10} {base_eval['train']:+8.0f} {base_eval['test']:+8.0f} "
          f"{base_eval['tot']:+8.0f} {base_eval['avg_risk']:8.2f}% {base_eval['n']:5d} {base_eval['pf']:5.2f}")
    print(f"    {'ADAY':<10} {e['train']:+8.0f} {e['test']:+8.0f} "
          f"{e['tot']:+8.0f} {e['avg_risk']:8.2f}% {e['n']:5d} {e['pf']:5.2f}")
    print(f"    yıl-yıl:")
    allyr = True
    for y in sorted(base_eval["year"]):
        bv = base_eval["year"][y]; cv = e["year"].get(y, 0.0)
        good = cv > bv
        allyr &= good
        print(f"      {y}: taban {bv:+7.0f} → aday {cv:+7.0f}  {'GEÇTİ' if good else 'KALDI'}")
    passed = (e["test"] > base_eval["test"]) and allyr
    lev = e["avg_risk"] > base_eval["avg_risk"] + 0.005
    print(f"    TEST tabanı geçti mi: {e['test'] > base_eval['test']} | HER YIL geçti mi: {allyr}")
    if lev:
        print(f"    ⚠ KALDIRAÇ UYARISI: ort risk {base_eval['avg_risk']:.2f}% → "
              f"{e['avg_risk']:.2f}% ARTTI; kazanç kaldıraçtan gelebilir.")
    print(f"    KABUL BARI: {'GEÇTİ' if passed else 'RED'}")
    return passed, lev


# ───────────────── 4) POST-HOC TANI (SEÇİM DEĞİL) ─────────────────
def diagnose(tag, fn, bk, axes, base_eval):
    """TARAMADAN SONRA çalışır. Amaç: 'TRAIN sıralaması TEST'e taşınıyor mu?'
    sorusunu ölçmek. BURADAN ADAY SEÇİLMEZ — TEST'ten seçmek yasaktır."""
    p = os.path.join(CACHE, fn)
    if not os.path.exists(p): return
    res = pickle.load(open(p, "rb"))
    b = res[bk]; ks = list(res)
    tr = np.array([res[k]["train"] for k in ks]); te = np.array([res[k]["test"] for k in ks])
    tot = np.array([res[k]["tot"] for k in ks])
    rank = lambda a: np.argsort(np.argsort(a))
    print(f"\n  === {tag} POST-HOC TANI ({len(ks)} kombinasyon) — SEÇİM DEĞİL ===")
    print(f"    TRAIN↔TEST Pearson {np.corrcoef(tr,te)[0,1]:+.2f} | "
          f"Spearman {np.corrcoef(rank(tr),rank(te))[0,1]:+.2f}")
    o = sorted(range(len(ks)), key=lambda i: -tr[i])
    print(f"    TABAN {bk}: TRAIN sıra {o.index(ks.index(bk))+1}/{len(ks)} | "
          f"TEST sıra {sorted(range(len(ks)),key=lambda i:-te[i]).index(ks.index(bk))+1} | "
          f"TOPLAM sıra {sorted(range(len(ks)),key=lambda i:-tot[i]).index(ks.index(bk))+1}")
    print(f"    TRAIN ilk-10'un TEST ort {te[o[:10]].mean():+.0f} vs TABAN TEST {b['test']:+.0f}")
    btr = [k for k in ks if res[k]["train"] > b["train"]]
    bte = [k for k in btr if res[k]["test"] > b["test"]]
    print(f"    TRAIN'de tabanı geçen {len(btr)} noktanın {len(bte)}'i TEST'te de geçiyor "
          f"({100*len(bte)/max(len(btr),1):.0f}%; saf şans ~%50)")
    full = [k for k in ks if res[k]["test"] > b["test"] and
            all(res[k]["year"].get(y, 0) > base_eval["year"][y] for y in (2023, 2024, 2025, 2026))]
    print(f"    TAM barı geçen: {len(full)}/{len(ks)}")
    for k in sorted(full, key=lambda k: -res[k]["train"])[:5]:
        e = res[k]
        norm = e["tot"] * base_eval["avg_risk"] / e["avg_risk"]
        print(f"      {str(k):<20} TRAINsıra{o.index(ks.index(k))+1:>3} TEST{e['test']:+6.0f} "
              f"risk{e['avg_risk']:.2f}% TOPLAM{e['tot']:+6.0f} → risk-normalize {norm:+.0f} "
              f"(taban {base_eval['tot']:+.0f})")
    print(f"    eksen marjinali (TRAIN$/TEST$/ort risk%):")
    for nm, ax, g in axes:
        row = "  ".join(f"{v}:{np.mean([res[k]['train'] for k in ks if k[ax]==v]):+.0f}/"
                        f"{np.mean([res[k]['test'] for k in ks if k[ax]==v]):+.0f}/"
                        f"{np.mean([res[k]['avg_risk'] for k in ks if k[ax]==v]):.2f}" for v in g)
        print(f"      {nm:8s} {row}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    ok, base_eval = verify()
    if not ok:
        print("\n  ✗ TABAN TUTMADI — DURULDU."); return
    if mode in ("verify",): return

    if mode in ("all", "donchian"):
        combos, res, gc, gs, gr, gm = sweep_donchian(base_eval)
        bk = (40, 2.0, 2.5, 30)
        best, be, nb, nbm, allm = report("DONCHIAN", res, bk, [gc, gs, gr, gm])
        final_test("DONCHIAN", best, be, base_eval)
        # eksen bazlı marjinal (plato okuması için)
        print("\n  --- DONCHIAN: eksen bazlı TRAIN ortalaması (marjinal) ---")
        for nm, g, ax in (("kanal", gc, 0), ("sl_atr", gs, 1), ("rr", gr, 2), ("maxhold", gm, 3)):
            row = " ".join(f"{v}:{np.mean([res[k]['train'] for k in res if k[ax]==v]):+.0f}" for v in g)
            print(f"      {nm:8s} {row}")
        with open(os.path.join(CACHE, "donch_sweep.pkl"), "wb") as f: pickle.dump(res, f)
        diagnose("DONCHIAN", "donch_sweep.pkl", bk,
                 [("kanal", 0, gc), ("sl_atr", 1, gs), ("rr", 2, gr), ("maxhold", 3, gm)],
                 base_eval)

    if mode in ("all", "squeeze"):
        combos, res, gs, gr, gm = sweep_squeeze(base_eval)
        bk = (2.0, 2.5, 48)
        best, be, nb, nbm, allm = report("SQUEEZE", res, bk, [gs, gr, gm])
        final_test("SQUEEZE", best, be, base_eval)
        print("\n  --- SQUEEZE: eksen bazlı TRAIN ortalaması (marjinal) ---")
        for nm, g, ax in (("sl_atr", gs, 0), ("rr", gr, 1), ("maxhold", gm, 2)):
            row = " ".join(f"{v}:{np.mean([res[k]['train'] for k in res if k[ax]==v]):+.0f}" for v in g)
            print(f"      {nm:8s} {row}")
        with open(os.path.join(CACHE, "sqz_sweep.pkl"), "wb") as f: pickle.dump(res, f)
        diagnose("SQUEEZE", "sqz_sweep.pkl", bk,
                 [("sl_atr", 0, gs), ("rr", 1, gr), ("maxhold", 2, gm)], base_eval)


if __name__ == "__main__":
    main()
