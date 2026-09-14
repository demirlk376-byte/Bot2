"""
cd_aralik.py — COOLDOWN'in BAGLAYICI olup olmadigini belirleyen tek olcu:
"bir anahtarda KAYIPLA kapanan islemden sonra, AYNI anahtarda 240 dakika icinde
yeni bir GIRIS oluyor mu?"

Cooldown ancak bu olursa bir seyi engeller.  Canliyi KRONOS'la elma-elmaya
kiyaslamak icin ayni olcuyu iki tarafta da hesaplariz.

Bu script KRONOS tarafini olcer (cooldownSUZ taban kosusu uzerinden):
  - anahtar (kol:coin) basina islem sayisi
  - ayni anahtarda ARDISIK islemler arasi bosluk (onceki CIKIS -> sonraki GIRIS)
  - o bosluklardan kaci <= 240 dk  (= cooldown'in blokllayabilecegi giris sayisi)
  - onceki islem KAYIPSA ve streak>=2 ise gercek blok

Ayrica islemleri /home/user/Bot2/cd_taban_islemler.csv'ye yazar.
"""
from __future__ import annotations
import sys, time
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
TABAN = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=190.0, kayma_bp=15.85)

t0 = time.time()
K = canli_kollar(SRC)
isl = Kronos(K, Ayar(**TABAN, ayni_bar_giris=True)).kos()
print(f"taban kosu {time.time()-t0:.0f}sn · n={len(isl)}", flush=True)

df = pd.DataFrame([dict(kol=t.kol, coin=t.coin, giris=t.giris_ts, cikis=t.cikis_ts,
                        R=t.R, pnl=t.pnl, neden=t.neden) for t in isl])
df["anahtar"] = df.kol + ":" + df.coin
df.to_csv("/home/user/Bot2/cd_taban_islemler.csv", index=False)

gun = (df.cikis.max() - df.giris.min()).total_seconds() / 86400
print(f"\nveri {gun:.0f} gun · {len(df)} islem · {len(df.anahtar.unique())} anahtar"
      f" · {len(df)/gun:.2f} islem/gun")

# ── anahtar basina islem ──
print(f"\n### ANAHTAR BASINA ISLEM (KRONOS)")
c = df.anahtar.value_counts()
for a, n in c.items():
    print(f"  {a:<18s} {n:>5d}")
print(f"  ort {c.mean():.1f} · medyan {c.median():.0f} · min {c.min()} · max {c.max()}")

# ── ardisik islem araligi + cooldown baglayiciligi ──
print(f"\n### AYNI ANAHTARDA: onceki CIKIS -> sonraki GIRIS bosluğu")
sat = []
for a, g in df.sort_values("giris").groupby("anahtar"):
    g = g.sort_values("giris").reset_index(drop=True)
    for i in range(1, len(g)):
        bos = (g.giris[i] - g.cikis[i - 1]).total_seconds() / 60.0
        sat.append(dict(anahtar=a, kol=g.kol[i], bosluk_dk=bos,
                        onceki_kayip=bool(g.pnl[i - 1] < 0)))
B = pd.DataFrame(sat)
print(f"  toplam ardisik cift: {len(B)}")
for kol in sorted(B.kol.unique()):
    s = B[B.kol == kol]
    print(f"  {kol:<10s} n={len(s):<5d} medyan bosluk {s.bosluk_dk.median():>9.0f} dk"
          f" · <=240dk olan %{(s.bosluk_dk <= 240).mean()*100:5.1f}"
          f" ({int((s.bosluk_dk <= 240).sum())} adet)"
          f" · <=240dk VE onceki kayip: {int(((s.bosluk_dk<=240)&s.onceki_kayip).sum())}")
s = B
print(f"  {'TOPLAM':<10s} n={len(s):<5d} medyan bosluk {s.bosluk_dk.median():>9.0f} dk"
      f" · <=240dk olan %{(s.bosluk_dk <= 240).mean()*100:5.1f}"
      f" ({int((s.bosluk_dk <= 240).sum())} adet)"
      f" · <=240dk VE onceki kayip: {int(((s.bosluk_dk<=240)&s.onceki_kayip).sum())}")
print(f"  bosluk yuzdelikleri (dk): " +
      " ".join(f"p{p}={np.percentile(B.bosluk_dk,p):.0f}" for p in (1,5,10,25,50)))
print(f"  bosluk = 0 dk (ayni bar cikis+giris): {int((B.bosluk_dk<=0).sum())}")

# ── ratchet tetikleme sayisi (limit=2, tetikte sifirlama yok) ──
print(f"\n### TETIKLEME (bitisik KAYIP-KAYIP cifti) — cooldownSUZ akista")
for kapsam, f in (("kol:coin", lambda r: r.anahtar), ("kol", lambda r: r.kol),
                  ("coin", lambda r: r.coin), ("genel", lambda r: "G")):
    ser = defaultdict(list)
    for _, r in df[df.neden != "veri_sonu"].sort_values("cikis").iterrows():
        ser[f(r)].append(1 if r.pnl < 0 else 0)
    tet = sum(1 for v in ser.values() for i in range(1, len(v)) if v[i] and v[i-1])
    print(f"  kapsam {kapsam:<10s} anahtar={len(ser):<3d} tetikleme={tet}"
          f"  (islem basina %{tet/len(df)*100:.1f})")

print(f"\ntoplam {time.time()-t0:.0f} sn")
