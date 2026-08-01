"""
daily_trend_test.py — GÜNLÜK (1d) BARLARDA YAVAŞ TREND KOLU: gerçek bir çeşitlendirici mi?

NEDEN: kitaptaki her şey 1h/4h. horizon_sweep 4h'te kanal 20-120 taradı = 3-20 gün tutuş.
Gerçek CTA'lar HAFTALAR-AYLAR tutar ve getirilerinin çoğu az sayıda BÜYÜK trendden gelir.
Günlük bar hiç denenmedi. Bu mevcut sistemin varyasyonu DEĞİL — farklı bir zaman ölçeği,
farklı tutuş süresi → düşük korelasyon beklemek için YAPISAL sebep var.

TABAN = deployed_backtest.py'nin ürettiği TAM canlı config (donchian7 + squeeze4 + BB/LTC).
  n=1579 PF 1.45 WR %44 $+1421 | 2023:+321 2024:+457 2025:+447 2026:+195 | ort risk %2.13

METODOLOJİ (aşırı-uyum karşıtı):
  • occ = j (coin başına tek pozisyon), koltuk seçimi giriş zamanına göre MAXPOS=7,
    boyut eff = min(RISKF, CAP*sl_pct), pnl = R*eff*BAL0 — tabanla birebir aynı.
  • LOOKAHEAD YOK: kanal = ÖNCEKİ ch barın hi/lo'su (mevcut bar HARİÇ, rolling+shift(1)),
    EMA nedensel (ewm), giriş barın KAPANIŞINDA, çıkış taraması i+1'den başlar.
  • SEÇİM YALNIZ TRAIN'DEN: giriş≥veri başı VE çıkış < 2025-01-01. TEST: giriş ≥ 2025-01-01.
    Sınırı aşan (2024'te girip 2025'te çıkan) işlem HİÇBİR tarafa sayılmaz.
  • 270 kombinasyon taranıyor → argmax neredeyse kesin gürültü içerir. Bu yüzden karar
    argmax'a DEĞİL, (a) tüm ailenin TEST medyanına, (b) train→test sıra korelasyonuna,
    (c) plato varlığına bakılarak veriliyor.

Kullanım:  py daily_trend_test.py local
"""
import sys, os, heapq, pickle, itertools
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, ema as ema_fn

COINS = DB.DONCH + DB.SQZ                       # 11 deploy coini
CH_GRID = [20, 30, 50, 80, 100]
SL_GRID = [1.5, 2.0, 3.0]
RR_GRID = [2.0, 3.0, 4.0]
MH_GRID = [20, 40, 60]                          # GÜN
EMA_GRID = [100, 200]                           # günlük trend filtresi
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/base_trades.pkl"


# ───────────────────────── taban (canlı kitap) ─────────────────────────
def base_trades(source):
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f: return pickle.load(f)
    out = []
    for c in DB.DONCH:
        out += [(t[0], t[1], t[2], t[3], "donchian", c) for t in DB.gen("donchian", fast_bt.load(c, source=source))]
    for c in DB.SQZ:
        out += [(t[0], t[1], t[2], t[3], "squeeze", c) for t in DB.gen("squeeze", fast_bt.load(c, source=source))]
    for c in DB.BB_COINS:
        out += [(t[0], t[1], t[2], t[3], "bb", c) for t in DB.gen_bb(fast_bt.load(c, source=source))]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f: pickle.dump(out, f)
    return out


# ───────────────────────── günlük kol ─────────────────────────
def daily_cache(coin, source):
    """Coin başına günlük bar + göstergeler + (ch,ema) sinyal listeleri. BİR KEZ."""
    m = fast_bt.load(coin, source=source)
    d = fast_bt.resample(m, "1D")
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    n = len(cl)
    a = atr_fn(d["high"], d["low"], d["close"], 14).values
    emas = {e: ema_fn(d["close"], e).values for e in EMA_GRID}
    # kanal: ÖNCEKİ ch barın hi max / lo min — mevcut bar HARİÇ (lookahead yok)
    rh = {c: pd.Series(hi).rolling(c).max().shift(1).values for c in CH_GRID}
    rl = {c: pd.Series(lo).rolling(c).min().shift(1).values for c in CH_GRID}
    sig = {}
    for ch in CH_GRID:
        for esp in EMA_GRID:
            warm = max(esp, ch + 2)             # DonchianStrategy._min_bars ile aynı kural
            ev = emas[esp]; s = []
            for i in range(warm, n - 1):
                av = a[i]
                if not np.isfinite(av) or av <= 0: continue
                c_ = cl[i]; H = rh[ch][i]; L = rl[ch][i]
                if not (np.isfinite(H) and np.isfinite(L) and H > L): continue
                if c_ > H and c_ > ev[i]: s.append((i, 1))
                elif c_ < L and c_ < ev[i]: s.append((i, -1))
            sig[(ch, esp)] = s
    return dict(idx=d.index, hi=hi, lo=lo, cl=cl, atr=a, n=n, sig=sig)


def gen_daily(dc, ch, esp, sl_a, rr, mh, coin):
    """occ-farkında simülasyon. Sinyal listesi (ch,esp)'ye bağlı; sl/rr/mh yalnız
    çıkışı ve dolayısıyla occ'u değiştirir. Elenen sinyal occ'u İLERLETMEZ."""
    hi, lo, cl, a, n, idx = dc["hi"], dc["lo"], dc["cl"], dc["atr"], dc["n"], dc["idx"]
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
        R = d_ * (ep - e) / sld - 2 * DB.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, "daily", coin)); occ = j
    return out


# ───────────────────────── portföy mekaniği (tabanla birebir) ─────────────────────────
def seat_select(trades, maxpos=DB.MAXPOS):
    ev = sorted(trades, key=lambda t: t[0]); openh = []; taken = []; ctr = 0
    for tr in ev:
        entry_ns, exit_ts = tr[0], tr[1]
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, 0.0)); taken.append(tr)
    return taken


def stats(taken):
    if not taken: return dict(n=0, tot=0.0, pf=0.0, wr=0.0, avg_risk=0.0, yrs={}, dd=0.0, mon=pd.Series(dtype=float))
    tk = sorted(taken, key=lambda t: t[1])
    r = np.array([t[2] for t in tk]); slp = np.array([t[3] for t in tk])
    ex = [pd.Timestamp(t[1]) for t in tk]
    eff = np.minimum(DB.RISKF, DB.CAP * slp)
    pnl = r * eff * DB.BAL0
    eq = np.concatenate([[DB.BAL0], DB.BAL0 + np.cumsum(pnl)])
    peak = np.maximum.accumulate(eq)
    ya = np.array([x.year for x in ex])
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum()
    return dict(n=len(r), tot=float(pnl.sum()), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100,
                avg_risk=float(eff.mean()), dd=float(((peak - eq) / peak).max() * 100),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))},
                mon=mon, R=r, pnl=pnl)


def split(trades):
    """TRAIN: giriş VE çıkış < 2025-01-01.  TEST: giriş >= 2025-01-01.  Sınırı aşan atılır."""
    tr = [t for t in trades if pd.Timestamp(t[1]) < SPLIT]
    te = [t for t in trades if t[0] >= SPLIT.value]
    return tr, te


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    W = 112
    print(f"\n{'='*W}\n=== GÖREV B — GÜNLÜK (1d) YAVAŞ TREND KOLU ===")

    # 1) TABAN
    base_all = base_trades(source)
    base_taken = seat_select(base_all)
    B = stats(base_taken)
    print(f"\n  [1] TABAN DOĞRULAMA (deployed_backtest tam canlı config)")
    print(f"      n={B['n']} PF {B['pf']:.2f} WR %{B['wr']:.0f} ${B['tot']:+.0f} "
          f"maxDD %{B['dd']:.1f} ort risk %{B['avg_risk']*100:.2f}")
    print(f"      yıl-yıl: " + "  ".join(f"{y}:${v:+.0f}" for y, v in B["yrs"].items()))
    ok = (B["n"] == 1579 and abs(B["tot"] - 1421) < 2 and abs(B["pf"] - 1.45) < 0.01)
    print(f"      → beklenen n=1579 / $+1421 / PF1.45 ile {'EŞLEŞTİ' if ok else 'EŞLEŞMEDİ (DUR!)'}")
    if not ok: sys.exit(1)
    b_tr, b_te = split(base_all)
    BTR = stats(seat_select(b_tr)); BTE = stats(seat_select(b_te))
    print(f"      TABAN TRAIN(→2024-12): n={BTR['n']} ${BTR['tot']:+.0f} | "
          f"TEST(2025-01→): n={BTE['n']} ${BTE['tot']:+.0f}")

    # 2) günlük veri + sinyaller
    print(f"\n  [2] GÜNLÜK BARLAR HAZIRLANIYOR ({len(COINS)} coin)...")
    dcs = {c: daily_cache(c, source) for c in COINS}
    d0 = dcs[COINS[0]]
    print(f"      {d0['n']} günlük bar  {d0['idx'][0].date()} → {d0['idx'][-1].date()}")
    for esp in EMA_GRID:
        w = max(esp, 3)
        print(f"      EMA{esp} ısınma → ilk olası sinyal ~{d0['idx'][w].date()} "
              f"(TRAIN'de {(SPLIT - d0['idx'][w]).days} gün kalıyor)")

    # 3) TARAMA — SEÇİM YALNIZ TRAIN'DEN
    combos = list(itertools.product(CH_GRID, EMA_GRID, SL_GRID, RR_GRID, MH_GRID))
    print(f"\n  [3] TARAMA: {len(CH_GRID)}ch x {len(EMA_GRID)}ema x {len(SL_GRID)}sl x "
          f"{len(RR_GRID)}rr x {len(MH_GRID)}mh = {len(combos)} KOMBİNASYON")
    rows = []
    for (ch, esp, sl_a, rr, mh) in combos:
        tr_all = []
        for c in COINS: tr_all += gen_daily(dcs[c], ch, esp, sl_a, rr, mh, c)
        a_tr, a_te = split(tr_all)
        s_tr = stats(seat_select(a_tr)); s_te = stats(seat_select(a_te))
        s_all = stats(seat_select(tr_all))
        rows.append(dict(ch=ch, ema=esp, sl=sl_a, rr=rr, mh=mh,
                         n_tr=s_tr["n"], tot_tr=s_tr["tot"], pf_tr=s_tr["pf"],
                         n_te=s_te["n"], tot_te=s_te["tot"], pf_te=s_te["pf"],
                         n_all=s_all["n"], tot_all=s_all["tot"], trades=tr_all))
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "trades"} for r in rows])

    print(f"\n      --- TÜM AİLENİN DAĞILIMI (argmax DEĞİL — asıl kanıt bu) ---")
    for lab, col, ncol in (("TRAIN", "tot_tr", "n_tr"), ("TEST", "tot_te", "n_te")):
        v = df[col]
        print(f"      {lab:5s}: medyan ${v.median():+7.1f} | ort ${v.mean():+7.1f} | "
              f"pozitif {(v>0).mean()*100:3.0f}% | min ${v.min():+.0f} max ${v.max():+.0f} | "
              f"medyan n={df[ncol].median():.0f}")
    sp = df["tot_tr"].rank().corr(df["tot_te"].rank())      # Spearman (scipy yok)
    pe = df["tot_tr"].corr(df["tot_te"])
    print(f"      TRAIN→TEST sıra korelasyonu (Spearman) {sp:+.3f} | Pearson {pe:+.3f}")
    print(f"      (≈0 ise: TRAIN'de iyi olmak TEST'i ÖNGÖRMÜYOR → seçim işlemi anlamsız)")

    print(f"\n      --- TRAIN'DE EN İYİ 10 (seçim buradan; TEST sütunu SEÇİMDE KULLANILMADI) ---")
    print(f"      {'ch':>4s} {'ema':>4s} {'sl':>4s} {'rr':>4s} {'mh':>3s} | "
          f"{'n_tr':>5s} {'TRAIN$':>8s} {'PFtr':>5s} | {'n_te':>5s} {'TEST$':>8s} {'PFte':>5s}")
    top = df.sort_values("tot_tr", ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"      {r.ch:>4.0f} {r.ema:>4.0f} {r.sl:>4.1f} {r.rr:>4.1f} {r.mh:>3.0f} | "
              f"{r.n_tr:>5.0f} {r.tot_tr:>+8.1f} {r.pf_tr:>5.2f} | "
              f"{r.n_te:>5.0f} {r.tot_te:>+8.1f} {r.pf_te:>5.2f}")

    best = df.sort_values("tot_tr", ascending=False).iloc[0]
    bkey = (int(best.ch), int(best.ema), float(best.sl), float(best.rr), int(best.mh))
    print(f"\n      SEÇİLEN (train argmax): ch{bkey[0]} EMA{bkey[1]} SL{bkey[2]}xATR "
          f"rr{bkey[3]} mh{bkey[4]}g")

    # 4) PLATO ANALİZİ
    print(f"\n  [4] PLATO ANALİZİ — komşular da iyi mi, yoksa tek nokta mı?")
    grids = dict(ch=CH_GRID, ema=EMA_GRID, sl=SL_GRID, rr=RR_GRID, mh=MH_GRID)
    bd = dict(ch=bkey[0], ema=bkey[1], sl=bkey[2], rr=bkey[3], mh=bkey[4])
    q75 = df["tot_tr"].quantile(0.75)
    nb = []
    for p, g in grids.items():
        k = g.index(bd[p])
        for kk in (k - 1, k + 1):
            if 0 <= kk < len(g):
                q = dict(bd); q[p] = g[kk]
                row = df[(df.ch == q["ch"]) & (df.ema == q["ema"]) & (df.sl == q["sl"]) &
                         (df.rr == q["rr"]) & (df.mh == q["mh"])].iloc[0]
                nb.append((f"{p}={g[kk]}", row.tot_tr, row.tot_te))
    print(f"      {'komşu':<10s} {'TRAIN$':>9s} {'TEST$':>9s}   (seçilen: TRAIN "
          f"${best.tot_tr:+.1f} / TEST ${best.tot_te:+.1f}; TRAIN 75.persentil ${q75:+.1f})")
    for nm, a_, b_ in nb:
        print(f"      {nm:<10s} {a_:>+9.1f} {b_:>+9.1f}  {'üst-çeyrek' if a_ >= q75 else 'ZAYIF'}")
    good = sum(1 for _, a_, _ in nb if a_ >= q75)
    print(f"      → {good}/{len(nb)} komşu TRAIN üst-çeyrekte. "
          f"{'PLATO var' if good >= 0.7*len(nb) else 'TEK NOKTA / kırık plato = GÜRÜLTÜ şüphesi'}")
    print(f"      → komşuların TEST medyanı ${np.median([b_ for _,_,b_ in nb]):+.1f}")

    # 5) SEÇİLEN KOLUN TEK BAŞINA TEST ÖLÇÜMÜ + bootstrap
    sel = next(r for r in rows if (r["ch"], r["ema"], r["sl"], r["rr"], r["mh"]) == bkey)
    s_all = stats(seat_select(sel["trades"]))
    a_tr, a_te = split(sel["trades"])
    s_te = stats(seat_select(a_te))
    print(f"\n  [5] SEÇİLEN GÜNLÜK KOL — TEK BAŞINA")
    print(f"      TÜM DÖNEM : n={s_all['n']} PF {s_all['pf']:.2f} WR %{s_all['wr']:.0f} "
          f"${s_all['tot']:+.0f} ort risk %{s_all['avg_risk']*100:.2f}")
    print(f"      yıl-yıl   : " + "  ".join(f"{y}:${v:+.0f}" for y, v in s_all["yrs"].items()))
    print(f"      TEST(OOS) : n={s_te['n']} PF {s_te['pf']:.2f} WR %{s_te['wr']:.0f} ${s_te['tot']:+.0f}")
    hold = [(pd.Timestamp(t[1]) - pd.Timestamp(t[0], tz="UTC")).days
            for t in seat_select(sel["trades"])]
    print(f"      ort tutuş : {np.mean(hold):.1f} gün (medyan {np.median(hold):.0f}, "
          f"maks {np.max(hold):.0f}) — taban donchian 4h/mh30 = 5 gün tavan")
    rr_ = s_all["R"]
    if len(rr_):
        big = np.sort(rr_)[-max(1, len(rr_)//10):]
        print(f"      kârın kaynağı: en iyi %10 işlem toplam +{big.sum():.1f}R / "
              f"tüm toplam {rr_.sum():+.1f}R  (CTA imzası: az sayıda büyük trend)")
    rng = np.random.default_rng(7)
    for lab, arr in (("TÜM DÖNEM", s_all), ("TEST", s_te)):
        if arr["n"] < 5: continue
        p = arr["pnl"]
        bs = np.array([p[rng.integers(0, len(p), len(p))].sum() for _ in range(10000)])
        print(f"      bootstrap {lab:9s} (n={len(p)}): ${arr['tot']:+.0f} | "
              f"%95 GA [${np.percentile(bs,2.5):+.0f}, ${np.percentile(bs,97.5):+.0f}] | "
              f"P(toplam>0)={np.mean(bs>0)*100:.0f}%")

    # 6) KORELASYON
    print(f"\n  [6] MEVCUT KİTAPLA AYLIK KORELASYON")
    mb = B["mon"]; md = s_all["mon"]
    allm = sorted(set(mb.index) | set(md.index))
    x = mb.reindex(allm).fillna(0.0); y = md.reindex(allm).fillna(0.0)
    print(f"      tüm dönem ({len(allm)} ay): Pearson {x.corr(y):+.3f} | "
          f"Spearman {x.rank().corr(y.rank()):+.3f}")
    tm = [m for m in allm if m >= pd.Period("2025-01")]
    print(f"      TEST dönemi ({len(tm)} ay): Pearson {x.reindex(tm).corr(y.reindex(tm)):+.3f}")
    print(f"      → hedef <+0.30. Günlük kolun aylarının %{(y!=0).mean()*100:.0f}'inde işlem var.")

    # 7) BİRLEŞİK PORTFÖY — AYNI 7 KOLTUK
    print(f"\n  [7] BİRLEŞİK PORTFÖY (taban + günlük kol, AYNI 7 koltuk havuzu)")
    comb = base_all + sel["trades"]
    C = stats(seat_select(comb))
    c_tr, c_te = split(comb)
    CTE = stats(seat_select(c_te))
    print(f"      {'':<10s} {'n':>5s} {'toplam$':>9s} {'Δ':>8s} {'PF':>5s} {'maxDD%':>7s} {'ort risk':>9s}")
    print(f"      {'TABAN':<10s} {B['n']:>5d} {B['tot']:>+9.0f} {'—':>8s} {B['pf']:>5.2f} "
          f"{B['dd']:>7.1f} {B['avg_risk']*100:>8.2f}%")
    print(f"      {'BİRLEŞİK':<10s} {C['n']:>5d} {C['tot']:>+9.0f} {C['tot']-B['tot']:>+8.0f} "
          f"{C['pf']:>5.2f} {C['dd']:>7.1f} {C['avg_risk']*100:>8.2f}%")
    print(f"      yıl-yıl:")
    for y in sorted(set(B["yrs"]) | set(C["yrs"])):
        bv = B["yrs"].get(y, 0.0); cv = C["yrs"].get(y, 0.0)
        print(f"        {y}: taban ${bv:+7.0f} → birleşik ${cv:+7.0f}  Δ{cv-bv:+7.0f}  "
              f"{'✓' if cv > bv else '✗'}")
    every = all(C["yrs"].get(y, 0.0) > B["yrs"].get(y, 0.0) for y in B["yrs"])
    print(f"      TEST dilimi: taban ${BTE['tot']:+.0f} → birleşik ${CTE['tot']:+.0f} "
          f"(Δ{CTE['tot']-BTE['tot']:+.0f})")
    # kaç günlük işlem koltuk buldu / kaç taban işlemi dışlandı
    dsel = [t for t in seat_select(comb) if t[4] == "daily"]
    print(f"      günlük sinyal {len(sel['trades'])} → koltuk bulan {len(dsel)}; "
          f"taban işlemlerinden dışlanan: {B['n'] - (C['n']-len(dsel))}")
    print(f"      KALDIRAÇ KONTROLÜ: ort dağıtılan risk %{B['avg_risk']*100:.3f} → "
          f"%{C['avg_risk']*100:.3f} ({'ARTTI' if C['avg_risk']>B['avg_risk']+1e-6 else 'aynı/düştü'})")
    print(f"        (günlük kol notional tavanına HİÇ takılmıyor → her işlemi tam %2.25 alıyor;")
    print(f"         tek-başına ${s_all['tot']:+.0f} rakamı bu yüzden tabanın %2.13'üne göre ~%6 şişik)")

    # 7b) bütçe-nötr: tüm kitabı g ile ölçekle, ort dağıtılan riski tabana eşitle
    def scaled(taken, g):
        r = np.array([t[2] for t in taken]); slp = np.array([t[3] for t in taken])
        ex = [pd.Timestamp(t[1]) for t in taken]
        eff = np.minimum(DB.RISKF * g, DB.CAP * slp); pnl = r * eff * DB.BAL0
        ya = np.array([x.year for x in ex])
        return eff.mean(), pnl.sum(), {int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))}
    ct = seat_select(comb)
    lo_, hi_ = 1e-3, 5.0
    for _ in range(60):
        g = (lo_ + hi_) / 2
        if scaled(ct, g)[0] > B["avg_risk"]: hi_ = g
        else: lo_ = g
    g = (lo_ + hi_) / 2; ar, tot_n, yrs_n = scaled(ct, g)
    print(f"      BÜTÇE-NÖTR (g={g:.3f}, ort risk %{ar*100:.2f} = tabanla aynı): "
          f"${tot_n:+.0f} (Δ{tot_n-B['tot']:+.0f})")
    everyn = all(yrs_n.get(y, 0.0) > B["yrs"].get(y, 0.0) for y in B["yrs"])
    print(f"        yıl-yıl: " + "  ".join(f"{y}:{yrs_n.get(y,0)-B['yrs'].get(y,0):+.0f}" for y in sorted(B["yrs"])))

    # 7c) KOLTUK FIRSAT MALİYETİ — birleşik neden kaybediyor?
    print(f"\n  [7c] KOLTUK EKONOMİSİ (birleşiğin neden kaybettiğinin ölçüsü)")
    def seatday(taken, lab):
        r = np.array([t[2] for t in taken]); slp = np.array([t[3] for t in taken])
        pnl = r * np.minimum(DB.RISKF, DB.CAP * slp) * DB.BAL0
        days = np.array([max((pd.Timestamp(t[1]) - pd.Timestamp(t[0], tz="UTC")).total_seconds()
                             / 86400, 1/24) for t in taken])
        print(f"      {lab:<22s} n={len(taken):>5d}  ort tutuş {days.mean():>5.2f} gün  "
              f"işlem başı ${pnl.mean():>+6.2f}  →  KOLTUK-GÜNÜ başına ${pnl.sum()/days.sum():>+6.2f}")
        return pnl.sum() / days.sum()
    e_b = seatday(base_taken, "taban (tüm kitap)")
    for sv in ("donchian", "squeeze", "bb"):
        seatday([t for t in base_taken if t[4] == sv], f"  taban/{sv}")
    e_d = seatday(seat_select(sel["trades"]), "günlük kol")
    print(f"      → günlük kol koltuk-günü verimi tabanın {e_d/e_b:.2f}x'i. 7 koltuk KIT bir")
    print(f"        kaynak; 23.6 gün koltuk tutan bir işlem, yerine girecek ~15 taban işlemini")
    print(f"        engelliyor. Tek başına iyi olması YETMİYOR — koltuk-günü verimi belirleyici.")

    # 7d) TÜM AİLE için birleşik etki — seçim artefaktı mı, yoksa hiçbir parametre işe yaramıyor mu?
    print(f"\n  [7d] 270 KOMBİNASYONUN HEPSİ için BİRLEŞİK ETKİ (seçim artefaktı testi)")
    dl_tr, dl_te, dl_all = [], [], []
    for r in rows:
        cc = base_all + r["trades"]
        ct_ = seat_select(cc); c_tr_, c_te_ = split(cc)
        dl_all.append(stats(ct_)["tot"] - B["tot"])
        dl_tr.append(stats(seat_select(c_tr_))["tot"] - BTR["tot"])
        dl_te.append(stats(seat_select(c_te_))["tot"] - BTE["tot"])
    for lab, v in (("TRAIN Δ", dl_tr), ("TEST  Δ", dl_te), ("TÜM   Δ", dl_all)):
        v = np.array(v)
        print(f"      {lab}: medyan ${np.median(v):+7.1f} | en iyi ${v.max():+7.1f} | "
              f"en kötü ${v.min():+7.1f} | tabanı geçen {(v>0).mean()*100:3.0f}% "
              f"({int((v>0).sum())}/{len(v)})")
    bi = int(np.argmax(dl_tr))
    br = rows[bi]
    print(f"      TRAIN'de birleşiği en çok artıran kombinasyon: ch{br['ch']} EMA{br['ema']} "
          f"SL{br['sl']} rr{br['rr']} mh{br['mh']} → TRAIN Δ${dl_tr[bi]:+.1f}, TEST Δ${dl_te[bi]:+.1f}")
    print(f"      (bu İKİNCİ bir seçim hedefi — ilk hedef başarısız olduktan sonra bakıldı, yani")
    print(f"       çoklu-karşılaştırma yükünü daha da artırıyor; ancak SONUÇ negatifse soru kapanır)")

    # 7e) BÜTÇE-NÖTR HAVUZ GENİŞLETME: 9 koltuk ama risk x7/9 → eşzamanlı maruziyet SABİT
    print(f"\n  [7e] 'Koltuk sıkışıksa havuzu büyütelim' — BÜTÇE-NÖTR form (MAXPOS 9, risk x7/9)")
    def eval_pool(trades, mp, gmul):
        tk = seat_select(trades, maxpos=mp)
        r = np.array([t[2] for t in tk]); slp = np.array([t[3] for t in tk])
        ex = [pd.Timestamp(t[1]) for t in tk]
        eff = np.minimum(DB.RISKF * gmul, DB.CAP * slp); pnl = r * eff * DB.BAL0
        ya = np.array([x.year for x in ex])
        return (len(tk), float(pnl.sum()),
                {int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})
    for mp, gm, lab in ((7, 1.0, "taban 7 koltuk"), (9, 7/9, "birleşik 9 koltuk x7/9"),
                        (9, 1.0, "birleşik 9 koltuk x1.0 (KALDIRAÇLI, kıyas değil)")):
        src = base_all if mp == 7 else base_all + sel["trades"]
        n_, t_, y_ = eval_pool(src, mp, gm)
        ys_ = " ".join(f"{k}:{v:+.0f}" for k, v in y_.items())
        print(f"      {lab:<44s} n={n_:>5d} ${t_:>+7.0f} ({t_-B['tot']:+6.0f})  {ys_}")

    # 8) KARAR
    print(f"\n  [8] KABUL BARI")
    c1 = s_te["tot"] > 0
    c2 = C["tot"] > B["tot"]
    c3 = every
    c4 = tot_n > B["tot"] and everyn
    print(f"      (a) seçilen kol TEST'te pozitif ................ {'EVET' if c1 else 'HAYIR'} (${s_te['tot']:+.0f})")
    print(f"      (b) birleşik toplam tabanı geçiyor ............. {'EVET' if c2 else 'HAYIR'} ({C['tot']-B['tot']:+.0f})")
    print(f"      (c) birleşik HER YIL tabanı geçiyor ........... {'EVET' if c3 else 'HAYIR'}")
    print(f"      (d) bütçe-nötr formda da geçiyor (kaldıraç değil) {'EVET' if c4 else 'HAYIR'}")
    print(f"      SONUÇ: {'★ ADAY' if (c1 and c2 and c3 and c4) else 'RET'}")
    print(f"\n{'='*W}")


if __name__ == "__main__":
    main()
