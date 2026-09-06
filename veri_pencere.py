"""
veri_pencere.py — sabırlı-maker testi için TAM GEREKEN 1dk pencereleri çeker.

NEDEN: sabirli_maker.py'nin KOVALAMA kolu 1h çözünürlükte test EDİLEMEDİ.
Sebep ölçüldü: 1h barında fiyat hem +10bp hem −10bp gidiyor, kötümser
beraberlik kuralı yüzünden her seferinde "kovalama" sayılıyor ve dolum
kontrolüne hiç ulaşılmıyor (kanıt: 2bp ve 10bp derinlik satırları BİREBİR
aynı sonucu verdi). Yani o tablo kovalama fikrini test etmiyor.

Doğru test BAR-İÇİ SIRA istiyor: limit mi önce doldu, fiyat mı önce kaçtı?
Bunun için 1dk veri şart. Ama 3.3 yıl × 7 coin × 1dk = ~12M bar; gereksiz.
GEREKEN yalnızca her donchian sinyalinden SONRAKİ 4 saat: sinyal başına 240
bar. ~145 sinyal/coin × 7 coin ≈ 1000 istek, birkaç dakika.

⚠ Ankor verisine DOKUNMAZ: ayrı dosyalara yazar (data/{COIN}_pencere_1m.csv),
   fast_bt._save_cache yoluna hiç girmez.
⚠ Eksik pencereyi UYDURMAZ: çekilemeyen sinyal kaydedilmez, sayısı raporlanır.

Kullanım (VPS'te — MEXC erişimi orada var):
    venv/bin/python veri_pencere.py
    git add data/*_pencere_1m.csv && git commit -m "1dk pencereler" && git push
Sonra PC'de:
    python3 sabirli_maker.py local      # kovalama kolu artık 1dk sırayla ölçer
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
from indicators import atr as atr_fn

PENCERE_SAAT = 4
CIKTI = "data/{coin}_pencere_1m.csv"


def sinyal_zamanlari(coin, source="local"):
    """A.gen'in KAPILARIYLA birebir — occ dahil, yani ankorun aldığı sinyaller."""
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
        out.append(idx[i] + pd.Timedelta(hours=4))     # barın KAPANDIĞI an
        occ = j
    return out


def main():
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}, "enableRateLimit": True})
    toplam_ok = toplam_yok = 0
    for coin in A.DONCH:
        p = CIKTI.format(coin=coin)
        if os.path.exists(p):
            print(f"  {coin}: {p} zaten var, ATLANDI (silip yeniden çek)")
            continue
        zamanlar = sinyal_zamanlari(coin)
        print(f"  {coin}: {len(zamanlar)} sinyal penceresi çekiliyor...", flush=True)
        parcalar = []; ok = yok = 0
        for t0 in zamanlar:
            since = int(t0.timestamp() * 1000)
            try:
                b = ex.fetch_ohlcv(f"{coin}/USDT:USDT", "1m", since=since,
                                   limit=PENCERE_SAAT * 60)
            except Exception as e:
                yok += 1
                continue
            if not b:
                yok += 1
                continue
            d = pd.DataFrame(b, columns=["ts", "open", "high", "low", "close", "volume"])
            d.index = pd.to_datetime(d["ts"], unit="ms", utc=True)
            # istenen pencerenin DIŞINI at (borsa fazla verebilir)
            d = d[(d.index >= t0) & (d.index < t0 + pd.Timedelta(hours=PENCERE_SAAT))]
            if len(d) < 30:                       # çok delikli pencereyi ALMA
                yok += 1
                continue
            parcalar.append(d.drop(columns=["ts"]))
            ok += 1
            time.sleep(0.12)
        if not parcalar:
            print(f"    ⛔ {coin}: hiç pencere alınamadı, dosya YAZILMADI")
            continue
        tam = pd.concat(parcalar).sort_index()
        tam = tam[~tam.index.duplicated(keep="first")]
        os.makedirs("data", exist_ok=True)
        tam.to_csv(p)
        toplam_ok += ok; toplam_yok += yok
        print(f"    ✓ {p} · {ok} pencere ({yok} alınamadı) · {len(tam)} bar")
    print(f"\n  TOPLAM: {toplam_ok} pencere alındı, {toplam_yok} alınamadı")
    if toplam_yok > toplam_ok * 0.2:
        print(f"  ⚠ Kayıp oranı %20'nin üstünde — kovalama ölçümü EKSİK örneklemle")
        print(f"    yapılır, hükümde bunu belirt.")
    print(f"  Sonraki adım: git add data/*_pencere_1m.csv && git commit && git push")


if __name__ == "__main__":
    main()
