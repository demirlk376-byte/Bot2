"""
veri_binance.py — ARAŞTIRMA VERİSİ: Binance vadeli (USDⓈ-M) aylık kline dökümleri.

NEDEN BINANCE: MEXC 5dk'yı derin geçmişe tutmuyor (veri_cek.py --probe). Yeni
brief'in istediği walk-forward + out-of-sample ancak derin veriyle anlamlı olur;
6 aylık bir pencerede "OOS" demek kendimizi kandırmaktır.

⚠ VENUE AYRIMI — bu dosyanın en önemli kuralı:
    Binance verisi KEŞİF içindir. KARAR için değil.
  Bu yüzden dosyalar `{COIN}_bnc_5m.csv` diye kaydediliyor, `_fut_` DEĞİL.
  MEXC önbelleği `{COIN}_fut_1h.csv`. İsimler karışmasın diye ayrı; bir araştırma
  betiği yanlışlıkla ikisini karıştıramaz.

  Bir strateji Binance'te hayatta kalırsa, karar ÖNCESİ MEXC'te ÖRTÜŞEN pencerede
  yeniden koşturulur. Bugün ankor denetiminde aynı ayrımı yaptık: bir ölçümün
  "hangi soruyu cevapladığı" ile "hangi soruya cevap sanıldığı" farklı şeyler.

KAYNAK: data.binance.vision aylık ZIP dökümleri.
  • REST API'ye göre üstün: hız limiti yok, eksiksiz, tekrarlanabilir (aynı dosya
    her indirişte aynı) — REST'te sayfalama hatası sessizce boşluk üretebilir.
  • Ek bağımlılık yok (urllib + zipfile, ikisi de stdlib).

VENUE FARKI ÖLÇÜLÜYOR, VARSAYILMIYOR: `--venue-fark` MEXC 1h önbelleğiyle
Binance'in 1h'a indirgenmiş halini aynı pencerede karşılaştırır ve farkı bp
cinsinden basar. "Çok fark olmaz" bir hipotezdir; bu onu sınar.

Kullanım (VPS'te):
    python3 veri_binance.py 5m 2023-09 2026-08
    python3 veri_binance.py --durum 5m
    python3 veri_binance.py --venue-fark SOL
"""
from __future__ import annotations

import io
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date

import numpy as np
import pandas as pd

CACHE = "data"
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB",
         "XRP", "DOGE", "TRX", "XLM", "LTC", "BTC"]
KOL = ["ts", "open", "high", "low", "close", "volume", "close_time",
       "quote_volume", "count", "taker_buy_volume", "taker_buy_quote", "ignore"]
ADIM = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def yol(coin: str, tf: str) -> str:
    return os.path.join(CACHE, f"{coin}_bnc_{tf}.csv")


def _aylar(bas: str, son: str) -> list[str]:
    y0, m0 = map(int, bas.split("-"))
    y1, m1 = map(int, son.split("-"))
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _ay_indir(sym: str, tf: str, ay: str) -> pd.DataFrame | None:
    url = f"{BASE}/{sym}/{tf}/{sym}-{tf}-{ay}.zip"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            ham = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None            # o ay yok (parite henüz listelenmemiş / güncel ay)
        raise
    with zipfile.ZipFile(io.BytesIO(ham)) as z:
        with z.open(z.namelist()[0]) as f:
            ilk = f.readline()
            basliksiz = ilk.split(b",")[0].strip().isdigit()
            f.seek(0)
            # Binance 2025'ten sonra başlık satırı ekledi. İkisini de tanı;
            # başlığı veri sanmak ilk barı bozar ve sessizce ilerler.
            d = pd.read_csv(f, header=None if basliksiz else 0, names=KOL)
    d = d[["ts", "open", "high", "low", "close", "volume"]].astype(float)
    # Binance 2025'te ts birimini mikrosaniyeye çevirdi (bazı dosyalarda).
    # Büyüklükten tanı: ms ~1.7e12, µs ~1.7e15.
    if d["ts"].iloc[0] > 1e14:
        d["ts"] = d["ts"] / 1000.0
    d.index = pd.to_datetime(d["ts"], unit="ms", utc=True)
    return d.drop(columns=["ts"])


def cek(coin: str, tf: str, bas: str, son: str) -> pd.DataFrame | None:
    sym = f"{coin}USDT"
    parca, yok = [], 0
    for ay in _aylar(bas, son):
        try:
            d = _ay_indir(sym, tf, ay)
        except Exception as e:
            print(f"\n    ⚠ {coin} {ay}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if d is None:
            yok += 1
            continue
        parca.append(d)
    if not parca:
        return None
    m = pd.concat(parca)
    m = m[~m.index.duplicated(keep="first")].sort_index()
    # SON BAR ATILIR — güncel ay dosyası oluşmakta olan barı içerebilir.
    m = m.iloc[:-1]
    if yok:
        print(f"    ({yok} ay dosyası yok — parite o tarihte listelenmemiş olabilir)", end="")
    return m


def rapor(m: pd.DataFrame, tf: str) -> str:
    gun = (m.index[-1] - m.index[0]).total_seconds() / 86400
    bekl = int(gun * 86400 / ADIM[tf])
    eksik = 1 - len(m) / max(bekl, 1)
    return (f"{len(m):>8d} bar · {gun:>5.0f} gün · {m.index[0].date()} → "
            f"{m.index[-1].date()} · boşluk %{eksik*100:.1f}")


def durum(tf: str) -> None:
    print(f"\n{'coin':<6s} durum")
    for c in COINS:
        p = yol(c, tf)
        if not os.path.exists(p):
            print(f"{c:<6s} YOK")
            continue
        d = pd.read_csv(p, index_col=0, parse_dates=True)
        print(f"{c:<6s} {rapor(d, tf)}")


def venue_fark(coin: str) -> None:
    """VARSAYMA, ÖLÇ: Binance ile MEXC aynı şeyi mi gösteriyor?
    Binance 5dk → 1h'a indirgenip MEXC 1h önbelleğiyle ÖRTÜŞEN pencerede kıyaslanır."""
    import mtf
    pb = yol(coin, "5m")
    pm = os.path.join(CACHE, f"{coin}_fut_1h.csv")
    if not os.path.exists(pb):
        print(f"✗ {pb} yok — önce Binance verisini çek."); return
    if not os.path.exists(pm):
        print(f"✗ {pm} yok — MEXC 1h önbelleği gerekli."); return
    b5 = pd.read_csv(pb, index_col=0, parse_dates=True)
    b1 = mtf.resample_tf(b5, "1h")
    mx = pd.read_csv(pm, index_col=0, parse_dates=True)
    if mx.index.tz is None:
        mx.index = mx.index.tz_localize("UTC")
    ort = b1.index.intersection(mx.index)
    if len(ort) < 500:
        print(f"✗ örtüşen pencere çok kısa ({len(ort)} bar)."); return
    bb, mm = b1.loc[ort, "close"].values, mx.loc[ort, "close"].values
    d_bp = (bb - mm) / mm * 10000.0
    rb = np.diff(np.log(bb))
    rm = np.diff(np.log(mm))
    print(f"\n=== VENUE FARKI: {coin} — Binance vs MEXC, {len(ort)} saatlik bar ===")
    print(f"  pencere: {ort[0].date()} → {ort[-1].date()}")
    print(f"  kapanış farkı: ort {d_bp.mean():+.2f}bp · medyan {np.median(d_bp):+.2f}bp "
          f"· |ort| {np.abs(d_bp).mean():.2f}bp · %95 {np.percentile(np.abs(d_bp),95):.2f}bp")
    print(f"  saatlik GETİRİ korelasyonu: {np.corrcoef(rb, rm)[0,1]:.5f}")
    print(f"  getiri farkının std'si: {np.std(rb-rm)*10000:.2f}bp "
          f"(MEXC getiri std {np.std(rm)*10000:.0f}bp)")
    kor = np.corrcoef(rb, rm)[0, 1]
    print(f"\n  HÜKÜM:")
    if kor > 0.995 and np.abs(d_bp).mean() < 15:
        print(f"    ✓ İki venue pratikte AYNI seriyi gösteriyor. Binance'te bulunan")
        print(f"      bir edge MEXC'te de var olmalı. KEŞİF için kullanılabilir.")
    elif kor > 0.98:
        print(f"    ~ Yüksek ama mükemmel değil. Keşif için yeterli; wick/likidite")
        print(f"      farkı sweep-tipi stratejileri ETKİLER (fitiller venue'ye özgü).")
        print(f"      Karar öncesi MEXC doğrulaması ZORUNLU.")
    else:
        print(f"    ⛔ Korelasyon düşük ({kor:.4f}). Binance verisiyle yapılan")
        print(f"      araştırma MEXC'e taşınamaz. Bu yolu KULLANMA.")
    print(f"\n  ⚠ Bu kıyas 1 SAATLİK kapanışlar üzerinde. Liquidity-sweep stratejisi")
    print(f"    FİTİLLERE bakıyor ve fitiller venue'ye çok daha duyarlıdır —")
    print(f"    korelasyon yüksek çıksa bile sweep sayısı iki borsada farklı olabilir.")


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--venue-fark" in sys.argv:
        venue_fark(argv[0] if argv else "SOL"); return
    tf = next((a for a in argv if a in ADIM), "5m")
    if "--durum" in sys.argv:
        durum(tf); return
    tarih = [a for a in argv if "-" in a and len(a) == 7]
    bugun = date.today()
    bas = tarih[0] if tarih else f"{bugun.year-3}-{bugun.month:02d}"
    son = tarih[1] if len(tarih) > 1 else f"{bugun.year}-{bugun.month:02d}"
    coins = [a for a in argv if a in COINS] or COINS
    os.makedirs(CACHE, exist_ok=True)
    print(f"=== BINANCE VADELİ (USDⓈ-M) {tf} · {bas} → {son} · {len(coins)} coin ===")
    print(f"  ⚠ ARAŞTIRMA verisi. Karar MEXC'te doğrulanmadan verilmez.")
    print(f"  ⚠ dosya adı '_bnc_' — MEXC önbelleği '_fut_' ile KARIŞMASIN diye")
    t0 = time.time()
    for i, c in enumerate(coins, 1):
        p = yol(c, tf)
        if os.path.exists(p):
            d = pd.read_csv(p, index_col=0, parse_dates=True)
            print(f"[{i}/{len(coins)}] {c:<5s} zaten var — {rapor(d, tf)}")
            continue
        print(f"[{i}/{len(coins)}] {c:<5s} indiriliyor...", end="", flush=True)
        m = cek(c, tf, bas, son)
        if m is None or len(m) < 1000:
            print(f" ✗ veri gelmedi")
            continue
        m.to_csv(p)
        print(f" ✓ {rapor(m, tf)}")
    print(f"\n  toplam {time.time()-t0:.0f} sn")
    print(f"\n  SONRAKİ: python3 veri_binance.py --venue-fark SOL")
    print(f"  ('çok fark olmaz' bir HİPOTEZ — o komut onu sınar)")


if __name__ == "__main__":
    main()
