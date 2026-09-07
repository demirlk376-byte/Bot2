"""
temiz_dogrula.py — "temiz dönemde gerçekten bu kadar mı kazandık?" — İKİNCİ YOL.

/status'un rakamı TEK BİR YOLDAN geliyor:
    A) temiz kâr = equity_şimdi − equity_çıpa − (sermaye_şimdi − sermaye_çıpa)
Bu yol iki girdiye dayanıyor: `daily_stats.starting_balance` (botun KENDİ
yazdığı anlık görüntü) ve borsanın transfer kaydı. İlki botun kendi kaydı
olduğu için bağımsız bir teyit DEĞİL.

Bu araç TAMAMEN AYRI bir yoldan aynı sayıyı üretir:
    B) temiz kâr = Σ(borsanın kendi gerçekleşmiş PnL'i, çıpadan beri)
                 + Σ(fonlama, çıpadan beri)
                 + açık pozisyonların uPnL'i
B yolu `daily_stats`'e HİÇ bakmaz. İki yol örtüşürse rakam güvenilir.
Örtüşmezse hangi bileşenin şüpheli olduğu ortaya çıkar.

⚠ Bu araç HÜKÜM VERMEZ, KARŞILAŞTIRIR. Okunamayan kaynak SIFIR sayılmaz;
   eksikse "eksik" der ve fark o kadar açıklanamamış kalır.
⚠ MEXC varlık uç noktaları 90 günle sınırlı; çıpa (2026-07-17) o pencerede
   olmalı. Değilse araç durur — uydurma yapmaz.

Kullanım (VPS'te):  venv/bin/python temiz_dogrula.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from config import load_config          # noqa: E402
from database import Database           # noqa: E402
from exchange import LiveExchange       # noqa: E402


async def dene(ad, coro):
    try:
        return True, await coro, None
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


async def main():
    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")
    db = Database(cfg.db_path); await db.initialize()
    cut = await db.get_meta("temiz_cut")
    c_eq = await db.get_meta_float("temiz_equity", 0.0)
    c_sm = await db.get_meta_float("temiz_sermaye", 0.0)
    s_now = await db.get_meta_float("sermaye_taban", 0.0)
    if not s_now:
        s_now = (await db.get_meta_float("inception_balance", 0.0)
                 + await db.get_meta_float("total_deposits", 0.0))
    await db.close()
    if not cut or c_eq <= 0 or c_sm <= 0:
        raise SystemExit("⛔ Çıpa kurulmamış (temiz_donem.py --yaz). Karşılaştırma YOK.")

    cut_dt = datetime.strptime(str(cut), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cut_ms = int(cut_dt.timestamp() * 1000)
    gun = (time.time() * 1000 - cut_ms) / 86400000
    print("=" * 74)
    print(f"TEMİZ DÖNEM DOĞRULAMASI — iki bağımsız yol ({cut} sonrası, {gun:.0f} gün)")
    print("=" * 74)
    if gun > 89:
        print(f"  ⛔ Çıpa {gun:.0f} gün önce; MEXC varlık uç noktaları 90 günle")
        print(f"     sınırlı. B yolu EKSİK olur — karşılaştırma yapılmıyor.")
        raise SystemExit(2)

    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await lx.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"  (initialize uyarısı: {e})")
    try:
        ex = lx._exchange
        eq = await lx.get_equity()

        # ── A) EQUITY FARKI YOLU (bugün /status'un kullandığı) ───────────────
        yeni_sermaye = s_now - c_sm
        A = eq - c_eq - yeni_sermaye
        print(f"\n  A) EQUITY FARKI YOLU  (daily_stats + transfer kaydı)")
        print(f"     equity şimdi     ${eq:>9,.2f}")
        print(f"     equity çıpa      ${c_eq:>9,.2f}   ({cut})")
        print(f"     çıpadan beri eklenen sermaye ${yeni_sermaye:>+9,.2f}")
        print(f"     → TEMİZ KÂR      ${A:>+9,.2f}")

        # ── B) BORSA KAYDI YOLU (daily_stats'e HİÇ bakmaz) ───────────────────
        print(f"\n  B) BORSA KAYDI YOLU  (gerçekleşmiş PnL + fonlama + uPnL)")
        eksik = []

        rpnl = None
        for ad in ("fetch_positions_history", "fetch_closed_orders"):
            if not hasattr(ex, ad):
                continue
            ok, r, err = await dene(ad, getattr(ex, ad)(None, cut_ms, 500))
            if not ok:
                print(f"     {ad:<26s} HATA: {err}")
                continue
            tot = 0.0; n = 0
            for x in (r or []):
                if not isinstance(x, dict):
                    continue
                v = (x.get("info") or {}).get("realised") or \
                    (x.get("info") or {}).get("realisedPnl") or x.get("realizedPnl")
                try:
                    tot += float(v); n += 1
                except (TypeError, ValueError):
                    pass
            if n:
                rpnl = tot
                print(f"     {ad:<26s} {n} kayıt · ${tot:+,.2f}")
                break
            print(f"     {ad:<26s} {len(r or [])} kayıt ama PnL alanı okunamadı")
        if rpnl is None:
            print(f"     ⛔ gerçekleşmiş PnL OKUNAMADI")
            eksik.append("gerçekleşmiş PnL")

        fon = 0.0; fn = 0; fhata = 0
        if hasattr(ex, "fetch_funding_history"):
            for s in cfg.exchange.symbols:
                ok, r, err = await dene("fetch_funding_history",
                                        ex.fetch_funding_history(s, cut_ms, 200))
                if not ok:
                    fhata += 1
                    continue
                for x in (r or []):
                    try:
                        fon += float(x.get("amount") or 0.0); fn += 1
                    except (TypeError, ValueError):
                        pass
                await asyncio.sleep(0.2)
            if fhata == len(cfg.exchange.symbols):
                print(f"     fonlama                    ⛔ hiç okunamadı")
                eksik.append("fonlama")
                fon = None
            else:
                print(f"     fonlama                    {fn} kayıt · ${fon:+,.2f}")
        else:
            eksik.append("fonlama"); fon = None

        upnl = 0.0
        try:
            for s in cfg.exchange.symbols:
                pz = await lx.get_position(s)
                if pz:
                    upnl += float(getattr(pz, "unrealized_pnl", 0.0) or 0.0)
            print(f"     açık uPnL                  ${upnl:+,.2f}")
        except Exception as e:
            print(f"     açık uPnL                  ⛔ okunamadı: {e}")
            eksik.append("uPnL"); upnl = None

        if eksik:
            print(f"\n  ⛔ B YOLU EKSİK: {', '.join(eksik)} okunamadı.")
            print(f"     Okunamayan kalem SIFIR SAYILMAZ → karşılaştırma YAPILMIYOR.")
            print(f"     A yolu tek başına duruyor: ${A:+,.2f}")
            return
        B = rpnl + fon + upnl
        print(f"     → TEMİZ KÂR      ${B:>+9,.2f}")

        fark = A - B
        print(f"\n{'='*74}\n  KARŞILAŞTIRMA\n{'='*74}")
        print(f"     A (equity farkı) ${A:>+9,.2f}")
        print(f"     B (borsa kaydı)  ${B:>+9,.2f}")
        print(f"     FARK             ${fark:>+9,.2f}")
        esik = max(3.0, abs(A) * 0.05)
        if abs(fark) <= esik:
            print(f"\n  ✓ İKİ BAĞIMSIZ YOL ÖRTÜŞÜYOR (eşik ${esik:.2f}).")
            print(f"    Temiz dönem kârı ${A:+,.2f} GÜVENİLİR.")
        else:
            print(f"\n  ⛔ ÖRTÜŞMÜYOR. Şüpheli bileşenler, en olasıdan başlayarak:")
            print(f"     1) equity_çıpa (${c_eq:,.2f}) — daily_stats'ten geliyor,")
            print(f"        botun kendi anlık görüntüsü. Yanlışsa A kayar.")
            print(f"     2) sermaye_çıpa (${c_sm:,.2f}) — transfer penceresi 90 günle")
            print(f"        sınırlı; daha eski transfer varsa eksik olabilir.")
            print(f"     3) borsanın PnL alanı — kayıt biçimi değişmiş olabilir.")
    finally:
        try:
            await lx.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
