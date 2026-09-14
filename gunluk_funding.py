"""
gunluk_funding.py — 1D TREND KOLU, FUNDING DAHİL. Yeni ön-kayıtlı tabana karşı.

ÖN-KAYITLI ÖNGÖRÜ (koşmadan önce yazıldı, görev metninden):
  "kol ~24 gün tutuyor, kitap ~2 gün → ~12x funding ödemesi. Kitap 0.0054R
   ödüyor, bu kol ~0.065R ödemeli. Kolun kaymalı ort R'si +0.2016 → funding ile
   ~+0.137, yani yeni tabanın (+0.1451) ALTINA düşer."
Bu dosya öngörüyü ÖLÇER. Öngörünün İÇİNDE bir varsayım var ve o da test edilir:
funding R bedeli = Σrate / sl_pct. Pay (Σrate) tutuş süresiyle DOĞRUSAL büyür
ama PAYDA (sl_pct) da büyür, çünkü günlük ATR 4h ATR'den büyüktür. Yani
"12x ödeme = 12x bedel" YANLIŞ olabilir. Ölçülecek.

ÖN-KAYITLI PARAMETRE: ch=50 esp=200 sl=2.0 rr=3.0 mh=40 (IZGARA ORTASI, argmax YOK)
ÖN-KAYITLI GEÇME BARI: (a) Δ ort R ≥ +0.0694  (b) TEST diliminde de pozitif
                       (c) en kötü ay %-34.39'dan kötüleşmiyor

Kullanım: py gunluk_funding.py local
"""
import sys, json
import numpy as np, pandas as pd
import deployed_backtest as DB
from kronos import Kronos, Ayar
from kronos.motor import _funding_R
from kronos.kollar import canli_kollar, funding_yukle
from gunluk_kol import gunluk_kollar, gunluk_veri

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
BAL0 = 1000.0
KAYMA = 15.85
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
COINS = DB.DONCH + DB.SQZ                      # 11 deploy coini (ön-kayıtlı)
TUM = DB.DONCH + DB.SQZ + DB.BB_COINS
CH, ESP, SL_A, RR, MH = 50, 200, 2.0, 3.0, 40
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)
# GÜNLÜK KOL için: canlı frenler KAPALI. Sebep: ayrı koşuda günlük zarar freni
# kolun KENDİ equity'sine bakar — canlıda hesap geneline bakar. Yanlış modellemek
# yerine kola AVANTAJ verilip kapatıldı (fren kolu ancak kötüleştirir).
KOL_AYAR = dict(riskf=0.028, cap=1.50, bal0=BAL0, ayni_bar_giris=True,
                tek_pozisyon_per_coin=True)
# ön-kayıtlı taban rakamları (kronos_market.py)
T_ORTR, T_TOP, T_AYLIK, T_DD, T_KOTU = 0.1451, 621.78, 15.54, 51.58, -34.39
BAR_DELTA_R = 0.0694

W = 118
fund = funding_yukle(TUM)


# ────────────────────── ölçüm yardımcıları ──────────────────────
def _dizi(isl, olcek=1.0):
    tk = sorted(isl, key=lambda t: (t.cikis_ts.value, t.giris_ts.value, t.kol, t.coin))
    R = np.array([t.R for t in tk]); eff = np.array([t.eff for t in tk]) * olcek
    ex = pd.to_datetime([t.cikis_ts for t in tk])
    return tk, R, eff, ex


def bilesik_dd(isl, olcek=1.0):
    if not isl: return 0.0
    _, R, eff, _ = _dizi(isl, olcek)
    b = np.concatenate([[1.0], np.cumprod(1 + R * eff)])
    return float(((np.maximum.accumulate(b) - b) / np.maximum.accumulate(b)).max() * 100)


def olcek_bul(isl, hedef):
    if bilesik_dd(isl, 1.0) <= hedef: return 1.0
    lo, hi = 0.02, 1.0
    for _ in range(60):
        m = (lo + hi) / 2
        if bilesik_dd(isl, m) > hedef: hi = m
        else: lo = m
    return (lo + hi) / 2


def rapor(isl, olcek=1.0):
    tk, R, eff, ex = _dizi(isl, olcek)
    pnl = R * eff * BAL0
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / BAL0 * 100
    return dict(n=len(tk), ortR=float(R.mean()), top=float(pnl.sum()) / BAL0 * 100,
                aylik=float(ay.mean()), bdd=bilesik_dd(isl, olcek),
                kotu=float(ay.min()), poz=float((ay > 0).mean() * 100), pnl=pnl, ay=ay)


def test_dilim(isl):
    return [t for t in isl if t.giris_ts >= SPLIT]


def funding_detay(isl, etiket):
    """İşlem başına: tutuş günü, funding ödeme SAYISI, funding'in R bedeli."""
    gun, ade, fr, slp = [], [], [], []
    for t in isl:
        s = fund.get(t.coin)
        gun.append((t.cikis_ts - t.giris_ts).total_seconds() / 86400)
        if s is None:
            ade.append(0); fr.append(0.0)
        else:
            m = s.loc[(s.index > t.giris_ts) & (s.index <= t.cikis_ts)]
            ade.append(len(m))
            fr.append(float(t.yon * m.sum() / t.sl_pct) if t.sl_pct > 0 else 0.0)
        slp.append(t.sl_pct)
    g, a, f, sp = map(np.array, (gun, ade, fr, slp))
    uzun = np.array([t.yon for t in isl]) == 1
    print(f"  {etiket:<30s} n={len(g):>5d}  tutuş {g.mean():>6.2f} gün (medyan {np.median(g):>5.2f})  "
          f"funding ödemesi {a.mean():>6.2f}/işlem  sl_pct %{sp.mean()*100:>5.2f}")
    print(f"  {'':<30s}        funding R bedeli ORT {f.mean():>+.4f}  "
          f"(long {f[uzun].mean() if uzun.any() else 0:+.4f} / short {f[~uzun].mean() if (~uzun).any() else 0:+.4f})  "
          f"· gün başına {f.mean()/max(g.mean(),1e-9):>+.5f} R/gün")
    return dict(gun=g, ade=a, fr=f, slp=sp)


print(f"\n{'='*W}\n=== 1) TABAN DOĞRULAMA (yeni ön-kayıtlı taban yeniden üretiliyor) ===")
kk = canli_kollar(SRC)
kitap_nf = Kronos(kk, Ayar(kayma_bp=KAYMA, **CANLI)).kos()              # funding YOK
kitap = Kronos(kk, Ayar(kayma_bp=KAYMA, funding=fund, **CANLI)).kos()   # funding VAR
import pickle, os
_SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
os.makedirs(_SCR, exist_ok=True)
pickle.dump(kitap, open(f"{_SCR}/kitap_funding.pkl", "wb"))
pickle.dump(kitap_nf, open(f"{_SCR}/kitap_nofunding.pkl", "wb"))
rb = rapor(kitap)
print(f"  kitap (kayma+funding): n={rb['n']} ortR {rb['ortR']:+.4f} toplam %{rb['top']:+.2f} "
      f"aylık %{rb['aylik']:+.2f} bileşikDD %{rb['bdd']:.2f} kötüay %{rb['kotu']:.2f} pozAy %{rb['poz']:.0f}")
uy = (rb['n'] == 1712 and abs(rb['ortR'] - T_ORTR) < 5e-4 and abs(rb['top'] - T_TOP) < 0.5
      and abs(rb['bdd'] - T_DD) < 0.05)
print(f"  ön-kayıtlı: n=1712 ortR +0.1451 toplam %+621.78 aylık %+15.54 bileşikDD %51.58 kötüay %-34.39")
print(f"  → {'EŞLEŞTİ ✓' if uy else '⛔ EŞLEŞMEDİ — DUR'}")
if not uy: sys.exit(1)
rb_te = rapor(test_dilim(kitap))
print(f"  TEST dilimi (giriş≥2025-01-01): n={rb_te['n']} ortR {rb_te['ortR']:+.4f} toplam %{rb_te['top']:+.2f}")


print(f"\n{'='*W}\n=== 2) GÜNLÜK KOL TEK BAŞINA (ön-kayıtlı ch50/ema200/sl2.0/rr3.0/mh40) ===")
ob = {c: gunluk_veri(c, SRC) for c in COINS}
def kol_kur(ch=CH, esp=ESP, sl_a=SL_A, rr=RR, mh=MH):
    return gunluk_kollar(COINS, SRC, None, ch, esp, sl_a, rr, mh, ob)

for ad, ky, fd in (("A) kaymasız + fundingsiz", 0.0, None),
                   ("B) 15.85bp kaymalı", KAYMA, None),
                   ("C) kayma + FUNDING", KAYMA, fund)):
    for mp, mad in ((10**9, "kısıtsız"), (7, "7 koltuk"), (2, "2 koltuk")):
        a = dict(KOL_AYAR); a["maxpos"] = mp
        r = rapor(Kronos(kol_kur(), Ayar(kayma_bp=ky, funding=(fd or {}), **a)).kos())
        print(f"  {ad:<26s} {mad:<9s} n={r['n']:>4d} ortR {r['ortR']:+.4f} toplam %{r['top']:+8.2f} "
              f"bileşikDD %{r['bdd']:6.2f} kötüay %{r['kotu']:+7.2f}")

print(f"\n  --- funding ayrıntısı (işlem bazında, kısıtsız koşudan) ---")
a = dict(KOL_AYAR); a["maxpos"] = 10**9
kol_ham = Kronos(kol_kur(), Ayar(kayma_bp=KAYMA, **a)).kos()
fd_kol = funding_detay(kol_ham, "GÜNLÜK kol (1D, mh40)")
fd_kit = funding_detay(kitap_nf, "KİTAP (donchian+squeeze+bb)")
for sv in ("donchian", "squeeze", "bb"):
    funding_detay([t for t in kitap_nf if t.kol == sv], f"  kitap/{sv}")


print(f"\n{'='*W}\n=== 3) AYRI HAVUZ · YENİ TABANA KARŞI · RİSK BİLEŞİK maxDD %{T_DD} 'e EŞİTLENMİŞ ===")
print(f"  {'S':<4} {'kol n':>6} {'ölçek':>7} {'ortR':>8} {'ΔortR':>8} {'toplam%':>9} {'Δtoplam%':>9} "
      f"{'aylık%':>8} {'Δaylık%':>8} {'kötüay%':>8} {'ΔTEST%':>8}  BAR")
taban_te = rapor(test_dilim(kitap))
sonuc = {}
for S in (1, 2, 3):
    a = dict(KOL_AYAR); a["maxpos"] = S
    kol = Kronos(kol_kur(), Ayar(kayma_bp=KAYMA, funding=fund, **a)).kos()
    C = kitap + kol
    o = olcek_bul(C, rb["bdd"])
    rc = rapor(C, o); rc_te = rapor(test_dilim(C), o)
    d_r = rc["ortR"] - rb["ortR"]; d_ay = rc["aylik"] - rb["aylik"]
    d_te = rc_te["top"] - taban_te["top"]
    gec = (d_r >= BAR_DELTA_R) and (d_te > 0) and (rc["kotu"] >= rb["kotu"])
    sonuc[S] = dict(dR=d_r, dtop=rc["top"] - rb["top"], day=d_ay, dte=d_te,
                    kotu=rc["kotu"], n=len(kol), olcek=o)
    print(f"  S={S:<2} {len(kol):>6d} {o:>7.3f} {rc['ortR']:>+8.4f} {d_r:>+8.4f} {rc['top']:>+9.2f} "
          f"{rc['top']-rb['top']:>+9.2f} {rc['aylik']:>+8.2f} {d_ay:>+8.2f} {rc['kotu']:>+8.2f} "
          f"{d_te:>+8.2f}  {'✓ GEÇTİ' if gec else '✗'}")
print(f"  taban    {'—':>6} {1.0:>7.3f} {rb['ortR']:>+8.4f} {'—':>8} {rb['top']:>+9.2f} {'—':>9} "
      f"{rb['aylik']:>+8.2f} {'—':>8} {rb['kotu']:>+8.2f} {'—':>8}")
print(f"\n  ön-kayıtlı bar: (a) ΔortR ≥ +{BAR_DELTA_R:.4f}  (b) ΔTEST% > 0  (c) kötü ay ≥ %{rb['kotu']:.2f}")


print(f"\n{'='*W}\n=== 4) NETTED TEK-POZİSYON/COIN BEDELİ (ayrı havuzun MODELLEMEDİĞİ kısıt) ===")
print(f"  MEXC netted: bir sembol = bir net pozisyon (execution.py:403). Günlük kol SOL'u")
print(f"  24 gün tutarsa kitabın SOL donchian'ı O SÜRE BOYUNCA giremez. Ayrı havuz bunu")
print(f"  modellemiyor → aşağıdaki rakam ayrı havuz sonucunun İYİMSERLİK PAYI.")
a = dict(KOL_AYAR); a["maxpos"] = 2
kol2 = Kronos(kol_kur(), Ayar(kayma_bp=KAYMA, funding=fund, **a)).kos()
mesgul = {}
for t in kol2: mesgul.setdefault(t.coin, []).append((t.giris_ts, t.cikis_ts))
blok, blok_pnl, blok_n = 0, 0.0, 0
for t in kitap:
    for (g, c) in mesgul.get(t.coin, []):
        if g <= t.giris_ts <= c:
            blok += 1; blok_pnl += t.pnl; break
print(f"  günlük kol (S=2) {len(kol2)} işlem · kitabın {blok}/{len(kitap)} işlemi "
      f"(%{blok/len(kitap)*100:.1f}) o coin meşgulken açılmış")
print(f"  bu işlemlerin kitaba katkısı: %{blok_pnl/BAL0*100:+.2f} (toplam %{rb['top']:+.2f}'in "
      f"%{blok_pnl/BAL0*100/rb['top']*100:.1f}'i)")
print(f"  → ayrı havuz Δ'sından bu kadarı DÜŞÜLMELİ (üst sınır: bazıları sonra tekrar girebilir)")


print(f"\n{'='*W}\n=== 5) GENEL İLKE: 'funding uzun tutan her stratejiyi vurur' — DOĞRU MU? ===")
g_k, f_k, s_k = fd_kit["gun"], fd_kit["fr"], fd_kit["slp"]
g_d, f_d, s_d = fd_kol["gun"], fd_kol["fr"], fd_kol["slp"]
print(f"  tutuş oranı      : {g_d.mean()/g_k.mean():>6.2f}x  ({g_k.mean():.2f} gün → {g_d.mean():.2f} gün)")
print(f"  ödeme oranı      : {fd_kol['ade'].mean()/max(fd_kit['ade'].mean(),1e-9):>6.2f}x  "
      f"({fd_kit['ade'].mean():.2f} → {fd_kol['ade'].mean():.2f} ödeme/işlem)")
print(f"  sl_pct oranı     : {s_d.mean()/s_k.mean():>6.2f}x  (%{s_k.mean()*100:.2f} → %{s_d.mean()*100:.2f}) "
      f"← PAYDA da büyüyor: bu, ödeme sayısı artışını KISMEN yutar")
print(f"  funding R bedeli : {f_d.mean()/max(f_k.mean(),1e-9):>6.2f}x  "
      f"({f_k.mean():+.4f}R → {f_d.mean():+.4f}R)")
print(f"  → öngörülen ~12x ödeme / ~0.065R bedel idi. ÖLÇÜLEN yukarıda.")
print(f"\n  tutuş süresine göre kova (kitap+kol birlikte, {len(g_k)+len(g_d)} işlem):")
G = np.concatenate([g_k, g_d]); F = np.concatenate([f_k, f_d]); S_ = np.concatenate([s_k, s_d])
A_ = np.concatenate([fd_kit["ade"], fd_kol["ade"]])
kenar = [0, 0.5, 1, 2, 4, 8, 16, 32, 1e9]
print(f"  {'tutuş(gün)':<14}{'n':>6}{'ödeme':>8}{'sl_pct%':>9}{'funding R':>11}{'R/gün':>10}")
for i in range(len(kenar) - 1):
    m = (G >= kenar[i]) & (G < kenar[i + 1])
    if m.sum() < 5: continue
    lab = f"{kenar[i]:g}-{kenar[i+1]:g}" if kenar[i+1] < 1e8 else f"{kenar[i]:g}+"
    print(f"  {lab:<14}{m.sum():>6d}{A_[m].mean():>8.2f}{S_[m].mean()*100:>9.2f}"
          f"{F[m].mean():>+11.4f}{F[m].mean()/max(G[m].mean(),1e-9):>+10.5f}")
kor = np.corrcoef(G, F)[0, 1]
print(f"  Pearson(tutuş gün, funding R) = {kor:+.3f}   "
      f"Pearson(gün/sl_pct, funding R) = {np.corrcoef(G/np.maximum(S_,1e-9), F)[0,1]:+.3f}")
print(f"{'='*W}\n")
json.dump({str(k): {kk: (float(vv) if not isinstance(vv, int) else vv) for kk, vv in v.items()}
           for k, v in sonuc.items()},
          open("/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/ayri.json", "w"))
