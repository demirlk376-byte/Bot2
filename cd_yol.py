"""cd_yol.py — C4 (stop dolum gap) + C5 (bar ici yol) icin MOTOR KOPYASI ile
YENIDEN KOSUM. kronos/motor.py DEGISTIRILMEDI; asagidaki Kronos2 onun birebir
kopyasi + iki anahtar:

  stop_gap=True   : stop tetiklenen barin ACILISI stopun otesindeyse dolum
                    ACILIS fiyatindan olur (gercekci stop-market davranisi).
  iyimser=True    : bir barda hem stop hem hedef gorunuyorsa ONCE HEDEF alinir
                    (KRONOS varsayilani: once STOP = muhafazakar).
  stop_ek_bp      : stop cikislarina ek kayma (bp) — duyarlilik taramasi.

DENKLIK SARTI: uc anahtar da kapaliyken Kronos2, kronos.Kronos ile BIREBIR ayni
islem listesini uretmeli. Kosunun ilk adimi budur; tutmazsa DURUR.
"""
from __future__ import annotations
import sys, os, pickle
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.motor import _funding_R, Islem, k_sig_var
from kronos.kollar import canli_kollar, funding_yukle

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
os.makedirs(SCR, exist_ok=True)
BAL0 = 1000.0
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)


class Kronos2(Kronos):
    """kronos.Kronos.kos()'un BIREBIR kopyasi + stop_gap / iyimser / stop_ek_bp."""

    def __init__(self, kollar, ayar=None, stop_gap=False, iyimser=False, stop_ek_bp=0.0):
        super().__init__(kollar, ayar)
        self.stop_gap = stop_gap; self.iyimser = iyimser; self.stop_ek_bp = stop_ek_bp
        self._op = [k.besleme._d["open"].values for k in self.kollar]

    def kos(self):
        a = self.a
        kayma = a.kayma_bp / 1e4
        ek = self.stop_ek_bp / 1e4
        ol = self._cizelge()
        acik: dict[int, dict] = {}
        engel: dict[int, int] = {}
        seri_zarar: dict[str, int] = {}
        cooldown: dict[str, pd.Timestamp] = {}
        gun_durdu: set = set()
        gun_pnl: dict = {}
        gun_bas: dict = {}
        equity = a.bal0
        islemler: list[Islem] = []
        self.sayac = dict(sinyal=0, cd_engel=0, gun_engel=0, koltuk_engel=0, coin_engel=0, acildi=0)
        self.tani = dict(belirsiz_bar=0, gap_stop=0, gap_R=0.0)

        j, N = 0, len(ol)
        while j < N:
            ts = ol[j][0]; e = j
            while e < N and ol[e][0] == ts: e += 1
            grup = ol[j:e]
            simdi = self.kollar[grup[0][3]].besleme.zaman(grup[0][4])
            gun = simdi.date()
            if gun not in gun_bas: gun_bas[gun] = equity

            # ─── 1) CIKISLAR ───
            cikan = set()
            for _ns, _p, _s, ki, i in grup:
                p = acik.get(ki)
                if p is None or i <= p["i0"]: continue
                k = self.kollar[ki]
                hi, lo, cl = k.besleme.bar(i)
                op = self._op[ki][i]
                ep, neden = None, ""
                if p["yon"] == 1:
                    sl_var, tp_var = (lo <= p["slp"]), (hi >= p["tp"])
                else:
                    sl_var, tp_var = (hi >= p["slp"]), (lo <= p["tp"])
                if sl_var and tp_var: self.tani["belirsiz_bar"] += 1
                gap_sl = (op < p["slp"]) if p["yon"] == 1 else (op > p["slp"])
                if self.stop_gap and gap_sl:
                    # acilista zaten stopun otesinde -> stop-market ACILISTA doldu;
                    # o bardaki hedefe ulasma sansi YOK (iyimser moda da onceliklidir)
                    self.tani["gap_stop"] += 1
                    self.tani["gap_R"] += p["yon"] * (op - p["slp"]) / p["sld"]
                    ep, neden = op, "sl"
                elif self.iyimser:
                    if tp_var: ep, neden = p["tp"], "tp"
                    elif sl_var: ep, neden = p["slp"], "sl"
                else:
                    if sl_var: ep, neden = p["slp"], "sl"
                    elif tp_var: ep, neden = p["tp"], "tp"
                if ep is None and i >= p["i0"] + p["mh"]: ep, neden = cl, "sure"
                if ep is None: continue

                R = p["yon"] * (ep - p["e"]) / p["sld"] - 2 * a.fee * p["e"] / p["sld"]
                if kayma: R -= kayma / p["sl_pct"]
                if ek and neden == "sl": R -= ek / p["sl_pct"]
                if a.funding:
                    R -= _funding_R(a.funding.get(k.coin), k.besleme.zaman(p["i0"]),
                                    k.besleme.zaman(i), p["yon"], p["sl_pct"])
                eff = min(a.riskf, a.cap * p["sl_pct"])
                taban = equity if a.bilesik_boyut else a.bal0
                pnl = R * eff * taban
                equity += pnl
                gun_pnl[gun] = gun_pnl.get(gun, 0.0) + pnl
                islemler.append(Islem(k.ad, k.coin, p["yon"], k.besleme.zaman(p["i0"]),
                                      k.besleme.zaman(i), p["e"], ep, p["sld"], R,
                                      p["sl_pct"], neden, eff, pnl))
                del acik[ki]; cikan.add(ki)

                if a.ardisik_zarar_limiti > 0:
                    anah = f"{k.ad}:{k.coin}"
                    if pnl < 0:
                        seri_zarar[anah] = seri_zarar.get(anah, 0) + 1
                        if seri_zarar[anah] >= a.ardisik_zarar_limiti:
                            cooldown[anah] = simdi + pd.Timedelta(minutes=a.cooldown_dk)
                    else:
                        seri_zarar[anah] = 0

            if a.gunluk_zarar_pct > 0 and gun not in gun_durdu:
                if gun_pnl.get(gun, 0.0) <= -a.gunluk_zarar_pct * gun_bas[gun]:
                    gun_durdu.add(gun)

            # ─── 2) GIRISLER ───
            for _ns, _p, _s, ki, i in grup:
                if ki in acik: continue
                if (not a.ayni_bar_giris) and ki in cikan: continue
                if a.hayalet_blokaj and i <= engel.get(ki, -1): continue
                if gun in gun_durdu:
                    if k_sig_var(self.kollar[ki], i): self.sayac["gun_engel"] += 1
                    continue
                k = self.kollar[ki]
                anah = f"{k.ad}:{k.coin}"
                cd = cooldown.get(anah)
                if cd is not None and simdi < cd:
                    if k.sinyal(i) is not None: self.sayac["cd_engel"] += 1
                    continue
                sg = k.sinyal(i)
                if sg is None: continue
                self.sayac["sinyal"] += 1
                if a.tek_pozisyon_per_coin and any(
                        self.kollar[o].coin == k.coin for o in acik):
                    self.sayac["coin_engel"] = self.sayac.get("coin_engel", 0) + 1
                    continue
                yon, sld, rr, mh = sg
                if len(acik) >= a.maxpos:
                    self.sayac["koltuk_engel"] += 1
                    if a.hayalet_blokaj:
                        engel[ki] = min(i + mh, k.besleme.n - 1)
                    continue
                _h, _l, cl = k.besleme.bar(i)
                self.sayac["acildi"] += 1
                acik[ki] = dict(yon=yon, e=cl, sld=sld, slp=cl - yon * sld,
                                tp=cl + yon * rr * sld, i0=i, mh=mh, sl_pct=sld / cl)
                if a.hayalet_blokaj: engel[ki] = min(i + mh, k.besleme.n - 1)
            j = e

        for ki, p in acik.items():
            k = self.kollar[ki]
            i = min(p["i0"] + p["mh"], k.besleme.n - 1)
            _h, _l, cl = k.besleme.bar(i)
            R = p["yon"] * (cl - p["e"]) / p["sld"] - 2 * a.fee * p["e"] / p["sld"]
            if kayma: R -= kayma / p["sl_pct"]
            if a.funding:
                R -= _funding_R(a.funding.get(k.coin), k.besleme.zaman(p["i0"]),
                                k.besleme.zaman(i), p["yon"], p["sl_pct"])
            eff = min(a.riskf, a.cap * p["sl_pct"])
            taban = equity if a.bilesik_boyut else a.bal0
            islemler.append(Islem(k.ad, k.coin, p["yon"], k.besleme.zaman(p["i0"]),
                                  k.besleme.zaman(i), p["e"], cl, p["sld"], R,
                                  p["sl_pct"], "veri_sonu", eff, R * eff * taban))
        islemler.sort(key=lambda t: (t.cikis_ts.value, t.giris_ts.value, t.kol, t.coin))
        return islemler


# ─────────────────────────── olcum ───────────────────────────
def rap(isl, ad, yaz=True):
    R = np.array([t.R for t in isl]); eff = np.array([t.eff for t in isl])
    pnl = np.array([t.pnl for t in isl])
    ex = pd.to_datetime([t.cikis_ts for t in isl])
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum()/BAL0*100
    bil = np.cumprod(1 + R*eff); bb = np.concatenate([[1.0], bil])
    d = dict(n=len(isl), ortR=float(R.mean()), top=float(pnl.sum())/BAL0*100,
             aylik=float(ay.mean()),
             bdd=float(((np.maximum.accumulate(bb)-bb)/np.maximum.accumulate(bb)).max()*100),
             kotu=float(ay.min()), poz=float((ay>0).mean()*100),
             sd=float(R.std(ddof=1)), se=float(R.std(ddof=1)/np.sqrt(len(R))))
    if yaz:
        print(f"  {ad:<44s} n={d['n']:>5d} ortR {d['ortR']:>+.4f} toplam %{d['top']:>+8.2f} "
              f"aylik %{d['aylik']:>+6.2f} bilesikDD %{d['bdd']:>6.2f} kotuay %{d['kotu']:>7.2f} pozAy %{d['poz']:.0f}")
    return d


def imza(isl):
    return [(t.kol, t.coin, t.giris_ts.value, t.cikis_ts.value, round(t.R, 9)) for t in isl]


SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
TUM = DB.DONCH + DB.SQZ + DB.BB_COINS
fund = funding_yukle(TUM)
kollar = canli_kollar(SRC)
AY = Ayar(kayma_bp=15.85, funding=fund, **CANLI)

print(f"\n{'='*118}\n=== 0) MOTOR KOPYASI DENKLIK TESTI (uc anahtar da KAPALI) ===")
ref = Kronos(kollar, AY).kos()
kop = Kronos2(kollar, AY).kos()
r0 = rap(ref, "kronos.Kronos  (uretim motoru)")
r1 = rap(kop, "cd_yol.Kronos2 (kopya, anahtarlar kapali)")
denk = imza(ref) == imza(kop)
print(f"  imza birebir ayni mi: {denk}")
uy = (r0['n'] == 1712 and abs(r0['ortR']-0.1451) < 5e-4 and abs(r0['top']-621.78) < 0.5)
print(f"  on-kayitli taban eslesti mi: {uy}  (n=1712 ortR +0.1451 toplam %+621.78)")
if not (denk and uy):
    print("  -> DUR: kopya uretim motoruyla denk degil ya da taban tutmadi"); sys.exit(1)
print("  -> DENKLIK OK, olcume gecilebilir")

print(f"\n{'='*118}\n=== 1) C4  STOP DOLUM FIYATI (gap varsa ACILIS'tan dol) ===")
K4 = Kronos2(kollar, AY, stop_gap=True)
c4 = K4.kos()
r_c4 = rap(c4, "C4: gercekci stop dolumu")
print(f"  gap'te dolan stop sayisi: {K4.tani['gap_stop']} · toplam ham R kaybi {K4.tani['gap_R']:+.4f}R "
      f"(islem basina {K4.tani['gap_R']/max(len(c4),1):+.6f}R)")
print(f"  delta: ortR {r_c4['ortR']-r0['ortR']:+.4f}  toplam %{r_c4['top']-r0['top']:+.2f}  "
      f"aylik {r_c4['aylik']-r0['aylik']:+.2f}p  DD {r_c4['bdd']-r0['bdd']:+.2f}p  kotuay {r_c4['kotu']-r0['kotu']:+.2f}p")

print(f"\n{'='*118}\n=== 1b) C4 DUYARLILIK: stop cikislarina EK KAYMA (bp) ===")
for bp in (2.0, 5.0, 10.0, 15.85):
    rr_ = rap(Kronos2(kollar, AY, stop_gap=True, stop_ek_bp=bp).kos(), f"gap + stop ek kayma {bp:5.2f}bp")
    print(f"      delta vs taban: ortR {rr_['ortR']-r0['ortR']:+.4f}  toplam %{rr_['top']-r0['top']:+.2f}")

print(f"\n{'='*118}\n=== 2) C5  BAR ICI YOL: iyimser (ONCE HEDEF) ===")
c5 = Kronos2(kollar, AY, iyimser=True)
c5i = c5.kos()
r_c5 = rap(c5i, "C5: iyimser (once hedef)")
print(f"  belirsiz bar sayisi (hem sl hem tp dokunulan): {c5.tani['belirsiz_bar']}")
print(f"  delta: ortR {r_c5['ortR']-r0['ortR']:+.4f}  toplam %{r_c5['top']-r0['top']:+.2f}  "
      f"aylik {r_c5['aylik']-r0['aylik']:+.2f}p  DD {r_c5['bdd']-r0['bdd']:+.2f}p  kotuay {r_c5['kotu']-r0['kotu']:+.2f}p")
kb = Kronos2(kollar, AY); kb.kos()
print(f"  (karamsar kosuda ayni sayim: {kb.tani['belirsiz_bar']})")

print(f"\n{'='*118}\n=== 3) BIRLESIK: C4 + C5 (en kotu ve en iyi kose) ===")
r_both = rap(Kronos2(kollar, AY, stop_gap=True, iyimser=True).kos(), "C4 gercekci + C5 iyimser")
print(f"\n  BELIRSIZLIK BANDI (ortR): "
      f"{min(r_c4['ortR'], r0['ortR']):+.4f} ... {max(r_c5['ortR'], r_both['ortR']):+.4f}  "
      f"(taban {r0['ortR']:+.4f})")
print(f"  BELIRSIZLIK BANDI (toplam%): "
      f"{min(r_c4['top'], r0['top']):+.2f} ... {max(r_c5['top'], r_both['top']):+.2f}  (taban {r0['top']:+.2f})")

print(f"\n{'='*118}\n=== 4) TEST DILIMI (giris >= 2025-01-01) ===")
for ad, isl in (("taban", ref), ("C4 gercekci", c4), ("C5 iyimser", c5i)):
    rap([t for t in isl if t.giris_ts >= SPLIT], f"TEST · {ad}")

pickle.dump(dict(taban=r0, c4=r_c4, c5=r_c5, both=r_both), open(f"{SCR}/cd_yol_sonuc.pkl","wb"))
print(f"{'='*118}\n")
