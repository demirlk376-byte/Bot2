"""
cd_tani.py — KRONOS'ta cooldown'in 1723 -> 240 yapmasinin MEKANIZMASINI dokumler.

Tek kosu (2/240dk, kol:coin) yapar ve HAM olay listelerini pickle'lar:
  tetikler = [(ts, anahtar, streak)]   arm olaylari
  engeller = [(ts, anahtar)]           bloklanan sinyal degerlendirmeleri
  islemler = acilan/kapanan islemler
Sonra aritmetigi dogrular:
  arm sayisi <= islem sayisi mi?  bir arm penceresi kac bar sürüyor?
  blok/arm orani ne?  (240dk = donchian'da 1 bar, 1h kollarda 4 bar OLMALI)
"""
from __future__ import annotations
import pickle, time, sys
from collections import Counter, defaultdict
import numpy as np, pandas as pd

from kronos.kollar import canli_kollar
from kronos_cd_varyant import VaryantKronos, VAyar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
TABAN = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=190.0, kayma_bp=15.85)

t0 = time.time()
K = canli_kollar(SRC)
m = VaryantKronos(K, VAyar(**TABAN, ayni_bar_giris=True,
                           ardisik_zarar_limiti=2, cooldown_dk=240))
isl = m.kos()
print(f"kosu {time.time()-t0:.0f}sn", flush=True)
print(f"n={len(isl)} · sayac={m.sayac}")

tet = pd.DataFrame(m.tetikler, columns=["ts", "anahtar", "streak"]) if m.tetikler else pd.DataFrame(columns=["ts","anahtar","streak"])
eng = pd.DataFrame(m.engeller, columns=["ts", "anahtar"]) if m.engeller else pd.DataFrame(columns=["ts","anahtar"])
df = pd.DataFrame([dict(kol=t.kol, coin=t.coin, giris=t.giris_ts, cikis=t.cikis_ts,
                        R=t.R, pnl=t.pnl, neden=t.neden) for t in isl])
df["anahtar"] = df.kol + ":" + df.coin
pickle.dump(dict(tet=tet, eng=eng, df=df, sayac=m.sayac),
            open("/home/user/Bot2/cd_tani.pkl", "wb"))

print(f"\n### ARITMETIK")
print(f"  islem (acildi)      = {m.sayac['acildi']}   len(islemler)={len(df)}")
print(f"  arm (cd_tetik)      = {len(tet)}")
print(f"  blok (cd_engel)     = {len(eng)}")
kapanan = int((df.neden != 'veri_sonu').sum())
kayip = int(((df.neden != 'veri_sonu') & (df.pnl < 0)).sum())
print(f"  kapanan islem       = {kapanan} · bunlarin KAYIP olani = {kayip}")
print(f"  >>> arm <= kayip olmali: {len(tet)} <= {kayip} ? {len(tet) <= kayip}")
if len(tet):
    print(f"  blok / arm          = {len(eng)/len(tet):.2f}")
print(f"\n  arm kol dagilimi : {dict(Counter(a.split(':')[0] for a in tet.anahtar))}")
print(f"  blok kol dagilimi: {dict(Counter(a.split(':')[0] for a in eng.anahtar))}")
print(f"  islem kol dagilimi: {dict(Counter(df.kol))}")

# her arm'dan sonra kac blok var, kac bar icinde
if len(tet) and len(eng):
    print(f"\n### ARM PENCERESI GERCEKTEN 240 DK MI?")
    eg = defaultdict(list)
    for _, r in eng.iterrows(): eg[r.anahtar].append(r.ts)
    for a in eg: eg[a].sort()
    gec = []
    for _, r in tet.iterrows():
        for ts in eg[r.anahtar]:
            d = (ts - r.ts).total_seconds() / 60
            if 0 <= d: gec.append(d)
    gec = np.array(sorted(gec))
    print(f"  arm -> blok gecikmesi (dk): min {gec.min():.0f} · p50 {np.median(gec):.0f}"
          f" · p90 {np.percentile(gec,90):.0f} · max {gec.max():.0f}")
    print(f"  240dk'dan BUYUK gecikmeli blok sayisi: {int((gec>240).sum())}/{len(gec)}"
          f"  (0 olmali; degilse pencere sizinti yapiyor)")

    # HER BLOGUN en yakin ONCEKI arm'a uzakligi -> gercek pencere
    yak = []
    tg = defaultdict(list)
    for _, r in tet.iterrows(): tg[r.anahtar].append(r.ts)
    for a in tg: tg[a].sort()
    for _, r in eng.iterrows():
        v = [t for t in tg[r.anahtar] if t <= r.ts]
        if v: yak.append((r.ts - v[-1]).total_seconds() / 60)
    yak = np.array(yak)
    print(f"  blok -> en yakin ONCEKI arm uzakligi (dk): "
          f"min {yak.min():.0f} p50 {np.median(yak):.0f} max {yak.max():.0f}")
    print(f"  histogram: {dict(sorted(Counter((yak//60).astype(int)).items()))}  (saat cinsinden)")

print(f"\ntoplam {time.time()-t0:.0f} sn")
