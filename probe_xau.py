"""
probe_xau.py — XAU (altın) MEXC'te var mı, işlenebilir mi? SALT OKUNUR yoklama.

NEDEN BU SORU YAPISAL OLARAK ÖNEMLİ:
Bugün sekiz eksen reddedildi ve HEPSİ aynı sebeple: kripto eklemek EŞZAMANLI KORELE
MARUZİYETİ artırıyor, en kötü ay çöküyor (coin ekleme −%58.7, fonlama tavanı −%59.0,
aralık kolu −%84.1 — üç BAĞIMSIZ mekanizma, aynı büyüklükte çöküş). Portföyün TEK bir
risk faktörü var: korele kripto maruziyeti.

ALTIN O FAKTÖRÜN DIŞINDA. Kriptoyla korelasyonu ~0 (risk-off dönemlerde bazen NEGATİF).
Yani bugün aradığımız ama kripto evreninde bulamadığımız şey tam olarak bu olabilir.

VE EDGE'İN ÖN-BİLGİSİ ÇOK DAHA GÜÇLÜ: donchian + ATR stop, birebir Turtle sistemidir ve
1970'lerden beri emtia trendlerinde belgelenmiş bir risk primidir. Bu, bizim in-sample
keşfettiğimiz bir şey DEĞİL — dışarıda, bizden bağımsız, on yıllardır ölçülmüş bir olgu.
Bugün test ettiğim her şeyden farkı bu: prior'ı bizim verimizden gelmiyor.

AMA ÖNCE DÖRT ŞEY DOĞRULANMALI — hepsi bu betikte, hiçbiri varsayım değil:
 1. MEXC gerçekten listeliyor mu, hangi sembol adıyla?
 2. GEÇMİŞ DERİNLİĞİ — bizim yöntemimiz TRAIN/TEST ayrımı istiyor. 1 yıllık veriyle
    hiçbir şey söylenemez. Kaç bar var?
 3. SPREAD ve LİKİDİTE — kriptoda ölçtüğümüz kayma 13.4 bp. İnce bir sentetik altın
    perp'inde 50+ bp olabilir ve edge'i tamamen yer.
 4. FONLAMA — sentetik emtia perp'inde fonlama yapısal olarak tek yönlü olabilir
    (long'lar sürekli öder). Bu, uzun tutan bir trend kolunu öldürür.

AYRICA ÖLÇÜLÜYOR — VOLATİLİTE UYUMSUZLUĞU (bizim sizing'imizi bozar):
Kripto SL%'si tipik %3-6 → nominal = risk/SL% ≈ 0.4-0.75× bakiye.
Altın vol'ü çok daha düşük; 2×ATR stop belki %1 → nominal 2.25× bakiye İSTENİR ama
CAP=1.25 kesecek → efektif risk %2.25 yerine ~%1.25'e düşer, getiri oransal azalır.
Bu ölümcül değil ama BEKLENTİYİ doğru kurmak için ölçülmesi şart.

Kullanım (VPS'te):  cd /opt/bot2 && python3 probe_xau.py
"""
import sys

ARANAN = ["XAU", "GOLD", "PAXG", "XAG", "SILVER", "WTI", "OIL", "BRENT",
          "SPX", "NDX", "DXY", "EUR", "USOIL"]


def main():
    try:
        import ccxt
    except Exception as e:
        print(f"✗ ccxt yok: {e}"); return

    print("=" * 88)
    print("XAU / EMTİA YOKLAMASI — MEXC (salt okunur, API anahtarı gerekmez)")
    print("=" * 88)

    ex = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    try:
        ex.load_markets()
    except Exception as e:
        print(f"✗ piyasalar yüklenemedi: {e}"); return

    # ── 1) hangi semboller var ──
    hits = []
    for sym, m in ex.markets.items():
        base = str(m.get("base") or "").upper()
        if any(k in base for k in ARANAN) or any(k in sym.upper() for k in ARANAN):
            hits.append((sym, m))
    print(f"\n[1] EŞLEŞEN SEMBOLLER ({len(hits)} adet)")
    if not hits:
        print("    ✗ MEXC swap evreninde altın/emtia benzeri sembol YOK.")
        print("      → Bu borsada XAU işlenemez. Alternatif: PAXG (altın-teminatlı token,")
        print("        spot'ta olabilir ama kaldıraçsız) ya da BAŞKA BİR BORSA gerekir.")
    for sym, m in sorted(hits)[:40]:
        t = m.get("type"); lin = m.get("linear"); cs = m.get("contractSize")
        act = m.get("active")
        print(f"    {sym:<24s} tip {str(t):<6s} contractSize {str(cs):<8s} aktif {act}")

    # spot tarafına da bak (PAXG gibi altın tokenleri orada olur)
    try:
        ex2 = ccxt.mexc({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        ex2.load_markets()
        sp = [s for s in ex2.markets if any(k in s.upper() for k in ("XAU", "PAXG", "GOLD"))]
        print(f"\n    SPOT tarafı: {sp[:20] if sp else 'eşleşme yok'}")
        ex2.close()
    except Exception as e:
        print(f"    spot bakılamadı: {e}")

    if not hits:
        print("\n" + "=" * 88); return

    # ── 2-4) her aday için derinlik / spread / fonlama ──
    print(f"\n[2-4] ADAYLARIN DETAYI (geçmiş derinliği · spread · fonlama)")
    for sym, m in sorted(hits)[:8]:
        print(f"\n  ── {sym} ──")
        # geçmiş derinliği
        try:
            o = ex.fetch_ohlcv(sym, "1d", limit=1500)
            if o:
                import datetime as dt
                ilk = dt.datetime.utcfromtimestamp(o[0][0] / 1000).date()
                son = dt.datetime.utcfromtimestamp(o[-1][0] / 1000).date()
                gun = (son - ilk).days
                print(f"     geçmiş: {len(o)} günlük bar · {ilk} → {son} ({gun} gün, "
                      f"{gun/365:.1f} yıl)")
                if gun < 730:
                    print(f"     ⚠ 2 YILDAN AZ — TRAIN/TEST ayrımı yapılamaz, yöntemimiz uygulanamaz")
                elif gun < 1095:
                    print(f"     ~ 2-3 yıl — sınırda; TEST dönemi çok kısa kalır")
                else:
                    print(f"     ✓ yeterli derinlik")
            else:
                print("     ✗ OHLCV boş")
        except Exception as e:
            print(f"     geçmiş alınamadı: {type(e).__name__}: {str(e)[:100]}")
        # spread
        try:
            ob = ex.fetch_order_book(sym, limit=5)
            if ob["bids"] and ob["asks"]:
                bid, ask = ob["bids"][0][0], ob["asks"][0][0]
                bp = (ask - bid) / ((ask + bid) / 2) * 1e4
                print(f"     spread: {bp:.1f} bp  (kripto kaymamız 13.4 bp)"
                      + ("   ⚠ ÇOK GENİŞ — edge'i yer" if bp > 25 else
                         "   ✓ makul" if bp < 10 else "   ~ sınırda"))
                print(f"     derinlik ilk kademe: bid {ob['bids'][0][1]} / ask {ob['asks'][0][1]}")
        except Exception as e:
            print(f"     order book alınamadı: {str(e)[:80]}")
        # hacim + fonlama
        try:
            t = ex.fetch_ticker(sym)
            print(f"     24s hacim: {t.get('quoteVolume')} · son {t.get('last')}")
        except Exception as e:
            print(f"     ticker alınamadı: {str(e)[:60]}")
        try:
            fr = ex.fetch_funding_rate(sym)
            r = fr.get("fundingRate")
            if r is not None:
                print(f"     fonlama: {r*100:.4f}% /8sa → yıllık ~{r*3*365*100:.1f}%"
                      + ("   ⚠ long'lar için ağır" if r*3*365 > 0.15 else ""))
        except Exception as e:
            print(f"     fonlama alınamadı: {str(e)[:60]}")

    print(f"\n{'=' * 88}")
    print("KARAR AĞACI:")
    print("  sembol YOK              → MEXC'te olmaz; başka borsa/enstrüman araştırılmalı")
    print("  geçmiş <2 yıl           → yöntemimiz (TRAIN/TEST) uygulanamaz; kağıt üzerinde izle")
    print("  spread >25 bp           → kripto kaymasının 2 katı; edge büyük ihtimalle yenir")
    print("  fonlama yıllık >%15     → uzun tutan trend kolu için ağır yük")
    print("  hepsi temizse           → 88 hücreli yöntemi altına uygula, korelasyonu ölç")
    print("=" * 88)
    try:
        ex.close()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}"); sys.exit(1)
