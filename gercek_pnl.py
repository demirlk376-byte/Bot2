"""
gercek_pnl.py — DEFTERİ BAYPAS ET: PnL'i doğrudan BORSADAN oku.

NEDEN: defter_gercek.py $56.83'lük bir boşluk buldu. Defter işlemlerden +$7.87
KÂR diyor, ama konan sermaye ($93.52 köken + $149.39 yatırım = $242.91) ile
borsadaki gerçekleşmiş equity ($193.97) arasındaki fark −$48.94 ZARAR diyor.

Üç aday vardı: (a) yatırım kaydı yanlış, (b) çıkış kayması, (c) fonlama+ücret.
(a)'yı yalnız kullanıcı doğrulayabilir. AMA (b) ve (c) DOĞRUDAN ÖLÇÜLEBİLİR —
yeter ki defter yerine BORSAYA sorulsun. Bu araç onu yapıyor.

DEFTERİN NEDEN GÜVENİLMEZ OLDUĞU (main.py:1619-1631):
    if sl_hit:   exit_price = pos.sl_price     # gerçek dolum DEĞİL
    elif tp_hit: exit_price = pos.tp_price
    raw_pnl = direction * (exit_price - pos.entry_price) * pos.quantity
Çıkışların %68'i böyle kaydediliyor. Yani defterdeki PnL büyük ölçüde
HEDEFLENEN, gerçekleşen değil.

BU ARAÇ NE OKUYOR (hepsi READ-ONLY, hiçbir emir gönderilmez):
  1. Kapanmış pozisyon geçmişi → borsanın kendi hesapladığı GERÇEKLEŞMİŞ PnL
  2. Gerçek dolumlar (fetch_my_trades) → gerçek çıkış fiyatları + gerçek ücretler
  3. Fonlama ödemeleri → defterde HİÇ tutulmayan kalem
  4. Hepsi defterle karşılaştırılır: hangi kalem farkı açıklıyor?

⚠ ccxt'nin MEXC vadeli desteği kalem kalem değişebilir. Araç HER kaynağı ayrı
  dener ve HANGİSİNİN ÇALIŞTIĞINI açıkça yazar. Çalışmayan kaynak SESSİZCE sıfır
  sayılmaz — "okunamadı" diye raporlanır ve hüküm o kadar eksik verilir.
  (Bugün defter_gercek.py'de tam bu hatayı yaptım: okunamayan uPnL'i 0 saydım.)

Kullanım (VPS'te):  cd /opt/bot2 && python3 gercek_pnl.py
                    python3 gercek_pnl.py 90        # son 90 gün
"""
import asyncio
import os
import sqlite3
import sys
import time

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))


def defter_ozet(since_ms):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, side, entry_price, exit_price, quantity, pnl_usdt,"
        " fees_usdt, entry_time, exit_time, COALESCE(exit_reason,'')"
        " FROM trades WHERE is_paper=0 AND exit_time IS NOT NULL AND exit_time<>''"
    ).fetchall()
    con.close()
    return rows


async def dene(ad, coro):
    """Bir veri kaynağını dener. Başarısızsa SESSİZ GEÇMEZ — sebebini döner."""
    try:
        r = await coro
        return True, r, None
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


async def main():
    gun = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 120
    since_ms = int((time.time() - gun * 86400) * 1000)
    print("=" * 100)
    print(f"=== GERÇEK PnL — borsadan doğrudan (son {gun} gün) ===")
    print("  Defter çıkışların %68'ini SEVİYE fiyatından kaydediyor (main.py:1619).")
    print("  Bu araç defteri baypas edip borsanın kendi kayıtlarını okuyor.")

    if not os.path.exists(DB):
        print(f"\n✗ {DB} bulunamadı."); return
    from config import load_config
    from exchange import LiveExchange
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("  PAPER modda — borsa sorgusu yok."); return

    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    syms = cfg.exchange.symbols or [cfg.exchange.symbol]
    try:
        await lx.initialize(syms[0])
    except Exception as e:
        print(f"  ⚠ initialize: {e}")
    ex = lx._exchange          # ham ccxt istemcisi

    dr = defter_ozet(since_ms)
    d_pnl = sum(float(r[5] or 0) for r in dr)
    d_fee = sum(float(r[6] or 0) for r in dr)
    print(f"\n  DEFTER: {len(dr)} kapanmış işlem · PnL ${d_pnl:+.2f} · ücret ${d_fee:.2f}")

    kaynak_ok = {}

    # ── 1) KAPANMIŞ POZİSYON GEÇMİŞİ (borsanın kendi realized PnL'i) ──
    print(f"\n{'=' * 100}\n=== [1] BORSANIN KENDİ GERÇEKLEŞMİŞ PnL'i ===")
    toplam_rpnl = None
    for ad, fn in (
        ("fetch_positions_history", lambda: ex.fetch_positions_history(syms, since_ms, None)),
        ("fetchPositionsHistory", lambda: ex.fetchPositionsHistory(syms, since_ms, None)),
    ):
        if not hasattr(ex, ad):
            print(f"  {ad:<26s} — ccxt'de YOK")
            continue
        ok, r, err = await dene(ad, fn())
        if not ok:
            print(f"  {ad:<26s} — HATA: {err}")
            continue
        try:
            vals = []
            for p in r or []:
                v = (p.get("realizedPnl") if isinstance(p, dict) else None)
                if v is None and isinstance(p, dict):
                    v = (p.get("info") or {}).get("realised") or (p.get("info") or {}).get("realized")
                if v is not None:
                    vals.append(float(v))
            print(f"  {ad:<26s} — {len(r or [])} kayıt, PnL alanı okunan {len(vals)}")
            if vals:
                toplam_rpnl = sum(vals)
                kaynak_ok["realized"] = ad
                print(f"      → BORSA GERÇEKLEŞMİŞ PnL: ${toplam_rpnl:+.2f}")
        except Exception as e:
            print(f"  {ad:<26s} — ayrıştırılamadı: {e}")
    if toplam_rpnl is None:
        # YEDEK: MEXC'in kendi kontrat uç noktası. ccxt bunu "implicit method"
        # olarak açar; isimlendirme sürümden sürüme değişebildiği için birkaç
        # aday denenir. Bu uç nokta kapanmış pozisyonun realised PnL'ini verir.
        adaylar = [a for a in dir(ex)
                   if "istory" in a and "osition" in a and a.lower().startswith("contract")]
        for ad in adaylar[:4]:
            ok, r, err = await dene(ad, getattr(ex, ad)({"page_size": 100}))
            if not ok:
                print(f"  {ad:<40s} — HATA: {err}")
                continue
            try:
                data = (r or {}).get("data") or []
                vals = [float(x.get("realised") or x.get("realized") or 0.0)
                        for x in data if isinstance(x, dict)]
                print(f"  {ad:<40s} — {len(data)} kayıt")
                if vals:
                    toplam_rpnl = sum(vals)
                    kaynak_ok["realized"] = ad
                    print(f"      → BORSA GERÇEKLEŞMİŞ PnL: ${toplam_rpnl:+.2f}")
                    break
            except Exception as e:
                print(f"  {ad:<40s} — ayrıştırılamadı: {e}")
        if not adaylar:
            print("  (MEXC kontrat geçmiş uç noktası ccxt'de bulunamadı)")
    if toplam_rpnl is None:
        print("  ⚠ Borsa realized PnL OKUNAMADI — bu kalem eksik kalıyor.")

    # ── 2) GERÇEK DOLUMLAR ──
    print(f"\n{'=' * 100}\n=== [2] GERÇEK DOLUMLAR (fetch_my_trades) — gerçek ücret + çıkış fiyatı ===")
    fills = []
    if hasattr(ex, "fetch_my_trades"):
        for s in syms:
            ok, r, err = await dene("fetch_my_trades", ex.fetch_my_trades(s, since_ms, 200))
            if not ok:
                print(f"  {s:<18s} — HATA: {err}")
                continue
            fills += list(r or [])
            await asyncio.sleep(0.25)
        if fills:
            kaynak_ok["fills"] = "fetch_my_trades"
            ucret = 0.0
            for f in fills:
                fee = f.get("fee") or {}
                try:
                    ucret += float(fee.get("cost") or 0.0)
                except (TypeError, ValueError):
                    pass
            print(f"  {len(fills)} dolum okundu · GERÇEK toplam ücret ${ucret:.4f}")
            print(f"  defterdeki ücret ${d_fee:.4f} → fark ${ucret - d_fee:+.4f}")
        else:
            print("  ⚠ Hiç dolum okunamadı.")
    else:
        print("  fetch_my_trades — ccxt'de YOK")

    # ── 3) FONLAMA — defterde HİÇ tutulmuyor ──
    print(f"\n{'=' * 100}\n=== [3] FONLAMA ÖDEMELERİ — defterde HİÇ kalemi yok ===")
    fon = None
    if hasattr(ex, "fetch_funding_history"):
        tot = 0.0
        n = 0
        hata = 0
        for s in syms:
            ok, r, err = await dene("fetch_funding_history",
                                    ex.fetch_funding_history(s, since_ms, 200))
            if not ok:
                hata += 1
                continue
            for x in r or []:
                try:
                    tot += float(x.get("amount") or 0.0); n += 1
                except (TypeError, ValueError):
                    pass
            await asyncio.sleep(0.25)
        if n or hata < len(syms):
            fon = tot
            kaynak_ok["funding"] = "fetch_funding_history"
            print(f"  {n} fonlama kaydı · TOPLAM ${tot:+.2f}"
                  f"{f'  ({hata} sembolde hata)' if hata else ''}")
        else:
            print(f"  ⚠ Fonlama okunamadı ({hata}/{len(syms)} sembolde hata).")
    else:
        print("  fetch_funding_history — ccxt'de YOK")

    try:
        await lx.close()
    except Exception:
        pass

    # ── HÜKÜM ──
    print(f"\n{'=' * 100}\n=== HÜKÜM ===")
    print(f"  okunabilen kaynaklar: {kaynak_ok or 'HİÇBİRİ'}")
    if toplam_rpnl is not None:
        fark = toplam_rpnl - d_pnl
        print(f"\n  BORSA gerçekleşmiş PnL : ${toplam_rpnl:+.2f}")
        print(f"  DEFTER PnL             : ${d_pnl:+.2f}")
        print(f"  FARK                   : ${fark:+.2f}")
        if fark < -1.0:
            print(f"\n  ⛔ DEFTER KÂRI OLDUĞUNDAN İYİ GÖSTERİYOR (${abs(fark):.2f}).")
            print(f"     Sebep main.py:1619: çıkışlar seviye fiyatından kaydediliyor,")
            print(f"     gerçek dolum stop'un ALTINDA oluyor. Düzeltilmeli.")
        elif abs(fark) <= 1.0:
            print(f"\n  ✓ Defter ile borsa uyuşuyor → çıkış kayması DOLAR olarak")
            print(f"    önemsiz. O halde defter_gercek'teki $56.83 boşluğun sebebi")
            print(f"    ÇIKIŞ KAYMASI DEĞİL → en güçlü aday YATIRIM KAYDI.")
    else:
        print(f"\n  Borsa realized PnL okunamadığı için defterle kıyas YAPILAMADI.")
    if fon is not None:
        print(f"\n  FONLAMA ${fon:+.2f} — defterde hiç yok, doğrudan boşluğa gider.")
        if abs(fon) > 5:
            print(f"    Bu, $56.83'ün ~%{abs(fon)/56.83*100:.0f}'ini açıklıyor.")
    print(f"\n  ⚠ Okunamayan her kaynak boşluğu AÇIKLANMAMIŞ bırakır — sessizce")
    print(f"    sıfır SAYILMADI. Yukarıda hangisinin okunduğu yazıyor.")
    print(f"\n  SENİN DOĞRULAMAN GEREKEN (araç bunu bilemez):")
    print(f"    2026-06-18'den bugüne MEXC'e GERÇEKTEN ne kadar para yatırdın?")
    print(f"    Defter $149.39 diyor. MEXC → Varlıklar → Para Yatırma geçmişinden bak.")
    print(f"    Rakam tutmuyorsa boşluğun kaynağı budur, kaçak değil.")


if __name__ == "__main__":
    asyncio.run(main())
