"""
kronos_canli.py — KRONOS'u VPS'ten okunan GERÇEK canlı konfigürasyonla koşar
ve ankordan farkı KAPI KAPI ayrıştırır.

GERÇEK CANLI AYAR (VPS /opt/bot2/.env, 2026-09-13):
  MAX_POSITIONS=7 · POSITION_CAP_FRACTION=1.5 · RISK_SCALE=1.4
  MAX_RISK_PCT 0.02 x 1.4 = 0.028 · DAILY_MAX_LOSS_PCT=0.35 · LEVERAGE=10
  MAKER_ENTRY=true · DONCHIAN_MAKER_ENTRY=true
  (.env'de YOK → varsayılan) CONSECUTIVE_LOSS_LIMIT=2 · COOLDOWN_MINUTES=240

Motor kronos_test.py ile doğrulandı: ankora denk (1603/0 fark), nedensel
(3 kesim, 0 fark), belirlenimci. Aşağıdaki farklar KAPILARDAN gelir.
"""
import sys
import numpy as np, pandas as pd
import deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
KY = 15.85
kollar = canli_kollar(SRC)

def olc(isl):
    R = np.array([t.R for t in isl]); pnl = np.array([t.pnl for t in isl])
    ex = pd.to_datetime([t.cikis_ts for t in isl])
    eq = np.concatenate([[A.BAL0], A.BAL0 + np.cumsum(pnl)])
    bil = np.concatenate([[1.0], np.cumprod(1 + R * np.array([t.eff for t in isl]))])
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / A.BAL0 * 100
    return dict(n=len(isl), kar=pnl.sum(), ortR=R.mean(), wr=(R > 0).mean() * 100,
                bdd=float(((np.maximum.accumulate(bil) - bil) / np.maximum.accumulate(bil)).max() * 100),
                kotu=ay.min())

TABAN = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=A.BAL0, kayma_bp=KY)
BASAMAK = [
    ("0) ANKOR eşleniği (aynı-bar girişi YASAK, kapı yok)", dict(ayni_bar_giris=False)),
    ("1) + aynı bar girişi (canlı koltuk)",                 dict(ayni_bar_giris=True)),
    ("2) + ardışık zarar cooldown (2 / 240dk)",             dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240)),
    ("3) + günlük zarar freni (%35) = TAM CANLI",           dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35)),
]

print(f"\n{'='*112}\n=== KRONOS · GERÇEK CANLI KONFİGÜRASYON · kapı kapı ayrıştırma (15.85bp kayma dahil) ===")
print(f"  {'basamak':<52s} {'n':>5s} {'$':>10s} {'ortR':>8s} {'WR':>6s} {'bileşikDD':>10s} {'kötüay':>8s}")
onc = None; ilk = None
for ad, ek in BASAMAK:
    m = olc(Kronos(kollar, Ayar(**TABAN, **ek)).kos())
    if ilk is None: ilk = m
    d = "" if onc is None else f"  (Δn {m['n']-onc['n']:+d}  Δ$ {m['kar']-onc['kar']:+.2f}  ΔortR {m['ortR']-onc['ortR']:+.4f})"
    print(f"  {ad:<52s} {m['n']:>5d} {m['kar']:>+10.2f} {m['ortR']:>+8.4f} %{m['wr']:>4.1f} "
          f"%{m['bdd']:>9.2f} %{m['kotu']:>7.2f}")
    if d: print(f"  {'':52s} {d}")
    onc = m
print(f"\n  ANKOR→TAM CANLI: Δn {onc['n']-ilk['n']:+d} · Δ$ {onc['kar']-ilk['kar']:+.2f} "
      f"(%{(onc['kar']-ilk['kar'])/abs(ilk['kar'])*100:+.1f}) · ΔortR {onc['ortR']-ilk['ortR']:+.4f} "
      f"(%{(onc['ortR']-ilk['ortR'])/ilk['ortR']*100:+.1f}) · Δkötüay {onc['kotu']-ilk['kotu']:+.2f} puan")
print(f"{'='*112}\n")
