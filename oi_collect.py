"""
oi_collect.py — OPEN INTEREST kaydedici. Sahte kırılım için kalan TEK veri kaynağı.

NEDEN BU, VE NEDEN ŞİMDİ:
Sahte kırılımı ayırt etmek için denenen HER ŞEY aynı kaynaktan besleniyordu — o coinin OHLCV'si.
Yani fiyatın NE YAPTIĞI. Hepsi başarısız (13 özellik çok-değişkenli OOS AUC 0.502; yapı <0.4σ;
hacim/ATR/vol-taban toplamı düşürdü; takvim 2026'da ters döndü; funding hiçbir eşikte tutmadı;
girişten sonraki 2-12 barlık erken çıkış 13/13 kaybettirdi).
Geriye tek bir bilgi TÜRÜ kalıyor: fiyatın ne yaptığı değil, POZİSYONUN kimde olduğu.
  kırılım + ARTAN OI  = yeni para geliyor      → gerçek
  kırılım + DÜŞEN OI  = pozisyon kapanıyor     → stop avı / sahte
Bu mekanizma OHLCV'de görünmez: aynı mum, aynı hacim, TERS anlam.

LEDGER'DAKİ RET EKSİK GEREKÇEYE DAYANIYORDU: "ccxt-MEXC fetchOpenInterest: False" deyip
kapatmıştık. Ama ccxt'nin yeteneği MEXC'in yeteneği DEĞİL — load_markets() timeout verdiği yerde
ham contract API çalıştı (fetch_universe.py). Bu script ham API'yi PROBE eder: OI alanı varsa
kaydeder, yoksa hangi alanların geldiğini basar (tahminle kapatmak yerine).

GEÇMİŞ OI YOK (hiçbir borsa çok-yıllık vermiyor) → tek yol İLERİYE DÖNÜK toplamak. Bugün
başlarsak 6-12 ay sonra test edilebilir bir seri olur. Maliyeti sıfır, bota dokunmuyor.

DÜRÜSTLÜK: bu BUGÜNE bir şey kazandırmaz. Bir OPSİYON yaratır. Toplanan veri 6-12 ay sonra
"kırılım anındaki OI değişimi kazananı kaybedenden ayırıyor mu" sorusunu test etmeyi mümkün kılar.
Cevap yine HAYIR olabilir — ama o zaman ölçüye dayanarak kapatırız, varsayıma değil.

Kullanım (VPS'te, systemd timer):  python3 oi_collect.py
Tek seferlik probe (alan adlarını gör):  python3 oi_collect.py --probe
Çıktı: data/oi_log.csv  (ts, symbol, oi, oi_usd, price, funding)
"""
import os, sys, csv, time
from datetime import datetime, timezone
import requests

BASE = "https://contract.mexc.com/api/v1/contract"
OUT = os.environ.get("OI_CSV", "data/oi_log.csv")
COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB", "XRP", "DOGE", "TRX", "XLM", "LTC"]
TIMEOUT = 30

# MEXC contract ticker'da OI için muhtemel alan adları. Doğrusunu PROBE belirler;
# tahmin etmiyoruz, gelen anahtarlara bakıp eşleşeni kullanıyoruz.
OI_KEYS = ("holdVol", "openInterest", "hold_vol", "oi", "positionVol")
PRICE_KEYS = ("lastPrice", "fairPrice", "indexPrice", "last")
FUND_KEYS = ("fundingRate", "funding_rate")

S = requests.Session()
S.headers.update({"User-Agent": "bot2-oi/1.0"})


def get(path, params=None, tries=3):
    last = None
    for k in range(tries):
        try:
            r = S.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            j = r.json()
            if not j.get("success", True):
                raise RuntimeError(f"success=false: {str(j)[:200]}")
            return j.get("data")
        except Exception as e:
            last = e
            if k < tries - 1: time.sleep(2 ** k)
    raise RuntimeError(f"{path} başarısız: {last}")


def pick(row, keys):
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "0", 0):
            try: return float(v)
            except (TypeError, ValueError): pass
    return None


def main():
    probe = "--probe" in sys.argv
    data = get("ticker")
    if isinstance(data, dict): data = [data]
    if not data:
        sys.exit("ticker boş döndü")

    if probe:
        print("=== ticker kaydındaki TÜM alanlar ===")
        for k, v in sorted(data[0].items()):
            print(f"  {k:<24s} = {v}")
        oi_field = next((k for k in OI_KEYS if k in data[0]), None)
        print(f"\n  OI alanı bulundu mu: {oi_field or 'HAYIR — yukarıdaki listeyi bana gönder'}")
        return

    rows = {r.get("symbol"): r for r in data if r.get("symbol")}
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    new = not os.path.exists(OUT)
    wrote = 0
    missing = []
    with open(OUT, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "symbol", "oi", "oi_usd", "price", "funding"])
        for c in COINS:
            r = rows.get(f"{c}_USDT")
            if not r:
                missing.append(c); continue
            oi = pick(r, OI_KEYS)
            px = pick(r, PRICE_KEYS)
            fr = pick(r, FUND_KEYS)
            if oi is None:
                missing.append(c); continue
            w.writerow([ts, c, oi, (oi * px) if px else "", px or "", fr if fr is not None else ""])
            wrote += 1
    print(f"{ts}  {wrote}/{len(COINS)} coin yazıldı → {OUT}")
    if missing:
        # Sessizce eksik yazmak, 6 ay sonra delik delik bir seriyle karşılaşmak demek.
        print(f"  UYARI: OI okunamadı: {', '.join(missing)}")
        print(f"  Alan adı değişmiş olabilir — 'python3 oi_collect.py --probe' çalıştırıp bana gönder.")


if __name__ == "__main__":
    main()
