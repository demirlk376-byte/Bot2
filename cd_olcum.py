"""
cd_olcum.py — COOLDOWN CELISKISI olcumu.

Soru: KRONOS'ta 2-kayip/240dk cooldown islem sayisini 1723 -> 240 dusuruyor,
ama CANLIDA ayni fren 60 gunde yalnizca 2 kez tetiklenmis (2/124 = %1.6).
Neden?

Olculenler:
  A) DENKLIK      : VaryantKronos(varsayilan) == kronos.Kronos(ayni ayar)?
  B) TETIKLEME vs ENGEL: KRONOS'ta cooldown KAC KEZ BASLADI (canlinin
     journalctl'de saydigi sey) ve KAC SINYAL BLOKLADI (sayac[cd_engel]).
  C) ANAHTAR YOGUNLUGU: KRONOS'ta anahtar basina islem dagilimi + bitisik
     kayip-kayip (LL) cifti sayisi.  Canliya ayni formul uygulanir.
  D) VARYANTLAR   : kapsam / sure / limit / tetikte-sifirlama / restart flush.

Cikti: /home/user/Bot2/cd_olcum_sonuc.txt  (stdout'a da yazar)
"""
from __future__ import annotations
import sys, time, json, math
from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
from kronos_cd_varyant import VaryantKronos, VAyar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
KY = 15.85
TABAN = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=190.0, kayma_bp=KY)

t0 = time.time()
KOLLAR = canli_kollar(SRC)
GUN = None   # veri suresi, asagida doldurulur


def _span_gun(kollar):
    b = min(k.besleme.zaman(0) for k in kollar)
    s = max(k.besleme.zaman(k.besleme.n - 1) for k in kollar)
    return (s - b).total_seconds() / 86400.0, b, s


GUN, T_BAS, T_SON = _span_gun(KOLLAR)


def imza(isl):
    return [(t.kol, t.coin, t.giris_ts.value, t.cikis_ts.value, round(t.R, 9))
            for t in isl]


def ll_ciftleri(isl, kapsam="kol_coin"):
    """Bitisik KAYIP-KAYIP cifti sayisi = ratchet semantiginde TETIKLEME sayisi
    (limit=2, tetikte sifirlama YOK).  veri_sonu islemleri motorun streak
    mantigina hic girmedigi icin haric tutulur."""
    ser = defaultdict(list)
    for t in sorted(isl, key=lambda x: x.cikis_ts.value):
        if t.neden == "veri_sonu":
            continue
        a = {"kol_coin": f"{t.kol}:{t.coin}", "kol": t.kol,
             "coin": t.coin, "genel": "G"}[kapsam]
        ser[a].append(1 if t.pnl < 0 else 0)
    n = 0
    for a, v in ser.items():
        for x in range(1, len(v)):
            if v[x] == 1 and v[x - 1] == 1:
                n += 1
    return n, {a: len(v) for a, v in ser.items()}


def olc(isl):
    R = np.array([t.R for t in isl]); pnl = np.array([t.pnl for t in isl])
    return dict(n=len(isl), kar=float(pnl.sum()), ortR=float(R.mean()),
                wr=float((R > 0).mean() * 100), gunluk=len(isl) / GUN)


def yaz(f, s=""):
    print(s, flush=True)
    f.write(s + "\n"); f.flush()


OUT = open("/home/user/Bot2/cd_olcum_sonuc.txt", "w")
yaz(OUT, "=" * 108)
yaz(OUT, "COOLDOWN CELISKISI — KRONOS olcumu")
yaz(OUT, f"veri: {T_BAS} -> {T_SON}  = {GUN:.1f} gun · {len(KOLLAR)} kol")
yaz(OUT, f"CANLI referans: 124 islem / 85 gun = 1.46/gun · 2 cooldown tetikleme (%1.6)")
yaz(OUT, "=" * 108)


# ══════════════════ A) DENKLIK ══════════════════
yaz(OUT, "\n### A) DENKLIK — VaryantKronos, kronos.Kronos ile ayni mi?")
for ad, ek in [("cooldown YOK", dict(ayni_bar_giris=True)),
               ("cooldown 2/240dk", dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240))]:
    a1 = Kronos(KOLLAR, Ayar(**TABAN, **ek)).kos()
    m2 = VaryantKronos(KOLLAR, VAyar(**TABAN, **ek)); a2 = m2.kos()
    esit = imza(a1) == imza(a2)
    yaz(OUT, f"  {ad:<22s} kronos n={len(a1):<5d} varyant n={len(a2):<5d} BIREBIR AYNI: {esit}")
    if not esit:
        yaz(OUT, "  ⛔ VARYANT MOTOR DENK DEGIL — asagidaki tum varyant sonuclari GECERSIZ")
        OUT.close(); sys.exit(2)


# ══════════════════ B) TETIKLEME vs ENGEL ══════════════════
yaz(OUT, "\n### B) TETIKLEME vs ENGEL (canlinin journalctl'i TETIKLEME sayar)")
m0 = VaryantKronos(KOLLAR, VAyar(**TABAN, ayni_bar_giris=True))
i0 = m0.kos()
mc = VaryantKronos(KOLLAR, VAyar(**TABAN, ayni_bar_giris=True,
                                 ardisik_zarar_limiti=2, cooldown_dk=240))
ic = mc.kos()
b0, k0 = olc(i0), m0.sayac
bc, kc = olc(ic), mc.sayac
ll0, dag0 = ll_ciftleri(i0)
yaz(OUT, f"  cooldown YOK      : n={b0['n']:<5d} gunluk={b0['gunluk']:.2f} sayac={k0}")
yaz(OUT, f"  cooldown 2/240dk  : n={bc['n']:<5d} gunluk={bc['gunluk']:.2f} sayac={kc}")
yaz(OUT, f"  → KRONOS TETIKLEME = {kc['cd_tetik']}  ·  ENGEL(sinyal) = {kc['cd_engel']}")
yaz(OUT, f"  → tetikleme/islem = {kc['cd_tetik']}/{bc['n']} = %{kc['cd_tetik']/max(bc['n'],1)*100:.1f}"
         f"   (CANLI: 2/124 = %1.6)")
yaz(OUT, f"  → cooldown YOK kosusunda bitisik LL cifti (=beklenen tetikleme) = {ll0}")

# engellerin kol dagilimi
eng_kol = Counter(a.split(":")[0] for _ts, a in mc.engeller)
tet_kol = Counter(a.split(":")[0] for _ts, a, _s in mc.tetikler)
yaz(OUT, f"  ENGEL kol dagilimi   : {dict(eng_kol)}")
yaz(OUT, f"  TETIK kol dagilimi   : {dict(tet_kol)}")
# kol bazli islem sayisi
for etiket, isl in (("cooldownSUZ", i0), ("cooldownLU", ic)):
    c = Counter(t.kol for t in isl)
    yaz(OUT, f"  islem/kol {etiket:<12s}: {dict(c)}")


# ══════════════════ C) ANAHTAR YOGUNLUGU ══════════════════
yaz(OUT, "\n### C) ANAHTAR YOGUNLUGU")
yaz(OUT, f"  KRONOS aktif anahtar sayisi = {len(dag0)} · toplam islem = {sum(dag0.values())}")
yaz(OUT, f"  anahtar basina islem: " +
         ", ".join(f"{a}={n}" for a, n in sorted(dag0.items(), key=lambda x: -x[1])))
vals = np.array(sorted(dag0.values()))
yaz(OUT, f"  ort={vals.mean():.1f} medyan={np.median(vals):.0f} min={vals.min()} max={vals.max()}")

# iid Bernoulli modeli: tetikleme ~ (n_k - 1) * q^2
q0 = float(np.mean([1 if t.pnl < 0 else 0 for t in i0 if t.neden != "veri_sonu"]))
bekl = sum(max(n - 1, 0) for n in dag0.values()) * q0 ** 2
yaz(OUT, f"  KRONOS kayip orani q={q0:.3f} · iid model beklenen tetikleme "
         f"= Σ(n_k−1)·q² = {bekl:.1f}  · GERCEK {ll0}")

# CANLI ayni formulle
yaz(OUT, "\n  --- CANLI'ya ayni formul (7 kol, kol bazli n ve WR verilen) ---")
CANLI = [("donchian", 56, 0.411), ("orb", 21, 0.238), ("squeeze", 19, 0.263),
         ("mean_rev", 14, 0.571), ("fvg", 10, 0.300), ("asia_bo", 4, 0.500),
         ("sr_breakout", 1, 0.0)]
N_can = sum(n for _a, n, _w in CANLI)
q_can = sum(n * (1 - w) for _a, n, w in CANLI) / N_can
yaz(OUT, f"  canli N={N_can} · agirlikli kayip orani q={q_can:.3f}")
yaz(OUT, f"  {'K (aktif anahtar)':<22s} {'Σ(n_k−1)':>10s} {'beklenen tetik':>16s}")
for K in (7, 12, 20, 30, 40, 50, 60, 70, 84):
    if K > N_can: continue
    yaz(OUT, f"  {K:<22d} {N_can-K:>10d} {(N_can-K)*q_can**2:>16.1f}")
yaz(OUT, "  (K = en az 1 islem gormus (kol:coin) anahtari; Σ(n_k−1)=N−K)")
yaz(OUT, "  → CANLI GOZLENEN TETIKLEME = 2.  Hangi K bunu verir?")
K_gerek = N_can - 2 / q_can ** 2
yaz(OUT, f"     2 = (N−K)·q²  →  K = {K_gerek:.1f}  (yani ~{N_can-K_gerek:.0f} kol:coin ciftinde"
         f" 2+ islem, kalan hepsi TEK islem)")


# ══════════════════ D) VARYANTLAR ══════════════════
yaz(OUT, "\n### D) VARYANTLAR — hangisi canlinin 1.46/gun'une ve %1.6 tetiklemesine yakin?")
VAR = [
    ("cooldown YOK (taban)",                 dict()),
    ("2 / 240dk · kol:coin  [KRONOS hali]",  dict(ardisik_zarar_limiti=2, cooldown_dk=240)),
    ("2 / 240dk · kol:coin · tetikte SIFIRLA", dict(ardisik_zarar_limiti=2, cooldown_dk=240, sifirla_tetikte=True)),
    ("2 / 240dk · KOL bazli",                dict(ardisik_zarar_limiti=2, cooldown_dk=240, anahtar_kapsam="kol")),
    ("2 / 240dk · COIN bazli",               dict(ardisik_zarar_limiti=2, cooldown_dk=240, anahtar_kapsam="coin")),
    ("2 / 60dk  · kol:coin",                 dict(ardisik_zarar_limiti=2, cooldown_dk=60)),
    ("2 / 30dk  · kol:coin",                 dict(ardisik_zarar_limiti=2, cooldown_dk=30)),
    ("3 / 240dk · kol:coin",                 dict(ardisik_zarar_limiti=3, cooldown_dk=240)),
    ("2 / 240dk + 7 gunde restart flush",    dict(ardisik_zarar_limiti=2, cooldown_dk=240, yeniden_baslat_gun=7)),
    ("2 / 240dk + 2 gunde restart flush",    dict(ardisik_zarar_limiti=2, cooldown_dk=240, yeniden_baslat_gun=2)),
    ("2 / 240dk + 1 gunde restart flush",    dict(ardisik_zarar_limiti=2, cooldown_dk=240, yeniden_baslat_gun=1)),
]
yaz(OUT, f"  {'varyant':<42s} {'n':>5s} {'/gun':>6s} {'tetik':>6s} {'%tet':>6s} {'engel':>6s} {'$':>9s} {'ortR':>8s}")
SON = {}
for ad, ek in VAR:
    tt = time.time()
    m = VaryantKronos(KOLLAR, VAyar(**TABAN, ayni_bar_giris=True, **ek))
    isl = m.kos()
    b = olc(isl); s = m.sayac
    SON[ad] = dict(**b, **s)
    yaz(OUT, f"  {ad:<42s} {b['n']:>5d} {b['gunluk']:>6.2f} {s['cd_tetik']:>6d} "
             f"{s['cd_tetik']/max(b['n'],1)*100:>5.1f}% {s['cd_engel']:>6d} "
             f"{b['kar']:>+9.2f} {b['ortR']:>+8.4f}   ({time.time()-tt:.0f}sn)")

yaz(OUT, "\n" + "=" * 108)
yaz(OUT, f"toplam sure {time.time()-t0:.0f} sn")
json.dump(SON, open("/home/user/Bot2/cd_olcum_sonuc.json", "w"), indent=1)
OUT.close()
