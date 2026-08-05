"""
nk_daily.py — GUNLUK (1D) AYRI TREND KOLU: ledger'daki "edge gercek ama koltuk-gunu
oldurdu" hukmunun YENIDEN YARGILANMASI.

NEDEN YENIDEN ACILDI (2026-08-03 cercevesi):
  daily_trend_test.py (2026-07-31) 270 hucrenin 259'unu TEST'te pozitif buldu — edge
  tartismali degil. RET gerekcesi KOLTUK EKONOMISIYDI: "koltuk-gunu basina $0.44 taban
  vs $0.08 gunluk". Bugun olculdu ki koltuklar zamanin yalnizca %3.25'inde tam dolu ve
  koltuk bulamayan sinyal tum tarihte 24 tane => "koltuk-gunu" kit bir kaynak DEGIL.
  Dogru soru: bu kol ankorun TOPLAMINA ne ekliyor?

BU DOSYANIN ONCEKINDEN FARKI (uc duzeltme, hepsi ADAY ALEYHINE calisir):
  1. SEMBOL-BASINA NETLEME (MEXC netted mod). daily_trend_test.py birlesik portfoyde
     per-symbol guard UYGULAMADI: ayni anda 4h-donchian SOL + gunluk SOL aciyordu.
     MEXC'te bu IMKANSIZ. Guard eklendi (taban tek basina degismiyor: sleeve'ler coin
     paylasmiyor, dogrulaniyor).
  2. ZAMAN DAMGASI: gunluk barda giris bar KAPANISINDA olur = idx[i]+1G, cikis idx[j]+1G.
     Onceki kod idx[i] (gun BASI) kullaniyordu => gunluk islem koltugu 24 saat ERKEN
     kapiyordu (taban 4h islemlerine karsi haksiz oncelik). Duzeltildi.
  3. OLCUM 22 COIN uzerinden (gorev sarti), deploy denemeleri 3 coin-kumesi varyantiyla.

ON-KAYITLI BAR (gevsetilmez):
  Delta$ > +28 · HICBIR YIL >%10 kotulesmeyecek · maxDD >2 puan artmayacak ·
  EN KOTU AY KOTULESMEYECEK · dort sahtelik testi ayni yonu gosterecek.

Kullanim:  python3 nk_daily.py local
"""
import sys, os, math, heapq, pickle, itertools
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, ema as ema_fn

SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
CACHE = os.path.join(SCR, "nk_daily_base.pkl")
DCACHE = os.path.join(SCR, "nk_daily_bars.pkl")

ALL22 = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
DEPLOY = A.DONCH + A.SQZ + A.BB_COINS                    # 12 coin canlida kullaniliyor
NONDEP = [c for c in ALL22 if c not in DEPLOY]           # 10 coin bos duruyor

CH_GRID = [20, 30, 50, 80, 100]
EMA_GRID = [100, 200]
SL_GRID = [1.5, 2.0, 3.0]
RR_GRID = [2.0, 3.0, 4.0]
MH_GRID = [20, 40, 60]
# LEDGER'IN SECTIGI (2026-07-31, YALNIZ TRAIN'den secilmisti — bugun yeniden secmiyorum,
# yeniden secmek coklu-karsilastirma yukunu ikinci kez odemek olurdu)
REF = (30, 100, 2.0, 4.0, 60)

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
PRI = {"donchian": 0, "squeeze": 1, "bb": 2, "daily": 3}   # sleeve sirasi: DONCH->SQZ->BB->YENI
DAY_NS = 86_400_000_000_000


# ───────────────────────────── yardimcilar ─────────────────────────────
def binom_two_sided(k, n):
    """iki yonlu isaret testi p-degeri (p=0.5), math.comb ile — scipy yok."""
    if n == 0: return 1.0
    pmf = [math.comb(n, i) for i in range(n + 1)]
    tot = float(sum(pmf))
    obs = pmf[k]
    return min(1.0, sum(v for v in pmf if v <= obs + 1e-9) / tot)


def zstat(r):
    r = np.asarray(r, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0: return 0.0
    return float(r.mean() / (r.std(ddof=1) / math.sqrt(len(r))))


# ───────────────────────────── taban havuzu ─────────────────────────────
def base_pool(source):
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f: return pickle.load(f)
    out = []
    for c in A.DONCH:
        out += [(t[0], t[1], t[2], t[3], "donchian", c)
                for t in A.gen("donchian", fast_bt.load(c, source=source))]
    for c in A.SQZ:
        out += [(t[0], t[1], t[2], t[3], "squeeze", c)
                for t in A.gen("squeeze", fast_bt.load(c, source=source))]
    for c in A.BB_COINS:
        out += [(t[0], t[1], t[2], t[3], "bb", c)
                for t in A.gen_bb(fast_bt.load(c, source=source))]
    os.makedirs(SCR, exist_ok=True)
    with open(CACHE, "wb") as f: pickle.dump(out, f)
    return out


# ───────────────────────────── gunluk kol ─────────────────────────────
def daily_cache(source, coins):
    """coin -> gunluk barlar + gostergeler + (ch,ema) sinyal listeleri. BIR KEZ."""
    if os.path.exists(DCACHE):
        with open(DCACHE, "rb") as f: dcs = pickle.load(f)
        if all(c in dcs for c in coins): return dcs
    dcs = {}
    for coin in coins:
        m = fast_bt.load(coin, source=source)
        d = fast_bt.resample(m, "1D")
        hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
        n = len(cl)
        a = atr_fn(d["high"], d["low"], d["close"], 14).values
        emas = {e: ema_fn(d["close"], e).values for e in EMA_GRID}
        # kanal: ONCEKI ch barin hi max / lo min — mevcut bar HARIC (lookahead yok)
        rh = {c: pd.Series(hi).rolling(c).max().shift(1).values for c in CH_GRID}
        rl = {c: pd.Series(lo).rolling(c).min().shift(1).values for c in CH_GRID}
        sig = {}
        for ch in CH_GRID:
            for esp in EMA_GRID:
                warm = max(esp, ch + 2)
                ev = emas[esp]; s = []
                for i in range(warm, n - 1):
                    av = a[i]
                    if not np.isfinite(av) or av <= 0: continue
                    c_ = cl[i]; H = rh[ch][i]; L = rl[ch][i]
                    if not (np.isfinite(H) and np.isfinite(L) and H > L): continue
                    if c_ > H and c_ > ev[i]: s.append((i, 1))
                    elif c_ < L and c_ < ev[i]: s.append((i, -1))
                sig[(ch, esp)] = s
        dcs[coin] = dict(idx=d.index, hi=hi, lo=lo, cl=cl, atr=a, n=n, sig=sig)
    os.makedirs(SCR, exist_ok=True)
    with open(DCACHE, "wb") as f: pickle.dump(dcs, f)
    return dcs


def gen_daily(dc, ch, esp, sl_a, rr, mh, coin, shift_day=True):
    """occ-farkinda uretim (elenen sinyal occ'u ILERLETMEZ).
    shift_day=True: giris/cikis damgasi bar KAPANISINA (+1 gun) kaydirilir — koltuk
    talebinin gercek zamani. False: eski (daily_trend_test) konvansiyonu."""
    hi, lo, cl, a, n, idx = dc["hi"], dc["lo"], dc["cl"], dc["atr"], dc["n"], dc["idx"]
    off = DAY_NS if shift_day else 0
    out = []; occ = -1
    for (i, d_) in dc["sig"][(ch, esp)]:
        if i <= occ: continue
        sld = sl_a * a[i]; e = cl[i]
        slp = e - d_ * sld; tp = e + d_ * rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value + off, idx[j] + pd.Timedelta(nanoseconds=off),
                    R, sld / e, "daily", coin, d_))
        occ = j
    return out


# ───────────────────────── portfoy mekanigi ─────────────────────────
def seat_select(trades, maxpos=A.MAXPOS, symguard=True):
    """MAXPOS + SEMBOL-BASINA NETLEME. Beraberlikte sleeve onceligi DONCH->SQZ->BB->DAILY.
    Doner: (alinan, koltuk-dolu-diye-red, sembol-mesgul-diye-red)."""
    ev = sorted(trades, key=lambda t: (t[0], PRI.get(t[4], 9)))
    openl = []                      # (exit_ns, coin)
    taken = []; rej_seat = []; rej_sym = []
    for tr in ev:
        entry_ns = tr[0]; coin = tr[5]
        if openl: openl = [o for o in openl if o[0] > entry_ns]
        if symguard and any(o[1] == coin for o in openl):
            rej_sym.append(tr); continue
        if len(openl) >= maxpos:
            rej_seat.append(tr); continue
        openl.append((pd.Timestamp(tr[1]).value, coin)); taken.append(tr)
    return taken, rej_seat, rej_sym


def stats(taken):
    if not taken:
        return dict(n=0, tot=0.0, pf=0.0, wr=0.0, dd=0.0, yrs={}, mon=pd.Series(dtype=float),
                    worst=0.0, posm=0.0, avg_risk=0.0, R=np.array([]), pnl=np.array([]))
    tk = sorted(taken, key=lambda t: pd.Timestamp(t[1]))
    r = np.array([t[2] for t in tk]); slp = np.array([t[3] for t in tk])
    ex = [pd.Timestamp(t[1]) for t in tk]
    eff = np.minimum(A.RISKF, A.CAP * slp)
    pnl = r * eff * A.BAL0
    eq = np.concatenate([[A.BAL0], A.BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    ya = np.array([x.year for x in ex])
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum()
    monp = mon / A.BAL0 * 100
    return dict(n=len(r), tot=float(pnl.sum()), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100,
                dd=float(((peak - eq) / peak).max() * 100),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))},
                mon=mon, worst=float(monp.min()), posm=float((monp > 0).mean() * 100),
                avg_risk=float(eff.mean()), R=r, pnl=pnl)


def split_tt(trades):
    tr = [t for t in trades if pd.Timestamp(t[1]) < SPLIT]
    te = [t for t in trades if t[0] >= SPLIT.value]
    return tr, te


# ═══════════════════════════════ ANA ═══════════════════════════════
def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    W = 100
    print(f"\n{'='*W}\n=== nk_daily.py — GUNLUK (1D) AYRI TREND KOLU, YENIDEN YARGILAMA ===\n{'='*W}")

    # ─────── [1] ANKOR DOGRULAMA ───────
    base = base_pool(source)
    bt, brs, brsym = seat_select(base, symguard=True)
    B = stats(bt)
    bt_noguard, _, _ = seat_select(base, symguard=False)
    print(f"\n[1] ANKOR DOGRULAMA (deployed_backtest tam canli config)")
    print(f"    n={B['n']}  PF {B['pf']:.2f}  ${B['tot']:+.2f}  maxDD %{B['dd']:.1f}  "
          f"en kotu ay %{B['worst']:.1f}  poz-ay %{B['posm']:.0f}")
    print(f"    yil-yil: " + "  ".join(f"{y}:${v:+.0f}" for y, v in B["yrs"].items()))
    print(f"    sembol-guard tabani DEGISTIRIYOR mu? n(guard)={len(bt)} vs n(guardsiz)="
          f"{len(bt_noguard)} -> {'DEGISTIRMIYOR (dogru)' if len(bt)==len(bt_noguard) else 'DEGISTIRIYOR (!)'}")
    ok = (B["n"] == 1579 and abs(B["tot"] - 1420.66) < 0.5)
    print(f"    ZORUNLU KONTROL n=1579 / $+1420.66 : {'GECTI' if ok else 'KALDI -> ARAC BOZUK'}")
    if not ok:
        print("    DUR. Sonuclar gecersiz."); sys.exit(1)
    print(f"    tabanda koltuk bulamayan sinyal: {len(brs)} (sembol cakismasi: {len(brsym)})")

    # ─────── [2] 22 COIN UZERINDE OLCUM: EDGE GERCEK MI? ───────
    print(f"\n[2] OLCUM — 22 COIN, GUNLUK KOL TEK BASINA (koltuk YOK, occ VAR)")
    dcs = daily_cache(source, ALL22)
    ch, esp, sl_a, rr, mh = REF
    print(f"    referans config (ledger'in TRAIN-argmax'i): ch{ch} EMA{esp} SL{sl_a}xATR rr{rr} mh{mh}g")
    per_coin = {}
    for c in ALL22:
        per_coin[c] = gen_daily(dcs[c], ch, esp, sl_a, rr, mh, c)
    allt = [t for c in ALL22 for t in per_coin[c]]
    Rall = np.array([t[2] for t in allt])
    print(f"    toplam {len(allt)} islem, {len(ALL22)} coin  |  ort R {Rall.mean():+.4f}  "
          f"medyan R {np.median(Rall):+.3f}")

    # (a) ISARET TESTI — coin bazinda
    pos = sum(1 for c in ALL22 if len(per_coin[c]) and np.mean([t[2] for t in per_coin[c]]) > 0)
    p_coin = binom_two_sided(pos, len(ALL22))
    print(f"\n    (a) ISARET TESTI / coin : {pos}/{len(ALL22)} coin pozitif ort R  ->  iki yonlu binom p={p_coin:.4f}")
    # (a2) ISARET TESTI — coin x config hucresi (22 x 270)
    print(f"        (coin x config hucre taramasi asagida [3]'te)")

    # (b) HAVUZLANMIS ORTALAMA R + z
    print(f"    (b) HAVUZLANMIS         : ort R {Rall.mean():+.4f}  sd {Rall.std(ddof=1):.3f}  "
          f"n={len(Rall)}  z={zstat(Rall):+.2f}")

    # (c) YON AYRIMI
    RL = np.array([t[2] for t in allt if t[6] == 1]); RS = np.array([t[2] for t in allt if t[6] == -1])
    print(f"    (c) YON AYRIMI          : LONG  n={len(RL):4d} ort R {RL.mean():+.4f} z={zstat(RL):+.2f}  |  "
          f"SHORT n={len(RS):4d} ort R {RS.mean():+.4f} z={zstat(RS):+.2f}")
    dir_ok = (RL.mean() > 0) and (RS.mean() > 0)
    print(f"        -> {'IKI YON DE POZITIF (piyasa betasi degil)' if dir_ok else 'TEK TARAFLI -> BETA SUPHESI'}")

    # (d) DONEM AYRIMI
    tr_t, te_t = split_tt(allt)
    Rtr = np.array([t[2] for t in tr_t]); Rte = np.array([t[2] for t in te_t])
    print(f"    (d) DONEM AYRIMI        : TRAIN n={len(Rtr):4d} ort R {Rtr.mean():+.4f} z={zstat(Rtr):+.2f}  |  "
          f"TEST  n={len(Rte):4d} ort R {Rte.mean():+.4f} z={zstat(Rte):+.2f}")
    per_ok = (Rtr.mean() > 0) == (Rte.mean() > 0)
    print(f"        -> {'AYNI ISARET' if per_ok else 'ISARET DONUYOR -> GURULTU'}")

    # tutus suresi
    hold = [(pd.Timestamp(t[1]) - pd.Timestamp(t[0], tz='UTC')).days for t in allt]
    print(f"    ort tutus {np.mean(hold):.1f} gun (medyan {np.median(hold):.0f}, maks {np.max(hold)}) "
          f"— taban donchian 4h/mh30 tavani 5 gun")

    # ─────── [3] IZGARA: AILE GENELI + DOZ-YANIT ───────
    print(f"\n[3] IZGARA — {len(CH_GRID)}ch x {len(EMA_GRID)}ema x {len(SL_GRID)}sl x {len(RR_GRID)}rr "
          f"x {len(MH_GRID)}mh = {len(CH_GRID)*len(EMA_GRID)*len(SL_GRID)*len(RR_GRID)*len(MH_GRID)} "
          f"kombinasyon x 22 coin")
    combos = list(itertools.product(CH_GRID, EMA_GRID, SL_GRID, RR_GRID, MH_GRID))
    grid = {}
    for (c_, e_, s_, r_, m_) in combos:
        tl = []
        for cn in ALL22: tl += gen_daily(dcs[cn], c_, e_, s_, r_, m_, cn)
        grid[(c_, e_, s_, r_, m_)] = tl
    rows = []
    for k, tl in grid.items():
        R = np.array([t[2] for t in tl])
        a_tr, a_te = split_tt(tl)
        rtr = np.array([t[2] for t in a_tr]); rte = np.array([t[2] for t in a_te])
        rows.append(dict(ch=k[0], ema=k[1], sl=k[2], rr=k[3], mh=k[4], n=len(R),
                         mR=R.mean(), z=zstat(R),
                         mR_tr=rtr.mean() if len(rtr) else 0.0,
                         mR_te=rte.mean() if len(rte) else 0.0))
    G = pd.DataFrame(rows)
    npos = int((G.mR > 0).sum())
    print(f"    TUM DONEM  : {npos}/{len(G)} kombinasyon pozitif ort R  (binom p={binom_two_sided(npos,len(G)):.2e})")
    print(f"    TRAIN      : {int((G.mR_tr>0).sum())}/{len(G)} pozitif")
    ntepos = int((G.mR_te > 0).sum())
    print(f"    TEST (OOS) : {ntepos}/{len(G)} pozitif  <- ledger 259/270 (11 coin) demisti")
    print(f"    NOT: 270 kombinasyon BAGIMSIZ DEGIL (ayni islemleri paylasiyorlar) -> binom p")
    print(f"         burada asiri-iyimser. Bagimsiza en yakin isaret testi coin bazli olan (a).")

    # coin x config isaret testi (bagimsizliga daha yakin: 22 coin x 5 ch, digerleri REF)
    cells = []
    for c_ in CH_GRID:
        k = (c_, esp, sl_a, rr, mh)
        for cn in ALL22:
            rl = [t[2] for t in grid[k] if t[5] == cn]
            if len(rl) >= 5: cells.append(np.mean(rl))
    kk = sum(1 for v in cells if v > 0)
    print(f"    (a2) HUCRE ISARET TESTI (coin x ch, n>=5): {kk}/{len(cells)} pozitif  "
          f"iki yonlu binom p={binom_two_sided(kk,len(cells)):.4f}")

    print(f"\n    DOZ-YANIT (digerleri REF'te sabit):")
    for par, gr in (("ch", CH_GRID), ("mh", MH_GRID), ("rr", RR_GRID), ("sl", SL_GRID)):
        vals = []
        for v in gr:
            k = dict(zip(("ch", "ema", "sl", "rr", "mh"), REF)); k[par] = v
            kt = (k["ch"], k["ema"], k["sl"], k["rr"], k["mh"])
            R = np.array([t[2] for t in grid[kt]])
            vals.append((v, R.mean(), len(R)))
        mono = all(vals[i][1] <= vals[i+1][1] for i in range(len(vals)-1)) or \
               all(vals[i][1] >= vals[i+1][1] for i in range(len(vals)-1))
        s = "  ".join(f"{v}:{m:+.4f}(n{n})" for v, m, n in vals)
        print(f"      {par:3s} {s}   -> {'MONOTON' if mono else 'ZIKZAK'}")

    # ─────── [4] ANKORA EKLE ───────
    print(f"\n[4] ANKORA EKLEME — sleeve sirasi DONCH->SQZ->BB->DAILY, sembol-guard ACIK")
    dep12 = [c for c in DEPLOY if c in ALL22]
    sets = [(f"{len(dep12)} deploy coin (ledger tasarimi)", dep12),
            (f"{len(NONDEP)} NON-deploy coin (cakisma yok)", NONDEP),
            ("22 coin (hepsi)", ALL22)]
    print(f"    {'coin kumesi':<34s} {'n':>5s} {'toplam$':>9s} {'delta':>8s} {'maxDD%':>7s} "
          f"{'kotu-ay%':>9s} {'poz-ay%':>8s}  yil-yil delta")
    print(f"    {'ANKOR':<34s} {B['n']:>5d} {B['tot']:>+9.0f} {'—':>8s} {B['dd']:>7.1f} "
          f"{B['worst']:>9.1f} {B['posm']:>8.0f}")
    results = {}
    for lab, cs in sets:
        dl = [t for cn in cs for t in per_coin[cn]]
        comb = base + dl
        tk, rs, rsym = seat_select(comb, symguard=True)
        C = stats(tk)
        dsel = [t for t in tk if t[4] == "daily"]
        base_in = len(tk) - len(dsel)
        ydl = "  ".join(f"{y}:{C['yrs'].get(y,0)-B['yrs'].get(y,0):+.0f}" for y in sorted(B["yrs"]))
        print(f"    {lab:<34s} {C['n']:>5d} {C['tot']:>+9.0f} {C['tot']-B['tot']:>+8.0f} "
              f"{C['dd']:>7.1f} {C['worst']:>9.1f} {C['posm']:>8.0f}  {ydl}")
        results[lab] = dict(C=C, tk=tk, rs=rs, rsym=rsym, dsel=dsel, base_in=base_in,
                            dl=dl, cs=cs)

    # ─────── [5] KOLTUK ISGALI — SAYIYLA ───────
    print(f"\n[5] KOLTUK ISGALI (yeni kol yuzunden koltuk bulamayan MEVCUT sinyal sayisi)")
    print(f"    ankorda: {B['n']}/{len(base)} taban sinyali koltuk buldu (disarida {len(base)-B['n']})")
    for lab, cs in sets:
        r = results[lab]
        pushed = B["n"] - r["base_in"]
        # nedene gore ayristir
        rs_base = sum(1 for t in r["rs"] if t[4] != "daily")
        rsym_base = sum(1 for t in r["rsym"] if t[4] != "daily")
        print(f"    {lab:<34s} gunluk sinyal {len(r['dl']):>4d} -> koltuk bulan {len(r['dsel']):>3d}  |  "
              f"DISARI ITILEN TABAN ISLEMI: {pushed:>4d} ({pushed/B['n']*100:.1f}%)")
        print(f"      {'':<34s} taban redleri: koltuk-dolu {rs_base}, sembol-mesgul {rsym_base}")

    # doluluk: zamanin ne kadarinda 7 koltuk dolu (ankor vs birlesik)
    def occupancy(taken):
        ev = []
        for t in taken:
            ev.append((t[0], 1)); ev.append((pd.Timestamp(t[1]).value, -1))
        ev.sort()
        cur = 0; last = ev[0][0]; full = 0; tot = 0
        for ts, d_ in ev:
            if ts > last:
                if cur >= A.MAXPOS: full += ts - last
                tot += ts - last; last = ts
            cur += d_
        return full / tot * 100 if tot else 0.0
    print(f"\n    7 KOLTUGUN TAMAMI DOLU GECEN ZAMAN ORANI:")
    print(f"      ankor                              : %{occupancy(bt):.2f}")
    for lab, cs in sets:
        print(f"      +{lab:<33s}: %{occupancy(results[lab]['tk']):.2f}")

    # ─────── [6] KORELASYON ───────
    print(f"\n[6] KORELASYON — gunluk kolun AYLIK PnL'i vs mevcut portfoy")
    mb = B["mon"]
    for lab, cs in sets:
        dl = results[lab]["dl"]
        tk_solo, _, _ = seat_select(dl, symguard=True)
        S = stats(tk_solo)
        md = S["mon"]
        allm = sorted(set(mb.index) | set(md.index))
        x = mb.reindex(allm).fillna(0.0); y = md.reindex(allm).fillna(0.0)
        tm = [m for m in allm if m >= pd.Period("2025-01")]
        print(f"    {lab:<34s} tek-basina ${S['tot']:+.0f} (n{S['n']}) | Pearson {x.corr(y):+.3f} "
              f"Spearman {x.rank().corr(y.rank()):+.3f} | TEST-donemi {x.reindex(tm).corr(y.reindex(tm)):+.3f}")

    # ─────── [7] AILE GENELI BIRLESIK ETKI (secim artefakti testi) ───────
    print(f"\n[7] SECIM ARTEFAKTI TESTI — 270 KOMBINASYONUN HEPSI icin BIRLESIK ETKI")
    print(f"    (coin kumesi: 22 coin ve 10 non-deploy ayri ayri)")
    for lab, cs in (("22 coin", ALL22), ("10 non-deploy", NONDEP)):
        dtot = []; dworst = []; ddd = []
        for k, tl in grid.items():
            dl = [t for t in tl if t[5] in cs]
            tk, _, _ = seat_select(base + dl, symguard=True)
            C = stats(tk)
            dtot.append(C["tot"] - B["tot"]); dworst.append(C["worst"] - B["worst"])
            ddd.append(C["dd"] - B["dd"])
        dtot = np.array(dtot); dworst = np.array(dworst); ddd = np.array(ddd)
        print(f"    {lab:<15s} delta$: medyan {np.median(dtot):+7.0f}  en iyi {dtot.max():+7.0f}  "
              f"en kotu {dtot.min():+7.0f}  tabani gecen {(dtot>0).mean()*100:.0f}% "
              f"({int((dtot>0).sum())}/{len(dtot)})")
        print(f"    {'':<15s} en-kotu-ay delta: medyan {np.median(dworst):+.1f}pp  "
              f"IYILESEN {(dworst>=0).mean()*100:.0f}%  |  maxDD delta medyan {np.median(ddd):+.1f}pp  "
              f"|  HEM $+ HEM kotu-ay bozulmayan: {int(((dtot>28)&(dworst>=0)).sum())}/{len(dtot)}")

    # ─────── [8] ZAMAN DAMGASI DUYARLILIGI ───────
    print(f"\n[8] ZAMAN DAMGASI KONVANSIYONU DUYARLILIGI (eski daily_trend_test formu)")
    for lab, cs in sets:
        dl_old = []
        for cn in cs: dl_old += gen_daily(dcs[cn], ch, esp, sl_a, rr, mh, cn, shift_day=False)
        for sg in (True, False):
            tk, _, _ = seat_select(base + dl_old, symguard=sg)
            C = stats(tk)
            print(f"    {lab:<34s} kaydirmasiz, symguard={str(sg):5s}: ${C['tot']:+.0f} "
                  f"(delta {C['tot']-B['tot']:+.0f}) kotu-ay %{C['worst']:.1f}")

    # ─────── [9b] DOLAR MUHASEBESI: "koltuk-gunu" yerine DOGRUDAN FIRSAT MALIYETI ───────
    from collections import Counter
    print(f"\n[9b] DOGRUDAN FIRSAT MALIYETI (koltuk-gunu metrigi YERINE dolar muhasebesi)")
    def val(tl):
        if not tl: return 0.0
        r = np.array([t[2] for t in tl]); slp = np.array([t[3] for t in tl])
        return float((r * np.minimum(A.RISKF, A.CAP * slp) * A.BAL0).sum())
    anc = Counter(bt)
    print(f"    {'coin kumesi':<34s} {'itilen':>7s} {'itilenin $':>11s} {'yeni giren':>10s} "
          f"{'gunluk kol $':>12s} {'NET':>8s}")
    for lab, cs in sets:
        r = results[lab]
        cmb = Counter(t for t in r["tk"] if t[4] != "daily")
        lost = list((anc - cmb).elements())          # ankorda vardi, birlesikte yok
        gained = list((cmb - anc).elements())        # birlesikte var, ankorda yoktu
        dv = val(r["dsel"])
        print(f"    {lab:<34s} {len(lost):>7d} {val(lost):>+11.0f} {len(gained):>10d} "
              f"{dv:>+12.0f} {dv - val(lost) + val(gained):>+8.0f}")
    print(f"    (NET = gunluk kolun kattigi - itilen taban islemlerinin degeri + yeni girenler")
    print(f"     ~ [4]'teki delta ile tutmali. 'Koltuk-gunu' tartismasina gerek yok: itilen")
    print(f"     islemlerin R'si portfoyden BAGIMSIZ hesaplandi, dolayisiyla dogrudan olculur.)")
    print(f"\n    UST SINIR ARGUMANI: cikarma maliyeti TIMING'in deterministik sonucu. Kolun")
    print(f"    verebilecegi EN COK sey = tek-basina degeri (TUM sinyaller koltuk bulsa).")
    print(f"    {'coin kumesi':<34s} {'gereken(D>28)':>14s} {'TAVAN(tek-basina)':>18s} {'mumkun mu':>10s}")
    for lab, cs in sets:
        r = results[lab]
        cmb = Counter(t for t in r["tk"] if t[4] != "daily")
        need = val(list((anc - cmb).elements())) + 28.0
        solo, _, _ = seat_select(r["dl"], symguard=True)
        ceil = stats(solo)["tot"]
        print(f"    {lab:<34s} {need:>+14.0f} {ceil:>+18.0f} "
              f"{('cebirsel IMKANSIZ' if ceil < need else 'teorik mumkun'):>10s}")

    # ─────── [9c] DOZ-YANIT: KAC COINLIK GUNLUK KOL SIGAR? ───────
    print(f"\n[9c] DOZ-YANIT — gunluk kol kac coinde? (sira ALFABETIK = secim YOK)")
    print(f"    {'k':>3s} {'n':>5s} {'toplam$':>9s} {'delta':>7s} {'maxDD%':>7s} {'kotu-ay%':>9s} "
          f"{'itilen':>7s} {'dolu%':>6s}")
    for k in (1, 2, 3, 5, 8, 12, 16, 22):
        cs = ALL22[:k]
        dl = [t for cn in cs for t in per_coin[cn]]
        tk, _, _ = seat_select(base + dl, symguard=True)
        C = stats(tk)
        cmb = Counter(t for t in tk if t[4] != "daily")
        lost = list((anc - cmb).elements())
        print(f"    {k:>3d} {C['n']:>5d} {C['tot']:>+9.0f} {C['tot']-B['tot']:>+7.0f} {C['dd']:>7.1f} "
              f"{C['worst']:>9.1f} {len(lost):>7d} {occupancy(tk):>6.2f}")

    # ─────── [9d] BUTCE-NOTR + AYRI HAVUZ UST SINIRI ───────
    print(f"\n[9d] BUTCE-NOTR (ort dagitilan riski tabana esitle) + AYRI-HAVUZ UST SINIRI")
    def scaled_tot(tk, g):
        r = np.array([t[2] for t in tk]); slp = np.array([t[3] for t in tk])
        eff = np.minimum(A.RISKF * g, A.CAP * slp)
        return float(eff.mean()), float((r * eff * A.BAL0).sum())
    for lab, cs in sets:
        tk = results[lab]["tk"]
        lo_, hi_ = 1e-3, 5.0
        for _ in range(60):
            g = (lo_ + hi_) / 2
            if scaled_tot(tk, g)[0] > B["avg_risk"]: hi_ = g
            else: lo_ = g
        g = (lo_ + hi_) / 2; ar, tn = scaled_tot(tk, g)
        dl = results[lab]["dl"]
        solo, _, _ = seat_select(dl, symguard=True)
        S = stats(solo)
        print(f"    {lab:<34s} butce-notr g={g:.3f} ${tn:+.0f} (delta {tn-B['tot']:+.0f})  |  "
              f"AYRI HAVUZ (ikinci sermaye): ${B['tot']+S['tot']:+.0f} (+{S['tot']:.0f}, 2x sermaye gerek)")

    # ─────── [9] ON-KAYITLI BAR ───────
    print(f"\n[9] ON-KAYITLI BAR")
    print(f"    {'coin kumesi':<34s} {'D$>28':>7s} {'yil>-10%':>9s} {'maxDD<=+2':>10s} "
          f"{'kotu-ay':>9s} {'SONUC':>7s}")
    for lab, cs in sets:
        C = results[lab]["C"]
        c1 = (C["tot"] - B["tot"]) > 28
        c2 = all(C["yrs"].get(y, 0.0) >= B["yrs"][y] - abs(B["yrs"][y]) * 0.10 for y in B["yrs"])
        c3 = (C["dd"] - B["dd"]) <= 2.0
        c4 = C["worst"] >= B["worst"] - 1e-9
        res = "ADAY" if (c1 and c2 and c3 and c4) else "RET"
        print(f"    {lab:<34s} {('E' if c1 else 'H'):>7s} {('E' if c2 else 'H'):>9s} "
              f"{('E' if c3 else 'H'):>10s} {('E' if c4 else 'H'):>9s} {res:>7s}")
    print(f"    dort sahtelik testi: isaret p={p_coin:.4f} | havuz z={zstat(Rall):+.2f} | "
          f"yon {'AYNI' if dir_ok else 'FARKLI'} | donem {'AYNI' if per_ok else 'FARKLI'}")
    print(f"\n{'='*W}")


if __name__ == "__main__":
    main()
