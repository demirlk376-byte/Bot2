"""
neden_sessiz.py — "Bot neden işlem açmıyor?" CANLI TEŞHİS.

Log'larda halt/cooldown/korelasyon kapısı YOK; tek görünen "BB skipped" ve BB
zaten YALNIZ HAFTA SONU çalışıyor. Yani bot durdurulmuş değil — sinyal yok.
Ama "sinyal yok" bir cevap değil, bir gözlem. Bu araç NEDEN olmadığını sayıyla
gösteriyor: her coin için kırılıma NE KADAR kaldığını.

HİPOTEZ (ölçülecek): BTC 62.239→79.539 hareketinden sonra 40 barlık kanal
(40×4s ≈ 6.7 GÜN) o hareketin TAMAMINI içine aldı. Kanal çok geniş, fiyat
ortasında, tetikleyecek bir şey yok. Zirve barları pencereden çıktıkça
(~6-7 gün) kanal daralır ve sinyaller kendiliğinden döner.

⚠ Bu araç MEXC'ten TAZE veri çeker ama önbelleği EZMEZ — fast_bt._save_cache
artık mevcut dosyanın üzerine yazmıyor (2026-08-14'te ankor verisi bu yüzden
bozulmuştu). Ankor güvende.

Kullanım (VPS'te):  cd /opt/bot2 && python3 neden_sessiz.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn

KANAL = 40


def main() -> None:
    print("=" * 96)
    print("=== NEDEN İŞLEM AÇMIYOR? — canlı kanal durumu ===")
    print("  Donchian: 40 bar × 4 saat = son ~6.7 GÜNÜN en yükseği/en düşüğü.")
    print("  Kırılım için fiyatın o aralığı AŞMASI gerekir.\n")
    print(f"  {'coin':<6s} {'fiyat':>10s} {'kanal alt':>11s} {'kanal üst':>11s} "
          f"{'kanal %':>8s} {'üste uzak':>10s} {'alta uzak':>10s} {'MTF':>5s}")
    yakin = []
    for c in A.DONCH:
        try:
            m = fast_bt.load(c, source="mexc_futures")
        except Exception as e:
            print(f"  {c:<6s} veri alınamadı: {str(e)[:40]}")
            continue
        d = fast_bt.resample(m, "4h")
        hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
        i = len(cl) - 1
        k0 = max(0, i - KANAL)
        ust = hi[k0:i].max(); alt = lo[k0:i].min(); f = cl[i]
        gen = (ust - alt) / f * 100
        du = (ust - f) / f * 100
        da = (f - alt) / f * 100
        # MTF kapısı: kapanış > DÜNE kadar tamamlanmış günlük EMA20
        _dc = d["close"].resample("1D").last().dropna()
        _dp = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
            d.index.normalize()).values
        up = bool(cl[i] > _dp[i]) if np.isfinite(_dp[i]) else True
        print(f"  {c:<6s} {f:>10.4f} {alt:>11.4f} {ust:>11.4f} {gen:>7.1f}% "
              f"{du:>9.2f}% {da:>9.2f}% {'LONG' if up else 'SHORT':>5s}")
        yakin.append((c, du if up else da, "üst" if up else "alt"))

    print(f"\n  MTF sütunu: günlük trend LONG'a izin veriyorsa yalnız ÜSTE kırılım,")
    print(f"  SHORT'a izin veriyorsa yalnız ALTA kırılım işlem açar.")
    if yakin:
        yakin.sort(key=lambda z: z[1])
        print(f"\n  KIRILIMA EN YAKIN 3 COİN (MTF'in izin verdiği yönde):")
        for c, d_, yon in yakin[:3]:
            print(f"    {c:<6s} {yon} kırılıma %{d_:.2f} kaldı")

    print(f"\n{'='*96}\n=== SQUEEZE KOLU (XRP DOGE TRX XLM, 1 saatlik) ===")
    print(f"  Kapı: ADX > 20 olmalı. ADX düşükse sinyal ÜRETİLMEZ.\n")
    print(f"  {'coin':<6s} {'ADX':>7s}  durum")
    for c in A.SQZ:
        try:
            m = fast_bt.load(c, source="mexc_futures")
        except Exception as e:
            print(f"  {c:<6s} veri alınamadı"); continue
        d = fast_bt.resample(m, "1h")
        ax = adx_fn(d["high"], d["low"], d["close"], 14).values
        v = ax[-1] if np.isfinite(ax[-1]) else 0.0
        print(f"  {c:<6s} {v:>7.1f}  {'✓ kapı AÇIK' if v > 20 else '✗ ADX<20, kapı KAPALI'}")

    print(f"\n{'='*96}\n=== BB/MR KOLU (LTC) ===")
    bugun = pd.Timestamp.utcnow()
    hs = bugun.weekday() >= 5
    print(f"  Bugün {bugun.strftime('%A')} · hafta sonu mu: {'EVET' if hs else 'HAYIR'}")
    print(f"  {'✓ çalışabilir' if hs else '✗ BB YALNIZ HAFTA SONU — bu normal, arıza değil'}")

    print(f"\n{'='*96}\n=== HÜKÜM ===")
    print(f"  Yukarıdaki 'kanal %' sütunu geniş (>%15) ve fiyat ortadaysa:")
    print(f"  bot BOZUK DEĞİL, tetikleyecek bir şey YOK. Sert hareket sonrası")
    print(f"  kanal o hareketin tamamını içerir; zirve/dip barları 40-barlık")
    print(f"  pencereden çıkana kadar (~6-7 gün) sessizlik NORMALDİR.")
    print(f"\n  ⚠ Bu bir tahmin değil, mekanik: kanal = son 40 barın uç değerleri.")
