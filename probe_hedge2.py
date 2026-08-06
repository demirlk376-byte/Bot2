"""
probe_hedge2.py — DÜZELTİLMİŞ min-notional + hedge mode uygulanabilirlik yoklaması.
SALT OKUNUR: emir açmaz, mod değiştirmez, kaldıraç dokunmaz.

⚠️ NEDEN v2 VAR — probe_hedge.py'de BENİM HATAM:
`limits.amount.min = 1.0` MEXC vadelide "1 COIN" değil "1 KONTRAT" demektir. Ben kontrat
sayısını coin fiyatıyla çarptım ve BTC için min notional'i $64,487 gösterdim (gerçeği ~$6.45).
Bu yüzden "16 bacak $132,816 gerektirir, YETMEZ" hükmü ÇÖPTÜ. Doğrusu:
    min notional = min_kontrat × contractSize × fiyat
exchange.py bunu ZATEN doğru yapıyor (satır 502-540, `_contract_size`); hata yalnızca
yoklama betiğindeydi. Kendi aracımı kendi kuralımla denetliyorum.

[3] SONUCU (v1'den, geçerli): hesap ZATEN HEDGE MODDA (data:'1'). Yani MEXC tarafında
aynı sembolde long+short ayrı tutulabiliyor → pairs için alt hesap gerekçesinin BORSA
tarafı düştü. Geriye iki soru kaldı ve bu betik onları yanıtlıyor:
  A) Gerçek min-notional nedir, $183 yeter mi?
  B) Bot'un kodu (exchange.py) hedge modda ters yönde İKİNCİ pozisyonu açabilir mi,
     yoksa mevcut pozisyonu KAPATIR mı? (netted mantığıyla yazılmış olabilir)

(B) kritik: hesap hedge modda olsa bile, kod ters emri "kapat" olarak gönderiyorsa
pairs bot'un pozisyonunu kapatır. Bu betik kodu OKUYARAK yanıtlar, emir GÖNDERMEZ.

Kullanım (VPS'te):  cd /opt/bot2 && python3 probe_hedge2.py
"""
import asyncio
import os
import sys


async def main():
    print("=" * 78)
    print("HEDGE MODE — DÜZELTİLMİŞ YOKLAMA (salt okunur)")
    print("=" * 78)

    import ccxt.async_support as ccxt
    key = os.getenv("MEXC_API_KEY", "")
    sec = os.getenv("MEXC_API_SECRET", "")
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
    try:
        await ex.load_markets()
        bal = await ex.fetch_balance()
        free = (bal.get("USDT") or {}).get("free") or 0.0
        lev = int(os.getenv("LEVERAGE", "10"))
        print(f"\n[A] GERÇEK min-notional (kontrat büyüklüğü DAHİL)")
        print(f"    serbest bakiye ${free:.2f} · kaldıraç {lev}x\n")
        print(f"    {'sembol':>7s} {'minKontrat':>11s} {'contractSize':>13s} {'fiyat':>12s} "
              f"{'min notional$':>14s} {'min marjin$':>12s}")
        pairs = [("ETC", "ETH"), ("ATOM", "DOT"), ("BTC", "ETH"), ("ADA", "DOT"),
                 ("XLM", "XRP"), ("ALGO", "DOT"), ("ADA", "ALGO"), ("ADA", "ATOM")]
        legs = [s for p in pairs for s in p]          # 16 bacak (tekrarlı)
        per = {}
        for s in sorted(set(legs)):
            m = ex.markets.get(f"{s}/USDT:USDT")
            if not m:
                print(f"    {s:>7s} {'piyasa yok':>11s}"); continue
            mn = (m.get("limits", {}).get("amount", {}) or {}).get("min") or 1.0
            cs = m.get("contractSize") or 1.0
            try:
                t = await ex.fetch_ticker(f"{s}/USDT:USDT"); px = t.get("last") or 0.0
            except Exception:
                px = 0.0
            notional = mn * cs * px
            per[s] = notional
            print(f"    {s:>7s} {mn:>11.4g} {cs:>13.6g} {px:>12.4f} "
                  f"{notional:>14.2f} {notional/lev:>12.2f}")
        tot_not = sum(per.get(s, 0.0) for s in legs)   # 16 bacak, tekrarlı sayılır
        print(f"\n    16 bacağın toplam min NOTIONAL'i  ≈ ${tot_not:.2f}")
        print(f"    {lev}x ile gereken min MARJİN       ≈ ${tot_not/lev:.2f}")
        print(f"    → serbest ${free:.2f} ile min-notional açısından: "
              f"{'YETER ✓' if free > tot_not/lev else 'YETMEZ ✗'}")

        print(f"\n    ⚠ AMA MİN-NOTIONAL YANLIŞ SORU. Asıl soru: pairs'in +$532'yi üretmek")
        print(f"    için ihtiyaç duyduğu BOYUT. Backtest her çift işlemini ~${190:.0f} nominal")
        print(f"    ile ölçtü (2 bacak × ~$95). 8 çift aynı anda açıksa ≈ ${190*8:.0f} nominal")
        print(f"    = {lev}x ile ${190*8/lev:.0f} marjin. Bot'un kendi 7 koltuğu da marjin yiyor.")
        print(f"    Gerçek eşzamanlılık backtest'ten ölçülmeli — min-notional ALT SINIR, hedef DEĞİL.")

        # ── B) kod hedge modu destekliyor mu ──
        print(f"\n[B] KOD TARAFI — exchange.py ters yönde İKİNCİ pozisyon açabilir mi?")
        try:
            src = open("exchange.py", encoding="utf-8").read()
        except Exception as e:
            print(f"    exchange.py okunamadı: {e}"); src = ""
        # DİKKAT: düz `"positionSide" in src` YANLIŞ POZİTİF verir — exchange.py'de
        # `position_side` YEREL bir değişken adı (SL/TP yönünü hesaplamak için,
        # satır 988-1007), MEXC'e gönderilen API alanı DEĞİL. Bu yüzden emir
        # parametresi sözlüğüne GİRDİĞİ yerleri arıyoruz.
        import re
        api_ps = bool(re.search(r'["\']positionSide["\']\s*:', src))
        api_pid = bool(re.search(r'["\']positionId["\']\s*:', src))
        order_params_ps = bool(re.search(r'order_params\[[^\]]*positionSide', src))
        checks = [
            ("API alanı 'positionSide':", api_ps),
            ("API alanı 'positionId':", api_pid),
            ("order_params'a ekleniyor", order_params_ps),
            ("reduceOnly (kapatma emri)", "reduceOnly" in src),
            ("openType (izole/cross)", "openType" in src),
            ("contractSize doğru işleniyor", "_contract_size" in src),
        ]
        for lbl, ok in checks:
            print(f"    {lbl:<32s} {'✓ VAR' if ok else '✗ YOK'}")
        if not (api_ps or api_pid):
            print(f"\n    ⛔ SONUÇ: kod MEXC'e pozisyon YÖNÜ GÖNDERMİYOR → tek-yönlü (netted)")
            print(f"    varsayımıyla yazılmış. Hesap hedge modda olsa BİLE, açık bir LONG varken")
            print(f"    gönderilen SELL emrinin ikinci bir SHORT mu açacağı yoksa mevcut LONG'u mu")
            print(f"    KAPATACAĞI kodun garantisi altında DEĞİL — ccxt'in varsayılanına kalıyor.")
            print(f"    Bu, canlı pozisyonu sessizce kapatabilecek bir belirsizliktir.")
            print(f"    → pairs eklemek KOD DEĞİŞİKLİĞİ + paper test gerektirir.")
        else:
            print(f"\n    ✓ Kod pozisyon yönünü açıkça gönderiyor — hedge modda ikinci pozisyon güvenli.")

        # ── açık pozisyonlar (bilgi) ──
        print(f"\n[C] Şu an açık pozisyonlar:")
        try:
            ps = await ex.fetch_positions()
            got = [p for p in ps if (p.get("contracts") or 0) > 0]
            if not got:
                print("    (yok)")
            for p in got:
                print(f"    {p.get('symbol'):<18s} {p.get('side'):>5s} "
                      f"kontrat {p.get('contracts')} · giriş {p.get('entryPrice')} · "
                      f"uPnL {p.get('unrealizedPnl')}")
        except Exception as e:
            print(f"    okunamadı: {type(e).__name__}: {str(e)[:120]}")
    finally:
        await ex.close()

    print("\n" + "=" * 78)
    print("KARAR AĞACI:")
    print("  [A] YETER + [B] positionSide VAR  → pairs alt hesapsız mümkün, sıradaki iş paper test")
    print("  [A] YETER + [B] positionSide YOK  → kod değişikliği gerekir; alt hesap DAHA GÜVENLİ")
    print("  [A] YETMEZ                        → sermaye engeli, hedge mode fark etmez")
    print("=" * 78)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
