"""
gunluk_netted.py — AYRI HAVUZUN MODELLEMEDİĞİ KISIT: MEXC NETTED TEK-POZİSYON/COIN.

Ayrı havuz iki KRONOS koşusunu yan yana koyar; gerçekte iki kitap AYNI BORSA
hesabında çalışır ve MEXC netted modda bir sembol = bir net pozisyon
(execution.py:403 "One-position-per-symbol guard (LIVE/netted only)"). Günlük kol
SOL'u 17 gün tutarsa kitabın SOL donchian'ı O SÜRE BOYUNCA giremez. Ayrı havuz
bunu göremez çünkü iki koşu birbirini görmüyor.

Bu dosya kısıtı GERÇEKTEN uygular: TEK motor, TEK zaman çizgisi, kitap kolları
+ günlük kol birlikte, `tek_pozisyon_per_coin=True`. Koltuk havuzu 7+S yapılır
(ayrı havuzun "kola S ekstra koltuk" niyetinin tek-motor karşılığı; hatta daha
CÖMERT, çünkü kol koltuk kullanmazsa kitap kullanabilir).

ÜÇ KONFİGÜRASYON — kolun marjinal katkısını koltuk artışından AYIRIR:
  A  kitap, 7 koltuk                     (CANLI = ön-kayıtlı taban)
  B  kitap, 7+S koltuk                   (yalnız koltuk artışı, kol YOK)
  C  kitap + GÜNLÜK kol, 7+S koltuk      (kol var, netted kısıt GERÇEK)
Kolun katkısı = C − B. Canlıya göre net = C − A.
Risk her seferinde A'nın bileşik maxDD'sine eşitlenir.

Kullanım: py gunluk_netted.py local
"""
import sys, os, pickle
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle
from gunluk_kol import gunluk_kollar, gunluk_veri

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
BAL0, KAYMA = 1000.0, 15.85
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
COINS = DB.DONCH + DB.SQZ
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
CANLI = dict(riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
CH, ESP, SL_A, RR, MH = 50, 200, 2.0, 3.0, 40
fund = funding_yukle(DB.DONCH + DB.SQZ + DB.BB_COINS)


def diz(isl):
    tk = sorted(isl, key=lambda t: (t.cikis_ts.value, t.giris_ts.value, t.kol, t.coin))
    return (np.array([t.R for t in tk]), np.array([t.eff for t in tk]),
            np.array([t.giris_ts.value for t in tk]),
            pd.to_datetime([t.cikis_ts for t in tk]))


def dd(R, e, o):
    b = np.concatenate([[1.0], np.cumprod(1 + R * e * o)]); p = np.maximum.accumulate(b)
    return float(((p - b) / p).max() * 100)


def esitle(R, e, h):
    if dd(R, e, 1.0) <= h: return 1.0
    lo, hi = 0.02, 1.0
    for _ in range(60):
        m = (lo + hi) / 2
        if dd(R, e, m) > h: hi = m
        else: lo = m
    return (lo + hi) / 2


def olc(isl, o):
    R, e, g, x = diz(isl)
    pnl = R * e * o * BAL0
    ay = pd.Series(pnl, index=x.tz_localize(None).to_period("M")).groupby(level=0).sum() / BAL0 * 100
    m = g >= SPLIT.value
    return dict(n=len(R), ortR=float(R.mean()), top=float(pnl.sum()) / BAL0 * 100,
                te=float(pnl[m].sum()) / BAL0 * 100, aylik=float(ay.mean()),
                dd=dd(R, e, o), kotu=float(ay.min()), o=o)


def satir(ad, r, A=None, ek=""):
    d = "" if A is None else (f"{r['top']-A['top']:>+9.2f} {r['te']-A['te']:>+9.2f} "
                              f"{r['aylik']-A['aylik']:>+8.2f} {r['ortR']-A['ortR']:>+8.4f}")
    print(f"  {ad:<34} n={r['n']:>5d} ölç {r['o']:>5.3f} top %{r['top']:>+8.2f} "
          f"TEST %{r['te']:>+8.2f} ay %{r['aylik']:>+6.2f} DD %{r['dd']:>5.2f} "
          f"kötüay %{r['kotu']:>+7.2f} {d} {ek}")


kk = canli_kollar(SRC)
ob = {c: gunluk_veri(c, SRC) for c in COINS}
KP = f"{SCR}/kitap_funding.pkl"
kitap = pickle.load(open(KP, "rb")) if os.path.exists(KP) else \
    Kronos(kk, Ayar(maxpos=7, kayma_bp=KAYMA, funding=fund, **CANLI)).kos()
Ra, ea, _, _ = diz(kitap)
dd_A = dd(Ra, ea, 1.0)
A = olc(kitap, 1.0)

print(f"\n{'='*150}\n=== NETTED TEK-POZİSYON/COIN · TEK MOTOR · GÜNLÜK KOL (ch{CH}/ema{ESP}/sl{SL_A}/rr{RR}/mh{MH}) ===")
print(f"  {'':<34} {'':<7} {'':<9} {'':<9} {'':<15} {'':<14}  {'Δtop%':>9} {'ΔTEST%':>9} {'Δay%':>8} {'ΔortR':>8}")
satir("A  kitap 7 koltuk (CANLI TABAN)", A)
for S in (1, 2, 3):
    bs = Kronos(kk, Ayar(maxpos=7 + S, kayma_bp=KAYMA, funding=fund, **CANLI)).kos()
    Rb_, eb_, _, _ = diz(bs)
    Bs = olc(bs, esitle(Rb_, eb_, dd_A))
    kol = gunluk_kollar(COINS, SRC, None, CH, ESP, SL_A, RR, MH, ob)
    cs = Kronos(kk + kol, Ayar(maxpos=7 + S, kayma_bp=KAYMA, funding=fund, **CANLI)).kos()
    ng = sum(1 for t in cs if t.kol == "gunluk")
    Rc, ec, _, _ = diz(cs)
    C = olc(cs, esitle(Rc, ec, dd_A))
    print()
    satir(f"B  kitap {7+S} koltuk (kol YOK)", Bs, A)
    satir(f"C  kitap+gunluk {7+S} koltuk", C, A, ek=f"| gunluk {ng} işlem")
    print(f"  {'kolun MARJİNAL katkısı (C−B)':<34} Δtop %{C['top']-Bs['top']:+.2f} · "
          f"ΔTEST %{C['te']-Bs['te']:+.2f} · Δay %{C['aylik']-Bs['aylik']:+.2f} · "
          f"ΔortR {C['ortR']-Bs['ortR']:+.4f} · kötüay %{C['kotu']:+.2f}")
print(f"{'='*150}\n")
