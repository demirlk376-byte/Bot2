"""
nk_funding.py — FONLAMA ORANI (funding rate) UÇ DEĞERLERİNİ FADE ETMEK: ayrı bir kol olabilir mi?

HİPOTEZ (görev metninden): perp funding aşırı pozitifse kalabalık LONG tarafta aşırı kaldıraçlıdır
→ long squeeze yakıtı → kontraryan SHORT. Aşırı negatifte ayna. Bu OSİLATÖR DEĞİL, KONUMLANMA
verisidir; fiyattan türetilmemiştir → "tetikleyiciyle aynı olayı ikinci kez ölçme" tautolojisine
teorik olarak düşmez. Adayın en güçlü yanı budur.

BU DOSYA NE YAPIYOR (ve NE YAPMIYOR):
  Funding GEÇMİŞ VERİSİ bu konteynerde YOK ve ÇEKİLEMİYOR (aşağıda BÖLÜM A'da kanıtı ölçülüyor).
  Bu yüzden funding sinyalinin EDGE'i ölçülemez. Uydurma yapılmayacak.
  Ölçülebilen ve karar için gerçekten belirleyici olan İKİ şey ölçülüyor:
    (1) KAPASİTE ve GEREKEN EDGE: funding takvimine (00/08/16 UTC) ve persentil-uç frekansına
        sahip bir HAYALET kol, 22 coin üzerinde, canlı mekanikle (SL 2×ATR, rr, maxhold, occ)
        koltuk yarışına sokuluyor. Yön RASTGELE — yani EDGE İDDİASI YOK. Ölçülen: kaç sinyal
        koltuk bulur, ankordan kaç işlem SİLİNİR, dolar/R nedir, ve ön-kayıtlı +$28 barını
        geçmek için funding sinyalinin SAHİP OLMASI GEREKEN ortalama R / kazanma oranı nedir.
    (2) EŞZAMANLILIK/KORELASYON YAPISI: funding piyasa-geneli bir değişkendir; uçları aynı anda
        tüm coinlerde ve AYNI YÖNDE tetiklenir. Bu, bugün ölçülen 2. sınırın (eşzamanlı korele
        maruziyet, coin ekleme çöküşü) tam merkezidir. Çapraz coin getiri korelasyonu + hayalet
        kolun piyasa-geneli modda koltuk davranışı ölçülüyor. Ayrıca funding'in fiyat vekili
        (trailing momentum/basis) üzerinden bir korelasyon TAHMİNİ veriliyor — VEKİL olduğu
        açıkça etiketli, edge iddiası DEĞİL.

Kullanım:  python3 nk_funding.py local
"""
from __future__ import annotations

import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn

BAL0 = 190.0
FEE = 0.0001
RISKF = 0.0225
CAP = 1.25
MAXPOS = 7
BAR_DOLLAR = 28.0                       # ön-kayıtlı bar: Δ$ > +28 (ankorun %2'si)
ANCHOR_MEAN_R = 0.237                   # ankorun ölçülmüş işlem başına R'si (iyimser tavan)

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
FUND_HOURS = (0, 8, 16)                 # perp funding kesinti saatleri (UTC)
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
CACHE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/nk_anchor.pkl"


# ─────────────────────────────────────────────────────────────────────────────
# BÖLÜM A — VERİ DENETİMİ (uydurma yok: dosya sistemi + ağ gerçekten yoklanıyor)
# ─────────────────────────────────────────────────────────────────────────────
def bolum_a():
    print("=" * 100)
    print("BÖLÜM A — FUNDING VERİSİ VAR MI? (ölçüm, iddia değil)")
    print("=" * 100)
    have, miss = [], []
    for c in COINS:
        p = f"data/{c}_funding.csv"
        (have if os.path.exists(p) else miss).append(c)
    print(f"  data/*_funding.csv  : var={len(have)}  yok={len(miss)}   (fetch_funding.py'nin yazacağı yol)")
    if have:
        print(f"    var olanlar: {', '.join(have)}")
    # repo genelinde herhangi bir funding CSV'si
    hits = []
    for root, _d, files in os.walk("."):
        if ".git" in root:
            continue
        for f in files:
            if "funding" in f.lower() and f.lower().endswith(".csv"):
                hits.append(os.path.join(root, f))
    print(f"  repo genelinde funding CSV: {len(hits)} adet {hits if hits else ''}")
    print()
    print("  AĞ (bu oturumda ölçüldü, agent-proxy günlüğünden — POLİTİKA REDDİ, yeniden denenmez):")
    print("    contract.mexc.com:443     → CONNECT 403 (policy denial)   [MEXC funding history]")
    print("    fapi.binance.com:443      → CONNECT 403 (policy denial)   [Binance funding history]")
    print("    data.binance.vision:443   → CONNECT 403 (policy denial)   [aylık fundingRate zip]")
    print("  → funding geçmişi bu konteynerde ÇEKİLEMEZ. Veri VPS'ten gelmek zorunda.")
    return len(have)


# ─────────────────────────────────────────────────────────────────────────────
# BÖLÜM B — ANKOR DOĞRULAMA (araç bozuksa her şey geçersiz)
# ─────────────────────────────────────────────────────────────────────────────
def anchor_trades(source):
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    tr = []
    for c in DB.DONCH:
        tr += [(*t, "DONCH") for t in DB.gen("donchian", fast_bt.load(c, source=source))]
    for c in DB.SQZ:
        tr += [(*t, "SQZ") for t in DB.gen("squeeze", fast_bt.load(c, source=source))]
    for c in DB.BB_COINS:
        tr += [(*t, "BB") for t in DB.gen_bb(fast_bt.load(c, source=source))]
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(tr, f)
    return tr


def seat_select(trades):
    """DB.seat_select ile AYNI mantık ama etiketi taşır (kimin koltuk bulduğunu ölçmek için).
    Giriş sırasına göre kronolojik; eşitlikte listedeki sıra kazanır → sleeve sırası
    DONCH → SQZ → BB → YENİ olacak şekilde çağrılır (yeni kol asla mevcut işlemi öne geçemez)."""
    import heapq
    ev = sorted(range(len(trades)), key=lambda k: trades[k][0])   # kararlı: eşitlikte orijinal sıra
    openh = []
    taken = []
    ctr = 0
    for k in ev:
        entry_ns, exit_ts, R, slp, tag = trades[k]
        while openh and openh[0][0].value <= entry_ns:
            heapq.heappop(openh)
        if len(openh) < MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((exit_ts, R, slp, tag))
    return sorted(taken, key=lambda t: t[0])


def dollars(taken):
    if not taken:
        return 0.0, np.array([]), []
    r = np.array([t[1] for t in taken])
    slp = np.array([t[2] for t in taken])
    eff = np.minimum(RISKF, CAP * slp)
    pnl = r * eff * BAL0
    exits = [pd.Timestamp(t[0]) for t in taken]
    return pnl.sum(), pnl, exits


def maxdd_worstmonth(pnl, exits):
    eq = BAL0 + np.cumsum(pnl)
    eq = np.concatenate([[BAL0], eq])
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max() * 100
    dfm = pd.DataFrame({"pnl": pnl, "m": [x.tz_localize(None).to_period("M") for x in exits]})
    mon = dfm.groupby("m")["pnl"].sum() / BAL0 * 100
    return dd, mon


def bolum_b(source):
    print()
    print("=" * 100)
    print("BÖLÜM B — ANKOR DOĞRULAMA (zorunlu: 1579 işlem / $+1420.66)")
    print("=" * 100)
    base = anchor_trades(source)
    taken = seat_select(base)
    tot, pnl, exits = dollars(taken)
    r = np.array([t[1] for t in taken])
    dd, mon = maxdd_worstmonth(pnl, exits)
    yr = np.array([x.year for x in exits])
    pf = r[r > 0].sum() / -r[r < 0].sum()
    print(f"  {len(taken)} işlem | PF {pf:.2f} | ort {r.mean():+.3f}R | toplam ${tot:+.2f} "
          f"| maxDD {dd:.1f}% | en kötü ay {mon.min():+.1f}% | poz-ay {(mon > 0).mean()*100:.0f}%")
    print("  yıl-yıl: " + "  ".join(f"{y}:${pnl[yr == y].sum():+.0f}" for y in sorted(set(yr))))
    ok = (len(taken) == 1579) and abs(tot - 1420.66) < 0.5
    print(f"  DOĞRULAMA: {'✅ GEÇTİ (araç sağlam)' if ok else '❌ BAŞARISIZ — SONUÇLAR GEÇERSİZ'}")
    if not ok:
        raise SystemExit("ankor tutmadı")
    return base, tot, pnl, exits, dd, mon


# ─────────────────────────────────────────────────────────────────────────────
# BÖLÜM C — HAYALET KOL: KAPASİTE + GEREKEN EDGE
#   Yön RASTGELE. Bu bir edge testi DEĞİL; bir KAPASİTE ve BAR-YÜKSEKLİĞİ ölçümü.
# ─────────────────────────────────────────────────────────────────────────────
def prep(source):
    """Her coin için 1h bar dizileri + ATR + funding-saati bar indeksleri."""
    out = {}
    for c in COINS:
        try:
            m = fast_bt.load(c, source=source)
        except SystemExit:
            continue
        d = fast_bt.resample(m, "1h")
        a = atr_fn(d["high"], d["low"], d["close"], 14).values
        idx = d.index
        fbar = np.where(np.isin(idx.hour, FUND_HOURS))[0]
        fbar = fbar[(fbar >= 260) & (fbar < len(d) - 1)]
        out[c] = dict(hi=d["high"].values, lo=d["low"].values, cl=d["close"].values,
                      idx=idx, atr=a, fbar=fbar,
                      ts_ns=idx.values.astype("datetime64[ns]").astype(np.int64))
    return out


def sim_signals(D, sig_i, sig_d, rr, mh, tag):
    """sig_i: bar indeksleri (artan), sig_d: yönler. occ guard ZORUNLU (netted mod)."""
    hi, lo, cl, idx, a_ser = D["hi"], D["lo"], D["cl"], D["idx"], D["atr"]
    n = len(cl)
    out = []
    occ = -1
    for i, d_ in zip(sig_i, sig_d):
        if i <= occ:
            continue
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        e = cl[i]
        sld = 2.0 * a                     # SL 2×ATR (görev metnindeki gibi)
        slp = e - d_ * sld
        tp = e + d_ * rr * sld
        ep = None
        j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp:
                    ep = slp; break
                if hi[j] >= tp:
                    ep = tp; break
            else:
                if hi[j] >= slp:
                    ep = slp; break
                if lo[j] <= tp:
                    ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e, f"{tag}#{d_}"))   # yön etikete gömülü
        occ = j
    return out


def phantom(P, p_fire, rr, mh, seed, mode):
    """mode='bagimsiz' : her coin kendi başına tetiklenir (funding'in coin-özgü olduğu varsayımı)
       mode='piyasa'   : funding piyasa-geneli → aynı damgada TÜM coinler AYNI yönde tetiklenir"""
    rng = np.random.default_rng(seed)
    trades = []
    if mode == "piyasa":
        # ortak funding damgası ızgarası (BTC'nin funding barları), ortak yön
        grid = P["BTC"]["idx"][P["BTC"]["fbar"]]
        fire = rng.random(len(grid)) < p_fire
        dirs = np.where(rng.random(len(grid)) < 0.5, 1, -1)
        fire_map = {int(t.value): int(dd) for t, f, dd in zip(grid, fire, dirs) if f}
        for c, D in P.items():
            si, sd = [], []
            for i in D["fbar"]:
                key = int(D["idx"][i].value)
                if key in fire_map:
                    si.append(int(i)); sd.append(fire_map[key])
            trades += sim_signals(D, si, sd, rr, mh, f"NEW:{c}")
    else:
        for c, D in P.items():
            fb = D["fbar"]
            m = rng.random(len(fb)) < p_fire
            si = fb[m].astype(int)
            sd = np.where(rng.random(m.sum()) < 0.5, 1, -1)
            trades += sim_signals(D, si, sd, rr, mh, f"NEW:{c}")
    return trades


def bolum_c(P, base, base_tot):
    print()
    print("=" * 100)
    print("BÖLÜM C — KAPASİTE ve GEREKEN EDGE (hayalet kol: funding TAKVİMİ + UÇ FREKANSI, yön RASTGELE)")
    print("=" * 100)
    print("  Yön rastgele → ortalama R ≈ −komisyon. Bu bir EDGE testi DEĞİL; ölçülen:")
    print("  (a) sinyalin kaçı KOLTUK buluyor  (b) ankordan kaç işlem SİLİNİYOR ve kaç $ kaybediliyor")
    print("  (c) +$28 barını geçmek için funding sinyalinin GEREKEN ort R'si ve GEREKEN WR'si")
    print()
    print(f"  {'mod':9s} {'p':>5s} {'rr':>4s} {'mh':>4s} {'sinyal':>7s} {'koltuk':>7s} {'%':>4s} "
          f"{'ankor-n':>8s} {'ankorΔ$':>8s} {'$/R':>6s} {'gerekR':>7s} {'gerekWR':>8s} {'iyimserTavan$':>13s}")
    rows = []
    for mode in ("bagimsiz", "piyasa"):
        for p_fire in (0.05, 0.10, 0.20):
            for rr in (2.5,):
                for mh in (48,):
                    agg = []
                    for seed in (1, 2, 3):
                        ph = phantom(P, p_fire, rr, mh, seed, mode)
                        allt = base + ph          # YENİ kol EN SONA → eşitlikte ankor kazanır
                        taken = seat_select(allt)
                        new_t = [t for t in taken if t[3].startswith("NEW")]
                        anc_t = [t for t in taken if not t[3].startswith("NEW")]
                        a_tot, _, _ = dollars(anc_t)
                        slp = np.array([t[2] for t in new_t]) if new_t else np.array([1.0])
                        eff = np.minimum(RISKF, CAP * slp)
                        dpr = eff.mean() * BAL0                 # 1R kaç dolar
                        agg.append((len(ph), len(new_t), len(anc_t), a_tot - base_tot, dpr,
                                    float(np.mean(2 * FEE / slp))))
                    A = np.array(agg, dtype=float)
                    n_sig, n_seat, n_anc, d_anc, dpr, cfee = A.mean(axis=0)
                    r_req = (BAR_DOLLAR - d_anc) / max(n_seat * dpr, 1e-9)
                    wr_req = (r_req + 1.0 + cfee) / (rr + 1.0)
                    ceil = n_seat * ANCHOR_MEAN_R * dpr + d_anc
                    rows.append(dict(mode=mode, p=p_fire, rr=rr, mh=mh, n_sig=n_sig, n_seat=n_seat,
                                     n_anc=n_anc, d_anc=d_anc, dpr=dpr, r_req=r_req,
                                     wr_req=wr_req, ceil=ceil))
                    print(f"  {mode:9s} {p_fire:>5.2f} {rr:>4.1f} {mh:>4d} {n_sig:>7.0f} {n_seat:>7.0f} "
                          f"{n_seat/max(n_sig,1)*100:>3.0f}% {n_anc:>8.0f} {d_anc:>+8.1f} {dpr:>6.2f} "
                          f"{r_req:>+7.3f} {wr_req:>7.1%} {ceil:>+13.0f}")
    print()
    print("  ── C2: SIFIR-EDGE'Lİ yeni kolun YER DEĞİŞTİRME (displacement) HASARI ──")
    print("  Yeni kolun R'si 0 kabul edilir (hiç kazanmaz/kaybetmez). Geriye SADECE koltuk çalması")
    print("  kalır. Ön-kayıtlı barın 'hiçbir yıl >%10 kötüleşmeyecek / en kötü ay kötüleşmeyecek /")
    print("  maxDD +2 puandan fazla artmayacak' maddeleri BU HASARA karşı test ediliyor.")
    base_taken = seat_select(base)
    b_tot, b_pnl, b_ex = dollars(base_taken)
    b_yr = np.array([x.year for x in b_ex])
    b_dd, b_mon = maxdd_worstmonth(b_pnl, b_ex)
    b_years = {y: b_pnl[b_yr == y].sum() for y in sorted(set(b_yr))}
    print(f"  {'mod':9s} {'p':>5s} | " + " ".join(f"{y:>7d}" for y in b_years) +
          f" | {'maxDD':>6s} {'ΔDD':>6s} {'enKötüAy':>9s} {'Δay':>6s} {'barKırıldı':>11s}")
    print(f"  {'ANKOR':9s} {'—':>5s} | " + " ".join(f"{b_years[y]:>+7.0f}" for y in b_years) +
          f" | {b_dd:>5.1f}% {'—':>6s} {b_mon.min():>+8.1f}% {'—':>6s} {'—':>11s}")
    for mode, p_fire in (("piyasa", 0.05), ("piyasa", 0.10), ("bagimsiz", 0.05), ("bagimsiz", 0.10)):
        acc_y = {y: [] for y in b_years}
        acc_dd, acc_mon = [], []
        for seed in (1, 2, 3):
            ph = phantom(P, p_fire, 2.5, 48, seed, mode)
            ph0 = [(a, b, 0.0, d, e) for (a, b, _c, d, e) in ph]   # SIFIR edge
            tk = seat_select(base + ph0)
            _t, pn, ex = dollars(tk)
            yy = np.array([x.year for x in ex])
            for y in acc_y:
                acc_y[y].append(pn[yy == y].sum())
            dd_, mon_ = maxdd_worstmonth(pn, ex)
            acc_dd.append(dd_); acc_mon.append(mon_.min())
        ys = {y: float(np.mean(v)) for y, v in acc_y.items()}
        dd_ = float(np.mean(acc_dd)); wm = float(np.mean(acc_mon))
        worst_pct = min((ys[y] - b_years[y]) / abs(b_years[y]) * 100 for y in b_years)
        broken = []
        if worst_pct < -10.0:
            broken.append(f"YIL{worst_pct:+.0f}%")
        if dd_ - b_dd > 2.0:
            broken.append("maxDD")
        if wm < b_mon.min() - 1e-9:
            broken.append("enKötüAy")
        print(f"  {mode:9s} {p_fire:>5.2f} | " + " ".join(f"{ys[y]:>+7.0f}" for y in b_years) +
              f" | {dd_:>5.1f}% {dd_-b_dd:>+5.1f}p {wm:>+8.1f}% {wm-b_mon.min():>+5.1f}p "
              f" {','.join(broken) if broken else 'temiz':>10s}")

    print()
    print("  ── C3: BARIN GERÇEK YÜKSEKLİĞİ — yeni kola SABİT bir edge (Δ R) eklenirse ne olur? ──")
    print("  Hayalet kolun her işlemine +Δ R ekleniyor (dağılımın şekli aynı, ortalaması kayıyor).")
    print("  Ön-kayıtlı barın DÖRT $/risk maddesi birden kontrol ediliyor. Referans: ankor +0.237R.")
    print(f"  {'mod':9s} {'p/mh':>7s} {'ΔR':>6s} {'kolun$':>8s} {'toplamΔ$':>9s} {'enKötüYıl%':>11s} "
          f"{'ΔmaxDD':>7s} {'ΔenKötüAy':>10s} {'BAR':>16s}")
    print("  SEYREK varyantlar da dahil (p=0.01 → coin başına ~11 sinyal/yıl) — saman adam olmasın.")
    for mode, p_fire, mh_ in (("piyasa", 0.01, 48), ("piyasa", 0.02, 48), ("piyasa", 0.05, 24),
                              ("piyasa", 0.10, 48), ("bagimsiz", 0.05, 48)):
        for dR in (0.0, 0.10, 0.237, 0.40):
            acc = []
            for seed in (1, 2, 3):
                ph = phantom(P, p_fire, 2.5, mh_, seed, mode)
                phd = [(a, b, c + dR, d, e) for (a, b, c, d, e) in ph]
                tk = seat_select(base + phd)
                tot_, pn, ex = dollars(tk)
                yy = np.array([x.year for x in ex])
                dd_, mon_ = maxdd_worstmonth(pn, ex)
                new_only = [t for t in tk if t[3].startswith("NEW")]
                nt, _, _ = dollars(new_only)
                wy = min((pn[yy == y].sum() - b_years[y]) / abs(b_years[y]) * 100 for y in b_years)
                acc.append((nt, tot_ - b_tot, wy, dd_ - b_dd, mon_.min() - b_mon.min()))
            nt, dtot, wy, ddd, dm = np.array(acc, dtype=float).mean(axis=0)
            ok = (dtot > BAR_DOLLAR) and (wy > -10.0) and (ddd <= 2.0) and (dm >= -1e-9)
            fails = []
            if dtot <= BAR_DOLLAR: fails.append("Δ$")
            if wy <= -10.0: fails.append("yıl")
            if ddd > 2.0: fails.append("DD")
            if dm < -1e-9: fails.append("ay")
            print(f"  {mode:9s} {p_fire:>4.2f}/{mh_:<2d} {dR:>+6.3f} {nt:>+8.0f} {dtot:>+9.0f} {wy:>+10.1f}% "
                  f"{ddd:>+6.1f}p {dm:>+9.1f}p {('✅ GEÇTİ' if ok else 'RED:' + ','.join(fails)):>16s}")

    print()
    print("  DOZ-YANIT (rr ekseni, mod=piyasa, p=0.10 — 5 nokta, monotonluk aranıyor):")
    print(f"  {'rr':>5s} {'sinyal':>7s} {'koltuk':>7s} {'ankorΔ$':>8s} {'$/R':>6s} {'gerekR':>7s} {'gerekWR':>8s}")
    dose = []
    for rr in (1.5, 2.0, 2.5, 3.0, 3.5):
        agg = []
        for seed in (1, 2, 3):
            ph = phantom(P, 0.10, rr, 48, seed, "piyasa")
            taken = seat_select(base + ph)
            new_t = [t for t in taken if t[3].startswith("NEW")]
            anc_t = [t for t in taken if not t[3].startswith("NEW")]
            a_tot, _, _ = dollars(anc_t)
            slp = np.array([t[2] for t in new_t]) if new_t else np.array([1.0])
            eff = np.minimum(RISKF, CAP * slp)
            agg.append((len(ph), len(new_t), a_tot - base_tot, eff.mean() * BAL0,
                        float(np.mean(2 * FEE / slp))))
        A = np.array(agg, dtype=float).mean(axis=0)
        n_sig, n_seat, d_anc, dpr, cfee = A
        r_req = (BAR_DOLLAR - d_anc) / max(n_seat * dpr, 1e-9)
        wr_req = (r_req + 1.0 + cfee) / (rr + 1.0)
        dose.append((rr, wr_req))
        print(f"  {rr:>5.1f} {n_sig:>7.0f} {n_seat:>7.0f} {d_anc:>+8.1f} {dpr:>6.2f} "
              f"{r_req:>+7.3f} {wr_req:>7.1%}")
    return rows, dose


# ─────────────────────────────────────────────────────────────────────────────
# BÖLÜM D — EŞZAMANLILIK ve KORELASYON YAPISI
# ─────────────────────────────────────────────────────────────────────────────
def momentum_fade_proxy(P, rr=2.5, mh=48, z=1.2816):
    """VEKİL (proxy) — funding EDGE'i DEĞİL. Gerekçe: perp funding oranı, perp-index bazına ve
    dolayısıyla son dönem momentumuna güçlü bağlıdır. Funding uçlarını fade etmek, İSTATİSTİKSEL
    OLARAK momentum uçlarını fade etmeye YAKINDIR. Buradaki amaç EDGE ölçmek değil, yeni kolun
    ankorla KORELASYON YAPISINI (işaret ve büyüklük) tahmin etmektir."""
    trades = []
    for c, D in P.items():
        cl = pd.Series(D["cl"], index=D["idx"])
        m3 = cl / cl.shift(72) - 1.0                      # son 3 günün getirisi (tamamlanmış)
        mu = m3.rolling(720, min_periods=240).mean()
        sd = m3.rolling(720, min_periods=240).std()
        zz = ((m3 - mu) / sd).values
        si, sd_ = [], []
        for i in D["fbar"]:
            v = zz[i]
            if not np.isfinite(v):
                continue
            if v >= z:
                si.append(int(i)); sd_.append(-1)         # aşırı pozitif "funding" → SHORT
            elif v <= -z:
                si.append(int(i)); sd_.append(+1)
        trades += sim_signals(D, si, sd_, rr, mh, f"PROXY:{c}")
    return trades


def bolum_d(P, base, base_pnl, base_exits):
    print()
    print("=" * 100)
    print("BÖLÜM D — EŞZAMANLILIK ve KORELASYON")
    print("=" * 100)
    # 1) çapraz coin getiri korelasyonu (log-getiri üzerinden, FİYAT SEVİYESİ DEĞİL)
    px = pd.DataFrame({c: pd.Series(P[c]["cl"], index=P[c]["idx"]) for c in P})
    lr1 = np.log(px).diff()
    lrd = np.log(px.resample("1D").last()).diff()
    for name, L in (("1h", lr1), ("1D", lrd)):
        C = L.corr().values
        iu = np.triu_indices_from(C, k=1)
        v = C[iu]
        print(f"  çapraz-coin log-getiri korelasyonu ({name}): ort ikili {np.nanmean(v):.3f} "
              f"| medyan {np.nanmedian(v):.3f} | min {np.nanmin(v):.3f} | max {np.nanmax(v):.3f}")
    n_eff = len(P) / (1 + (len(P) - 1) * float(np.nanmean(lrd.corr().values[np.triu_indices(len(P), 1)])))
    print(f"  → 22 coin AYNI YÖNDE eşzamanlı açılırsa etkin bağımsız bahis sayısı ≈ {n_eff:.2f}")
    print(f"    (yani 7 koltuk dolsa bile risk ~{7/n_eff:.1f}× tek pozisyona denk — çeşitlendirme YOK)")

    # 2) VEKİL kol: momentum-uç fade → ankorla aylık PnL korelasyonu
    prox = momentum_fade_proxy(P)
    tk = seat_select(prox)                                # kendi başına (koltuk yarışı yalnız kendi içinde)
    p_tot, p_pnl, p_ex = dollars(tk)
    pr = np.array([t[1] for t in tk])
    pf = pr[pr > 0].sum() / max(-pr[pr < 0].sum(), 1e-9)
    print()
    print(f"  VEKİL KOL (momentum-uç fade, z≥1.28, SL2ATR rr2.5 mh48, 22 coin, occ):")
    print(f"    n={len(tk)} | WR {(pr>0).mean()*100:.0f}% | PF {pf:.2f} | ort {pr.mean():+.3f}R | ${p_tot:+.0f}")
    tr_m = np.array([x >= SPLIT for x in p_ex])
    print(f"    TRAIN(<2025) ${p_pnl[~tr_m].sum():+.0f} (n{(~tr_m).sum()})  |  "
          f"TEST(≥2025) ${p_pnl[tr_m].sum():+.0f} (n{tr_m.sum()})")
    # ── DÖRT SAHTELİK TESTİ (VEKİL kol üzerinde; funding verisi olsaydı aynı iskelet kullanılacaktı) ──
    print()
    print("  DÖRT SAHTELİK TESTİ — VEKİL kol (ham sinyaller, koltuk seçimi YOK: tetikleyici kalitesi)")
    coins_r = {}
    for t in prox:
        c = t[4].split(":")[1].split("#")[0]
        coins_r.setdefault(c, []).append(t[2])
    pos = sum(1 for c, v in coins_r.items() if np.mean(v) > 0)
    N = len(coins_r)
    k = min(pos, N - pos)
    p2 = 2.0 * sum(math.comb(N, i) for i in range(0, k + 1)) / (2.0 ** N)
    print(f"   (a) İŞARET: {pos}/{N} coinde ort R > 0  → iki yönlü binom p = {min(p2,1.0):.4f}")
    allR = np.array([t[2] for t in prox])
    z = allR.mean() / (allR.std(ddof=1) / math.sqrt(len(allR)))
    print(f"   (b) HAVUZLANMIŞ: n={len(allR)} ort R {allR.mean():+.4f} ± {allR.std(ddof=1)/math.sqrt(len(allR)):.4f}"
          f"  → z = {z:+.2f}")
    for nm, dsel in (("LONG", 1), ("SHORT", -1)):
        sub = np.array([t[2] for t in prox if t[4].endswith(f"#{dsel}")])
        if len(sub):
            zz = sub.mean() / (sub.std(ddof=1) / math.sqrt(len(sub)))
            print(f"   (c) YÖN {nm:5s}: n={len(sub):>5d} ort R {sub.mean():+.4f} z {zz:+.2f}")
    for nm, sel in (("TRAIN(<2025)", False), ("TEST(>=2025)", True)):
        sub = np.array([t[2] for t in prox
                        if (pd.Timestamp(t[0], tz="UTC") >= SPLIT) == sel])
        zz = sub.mean() / (sub.std(ddof=1) / math.sqrt(len(sub)))
        print(f"   (d) DÖNEM {nm:12s}: n={len(sub):>5d} ort R {sub.mean():+.4f} z {zz:+.2f}")

    ma = pd.Series(base_pnl, index=[x.tz_localize(None).to_period("M") for x in base_exits]).groupby(level=0).sum()
    mb = pd.Series(p_pnl, index=[x.tz_localize(None).to_period("M") for x in p_ex]).groupby(level=0).sum()
    j = pd.concat([ma.rename("ankor"), mb.rename("vekil")], axis=1).fillna(0.0)
    print(f"    AYLIK PnL KORELASYONU (ankor ↔ vekil kol): {j['ankor'].corr(j['vekil']):+.3f}  "
          f"(n={len(j)} ay)")
    print("    NOT: bu bir VEKİL. Gerçek funding kolunun korelasyonu funding verisi olmadan")
    print("    ÖLÇÜLEMEZ; bu sayı yalnızca işaret/büyüklük TAHMİNİDİR.")

    # 3) eşzamanlılık: vekil kol aynı 8h penceresinde kaç coinde tetikleniyor?
    ent = pd.Series(1, index=pd.DatetimeIndex([pd.Timestamp(t[0]) for t in tk]))
    # giriş zamanı yerine sinyal kümelenmesini ham sinyalden ölç
    raw_ts = pd.DatetimeIndex([pd.Timestamp(t[0], tz="UTC") for t in prox])
    grp = pd.Series(1, index=raw_ts).groupby(pd.Grouper(freq="8h")).sum()
    grp = grp[grp > 0]
    print()
    print(f"  KÜMELENME (vekil ham sinyal, 8h kova): ort {grp.mean():.2f} coin/kova | "
          f"medyan {grp.median():.0f} | %90 dilim {grp.quantile(0.9):.0f} | max {grp.max():.0f}")
    print(f"    kovaların %{(grp >= 7).mean()*100:.0f}'inde ≥7 coin aynı anda tetikleniyor "
          f"→ 7 koltuğun TAMAMI tek bir yöne gider")
    return j


# ─────────────────────────────────────────────────────────────────────────────
def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    n_have = bolum_a()
    base, base_tot, base_pnl, base_exits, base_dd, base_mon = bolum_b(source)
    print("\n  22 coin 1h veri yükleniyor...")
    P = prep(source)
    print(f"  {len(P)} coin hazır.")
    rows, dose = bolum_c(P, base, base_tot)
    j = bolum_d(P, base, base_pnl, base_exits)

    print()
    print("=" * 100)
    print("BÖLÜM E — KARAR")
    print("=" * 100)
    if n_have == 0:
        print("  1) FUNDING GEÇMİŞ VERİSİ YOK ve bu konteynerden ÇEKİLEMİYOR (3 host da 403 politika reddi).")
        print("     → funding sinyalinin EDGE'i BUGÜN ÖLÇÜLEMEZ. Uydurulmayacak.")
    print("  2) Ölçülenler yukarıda. Ön-kayıtlı barın (Δ$>+28, hiçbir yıl >%10 kötüleşmeyecek,")
    print("     maxDD +2 puandan fazla artmayacak, en kötü ay kötüleşmeyecek, 4 sahtelik testi)")
    print("     TAMAMI için funding verisi ŞART; dört sahtelik testinden (d) DÖNEM AYRIMI, MEXC")
    print("     funding geçmişi (son 1000 kayıt ≈ 11 ay, hepsi ≥2025-08) ile YAPILAMAZ: TRAIN boş.")
    print("  3) POZİTİF İDDİA: YOK. Bu tur bir RED/AÇIK-KALDI raporudur.")


if __name__ == "__main__":
    main()
