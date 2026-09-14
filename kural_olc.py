"""
kural_olc.py — İKİ TASARIM KURALINI kitabın KENDİ işlemleri üzerinde ölçer.

KURAL 1 (geniş stop ucuz): kayma bedeli = 15.85bp / stop_mesafesi.
KURAL 2 (uzun tutuş pahalı): funding bedeli = Σrate / sl_pct, tutuşla artar.

İkisi birlikte bir OPTİMUM tarif ediyor olabilir: geniş stop + kısa tutuş.
Kitap o düzlemde nerede? Ve kurallar gerçekten doğrusal mı, yoksa geniş stoplu
işlemlerin ham edge'i mi düşük (o zaman "avantaj" bir yanılsama olur)?

Bu bir strateji testi DEĞİL — tasarım kuralı doğrulaması. Deploy önerisi üretmez.
"""
import sys
import numpy as np, pandas as pd
import deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar, funding_yukle

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
COINLER = A.DONCH + A.SQZ + A.BB_COINS
fund = funding_yukle(COINLER)
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=1000.0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
kollar = canli_kollar(SRC)

ham  = Kronos(kollar, Ayar(kayma_bp=0.0,   **CANLI)).kos()          # ham R
tam  = Kronos(kollar, Ayar(kayma_bp=15.85, funding=fund, **CANLI)).kos()
assert len(ham) == len(tam) == 1712, f"taban {len(ham)}/{len(tam)} — 1712 bekleniyordu"

d = pd.DataFrame({
    "kol":   [t.kol for t in ham],
    "coin":  [t.coin for t in ham],
    "hamR":  [t.R for t in ham],
    "tamR":  [t.R for t in tam],
    "sl_pct":[t.sl_pct for t in ham],
    "saat":  [(t.cikis_ts - t.giris_ts).total_seconds()/3600 for t in ham],
})
d["kayma_R"]   = 15.85/1e4 / d["sl_pct"]
d["surtR"]     = d["hamR"] - d["tamR"]
d["funding_R"] = d["surtR"] - d["kayma_R"]

print(f"\n{'='*104}\n=== TASARIM KURALLARI — kitabın 1712 işlemi üzerinde ===")
print(f"  taban: ham ortR {d.hamR.mean():+.4f} · tam ortR {d.tamR.mean():+.4f} · "
      f"stop medyan %{d.sl_pct.median()*100:.2f} · tutuş medyan {d.saat.median():.0f}s")

print(f"\n── KURAL 1: STOP GENİŞLİĞİ (5 dilim, eşit sayıda) ──")
print(f"  {'stop aralığı':<18s} {'n':>5s} {'ham ortR':>9s} {'kayma R':>8s} {'tam ortR':>9s} {'kayma/ham':>10s}")
d["q_stop"] = pd.qcut(d.sl_pct, 5, labels=False)
for q in range(5):
    g = d[d.q_stop == q]
    pay = g.kayma_R.mean()/abs(g.hamR.mean())*100 if g.hamR.mean() != 0 else float('nan')
    print(f"  %{g.sl_pct.min()*100:5.2f}–%{g.sl_pct.max()*100:5.2f}      {len(g):>5d} "
          f"{g.hamR.mean():>+9.4f} {g.kayma_R.mean():>8.4f} {g.tamR.mean():>+9.4f} {pay:>9.0f}%")

print(f"\n── KURAL 2: TUTUŞ SÜRESİ (5 dilim, eşit sayıda) ──")
print(f"  {'tutuş (saat)':<18s} {'n':>5s} {'ham ortR':>9s} {'fund R':>8s} {'tam ortR':>9s} {'fund/kayma':>11s}")
d["q_sure"] = pd.qcut(d.saat, 5, labels=False)
for q in range(5):
    g = d[d.q_sure == q]
    oran = g.funding_R.mean()/g.kayma_R.mean() if g.kayma_R.mean() else float('nan')
    print(f"  {g.saat.min():5.0f}–{g.saat.max():5.0f}         {len(g):>5d} "
          f"{g.hamR.mean():>+9.4f} {g.funding_R.mean():>8.4f} {g.tamR.mean():>+9.4f} {oran:>10.2f}x")

# funding dogrusal mi?
korel = np.corrcoef(d.saat, d.funding_R)[0,1]
egim = np.polyfit(d.saat, d.funding_R, 1)[0]
print(f"\n  funding ↔ tutuş korelasyonu {korel:+.3f} · eğim {egim:+.6f}R/saat")
print(f"  → 24 GÜNLÜK (576s) bir kol kabaca {egim*576:+.4f}R funding öderdi "
      f"(kitap {d.funding_R.mean():+.4f}R)")
esik = d.kayma_R.mean()/egim if egim else float('nan')
print(f"  → funding, kaymayı {esik:.0f} saat (~{esik/24:.1f} gün) tutuştan sonra GEÇER")

print(f"\n── KOL BAZINDA ──")
for k, g in d.groupby("kol"):
    print(f"  {k:<10s} n={len(g):>4d} stop %{g.sl_pct.median()*100:5.2f} tutuş {g.saat.median():>5.0f}s "
          f"ham {g.hamR.mean():+.4f} → tam {g.tamR.mean():+.4f} "
          f"(kayma {g.kayma_R.mean():.4f} · fund {g.funding_R.mean():+.4f})")
print(f"{'='*104}\n")
