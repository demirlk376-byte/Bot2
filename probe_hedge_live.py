"""
probe_hedge_live.py — TEK CEVAPSIZ SORUYU KESİN OLARAK YANITLAR: ters emir ikinci pozisyon
mu açar, yoksa mevcut pozisyonu mu kapatır?

⚠️ BU BETİK GERÇEK EMİR GÖNDERİR. Diğer yoklamalar (probe_hedge, probe_hedge2) salt okunurdu;
bu DEĞİL. Ama maliyeti ~1 sent ve tasarımı bot'a dokunmayacak şekilde kurgulandı.

NEDEN GEREKLİ: probe_hedge2 iki şeyi kesinleştirdi —
  · hesap ZATEN hedge modda (data:'1'),
  · ama exchange.py MEXC'e pozisyon YÖNÜ göndermiyor (order_params = {openType, ...}).
Bu ikisi birleşince cevaplanamayan bir soru kalıyor: açık bir LONG varken gönderilen SELL
İKİNCİ BİR SHORT MU AÇAR yoksa MEVCUT LONG'U MU KAPATIR? Bu, ccxt'in varsayılan davranışına
bağlı ve BACKTEST'LE ÇÖZÜLEMEZ. Tek yolu gerçek bir emir göndermek.

Cevap "ikinci short açar" ise → pairs alt hesapsız mümkün, sıradaki iş paper test.
Cevap "mevcut pozisyonu kapatır" ise → pairs'i eklemek bot'un pozisyonlarını KAPATIRDI;
kod değişikliği zorunlu, alt hesap daha güvenli. Bu, canlıda öğrenilmesi FELAKET olan bir şey —
bu yüzden 1 sentlik kontrollü bir testle şimdi öğreniyoruz.

GÜVENLİK TASARIMI (hepsi zorunlu, hiçbiri opsiyonel değil):
 1. TEST SEMBOLÜ BOT'UN EVRENİNDE OLAMAZ. Bot: donchian(SOL,ETH,ADA,NEAR,BCH,ICP,BNB) +
    squeeze(XRP,DOGE,TRX,XLM) + bb(LTC). Test için LINK kullanılır — bot ona HİÇ dokunmaz,
    dolayısıyla test bot'un hiçbir pozisyonuyla etkileşemez.
 2. BOYUT: 1 kontrat (minimum). LINK için ~$1-2 nominal, 10x'te ~$0.15 marjin.
 3. ÖN KONTROL: test sembolünde ZATEN pozisyon varsa betik ÇALIŞMAZ (beklenmedik durum).
 4. TEMİZLİK: finally bloğunda kalan HER pozisyon reduceOnly ile kapatılır; kapanmazsa
    EKRANA BÜYÜK UYARI basılır ve elle kapatma komutu verilir.
 5. ONAY: --evet bayrağı olmadan HİÇBİR EMİR gönderilmez (varsayılan: kuru çalışma).

Kullanım:
    python3 probe_hedge_live.py            # KURU ÇALIŞMA - ne yapacağını anlatır, emir YOK
    python3 probe_hedge_live.py --evet     # gerçek test (~1 sent)
"""
import asyncio
import os
import sys

TEST_SYMBOL = "LINK/USDT:USDT"      # bot'un evreninde YOK — çakışma imkânsız
BOT_UNIVERSE = {"SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB",
                "XRP", "DOGE", "TRX", "XLM", "LTC"}


def line(c="-", n=76):
    print(c * n)


async def pos_of(ex, symbol):
    """Sembolün AÇIK pozisyonlarını döndür. Hedge modda birden fazla olabilir."""
    try:
        ps = await ex.fetch_positions([symbol])
    except Exception:
        ps = await ex.fetch_positions()
    out = []
    for p in ps:
        if p.get("symbol") != symbol:
            continue
        c = p.get("contracts") or 0
        if c and float(c) > 0:
            out.append({"side": p.get("side"), "contracts": float(c),
                        "entry": p.get("entryPrice"), "id": p.get("id")})
    return out


def show_pos(tag, ps):
    if not ps:
        print(f"    {tag}: (pozisyon yok)")
        return
    for p in ps:
        print(f"    {tag}: {p['side']:>5s} · {p['contracts']} kontrat · giriş {p['entry']}")


async def main():
    do_it = "--evet" in sys.argv
    line("=")
    print("HEDGE YÖNLENDİRME TESTİ — ters emir ikinci pozisyon mu açar?")
    line("=")
    if not do_it:
        print("\n🔸 KURU ÇALIŞMA (emir GÖNDERİLMEYECEK). Gerçek test için: --evet\n")

    base = TEST_SYMBOL.split("/")[0]
    if base in BOT_UNIVERSE:
        print(f"⛔ GÜVENLİK DURDURMASI: {base} bot'un evreninde. Test sembolü değiştirilmeli.")
        return

    print(f"PLAN:")
    print(f"  test sembolü : {TEST_SYMBOL}  ({base} bot'un evreninde YOK ✓)")
    print(f"  1) {base}'te pozisyon var mı bak — VARSA DUR")
    print(f"  2) 1 kontrat LONG aç")
    print(f"  3) pozisyonu oku (long görünmeli)")
    print(f"  4) 1 kontrat SELL gönder  ← ASIL SORU BURADA")
    print(f"  5) pozisyonu tekrar oku:")
    print(f"       short pozisyon VARSA  → HEDGE yönlendirme ✓ pairs mümkün")
    print(f"       pozisyon YOKSA        → NETTED yönlendirme ✗ ters emir KAPATIYOR")
    print(f"  6) kalan her şeyi reduceOnly ile kapat (finally — hata olsa bile çalışır)")

    if not do_it:
        print(f"\nBu test bot'un HİÇBİR pozisyonuna dokunamaz ({base} bot evreninde değil).")
        print(f"Maliyet: 1 kontrat LINK ≈ $1-2 nominal, ücret ~1 sent.")
        print(f"\nÇalıştırmak için:  python3 probe_hedge_live.py --evet")
        return

    import ccxt.async_support as ccxt
    key = os.getenv("MEXC_API_KEY", ""); sec = os.getenv("MEXC_API_SECRET", "")
    if not key or not sec:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.getenv("MEXC_API_KEY", ""); sec = os.getenv("MEXC_API_SECRET", "")
        except Exception:
            pass
    if not key or not sec:
        print("✗ API anahtarı yok — /opt/bot2 içinde çalıştırın."); return

    ex = ccxt.mexc({"apiKey": key, "secret": sec, "enableRateLimit": True,
                    "options": {"defaultType": "swap"}})
    opened = False
    try:
        await ex.load_markets()
        m = ex.markets.get(TEST_SYMBOL)
        if not m:
            print(f"✗ {TEST_SYMBOL} piyasası bulunamadı."); return
        cs = m.get("contractSize") or 1.0
        t = await ex.fetch_ticker(TEST_SYMBOL); px = t.get("last") or 0.0
        print(f"\n  {base}: contractSize {cs} · fiyat {px:.4f} → 1 kontrat ≈ ${cs*px:.2f} nominal")

        # ── 1) ön kontrol ──
        line()
        print("[1] ÖN KONTROL")
        before = await pos_of(ex, TEST_SYMBOL)
        show_pos("mevcut", before)
        if before:
            print(f"\n⛔ DURDURULDU: {base}'te zaten pozisyon var. Beklenmedik durum —")
            print(f"   test yapılmıyor. Önce bu pozisyonu elle inceleyin.")
            return

        # ── 2) long aç ──
        line()
        print("[2] 1 kontrat LONG açılıyor…")
        o1 = await ex.create_order(TEST_SYMBOL, "market", "buy", 1, None, {"openType": 2})
        opened = True
        print(f"    emir id {o1.get('id')} · durum {o1.get('status')}")
        await asyncio.sleep(2)

        # ── 3) oku ──
        line()
        print("[3] Pozisyon okunuyor…")
        after_long = await pos_of(ex, TEST_SYMBOL)
        show_pos("açılış sonrası", after_long)
        if not after_long:
            print("    ⚠ pozisyon görünmüyor — test sonuçsuz, temizliğe geçiliyor.")
            return

        # ── 4) ASIL SORU: ters emir ──
        line()
        print("[4] 1 kontrat SELL gönderiliyor  ← ASIL SORU")
        o2 = await ex.create_order(TEST_SYMBOL, "market", "sell", 1, None, {"openType": 2})
        print(f"    emir id {o2.get('id')} · durum {o2.get('status')}")
        await asyncio.sleep(2)

        # ── 5) hüküm ──
        line()
        print("[5] SONUÇ")
        after_sell = await pos_of(ex, TEST_SYMBOL)
        show_pos("SELL sonrası", after_sell)
        shorts = [p for p in after_sell if p["side"] == "short"]
        longs = [p for p in after_sell if p["side"] == "long"]
        line("=")
        if shorts and longs:
            print("★ HEDGE YÖNLENDİRME — hem LONG hem SHORT açık.")
            print("  → ters emir İKİNCİ POZİSYON AÇIYOR. pairs alt hesapsız MÜMKÜN.")
            print("  → sıradaki iş: paper test, sonra k=0.70 ölçeğinde çok küçük canlı.")
        elif shorts and not longs:
            print("? KARIŞIK — long kapandı, short açıldı (net devir).")
            print("  → ters emir önce kapatıp sonra açmış olabilir. pairs için GÜVENLİ DEĞİL:")
            print("    bot'un pozisyonu kapanırdı. Kod değişikliği zorunlu.")
        elif not after_sell:
            print("✗ NETTED YÖNLENDİRME — pozisyon KAPANDI, short açılmadı.")
            print("  → ters emir MEVCUT POZİSYONU KAPATIYOR. pairs'i şu haliyle eklemek")
            print("    bot'un pozisyonlarını kapatırdı. Kod değişikliği ZORUNLU")
            print("    (positionSide/positionId parametresi) ya da alt hesap.")
        else:
            print("? BEKLENMEDİK durum — yukarıdaki pozisyon dökümünü bana iletin.")
        line("=")

    except Exception as e:
        print(f"\n✗ HATA: {type(e).__name__}: {e}")
    finally:
        # ── 6) TEMİZLİK — hata olsa bile ──
        try:
            line()
            print("[6] TEMİZLİK — kalan pozisyonlar kapatılıyor…")
            rest = await pos_of(ex, TEST_SYMBOL)
            show_pos("kalan", rest)
            for p in rest:
                side = "sell" if p["side"] == "long" else "buy"
                n = int(round(p["contracts"]))
                if n <= 0:
                    continue
                await ex.create_order(TEST_SYMBOL, "market", side, n, None,
                                      {"openType": 2, "reduceOnly": True})
                print(f"    kapatıldı: {p['side']} {n} kontrat")
            await asyncio.sleep(2)
            final = await pos_of(ex, TEST_SYMBOL)
            show_pos("son durum", final)
            if final:
                print("\n" + "!" * 76)
                print(f"!! DİKKAT: {base}'te HÂLÂ POZİSYON VAR. ELLE KAPATIN:")
                print(f"!! MEXC arayüzünden {base} pozisyonunu kapatın.")
                print("!" * 76)
            elif opened:
                print("    ✓ temiz — açık pozisyon kalmadı")
        except Exception as e:
            print(f"    ⚠ temizlik hatası: {type(e).__name__}: {e}")
            print(f"    {base} pozisyonunu MEXC arayüzünden ELLE kontrol edin.")
        finally:
            await ex.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nkesildi — LINK pozisyonunu MEXC'ten kontrol edin.")
        sys.exit(1)
