"""
voltarget_test.py — GOREV C: PORTFOY SEVIYESI VOLATILITE HEDEFLEME.

Mevcut sistem ZATEN islem-bazinda vol-normalize (SL=2xATR, boyut=risk/SL mesafesi).
Buradaki test FARKLI: stratejinin KENDI getiri volatilitesi yuksekken TUM kitabi kucult
(klasik CTA vol-targeting). Filtre DEGIL — surekli boyutlandirma.

METODOLOJI (zorunlu kurallara birebir uyum):
  * Veri: fast_bt.load(coin, source="local") + fast_bt.resample
  * Sinyal uretimi: deployed_backtest.gen AYNEN kullanilir (occ=j icinde, lookahead yok)
  * Koltuk secimi: deployed_backtest.seat_select ile AYNI mantik (MAXPOS=7, giris zamanina gore),
    tek fark: entry timestamp'i de tasiyoruz (olcek carpani GIRIS aninda belirlenir).
  * Boyut: eff = min(RISKF * s, CAP * sl_pct);  pnl = R * eff * BAL0
    (s = vol-hedef olcegi. Notional tavani s'den BAGIMSIZ: notional=risk/slp <= CAP*BAL0
     => risk <= CAP*slp. Kucultunce tavana daha az takilir — bu gercekci model.)
  * LOOKAHEAD YASAK: k. islemin olcegi SADECE giris zamanindan ONCE KAPANMIS islemlerden
    hesaplanir (exit_ts < entry_ts_k). "son N islem" = exit sirasina gore, mevcut islem HARIC.
  * Hedef vol de lookahead'siz: o ana kadar gozlenen gerceklesen-vol serisinin GENISLEYEN
    medyani. (Ayrica tam-orneklem sabit hedef = KAHIN varyanti, tavani gormek icin, ETIKETLI.)

Kabul bari: toplam ARTACAK **ve** HER YIL (2023,2024,2025,2026) artacak.
Ayrica riske-gore-olceklenmis karsilastirma (maxDD tabana esitlenirse) da ayni bar.

Kullanim: python voltarget_test.py
"""
import os, sys, heapq, pickle
import numpy as np, pandas as pd

import fast_bt
import deployed_backtest as db

BAL0 = db.BAL0      # 190.0
FEE = db.FEE        # 0.0001
RISKF = db.RISKF    # 0.0225
CAP = db.CAP        # 1.25
MAXPOS = db.MAXPOS  # 7
DONCH = db.DONCH
SQZ = db.SQZ

CACHE = "/home/user/Bot2/.voltarget_trades.pkl"


# ---------------------------------------------------------------- veri / islemler
def build_trades():
    """deployed_backtest.gen -> (entry_ns, exit_ts, R, sl_pct) ham islem havuzu."""
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            tr = pickle.load(f)
        print(f"  islem havuzu onbellekten: {len(tr)} ham sinyal ({CACHE})")
        return tr
    trades = []
    for c in DONCH:
        trades += db.gen("donchian", fast_bt.load(c, source="local"))
    for c in SQZ:
        trades += db.gen("squeeze", fast_bt.load(c, source="local"))
    with open(CACHE, "wb") as f:
        pickle.dump(trades, f)
    return trades


def seat_select_keep_entry(trades):
    """deployed_backtest.seat_select ile BIREBIR ayni kabul mantigi; entry_ns korunur."""
    ev = sorted(trades, key=lambda t: t[0])
    openh = []
    taken = []
    ctr = 0
    for entry_ns, exit_ts, R, slp in ev:
        while openh and openh[0][0].value <= entry_ns:
            heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((entry_ns, exit_ts, R, slp))
    return sorted(taken, key=lambda t: t[1])   # EXIT sirasi (deployed ile ayni)


# ---------------------------------------------------------------- metrikler
def maxdd(equity):
    peak = np.maximum.accumulate(equity)
    return ((peak - equity) / peak).max() * 100.0


def stats(pnl, exits, label):
    eq = BAL0 + np.cumsum(pnl)
    tot = eq[-1] - BAL0
    dd = maxdd(np.concatenate([[BAL0], eq]))
    gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    pf = gp / gl if gl > 0 else 99.9
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in exits]).groupby(level=0).sum()
    yr = np.array([x.year for x in exits])
    ypnl = {y: pnl[yr == y].sum() for y in sorted(set(yr))}
    return dict(label=label, tot=tot, pf=pf, dd=dd, worst_m=mon.min(),
                worst_m_pct=mon.min() / BAL0 * 100, pos_m=(mon > 0).mean() * 100,
                yr=ypnl, n=len(pnl), pnl=pnl)


def scale_to_dd(pnl, target_dd):
    """Global risk carpani k bul: maxdd(BAL0+cumsum(k*pnl)) == target_dd. Bisection."""
    lo, hi = 0.01, 20.0
    if maxdd(np.concatenate([[BAL0], BAL0 + np.cumsum(hi * pnl)])) < target_dd:
        return hi
    for _ in range(80):
        mid = (lo + hi) / 2
        d = maxdd(np.concatenate([[BAL0], BAL0 + np.cumsum(mid * pnl)]))
        if d < target_dd: lo = mid
        else: hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- vol-hedef olcekleri
def scales_trade_vol(entry_ns, exit_ns, r_or_pnl, N, lo, hi, warm=30, oracle=False):
    """k. islemin GIRIS aninda: exit_ts < entry_ts olan islemlerin son N tanesinin std'si.
    Hedef = o ana kadarki vol gozlemlerinin GENISLEYEN medyani (lookahead yok).
    oracle=True -> hedef = tam-orneklem medyani (LOOKAHEAD, sadece tavan teshisi)."""
    n = len(entry_ns)
    order = np.argsort(exit_ns, kind="stable")     # exit sirasi (zaten sirali ama garanti)
    ex_sorted = exit_ns[order]
    v_sorted = r_or_pnl[order]
    vols = np.full(n, np.nan)
    for k in range(n):
        cnt = np.searchsorted(ex_sorted, entry_ns[k], side="left")   # exit < entry olanlar
        if cnt >= N:
            w = v_sorted[cnt - N:cnt]
            vols[k] = w.std(ddof=1)
    fin = np.isfinite(vols)
    s = np.ones(n)
    if oracle:
        if fin.sum() == 0: return s, vols
        tgt_full = np.nanmedian(vols[fin])
        tgt = np.where(fin, tgt_full, np.nan)
    else:
        tgt = np.full(n, np.nan)
        seen = []
        for k in range(n):
            if fin[k]:
                seen.append(vols[k])
                if len(seen) >= warm:
                    tgt[k] = np.median(seen)       # SADECE gecmis gozlemler + mevcut (gecmis-turevi)
    for k in range(n):
        if np.isfinite(tgt[k]) and np.isfinite(vols[k]) and vols[k] > 0:
            s[k] = float(np.clip(tgt[k] / vols[k], lo, hi))
    return s, vols


def scales_daily_vol(entry_ts, exit_ts, base_pnl, Ndays, lo, hi, warm=30, oracle=False):
    """Gunluk PnL std'si (gerceklesen, exit gununde muhasebe). k. islemin giris GUNUNDEN
    ONCEKI son Ndays gunun std'si — mevcut gun HARIC (.shift(1) mantigi)."""
    n = len(entry_ts)
    ex_days = pd.DatetimeIndex(exit_ts).tz_localize(None).normalize()
    ser = pd.Series(base_pnl, index=ex_days).groupby(level=0).sum()
    full = pd.date_range(ser.index.min(), ser.index.max(), freq="D")
    ser = ser.reindex(full, fill_value=0.0)
    vals = ser.values
    days = ser.index
    en_days = pd.DatetimeIndex(entry_ts).tz_localize(None).normalize()
    vols = np.full(n, np.nan)
    for k in range(n):
        pos = days.searchsorted(en_days[k], side="left")   # giris gunu HARIC
        if pos >= Ndays:
            vols[k] = vals[pos - Ndays:pos].std(ddof=1)
    fin = np.isfinite(vols) & (vols > 0)
    s = np.ones(n)
    if oracle:
        if fin.sum() == 0: return s, vols
        tgt = np.where(fin, np.median(vols[fin]), np.nan)
    else:
        tgt = np.full(n, np.nan)
        seen = []
        for k in range(n):
            if fin[k]:
                seen.append(vols[k])
                if len(seen) >= warm:
                    tgt[k] = np.median(seen)
    for k in range(n):
        if np.isfinite(tgt[k]) and fin[k]:
            s[k] = float(np.clip(tgt[k] / vols[k], lo, hi))
    return s, vols


# ---------------------------------------------------------------- rapor
def line(st, base=None):
    ys = " ".join(f"{y}:${v:+6.0f}" for y, v in st["yr"].items())
    tag = ""
    if base is not None:
        allup = all(st["yr"][y] > base["yr"][y] for y in base["yr"])
        tot_up = st["tot"] > base["tot"]
        tag = ("  ***ADAY***" if (allup and tot_up) else
               ("  [toplam+ ama yil-yil X]" if tot_up else "  [toplam-]"))
    return (f"{st['label']:<34s} ${st['tot']:+7.0f}  PF{st['pf']:4.2f}  DD{st['dd']:5.1f}%  "
            f"kotuAy${st['worst_m']:+6.1f}  | {ys}{tag}")


def main():
    print("=" * 118)
    print("GOREV C — PORTFOY SEVIYESI VOLATILITE HEDEFLEME")
    print("=" * 118)
    raw = build_trades()
    taken = seat_select_keep_entry(raw)
    entry_ns = np.array([t[0] for t in taken], dtype=np.int64)
    exit_ts = [pd.Timestamp(t[1]) for t in taken]
    exit_ns = np.array([pd.Timestamp(t[1]).value for t in taken], dtype=np.int64)
    R = np.array([t[2] for t in taken])
    slp = np.array([t[3] for t in taken])
    n = len(R)

    # ---- TABAN (deployed_backtest A-gorunumu ile birebir)
    eff0 = np.minimum(RISKF, CAP * slp)
    pnl0 = R * eff0 * BAL0
    base = stats(pnl0, exit_ts, "TABAN (vol-hedef yok)")
    rr = R
    print(f"\n  {n} islem, {pd.Timestamp(entry_ns[0]).date()} -> {exit_ts[-1].date()}")
    print(f"  R-PF {rr[rr>0].sum()/-rr[rr<0].sum():.2f} | WR {(rr>0).mean()*100:.0f}% | ort {rr.mean():+.3f}R")
    print(f"  ort gercek risk {eff0.mean()*100:.2f}% (hedef {RISKF*100:.2f}%), "
          f"tavana takilan {(eff0 < RISKF-1e-12).mean()*100:.0f}%")
    print("\n" + "-" * 118)
    print(line(base))
    print("-" * 118)

    results = []

    # ================= A) ISLEM-BAZLI R VOLATILITESI =================
    print("\n### A) Gerceklesen vol = son N ISLEMIN R standart sapmasi "
          "(hedef = genisleyen medyan, lookahead yok)\n")
    for N in (20, 40, 60):
        for hi in (1.0, 1.5, 2.0):
            for lo in (0.3, 0.5):
                s, vols = scales_trade_vol(entry_ns, exit_ns, R, N, lo, hi)
                eff = np.minimum(RISKF * s, CAP * slp)
                st = stats(R * eff * BAL0, exit_ts, f"R-vol N{N} clip[{lo},{hi}]")
                st["s"] = s
                results.append(st)
                print("  " + line(st, base))

    # ================= B) GUNLUK PnL VOLATILITESI =================
    print("\n### B) Gerceklesen vol = son N GUNUN gunluk PnL std'si "
          "(giris gunu haric, hedef = genisleyen medyan)\n")
    for N in (20, 40, 60):
        for hi in (1.0, 1.5, 2.0):
            for lo in (0.3, 0.5):
                s, vols = scales_daily_vol(entry_ns_to_ts(entry_ns), exit_ts, pnl0, N, lo, hi)
                eff = np.minimum(RISKF * s, CAP * slp)
                st = stats(R * eff * BAL0, exit_ts, f"D-vol N{N}g clip[{lo},{hi}]")
                st["s"] = s
                results.append(st)
                print("  " + line(st, base))

    # ================= C) KAHIN (LOOKAHEAD — sadece TAVAN teshisi) =================
    print("\n### C) KAHIN varyanti (hedef = TAM-ORNEKLEM medyani; LOOKAHEAD var, "
          "karar icin GECERSIZ, sadece tavani gormek icin)\n")
    orc = []
    for N in (20, 40, 60):
        for hi in (1.0, 2.0):
            s, _ = scales_trade_vol(entry_ns, exit_ns, R, N, 0.3, hi, oracle=True)
            eff = np.minimum(RISKF * s, CAP * slp)
            st = stats(R * eff * BAL0, exit_ts, f"[KAHIN] R-vol N{N} clip[0.3,{hi}]")
            orc.append(st)
            print("  " + line(st, base))

    # ================= D) RISKE-GORE-DUZELTILMIS KARSILASTIRMA =================
    print("\n" + "=" * 118)
    print("### D) RISKE-GORE-DUZELTILMIS: her varyant TABAN maxDD'sine kadar kaldiraclanir")
    print(f"    (taban DD = {base['dd']:.1f}%; k = global risk carpani; k*pnl ile yeniden olculur)")
    print("=" * 118 + "\n")
    print(f"  {'varyant':<34s} {'k':>5s}  {'olcekli$':>9s}  {'DD':>6s}   yil-yil (olcekli) vs taban")
    adaylar = []
    for st in sorted(results, key=lambda x: -x["tot"]):
        k = scale_to_dd(st["pnl"], base["dd"])
        sp = k * st["pnl"]
        s2 = stats(sp, exit_ts, st["label"] + f" x{k:.2f}")
        allup = all(s2["yr"][y] > base["yr"][y] for y in base["yr"])
        ys = " ".join(f"{y}:${s2['yr'][y]:+6.0f}({base['yr'][y]:+.0f})" for y in base["yr"])
        tag = "  ***ADAY(risk-adj)***" if (allup and s2["tot"] > base["tot"]) else ""
        print(f"  {st['label']:<34s} {k:5.2f}  ${s2['tot']:+8.0f}  {s2['dd']:5.1f}%   {ys}{tag}")
        if allup and s2["tot"] > base["tot"]:
            adaylar.append((st["label"], k, s2))

    # ================= E) ESIT-RISK NORMALIZASYONU + DUZ-KALDIRAC KONTROLU =================
    # KRITIK: vol-hedefleme ortalama riski DEGISTIRIR. Ust sinir>1 ise kitap ortalamada
    # BUYUR -> toplam artar ama bu ZAMANLAMA BECERISI degil, sadece KALDIRAC.
    # Olcek-bagimsiz tek dogru test: birim-riske-dusen getiri (agirlikli ort R).
    #   tot = sum(R*eff*BAL0)  =>  agirlikli_ort_R = tot / (BAL0 * sum(eff))
    # Beceri varsa vol-hedef agirlikli ort R'yi YUKSELTIR. Yukseltmiyorsa kazanc kaldiractir.
    print("\n" + "=" * 118)
    print("### E) OLCEK-BAGIMSIZ TEST: birim riske dusen getiri + DUZ-KALDIRAC kontrolu")
    print("    ag.ortR = tot / (BAL0*sum(eff)) — riskten arindirilmis edge. TABAN'i gecmeli.")
    print("    duz-kaldirac = TABAN'in ayni oranda buyutulmus hali (vol ZAMANLAMASI YOK).")
    print("=" * 118 + "\n")
    sum_eff0 = eff0.sum()
    wR0 = base["tot"] / (BAL0 * sum_eff0)
    print(f"  {'varyant':<34s} {'ort_s':>6s} {'risk×':>6s} {'ag.ortR':>8s} {'esit-risk$':>10s} "
          f"{'duz-kald.$':>10s}  esit-risk yil-yil")
    print(f"  {'TABAN':<34s} {1.0:6.3f} {1.000:6.3f} {wR0:8.4f} ${base['tot']:+9.0f} "
          f"{'—':>10s}  " + " ".join(f"{y}:${v:+.0f}" for y, v in base["yr"].items()))
    eq_aday = []
    for st in results:
        s = st["s"]
        eff = np.minimum(RISKF * s, CAP * slp)
        se = eff.sum()
        ratio = se / sum_eff0                      # dagitilan toplam risk (taban=1.0)
        wR = st["tot"] / (BAL0 * se)
        pnl_eq = st["pnl"] / ratio                 # esit-risk: global sabitle normalize
        s_eq = stats(pnl_eq, exit_ts, st["label"] + " [esit-risk]")
        flat = base["tot"] * ratio                 # ayni riski ZAMANLAMASIZ almanin getirisi
        allup = all(s_eq["yr"][y] > base["yr"][y] for y in base["yr"])
        tag = "  ***ADAY(esit-risk)***" if (allup and s_eq["tot"] > base["tot"]) else ""
        ys = " ".join(f"{y}:${s_eq['yr'][y]:+.0f}" for y in base["yr"])
        print(f"  {st['label']:<34s} {s.mean():6.3f} {ratio:6.3f} {wR:8.4f} ${s_eq['tot']:+9.0f} "
              f"${flat:+9.0f}  {ys}{tag}")
        if allup and s_eq["tot"] > base["tot"]:
            eq_aday.append(st["label"])
    print(f"\n  Esit-risk normalizasyonunda toplam+her-yil gecen: {len(eq_aday)}")
    print(f"  ag.ortR TABAN'i gecen varyant sayisi: "
          f"{sum(1 for st in results if st['tot']/(BAL0*np.minimum(RISKF*st['s'],CAP*slp).sum()) > wR0)}/{len(results)}")

    # ================= F) DAGITILABILIR ESIT-RISK FORMU + PERMUTASYON TESTI =================
    # E'deki "esit-risk" post-hoc lineer olceklemeydi (pnl/ratio). Canlida bunun karsiligi:
    # taban riski RISKF' = RISKF/ratio'ya cikar VE notional tavanini YENIDEN uygula.
    # Tavan bagladigi icin ikisi ayni sey DEGIL — dagitilabilir formu ayrica olcuyoruz.
    #
    # PERMUTASYON: olcek serisi s'nin DAGILIMI ayni kalsin ama ZAMANLAMASI bozulsun
    # (rastgele permutasyon). Gercek zamanlama gurultuden ayirt edilebiliyor mu?
    print("\n" + "=" * 118)
    print("### F) DAGITILABILIR ESIT-RISK (RISKF yukseltilir + tavan yeniden uygulanir)")
    print("       + PERMUTASYON TESTI (olcek dagilimi ayni, ZAMANLAMA bozuk, 2000 tur)")
    print("=" * 118 + "\n")
    rng = np.random.default_rng(12345)
    print(f"  {'varyant':<30s} {'RISKF*':>7s} {'toplam$':>9s} {'DD':>6s} {'kotuAy$':>8s} "
          f"{'p(perm)':>8s}  yil-yil (taban farki)")
    print(f"  {'TABAN':<30s} {RISKF*100:6.2f}% ${base['tot']:+8.0f} {base['dd']:5.1f}% "
          f"{base['worst_m']:+8.1f} {'—':>8s}  " + " ".join(f"{y}:${v:+.0f}" for y, v in base["yr"].items()))
    depl = []; cross = []
    for st in results:
        s = st["s"]
        ratio = np.minimum(RISKF * s, CAP * slp).sum() / sum_eff0
        rf2 = RISKF / ratio                                  # esit ortalama risk hedefi
        eff2 = np.minimum(rf2 * s, CAP * slp)                # tavan YENIDEN uygulanir
        p2 = R * eff2 * BAL0
        s2 = stats(p2, exit_ts, st["label"])
        # permutasyon: ayni s DAGILIMI, rastgele zamanlama
        wR_real = st["tot"] / (BAL0 * np.minimum(RISKF * s, CAP * slp).sum())
        cnt = 0
        for _ in range(2000):
            sp = rng.permutation(s)
            ep = np.minimum(RISKF * sp, CAP * slp)
            if (R * ep * BAL0).sum() / (BAL0 * ep.sum()) >= wR_real: cnt += 1
        pval = (cnt + 1) / 2001
        allup = all(s2["yr"][y] > base["yr"][y] for y in base["yr"])
        marj = min(s2["yr"][y] - base["yr"][y] for y in base["yr"])
        tag = f"  ***ADAY*** (en dar yil marji ${marj:+.0f})" if (allup and s2["tot"] > base["tot"]) else ""
        ys = " ".join(f"{y}:{s2['yr'][y]-base['yr'][y]:+.0f}" for y in base["yr"])
        print(f"  {st['label']:<30s} {rf2*100:6.2f}% ${s2['tot']:+8.0f} {s2['dd']:5.1f}% "
              f"{s2['worst_m']:+8.1f} {pval:8.3f}  {ys}{tag}")
        if allup and s2["tot"] > base["tot"]:
            depl.append((st["label"], s2, pval, marj))
        cross.append((st["label"], pval, allup and s2["tot"] > base["tot"]))

    # KESIN CAPRAZ TABLO: istatistiksel anlamlilik VE yil-yil bari AYNI ANDA saglanabiliyor mu?
    sig = [c for c in cross if c[1] < 0.05]
    both = [c for c in cross if c[1] < 0.05 and c[2]]
    print(f"\n  CAPRAZ TABLO (36 varyant):")
    print(f"    permutasyon p<0.05 (zamanlama gercek)        : {len(sig)}  -> {[c[0] for c in sig]}")
    print(f"    toplam+HER YIL gecen                          : {len(depl)}")
    print(f"    IKISI BIRDEN (p<0.05 VE her yil)              : {len(both)}")
    if not both:
        print("    -> Zamanlamanin OLCULEBILDIGI yerde yil-yil bari DUSUYOR; yil-yil barini")
        print("       gecen yerde zamanlama GURULTUDEN AYIRT EDILEMIYOR. Ortusme YOK.")

    print(f"\n  Dagitilabilir esit-risk formunda toplam+her-yil gecen: {len(depl)}")
    win = pnl0[pnl0 > 0].mean(); los = pnl0[pnl0 < 0].mean()
    print(f"\n  OLCEK REFERANSI: taban ort KAZANAN islem ${win:+.2f}, ort KAYBEDEN ${los:+.2f}.")
    print(f"  Yani TEK bir islemin sonucu ~${win-los:.1f} oynatir. Asagidaki yil marjlari bunu asmali:")
    for lab, s2, pv, marj in depl:
        print(f"    {lab}: ${s2['tot']:+.0f} (+${s2['tot']-base['tot']:.0f}), en dar yil marji "
              f"${marj:+.0f} (= {abs(marj)/(win-los):.2f} islem!), permutasyon p={pv:.3f}")

    # ================= OZET =================
    print("\n" + "=" * 118)
    print("### OZET")
    print("=" * 118)
    ham_aday = [st for st in results
                if st["tot"] > base["tot"] and all(st["yr"][y] > base["yr"][y] for y in base["yr"])]
    tot_up = [st for st in results if st["tot"] > base["tot"]]
    print(f"  Denenen varyant: {len(results)} (18 R-vol + 18 gunluk-vol)")
    print(f"  Toplami TABANI gecen: {len(tot_up)}/{len(results)}")
    print(f"  Toplam VE her yil gecen (HAM aday): {len(ham_aday)}")
    print(f"  Riske-gore-olceklenmis aday: {len(adaylar)}")
    best = max(results, key=lambda x: x["tot"])
    print(f"\n  En iyi ham varyant: {best['label']}  ${best['tot']:+.0f} (taban ${base['tot']:+.0f}, "
          f"fark ${best['tot']-base['tot']:+.0f})")
    bo = max(orc, key=lambda x: x["tot"])
    print(f"  En iyi KAHIN (lookahead'li TAVAN): {bo['label']}  ${bo['tot']:+.0f} "
          f"(fark ${bo['tot']-base['tot']:+.0f})")
    # DD azalmasi var mi?
    dmin = min(results, key=lambda x: x["dd"])
    print(f"  En dusuk DD varyanti: {dmin['label']}  DD {dmin['dd']:.1f}% (taban {base['dd']:.1f}%), "
          f"toplam ${dmin['tot']:+.0f}")
    print(f"  Esit-risk (olcek-bagimsiz) aday: {len(eq_aday)}")
    # Sadece-kucult (ust sinir 1.0) kolu ayri raporlanir: "muhafazakar" varyant tam da bu.
    only_dn = [st for st in results if "1.0]" in st["label"]]
    print(f"\n  SADECE-KUCULT kolu (ust sinir 1.0, asla buyutme) — {len(only_dn)} varyant:")
    print(f"    toplam araligi ${min(x['tot'] for x in only_dn):+.0f}..${max(x['tot'] for x in only_dn):+.0f} "
          f"(taban ${base['tot']:+.0f}) — HICBIRI tabani gecmiyor")
    print(f"    DD araligi {min(x['dd'] for x in only_dn):.1f}..{max(x['dd'] for x in only_dn):.1f}% "
          f"(taban {base['dd']:.1f}%) — DD de anlamli DUSMUYOR")
    # UC normalizasyonun KESISIMI — gercek bir etki her birinde ayakta kalmali
    lab_raw = {st["label"] for st in ham_aday}
    lab_dd = {l for l, _, _ in adaylar}
    lab_dep = {l for l, _, _, _ in depl}
    kesisim = lab_raw & lab_dep & lab_dd
    print(f"\n  NORMALIZASYON TUTARLILIGI (gercek etki HEPSINDE ayakta kalmali):")
    print(f"    ham (risk esitlenmemis)      : {len(lab_raw)} aday")
    print(f"    maxDD-esitlenmis             : {len(lab_dd)} aday")
    print(f"    dagitilabilir esit-risk      : {len(lab_dep)} aday")
    print(f"    UCUNDE DE gecen (KESISIM)    : {len(kesisim)}  {sorted(kesisim) if kesisim else ''}")
    if not kesisim:
        print("\n  SONUC: ADAY YOK. Hangi normalizasyonun secildigine gore aday KUMESI tamamen")
        print("         degisiyor (ham=kaldirac, esit-risk=baska varyantlar, DD-esit=hicbiri).")
        print("         Bu sinyal degil GURULTU imzasi. Portfoy vol-hedefleme kabul barini GECEMEDI.")
    if not ham_aday and not adaylar:
        print("\n  SONUC: ADAY YOK. Portfoy-seviyesi vol-hedefleme kabul barini gecemedi.")
    elif not adaylar and not eq_aday:
        print("\n  SONUC: HAM aday var ama riske-gore-duzeltilmis VE esit-risk testlerinde")
        print("         hepsi oluyor -> kazanc ZAMANLAMA becerisi degil, KALDIRAC. ADAY YOK.")
    return base, results, orc, adaylar


def entry_ns_to_ts(entry_ns):
    return pd.to_datetime(entry_ns, utc=True)


if __name__ == "__main__":
    main()
