"""kronos_tani.py — cooldown neden 1723→240 yapıyor? ÖLÇ, tahmin etme."""
import sys, numpy as np, pandas as pd, deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
kollar = canli_kollar(SRC)
T = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=A.BAL0, kayma_bp=15.85, ayni_bar_giris=True)
for ad, ek in (("cooldown YOK", {}),
               ("cooldown 2/240dk", dict(ardisik_zarar_limiti=2, cooldown_dk=240)),
               ("cooldown 2/60dk",  dict(ardisik_zarar_limiti=2, cooldown_dk=60)),
               ("cooldown 3/240dk", dict(ardisik_zarar_limiti=3, cooldown_dk=240))):
    m = Kronos(kollar, Ayar(**T, **ek)); isl = m.kos(); c = m.sayac
    print(f"  {ad:<20s} açıldı {c['acildi']:>5d} · cd_engel {c['cd_engel']:>6d} · "
          f"koltuk_engel {c['koltuk_engel']:>5d} · işlem {len(isl):>5d} · "
          f"${sum(t.pnl for t in isl):>+9.2f}")
