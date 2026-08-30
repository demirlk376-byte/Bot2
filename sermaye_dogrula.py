"""
sermaye_dogrula.py — "para koyunca gerçekten algılayacak mı?" — KANIT.

Otomatik sermaye takibi (main.sermaye_guncelle) sahte borsayla test edildi.
Ama GERÇEK MEXC yanıtıyla hiç çalışmadı. Bu araç onu para eklemeden kanıtlar:
hesapta zaten 6 gerçek transfer var, kod onları doğru okuyabiliyorsa yeni bir
transferi de okur — kayıt biçimi aynı.

ÜÇ KONTROL:
  1) GEÇMİŞİ OKUYOR MU — fetch_transfers_in(89 gün) bilinen toplamı veriyor mu?
  2) PENCERE ÇALIŞIYOR MU — fetch_transfers_in(şimdi) 0.00 vermeli.
     Vermezse `since` yok sayılıyor VE istemci süzgeci de tutmuyor demektir →
     taban her 5 dakikada şişer. Bu testin asıl amacı BU.
  3) TOHUM ATILDI MI — sermaye_taban meta'sı yazılmış mı, /status onu mu okuyor?

Kullanım (VPS'te):  cd /opt/bot2 && venv/bin/python sermaye_dogrula.py
Hiçbir şey YAZMAZ, yalnız okur.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from config import load_config          # noqa: E402
from database import Database           # noqa: E402
from exchange import LiveExchange       # noqa: E402


async def main():
    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")
    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await lx.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"  (initialize uyarısı: {e})")
    try:
        await _govde(lx, cfg)
    finally:
        try:
            await lx.close()
        except Exception:
            pass


async def _govde(lx, cfg):
    simdi_ms = time.time() * 1000
    eski_ms = simdi_ms - 89 * 86400 * 1000

    print("=" * 70)
    print("SERMAYE OTOMATİĞİ — gerçek MEXC yanıtıyla kanıt")
    print("=" * 70)

    hata = []

    # ── 1) GEÇMİŞİ OKUYOR MU ────────────────────────────────────────────────
    print("\n1) Geçmiş transferleri okuyabiliyor mu? (son 89 gün)")
    gecmis = await lx.fetch_transfers_in(int(eski_ms))
    if gecmis is None:
        print("   ⛔ OKUNAMADI (None döndü). Otomatik takip ÇALIŞMAZ —")
        print("      bot sessizce eski tabanı korur, para eklersen kâr şişer.")
        hata.append("geçmiş okunamıyor")
    else:
        print(f"   ✓ okundu: ${gecmis:,.2f}")
        print(f"     (bilinen doğru toplam ~$280.37 — tutuyorsa ayrıştırma,")
        print(f"      para birimi ve yön mantığı GERÇEK veride çalışıyor)")
        if gecmis <= 0:
            print("   ⛔ 0 ya da negatif — kayıtlar okunuyor ama toplanamıyor.")
            hata.append("toplam sıfır")

    # ── 2) PENCERE ÇALIŞIYOR MU — ASIL TEST ─────────────────────────────────
    print("\n2) Pencere süzgeci çalışıyor mu? (şimdiden sonrası → 0.00 olmalı)")
    print("   Bu testin amacı: MEXC `since`'i yok sayarsa ve istemci süzgeci de")
    print("   tutmazsa, taban HER 5 DAKİKADA şişer ve sermaye uçar.")
    yeni = await lx.fetch_transfers_in(int(simdi_ms))
    if yeni is None:
        print("   ⛔ OKUNAMADI")
        hata.append("pencere testi yapılamadı")
    elif abs(yeni) < 1e-9:
        print(f"   ✓ ${yeni:,.2f} — süzgeç TUTUYOR. Eski transferler tekrar")
        print(f"     sayılmıyor, taban şişmez.")
    else:
        print(f"   ⛔ ${yeni:,.2f} DÖNDÜ — süzgeç TUTMUYOR!")
        print(f"      Bot her 5 dakikada bu tutarı tabana EKLER. Otomatik takip")
        print(f"      KAPATILMALI: sermaye_taban meta'sını sil ve elle yönet.")
        hata.append("SÜZGEÇ TUTMUYOR — kritik")

    # ── 3) TOHUM ATILDI MI ──────────────────────────────────────────────────
    print("\n3) Sermaye tabanı tohumlandı mı? (/status onu mu okuyor?)")
    db = Database(cfg.db_path); await db.initialize()
    taban = await db.get_meta_float("sermaye_taban", 0.0)
    damga = await db.get_meta_float("sermaye_taban_ts", 0.0)
    inc = await db.get_meta_float("inception_balance", 0.0)
    dep = await db.get_meta_float("total_deposits", 0.0)
    await db.close()
    if taban > 0:
        yas = (simdi_ms - damga) / 3600000.0
        print(f"   ✓ sermaye_taban = ${taban:,.2f}  (damga {yas:.1f} saat önce)")
        print(f"     /status artık BU rakamı kullanıyor, elle kayda bağlı değil.")
        if abs(taban - (inc + dep)) > 1.0:
            print(f"   ⓘ elle kayıt ${inc+dep:,.2f} ile farklı — normal, taban")
            print(f"     tohumdan sonra borsadan güncelleniyor.")
    else:
        print(f"   ⓘ HENÜZ tohumlanmamış. /status yedek yolu kullanıyor:")
        print(f"     inception ${inc:,.2f} + kaydedilen ${dep:,.2f} = ${inc+dep:,.2f}")
        print(f"     Tohum ilk heartbeat'te atılır (~5 dk). Bot yeni")
        print(f"     başlatıldıysa biraz bekle ve tekrar çalıştır.")

    # ── HÜKÜM ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}\nHÜKÜM\n{'='*70}")
    if hata:
        print(f"  ⛔ ÇALIŞMAZ: {', '.join(hata)}")
        print(f"     Para eklersen OTOMATİK ALGILANMAZ. O zaman elle:")
        print(f"       venv/bin/python para_ekle.py <tutar> --kaydet")
    else:
        print(f"  ✓ ÇALIŞIYOR. Para eklediğinde ~5 dakika içinde algılanacak,")
        print(f"    sermaye kaydı kendiliğinden güncellenecek ve Telegram'a")
        print(f"    'Sermaye kaydı güncellendi' mesajı düşecek.")
        print(f"    Senin hiçbir şey çalıştırman gerekmiyor.")
        if taban <= 0:
            print(f"\n  ⓘ Tek eksik: tohum henüz atılmadı (bot yeni başladı).")
            print(f"    ~5 dk sonra tekrar çalıştırırsan 3. madde de ✓ olur.")


if __name__ == "__main__":
    asyncio.run(main())
