"""
gunluk_ilke.py — "FUNDING UZUN TUTAN HER STRATEJİYİ VURUR" TEZİNİ SAYIYLA SINAR.

Funding'in R bedeli motorun formülüyle:   f_R = Σrate / sl_pct
Yani bedel tutuş süresinin TEK BAŞINA fonksiyonu DEĞİL: pay (Σrate) süreyle
doğrusal büyür, PAYDA (stop genişliği) ise stratejinin hangi bar ölçeğinde
çalıştığına bağlıdır. İki ayrı deney bunu ayırır:

  (A) AYNI bar ölçeği (1D), max-hold uzatılıyor → sl_pct SABİT kalır.
      Beklenti: bedel süreyle ~DOĞRUSAL (log-log eğim ≈ 1).
  (B) FARKLI bar ölçeği (1h / 4h / 1D), stop = k×ATR(o ölçek) → sl_pct de büyür.
      Beklenti: bedel süreyle ~KAREKÖK (log-log eğim ≈ 0.5).

Hangisi doğruysa gelecekteki uzun-horizon fikirleri için tasarım kuralı O.
Kullanım: py gunluk_ilke.py local
"""
import sys, pickle
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.kollar import funding_yukle
from gunluk_kol import gunluk_kollar, gunluk_veri

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
COINS = DB.DONCH + DB.SQZ
fund = funding_yukle(DB.DONCH + DB.SQZ + DB.BB_COINS)
KOL = dict(riskf=0.028, cap=1.50, bal0=1000.0, ayni_bar_giris=True,
           tek_pozisyon_per_coin=True, maxpos=10**9)


def fd(isl):
    g, f, sp, ad = [], [], [], []
    for t in isl:
        s = fund.get(t.coin)
        g.append((t.cikis_ts - t.giris_ts).total_seconds() / 86400)
        sp.append(t.sl_pct)
        if s is None: f.append(0.0); ad.append(0); continue
        m = s.loc[(s.index > t.giris_ts) & (s.index <= t.cikis_ts)]
        ad.append(len(m)); f.append(float(t.yon * m.sum() / t.sl_pct) if t.sl_pct > 0 else 0.0)
    return map(np.array, (g, f, sp, ad))


def egim(x, y):
    x, y = np.log(np.array(x)), np.log(np.array(y))
    return float(np.polyfit(x, y, 1)[0])


W = 108
ob = {c: gunluk_veri(c, SRC) for c in COINS}
print(f"\n{'='*W}\n=== (A) AYNI BAR ÖLÇEĞİ (1D), max-hold uzuyor · sl_pct SABİT ===")
print(f"  {'mh(gün)':>8}{'n':>6}{'tutuş g':>9}{'ödeme':>8}{'sl_pct%':>9}{'|fundingR|':>12}{'fundingR':>11}")
xs, ys, sls = [], [], []
for mh in (5, 10, 20, 40, 60, 90, 120):
    isl = Kronos(gunluk_kollar(COINS, SRC, None, 50, 200, 2.0, 3.0, mh, ob),
                 Ayar(kayma_bp=15.85, **KOL)).kos()
    g, f, sp, ad = fd(isl)
    print(f"  {mh:>8d}{len(g):>6d}{g.mean():>9.2f}{ad.mean():>8.2f}{sp.mean()*100:>9.2f}"
          f"{np.abs(f).mean():>12.5f}{f.mean():>+11.5f}")
    xs.append(g.mean()); ys.append(np.abs(f).mean()); sls.append(sp.mean())
print(f"  log-log eğim (|fundingR| ~ tutuş^b): b = {egim(xs, ys):.3f}   "
      f"[1.0 = doğrusal, 0.5 = karekök]")
print(f"  sl_pct log-log eğim (a): {egim(xs, sls):.3f}  ← ~0 beklenir (aynı ölçek, stop sabit)")

print(f"\n{'='*W}\n=== (B) FARKLI BAR ÖLÇEĞİ · stop = k×ATR(o ölçek) → sl_pct de büyür ===")
kit = pickle.load(open(f"{SCR}/kitap_nofunding.pkl", "rb"))
sat = []
for ad_, et in (("squeeze", "squeeze 1h mh48"), ("bb", "bb 1h mh48"), ("donchian", "donchian 4h mh30")):
    sub = [t for t in kit if t.kol == ad_]
    g, f, sp, a_ = fd(sub)
    sat.append((et, len(g), g.mean(), a_.mean(), sp.mean(), np.abs(f).mean(), f.mean()))
isl = Kronos(gunluk_kollar(COINS, SRC, None, 50, 200, 2.0, 3.0, 40, ob),
             Ayar(kayma_bp=15.85, **KOL)).kos()
g, f, sp, a_ = fd(isl)
sat.append(("gunluk 1D mh40", len(g), g.mean(), a_.mean(), sp.mean(), np.abs(f).mean(), f.mean()))
print(f"  {'strateji':<20}{'n':>6}{'tutuş g':>9}{'ödeme':>8}{'sl_pct%':>9}{'|fundingR|':>12}{'fundingR':>11}")
for r in sat:
    print(f"  {r[0]:<20}{r[1]:>6d}{r[2]:>9.2f}{r[3]:>8.2f}{r[4]*100:>9.2f}{r[5]:>12.5f}{r[6]:>+11.5f}")
xs = [r[2] for r in sat]; ys = [r[5] for r in sat]; ss = [r[4] for r in sat]
print(f"  log-log eğim (|fundingR| ~ tutuş^b): b = {egim(xs, ys):.3f}")
print(f"  log-log eğim (sl_pct   ~ tutuş^a): a = {egim(xs, ss):.3f}   "
      f"[0.5 = rastgele yürüyüş; stop horizon volatilitesiyle büyüyor demek]")
print(f"  → b ≈ 1 − a bekleniyor (f_R = Σrate/sl_pct, Σrate ∝ süre)")
print(f"{'='*W}\n")
