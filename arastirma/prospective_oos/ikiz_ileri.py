"""
ikiz_ileri.py — canlı-birebir ikizi 2026-07-19 SONRASI veriyle devam ettirip işlem listesi üretir.

HENÜZ ÇALIŞTIRILMADI. Çevrimdışıdır: canlı süreçlere, .env'e, emirlere dokunmaz; ikizin
PaperExchange'i ağ erişimi kapalı çalışır. Production kodu DEĞİŞTİRMEZ; yalnız
fast_bt.CACHE_DIR'i bu süreç içinde ayrı bir veri dizinine yönlendirir.

Önkoşul: --veri dizini = dondurulmuş data/{COIN}_fut_1h.csv satırları + 2026-07-19 sonrası
yeni 1h barlar (MEXC futures). data/ klasörü DEĞİŞTİRİLMEZ (araştırma tabanı).

Kullanım (repo kökünden):
  python3 arastirma/prospective_oos/ikiz_ileri.py --veri <genisletilmis_veri> \
      --db /tmp/ikiz_ileri.db --cikti /tmp/ikiz_ileri_islemler.csv

Çıktılar: işlem CSV'si (açık + kapanmış) ve yanında <cikti>.sureklilik.json.
Süreklilik PASS değilse prospective_oos.py defteri GÜNCELLEMEZ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys

import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOK)
COINLER = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC", "BTC"]
DONDURULMUS_SON = pd.Timestamp("2026-07-19", tz="UTC")     # 936 işlemlik referans koşunun bitişi
MALIYET = {"PAPER_SLIP_GIRIS_BP": "15.85", "PAPER_SLIP_CIKIS_BP": "0.24", "PAPER_FUNDING": "true"}


def veri_surekliligi(veri):
    """Yeni dizindeki satırlar, dondurulmuş data/ satırlarını AYNEN içermeli."""
    sorun = []
    for c in COINLER:
        eski = pd.read_csv(os.path.join(KOK, "data", f"{c}_fut_1h.csv"))
        yeni = pd.read_csv(os.path.join(veri, f"{c}_fut_1h.csv"))
        bas = yeni.head(len(eski)).reset_index(drop=True)
        if len(yeni) < len(eski) or not bas[eski.columns].equals(eski[eski.columns]):
            sorun.append(c)
    return sorun


async def kos(veri, bitis):
    import fast_bt
    fast_bt.CACHE_DIR = veri                     # yalnız bu süreçte; data/ okunmaz/yazılmaz
    from ikiz.kos import kur, sur
    M, saat, feed = await kur("2023-04-06", source="local")
    await sur(M, saat, feed, bitis=bitis, ilerleme_her=20000)


def disa_aktar(db, cikti):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    d = pd.read_sql("SELECT symbol, side, entry_price, exit_price, sl_price, quantity, entry_time, exit_time, "
                    "pnl_usdt, exit_reason, strategy_scores FROM trades", c)
    c.close()
    d["kol"] = d.strategy_scores.map(lambda s: (json.loads(s or "{}") or {}).get("strategy", "?"))
    d.to_csv(cikti, index=False)
    return d


def islem_surekliligi(d):
    ref = pd.read_csv(os.path.join(KOK, "ikiz_k25_cap25_islemler.csv"))
    k = ["symbol", "side", "entry_time"]
    m = ref.merge(d[d.exit_time.notna()], on=k, how="left", suffixes=("", "_yeni"))
    ayni = (m.exit_time == m.exit_time_yeni) & ((m.pnl_usdt - m.pnl_usdt_yeni).abs() < 1e-6)
    return dict(referans=len(ref), birebir=int(ayni.sum()),
                sonuc="PASS" if int(ayni.sum()) == len(ref) == 936 else "FAIL")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--veri", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--cikti", required=True)
    a = ap.parse_args()
    if os.path.abspath(a.veri) == os.path.abspath(os.path.join(KOK, "data")):
        raise SystemExit("--veri dondurulmuş data/ olamaz; genişletilmiş kopya kullan.")
    sorun = veri_surekliligi(a.veri)
    if sorun:
        raise SystemExit(f"veri sürekliliği FAIL (data/ satırları aynen yok): {sorun}")
    bitis = min(pd.read_csv(os.path.join(a.veri, f"{c}_fut_1h.csv")).ts.iloc[-1] for c in COINLER)
    for k, v in MALIYET.items():
        os.environ.setdefault(k, v)
    os.environ["REPLAY_DB"] = a.db
    if os.path.exists(a.db):
        raise SystemExit(f"{a.db} zaten var; yeni koşu için boş yol ver.")
    asyncio.run(kos(os.path.abspath(a.veri), str(pd.Timestamp(bitis).date())))
    d = disa_aktar(a.db, a.cikti)
    s = islem_surekliligi(d)
    s.update(veri_bitis=str(bitis), islem=len(d), acik=int(d.exit_time.isna().sum()))
    with open(a.cikti + ".sureklilik.json", "w") as f:
        json.dump(s, f, indent=1)
    print(json.dumps(s, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(0 if s["sonuc"] == "PASS" else 1)      # aiosqlite thread'i süreci asılı tutmasın


if __name__ == "__main__":
    main()
