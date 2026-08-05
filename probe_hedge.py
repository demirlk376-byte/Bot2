"""
probe_hedge.py — HEDGE MODE YOKLAMASI (SALT OKUNUR, hiçbir şey değiştirmez).

NEDEN: pairs, ledger'daki TEK hayatta kalan bulgu (+$532, PF 1.63, 4/4 yıl pozitif,
kitapla korelasyon −0.362, permütasyon p=0.006). Ama MEXC netted modda bir sembolde tek
net pozisyon tutuyor; bot ADA'da LONG'ken pairs ADA'yı SHORT'layamıyor — emirler netleşir.
pairs_collide.py ölçtü: aynı hesapta "çakışanı atla" politikasıyla edge'in %100'ü yok
oluyor ($+532 → $−4), çünkü çakışma tesadüfi değil YAPISAL (işlemlerin %89'u çakışıyor,
semboller zamanın yalnızca %8-31'inde meşgulken).

GERİYE TEK ALTERNATİF KALDI: MEXC ÇİFT-YÖNLÜ (hedge) POZİSYON MODU. Açıksa aynı sembolde
long ve short AYRI pozisyon olarak durur, netleşme olmaz → ALT HESABA GEREK KALMAZ.

BU BETİK HİÇBİR ŞEY DEĞİŞTİRMEZ. Emir açmaz, mod değiştirmez, kaldıraç dokunmaz.
Yalnızca ÜÇ SORUYU yanıtlar:
  1. Hesap hangi pozisyon modunda ve MEXC hedge mode'a izin veriyor mu?
  2. Kurulu ccxt sürümü MEXC için mod okuma/yazmayı destekliyor mu?
  3. Mevcut bakiyeyle 16 bacak (8 çift) için marjin yeter mi — min-notional ne?

Kullanım (VPS'te):  cd /opt/bot2 && python3 probe_hedge.py
"""
import asyncio
import os
import sys


async def main():
    print("=" * 78)
    print("HEDGE MODE YOKLAMASI — SALT OKUNUR (emir açmaz, mod değiştirmez)")
    print("=" * 78)

    # ── ccxt sürümü ve yetenekleri ──
    try:
        import ccxt.async_support as ccxt
    except Exception as e:
        print(f"✗ ccxt import edilemedi: {e}")
        return
    print(f"\n[1] ccxt sürümü: {ccxt.__version__}")

    key = os.getenv("MEXC_API_KEY", "")
    sec = os.getenv("MEXC_API_SECRET", "")
    if not key or not sec:
        # .env'den oku (bot ile aynı kaynak)
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.getenv("MEXC_API_KEY", "")
            sec = os.getenv("MEXC_API_SECRET", "")
        except Exception:
            pass
    if not key or not sec:
        print("✗ MEXC_API_KEY / MEXC_API_SECRET bulunamadı (.env okunamadı).")
        print("  /opt/bot2 dizininde çalıştırdığınızdan emin olun.")
        return
    print(f"    API anahtarı bulundu (…{key[-4:]})")

    ex = ccxt.mexc({"apiKey": key, "secret": sec, "enableRateLimit": True,
                    "options": {"defaultType": "swap"}})
    try:
        # ── 2) ccxt yetenek matrisi ──
        print(f"\n[2] ccxt'in MEXC için desteklediği mod fonksiyonları:")
        for fn in ("setPositionMode", "fetchPositionMode", "setMarginMode", "setLeverage"):
            has = ex.has.get(fn, False)
            print(f"    {fn:<20s} {'✓ var' if has else '✗ YOK'}")

        # ── 3) hesabın MEVCUT pozisyon modu ──
        print(f"\n[3] Hesabın şu anki pozisyon modu:")
        got = False
        for meth in ("contractPrivateGetPositionPositionMode",
                     "contract_private_get_position_position_mode"):
            f = getattr(ex, meth, None)
            if f is None:
                continue
            try:
                r = await f()
                print(f"    ham yanıt: {r}")
                d = r.get("data") if isinstance(r, dict) else None
                if d == 1 or d == "1":
                    print("    → 1 = HEDGE (çift yönlü)  ★ pairs alt hesap OLMADAN mümkün")
                elif d == 2 or d == "2":
                    print("    → 2 = ONE-WAY (netted)    ← şu anki durum; değiştirilebilir mi:")
                    print("      MEXC bunu AÇIK POZİSYON ve AÇIK EMİR YOKKEN değiştirmeye izin verir.")
                    print("      Değiştirme komutu BİLEREK bu betikte YOK — karar sizin.")
                got = True
                break
            except Exception as e:
                print(f"    {meth} hata: {type(e).__name__}: {str(e)[:160]}")
        if not got:
            print("    ✗ Bu ccxt sürümünde MEXC pozisyon-modu uç noktası bulunamadı.")
            print("      Bu, hedge mode'un YOK olduğu anlamına GELMEZ — ccxt'in sarmadığı")
            print("      anlamına gelir. O durumda doğrudan REST çağrısı gerekir = KOD RİSKİ.")

        # ── 4) bakiye ve min-notional ──
        print(f"\n[4] Bakiye ve 8 çift (16 bacak) için min-notional kontrolü:")
        bal = await ex.fetch_balance()
        usdt = bal.get("USDT", {})
        free = usdt.get("free") or 0.0
        total = usdt.get("total") or 0.0
        print(f"    serbest ${free:.2f} · toplam ${total:.2f}")

        await ex.load_markets()
        pairs = [("ETC", "ETH"), ("ATOM", "DOT"), ("BTC", "ETH"), ("ADA", "DOT"),
                 ("XLM", "XRP"), ("ALGO", "DOT"), ("ADA", "ALGO"), ("ADA", "ATOM")]
        syms = sorted({s for p in pairs for s in p})
        print(f"    {'sembol':>8s} {'min tutar':>12s} {'son fiyat':>12s} {'min notional$':>14s}")
        tot_min = 0.0
        for s in syms:
            m = ex.markets.get(f"{s}/USDT:USDT")
            if m is None:
                print(f"    {s:>8s} {'piyasa yok':>12s}")
                continue
            mn = (m.get("limits", {}).get("amount", {}) or {}).get("min")
            cost_min = (m.get("limits", {}).get("cost", {}) or {}).get("min")
            try:
                t = await ex.fetch_ticker(f"{s}/USDT:USDT")
                px = t.get("last") or 0.0
            except Exception:
                px = 0.0
            notional = cost_min if cost_min else ((mn or 0) * px)
            tot_min += notional or 0.0
            print(f"    {s:>8s} {str(mn):>12s} {px:>12.4f} {notional or 0:>14.2f}")
        lev = int(os.getenv("LEVERAGE", "10"))
        print(f"\n    16 bacağın toplam min NOTIONAL'i ≈ ${tot_min*2:.2f}"
              f"  (her sembol ~2 çiftte geçiyor)")
        print(f"    {lev}x kaldıraçla gereken MARJİN ≈ ${tot_min*2/lev:.2f}")
        print(f"    → mevcut serbest ${free:.2f} ile "
              f"{'YETER' if free > tot_min*2/lev else 'YETMEZ'}")
        print(f"    NOT: bu SADECE min-notional. Gerçek pozisyon boyutu risk kuralından")
        print(f"    gelir ve bundan büyüktür; ayrıca bot'un kendi 7 koltuğu da marjin yiyor.")

    finally:
        await ex.close()

    print("\n" + "=" * 78)
    print("SONUÇ NASIL OKUNUR:")
    print("  [3] HEDGE ise → pairs alt hesap olmadan mümkün, sıradaki iş exchange.py'nin")
    print("      positionSide desteği (kod değişikliği, test gerekir).")
    print("  [3] ONE-WAY ve değiştirilebilir ise → değiştirmek AÇIK POZİSYON YOKKEN yapılır;")
    print("      bot'u durdurup pozisyonları kapatmayı gerektirir. Karar sizin, ben yapmam.")
    print("  [3] uç nokta YOK ise → ccxt sarmıyor, doğrudan REST = kod riski; alt hesap daha güvenli.")
    print("  [4] YETMEZ ise → hedge mode açık olsa bile sermaye engeli devam eder.")
    print("=" * 78)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
