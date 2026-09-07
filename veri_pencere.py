"""
veri_pencere.py — kovalama testi için 1dk pencereleri. BINANCE aylık dökümlerinden.

═══ İLK SÜRÜM ÇÖKTÜ VE İKİ HATASI BENDENDİ (2026-09-06 → düzeltildi) ═══════════
VPS çıktısı: her coin için "hiç pencere alınamadı", altında "TOPLAM: 0 alındı,
0 ALINAMADI". İki ayrı hata:

  (1) SESSİZ HATA — `except Exception: yok += 1; continue` hatanın SEBEBİNİ
      yutuyordu. Bütün oturum boyunca "okunamayan kaynak sıfır sayılmaz"
      diye uğraşıp aynı tuzağa kendim düştüm. Artık ilk hata TAM METNİYLE
      basılıyor ve arka arkaya 3 hatadan sonra o coin için DURULUYOR.

  (2) YALANCI SAYAÇ — coin tamamen başarısız olunca `continue` sayaç
      toplamasını atlıyordu; "0 alınamadı" yazıyordu, oysa 147 deneme
      başarısızdı. Sayaçlar artık her yolda toplanıyor.

═══ KÖK SEBEP: MEXC DERİN 1dk TUTMUYOR ════════════════════════════════════════
veri_binance.py'nin docstring'i bunu ZATEN yazıyordu ("MEXC 5dk'yı derin
geçmişe tutmuyor") — kontrol etmeden MEXC'e gittim. Kaynak Binance aylık
ZIP dökümleri oldu (data.binance.vision): hız limiti yok, eksiksiz,
tekrarlanabilir.

⚠ VENUE AYRIMI — repo kuralı: Binance verisi KEŞİF içindir, KARAR için değil.
   Dosyalar `{COIN}_bnc_pencere_1m.csv` diye kaydedilir, `_fut_` DEĞİL.
   Kovalama ölçümü "limit mi önce doldu, fiyat mı önce kaçtı" SIRALAMASINI
   sorar; bu soru için venue farkı ikinci derecedendir ama SIFIR değildir —
   `veri_binance.py --venue-fark SOL` ile ölçülebilir, hükümde belirtilmeli.

⚠ DİSKİ ŞİŞİRMEZ: aylık dosya indirilir, YALNIZ sinyal pencereleri (her
   sinyalden sonraki 4 saat) saklanır, gerisi atılır. Coin başına ~2 MB.
⚠ ANKOR VERİSİNE DOKUNMAZ: ayrı isim, fast_bt._save_cache yoluna hiç girmez.

Kullanım (VPS'te — ağ erişimi orada):
    venv/bin/python veri_pencere.py
    git add data/*_bnc_pencere_1m.csv && git commit -m "1dk pencereler" && git push
Sonra:
    python3 sabirli_maker.py local     # kovalama kolu 1dk SIRAYLA ölçer
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
import veri_binance as VB
from indicators import atr as atr_fn

PENCERE_SAAT = 4
CIKTI = "data/{coin}_bnc_pencere_1m.csv"
ART_ARDA_HATA_SINIR = 3


def sinyal_zamanlari(coin, source="local"):
    """A.gen'in KAPILARIYLA birebir (occ dahil) — ankorun ALDIĞI sinyaller.
    Döner: barın KAPANDIĞI anlar (limit o an konur)."""
    from strategies.donchian import DonchianStrategy
    m = fast_bt.load(coin, source=source)
    d4 = fast_bt.resample(m, "4h")
    a_ser = atr_fn(d4["high"], d4["low"], d4["close"], 14).values
    _dc = d4["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
        d4.index.normalize()).values
    up = d4["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d4["high"].values; lo = d4["low"].values; cl = d4["close"].values
    idx = d4.index; n = len(cl)
    _, _, sl_a, rr, mh = A.CFG["donchian"]
    out = []; occ = -1
    for i in range(260, n - 1):
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ:
            continue
        sg = s.analyze(d4.iloc[max(0, i - 259):i + 1], float(a))
        if sg.direction == 0:
            continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((sg.direction == 1 and dup) or (sg.direction == -1 and not dup)):
            continue
        e = cl[i]; sld = sl_a * a
        slp = e - sg.direction * sld; tp = e + sg.direction * rr * sld
        j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if sg.direction == 1:
                if lo[j] <= slp or hi[j] >= tp: break
            else:
                if hi[j] >= slp or lo[j] <= tp: break
        out.append(idx[i] + pd.Timedelta(hours=4))
        occ = j
    return out


def main():
    os.makedirs("data", exist_ok=True)
    g_ok = g_yok = 0
    ozet = []
    for coin in A.DONCH:
        p = CIKTI.format(coin=coin)
        if os.path.exists(p):
            print(f"  {coin}: {p} zaten var, ATLANDI (yeniden çekmek için sil)")
            ozet.append((coin, "atlandı", 0, 0))
            continue
        zamanlar = sinyal_zamanlari(coin)
        if not zamanlar:
            print(f"  ⛔ {coin}: sinyal bulunamadı — ankor verisi eksik olabilir")
            ozet.append((coin, "sinyal yok", 0, 0))
            continue
        aylar = sorted({t.strftime("%Y-%m") for t in zamanlar})
        print(f"  {coin}: {len(zamanlar)} sinyal · {len(aylar)} ay indirilecek",
              flush=True)
        parcalar = []; ok = yok = 0; ard = 0; ilk_hata = None
        for ay in aylar:
            try:
                d = VB._ay_indir(f"{coin}USDT", "1m", ay)
                ard = 0
            except Exception as e:
                yok += 1; ard += 1
                if ilk_hata is None:
                    ilk_hata = f"{type(e).__name__}: {e}"
                    # ⚠ İLK HATA TAM METNİYLE — sessiz geçmek YASAK
                    print(f"    ⛔ {coin} {ay}: {ilk_hata}", flush=True)
                if ard >= ART_ARDA_HATA_SINIR:
                    print(f"    ⛔ {coin}: arka arkaya {ard} hata — bu coin BIRAKILDI")
                    break
                continue
            if d is None or d.empty:
                yok += 1
                continue
            # yalnız bu aya düşen sinyal pencerelerini AL, gerisini AT
            for t0 in [t for t in zamanlar if t.strftime("%Y-%m") == ay]:
                w = d[(d.index >= t0) & (d.index < t0 + pd.Timedelta(hours=PENCERE_SAAT))]
                if len(w) < 30:            # çok delikli pencereyi ALMA
                    yok += 1
                    continue
                parcalar.append(w)
                ok += 1
            del d
        g_ok += ok; g_yok += yok           # ⚠ HER YOLDA topla (eski hata buydu)
        if not parcalar:
            print(f"    ⛔ {coin}: hiç pencere alınamadı ({yok} deneme başarısız)"
                  + (f" · ilk hata: {ilk_hata}" if ilk_hata else ""))
            ozet.append((coin, "BAŞARISIZ", ok, yok))
            continue
        tam = pd.concat(parcalar).sort_index()
        tam = tam[~tam.index.duplicated(keep="first")]
        tam.to_csv(p)
        mb = os.path.getsize(p) / 1e6
        print(f"    ✓ {p} · {ok}/{len(zamanlar)} pencere · {len(tam)} bar · {mb:.1f} MB")
        ozet.append((coin, "tamam", ok, yok))

    print(f"\n{'='*66}\n  ÖZET\n{'='*66}")
    for c, durum, ok, yok in ozet:
        print(f"    {c:<5s} {durum:<11s} alınan {ok:>4d} · alınamayan {yok:>4d}")
    print(f"\n  TOPLAM: {g_ok} pencere alındı, {g_yok} alınamadı")
    if g_ok == 0:
        print(f"  ⛔ HİÇBİR pencere alınamadı. Yukarıdaki İLK HATA satırlarına bak —")
        print(f"     ağ engeli, 404 (parite o ay listede yok) ya da disk olabilir.")
        print(f"     Kovalama ölçümü YAPILAMAZ; sabirli_maker.py'yi çalıştırma.")
        return 1
    if g_yok > g_ok * 0.2:
        print(f"  ⚠ Kayıp oranı %{g_yok/(g_ok+g_yok)*100:.0f} — ölçüm EKSİK")
        print(f"     örneklemle yapılır, hükümde bu belirtilmeli.")
    print(f"\n  Sonraki: git add data/*_bnc_pencere_1m.csv && git commit && git push")
    print(f"  ⚠ Venue farkı ölçülmeli: python3 veri_binance.py --venue-fark SOL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
