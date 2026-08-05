"""
nk_range.py — ARALIK (RANGE) KENARI ORTALAMAYA DÖNÜŞ: kırılımı DEĞİL, kenardan REDDİ al.

SORU
  Bizde ZATEN çalışan tek ortalamaya-dönüş ailesi BB/LTC hafta-sonu kolu (+$135, 4/4 yıl+).
  Bu ailenin bu sistemde işlediğinin kanıtı var. Aynı fikir DAHA GENİŞ uygulanabilir mi?
  Yeni kol hiçbir mevcut işlemi SİLMEZ (filtre değil), BOŞ KOLTUKLARI doldurur.

fade_test.py'DEN FARKI (ledger: "breakout fade: mekanizma GERÇEK, kâr YOK → RED")
  fade_test KIRILIMI fade ediyordu: close > kanal_üst (yani kanal KIRILDI) → short.
  Burada kırılım OLMAYAN yapı alınıyor: fitil kenara dokunuyor/aşıyor AMA kapanış
  aralığın İÇİNDE kalıyor = REDDEDİLMİŞ kenar. Kırılan barlar AÇIKÇA dışlanıyor.
  (Kırılanları donchian zaten alıyor; bu kol onun tamamlayıcısı, rakibi değil.)

ARALIK TESPİTİ — t ANINDA BİLİNEN BİLGİYLE (lookahead tuzağının tam yeri)
  hh = son N barın (i-N..i-1, shift(1)) en yükseği · ll = aynı pencerenin en düşüğü.
  Genişlik ölçüsü w = (hh-ll)/ATR(i). Üç DETEKTÖR ayrı ayrı taranıyor:
    A) w <= eşik                       (mutlak, ATR-normalize dar aralık)
    B) w'nin GEÇMİŞ 500 bara göre yüzdelik sırası <= q   (rolling rank, kendini normalize eder)
    C) ADX(i) < eşik                   (trendsizlik)
  Hiçbiri geleceğe bakmıyor: hh/ll shift(1)'li, ATR/ADX bar i'de tamamlanmış, giriş close[i].
  "Sonradan aralık olduğu anlaşılan" bölge seçilmiyor.

GİRİŞ
  SHORT: high[i] >= hh  (üst kenara dokundu/aştı)  VE  close[i] < hh  (içeri kapandı) → RED
  LONG : low[i]  <= ll                              VE  close[i] > ll                 → RED
  İkisi birden olan bar (dış-bar) BELİRSİZ → atlanır. Kapanışın aralık içinde olması şart.

DÖRT SAHTELİK TESTİ (hepsi raporlanıyor)
  (a) İŞARET: 22 coin × 3 tf hücrede kaçı pozitif + EŞLEŞTİRİLMİŞ kontrol (aynı barlarda
      TERS yön = "kenarda güç satın al"). Eşleştirilmiş null tam olarak 0.5'tir → temiz binom.
  (b) Havuzlanmış ortalama R + z
  (c) YÖN AYRIMI: long/short ayrı. Etki sadece long'daysa piyasa betası → RED.
  (d) DÖNEM: TRAIN(<2025) / TEST(>=2025) aynı işaret mi.
  + DOZ-YANIT (N, üç detektörün eşiği, rr, SL) + ANKOR + AYLIK KORELASYON.

ÖN-KAYITLI BAR (gevşetilmez, bugün altı ekseni reddeden barın aynısı)
  Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek · maxDD >2 puan artmayacak ·
  EN KÖTÜ AY kötüleşmeyecek · dört sahtelik testi aynı yönü gösterecek.

Kullanım:  py nk_range.py local [probe|main|dose|anchor|all]
"""
import os
import pickle
import sys
from math import comb

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import adx as adx_fn
from indicators import atr as atr_fn

ALL22 = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
USED = set(A.DONCH) | set(A.SQZ) | set(A.BB_COINS)
FREE = [c for c in ALL22 if c not in USED]          # netted çakışma YOK
TFS = ["1h", "2h", "4h"]
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")

BAL0 = A.BAL0; FEE = A.FEE; RISKF = A.RISKF; CAP = A.CAP
START = 520          # rank penceresi 500 → tüm detektörler AYNI barlarda karşılaştırılsın
RANKW = 500
NS = (10, 15, 20, 30, 40, 60)

# merkez konfigürasyon (BB ailesinin canlı parametreleri = ön bilgi, keyfi değil)
C_N, C_RR, C_SL, C_MH = 40, 1.667, 3.0, 48
C_DET, C_THR = "rank", 0.40

SCRATCH = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
RAW = {}
_PREP = {}


# ───────────────────────────────── veri / hazırlık ─────────────────────────────────
def load_raw(source):
    for c in ALL22:
        try:
            RAW[c] = fast_bt.load(c, source=source)
        except Exception as e:                       # noqa: BLE001
            print(f"  {c}: yüklenemedi ({e})")


def prep(coin, tf):
    """Bar-bazlı diziler + N başına kanal. HEPSİ shift(1)'li (lookahead yok)."""
    key = (coin, tf)
    if key in _PREP:
        return _PREP[key]
    d = fast_bt.resample(RAW[coin], tf)
    if len(d) < START + 100:
        _PREP[key] = None
        return None
    hi = d["high"].values.astype(float); lo = d["low"].values.astype(float)
    cl = d["close"].values.astype(float)
    at = atr_fn(d["high"], d["low"], d["close"], 14).values.astype(float)
    ax = adx_fn(d["high"], d["low"], d["close"], 14).values.astype(float)
    P = dict(hi=hi, lo=lo, cl=cl, idx=d.index, n=len(cl), atr=at, adx=ax, ch={})
    with np.errstate(invalid="ignore", divide="ignore"):
        for N in NS:
            hh = d["high"].rolling(N).max().shift(1).values.astype(float)
            ll = d["low"].rolling(N).min().shift(1).values.astype(float)
            w = (hh - ll) / at                       # ATR-normalize aralık genişliği
            # yüzdelik sıra: SADECE bar i ve öncesi (rolling, ileri bakış yok)
            wr = pd.Series(w).rolling(RANKW, min_periods=200).rank(pct=True).values.astype(float)
            P["ch"][N] = (hh, ll, w, wr)
    _PREP[key] = P
    return P


def signals(P, N, det, thr, wknd=0):
    """Kenardan RED maskeleri + rejim kapısı. Dönüş: (short_mask, long_mask).
    wknd: 0=tüm günler · 1=YALNIZ hafta sonu (BB kolunun canlı kısıtı) · 2=yalnız hafta içi.
    Takvim kapısı ÜRETİM SIRASINDA uygulanır (elenen sinyal occ'u meşgul etmez)."""
    hh, ll, w, wr = P["ch"][N]
    hi, lo, cl = P["hi"], P["lo"], P["cl"]
    with np.errstate(invalid="ignore"):
        inside = (cl < hh) & (cl > ll)               # KIRILIM DEĞİL: kapanış aralık içinde
        rej_up = (hi >= hh) & inside                 # üst kenar reddi  → SHORT
        rej_dn = (lo <= ll) & inside                 # alt kenar reddi  → LONG
        amb = rej_up & rej_dn                        # dış-bar: belirsiz
        if det == "w":
            reg = w <= thr
        elif det == "rank":
            reg = wr <= thr
        elif det == "adx":
            reg = P["adx"] < thr
        elif det == "none":
            reg = np.ones(P["n"], dtype=bool)
        else:
            raise ValueError(det)
        reg = reg & np.isfinite(w) & np.isfinite(P["atr"]) & (P["atr"] > 0)
        if wknd:
            we = P["idx"].weekday.values >= 5
            reg = reg & (we if wknd == 1 else ~we)
    return (rej_up & ~amb & reg), (rej_dn & ~amb & reg)


def sim(P, sm, lm, rr, sl_a, mh, flip=False, force_idx=None):
    """occ'lu üretim (MEXC netted: sembol başına tek pozisyon). Koltuk seçimi YOK.
    force_idx verilirse AYNI giriş barları kullanılır (eşleştirilmiş kontrol için)."""
    hi, lo, cl, at, idx, n = P["hi"], P["lo"], P["cl"], P["atr"], P["idx"], P["n"]
    cand = np.where(sm | lm)[0] if force_idx is None else force_idx
    out = []
    occ = -1
    for i in cand:
        i = int(i)
        if i < START or i >= n - 1:
            continue
        if force_idx is None and i <= occ:
            continue
        a = at[i]
        if not np.isfinite(a) or a <= 0:
            continue
        d_ = -1 if sm[i] else 1
        if flip:
            d_ = -d_
        e = cl[i]; sld = sl_a * a
        slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((i, idx[i], idx[j], R, sld / e, d_))
        occ = j
    return out


def run_universe(coins, tfs, N, det, thr, rr, sl_a, mh, paired=False, wknd=0, minn=15):
    """Tüm (coin,tf) hücrelerinde koştur. paired=True ise aynı barlarda TERS yön de."""
    cells = []; fade = []; foll = []
    for tf in tfs:
        for c in coins:
            P = prep(c, tf)
            if P is None:
                continue
            sm, lm = signals(P, N, det, thr, wknd)
            tr = sim(P, sm, lm, rr, sl_a, mh)
            if len(tr) < minn:
                continue
            rec = [dict(coin=c, tf=tf, entry=t[1], exit=t[2], R=t[3], slp=t[4], dir=t[5]) for t in tr]
            fade += rec
            cell = dict(coin=c, tf=tf, n=len(tr), mR=float(np.mean([t[3] for t in tr])))
            if paired:
                idxs = [t[0] for t in tr]
                tr2 = sim(P, sm, lm, rr, sl_a, mh, flip=True, force_idx=idxs)
                foll += [dict(coin=c, tf=tf, entry=t[1], exit=t[2], R=t[3], slp=t[4], dir=t[5]) for t in tr2]
                cell["mR_flip"] = float(np.mean([t[3] for t in tr2]))
            cells.append(cell)
    return pd.DataFrame(cells), pd.DataFrame(fade), (pd.DataFrame(foll) if paired else None)


# ───────────────────────────────── istatistik ─────────────────────────────────
def binom_two(w, n):
    if n == 0:
        return 1.0
    if w >= n / 2:
        p = 2 * sum(comb(n, k) for k in range(w, n + 1)) / (2 ** n)
    else:
        p = 2 * sum(comb(n, k) for k in range(0, w + 1)) / (2 ** n)
    return min(1.0, p)


def zstat(r):
    r = np.asarray(r, dtype=float)
    if len(r) < 3:
        return 0.0, 0.0
    return float(r.mean()), float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))


def dollars(df):
    if df is None or not len(df):
        return 0.0
    eff = np.minimum(RISKF, CAP * df["slp"].values)
    return float((df["R"].values * eff * BAL0).sum())


def monthly(df):
    if df is None or not len(df):
        return pd.Series(dtype=float)
    eff = np.minimum(RISKF, CAP * df["slp"].values)
    pnl = df["R"].values * eff * BAL0
    per = [pd.Timestamp(x).tz_localize(None).to_period("M") for x in df["exit"]]
    return pd.Series(pnl, index=per).groupby(level=0).sum()


# ───────────────────────────────── ankor ─────────────────────────────────
def anchor_trades():
    cache = os.path.join(SCRATCH, "nk_range_anchor.pkl")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)
    tr = []
    for c in A.DONCH: tr += A.gen("donchian", RAW[c])
    for c in A.SQZ: tr += A.gen("squeeze", RAW[c])
    for c in A.BB_COINS: tr += A.gen_bb(RAW[c])
    os.makedirs(SCRATCH, exist_ok=True)
    with open(cache, "wb") as f:
        pickle.dump(tr, f)
    return tr


def metrics(taken):
    r = np.array([t[1] for t in taken]); slp = np.array([t[2] for t in taken])
    ex = [pd.Timestamp(t[0]) for t in taken]
    eff = np.minimum(RISKF, CAP * slp); pnl = r * eff * BAL0
    eq = BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum() / BAL0 * 100
    yr = pd.Series(pnl, index=[x.year for x in ex]).groupby(level=0).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), tot=float(pnl.sum()), pf=float(gp / gl) if gl > 0 else float("inf"),
                wr=float((r > 0).mean() * 100),
                dd=float(A.maxdd(np.concatenate([[BAL0], eq]))),
                worst=float(mon.min()), posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()},
                mon=pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum())


def seat_select_idx(trades):
    """A.seat_select ile BİREBİR aynı (aynı sıralama, aynı heap) ama hangi işlemin koltuk
    aldığını da döndürür → yeni kolun mevcut işlemleri GERÇEKTEN yerinden edip etmediğini ölç."""
    import heapq
    ev = sorted(enumerate(trades), key=lambda kv: kv[1][0])
    openh = []; taken = []; ctr = 0
    for k, (entry_ns, exit_ts, R, slp) in ev:
        while openh and openh[0][0].value <= entry_ns:
            heapq.heappop(openh)
        if len(openh) < A.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (exit_ts, ctr, R))
            taken.append((exit_ts, R, slp, k))
    return sorted(taken, key=lambda t: t[0])


def spearman(a, b):
    ra = pd.Series(a).rank().values; rb = pd.Series(b).rank().values
    return float(np.corrcoef(ra, rb)[0, 1])


def sleeve_to_anchor_fmt(df):
    """gen_range çıktısını A.seat_select'in beklediği (entry_ns, exit_ts, R, sl_pct) formatına."""
    return [(pd.Timestamp(e).value, pd.Timestamp(x), float(R), float(s))
            for e, x, R, s in zip(df["entry"], df["exit"], df["R"], df["slp"])]


def verdict(v, b):
    why = []
    if v["tot"] - b["tot"] <= 28:
        why.append(f"kâr yetersiz ({v['tot'] - b['tot']:+.0f}$)")
    for y in sorted(b["yr"]):
        if abs(b["yr"][y]) > 1e-9 and (v["yr"].get(y, 0) - b["yr"][y]) / abs(b["yr"][y]) < -0.10:
            why.append(f"{y} kötüleşti {(v['yr'].get(y, 0) - b['yr'][y]) / abs(b['yr'][y]) * 100:.0f}%")
    if v["dd"] > b["dd"] + 2:
        why.append(f"maxDD {b['dd']:.1f}→{v['dd']:.1f}")
    if v["worst"] < b["worst"] - 0.05:
        why.append(f"en kötü ay {b['worst']:.1f}→{v['worst']:.1f}")
    return why


# ───────────────────────────────── fazlar ─────────────────────────────────
def phase_selftest():
    """ARAÇ KENDİ KONTROL TESTİNİ GEÇMEDEN GÜVENİLMEZ. Dört kontrol:
    1) hh/ll gerçekten [i-N, i-1] penceresinden mi (shift(1) doğrulaması, elle yeniden hesap)
    2) sinyal barı i'nin GELECEK barlarına dokunuluyor mu (giriş = close[i], çıkış j>i)
    3) rejim kapısı (rank) yalnız geçmişe mi bakıyor
    4) PLASEBO: aynı barlarda yön RASTGELE → ortalama R ≈ 0 (fee kadar eksi) olmalı"""
    print(f"\n{'=' * 100}\n=== FAZ 0 — ARAÇ ÖZ-DENETİMİ (lookahead + plasebo) ===")
    P = prep("BTC", "1h")
    N = C_N
    hh, ll, w, wr = P["ch"][N]
    hi, lo = P["hi"], P["lo"]
    bad = 0
    for i in np.random.default_rng(7).integers(START, P["n"] - 1, 400):
        i = int(i)
        if hh[i] != hi[i - N:i].max() or ll[i] != lo[i - N:i].min():
            bad += 1
    print(f"  1) hh/ll = [i-N, i-1] penceresi mi: 400 rastgele barda uyumsuzluk = {bad} "
          f"→ {'✓ shift(1) DOĞRU' if bad == 0 else '✗ LOOKAHEAD VAR'}")

    # 2) sinyal bar i'nin kendi high/low/close'u kullanılıyor, i+1 KULLANILMIYOR:
    #    kanıt = son barı silince eski sinyaller AYNEN kalmalı
    sm, lm = signals(P, N, C_DET, C_THR)
    P2 = dict(P); K = P["n"] - 300
    P2 = dict(hi=P["hi"][:K], lo=P["lo"][:K], cl=P["cl"][:K], idx=P["idx"][:K], n=K,
              atr=P["atr"][:K], adx=P["adx"][:K], ch={N: (hh[:K], ll[:K], w[:K], wr[:K])})
    sm2, lm2 = signals(P2, N, C_DET, C_THR)
    same = np.array_equal(sm[:K], sm2) and np.array_equal(lm[:K], lm2)
    print(f"  2) veri sonu 300 bar kesilince geçmiş sinyaller değişiyor mu: "
          f"{'HAYIR ✓ (nedensel)' if same else 'EVET ✗ LOOKAHEAD'}")

    # 3) rank penceresi: rolling(500), min_periods=200 → i'den sonraki bar kullanılmıyor
    j = int(P["n"] * 0.6)
    manual = float((pd.Series(w[j - RANKW + 1:j + 1]).rank(pct=True).iloc[-1]))
    print(f"  3) rank[i] elle geçmiş-500 pencereden: {manual:.4f} vs araç {wr[j]:.4f} "
          f"→ {'✓ yalnız geçmiş' if abs(manual - wr[j]) < 1e-9 else '✗ SAPMA'}")

    # 4) PLASEBO
    rng = np.random.default_rng(11)
    tot = []
    for c in ("BTC", "ETH", "SOL", "ADA", "LINK"):
        Q = prep(c, "1h")
        s_, l_ = signals(Q, N, C_DET, C_THR)
        idxs = [t[0] for t in sim(Q, s_, l_, C_RR, C_SL, C_MH)]
        flip = rng.random(len(idxs)) < 0.5
        s2 = s_.copy(); l2 = l_.copy()
        for k, i in enumerate(idxs):
            if flip[k]:
                s2[i], l2[i] = l_[i], s_[i]
        tot += [t[3] for t in sim(Q, s2, l2, C_RR, C_SL, C_MH, force_idx=idxs)]
    m, z = zstat(tot)
    print(f"  4) PLASEBO (aynı barlar, RASTGELE yön, 5 coin): n={len(tot)} ort {m:+.4f}R z={z:+.2f} "
          f"→ {'✓ sıfıra yakın (araç sahte edge üretmiyor)' if abs(z) < 2 else '✗ ARAÇ SAHTE EDGE ÜRETİYOR'}")


def phase_probe():
    print(f"\n{'=' * 100}\n=== PROBE: aralık genişliği dağılımı + ham sinyal sayıları (lookahead kontrolü) ===")
    print(f"  {'tf':>4s} {'N':>3s} | w=(hh-ll)/ATR  p10/p25/p50/p75/p90 | rej_up  rej_dn  (22 coin toplamı)")
    for tf in TFS:
        for N in (20, 40):
            ws = []; nu = nd = 0
            for c in ALL22:
                P = prep(c, tf)
                if P is None: continue
                hh, ll, w, wr = P["ch"][N]
                ws.append(w[START:][np.isfinite(w[START:])])
                sm, lm = signals(P, N, "none", 0)
                nu += int(sm[START:].sum()); nd += int(lm[START:].sum())
            allw = np.concatenate(ws)
            q = np.percentile(allw, [10, 25, 50, 75, 90])
            print(f"  {tf:>4s} {N:>3d} | {q[0]:5.1f} {q[1]:5.1f} {q[2]:5.1f} {q[3]:5.1f} {q[4]:5.1f}"
                  f"        | {nu:6d}  {nd:6d}")


def phase_main():
    print(f"\n{'=' * 100}")
    print(f"=== FAZ 1 — MEKANİZMA: {len(ALL22)} coin × {len(TFS)} tf, merkez konfig ===")
    print(f"  N={C_N} detektör={C_DET}<={C_THR} rr={C_RR} SL={C_SL}×ATR mh={C_MH}  (occ ZORUNLU, koltuk YOK)")
    cells, fd, fl = run_universe(ALL22, TFS, C_N, C_DET, C_THR, C_RR, C_SL, C_MH, paired=True)
    if not len(cells):
        print("  hücre yok"); return None
    print(f"  hücre: {len(cells)} | RED(fade) işlem: {len(fd)} | eşleştirilmiş TERS: {len(fl)}")

    # DEJENERE VARYANT KONTROLÜ — ters yön cebirsel olarak -R değil mi?
    s = fd["R"].values + fl["R"].values
    print(f"\n  --- DEJENERE Mİ? (R_red + R_ters) max|.| = {np.abs(s).max():.3e}, "
          f"ort {s.mean():+.4f} → {'DEJENERE, TEST GEÇERSİZ' if np.abs(s).max() < 1e-9 else 'bağımsız ✓'}")

    # (a) İŞARET TESTİ
    w1 = int((cells.mR > 0).sum()); n1 = len(cells)
    cells["d"] = cells.mR - cells.mR_flip                 # RED − TERS (eşleştirilmiş fark)
    w2 = int((cells.d > 0).sum())
    print(f"\n  --- (a) İŞARET TESTİ ---")
    print(f"      A1 ham    : {w1}/{n1} hücrede ort R > 0     → binom p={binom_two(w1, n1):.4f}"
          f"   {'✓' if binom_two(w1, n1) < 0.05 else '✗'}   (null tam 0.5 DEĞİL: R dağılımı çarpık)")
    print(f"      A2 eşleşt.: {w2}/{n1} hücrede RED > TERS     → binom p={binom_two(w2, n1):.4f}"
          f"   {'✓' if binom_two(w2, n1) < 0.05 else '✗'}   (null TAM 0.5: aynı bar, ters yön)")

    # (b) HAVUZLANMIŞ ORTALAMA R
    mR, z = zstat(fd["R"].values)
    mF, zF = zstat(fl["R"].values)
    dd = fd["R"].values - fl["R"].values
    mD, zD = zstat(dd)
    print(f"\n  --- (b) HAVUZLANMIŞ ORTALAMA R ---")
    print(f"      RED  {mR:+.4f}R (n={len(fd)}, sd {fd['R'].std(ddof=1):.3f})  z={z:+.2f}  "
          f"{'✓' if abs(z) > 1.96 else '✗'}   ${dollars(fd):+.0f}")
    print(f"      TERS {mF:+.4f}R (n={len(fl)})  z={zF:+.2f}                       ${dollars(fl):+.0f}")
    print(f"      fark {mD:+.4f}R  z={zD:+.2f}  {'✓ ANLAMLI' if abs(zD) > 1.96 else '✗ anlamsız'}")

    # (c) YÖN AYRIMI
    print(f"\n  --- (c) YÖN AYRIMI (etki sadece LONG'daysa piyasa betası → RED) ---")
    for nm, dv in (("LONG (alt kenar reddi)", 1), ("SHORT (üst kenar reddi)", -1)):
        s_ = fd[fd["dir"] == dv]
        if not len(s_): continue
        m_, z_ = zstat(s_["R"].values)
        print(f"      {nm:<24s} n={len(s_):>5d}  ort {m_:+.4f}R  z={z_:+.2f}  ${dollars(s_):+.0f}")
    lo_ = fd[fd["dir"] == 1]["R"].values; sh_ = fd[fd["dir"] == -1]["R"].values
    if len(lo_) > 3 and len(sh_) > 3:
        se = np.sqrt(lo_.var(ddof=1) / len(lo_) + sh_.var(ddof=1) / len(sh_))
        print(f"      long−short farkı {lo_.mean() - sh_.mean():+.4f}R  z={(lo_.mean() - sh_.mean()) / se:+.2f}")

    # (d) DÖNEM
    print(f"\n  --- (d) DÖNEM AYRIMI (işaret dönüyorsa gürültü → RED) ---")
    ent = pd.DatetimeIndex(fd["entry"])
    for lbl, msk in (("TRAIN(<2025)", ent < TRAIN_END), ("TEST (>=2025)", ent >= TRAIN_END)):
        s_ = fd[msk]
        if len(s_) < 30: continue
        m_, z_ = zstat(s_["R"].values)
        print(f"      {lbl}: n={len(s_):>5d}  ort {m_:+.4f}R  z={z_:+.2f}  ${dollars(s_):+.0f}")
        for nm, dv in (("long", 1), ("short", -1)):
            t_ = s_[s_["dir"] == dv]
            if len(t_) > 10:
                mm, zz = zstat(t_["R"].values)
                print(f"          {nm:<6s} n={len(t_):>5d} ort {mm:+.4f}R z={zz:+.2f}")

    # yıl-yıl (kol tek başına, koltuksuz)
    yr = pd.Series(fd["R"].values * np.minimum(RISKF, CAP * fd["slp"].values) * BAL0,
                   index=[pd.Timestamp(x).year for x in fd["exit"]]).groupby(level=0).sum()
    print(f"\n  --- kol tek başına yıl-yıl (koltuksuz, 22 coin×3tf — ölçüm, portföy değil) ---")
    print("      " + "  ".join(f"{y}:${v:+.0f}" for y, v in yr.items()))
    return cells, fd, fl


def _sweep_row(tag, coins, tfs, N, det, thr, rr, sl_a, mh):
    cells, fd, _ = run_universe(coins, tfs, N, det, thr, rr, sl_a, mh)
    if not len(fd):
        print(f"  {tag:<22s}  — sinyal yok"); return None
    mR, z = zstat(fd["R"].values)
    w = int((cells.mR > 0).sum()); n = len(cells)
    ent = pd.DatetimeIndex(fd["entry"])
    tr_ = fd[ent < TRAIN_END]["R"]; te_ = fd[ent >= TRAIN_END]["R"]
    lo_ = fd[fd["dir"] == 1]["R"]; sh_ = fd[fd["dir"] == -1]["R"]
    print(f"  {tag:<22s} {len(fd):>6d} {(fd['R'] > 0).mean() * 100:>4.0f}% {mR:>+8.4f} {z:>+6.2f} "
          f"{dollars(fd):>+8.0f} {w:>3d}/{n:<3d} {binom_two(w, n):>7.4f} "
          f"{tr_.mean() if len(tr_) else 0:>+8.4f} {te_.mean() if len(te_) else 0:>+8.4f} "
          f"{lo_.mean() if len(lo_) else 0:>+8.4f} {sh_.mean() if len(sh_) else 0:>+8.4f}")
    return dict(tag=tag, n=len(fd), mR=mR, z=z, tot=dollars(fd), w=w, cells=n,
                tr=float(tr_.mean()) if len(tr_) else 0.0, te=float(te_.mean()) if len(te_) else 0.0,
                lo=float(lo_.mean()) if len(lo_) else 0.0, sh=float(sh_.mean()) if len(sh_) else 0.0)


def phase_dose():
    hdr = (f"  {'varyant':<22s} {'n':>6s} {'WR':>4s} {'ortR':>8s} {'z':>6s} {'$':>8s} "
           f"{'hücre+':>7s} {'binomP':>7s} {'TRAIN R':>8s} {'TEST R':>8s} {'LONG R':>8s} {'SHORT R':>8s}")
    print(f"\n{'=' * 130}\n=== FAZ 2 — DOZ-YANIT (monotonluk ara; zikzak = gürültü) ===")

    print(f"\n  [1] N (aralık pencere uzunluğu), detektör={C_DET}<={C_THR} rr={C_RR} SL={C_SL}")
    print(hdr)
    for N in NS:
        _sweep_row(f"N={N}", ALL22, TFS, N, C_DET, C_THR, C_RR, C_SL, C_MH)

    print(f"\n  [2] DETEKTÖR A — mutlak genişlik w=(hh-ll)/ATR <= eşik   (N={C_N})")
    print(hdr)
    for t in (4, 6, 8, 10, 14, 999):
        _sweep_row(f"w<={t}", ALL22, TFS, C_N, "w", t, C_RR, C_SL, C_MH)

    print(f"\n  [3] DETEKTÖR B — geçmiş-500-bar yüzdelik sırası <= q   (N={C_N})")
    print(hdr)
    for t in (0.2, 0.4, 0.6, 0.8, 1.0):
        _sweep_row(f"rank<={t}", ALL22, TFS, C_N, "rank", t, C_RR, C_SL, C_MH)

    print(f"\n  [4] DETEKTÖR C — ADX < eşik   (N={C_N})")
    print(hdr)
    for t in (15, 20, 25, 30, 100):
        _sweep_row(f"ADX<{t}", ALL22, TFS, C_N, "adx", t, C_RR, C_SL, C_MH)

    print(f"\n  [5] rr (detektör={C_DET}<={C_THR}, SL={C_SL}×ATR)")
    print(hdr)
    for rr in (0.75, 1.0, 1.667, 2.0, 2.5, 3.5):
        _sweep_row(f"rr={rr}", ALL22, TFS, C_N, C_DET, C_THR, rr, C_SL, C_MH)

    print(f"\n  [6] SL çarpanı (rr={C_RR})")
    print(hdr)
    for sl in (1.0, 1.5, 2.0, 3.0, 4.0):
        _sweep_row(f"SL={sl}×ATR", ALL22, TFS, C_N, C_DET, C_THR, C_RR, sl, C_MH)

    print(f"\n  [7] maxhold (rr={C_RR} SL={C_SL})")
    print(hdr)
    for mh in (12, 24, 48, 96, 200):
        _sweep_row(f"mh={mh}", ALL22, TFS, C_N, C_DET, C_THR, C_RR, C_SL, mh)


def phase_anchor(configs):
    """configs = [(etiket, coins, tf, N, det, thr, rr, sl, mh), ...]"""
    print(f"\n{'=' * 128}\n=== FAZ 3 — ANKOR ENTEGRASYONU (sleeve sırası DONCH→SQZ→BB→YENİ, occ+koltuk gerçek) ===")
    base_tr = anchor_trades()
    b = metrics(A.seat_select(base_tr))
    b2 = metrics([(t[0], t[1], t[2]) for t in seat_select_idx(base_tr)])   # kendi koltuk kopyam
    ok = (b["n"] == 1579 and abs(b["tot"] - 1420.66) < 0.5
          and b2["n"] == b["n"] and abs(b2["tot"] - b["tot"]) < 1e-9)
    print(f"  DEĞİŞTİRİLMEMİŞ TABAN: {b['n']} işlem  ${b['tot']:+.2f}   "
          f"(ZORUNLU: 1579 / +1420.66)  → {'✓ ARAÇ SAĞLAM' if ok else '✗ ARAÇ BOZUK, SONUÇLAR GEÇERSİZ'}")
    print(f"  kendi koltuk kopyam (yerinden-edilme sayımı için): {b2['n']} işlem ${b2['tot']:+.2f} "
          f"→ {'birebir ✓' if b2['n'] == b['n'] and abs(b2['tot'] - b['tot']) < 1e-9 else 'SAPMA ✗'}")
    if not ok:
        return None
    yrs = sorted(b["yr"])
    print(f"\n  {'konfig':<40s} {'n':>5s} {'toplam$':>8s} {'Δ$':>7s} {'PF':>5s} {'maxDD':>7s} "
          f"{'enKötüAy':>9s} {'poz-ay':>7s} | " + " ".join(f"{y:>7d}" for y in yrs))
    print(f"  {'ANKOR (taban)':<40s} {b['n']:>5d} {b['tot']:>+8.0f} {0:>+7.0f} {b['pf']:>5.2f} "
          f"{b['dd']:>7.1f} {b['worst']:>+9.1f} {b['posm']:>7.0f} | " + " ".join(f"{b['yr'].get(y, 0):>+7.0f}" for y in yrs))

    results = []
    for label, coins, tf, N, det, thr, rr, sl_a, mh in configs:
        _, fd, _ = run_universe(coins, [tf], N, det, thr, rr, sl_a, mh)
        if not len(fd):
            print(f"  {label:<40s} — sinyal yok"); continue
        comb_tr = base_tr + sleeve_to_anchor_fmt(fd)
        sel = seat_select_idx(comb_tr)
        v = metrics([(t[0], t[1], t[2]) for t in sel])
        nb = len(base_tr)
        kept_base = sum(1 for t in sel if t[3] < nb)
        took_new = sum(1 for t in sel if t[3] >= nb)
        print(f"  {label:<40s} {v['n']:>5d} {v['tot']:>+8.0f} {v['tot'] - b['tot']:>+7.0f} {v['pf']:>5.2f} "
              f"{v['dd']:>7.1f} {v['worst']:>+9.1f} {v['posm']:>7.0f} | " + " ".join(f"{v['yr'].get(y, 0):>+7.0f}" for y in yrs))
        why = verdict(v, b)
        print(f"      kol tek başına ${dollars(fd):+.0f} (n={len(fd)}, koltuk öncesi) | "
              f"KOLTUK: taban {b['n']}→{kept_base} (YERİNDEN EDİLEN {b['n'] - kept_base}), yeni kol {took_new}/{len(fd)} koltuk buldu")
        print(f"      ÖN-KAYITLI BAR: {'✅ GEÇTİ' if not why else '❌ RED — ' + ' · '.join(why)}")
        results.append((label, v, fd))

    # KORELASYON RAPORU
    print(f"\n  --- FAZ 4 — AYLIK PnL KORELASYONU (yeni kol vs mevcut portföy) ---")
    bm = b["mon"]
    for label, v, fd in results:
        sm_ = monthly(fd)
        j = pd.concat({"y": sm_, "b": bm}, axis=1).dropna()
        if len(j) < 10:
            continue
        r_p = j["y"].corr(j["b"]); r_s = spearman(j["y"].values, j["b"].values)
        bad = j[j["b"] < 0]
        note = "YÜKSEK (>0.5) = çeşitlendirme DEĞİL" if r_p > 0.5 else "düşük (kâr yoksa yine değersiz)"
        print(f"      {label:<40s} Pearson {r_p:+.3f} | Spearman {r_s:+.3f} | {len(j)} ay | "
              f"kitabın {len(bad)} kayıp ayında ${bad['y'].sum():+.0f} ({(bad['y'] > 0).sum()}/{len(bad)} poz) | {note}")
    return results


def phase_cal():
    """BB kolunun HAFTA SONU kısıtı bu ailede de işe yarıyor mu?
    Ledger: kısıt eski BTC-1m döneminden (research_bb_weekend_impact) miras; faz-2 ajanı
    11-coin BB genişlemesinde ölçtü ve 'takvime asılı, mekanizması yok' dedi
    (hafta sonu +$110 · sadece Cmt +$13 · sadece Paz −$44 · Cuma+hs −$188 · hafta içi −$454).
    Aynı ayrımı ARALIK-REDDİ ailesinde de yapıyoruz."""
    print(f"\n{'=' * 130}\n=== FAZ 2c — TAKVİM KAPISI (BB kolunun 'yalnız hafta sonu' kısıtı bu ailede yaşıyor mu?) ===")
    hdr = (f"  {'varyant':<22s} {'n':>6s} {'WR':>4s} {'ortR':>8s} {'z':>6s} {'$':>8s} "
           f"{'hücre+':>7s} {'binomP':>7s} {'TRAIN R':>8s} {'TEST R':>8s} {'LONG R':>8s} {'SHORT R':>8s}")
    print(hdr)
    for lbl, wk in (("tüm günler", 0), ("YALNIZ hafta sonu", 1), ("yalnız hafta içi", 2)):
        cells, fd, _ = run_universe(ALL22, TFS, C_N, C_DET, C_THR, C_RR, C_SL, C_MH, wknd=wk, minn=10)
        if not len(fd):
            print(f"  {lbl:<22s} — sinyal yok"); continue
        mR, z = zstat(fd["R"].values); w = int((cells.mR > 0).sum()); n = len(cells)
        ent = pd.DatetimeIndex(fd["entry"])
        tr_ = fd[ent < TRAIN_END]["R"]; te_ = fd[ent >= TRAIN_END]["R"]
        lo_ = fd[fd["dir"] == 1]["R"]; sh_ = fd[fd["dir"] == -1]["R"]
        print(f"  {lbl:<22s} {len(fd):>6d} {(fd['R'] > 0).mean() * 100:>4.0f}% {mR:>+8.4f} {z:>+6.2f} "
              f"{dollars(fd):>+8.0f} {w:>3d}/{n:<3d} {binom_two(w, n):>7.4f} "
              f"{tr_.mean():>+8.4f} {te_.mean():>+8.4f} {lo_.mean():>+8.4f} {sh_.mean():>+8.4f}")


def phase_pick():
    """KİRAZ TOPLAMA ÜST SINIRI: SERBEST coinlerde küçük bir ızgara — en iyi hücre bile
    barı geçiyor mu? (Tek hücrenin geçmesi HİÇBİR ŞEY ifade etmez; amaç TAVANI görmek.)"""
    print(f"\n{'=' * 118}\n=== FAZ 2b — SERBEST-COİN IZGARASI (kiraz toplama tavanı; seçim in-sample = iyimser) ===")
    print(f"  {'tf':>3s} {'N':>3s} {'det':>10s} {'rr':>5s} {'SL':>4s} {'mh':>4s} {'n':>5s} {'ortR':>8s} "
          f"{'z':>6s} {'$':>7s} {'TRAIN':>8s} {'TEST':>8s} {'LONG':>8s} {'SHORT':>8s}")
    best = None
    for tf in ("1h", "4h"):
        for N in (20, 40):
            for det, thr in (("rank", 0.2), ("rank", 0.4), ("adx", 20)):
                for rr, sl_a in ((1.0, 2.0), (1.667, 3.0), (2.5, 2.0)):
                    _, fd, _ = run_universe(FREE, [tf], N, det, thr, rr, sl_a, C_MH)
                    if len(fd) < 50:
                        continue
                    mR, z = zstat(fd["R"].values)
                    ent = pd.DatetimeIndex(fd["entry"])
                    tr_ = fd[ent < TRAIN_END]["R"]; te_ = fd[ent >= TRAIN_END]["R"]
                    lo_ = fd[fd["dir"] == 1]["R"]; sh_ = fd[fd["dir"] == -1]["R"]
                    d_ = dollars(fd)
                    print(f"  {tf:>3s} {N:>3d} {det + '<=' + str(thr):>10s} {rr:>5.3f} {sl_a:>4.1f} {C_MH:>4d} "
                          f"{len(fd):>5d} {mR:>+8.4f} {z:>+6.2f} {d_:>+7.0f} "
                          f"{tr_.mean() if len(tr_) else 0:>+8.4f} {te_.mean() if len(te_) else 0:>+8.4f} "
                          f"{lo_.mean() if len(lo_) else 0:>+8.4f} {sh_.mean() if len(sh_) else 0:>+8.4f}")
                    if best is None or d_ > best[0]:
                        best = (d_, (tf, N, det, thr, rr, sl_a))
    print(f"\n  IZGARANIN EN İYİSİ (in-sample seçim, geçerli kanıt DEĞİL): ${best[0]:+.0f} → {best[1]}")
    return best[1]


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    what = sys.argv[2] if len(sys.argv) > 2 else "all"
    load_raw(source)
    print(f"\n  evren: {len(RAW)} coin | SERBEST (netted çakışma yok): {FREE}")
    if what in ("selftest", "probe", "all"):
        phase_selftest()
    if what in ("probe", "all"):
        phase_probe()
    if what in ("main", "all"):
        phase_main()
    if what in ("dose", "all"):
        phase_dose()
    if what in ("cal", "dose", "all"):
        phase_cal()
    pick = None
    if what in ("pick", "anchor", "all"):
        pick = phase_pick()
    if what in ("anchor", "all"):
        cfgs = [("merkez, SERBEST 10c, 1h", FREE, "1h", C_N, C_DET, C_THR, C_RR, C_SL, C_MH),
                ("merkez, SERBEST 10c, 4h", FREE, "4h", C_N, C_DET, C_THR, C_RR, C_SL, C_MH),
                ("merkez, 22 coin, 1h (çakışmalı)", ALL22, "1h", C_N, C_DET, C_THR, C_RR, C_SL, C_MH),
                ("dar aralık N=20 rank<=.2, SERBEST", FREE, "1h", 20, "rank", 0.2, C_RR, C_SL, C_MH),
                ("mh=200 varyantı, SERBEST", FREE, "1h", C_N, C_DET, C_THR, C_RR, C_SL, 200)]
        if pick:
            tf, N, det, thr, rr, sl_a = pick
            cfgs.append((f"IZGARA EN İYİSİ {tf} N{N} {det}{thr} rr{rr} SL{sl_a}",
                         FREE, tf, N, det, thr, rr, sl_a, C_MH))
        phase_anchor(cfgs)


if __name__ == "__main__":
    main()
