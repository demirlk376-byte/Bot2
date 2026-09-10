"""
dolum_tani.py — fetch_close_fill() NEDEN hiç çalışmadı? (VPS'te koşar)

BULGU (2026-09-10): `journalctl | grep -c "GERÇEK dolum"` → **0**.
Fonksiyon 30 günde bir kez bile başarılı olmamış. Sonuç: defter her SL
çıkışını tam stop seviyesinden yazıyor (kayma görünmez), çıkış ücretini 1bp
sabit varsayıyor, ve GÜNLÜK ZARAR FRENİ bu defteri okuyor.

Dört ihtimal var ve dördü de AYRI şeyler. Tahmin etmiyoruz, sırayla eliyoruz:
  1. Kod VPS'te yok (git pull yapılmadı)
  2. Kod var ama SÜREÇ eski (git pull ≠ systemctl restart — süreç eski kodu koşar)
  3. ccxt-MEXC `fetch_my_trades`'i swap için desteklemiyor
  4. Destekliyor ama boş dönüyor (yanlış parametre / yetki / zaman penceresi)

⚠ 3 ve 4'ün ayrımı önemli: 3 ise bu yol KAPALI ve çıkış kaymasını başka türlü
   ölçmek gerekir; 4 ise düzeltilebilir bir çağrı hatasıdır.

Kullanım (VPS'te):  cd /opt/bot2 && python3 dolum_tani.py
"""
import asyncio
import os
import subprocess
import sys

BOT_DIR = os.path.dirname(os.path.abspath(__file__))


def _env():
    try:
        with open(os.path.join(BOT_DIR, ".env"), encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                if s.startswith("export "):
                    s = s[7:].lstrip()
                k, v = s.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                os.environ[k.strip()] = v
    except FileNotFoundError:
        print("✗ .env yok"); sys.exit(2)


def _sh(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception as e:
        return f"(okunamadı: {e})"


async def main():
    print(f"\n{'=' * 78}\n=== fetch_close_fill TEŞHİSİ ===\n")

    # ── 1. Kod var mı ──
    print("  [1] KOD VPS'TE VAR MI")
    try:
        src = open(os.path.join(BOT_DIR, "exchange.py"), encoding="utf-8").read()
    except OSError as e:
        print(f"      ✗ exchange.py okunamadı: {e}"); sys.exit(2)
    var = "async def fetch_close_fill" in src
    print(f"      exchange.py içinde fetch_close_fill: {'✓ VAR' if var else '✗ YOK'}")
    if not var:
        print(f"      → git pull yapılmamış. Çözüm: git pull && systemctl restart btc-bot")
        sys.exit(2)
    print(f"      son commit: {_sh('git','-C',BOT_DIR,'log','-1','--format=%h %ad %s','--date=short')}")

    # ── 2. Süreç güncel mi ──
    print(f"\n  [2] ÇALIŞAN SÜREÇ BU KODU MU KOŞUYOR")
    st = _sh("systemctl", "show", "btc-bot", "--property=ActiveEnterTimestamp")
    mt = _sh("date", "-u", "-r", os.path.join(BOT_DIR, "exchange.py"),
             "+%a %Y-%m-%d %H:%M:%S UTC")
    print(f"      exchange.py değişiklik : {mt}")
    print(f"      {st}")
    print(f"      ⚠ ActiveEnterTimestamp, dosya değişikliğinden SONRA olmalı.")
    print(f"        ÖNCE ise süreç ESKİ kodu koşuyor — 'git pull' servisi yeniden")
    print(f"        BAŞLATMAZ. Tek başına en olası sebep budur.")

    # ── 3-4. ccxt gerçekten ne yapıyor ──
    print(f"\n  [3] ccxt-MEXC fetch_my_trades DESTEKLİYOR MU — GERÇEK ÇAĞRI")
    _env()
    try:
        import ccxt.async_support as ccxt
    except ImportError as e:
        print(f"      ✗ ccxt yok: {e}"); sys.exit(2)
    ex = ccxt.mexc({
        "apiKey": os.environ.get("MEXC_API_KEY", ""),
        "secret": os.environ.get("MEXC_API_SECRET", ""),
        "options": {"defaultType": "swap"}, "enableRateLimit": True, "timeout": 30000,
    })
    try:
        print(f"      has['fetchMyTrades'] = {ex.has.get('fetchMyTrades')}")
        import time
        since = int(time.time() * 1000) - 30 * 24 * 3600 * 1000
        for sym in ("SOL/USDT:USDT", "XRP/USDT:USDT"):
            try:
                fills = await ex.fetch_my_trades(sym, since, 50)
                print(f"      {sym:<16s} → {len(fills)} dolum döndü")
                if fills:
                    f = fills[-1]
                    print(f"        son: {f.get('datetime')} · fiyat {f.get('price')} · "
                          f"miktar {f.get('amount')} · ücret {f.get('fee')}")
            except Exception as e:
                print(f"      {sym:<16s} → ✗ {type(e).__name__}: {str(e)[:110]}")
    finally:
        await ex.close()

    print(f"\n  {'—' * 70}\n  NASIL OKUNMALI")
    print(f"    · [2]'de süreç eskiyse: systemctl restart btc-bot, sonra 1-2 hafta bekle.")
    print(f"    · [3]'te NotSupported/hata varsa: bu yol KAPALI, çıkış kayması")
    print(f"      borsadan ayrı çekilmeli (ya da MEXC web arayüzünden dışa aktarılmalı).")
    print(f"    · [3]'te dolum DÖNÜYORSA: fonksiyon çalışabilirdi, çağrı yerinde bir")
    print(f"      hata var — o zaman exchange.py:728-740 incelenmeli.")
    print(f"{'=' * 78}\n")


if __name__ == "__main__":
    asyncio.run(main())
