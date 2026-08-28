"""
para_ekle.py — para ekleme/çekmeyi GÜVENLİ yapan iki adımlı araç.

NEDEN deposit.py YETMİYOR: deposit.py sadece rakamı deftere yazar. Yanlış rakam
ya da parayı SPOT cüzdanda unutmak sessizce geçer. Bu araç borsaya bakarak
DOĞRULAR ve iki gerçek riski yüzüne söyler:

  1) GÜNLÜK ZARAR FRENİ GEVŞER. execution.py:238/473 günlük zarar tabanını
     `taban + deposit.py'ye kaydedilen akış` diye hesaplıyor. Parayı yatırıp
     KAYDETMEZSEN taban eski kalır, equity yükselir → o gün fren pratikte
     yatırdığın kadar gevşer. Örn: taban $278, %35 limit → $180'de durur.
     $200 ekleyip kaydetmezsen equity $478 olur ve fren yine $180'de durur:
     yani yeni sermayeye göre -%62'ye kadar iner. KAYIT OPSİYONEL DEĞİL, FREN.

  2) SABİT-MARJ AÇIKSA PARA HİÇBİR ŞEY DEĞİŞTİRMEZ. risk.py:57 FIXED_MARGIN_USDT>0
     iken pozisyon boyutu `min(bakiye, sabit)` — bakiye büyüse de aynı kalır.

Kullanım (VPS'te, /opt/bot2):
    venv/bin/python para_ekle.py 200 --once    # transferden ÖNCE: durum + uyarılar
    #  ... MEXC'te SPOT → VADELİ (futures) transferi yap ...
    venv/bin/python para_ekle.py 200 --sonra   # borsayı doğrular, SONRA deftere yazar

Çekmek için tutarı negatif ver:  para_ekle.py -- -50 --once
Araç emir GÖNDERMEZ; yalnız okur ve trades.db'ye muhasebe kaydı yazar.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

from config import load_config
from database import Database
from exchange import LiveExchange

SNAP = ".para_ekle_snapshot.json"
TOLERANS = 0.02          # equity farkı beklenenin ±%2'si kadar sapabilir (fiyat oynar)


async def _borsa(cfg):
    ex = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await ex.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"  (initialize uyarısı: {e})")
    free = await ex.get_balance()
    eq = await ex.get_equity()
    poz = []
    try:
        for s in cfg.exchange.symbols:
            p = await ex.get_position(s)
            if p:
                poz.append((s, p))
    except Exception as e:
        print(f"  (pozisyon okuma uyarısı: {e})")
    return ex, free, eq, poz


def _boyut(eq, cfg):
    """Bir sonraki işlemin RİSK tutarı ve tavanı — risk.py:65-68 ile aynı."""
    fixed = getattr(cfg.risk, "fixed_margin_usdt", 0.0)
    if fixed > 0:
        return None, min(eq, fixed)
    risk = eq * cfg.risk.max_risk_per_trade
    tavan = eq * cfg.risk.position_cap_fraction
    return risk, tavan


async def once(tutar):
    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")
    ex, free, eq, poz = await _borsa(cfg)
    db = Database(cfg.db_path); await db.initialize()
    inc = await db.get_meta_float("inception_balance", 0.0)
    dep = await db.get_meta_float("total_deposits", 0.0)
    await db.close()
    try:
        await ex.close()
    except Exception:
        pass

    if eq <= 0:
        raise SystemExit("⛔ Borsa equity okunamadı (0). Ağ/anahtar sorunu — DURDURULDU.")

    print("=" * 70)
    print("ÖNCE — mevcut durum (borsadan okundu)")
    print("=" * 70)
    print(f"  Vadeli cüzdan equity : ${eq:,.2f}   (serbest ${free:,.2f})")
    print(f"  Açık pozisyon        : {len(poz)}")
    print(f"  Deftere göre yatırılan: ${inc + dep:,.2f}  "
          f"(başlangıç ${inc:,.2f} + eklenen ${dep:,.2f})")
    print(f"  Defter kârı          : ${eq - inc - dep:+,.2f}")

    yeni = eq + tutar
    print(f"\n  PLAN: ${tutar:+,.2f}  →  yeni equity ~${yeni:,.2f}")

    print(f"\n{'─'*70}\nNE DEĞİŞECEK\n{'─'*70}")
    r0, t0 = _boyut(eq, cfg)
    r1, t1 = _boyut(yeni, cfg)
    if r0 is None:
        print(f"  ⛔ FIXED_MARGIN_USDT={cfg.risk.fixed_margin_usdt} > 0 → SABİT MARJ AÇIK.")
        print(f"     Pozisyon boyutu min(bakiye, sabit) = ${t0:,.2f} ve ${t1:,.2f}.")
        print(f"     Yani para eklemek pozisyon boyutunu DEĞİŞTİRMEZ. Etkisi olsun")
        print(f"     istiyorsan .env'de FIXED_MARGIN_USDT'yi 0 yap ya da büyüt.")
    else:
        print(f"  İşlem başına risk : ${r0:,.2f}  →  ${r1:,.2f}   "
              f"(equity'nin %{cfg.risk.max_risk_per_trade*100:.2f}'i, oran DEĞİŞMEZ)")
        print(f"  Notional tavanı   : ${t0:,.2f}  →  ${t1:,.2f}")
        print(f"  Açık pozisyonlar ETKİLENMEZ — boyut girişte hesaplanır, "
              f"sonradan değişmez.")
    print(f"  Kaldıraç {cfg.exchange.leverage}x · MAX_POSITIONS={cfg.risk.max_positions} — DEĞİŞMEZ.")

    print(f"\n{'─'*70}\nRİSK — yüzde aynı, DOLAR büyür\n{'─'*70}")
    dd = 26.2
    print(f"  Ankorun max drawdown'ı %{dd:.1f}. Bu ORAN para eklemekle değişmez.")
    print(f"    şimdi : -%{dd:.1f} = ${eq*dd/100:,.2f}")
    print(f"    sonra : -%{dd:.1f} = ${yeni*dd/100:,.2f}   "
          f"(${yeni*dd/100 - eq*dd/100:+,.2f} daha fazla)")
    print(f"  En kötü ay ankorda -%21.0 → ${yeni*0.21:,.2f}.")
    print(f"  Ağustos'ta yaşadığın -%26.8 aynı oranla ${yeni*0.268:,.2f} olurdu.")

    print(f"\n{'─'*70}\nŞİMDİ NE YAP\n{'─'*70}")
    print("  1) MEXC'te SPOT → VADELİ (USDT-M futures) transferi yap.")
    print("     ⚠ Bot yalnız VADELİ cüzdanı okur (fetch_balance type=swap).")
    print("       Para spotta kalırsa bot onu GÖRMEZ.")
    print("  2) Transfer bitince:")
    print(f"       venv/bin/python para_ekle.py {tutar:g} --sonra")
    print("     Araç borsayı tekrar okur, artışı DOĞRULAR, sonra deftere yazar.")
    print("  3) Bot'u yeniden başlatmana GEREK YOK — boyut her girişte")
    print("     equity'den okunur (execution.py:472).")

    json.dump({"ts": datetime.now(timezone.utc).isoformat(), "tutar": tutar,
               "equity_once": eq, "free_once": free, "acik": len(poz),
               "deposits_once": dep},
              open(SNAP, "w"))
    print(f"\n  (durum {SNAP} dosyasına yazıldı — --sonra bunu kullanacak)")


async def sonra(tutar):
    if not os.path.exists(SNAP):
        raise SystemExit(f"⛔ {SNAP} yok. Önce şunu çalıştır: para_ekle.py {tutar:g} --once")
    snap = json.load(open(SNAP))
    if abs(snap["tutar"] - tutar) > 1e-9:
        raise SystemExit(f"⛔ Tutar uyuşmuyor: --once ${snap['tutar']:,.2f} ile "
                         f"çalıştırılmıştı, şimdi ${tutar:,.2f} verdin. DURDURULDU.")
    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")

    # ÇİFT KAYIT GUARD'I: arada deposit.py elle çalıştırıldıysa toplam değişmiştir.
    # Üstüne bir kez daha yazmak sermayeyi iki kere sayar ve "kâr" rakamını
    # kalıcı olarak bozar — tam da 'ne ile başladık' sorusunun üç farklı cevap
    # vermesine yol açan hata sınıfı.
    _db = Database(cfg.db_path); await _db.initialize()
    dep_simdi = await _db.get_meta_float("total_deposits", 0.0)
    await _db.close()
    dep_once = snap.get("deposits_once")
    if dep_once is not None and abs(dep_simdi - dep_once) > 1e-9:
        raise SystemExit(
            f"⛔ Defterdeki 'total_deposits' --once'dan beri DEĞİŞTİ "
            f"(${dep_once:,.2f} → ${dep_simdi:,.2f}).\n"
            f"   Arada deposit.py elle çalıştırılmış olabilir. Üstüne yazmak\n"
            f"   sermayeyi İKİ KEZ sayar. Kayıt YAPILMADI — önce şunu kontrol et:\n"
            f"     venv/bin/python deposit.py")

    ex, free, eq, poz = await _borsa(cfg)
    try:
        await ex.close()
    except Exception:
        pass
    if eq <= 0:
        raise SystemExit("⛔ Borsa equity okunamadı (0) — kayıt YAPILMADI.")

    fark = eq - snap["equity_once"]
    bek = tutar
    sapma = abs(fark - bek)
    izin = max(abs(bek) * TOLERANS, 2.0)     # fiyat oynaması için pay

    print("=" * 70)
    print("SONRA — borsa doğrulaması")
    print("=" * 70)
    print(f"  equity ÖNCE  : ${snap['equity_once']:,.2f}  ({snap['ts'][:16]})")
    print(f"  equity ŞİMDİ : ${eq:,.2f}")
    print(f"  GERÇEK fark  : ${fark:+,.2f}   |  beklenen ${bek:+,.2f}   "
          f"|  sapma ${sapma:,.2f} (izin ${izin:,.2f})")
    if snap["acik"] or poz:
        print(f"  ⓘ açık pozisyon vardı/var ({snap['acik']}→{len(poz)}) — uPnL "
              f"oynadığı için sapma normaldir, tolerans bunun için var.")

    if sapma > izin:
        print(f"\n  ⛔ DOĞRULANAMADI — deftere HİÇBİR ŞEY YAZILMADI.")
        print(f"     Olası sebepler:")
        print(f"       • para SPOT cüzdanda kaldı (bot vadeli cüzdanı okur)")
        print(f"       • transfer henüz oturmadı → 1-2 dk sonra tekrar dene")
        print(f"       • gerçek tutar farklı → doğru tutarla --once'dan başla")
        print(f"       • açık pozisyon çok oynadı → pozisyon kapanınca tekrar dene")
        raise SystemExit(2)

    db = Database(cfg.db_path); await db.initialize()
    yeni_top = await db.add_deposit(tutar)
    inc = await db.get_meta_float("inception_balance", 0.0)
    await db.close()
    os.remove(SNAP)

    print(f"\n  ✓ DOĞRULANDI ve deftere yazıldı.")
    print(f"    Toplam eklenen   : ${yeni_top:,.2f}")
    print(f"    TOPLAM YATIRILAN : ${inc + yeni_top:,.2f}")
    print(f"    Defter kârı      : ${eq - inc - yeni_top:+,.2f}")
    print(f"\n  ✓ Günlük zarar freni yeniden hizalandı: taban artık "
          f"${snap['equity_once']:,.2f} yerine akışı da sayıyor")
    print(f"    (execution.py:238/473 — _deposit_flow_since_baseline).")
    print(f"  ✓ Restart GEREKMEZ. Panel birkaç saniyede güncellenir.")


def main():
    args = [a for a in sys.argv[1:] if a != "--"]
    mod = None
    for m in ("--once", "--sonra"):
        if m in args:
            mod = m; args.remove(m)
    if not args or mod is None:
        raise SystemExit(__doc__)
    try:
        tutar = float(args[0])
    except ValueError:
        raise SystemExit(f"Geçersiz tutar: {args[0]!r}")
    if tutar == 0:
        raise SystemExit("Tutar 0 olamaz.")
    asyncio.run(once(tutar) if mod == "--once" else sonra(tutar))


if __name__ == "__main__":
    main()
