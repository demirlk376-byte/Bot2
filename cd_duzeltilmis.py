"""
cd_duzeltilmis.py — KRONOS kapi merdiveninin ZAMAN BIRIMI DUZELTILMIS hali.

BULUNAN HATA (kronos/motor.py:127):
    simdi = pd.Timestamp(ts, tz="UTC")        # ts = _idx.asi8[i]
pandas 3.0'da DatetimeIndex birimi MIKROSANIYE ('us'), ama pd.Timestamp(int)
degeri NANOSANIYE sayar.  Sonuc: motorun zaman ekseni 1000x SIKISIYOR.
  3.3 yillik veri  -> motorda 1.2 gun
  240 dk cooldown  -> GERCEKTE 166.7 gun
  60  dk cooldown  -> GERCEKTE 41.7 gun
  gun = simdi.date() -> tum backtest 2 "gun"  => gunluk zarar freni aslinda
                        TUM TARIH freni

Bu dosya AYNI motoru iki modda kosar (kronos/ ALTINA DOKUNULMADI):
  "bozuk" = motor.py'nin bugunku davranisi (A/B kaniti)
  "auto"  = DOGRU zaman
ve canli merdiveni yeniden uretir.

Kullanim: py cd_duzeltilmis.py local
"""
from __future__ import annotations
import sys, time, json
from collections import Counter
import numpy as np, pandas as pd

from kronos.kollar import canli_kollar
from kronos_cd_varyant import VaryantKronos, VAyar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
TABAN = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=190.0, kayma_bp=15.85)

K = canli_kollar(SRC)
GUN = (max(k.besleme.zaman(k.besleme.n - 1) for k in K)
       - min(k.besleme.zaman(0) for k in K)).total_seconds() / 86400


def olc(isl):
    R = np.array([t.R for t in isl]); pnl = np.array([t.pnl for t in isl])
    ex = pd.to_datetime([t.cikis_ts for t in isl])
    bil = np.concatenate([[1.0], np.cumprod(1 + R * np.array([t.eff for t in isl]))])
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / 190.0 * 100
    return dict(n=len(isl), gunluk=len(isl) / GUN, kar=float(pnl.sum()),
                ortR=float(R.mean()), wr=float((R > 0).mean() * 100),
                bdd=float(((np.maximum.accumulate(bil) - bil) / np.maximum.accumulate(bil)).max() * 100),
                kotu=float(ay.min()))


F = open("/home/user/Bot2/cd_duzeltilmis_sonuc.txt", "w")
def yaz(s=""):
    print(s, flush=True); F.write(s + "\n"); F.flush()


yaz("=" * 118)
yaz("KRONOS KAPI MERDIVENI — ZAMAN BIRIMI DUZELTILMIS  (kronos/ dokunulmadi)")
yaz(f"veri {GUN:.0f} gun · CANLI referans: gunde 1.46 islem · 60 gunde 2 cooldown kaydi")
yaz("=" * 118)
hdr = (f"  {'basamak':<48s} {'n':>5s} {'/gun':>6s} {'tetik':>6s} {'engel':>6s} "
       f"{'$':>10s} {'ortR':>8s} {'WR':>6s} {'bilDD':>7s} {'kotuay':>8s} {'sn':>5s}")

SIRA = [
    # (etiket, zaman_birimi, ek ayarlar)
    ("0) ANKOR eslenigi (kapi yok)",              "auto",  dict(ayni_bar_giris=False)),
    ("1) + ayni bar girisi",                      "auto",  dict(ayni_bar_giris=True)),
    ("2-BOZUK) + cooldown 2/240dk  [motor.py]",   "bozuk", dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240)),
    ("2-DOGRU) + cooldown 2/240dk",               "auto",  dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240)),
    ("3-BOZUK) + gunluk fren %35   [motor.py]",   "bozuk", dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35)),
    ("3-DOGRU) + gunluk fren %35 = TAM CANLI",    "auto",  dict(ayni_bar_giris=True, ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35)),
]
yaz("\n### MERDIVEN")
yaz(hdr)
SON = {}
for ad, bir, ek in SIRA:
    t = time.time()
    m = VaryantKronos(K, VAyar(**TABAN, zaman_birimi=bir, **ek)); isl = m.kos()
    b = olc(isl); s = m.sayac; SON[ad] = dict(**b, **s)
    yaz(f"  {ad:<48s} {b['n']:>5d} {b['gunluk']:>6.2f} {s['cd_tetik']:>6d} {s['cd_engel']:>6d} "
        f"{b['kar']:>+10.2f} {b['ortR']:>+8.4f} %{b['wr']:>4.1f} %{b['bdd']:>6.2f} %{b['kotu']:>7.2f} "
        f"{time.time()-t:>5.0f}")

yaz("\n### DUZELTILMIS COOLDOWN VARYANTLARI (hepsi zaman_birimi=auto)")
yaz(hdr)
VAR = [
    ("2 / 240dk · kol:coin  [CANLI AYAR]", dict(ardisik_zarar_limiti=2, cooldown_dk=240)),
    ("2 / 240dk · KOL bazli",              dict(ardisik_zarar_limiti=2, cooldown_dk=240, anahtar_kapsam="kol")),
    ("2 / 240dk · tetikte SIFIRLA",        dict(ardisik_zarar_limiti=2, cooldown_dk=240, sifirla_tetikte=True)),
    ("2 / 240dk + 3 gunde restart flush",  dict(ardisik_zarar_limiti=2, cooldown_dk=240, yeniden_baslat_gun=3)),
    ("2 / 1440dk (24 saat) · kol:coin",    dict(ardisik_zarar_limiti=2, cooldown_dk=1440)),
]
for ad, ek in VAR:
    t = time.time()
    m = VaryantKronos(K, VAyar(**TABAN, ayni_bar_giris=True, zaman_birimi="auto", **ek))
    isl = m.kos(); b = olc(isl); s = m.sayac; SON[ad] = dict(**b, **s)
    yaz(f"  {ad:<48s} {b['n']:>5d} {b['gunluk']:>6.2f} {s['cd_tetik']:>6d} {s['cd_engel']:>6d} "
        f"{b['kar']:>+10.2f} {b['ortR']:>+8.4f} %{b['wr']:>4.1f} %{b['bdd']:>6.2f} %{b['kotu']:>7.2f} "
        f"{time.time()-t:>5.0f}")

json.dump(SON, open("/home/user/Bot2/cd_duzeltilmis_sonuc.json", "w"), indent=1)
yaz("\n" + "=" * 118)
F.close()
