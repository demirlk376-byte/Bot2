"""
cvd_kol2.py — CVD KOLU · YENI TABANA (Kronos) KARSI OLCUM + VERI KAPISI.
URETIM KODU DEGISMEDI. Bu dosya salt-okunur olcum yapar.

Asamalar:
  veri    ASAMA 0 veri kapisi (taker verisi)
  t2      YENI KOL icin NEDENSELLIK (kesme) testi — kronos_test T2 metodolojisi
  taban   Yeni on-kayitli tabani Kronos ile uret + dogrula (cache)
  kol     CVD kolu AYRI HAVUZ (kendi Kronos'u, ayni kapilar, funding dahil)
  birlesik risk-esitlenmis delta + gecme bari (a)-(f)
  aile    81 hucre izgara + gurultu tavani
  funding tutus suresi + funding bedeli ayristirmasi
"""
from __future__ import annotations
import sys, os, glob, pickle, itertools
import numpy as np, pandas as pd

sys.path.insert(0, "/home/user/Bot2")
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn
from kronos import Kronos, Ayar, Besleme
from kronos.kollar import Kol, canli_kollar, funding_yukle

SCRATCH = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
os.makedirs(SCRATCH, exist_ok=True)

# ── ON-KAYITLI KOL PARAMETRELERI (izgara ortasi, degismedi) ───────────────
LB, SL_A, RR, MH = 20, 2.0, 2.0, 24
LB_G, SL_G, RR_G, MH_G = [10, 20, 40], [1.5, 2.0, 3.0], [1.5, 2.0, 2.5], [12, 24, 48]
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")

# ── ON-KAYITLI YENI TABAN (brief) ─────────────────────────────────────────
T_N, T_ORTR, T_TOPLAM, T_DD, T_KOTUAY = 1712, 0.1451, 621.78, 51.58, -34.39
BAR_A = 0.0694          # (a) risk-esitlenmis Delta ort R esigi

COINS_LIVE = DB.DONCH + DB.SQZ + DB.BB_COINS
TAKER_SRC = {
    "BTC": [f"{SCRATCH}/btc1m/BTCUSDT-1m-*.csv", "/home/user/Bot2/BTCUSDT-1m-*.csv"],
    "ETH": ["/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv"],
}

def AYAR(fund):
    """ON-KAYITLI yeni taban ayari (brief ile birebir)."""
    return Ayar(maxpos=7, riskf=0.028, cap=1.50, bal0=1000.0, kayma_bp=15.85,
                funding=fund, ayni_bar_giris=True, ardisik_zarar_limiti=2,
                cooldown_dk=240, gunluk_zarar_pct=0.35, tek_pozisyon_per_coin=True)


# ═══════════════════ ASAMA 0 · VERI ═══════════════════
_TK = {}
def taker_4h(coin):
    if coin in _TK: return _TK[coin]
    pats = TAKER_SRC.get(coin)
    if not pats: _TK[coin] = None; return None
    fs = []
    for p in pats: fs += sorted(glob.glob(p))
    if not fs: _TK[coin] = None; return None
    fr = []
    for f in fs:
        d = pd.read_csv(f, usecols=["open_time", "volume", "taker_buy_volume"])
        fr.append(d.astype(float))
    m = (pd.concat(fr, ignore_index=True)
           .drop_duplicates(subset="open_time").sort_values("open_time"))
    m.index = pd.to_datetime(m["open_time"], unit="ms", utc=True)
    r = m.resample("4h").agg({"volume": "sum", "taker_buy_volume": "sum"})
    r = r[r["volume"] > 0]
    r["buy_ratio"] = (r["taker_buy_volume"] / r["volume"]).clip(0, 1)
    _TK[coin] = r[["buy_ratio"]]
    return _TK[coin]


def veri_denetim(verbose=True):
    rapor = []
    for c in COINS_LIVE + ["BTC"]:
        t = taker_4h(c)
        if t is None or len(t) == 0:
            rapor.append((c, 0, None, None, -1, "taker verisi YOK")); continue
        d = t.index.to_series().diff().dt.total_seconds() / 3600.0
        bos = int((d > 24).sum()); enb = float(d.max()) if len(d) > 1 else 0.0
        rapor.append((c, len(t), t.index[0].date(), t.index[-1].date(), bos,
                      f"en buyuk bosluk {enb:.0f}h · {'GECTI' if bos==0 else 'ELENDI'}"))
    if verbose:
        print(f"\n{'='*100}\n=== ASAMA 0 · VERI KAPISI ===")
        print(f"  {'coin':<6} {'4H bar':>7} {'bas':>12} {'son':>12} {'>24h':>6}  durum")
        for c, n, a, b, bos, s in rapor:
            print(f"  {c:<6} {n:>7} {str(a):>12} {str(b):>12} {bos if bos>=0 else '-':>6}  {s}")
        g = [r[0] for r in rapor if r[0] in COINS_LIVE and r[4] == 0]
        print(f"\n  CANLI coinlerden veri kapisini gecen: {len(g)}/12  {g}")
        print(f"  (d0) >=6 coin →  {'GECTI' if len(g)>=6 else 'GECMEDI → OLCULEMEDI'}")
    return rapor


# ═══════════════════ CVD KOLU (Kronos Kol) ═══════════════════
class CvdKol(Kol):
    """LONG-only 4H: yeni lb-bar dibi + onceki dipten beri net taker ALIMI.
       Fiyat/hacim MEXC (ankor kaynagi), taker orani Binance. i DAHIL, i+1 ASLA."""
    ad = "cvd"; oncelik = 3

    def __init__(self, coin, src="local", sira=0, kadar=None,
                 lb=LB, sl_atr=SL_A, rr=RR, mh=MH):
        super().__init__(coin, sira)
        self.lb, self.sl_a, self.rr, self.mh = lb, sl_atr, rr, mh
        m = fast_bt.load(coin, source=src)
        if kadar is not None: m = m[m.index <= kadar]
        d = fast_bt.resample(m, "4h")
        t = taker_4h(coin)
        if t is None: raise ValueError(f"{coin}: taker verisi yok")
        if kadar is not None: t = t[t.index <= kadar]
        d = d.join(t, how="left")
        ok = d["buy_ratio"].notna().values
        br = d["buy_ratio"].fillna(0.5).values
        dl = d["volume"].values * (2.0 * br - 1.0)
        dl = np.where(ok, dl, 0.0)
        self._cvd = np.cumsum(dl)
        self._ok = ok
        self._lo = d["low"].values
        d = d.drop(columns=["buy_ratio"])
        self.besleme = Besleme(d)
        self._atr = atr_fn(d["high"], d["low"], d["close"], 14).values

    def sinyal(self, i):
        lb = self.lb
        if i < lb + 15 or i >= self.besleme.n - 1: return None
        lo = self._lo
        if lo[i] > lo[i - lb:i + 1].min(): return None
        if not self._ok[i - lb:i + 1].all(): return None
        p = i - lb + int(np.argmin(lo[i - lb:i]))
        if not (self._cvd[i] > self._cvd[p]): return None
        a = self._atr[i]
        if not np.isfinite(a) or a <= 0: return None
        return 1, self.sl_a * a, self.rr, self.mh


def kol_coinleri():
    return [c for c in ["BTC", "ETH"] if taker_4h(c) is not None]


# ═══════════════════ OLCUM YARDIMCILARI ═══════════════════
def seri(islemler, olcek=1.0):
    """cikisa gore sirali (pnl, ay) — Kronos eff*bal0 zaten icinde."""
    t = sorted(islemler, key=lambda x: (x.cikis_ts.value, x.giris_ts.value, x.kol, x.coin))
    R = np.array([x.R for x in t]); eff = np.array([x.eff for x in t]) * olcek
    ex = [x.cikis_ts for x in t]
    return R, eff, ex

def kar_pct(islemler, olcek=1.0, bal0=1000.0):
    if not islemler: return 0.0, pd.Series(dtype=float)
    R, eff, ex = seri(islemler, olcek)
    pnl = R * eff * bal0
    ay = pd.Series(pnl, index=[x.tz_localize(None).to_period("M") for x in ex]).groupby(level=0).sum()
    return float(pnl.sum()) / bal0 * 100, ay / bal0 * 100

def dd_bilesik(islemler, olcek=1.0):
    if not islemler: return 0.0
    R, eff, _ = seri(islemler, olcek)
    eq = np.concatenate([[1.0], np.cumprod(1.0 + R * eff)])
    return float(((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq)).max() * 100)

def olcek_bul(islemler, hedef_dd):
    if dd_bilesik(islemler, 1.0) <= hedef_dd: return 1.0
    lo, hi = 0.01, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if dd_bilesik(islemler, mid) > hedef_dd: hi = mid
        else: lo = mid
    return (lo + hi) / 2

def ozet(islemler, etiket):
    if not islemler: print(f"  {etiket:<34s} n=0"); return
    R = np.array([x.R for x in islemler])
    z = R.mean() / R.std(ddof=1) * np.sqrt(len(R)) if len(R) > 1 and R.std(ddof=1) > 0 else 0.0
    top, ay = kar_pct(islemler)
    print(f"  {etiket:<34s} n={len(R):<5d} ortR={R.mean():+.4f} z={z:+.2f} "
          f"toplam%={top:+7.2f} maxDD%={dd_bilesik(islemler):5.2f} "
          f"kotuAy%={(ay.min() if len(ay) else 0):+6.2f} pozAy%={(ay>0).mean()*100 if len(ay) else 0:.0f}")

def tr_te(islemler):
    TR = [x for x in islemler if x.giris_ts < SPLIT and x.cikis_ts < SPLIT]
    TE = [x for x in islemler if x.giris_ts >= SPLIT]
    return TR, TE


# ═══════════════════ CACHE'li KOSULAR ═══════════════════
def _cache(ad, uret):
    p = f"{SCRATCH}/cvd2_{ad}.pkl"
    if os.path.exists(p):
        with open(p, "rb") as f: return pickle.load(f)
    r = uret()
    with open(p, "wb") as f: pickle.dump(r, f)
    return r

def taban_kos(src="local"):
    def u():
        fund = funding_yukle(COINS_LIVE)
        return Kronos(canli_kollar(src), AYAR(fund)).kos()
    return _cache("taban", u)

def kol_kos(src="local", lb=LB, sl=SL_A, rr=RR, mh=MH, fund=None, etiket=None):
    def u():
        f = fund if fund is not None else funding_yukle(COINS_LIVE)
        ks = [CvdKol(c, src, n, None, lb, sl, rr, mh) for n, c in enumerate(kol_coinleri())]
        return Kronos(ks, AYAR(f)).kos()
    if etiket is None: return u()
    return _cache(etiket, u)


# ═══════════════════ FUNDING PROXY (BTC verisi YOK) ═══════════════════
def btc_funding_proxy(fund_all):
    """BTC funding verisi depoda YOK. Iki proxy uretilir:
       'medyan' = 12 canli coinin her damgadaki MEDYANI, 'eth' = ETH serisi."""
    ser = {c: s for c, s in fund_all.items() if len(s)}
    if not ser: return {}
    df = pd.DataFrame(ser).sort_index()
    med = df.median(axis=1).dropna()
    out = {"medyan": med}
    if "ETH" in ser: out["eth"] = ser["ETH"]
    return out


# ═══════════════════ T2 · NEDENSELLIK (yeni kol) ═══════════════════
def t2(src="local"):
    print(f"\n{'='*100}\n=== T2 · NEDENSELLIK — CVD KOLU (kronos_test metodolojisi) ===")
    fund = funding_yukle(COINS_LIVE)
    def imza(ts):
        return {(x.kol, x.coin, x.giris_ts.value, x.cikis_ts.value, round(x.R, 9)) for x in ts}
    tam = Kronos([CvdKol(c, src, n) for n, c in enumerate(kol_coinleri())], AYAR(fund)).kos()
    it = imza(tam); hata = 0
    for T in ("2024-06-01", "2025-03-15", "2025-11-01"):
        Tts = pd.Timestamp(T, tz="UTC")
        global _TK; _TK = {}
        ks = [CvdKol(c, src, n, Tts) for n, c in enumerate(kol_coinleri())]
        _TK = {}
        kes = Kronos(ks, AYAR(fund)).kos()
        a_ = {x for x in it if x[3] < Tts.value}
        b_ = {x for x in imza(kes) if x[3] < Tts.value}
        f = (a_ - b_) | (b_ - a_)
        print(f"  kesim {T}: tam {len(a_)} karar · kesik {len(b_)} karar · FARK {len(f)}")
        if f:
            hata += 1
            for k in sorted(f, key=lambda x: x[2])[:4]:
                print(f"     ! {'yalniz TAM' if k in a_ else 'yalniz KESIK'}: {k[1]} "
                      f"giris={pd.Timestamp(k[2])} R={k[4]:+.4f}")
    # T3 belirlenimcilik
    iki = Kronos([CvdKol(c, src, n) for n, c in enumerate(kol_coinleri())], AYAR(fund)).kos()
    det = imza(iki) == it
    print(f"  T3 belirlenimci: {det}  (n={len(tam)})")
    print(f"  → {'GECTI — kol gelecege bakmiyor' if hata==0 and det else 'KALDI'}")
    return hata == 0 and det


# ═══════════════════ TABAN ═══════════════════
def taban_rapor(src="local"):
    A = taban_kos(src)
    R = np.array([x.R for x in A]); top, ay = kar_pct(A)
    dd = dd_bilesik(A); ayn = len(ay)
    print(f"\n{'='*100}\n=== YENI TABAN (Kronos, on-kayitli ayar) ===")
    print(f"  n={len(A)} (beklenen {T_N})   ortR={R.mean():+.6f} (beklenen {T_ORTR:+.4f})")
    print(f"  toplam%={top:+.2f} (beklenen {T_TOPLAM:+.2f})  aylik%={top/ayn:+.2f}  ay sayisi={ayn}")
    print(f"  bilesik maxDD%={dd:.2f} (beklenen {T_DD:.2f})  en kotu ay%={ay.min():+.2f} "
          f"(beklenen {T_KOTUAY:+.2f})  pozitif ay%={(ay>0).mean()*100:.0f}")
    ok = (len(A) == T_N and abs(R.mean() - T_ORTR) < 5e-4 and abs(top - T_TOPLAM) < 1.0
          and abs(dd - T_DD) < 0.5 and abs(ay.min() - T_KOTUAY) < 0.5)
    print(f"  → TABAN {'DOGRULANDI' if ok else '*** UYUSMADI — KIYAS GECERSIZ ***'}")
    return A, ok


# ═══════════════════ KOL · AYRI HAVUZ ═══════════════════
def kol_rapor(src="local"):
    fund = funding_yukle(COINS_LIVE)
    K = kol_kos(src, fund=fund, etiket="kol_orta")
    print(f"\n{'='*100}\n=== CVD KOLU · AYRI HAVUZ (lb={LB} sl={SL_A} rr={RR} mh={MH}, LONG-only) ===")
    print(f"  coinler: {kol_coinleri()}   (BTC canli kitapta YOK: {'BTC' in COINS_LIVE})")
    ozet(K, "kol TUMU")
    TR, TE = tr_te(K)
    ozet(TR, "  TRAIN (<2025-01-01)"); ozet(TE, "  TEST  (>=2025-01-01)")
    for c in sorted({x.coin for x in K}):
        ozet([x for x in K if x.coin == c], f"  coin {c}")
    for y in sorted({x.giris_ts.year for x in K}):
        ozet([x for x in K if x.giris_ts.year == y], f"  yil {y}")
    return K


# ═══════════════════ BIRLESIK · RISK ESITLENMIS ═══════════════════
def birlesik_rapor(A, K):
    print(f"\n{'='*100}\n=== BIRLESIK · RISK ESITLENMIS DELTA ===")
    RA = np.array([x.R for x in A]); dd_A = dd_bilesik(A)
    topA, ayA = kar_pct(A); topA_te, _ = kar_pct([x for x in A if x.giris_ts >= SPLIT])
    S = olcek_bul(K, dd_A)                       # kol olcegi: bilesik maxDD <= tabanin
    C = A + [x for x in K]
    # olcek kolun eff'ine uygulanir
    Kd = []
    for x in K:
        y = type(x)(**{k: getattr(x, k) for k in x.__dataclass_fields__})
        y.eff = x.eff * S; y.pnl = x.pnl * S; Kd.append(y)
    C = A + Kd
    RC = np.array([x.R for x in C]); topC, ayC = kar_pct(C); ddC = dd_bilesik(C)
    topC_te, _ = kar_pct([x for x in C if x.giris_ts >= SPLIT])
    RK = np.array([x.R for x in K])
    seA = RA.std(ddof=1) / np.sqrt(len(RA))
    # (a) IKI OKUMA
    d_kitap = RC.mean() - RA.mean()                       # okuma-1: kitabin ort R degisimi
    d_kol   = RK.mean() - RA.mean()                       # okuma-2: kolun kitaba ustunlugu
    sed = np.sqrt(RK.var(ddof=1)/len(RK) + seA**2)
    print(f"  taban:   n={len(A)} ortR={RA.mean():+.4f} SE={seA:.4f} toplam%={topA:+.2f} "
          f"maxDD%={dd_A:.2f} kotuAy%={ayA.min():+.2f} TEST%={topA_te:+.2f}")
    print(f"  kol S=1: n={len(K)} ortR={RK.mean():+.4f} toplam%={kar_pct(K)[0]:+.2f} "
          f"maxDD%={dd_bilesik(K):.2f}")
    print(f"  risk esitleme olcegi S={S:.4f}  (kol maxDD {dd_bilesik(K):.2f}% → hedef {dd_A:.2f}%)")
    print(f"  BIRLESIK: n={len(C)} ortR={RC.mean():+.4f} toplam%={topC:+.2f} "
          f"maxDD%={ddC:.2f} kotuAy%={ayC.min():+.2f} TEST%={topC_te:+.2f}")
    print(f"\n  (a) okuma-1 · kitabin ort R degisimi   = {d_kitap:+.4f}  esik {BAR_A:+.4f}  "
          f"{'GECTI' if d_kitap >= BAR_A else 'GECMEDI'}")
    print(f"      (yapisal tavan: n_kol={len(K)} ile kitabin ort R'sini {BAR_A:+.4f} oynatmak icin")
    print(f"       kolun ort R'si {(BAR_A*(len(A)+len(K))/len(K) + RA.mean()):+.3f} olmali)")
    print(f"  (a) okuma-2 · kol ortR - taban ortR    = {d_kol:+.4f} (SE {sed:.4f}, z={d_kol/sed:+.2f})  "
          f"esik {BAR_A:+.4f}  {'GECTI' if d_kol >= BAR_A else 'GECMEDI'}")
    print(f"  (a) $ okumasi · Delta toplam%          = {topC-topA:+.2f} puan  "
          f"(risk esitlenmis, TEST {topC_te-topA_te:+.2f} puan)")
    TRk, TEk = tr_te(K)
    RTE = np.array([x.R for x in TEk]) if TEk else np.array([])
    print(f"  (b) TEST diliminde pozitif mi: kol TEST n={len(TEk)} ortR="
          f"{RTE.mean() if len(RTE) else 0:+.4f} · birlesik TEST% {topC_te:+.2f} vs taban {topA_te:+.2f} "
          f"{'GECTI' if len(RTE) and RTE.mean()>0 and topC_te>topA_te else 'GECMEDI'}")
    print(f"  (c) en kotu ay {ayC.min():+.2f}% vs taban {ayA.min():+.2f}%  "
          f"{'GECTI' if ayC.min() >= ayA.min()-1e-9 else 'GECMEDI'}")
    print(f"  kitap KORUNDU mu (ayri havuz): taban {len(A)} → birlesikte {len([x for x in C if x.kol!='cvd'])}")
    return dict(S=S, d_kitap=d_kitap, d_kol=d_kol, topA=topA, topC=topC,
                topA_te=topA_te, topC_te=topC_te, kotuA=ayA.min(), kotuC=ayC.min())


# ═══════════════════ AILE IZGARASI + GURULTU TAVANI ═══════════════════
def aile_rapor(src="local"):
    fund = funding_yukle(COINS_LIVE)
    p = f"{SCRATCH}/cvd2_aile.pkl"
    if os.path.exists(p):
        with open(p, "rb") as f: G = pickle.load(f)
    else:
        G = {}
        for lb, sl, rr, mh in itertools.product(LB_G, SL_G, RR_G, MH_G):
            K = kol_kos(src, lb, sl, rr, mh, fund)
            TR, TE = tr_te(K)
            G[(lb, sl, rr, mh)] = dict(
                n=len(K), R=float(np.mean([x.R for x in K])) if K else 0.0,
                nTR=len(TR), RTR=float(np.mean([x.R for x in TR])) if TR else 0.0,
                nTE=len(TE), RTE=float(np.mean([x.R for x in TE])) if TE else 0.0)
            print(f"    hucre lb{lb} sl{sl} rr{rr} mh{mh}: n={len(K)} R={G[(lb,sl,rr,mh)]['R']:+.4f} "
                  f"TE n={len(TE)} R={G[(lb,sl,rr,mh)]['RTE']:+.4f}", flush=True)
        with open(p, "wb") as f: pickle.dump(G, f)
    tum = np.array([v["R"] for v in G.values()])
    te = np.array([v["RTE"] for v in G.values()])
    tr = np.array([v["RTR"] for v in G.values()])
    N = len(G)
    print(f"\n{'='*100}\n=== AILE · {N} HUCRE ===")
    print(f"  TUM  medyan={np.median(tum):+.4f}  pozitif={np.mean(tum>0)*100:.1f}%")
    print(f"  TRAIN medyan={np.median(tr):+.4f}  pozitif={np.mean(tr>0)*100:.1f}%")
    print(f"  TEST medyan={np.median(te):+.4f}  pozitif={np.mean(te>0)*100:.1f}%")
    en = max(G.items(), key=lambda kv: kv[1]["R"])
    orta = G[(LB, SL_A, RR, MH)]
    sig = float(np.std(tum, ddof=1))
    tavan = sig * np.sqrt(2 * np.log(N))
    print(f"  (f) GURULTU TAVANI: N={N} hucre, sigma(hucre ortR)={sig:.4f} → "
          f"sigma*sqrt(2lnN)={tavan:+.4f}")
    print(f"      en iyi hucre {en[0]} R={en[1]['R']:+.4f} · izgara ortasi R={orta['R']:+.4f}")
    print(f"      izgara ortasi tavani asiyor mu: {'EVET' if orta['R'] > tavan else 'HAYIR → YOK hukmunde'}")
    # bagimsizlik: ayni lb ayni giris setini paylasir
    print(f"  (d) UYARI: {N} hucre = {len(LB_G)} lb x {N//len(LB_G)} cikis kurali. "
          f"Sinyal seti YALNIZ lb'ye bagli → etkin df ~= {len(LB_G)}")
    for lb in LB_G:
        s = np.array([v["RTE"] for k, v in G.items() if k[0] == lb])
        print(f"      lb={lb}: TEST medyan={np.median(s):+.4f} pozitif={np.mean(s>0)*100:.0f}%")
    return G


# ═══════════════════ FUNDING / TUTUS SURESI ═══════════════════
def funding_rapor(src="local"):
    from kronos.motor import _funding_R
    fund = funding_yukle(COINS_LIVE)
    K = kol_kos(src, fund=fund, etiket="kol_orta")
    A = taban_kos(src)
    print(f"\n{'='*100}\n=== SURTUNME · TUTUS SURESI · FUNDING ===")
    for ad, S in (("KOL(cvd)", K), ("TABAN", A)):
        sa = np.array([(x.cikis_ts - x.giris_ts).total_seconds()/3600.0 for x in S])
        sp = np.array([x.sl_pct for x in S])
        ky = (15.85/1e4) / sp
        print(f"  {ad:<10} n={len(S)}  tutus saat: ort={sa.mean():6.1f} medyan={np.median(sa):6.1f} "
              f"max={sa.max():6.1f}  (funding odemesi ~ {sa.mean()/8:.1f} kez/islem)")
        print(f"  {'':<10} stop%: medyan={np.median(sp)*100:.2f}  kayma bedeli={ky.mean():.4f}R")
    print(f"\n  BTC funding verisi depoda: {'VAR' if 'BTC' in fund else 'YOK'} "
          f"→ kol icin funding GERCEK DEGIL, PROXY ile olculur")
    px = btc_funding_proxy(fund)
    print(f"  ETH funding kapsami: {fund['ETH'].index[0].date()}..{fund['ETH'].index[-1].date()} "
          f"n={len(fund['ETH'])}" if "ETH" in fund else "  ETH funding YOK")
    for ad, ser in px.items():
        bed = []
        for x in K:
            s = fund.get(x.coin) if x.coin in fund else ser
            bed.append(_funding_R(ser if x.coin == "BTC" else s,
                                  x.giris_ts, x.cikis_ts, x.yon, x.sl_pct))
        bed = np.array(bed)
        print(f"  proxy '{ad}': funding bedeli ort={bed.mean():+.4f}R  "
              f"(kolun ort R'sinin %{abs(bed.mean())/max(abs(np.mean([x.R for x in K])),1e-9)*100:.1f}'i)  "
              f"max tek islem={bed.max():+.4f}R  medyan oran={float(ser.median()):+.6f}")
    RA = np.array([x.R for x in A])
    print(f"\n  TABAN funding bedeli (gercek veri): ", end="")
    b = np.array([_funding_R(fund.get(x.coin), x.giris_ts, x.cikis_ts, x.yon, x.sl_pct) for x in A])
    print(f"ort={b.mean():+.4f}R (brief: -0.0054R)  → isaret: R'den DUSULUR")
    return K


# ═══════════════════ DUZELTME · NULL · PERMUTASYON · (f) ═══════════════════
class CvdKolNull(CvdKol):
    """AYNI dip sinyali, CVD SARTI YOK (null kontrolu)."""
    ad = "cvdnull"
    def sinyal(self, i):
        lb = self.lb
        if i < lb + 15 or i >= self.besleme.n - 1: return None
        lo = self._lo
        if lo[i] > lo[i - lb:i + 1].min(): return None
        if not self._ok[i - lb:i + 1].all(): return None
        a = self._atr[i]
        if not np.isfinite(a) or a <= 0: return None
        return 1, self.sl_a * a, self.rr, self.mh


def duzeltme(src="local"):
    from kronos.motor import _funding_R
    fund = funding_yukle(COINS_LIVE)
    px = btc_funding_proxy(fund)
    print(f"\n{'='*100}\n=== DUZELTME 1 · BTC FUNDING PROXY ILE YENIDEN ===")
    A = taban_kos(src)
    RA = np.array([x.R for x in A]); topA, ayA = kar_pct(A)
    topA_te, _ = kar_pct([x for x in A if x.giris_ts >= SPLIT])
    for ad, ser in px.items():
        f2 = dict(fund); f2["BTC"] = ser
        K = kol_kos(src, fund=f2)
        R = np.array([x.R for x in K])
        z = R.mean()/R.std(ddof=1)*np.sqrt(len(R))
        TR, TE = tr_te(K); RTE = np.array([x.R for x in TE])
        C = A + K
        RC = np.array([x.R for x in C]); topC, ayC = kar_pct(C)
        topC_te, _ = kar_pct([x for x in C if x.giris_ts >= SPLIT])
        S = olcek_bul(K, dd_bilesik(A))
        print(f"  proxy '{ad}': kol n={len(R)} ortR={R.mean():+.4f} z={z:+.2f} | "
              f"TEST n={len(TE)} ortR={RTE.mean():+.4f}")
        print(f"      birlesik toplam%={topC:+.2f} (taban {topA:+.2f}, Delta {topC-topA:+.2f}pp) "
              f"maxDD%={dd_bilesik(C):.2f} kotuAy%={ayC.min():+.2f} TEST Delta {topC_te-topA_te:+.2f}pp S={S:.3f}")
        print(f"      (a) okuma-1 kitap ortR Delta={RC.mean()-RA.mean():+.4f} | "
              f"okuma-2 kol-taban={R.mean()-RA.mean():+.4f}")
        for c in sorted({x.coin for x in K}):
            Rc = np.array([x.R for x in K if x.coin == c])
            print(f"      coin {c}: n={len(Rc)} ortR={Rc.mean():+.4f}")

    print(f"\n{'='*100}\n=== DUZELTME 2 · NULL KONTROL (CVD sarti KALDIRILDI) ===")
    f2 = dict(fund); f2["BTC"] = px.get("medyan")
    for lb in LB_G:
        Kn = Kronos([CvdKolNull(c, src, n, None, lb, SL_A, RR, MH)
                     for n, c in enumerate(kol_coinleri())], AYAR(f2)).kos()
        Kc = Kronos([CvdKol(c, src, n, None, lb, SL_A, RR, MH)
                     for n, c in enumerate(kol_coinleri())], AYAR(f2)).kos()
        Rn = np.array([x.R for x in Kn]); Rc = np.array([x.R for x in Kc])
        print(f"  lb={lb:<3d} NULL(dip, CVD yok) n={len(Rn):<4d} ortR={Rn.mean():+.4f}   "
              f"CVD'li n={len(Rc):<4d} ortR={Rc.mean():+.4f}   katki={Rc.mean()-Rn.mean():+.4f}R")
        # permutasyon: NULL kumesinden ayni boyutta rastgele alt-kume
        if len(Rn) > len(Rc) > 0:
            rng = np.random.default_rng(7)
            sim = np.array([rng.choice(Rn, size=len(Rc), replace=False).mean() for _ in range(2000)])
            p = float((sim >= Rc.mean()).mean())
            print(f"        permutasyon (2000, ayni boyutta rastgele alt-kume): p={p:.4f}  "
                  f"null ort={sim.mean():+.4f} sd={sim.std():.4f}")

    print(f"\n{'='*100}\n=== DUZELTME 3 · (f) GURULTU TAVANI (dogru sigma) ===")
    K = kol_kos(src, fund=f2)
    R = np.array([x.R for x in K]); se = R.std(ddof=1)/np.sqrt(len(R))
    for N, etk in ((81, "81 hucre BAGIMSIZ varsayimi"), (3, "etkin df=3 (sinyal seti yalniz lb'ye bagli)")):
        t = se*np.sqrt(2*np.log(N))
        print(f"  N={N:<3d} ({etk}): SE={se:.4f} → tavan={t:+.4f}  "
              f"izgara ortasi {R.mean():+.4f} {'ASIYOR' if R.mean()>t else 'ALTINDA → YOK hukmunde'}")

    print(f"\n{'='*100}\n=== DUZELTME 4 · CANLI KITAP COINLERIYLE SINIRLI ===")
    Ke = Kronos([CvdKol("ETH", src, 0, None, LB, SL_A, RR, MH)], AYAR(f2)).kos()
    Re = np.array([x.R for x in Ke])
    print(f"  Canli kitapta OLAN tek taker-verili coin: ETH → n={len(Re)} ortR={Re.mean():+.4f}")
    print(f"  BTC canli kitapta YOK (DONCHIAN_SYMBOLS/SQZ/BB icinde degil) → bu kol ancak")
    print(f"  BTC deploy edilerek calisir; olcumun {len([x for x in K if x.coin=='BTC'])}/{len(K)} islemi BTC.")


# ═══════════════════ MAIN ═══════════════════
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hepsi"
    src = "local"
    if cmd == "veri": veri_denetim()
    elif cmd == "t2": t2(src)
    elif cmd == "taban": taban_rapor(src)
    elif cmd == "kol": kol_rapor(src)
    elif cmd == "aile": aile_rapor(src)
    elif cmd == "funding": funding_rapor(src)
    elif cmd == "duzeltme": duzeltme(src)
    elif cmd == "birlesik":
        A, ok = taban_rapor(src); K = kol_rapor(src); birlesik_rapor(A, K)
    else:
        veri_denetim(); t2(src)
        A, ok = taban_rapor(src)
        K = kol_rapor(src)
        birlesik_rapor(A, K)
        funding_rapor(src)
        aile_rapor(src)


