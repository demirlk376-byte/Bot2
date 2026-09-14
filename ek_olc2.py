"""
ek_olc2.py — ASIL ÖLÇÜM: dört ankor-dışı kolu KAPATMAK para kazandırır mı?

İKİ DOLUM MODELİ (ikisi de aynı motorda, aynı 7 koltukta):
  [K] kapanış-girişi : giriş = sinyal barının kapanışı, taker/taker + 15.85bp kayma.
      sr_breakout için CANLI GERÇEĞİ (force_market=True). orb/asia/fvg için ALEYHTE.
  [L] limit-girişi   : emir SEVİYEDE bekler; i+1 barı seviyeye değmezse İŞLEM YOK
      (canlıda piyasa yedeği yok). Giriş = seviye, maker → giriş ücreti 0, kayma 0.
      orb/asia/fvg için CANLI GERÇEĞİ. (İyimser yan: canlı 600 sn bekler, burada 1 saat.)

MALİYET MUHASEBESİ MOTORDAN BAĞIMSIZ YAPILIR (kesin):
  R_ham  = R_motor + (2·fee + kayma_motor)/sl_pct        ← motorun düştüğünü geri al
  R_doğru= R_ham − (1·fee)/sl_pct                 (_L kolları: maker giriş, kayma yok)
         = R_ham − (2·fee + 15.85bp)/sl_pct       (ankor + sr: taker×2 + kayma)
  $      = R_doğru × min(risk%_kol, 1.50×sl_pct) × 190      risk%: execution.py:507-530

DOĞRULAMA: ANKOR@K0 → 1583 işlem / +$1314.11 / ortR +0.1736 / bDD %52.23 / kötüay −32.62

Kullanım: py ek_olc2.py local
"""
import sys, math
import numpy as np, pandas as pd

from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar
import kollar_ek as EK

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
BOL = pd.Timestamp("2025-01-01", tz="UTC")
ANKOR = {"donchian", "squeeze", "bb"}
ADLAR = ["orb", "asia_bo", "fvg", "sr_breakout"]
FEE, KAYMA, CAP, BAL0, RISKF = 0.0001, 15.85 / 1e4, 1.50, 190.0, 0.028
RISK_KOL = {"orb": 0.07, "asia_bo": 0.042, "fvg": 0.028, "sr_breakout": 0.028,
            "donchian": 0.028, "squeeze": 0.028, "bb": 0.028}


def defter(islemler, kayma_motor_bp):
    """Motor çıktısını KESİN maliyet muhasebesiyle deftere çevir.
    kayma_motor_bp: motorun Ayar.kayma_bp değeri (BAZ PUAN). İçeride /1e4 yapılır."""
    kayma_motor = kayma_motor_bp / 1e4
    out = []
    for t in islemler:
        R_ham = t.R + (2 * FEE + kayma_motor) / t.sl_pct
        if t.kol.endswith("_L"):
            R = R_ham - FEE / t.sl_pct
        else:
            R = R_ham - (2 * FEE + KAYMA) / t.sl_pct
        ad = t.kol[:-2] if t.kol.endswith("_L") else t.kol
        rf = RISK_KOL.get(ad, RISKF)
        if ad == "orb" and t.giris_ts.weekday() >= 5:
            rf = min(rf * 1.5, 0.08)
        eff = min(rf, CAP * t.sl_pct)
        out.append(dict(kol=ad, coin=t.coin, gts=t.giris_ts, cts=t.cikis_ts,
                        R=R, eff=eff, pnl=R * eff * BAL0, neden=t.neden))
    return out


def ozet(D, etiket):
    n = len(D)
    if n == 0:
        return dict(etiket=etiket, n=0, usd=0.0, ortR=0.0, se=0.0, z=0.0, wr=0.0, dd=0.0, ka=0.0)
    R = np.array([d["R"] for d in D]); usd = sum(d["pnl"] for d in D)
    se = R.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
    ss = sorted(D, key=lambda d: d["cts"].value)
    eq = tepe = 1.0; dd = 0.0; aylik = {}
    for d in ss:
        onc = eq; eq *= (1.0 + d["R"] * d["eff"]); tepe = max(tepe, eq)
        dd = max(dd, (tepe - eq) / tepe)
        p = aylik.setdefault((d["cts"].year, d["cts"].month), [onc, eq]); p[1] = eq
    ka = min(((s / b - 1) * 100 for b, s in aylik.values()), default=0.0)
    return dict(etiket=etiket, n=n, usd=usd, ortR=R.mean(), se=se,
                z=R.mean() / se if se > 0 else float("nan"),
                wr=100 * (R > 0).mean(), dd=dd * 100, ka=ka)


def yaz(o, ek=""):
    print(f"  {o['etiket']:<32s} n={o['n']:5d}  ${o['usd']:+9.2f}  ortR {o['ortR']:+.4f}"
          f"  z {o['z']:+6.2f}  WR %{o['wr']:4.1f}  bDD %{o['dd']:5.2f}  kötüay {o['ka']:+6.2f} {ek}")


print("kollar kuruluyor…", flush=True)
ANK = canli_kollar(SRC)
KAP = {ad: EK.ek_kollar([ad], None, SRC) for ad in ADLAR}
LIM = {ad: [EK.limit_varyant(k) for k in KAP[ad]] for ad in ADLAR}
KAP_H = [k for ad in ADLAR for k in KAP[ad]]
# sr_breakout canlida force_market=True -> LIMIT MODELI ONA UYGULANMAZ.
# [L] portfoyunde sr, KAPANIS kolu olarak kalir (canli gercegi).
LIM_H = [k for ad in ADLAR for k in (LIM[ad] if ad != "sr_breakout" else KAP[ad])]
print(f"  ankor {len(ANK)} · kapanış-kolları {len(KAP_H)} · limit-kolları {len(LIM_H)}", flush=True)
for ad in ADLAR:
    s = sum(1 for k in KAP[ad] for x in k._sig if x is not None)
    dm = sum(k.dusen["dolmadi"] for k in LIM[ad])
    ek_not = "   [force_market - limit modeli UYGULANMAZ]" if ad == "sr_breakout" else ""
    ck = sum(k.dusen["cakisma"] for k in LIM[ad])
    gm = sum(k.dusen["geometri"] for k in LIM[ad])
    print(f"    {ad:12s} sinyal {s:6d} · limit dolmayan {dm:6d} (%{100*dm/max(s,1):.0f}) "
          f"· çakışma {ck} · geometri {gm}" + ek_not, flush=True)

KAPILAR = [
    ("K0 ankor eşleniği", dict(ayni_bar_giris=False), 15.85),
    ("K1 +aynı bar",      dict(ayni_bar_giris=True), 15.85),
    ("K3a CANLI TAM",     dict(ayni_bar_giris=True, ardisik_zarar_limiti=2,
                               cooldown_dk=240, gunluk_zarar_pct=0.35), 15.85),
    ("K3b CANLI TAM*",    dict(ayni_bar_giris=True, ardisik_zarar_limiti=2,
                               cooldown_dk=240, gunluk_zarar_pct=0.35), 0.0),
]
TABAN = dict(maxpos=7, riskf=RISKF, cap=CAP, bal0=BAL0, fee=FEE)

print(f"\n{'='*112}\n(b)/(c) ORTAK 7 KOLTUK — ankor TEK BAŞINA vs ankor + dört kol")
print("K3a: motor kapıları 15.85bp'lik R ile karar verir (limit kolları için aleyhte)")
print("K3b: motor kapıları kaymasız R ile karar verir (ankor için lehte). İkisi bir ARALIK verir.")
print(f"{'='*112}")

SON = {}
for etiket, kap, kym in KAPILAR:
    ay = Ayar(**TABAN, kayma_bp=kym, **kap)
    d_sadece = defter(Kronos(ANK, ay).kos(), kym)
    print(f"\n══ {etiket} ══")
    o0 = ozet(d_sadece, "ANKOR tek başına (dört kol KAPALI)")
    yaz(o0)
    if etiket.startswith("K0"):
        print(f"     [DOĞRULAMA] beklenen 1583 / +$1314.11 / ortR +0.1736 / bDD %52.23 / kötüay -32.62")
        ok = (o0["n"] == 1583 and abs(o0["usd"] - 1314.11) < 1.0 and abs(o0["ortR"] - 0.1736) < 0.001)
        print(f"     [DOĞRULAMA] {'✓ ANKOR EŞLENİĞİ TUTTU' if ok else '⛔ TUTMADI — muhasebe hatalı'}")
    for mod, kollar in (("K kapanış", KAP_H), ("L limit  ", LIM_H)):
        m = Kronos(ANK + kollar, ay)
        d_all = defter(m.kos(), kym)
        ankor_i = [d for d in d_all if d["kol"] in ANKOR]
        ek_i = [d for d in d_all if d["kol"] not in ANKOR]
        a_k = {(d["kol"], d["coin"], d["gts"].value): d for d in d_sadece}
        b_k = {(d["kol"], d["coin"], d["gts"].value): d for d in ankor_i}
        kayip = [a_k[k] for k in set(a_k) - set(b_k)]
        yeni = len(set(b_k) - set(a_k))
        o = ozet(d_all, f"ANKOR+4 [{mod}]")
        yaz(o)
        yaz(ozet(ankor_i, f"   ↳ ankor kolları [{mod}]"))
        yaz(ozet(ek_i, f"   ↳ dört kol [{mod}]"))
        dus = o["usd"] - o0["usd"]
        dogrudan = sum(d["pnl"] for d in ek_i)
        koltuk = dus - dogrudan
        print(f"     Δ$ = {dus:+8.2f}  →  KAPATMANIN KAZANCI {-dus:+8.2f}$"
              f"   [doğrudan {dogrudan:+8.2f} · koltuk {koltuk:+8.2f}]")
        print(f"     ankor kitabı: kaybedilen {len(kayip)} işlem "
              f"(kapalı koşuda ${sum(d['pnl'] for d in kayip):+.2f}) · yeni açılan {yeni}"
              f" · koltuk engeli {m.sayac['koltuk_engel']} · cd engeli {m.sayac['cd_engel']}"
              f" · gün engeli {m.sayac['gun_engel']}")
        print(f"     Δ bDD {o['dd']-o0['dd']:+.2f} puan · Δ en kötü ay {o['ka']-o0['ka']:+.2f} puan")
        yl = {}
        for d in d_sadece: yl.setdefault(d["cts"].year, [0.0, 0.0])[0] += d["pnl"]
        for d in d_all:    yl.setdefault(d["cts"].year, [0.0, 0.0])[1] += d["pnl"]
        print("     yıl-yıl Δ$: " + " | ".join(
            f"{y} {v[1]-v[0]:+7.1f}" for y, v in sorted(yl.items())))
        SON[(etiket, mod)] = (dus, dogrudan, koltuk, len(kayip), o, o0)

# ── TEK TEK: hangi kol ne kadar ──
print(f"\n{'='*112}\nTEK TEK EKLEME (K1 kapıları) — her kol AYRI AYRI ankora eklenir")
print(f"{'='*112}")
ay1 = Ayar(**TABAN, kayma_bp=15.85, ayni_bar_giris=True)
d0 = defter(Kronos(ANK, ay1).kos(), 15.85)
o0 = ozet(d0, "ANKOR tek başına"); yaz(o0)
for mod, KK in (("K", KAP), ("L", LIM)):
    for ad in ADLAR:
        if mod == "L" and ad == "sr_breakout":
            continue        # sr canlıda force_market → L varyantı yok
        dA = defter(Kronos(ANK + KK[ad], ay1).kos(), 15.85)
        ek_i = [d for d in dA if d["kol"] == ad]
        o = ozet(dA, f"ankor + {ad} [{mod}]")
        dogrudan = sum(d["pnl"] for d in ek_i)
        dus = o["usd"] - o0["usd"]
        yaz(o, f"| kolun kendi ${dogrudan:+8.2f} · koltuk ${dus-dogrudan:+8.2f} · KAPATMA {-dus:+8.2f}$")

print(f"\n{'='*112}\nÖZET — dört kolu KAPATMANIN kazancı ($, 3.3 yıl, sabit $190 taban)")
for (etiket, mod), (dus, dg, kl, ky, o, o0) in SON.items():
    print(f"  {etiket:<20s} [{mod}]  KAPATMA {-dus:+9.2f}$  (doğrudan {-dg:+8.2f} · koltuk {-kl:+8.2f})"
          f"  ankor kaybı {ky} işlem")
print(f"{'='*112}\n")
