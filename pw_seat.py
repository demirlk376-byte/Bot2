"""
pw_seat.py — KOLTUK TAHSIS KURALI: bagliyici mi, ve kime verilmeli?

SORU: seat_select su an ILK GELEN ALIR (deployed_backtest.py:126, stabil sort ->
esit entry_ns'te liste sirasi = DONCH coinleri, sonra SQZ, sonra BB). Es zamanli
sinyaller kalite bakimindan farkliysa koltugu daha iyisine vermek bedava para olur.

YONTEM (ONCE OLC, SONRA DENE):
 ASAMA 0 — HAVUZ: A.gen / A.gen_bb ile BIREBIR ayni aday havuzu + her isleme meta
   (coin, sleeve, yon, ADX, gunluk trend hizasi, sl_pct). Core dortlu (entry_ns,
   exit_ts, R, sl_pct) A.gen'in ciktisiyla BIREBIR karsilastirilarak dogrulaniyor.
 ASAMA 1 — BAGLIYICILIK: zaman-agirlikli doluluk dagilimi, kac sinyal koltuk
   bulamadi, onlarin GERCEK R'si ve dolar karsiligi (firsat maliyeti tavani).
   ASIL SAYI: "karar noktasi" = ayni entry_ns'te gelen aday sayisi > bos koltuk.
   Baska her anda ILK GELEN ALIR zaten TEK nedensel kuraldir (bir sonraki sinyali
   gormeden koltuk saklamak lookahead'dir). Karar noktasi yoksa TAVAN SIFIR.
 ASAMA 2 — KURALLAR (yalniz bagliyicilik anlamliysa): ayni entry_ns grubunda
   siralamayi degistir. Adaylar: dar/genis stop, gecmis PF (NEDENSEL, genisleyen
   pencere), gunluk trend hizasi, ADX, sleeve onceligi, RASTGELE (kontrol, 300
   tohum), ORACLE / ANTI-ORACLE (gelecegi bilen ust/alt sinir).
 ASAMA 3 — DOZ-YANIT: MAX_POSITIONS 3..12. Kural gercekse koltuk kitlastikca
   avantaji MONOTON buyumeli.
 ASAMA 4 — SAHTELIK: (a) isaret testi karar noktasi bazinda binom, (b) havuzlanmis
   ort R farki + z, (c) yon ayrimi (long/short), (d) donem ayrimi (TRAIN/TEST).

Kullanim:  py pw_seat.py local
"""
import sys, os, heapq, math, pickle
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn

CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/pw_seat_pool.pkl"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")   # veri tz-aware UTC
NSEED = 300


# ─────────────────────────────────────────────────────────────────────────────
# ASAMA 0 — HAVUZ (A.gen'in META'li kopyasi; core dortlu birebir dogrulanir)
# ─────────────────────────────────────────────────────────────────────────────
def gen_meta(sleeve, coin, m):
    """A.gen ile SATIR SATIR ayni; ek olarak meta doner.
    Ek alanlar hicbir kontrol akisini degistirmez (yalniz kayit)."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (A.DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         A.SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
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
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        # META (karar akisina dokunmaz)
        dp = _dprev[i]
        trend = float(d_ * (e - dp) / a) if np.isfinite(dp) else 0.0   # ATR biriminde hizali mesafe
        adxv = float(adx_ser[i]) if np.isfinite(adx_ser[i]) else 20.0
        out.append(dict(entry_ns=idx[i].value, exit_ts=idx[j], R=float(R), slp=sld / e,
                        coin=coin, sleeve=sleeve, dirn=int(d_), adx=adxv, trend=trend,
                        bars=int(j - i), entry_ts=idx[i]))
        occ = j
    return out


def gen_bb_meta(coin, m):
    """A.gen_bb ile SATIR SATIR ayni + meta."""
    from indicators import bollinger_bands
    from strategies.mean_reversion import MeanReversionStrategy
    from config import load_config
    s = MeanReversionStrategy(load_config().strategy)
    d = fast_bt.resample(m, A.BB_TF)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    out = []; occ = -1
    for i in np.where(outside & volok)[0]:
        i = int(i)
        if i < 260 or i >= n - 1 or i <= occ: continue
        if idx[i].weekday() < 5: continue
        sub = d.iloc[max(0, i - 119):i + 1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0: continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        adxv = float(adxr) if np.isfinite(adxr) else 20.0
        if adxv >= A.BB_ADX_MAX: continue
        d_ = s.analyze(sub).direction
        if d_ == 0: continue
        a = float(av); sld = A.BB_SL_ATR * a
        e = cl[i]; slp = e - d_ * sld; tp = e + d_ * A.BB_RR * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + A.BB_MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + A.BB_MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        dp = _dprev[i]
        trend = float(d_ * (e - dp) / a) if np.isfinite(dp) else 0.0
        out.append(dict(entry_ns=idx[i].value, exit_ts=idx[j], R=float(R), slp=sld / e,
                        coin=coin, sleeve="bb", dirn=int(d_), adx=adxv, trend=trend,
                        bars=int(j - i), entry_ts=idx[i]))
        occ = j
    return out


def build_pool(source, verify=True):
    """Havuzu kur; A.gen ile BIREBIR dogrula. Sira DONCH->SQZ->BB (kritik)."""
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            pool = pickle.load(f)
        print(f"  havuz onbellekten: {len(pool)} aday sinyal")
        return pool
    pool = []
    for c in A.DONCH:
        m = fast_bt.load(c, source=source)
        mine = gen_meta("donchian", c, m)
        if verify:
            ref = A.gen("donchian", m)
            got = [(t["entry_ns"], t["exit_ts"], t["R"], t["slp"]) for t in mine]
            assert got == ref, f"{c} donchian: gen_meta != A.gen ({len(got)} vs {len(ref)})"
        pool += mine
    for c in A.SQZ:
        m = fast_bt.load(c, source=source)
        mine = gen_meta("squeeze", c, m)
        if verify:
            ref = A.gen("squeeze", m)
            got = [(t["entry_ns"], t["exit_ts"], t["R"], t["slp"]) for t in mine]
            assert got == ref, f"{c} squeeze: gen_meta != A.gen"
        pool += mine
    for c in A.BB_COINS:
        m = fast_bt.load(c, source=source)
        mine = gen_bb_meta(c, m)
        if verify:
            ref = A.gen_bb(m)
            got = [(t["entry_ns"], t["exit_ts"], t["R"], t["slp"]) for t in mine]
            assert got == ref, f"{c} bb: gen_bb_meta != A.gen_bb"
        pool += mine
    print(f"  havuz kuruldu ve A.gen ile BIREBIR dogrulandi: {len(pool)} aday sinyal")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(pool, f)
    return pool


# ─────────────────────────────────────────────────────────────────────────────
# KOLTUK MOTORU
# ─────────────────────────────────────────────────────────────────────────────
def seat_run(pool, prio=None, maxpos=None, trace=False):
    """A.seat_select ile ayni semantik. prio=None -> ILK GELEN ALIR (liste sirasi
    stabil sort ile korunur = ankor). prio(t)->float verilirse ayni entry_ns
    grubunda kucuk deger ONCE gelir (yalniz TIE kirilimi degisir; farkli
    entry_ns'lerin sirasi ASLA degismez)."""
    mp = A.MAXPOS if maxpos is None else maxpos
    if prio is None:
        ev = sorted(range(len(pool)), key=lambda k: pool[k]["entry_ns"])
    else:
        ev = sorted(range(len(pool)), key=lambda k: (pool[k]["entry_ns"], prio(pool[k]), k))
    openh = []; taken = []; rejected = []; ctr = 0
    decisions = []          # her ayri entry_ns ani: bos koltuk + o anda gelen adaylar
    cur_ns = None; batch = None
    for k in ev:
        t = pool[k]; entry_ns = t["entry_ns"]
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if trace and entry_ns != cur_ns:
            if batch is not None: decisions.append(batch)
            batch = dict(ns=entry_ns, free=mp - len(openh), cands=[], sel=[]); cur_ns = entry_ns
        if trace:
            batch["cands"].append(t)
        if len(openh) < mp:
            ctr += 1; heapq.heappush(openh, (t["exit_ts"], ctr, t["R"])); taken.append(t)
            if trace: batch["sel"].append(t)
        else:
            rejected.append(t)
    if trace and batch is not None: decisions.append(batch)
    taken = sorted(taken, key=lambda t: t["exit_ts"])
    return (taken, rejected, decisions) if trace else (taken, rejected)


def metrics(taken):
    """A.main ile ayni dolar/risk modeli."""
    r = np.array([t["R"] for t in taken])
    exits = [pd.Timestamp(t["exit_ts"]) for t in taken]
    slp = np.array([t["slp"] for t in taken])
    eff = np.minimum(A.RISKF, A.CAP * slp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    dd = A.maxdd(np.concatenate([[A.BAL0], eq]))
    mon = (pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in exits])
           .groupby(level=0).sum() / A.BAL0 * 100)
    yr = {}
    ys = np.array([pd.Timestamp(x).year for x in exits])
    for y in sorted(set(ys)): yr[int(y)] = float(pnl[ys == y].sum())
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    bars = np.array([t["bars"] for t in taken])
    return dict(n=len(taken), tot=float(pnl.sum()), dd=float(dd), worst=float(mon.min()),
                posm=float((mon > 0).mean() * 100), pf=float(gp / max(gl, 1e-9)),
                meanR=float(r.mean()), rbar=float(r.sum() / bars.sum()), yr=yr)


def fmt(tag, m, base=None):
    d = "" if base is None else f"  Δ${m['tot']-base['tot']:+7.0f}"
    ys = " ".join(f"{y}:{v:+5.0f}" for y, v in sorted(m["yr"].items()))
    return (f"  {tag:<26s} n{m['n']:<5d} ${m['tot']:+7.0f}{d}  DD{m['dd']:5.1f}%  "
            f"kotuAy{m['worst']:+6.1f}  PF{m['pf']:.2f}  R/bar{m['rbar']:+.4f}  | {ys}")


# ─────────────────────────────────────────────────────────────────────────────
# NEDENSEL GECMIS PF (genisleyen pencere; yalniz entry'den ONCE KAPANMIS islemler)
# ─────────────────────────────────────────────────────────────────────────────
def build_hist_pf(pool, minn=20):
    """Her aday icin: ayni coin+sleeve'in o ANA kadar KAPANMIS sinyallerinin PF'i.
    Lookahead yok (exit_ts <= entry_ts sarti). minn'den az ornek varsa notr (=1.0)."""
    out = {}
    by = {}
    for i, t in enumerate(pool): by.setdefault((t["coin"], t["sleeve"]), []).append(i)
    for key, idxs in by.items():
        idxs = sorted(idxs, key=lambda i: pool[i]["entry_ns"])
        closed = sorted(idxs, key=lambda i: pool[i]["exit_ts"])
        gp = gl = 0.0; nn = 0; p = 0
        for i in idxs:
            ets = pool[i]["entry_ts"]
            while p < len(closed) and pool[closed[p]]["exit_ts"] <= ets:
                R = pool[closed[p]]["R"]
                if R > 0: gp += R
                else: gl += -R
                nn += 1; p += 1
            out[i] = (gp / gl) if (nn >= minn and gl > 0) else 1.0
    return out


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    pool = build_pool(source)
    for i, t in enumerate(pool): t["i"] = i      # havuz sirasi = ankorun stabil-sort sirasi
    n_pool = len(pool)

    base_taken, base_rej, decs = seat_run(pool, trace=True)
    B = metrics(base_taken)
    print(f"\n{'='*118}")
    print(f"=== ANKOR (ILK GELEN ALIR) === ham sinyal {n_pool}")
    print(fmt("TABAN first-come", B))

    # ── 1) BAGLIYICILIK ────────────────────────────────────────────────────
    print(f"\n{'='*118}\n=== 1) KOLTUK TAVANI GERCEKTEN BAGLIYICI MI? ===")
    # zaman-agirlikli doluluk
    ev = []
    for t in base_taken:
        ev.append((t["entry_ts"], +1)); ev.append((t["exit_ts"], -1))
    ev.sort(key=lambda x: (x[0], x[1]))
    dur = {}; cur = 0; prev = None
    for ts, dl in ev:
        if prev is not None and ts > prev: dur[cur] = dur.get(cur, 0.0) + (ts - prev).total_seconds()
        cur += dl; prev = ts
    tot_s = sum(dur.values())
    print(f"  Zaman-agirlikli acik pozisyon dagilimi (MAXPOS={A.MAXPOS}):")
    for k in sorted(dur):
        print(f"    {k} poz: {dur[k]/tot_s*100:5.1f}%  {'#'*int(dur[k]/tot_s*100/2)}")
    full = dur.get(A.MAXPOS, 0.0) / tot_s * 100
    print(f"    -> TAMAMEN DOLU: %{full:.2f} | bos: %{dur.get(0,0)/tot_s*100:.1f} | "
          f"ort acik: {sum(k*v for k,v in dur.items())/tot_s:.2f}")

    print(f"\n  Koltuk bulamayan sinyaller (firsat maliyeti TAVANI):")
    if base_rej:
        rr = np.array([t["R"] for t in base_rej])
        sp = np.array([t["slp"] for t in base_rej])
        lost = float((rr * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0).sum())
        print(f"    {len(base_rej)} sinyal reddedildi (havuzun %{len(base_rej)/n_pool*100:.2f}'si)")
        print(f"    GERCEK sonuclari: ort {rr.mean():+.3f}R | WR %{(rr>0).mean()*100:.0f} | "
              f"toplam ${lost:+.0f}")
        from collections import Counter
        print(f"    sleeve dagilimi: {dict(Counter(t['sleeve'] for t in base_rej))}")
    else:
        print(f"    HICBIRI reddedilmedi.")

    # ASIL SAYI: karar noktasi = ayni entry_ns'te aday sayisi > bos koltuk
    contested = [b for b in decs if len(b["cands"]) > b["free"]]
    n_cand_c = sum(len(b["cands"]) for b in contested)
    multi = [b for b in decs if len(b["cands"]) > 1]
    print(f"\n  KARAR NOKTASI ANALIZI (tahsis kuralinin degistirebilecegi TEK sey):")
    print(f"    toplam ayri entry_ns ani            : {len(decs)}")
    print(f"    ayni anda >1 aday gelen an          : {len(multi)}  (%{len(multi)/max(len(decs),1)*100:.1f})")
    print(f"    aday sayisi > bos koltuk (CEKISMELI): {len(contested)}  "
          f"(%{len(contested)/max(len(decs),1)*100:.2f}), icinde {n_cand_c} aday")
    real = [b for b in contested if 0 < b["free"] < len(b["cands"])]
    n_real_c = sum(len(b["cands"]) for b in real)
    print(f"    bunlarin GERCEK SECIM olani (0<bos<aday): {len(real)}  -> {n_real_c} aday arasindan")
    print(f"       (bos=0 olan cekismeli anlarda secim YOK, hepsi reddedilir)")
    if real:
        from collections import Counter
        shp = Counter("%d/%d" % (b["free"], len(b["cands"])) for b in real)
        print("       secim anlarinin sekli (bos/aday): %s" % dict(sorted(shp.items())))
        yrs = Counter(pd.Timestamp(b["ns"]).year for b in real)
        print("       yil dagilimi: %s" % dict(sorted(yrs.items())))
    print(f"    NOT: cekismeli AN yoksa ILK GELEN ALIR tek nedensel kuraldir; koltuk saklamak")
    print(f"         gelecegi bilmeyi gerektirir (lookahead).")

    # ── 2) TAHSIS KURALLARI ────────────────────────────────────────────────
    print(f"\n{'='*118}\n=== 2) KURAL ADAYLARI (yalniz ayni entry_ns grubunda siralama degisir) ===")
    hist = build_hist_pf(pool)
    rules = {
        "(a1) DAR stop once":      lambda t: t["slp"],
        "(a2) GENIS stop once":    lambda t: -t["slp"],
        "(b)  yuksek gecmis PF":   lambda t: -hist[t["i"]],
        "(c)  gunluk trend hizasi": lambda t: -t["trend"],
        "(d1) yuksek ADX":         lambda t: -t["adx"],
        "(d2) dusuk ADX":          lambda t: t["adx"],
        "(e1) donch>sqz>bb":       lambda t: {"donchian": 0, "squeeze": 1, "bb": 2}[t["sleeve"]],
        "(e2) bb>sqz>donch":       lambda t: {"donchian": 2, "squeeze": 1, "bb": 0}[t["sleeve"]],
        "(g1) ORACLE en iyi R":    lambda t: -t["R"],
        "(g2) ANTI-ORACLE en kotu": lambda t: t["R"],
        "(g3) ORACLE en iyi $":    lambda t: -t["R"] * min(A.RISKF, A.CAP * t["slp"]),
        "(h)  KISA tutus once":    lambda t: t["bars"],
    }
    res = {}
    for name, f in rules.items():
        tk, rj = seat_run(pool, prio=f)
        res[name] = metrics(tk)
        print(fmt(name, res[name], B))

    # ── RASTGELE KONTROL ───────────────────────────────────────────────────
    print(f"\n  --- RASTGELE KONTROL ({NSEED} tohum) ---")
    rnds = []
    for s in range(NSEED):
        rng = np.random.default_rng(s)
        keys = rng.random(n_pool)
        m = metrics(seat_run(pool, prio=lambda t, K=keys: K[t["i"]])[0])
        rnds.append(m)
    rt = np.array([m["tot"] for m in rnds])
    print(f"    rastgele toplam $: ort {rt.mean():+.0f} | std {rt.std():.0f} | "
          f"min {rt.min():+.0f} | p05 {np.percentile(rt,5):+.0f} | med {np.median(rt):+.0f} | "
          f"p95 {np.percentile(rt,95):+.0f} | max {rt.max():+.0f}")
    print(f"    TABAN ${B['tot']:+.0f} rastgele dagilimin persentili: "
          f"%{(rt < B['tot']).mean()*100:.0f}")
    for name in rules:
        v = res[name]["tot"]
        z = (v - rt.mean()) / max(rt.std(), 1e-9)
        print(f"    {name:<26s} ${v:+7.0f}  persentil %{(rt<v).mean()*100:5.1f}  z{z:+.2f}")

    # ── 3) DOZ-YANIT: koltuk kitligi ───────────────────────────────────────
    print(f"\n{'='*118}\n=== 3) DOZ-YANIT: MAX_POSITIONS (kitlik arttikca kural avantaji buyumeli mi?) ===")
    hdr = f"  {'MP':>3s} {'cekismeli an':>13s} {'red':>5s} {'TABAN $':>9s}"
    for name in ["(a1) DAR stop once", "(a2) GENIS stop once", "(b)  yuksek gecmis PF",
                 "(c)  gunluk trend hizasi", "(d1) yuksek ADX", "(g1) ORACLE en iyi R",
                 "(g2) ANTI-ORACLE en kotu"]:
        hdr += f" {name[:12]:>13s}"
    hdr += f" {'rastgele±std':>16s}"
    print(hdr)
    for mp in (2, 3, 4, 5, 6, 7, 8, 10, 12):
        tk, rj, dc = seat_run(pool, maxpos=mp, trace=True)
        bb = metrics(tk); nc = sum(1 for b in dc if len(b["cands"]) > b["free"])
        line = f"  {mp:>3d} {nc:>13d} {len(rj):>5d} {bb['tot']:>+9.0f}"
        for name in ["(a1) DAR stop once", "(a2) GENIS stop once", "(b)  yuksek gecmis PF",
                     "(c)  gunluk trend hizasi", "(d1) yuksek ADX", "(g1) ORACLE en iyi R",
                     "(g2) ANTI-ORACLE en kotu"]:
            mm = metrics(seat_run(pool, prio=rules[name], maxpos=mp)[0])
            line += f" {mm['tot']-bb['tot']:>+13.0f}"
        rs = []
        for s in range(40):
            rng = np.random.default_rng(s); K = rng.random(n_pool)
            rs.append(metrics(seat_run(pool, prio=lambda t, K=K: K[t["i"]], maxpos=mp)[0])["tot"])
        rs = np.array(rs)
        line += f" {rs.mean()-bb['tot']:>+8.0f}±{rs.std():<7.0f}"
        print(line)
    print("  (kural sutunlari TABAN'a gore Δ$; rastgele sutunu ort±std)")

    # ── 4) SAHTELIK TESTLERI ───────────────────────────────────────────────
    print(f"\n{'='*118}\n=== 4) DORT SAHTELIK TESTI ===")
    if not contested:
        print("  Cekismeli karar noktasi YOK -> tahsis kurali diye bir sey yok. Testler anlamsiz.")
    else:
        # (a) ISARET TESTI: her cekismeli anda ORACLE ile TABAN secimi arasindaki R farki
        for name in ["(a1) DAR stop once", "(a2) GENIS stop once", "(b)  yuksek gecmis PF",
                     "(c)  gunluk trend hizasi", "(d1) yuksek ADX"]:
            f = rules[name]
            w = l = 0; diffs = []
            for b in contested:
                cs = b["cands"]; k = b["free"]
                if k <= 0 or k >= len(cs): continue
                bsel = sum(t["R"] for t in cs[:k])                       # first-come
                rsel = sum(t["R"] for t in sorted(cs, key=f)[:k])        # kural
                d = rsel - bsel
                if abs(d) > 1e-12:
                    diffs.append(d)
                    if d > 0: w += 1
                    else: l += 1
            nn = w + l
            p = (2 * sum(math.comb(nn, i) for i in range(min(w, l) + 1)) / 2**nn) if nn else 1.0
            dd = np.array(diffs) if diffs else np.array([0.0])
            print(f"  (a) ISARET  {name:<26s} kazandi {w}/{nn} (p={min(p,1.0):.3f})  "
                  f"ort ΔR/karar {dd.mean():+.3f}")

        # (b)(c)(d): en iyi aday kural(lar) icin havuzlanmis / yon / donem
        print()
        for name in ["(a1) DAR stop once", "(a2) GENIS stop once", "(b)  yuksek gecmis PF",
                     "(c)  gunluk trend hizasi", "(d1) yuksek ADX"]:
            tk, _ = seat_run(pool, prio=rules[name])
            ra = np.array([t["R"] for t in base_taken]); rb = np.array([t["R"] for t in tk])
            se = math.sqrt(ra.var(ddof=1) / len(ra) + rb.var(ddof=1) / len(rb))
            z = (rb.mean() - ra.mean()) / se
            # yon ayrimi
            def sub(ts, key):
                a = np.array([t["R"] for t in ts if key(t)]); return a
            outs = []
            for lab, key in [("LONG", lambda t: t["dirn"] == 1), ("SHORT", lambda t: t["dirn"] == -1),
                             ("TRAIN", lambda t: pd.Timestamp(t["exit_ts"]) < TRAIN_END),
                             ("TEST", lambda t: pd.Timestamp(t["exit_ts"]) >= TRAIN_END)]:
                pa = np.array([t["R"] * min(A.RISKF, A.CAP * t["slp"]) * A.BAL0 for t in base_taken if key(t)])
                pb = np.array([t["R"] * min(A.RISKF, A.CAP * t["slp"]) * A.BAL0 for t in tk if key(t)])
                outs.append(f"{lab} Δ${pb.sum()-pa.sum():+.0f}")
            print(f"  (b/c/d) {name:<26s} havuz ΔR {rb.mean()-ra.mean():+.4f} z{z:+.2f} | " + " | ".join(outs))

    # ── 5) TUKETICI SINIR: TUM olasi tahsislerin uzayi ────────────────────
    # Cekismeli anlarda "hangi alt kume koltuk alsin" secimlerinin TAMAMINI DFS ile gez.
    # Bu, HERHANGI bir nedensel tahsis kuralinin ulasabilecegi EN IYI ve EN KOTU sonucu
    # verir (greedy oracle bir ust sinir DEGIL; bu tuketici arama gercek sinir).
    print(f"\n{'='*118}\n=== 5) TUKETICI SINIR: tum nedensel tahsis kurallarinin uzayi (DFS) ===")
    from itertools import combinations
    order = sorted(range(n_pool), key=lambda k: pool[k]["entry_ns"])
    LIMIT = 400000
    stats = {"leaf": 0, "nodes": 0, "cut": False}
    best = [-1e18, None]; worst = [1e18, None]
    def dollars(ts):
        return sum(t["R"] * min(A.RISKF, A.CAP * t["slp"]) * A.BAL0 for t in ts)
    def dfs(pos, openh, acc):
        """Secim OLMAYAN anlari dongude tuket (recursion derinligi = GERCEK secim sayisi),
        yalnizca gercek secimde dallan."""
        stats["nodes"] += 1
        if stats["nodes"] > LIMIT: stats["cut"] = True; return
        while pos < len(order):
            ns = pool[order[pos]]["entry_ns"]; j = pos
            while j < len(order) and pool[order[j]]["entry_ns"] == ns: j += 1
            cands = [pool[order[k]] for k in range(pos, j)]
            openh = [x for x in openh if x[0].value > ns]
            free = A.MAXPOS - len(openh)
            if free <= 0:
                pos = j; continue                                   # hepsi red, secim yok
            if free >= len(cands):
                openh = openh + [(t["exit_ts"], t["i"]) for t in cands]
                acc = acc + cands; pos = j; continue                # hepsi girer, secim yok
            for sel in combinations(cands, free):                   # GERCEK SECIM
                dfs(j, openh + [(t["exit_ts"], t["i"]) for t in sel], acc + list(sel))
            return
        stats["leaf"] += 1; v = dollars(acc)
        if v > best[0]: best[0] = v; best[1] = list(acc)
        if v < worst[0]: worst[0] = v; worst[1] = list(acc)
    dfs(0, [], [])
    if stats["cut"]:
        print(f"  ARAMA KESILDI ({LIMIT} dugum) — sinirlar ALT-tahmin, yine de bilgilendirici.")
    print(f"  gezilen yaprak: {stats['leaf']}, dugum: {stats['nodes']}")
    if best[1]:
        bm = metrics(sorted(best[1], key=lambda t: t["exit_ts"]))
        wm = metrics(sorted(worst[1], key=lambda t: t["exit_ts"]))
        print(fmt("EN IYI olasi tahsis", bm, B))
        print(fmt("EN KOTU olasi tahsis", wm, B))
        print(f"  -> TUM tahsis uzayinin genisligi: ${wm['tot']:+.0f} .. ${bm['tot']:+.0f} "
              f"= ${bm['tot']-wm['tot']:.0f} ({(bm['tot']-wm['tot'])/B['tot']*100:.1f}% ankorun)")
        print(f"  -> MUTLAK TAVAN (gelecegi bilerek): Δ${bm['tot']-B['tot']:+.0f}. "
              f"Kabul bari +${0.02*B['tot']:.0f}.")

    # ── 6) DOZ-YANITTAKI TEK YAPI: MP=3'te kurallar buyuk artida. GERCEK mi? ──
    # MP=7'de (canli) hicbir sey yok ama MP=2-4'te (c)/(d1)/(a1) buyuk pozitif.
    # Bu "koltuk kitken kalite onemli" demek olabilir — ya da orneklem-ici gurultu.
    # HAKEM: TRAIN(<2025) ve TEST(>=2025) AYNI isareti veriyor mu + rastgeleye gore z.
    print(f"\n{'='*118}\n=== 6) MP=3'TEKI YAPI GERCEK MI? (donem ayrimi + rastgele z) ===")
    for mp in (3, 4, 5):
        base_mp, _ = seat_run(pool, maxpos=mp)
        rs = []
        for s in range(200):
            rng = np.random.default_rng(1000 + s); K = rng.random(n_pool)
            rs.append(metrics(seat_run(pool, prio=lambda t, K=K: K[t["i"]], maxpos=mp)[0])["tot"])
        rs = np.array(rs)
        print(f"\n  --- MP={mp} (taban ${metrics(base_mp)['tot']:+.0f}, "
              f"rastgele {rs.mean():+.0f}±{rs.std():.0f}) ---")
        for name in ["(a1) DAR stop once", "(c)  gunluk trend hizasi", "(d1) yuksek ADX",
                     "(b)  yuksek gecmis PF", "(g1) ORACLE en iyi R"]:
            tk, _ = seat_run(pool, prio=rules[name], maxpos=mp)
            def dol(ts, key): return sum(t["R"] * min(A.RISKF, A.CAP * t["slp"]) * A.BAL0
                                         for t in ts if key(t))
            tr = lambda t: t["exit_ts"] < TRAIN_END; te = lambda t: t["exit_ts"] >= TRAIN_END
            dtr = dol(tk, tr) - dol(base_mp, tr); dte = dol(tk, te) - dol(base_mp, te)
            m = metrics(tk); z = (m["tot"] - rs.mean()) / max(rs.std(), 1e-9)
            same = "AYNI" if (dtr > 0) == (dte > 0) else "TERS"
            ys = " ".join(f"{y}:{v-metrics(base_mp)['yr'].get(y,0):+5.0f}" for y, v in sorted(m["yr"].items()))
            print(f"    {name:<26s} Δ${m['tot']-metrics(base_mp)['tot']:+6.0f} z{z:+5.2f} | "
                  f"TRAIN Δ${dtr:+6.0f} TEST Δ${dte:+6.0f} -> {same} | {ys}")

    print(f"\n{'='*118}\n=== KABUL BARI KONTROLU (taban ${B['tot']:+.0f}, bar: +${0.02*B['tot']:.0f}) ===")
    for name, m in res.items():
        d = m["tot"] - B["tot"]
        yb = all(m["yr"].get(y, 0) >= B["yr"][y] - abs(B["yr"][y]) * 0.10 for y in B["yr"])
        ok = (d >= 0.02 * B["tot"]) and yb and (m["dd"] <= B["dd"] + 2) and (m["worst"] >= B["worst"])
        print(f"  {name:<26s} Δ${d:+7.0f} {'kar-OK' if d>=0.02*B['tot'] else 'kar-YOK'} | "
              f"{'yil-OK' if yb else 'yil-BOZUK'} | DD{m['dd']-B['dd']:+.1f}p | "
              f"kotuAy{m['worst']-B['worst']:+.1f} | {'*** GECTI' if ok else 'RET'}")


if __name__ == "__main__":
    main()
