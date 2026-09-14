"""
kronos_yuzde.py — KRONOS sonuclarini $1000 taban ve YUZDE cinsinden verir.

OLCEK DEGISMEZLIGI: eff = min(riskf, cap*sl_pct) tabandan BAGIMSIZ; pnl = R*eff*BAL0
dogrusal; gunluk fren oransal (gun basi equity'nin %35'i). Dolayisiyla taban
190 -> 1000 bütün dolarlari 5.26x yapar, YUZDELERI HIC DEGISTIRMEZ.
Bu dosya bunu once KANITLAR, sonra yuzdeleri basar.

MODELLENMEYEN TEK OLCEK ETKISI: minimum emir buyuklugu. Motor bunu bilmiyor.
"""
import sys
import numpy as np, pandas as pd
import deployed_backtest as A
from kronos import Kronos, Ayar
from kronos.kollar import canli_kollar

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
kollar = canli_kollar(SRC)
CANLI = dict(maxpos=7, riskf=0.028, cap=1.50, ayni_bar_giris=True,
             ardisik_zarar_limiti=2, cooldown_dk=240, gunluk_zarar_pct=0.35,
             tek_pozisyon_per_coin=True)

def rapor(isl, bal0):
    R = np.array([t.R for t in isl]); eff = np.array([t.eff for t in isl])
    pnl = np.array([t.pnl for t in isl])
    ex = pd.to_datetime([t.cikis_ts for t in isl])
    yil = (ex.max() - ex.min()).days / 365.25
    # SABIT-KESIR uzayi (dogrusal)
    top_sk = pnl.sum() / bal0 * 100
    eq = np.concatenate([[bal0], bal0 + np.cumsum(pnl)])
    dd_sk = float(((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq)).max() * 100)
    # BILESIK uzayi (botun gercek davranisi)
    bil = np.cumprod(1 + R * eff)
    top_b = (bil[-1] - 1) * 100
    bb = np.concatenate([[1.0], bil])
    dd_b = float(((np.maximum.accumulate(bb) - bb) / np.maximum.accumulate(bb)).max() * 100)
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / bal0 * 100
    return dict(n=len(isl), yil=yil, top_sk=top_sk, yillik_sk=top_sk / yil,
                aylik_sk=ay.mean(), dd_sk=dd_sk, top_b=top_b,
                yillik_b=((bil[-1]) ** (1 / yil) - 1) * 100, dd_b=dd_b,
                kotu=ay.min(), iyi=ay.max(), poz_ay=(ay > 0).mean() * 100,
                ay_med=ay.median(), kat=bil[-1], dolar=pnl.sum(), ay_n=len(ay))

print(f"\n{'='*100}\n=== ÖLÇEK DEĞİŞMEZLİĞİ KANITI ===")
r190 = rapor(Kronos(kollar, Ayar(bal0=190.0, kayma_bp=15.85, **CANLI)).kos(), 190.0)
r1000 = rapor(Kronos(kollar, Ayar(bal0=1000.0, kayma_bp=15.85, **CANLI)).kos(), 1000.0)
print(f"  taban $190 : n={r190['n']}  toplam ${r190['dolar']:+.2f}  = %{r190['top_sk']:+.2f}")
print(f"  taban $1000: n={r1000['n']}  toplam ${r1000['dolar']:+.2f}  = %{r1000['top_sk']:+.2f}")
ayni = abs(r190['top_sk'] - r1000['top_sk']) < 1e-9 and r190['n'] == r1000['n']
print(f"  → yüzdeler {'BİREBİR AYNI ✓ (taban sonucu etkilemiyor)' if ayni else 'FARKLI ⛔'}")

for ad, ky in (("KAYMASIZ (üst sınır)", 0.0), ("15.85bp KAYMALI (alt sınır)", 15.85)):
    r = rapor(Kronos(kollar, Ayar(bal0=1000.0, kayma_bp=ky, **CANLI)).kos(), 1000.0)
    print(f"\n{'='*100}\n=== $1000 TABAN · {ad} · {r['n']} işlem · {r['yil']:.2f} yıl ===")
    print(f"\n  ── SABİT KESİR (her işlem aynı taban; doğrusal, kıyas için) ──")
    print(f"     toplam getiri    %{r['top_sk']:+8.2f}      →  ${1000 + r['dolar']:,.0f}")
    print(f"     yıllık           %{r['yillik_sk']:+8.2f}")
    print(f"     aylık ortalama   %{r['aylik_sk']:+8.2f}   ·  medyan %{r['ay_med']:+.2f}")
    print(f"     maxDD            %{r['dd_sk']:8.2f}")
    print(f"\n  ── BİLEŞİK (botun GERÇEK davranışı: canlı equity'den boyutlandırma) ──")
    print(f"     toplam getiri    %{r['top_b']:+8.2f}      →  ${1000 * r['kat']:,.0f}  ({r['kat']:.2f}x)")
    print(f"     yıllık (CAGR)    %{r['yillik_b']:+8.2f}")
    print(f"     maxDD            %{r['dd_b']:8.2f}   ← GERÇEK risk bu")
    print(f"\n  ── AYLIK DAĞILIM ({r['ay_n']} ay) ──")
    print(f"     en iyi %{r['iyi']:+.2f} · en kötü %{r['kotu']:+.2f} · pozitif ay oranı %{r['poz_ay']:.1f}")
print(f"{'='*100}\n")
