"""
gunluk_aile.py — AYRI HAVUZ · AİLE TESTİ · FUNDING DAHİL (270 kombinasyon).

2026-09-12'deki aynı test funding OLMADAN koşulmuştu ve kolu ZATEN öldürmüştü:
TEST medyanı +$4.50, TEST pozitif oran %54.4 (yazı-turadan 1.45σ), TRAIN/TEST
12-18x ayrışma. Bu dosya aynı aileyi FUNDING'li ve YENİ TABANA karşı yeniden
koşar: reddi teyit mi ediyor, yoksa sayı mı değişiyor?

Tek hücre kanıt değildir; hüküm ailenin TEST medyanına ve pozitif hücre oranına
bakılarak verilir. Ölçü birimi Δ toplam getiri YÜZDESİ (taban $1000).

Kullanım: py gunluk_aile.py local
"""
import sys, os, pickle, itertools
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle
from gunluk_kol import gunluk_kollar, gunluk_veri

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
BAL0, KAYMA = 1000.0, 15.85
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
COINS = DB.DONCH + DB.SQZ
TUM = DB.DONCH + DB.SQZ + DB.BB_COINS
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
KOL_AYAR = dict(riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
                tek_pozisyon_per_coin=True)   # canlı frenler KAPALI = kola avantaj
CH_G, EMA_G, SL_G, RR_G, MH_G = [20, 30, 50, 80, 100], [100, 200], [1.5, 2.0, 3.0], [2.0, 3.0, 4.0], [20, 40, 60]
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
fund = funding_yukle(TUM)


def diz(isl):
    tk = sorted(isl, key=lambda t: (t.cikis_ts.value, t.giris_ts.value, t.kol, t.coin))
    return (np.array([t.R for t in tk]), np.array([t.eff for t in tk]),
            np.array([t.giris_ts.value for t in tk]),
            pd.to_datetime([t.cikis_ts for t in tk]))


def dd(R, eff, o):
    b = np.concatenate([[1.0], np.cumprod(1 + R * eff * o)])
    p = np.maximum.accumulate(b)
    return float(((p - b) / p).max() * 100)


def esitle(R, eff, hedef):
    if dd(R, eff, 1.0) <= hedef: return 1.0
    lo, hi = 0.02, 1.0
    for _ in range(50):
        m = (lo + hi) / 2
        if dd(R, eff, m) > hedef: hi = m
        else: lo = m
    return (lo + hi) / 2


def olc(R, eff, gi, ex, o):
    pnl = R * eff * o * BAL0
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / BAL0 * 100
    m = gi >= SPLIT.value
    return (float(pnl.sum()) / BAL0 * 100, float(pnl[m].sum()) / BAL0 * 100,
            float(R.mean()), float(ay.min()))


# ── taban (pahalı: bir kez, önbelleğe) ──
KC = f"{SCR}/kitap_funding.pkl"
if os.path.exists(KC):
    kitap = pickle.load(open(KC, "rb")); print(f"  taban önbellekten: {len(kitap)} işlem")
else:
    kitap = Kronos(canli_kollar(SRC), Ayar(kayma_bp=KAYMA, funding=fund, **CANLI)).kos()
    os.makedirs(SCR, exist_ok=True); pickle.dump(kitap, open(KC, "wb"))
Rb, eb, gb, xb = diz(kitap)
dd_A = dd(Rb, eb, 1.0)
topA, teA, ortRA, kotuA = olc(Rb, eb, gb, xb, 1.0)
print(f"\n{'='*112}\n=== AYRI HAVUZ · AİLE TESTİ · FUNDING DAHİL ===")
print(f"  taban: n={len(Rb)} ortR {ortRA:+.4f} toplam %{topA:+.2f} (TEST %{teA:+.2f}) "
      f"bileşikDD %{dd_A:.2f} en kötü ay %{kotuA:.2f}")

ob = {c: gunluk_veri(c, SRC) for c in COINS}
kombo = list(itertools.product(CH_G, EMA_G, SL_G, RR_G, MH_G))
print(f"  ızgara: {len(CH_G)}ch x {len(EMA_G)}ema x {len(SL_G)}sl x {len(RR_G)}rr x {len(MH_G)}mh "
      f"= {len(kombo)} kombinasyon x S∈{{1,2,3}}")

for S in (1, 2, 3):
    a = dict(KOL_AYAR); a["maxpos"] = S
    dtop, dte, dR, kotu, nkol = [], [], [], [], []
    for z, (ch, esp, sl_a, rr, mh) in enumerate(kombo):
        kol = Kronos(gunluk_kollar(COINS, SRC, None, ch, esp, sl_a, rr, mh, ob),
                     Ayar(kayma_bp=KAYMA, funding=fund, **a)).kos()
        if not kol: continue
        Rc, ec, gc, xc = diz(kitap + kol)
        o = esitle(Rc, ec, dd_A)
        t, te, r_, k_ = olc(Rc, ec, gc, xc, o)
        dtop.append(t - topA); dte.append(te - teA); dR.append(r_ - ortRA)
        kotu.append(k_); nkol.append(len(kol))
        if (z + 1) % 60 == 0:
            print(f"    S={S} {z+1}/{len(kombo)} ...", flush=True)
    A_, T_, R_, K_ = map(np.array, (dtop, dte, dR, kotu))
    n = len(A_)
    poz = (T_ > 0).mean()
    sig = (poz - 0.5) / np.sqrt(0.25 / max(n, 1))          # bağımsız varsayımıyla ÜST sınır
    print(f"\n  S={S} koltuk · {n} kombinasyon · medyan kol n={np.median(nkol):.0f}")
    print(f"    TÜM DÖNEM Δtoplam%  medyan {np.median(A_):+8.2f} · pozitif %{(A_>0).mean()*100:5.1f} · "
          f"aralık [{A_.min():+.1f}, {A_.max():+.1f}]")
    print(f"    TEST      Δtoplam%  medyan {np.median(T_):+8.2f} · pozitif %{poz*100:5.1f} · "
          f"aralık [{T_.min():+.1f}, {T_.max():+.1f}]")
    print(f"    ΔortR              medyan {np.median(R_):+8.4f} · pozitif %{(R_>0).mean()*100:5.1f} · "
          f"bar +0.0694'ü geçen %{(R_>=0.0694).mean()*100:.1f}")
    print(f"    en kötü ay medyan %{np.median(K_):+.2f} (taban %{kotuA:.2f}) · "
          f"kötüleşen %{(K_<kotuA).mean()*100:.0f}")
    print(f"    yazı-tura sapması (bağımsız varsayımı, ÜST sınır): {sig:+.2f}σ; "
          f"etkin df 10-20 varsayılırsa {sig*np.sqrt(15/max(n,1)):+.2f}σ")
    gec = np.median(T_) > 0 and poz > 0.5 and np.median(A_) > 0
    print(f"    → {'✓ aile geçti' if gec else '✗ AİLE GEÇMEDİ'}")
print(f"{'='*112}\n")
