"""
ek_olc.py — ANKOR DIŞI DÖRT KOL (orb/asia_bo/fvg/sr_breakout) ÖLÇÜMÜ.

Soru: bu dört kolu KAPATMAK para kazandırır mı? Kazandırıyorsa koltuk
serbestleşmesinden mi, doğrudan zarar kesilmesinden mi?

Ölçek: CANLI (riskf 0.028, cap 1.50, bal0 190, kayma 15.85bp, fee 1bp/taraf).
Kapılar üç kademe (kronos kapı-kapı tablosuyla aynı):
  K0 ankor eşleniği : maxpos=7, ayni_bar_giris=False
  K1 +aynı bar      : ayni_bar_giris=True
  K3 CANLI TAM      : +cooldown 2/240dk +günlük fren %35
DOĞRULAMA: ANKOR@K0 → 1583 işlem / +$1314.11 / ortR +0.1736 çıkmalı.

Kullanım: py ek_olc.py local
"""
import sys, math, json
import numpy as np, pandas as pd

from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
import kollar_ek as EK

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
BOL = pd.Timestamp("2025-01-01", tz="UTC")
ANKOR_ADLAR = {"donchian", "squeeze", "bb"}
EK_ADLAR = ["orb", "asia_bo", "fvg", "sr_breakout"]

TABAN = dict(riskf=0.028, cap=1.50, bal0=190.0, kayma_bp=15.85, fee=0.0001, maxpos=7)
KAPI = {
    "K0 ankor eşleniği": dict(ayni_bar_giris=False),
    "K1 +aynı bar":      dict(ayni_bar_giris=True),
    "K3 CANLI TAM":      dict(ayni_bar_giris=True, ardisik_zarar_limiti=2,
                              cooldown_dk=240, gunluk_zarar_pct=0.35),
}


# ── GERÇEK CANLI RİSK YÜZDELERİ (execution.py:507-530 × RISK_SCALE 1.4) ──
# KRONOS Ayar'ında tek riskf var; canlıda kol başına farklı. eff=min(riskf, cap*sl_pct)
# olduğu için çoğu işlemde CAP bağlar ve fark yok — ama orb %7 (hafta sonu %8) ve
# asia %4.2 ile ankorun %2.8'inden büyük. Bu yüzden $ AYRICA gerçek riskle yeniden ölçülür.
RISK_KOL = {"orb": 0.07, "asia_bo": 0.042, "fvg": 0.028, "sr_breakout": 0.028,
            "donchian": 0.028, "squeeze": 0.028, "bb": 0.028}


def gercek_usd(ts):
    """Her işlemin $'ını KENDİ kolunun canlı risk yüzdesiyle yeniden hesapla."""
    tot = 0.0
    for t in ts:
        rf = RISK_KOL.get(t.kol, 0.028)
        if t.kol == "orb" and t.giris_ts.weekday() >= 5:
            rf = min(rf * 1.5, 0.08)          # ORB_WEEKEND_MULT
        tot += t.R * min(rf, TABAN["cap"] * t.sl_pct) * TABAN["bal0"]
    return tot


def cap_orani(ts):
    if not ts: return 0.0
    return 100.0 * np.mean([TABAN["cap"] * t.sl_pct <= TABAN["riskf"] for t in ts])


# ────────────────────────── istatistik ──────────────────────────
def dd_ay(ts):
    """Bileşik equity eğrisinden maxDD% ve en kötü ay%."""
    if not ts:
        return 0.0, 0.0
    ss = sorted(ts, key=lambda t: t.cikis_ts.value)
    eq, tepe, dd = 1.0, 1.0, 0.0
    aylik = {}
    for t in ss:
        onc = eq
        eq *= (1.0 + t.R * t.eff)
        tepe = max(tepe, eq)
        dd = max(dd, (tepe - eq) / tepe)
        a = (t.cikis_ts.year, t.cikis_ts.month)
        p = aylik.setdefault(a, [onc, eq])
        p[1] = eq
    ka = min(((s / b - 1.0) * 100 for b, s in aylik.values()), default=0.0)
    return dd * 100, ka


def ozet(ts, etiket=""):
    n = len(ts)
    if n == 0:
        return dict(etiket=etiket, n=0, usd=0.0, gusd=0.0, capb=0.0, ortR=0.0, se=0.0, z=0.0, wr=0.0, dd=0.0, kotuay=0.0)
    R = np.array([t.R for t in ts])
    usd = sum(t.pnl for t in ts)
    se = R.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
    d, ka = dd_ay(ts)
    return dict(etiket=etiket, n=n, usd=usd, gusd=gercek_usd(ts), capb=cap_orani(ts),
                ortR=R.mean(), se=se,
                z=(R.mean() / se if se and np.isfinite(se) and se > 0 else float("nan")),
                wr=100.0 * (R > 0).mean(), dd=d, kotuay=ka)


def yaz(o, ek=""):
    print(f"  {o['etiket']:<34s} n={o['n']:5d}  ${o['usd']:+9.2f}  ortR {o['ortR']:+.4f}"
          f"  SE {o['se']:.4f}  z {o['z']:+5.2f}  WR %{o['wr']:4.1f}"
          f"  bDD %{o['dd']:5.2f}  kötüay {o['kotuay']:+6.2f}"
          f"  [gerçek risk ${o['gusd']:+9.2f}, cap-bağlı %{o['capb']:.0f}] {ek}")


def yil_yil(ts, etiket):
    yl = {}
    for t in ts:
        yl.setdefault(t.cikis_ts.year, []).append(t)
    print(f"  {etiket} yıl-yıl:")
    for y in sorted(yl):
        g = yl[y]
        R = np.array([t.R for t in g])
        print(f"     {y}  n={len(g):5d}  ${sum(t.pnl for t in g):+9.2f}  ortR {R.mean():+.4f}")


def tr_te(ts, etiket):
    tr = [t for t in ts if t.giris_ts < BOL]
    te = [t for t in ts if t.giris_ts >= BOL]
    for ad, g in (("TRAIN <2025", tr), ("TEST >=2025", te)):
        if not g:
            print(f"     {ad}: n=0"); continue
        R = np.array([t.R for t in g])
        se = R.std(ddof=1) / math.sqrt(len(g)) if len(g) > 1 else float("nan")
        print(f"     {ad}: n={len(g):5d}  ${sum(t.pnl for t in g):+9.2f}  ortR {R.mean():+.4f}"
              f"  z {R.mean()/se if se>0 else float('nan'):+5.2f}")


def ayar(kapi):
    a = dict(TABAN); a.update(KAPI[kapi]); return Ayar(**a)


# ────────────────────────── kollar ──────────────────────────
print("kollar kuruluyor…", flush=True)
ANK = canli_kollar(SRC)
EKK = {ad: EK.ek_kollar([ad], None, SRC) for ad in EK_ADLAR}
EK_HEPSI = [k for ad in EK_ADLAR for k in EKK[ad]]
print(f"  ankor {len(ANK)} kol · ek {len(EK_HEPSI)} kol (4 aile × 12 coin)", flush=True)
for ad in EK_ADLAR:
    tot = sum(sum(1 for x in k._sig if x is not None) for k in EKK[ad])
    dus = {}
    for k in EKK[ad]:
        for kk, vv in k.dusen.items(): dus[kk] = dus.get(kk, 0) + vv
    print(f"    {ad:12s} ham sinyal {tot:6d}  elenen(geometri) {dus}", flush=True)


# ═══════════ 4(a) HER KOL TEK BAŞINA (kısıtsız koltuk, kendi slotu) ═══════════
print(f"\n{'='*104}\n4(a) HER KOL TEK BAŞINA — kısıtsız koltuk (maxpos=∞), canlı ölçek + 15.85bp")
print(f"{'='*104}")
serbest = dict(TABAN); serbest.update(maxpos=10**9, ayni_bar_giris=False)
tekil = {}
for ad in EK_ADLAR:
    ts = Kronos(EKK[ad], Ayar(**serbest)).kos()
    tekil[ad] = ts
    yaz(ozet(ts, ad))
ts_ank = Kronos(ANK, Ayar(**serbest)).kos()
yaz(ozet(ts_ank, "ANKOR (donch+sqz+bb)"), "← kıyas")
print()
for ad in EK_ADLAR:
    yil_yil(tekil[ad], ad); tr_te(tekil[ad], ad)
print()
yil_yil(ts_ank, "ANKOR"); tr_te(ts_ank, "ANKOR")


# ═══════════ 4(b)/(c) ORTAK 7 KOLTUK — ankor vs ankor+4 ═══════════
print(f"\n{'='*104}\n4(b)/(c) ORTAK 7 KOLTUK — ankor TEK BAŞINA  vs  ankor + dört kol")
print(f"{'='*104}")
SONUC = {}
for kapi in KAPI:
    ay = ayar(kapi)
    sadece = Kronos(ANK, ay).kos()
    hepsi = Kronos(ANK + EK_HEPSI, ay).kos()
    ank_h = [t for t in hepsi if t.kol in ANKOR_ADLAR]
    ek_h = [t for t in hepsi if t.kol not in ANKOR_ADLAR]

    a_key = {(t.kol, t.coin, t.giris_ts.value): t for t in sadece}
    b_key = {(t.kol, t.coin, t.giris_ts.value): t for t in ank_h}
    kayip = [a_key[k] for k in set(a_key) - set(b_key)]
    yeni = [b_key[k] for k in set(b_key) - set(a_key)]

    o1 = ozet(sadece, "ANKOR tek başına")
    o2 = ozet(hepsi, "ANKOR + dört kol (toplam)")
    print(f"\n── {kapi} ──")
    yaz(o1); yaz(o2)
    yaz(ozet(ank_h, "  ↳ içindeki ankor kolları"))
    yaz(ozet(ek_h, "  ↳ içindeki dört kol"))
    print(f"     ANKOR KİTABI: kaybedilen {len(kayip)} işlem (${sum(t.pnl for t in kayip):+.2f} "
          f"ankor koşusunda) · yeni açılan {len(yeni)} işlem")
    d_usd = o2["usd"] - o1["usd"]
    d_g = o2["gusd"] - o1["gusd"]
    print(f"     Δ TOPLAM $ (dört kol AÇIK − KAPALI) = {d_usd:+.2f}   → KAPATMANIN kazancı = {-d_usd:+.2f}$")
    print(f"     Δ TOPLAM $ GERÇEK RİSKLE            = {d_g:+.2f}   → KAPATMANIN kazancı = {-d_g:+.2f}$")
    print(f"     Δ bileşikDD {o2['dd']-o1['dd']:+.2f} puan · Δ en kötü ay {o2['kotuay']-o1['kotuay']:+.2f} puan")
    SONUC[kapi] = dict(sadece=o1, hepsi=o2, ek=ozet(ek_h, "ek"),
                       ankor_ici=ozet(ank_h, "ankor_ici"),
                       kayip_n=len(kayip), kayip_usd=sum(t.pnl for t in kayip),
                       yeni_n=len(yeni), d_usd=d_usd)
    # yıl-yıl fark
    yl = {}
    for t in sadece: yl.setdefault(t.cikis_ts.year, [0.0, 0.0])[0] += t.pnl
    for t in hepsi:  yl.setdefault(t.cikis_ts.year, [0.0, 0.0])[1] += t.pnl
    print("     yıl-yıl $:  " + " | ".join(
        f"{y}: kapalı {v[0]:+7.1f} açık {v[1]:+7.1f} Δ {v[1]-v[0]:+7.1f}" for y, v in sorted(yl.items())))

# ═══════════ tek tek: hangi kol ne kadar zarar veriyor (K3, canlı tam) ═══════════
print(f"\n{'='*104}\nTEK TEK EKLEME — CANLI TAM kapılarda (K3), her kol AYRI AYRI ankora eklenir")
print(f"{'='*104}")
ay3 = ayar("K3 CANLI TAM")
taban3 = Kronos(ANK, ay3).kos()
o_t = ozet(taban3, "ANKOR tek başına")
yaz(o_t)
for ad in EK_ADLAR:
    ts = Kronos(ANK + EKK[ad], ay3).kos()
    o = ozet(ts, f"ankor + {ad}")
    ekp = [t for t in ts if t.kol == ad]
    ankp = [t for t in ts if t.kol in ANKOR_ADLAR]
    a_key = {(t.kol, t.coin, t.giris_ts.value) for t in taban3}
    b_key = {(t.kol, t.coin, t.giris_ts.value) for t in ankp}
    kayip = len(a_key - b_key)
    dogrudan = sum(t.pnl for t in ekp)
    koltuk = (o["usd"] - o_t["usd"]) - dogrudan
    yaz(o, f"| kolun kendi $ {dogrudan:+8.2f} · koltuk etkisi {koltuk:+8.2f} · ankor kaybı {kayip} işlem")

print(f"\n{'='*104}\nÖZET (Δ$ = dört kol AÇIK − KAPALI; NEGATİF ise kapatmak kazandırır)")
for kapi, v in SONUC.items():
    print(f"  {kapi:<20s} Δ$ {v['d_usd']:+9.2f}  (dört kolun kendi $ {v['ek']['usd']:+8.2f}, "
          f"ankor kitabı kaybı {v['kayip_n']} işlem / {v['kayip_usd']:+8.2f}$)")
print(f"{'='*104}\n")
