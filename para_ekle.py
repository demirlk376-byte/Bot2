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

GEÇMİŞTE kaydedilmemiş bir transfer varsa (para zaten geldi, defter bilmiyor):
    venv/bin/python para_ekle.py --tespit         # borsa geçmişi vs defter
    venv/bin/python para_ekle.py 65 --kaydet      # tespit ettiğin tutarı işle
Araç emir GÖNDERMEZ; yalnız okur ve trades.db'ye muhasebe kaydı yazar.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from config import load_config
from database import Database
from exchange import LiveExchange

SNAP = ".para_ekle_snapshot.json"


def pd_ts(t: str):
    """'YYYY-MM-DD HH:MM' → datetime (UTC). Çift eşleştirmesi için."""
    return datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
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


def sermaye_denklemi(kalem, ilk, inc, dep, eq):
    """Sermaye denklemini SAF olarak kur (ağ yok, DB yok) — test edilebilsin.

    Bu fonksiyon iki kez YANLIŞ rakam ürettiği için ayrıştırıldı:
      1. sürüm: 'köken SONRASI transfer − kaydedilen' = $26.32. YANLIŞ TABAN —
         inception'ın köken öncesi transferleri karşıladığını varsayıyordu.
      2. sürüm: deposits+transfers+withdrawals TOPLANDI = $456.09. ÇİFT SAYMA —
         aynı para hem 'deposit' (dışarıdan MEXC'e) hem 'transfer' (spot→vadeli)
         olarak görünüyor.
    Doğrusu: sermaye YALNIZ 'transfers' ile ölçülür (bota para ancak VADELİ
    cüzdana geçince girer). tests/test_sermaye.py bunu gerçek veriyle kilitliyor.

    kalem: [(ts_str, tutar, tur)] · ilk: botun ilk işlem zamanı (ISO) ya da None
    Döner: dict
    """
    sermaye = [(t, a) for t, a, ty in kalem if ty == "transfers"]
    oncesi = sum(a for t, a in sermaye if ilk and t < ilk[:16])
    sonrasi = sum(a for t, a in sermaye if not (ilk and t < ilk[:16]))
    tum = oncesi + sonrasi
    return {
        "oncesi": oncesi, "sonrasi": sonrasi, "tum": tum,
        "defter_yatirilan": inc + dep,
        "defter_kar": eq - inc - dep,
        "gercek_kar": eq - tum if tum > 0 else None,
        "inception_farki": oncesi - inc,
        "gereken_dep": tum - inc,
        "duzeltme": (tum - inc) - dep,
    }


async def tespit(gun: int = 89):
    """Borsanın transfer geçmişini oku, defterle karşılaştır, EKSİĞİ göster.

    28 Ağustos'ta olan şuydu: para vadeli cüzdana geldi, `total_deposits`
    değişmedi, fark doğrudan "Gerçek kâr" diye göründü. Bu mod o farkı
    borsadan arar.

    ⚠ ÇİFT SAYMA TUZAĞI: köken bakiyesi (`inception_balance`) ZATEN bir
    transferin sonucudur. Bot başlamadan ÖNCEKİ transferler onun İÇİNDE — onları
    ayrıca eklemek sermayeyi şişirir ve kârı olduğundan DÜŞÜK gösterir. O yüzden
    bu mod OTOMATİK KAYIT YAPMAZ: tarihli döküm basar, kararı sen verirsin.
    """
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
        await _tespit_govde(lx, cfg, gun)
    finally:
        # Çökse de bağlantı kapansın — ilk sürüm çökünce "Unclosed connector"
        # bırakıyordu ve ccxt "explicit .close()" uyarısı basıyordu.
        try:
            await lx.close()
        except Exception:
            pass


async def _tespit_govde(lx, cfg, gun: int):
    ex = lx._exchange                      # ham ccxt istemcisi (ASENKRON!)
    eq = await lx.get_equity()

    db = Database(cfg.db_path); await db.initialize()
    inc = await db.get_meta_float("inception_balance", 0.0)
    dep = await db.get_meta_float("total_deposits", 0.0)
    try:
        perf = await db.get_performance_summary(is_paper=False)
        defter_pnl = float(perf.total_pnl_usdt)
    except Exception:
        defter_pnl = None
    ilk = None
    try:
        import sqlite3
        con = sqlite3.connect(cfg.db_path)
        r = con.execute("SELECT MIN(entry_time) FROM trades WHERE is_paper=0").fetchone()
        con.close()
        ilk = r[0] if r and r[0] else None
    except Exception:
        pass
    await db.close()

    since = int((datetime.now(timezone.utc) - timedelta(days=gun)).timestamp() * 1000)
    print("=" * 74)
    print(f"TESPİT — borsa transfer geçmişi (son {gun} gün) vs defter")
    print("=" * 74)
    print(f"  Borsa equity          : ${eq:,.2f}")
    print(f"  Defter: köken bakiye  : ${inc:,.2f}")
    print(f"  Defter: kaydedilen ek : ${dep:,.2f}")
    print(f"  Defter: yatırılan TOP : ${inc+dep:,.2f}")
    print(f"  → 'Gerçek kâr' şu an  : ${eq-inc-dep:+,.2f}")

    if defter_pnl is not None:
        # AÇIK pozisyonların uPnL'i de defterin parçası — ilk sürüm bunu
        # SAYMIYORDU ve farkı olduğundan BÜYÜK gösteriyordu.
        upnl = 0.0
        try:
            for sym in cfg.exchange.symbols:
                pz = await lx.get_position(sym)
                if pz:
                    upnl += float(getattr(pz, "unrealized_pnl", 0.0) or 0.0)
        except Exception as e:
            print(f"  (uPnL okunamadı: {e})")
            upnl = None
        if upnl is None:
            print(f"  → İşlem defteri (kapanan): ${defter_pnl:+,.2f}"
                  f"   ⚠ açık uPnL okunamadı, FARK hesaplanmadı")
        else:
            fark = (eq - inc - dep) - (defter_pnl + upnl)
            print(f"  → İşlem defteri: kapanan ${defter_pnl:+,.2f} + açık uPnL "
                  f"${upnl:+,.2f} = ${defter_pnl+upnl:+,.2f}")
            print(f"     FARK: ${fark:+,.2f}")
            print(f"\n  ⚠ FARK'I HEMEN 'KAYIT EKSİĞİ' SANMA. Bilinen sızıntılar:")
            print(f"     • ücret: defter 1bp yazıyor, gerçek ~2.5bp/yön (DURUM 2d)")
            print(f"       → yüzlerce işlemde birikir")
            print(f"     • fonlama: ölçülen −$0.91 (DURUM 4i)")
            print(f"     • main.py:1619 çıkışları SEVİYE fiyatından yazıyor, gerçek")
            print(f"       dolumdan değil — çıkışların %68'i (DURUM backlog)")
            print(f"     Kayıt eksiği ancak aşağıdaki dökümde DEFTERDE OLMAYAN bir")
            print(f"     transfer varsa doğrulanır.")
    if ilk:
        print(f"  Botun ilk gerçek işlemi: {ilk[:16]}")

    print(f"\n  --- BORSADAN TRANSFER KAYITLARI ---")
    # ⚠ DÜZELTİLDİ: ccxt burada ASENKRON. İlk sürüm `ex.fetch_transfers(...)`
    # diye çağırıp coroutine'i AWAIT ETMEDEN döngüye soktu →
    # "TypeError: 'coroutine' object is not iterable" (VPS, 28 Ağustos).
    # Ayrıca tek uç nokta yetmiyor: MEXC'te para vadeliye transfer ya da
    # deposit olarak görünebiliyor (gercek_pnl.py da birkaçını deniyor).
    kalem = []
    okunan = 0
    # ⚠ MEXC KISITI: fetch_deposits/fetch_withdrawals 7 GÜNDEN uzun pencereyi
    # REDDEDİYOR ({"code":33333,"msg":"start time and end time diff cannot
    # exceed 7 days"}). İlk sürüm tek seferde 89 gün sorup ikisini de KAYBETTİ —
    # yani PARA ÇIKIŞLARI hiç görünmedi ve sermaye denklemi eksik kuruldu.
    # Artık 7 günlük dilimlere bölünüyor. fetch_transfers bu kısıta tabi değil.
    simdi_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    HAFTA = 7 * 86400 * 1000

    async def _parcali(fn):
        top = []
        t = since
        while t < simdi_ms:
            son = min(t + HAFTA - 1000, simdi_ms)
            try:
                top += list(await fn(t, son) or [])
            except Exception as e:
                raise e
            t = son + 1000
            await asyncio.sleep(0.2)
        return top

    for ad, yap in (
        ("fetch_transfers", lambda: ex.fetch_transfers(
            "USDT", since, 200,
            {"fromAccountType": "SPOT", "toAccountType": "FUTURES"})),
        ("fetch_deposits", lambda: _parcali(
            lambda a, b: ex.fetch_deposits(None, a, 200, {"endTime": b}))),
        ("fetch_withdrawals", lambda: _parcali(
            lambda a, b: ex.fetch_withdrawals(None, a, 200, {"endTime": b}))),
    ):
        base = ad if hasattr(ex, ad) else None
        if base is None:
            print(f"    {ad:<18s} — ccxt'de YOK")
            continue
        try:
            r = await yap()
        except Exception as e:
            print(f"    {ad:<18s} — HATA: {type(e).__name__}: {e}")
            continue
        n = 0
        for x in (r or []):
            if not isinstance(x, dict) or (x.get("currency") or "USDT") != "USDT":
                continue
            try:
                a = float(x.get("amount") or 0.0)
            except (TypeError, ValueError):
                continue
            if ad == "fetch_withdrawals":
                a = -abs(a)
            ts = x.get("timestamp")
            t = (datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")
                 if ts else "?")
            kalem.append((t, a, ad.replace("fetch_", "")))
            n += 1
        okunan += 1
        print(f"    {ad:<18s} — {n} USDT kaydı")
        await asyncio.sleep(0.25)

    if okunan == 0:
        print("\n  ⛔ HİÇBİR uç nokta okunamadı — 'transfer yok' SONUCU ÇIKARMA.")
        print("     Karar verme; MEXC uygulamasından elle bak.")
        return

    if not kalem:
        print("\n  Bu pencerede USDT transfer kaydı YOK.")
        print("  → Yani yukarıdaki FARK bir para girişinden DEĞİL, muhtemelen")
        print("    yukarıda sayılan muhasebe sızıntılarından geliyor.")
        print("  (MEXC varlık uç noktaları 90 günle sınırlı; daha eskisi görünmez.)")
        return

    print()
    for t, a, ty in sorted(kalem):
        if ty != "transfers":
            print(f"    {t}  ${a:+10,.2f}  {ty:<12s}  (bağlam — sermayeye SAYILMAZ)")
            continue
        isaret = "  ← köken ÖNCESİ, muhtemelen inception içinde" if (
            ilk and t < ilk[:16]) else ""
        print(f"    {t}  ${a:+10,.2f}  {ty:<12s}{isaret}")
    # ══ ÇİFT SAYMA DÜZELTİLDİ ═════════════════════════════════════════════
    # İlk sürüm ÜÇ uç noktanın kalemlerini TOPLADI ve sermayeyi İKİ KATINA
    # çıkardı ($456.09 çıktı, doğrusu $280.37). Çünkü aynı para iki kez
    # görünüyor:
    #     2026-07-12 00:32  +104.40  deposits   ← dışarıdan MEXC'e girdi
    #     2026-07-12 00:37  +104.40  transfers  ← spot'tan VADELİYE geçti
    # Bunlar iki ayrı para değil, AYNI paranın iki bacağı.
    #
    # DOĞRU ÖLÇÜ = YALNIZ 'transfers'. Bota sermaye ancak VADELİ cüzdana
    # geçince girer; deposit tek başına spotta durur ve bot onu görmez.
    # Zaten spotta duran bir para taze deposit olmadan transfer edilirse de
    # 'transfers' onu yakalar. deposits/withdrawals yalnız BAĞLAM olarak
    # listelenir, sermaye denklemine GİRMEZ.
    sermaye_kalem = [(t, a, ty) for t, a, ty in kalem if ty == "transfers"]
    baglam = [(t, a, ty) for t, a, ty in kalem if ty != "transfers"]
    # eşleşen çiftleri göster (aynı tutar, 24 saat içinde) — okur da görsün
    ciftler = []
    for t, a, ty in baglam:
        for t2, a2, _ in sermaye_kalem:
            if abs(a - a2) < 0.01 and abs(
                    (pd_ts(t) - pd_ts(t2)).total_seconds()) < 86400:
                ciftler.append((t, t2, a, ty))
                break
    # ⚠ RAKAMLAR TEST EDİLMİŞ SAF FONKSİYONDAN gelir (tests/test_sermaye.py,
    # gerçek MEXC verisiyle kilitli). Burada elle aritmetik YAPILMAZ — bu araç
    # aynı rakamı iki kez yanlış verdi, ikisi de satır içi hesaptandı.
    R = sermaye_denklemi(kalem, ilk, inc, dep, eq)

    print(f"\n{'─'*74}\nSERMAYE DENKLEMİ — İKİ OKUMA\n{'─'*74}")
    print(f"  A) DEFTERİN OKUMASI (inception + kaydedilen):")
    print(f"     köken ${inc:,.2f} + kaydedilen ${dep:,.2f} = ${R['defter_yatirilan']:,.2f}")
    print(f"     → defterin iddia ettiği kâr: ${R['defter_kar']:+,.2f}")
    print(f"\n  B) BORSANIN OKUMASI (yalnız SPOT→VADELİ transferler):")
    print(f"     köken ÖNCESİ ${R['oncesi']:,.2f} + SONRASI ${R['sonrasi']:,.2f} "
          f"= ${R['tum']:,.2f}")

    if R["tum"] <= 0:
        print(f"\n  ⛔ Hiç transfer okunamadı — sermaye denklemi KURULAMAZ.")
        print(f"     Hüküm yok. MEXC uygulamasından elle bak.")
        return

    if abs(R["inception_farki"]) > 2.0:
        print(f"\n  ⛔ İKİ OKUMA ÇELİŞİYOR — inception_balance GÜVENİLMEZ.")
        print(f"     Bot başlamadan önce ${R['oncesi']:,.2f} vadeliye geçmiş ama")
        print(f"     inception_balance ${inc:,.2f} yazıyor "
              f"(fark ${R['inception_farki']:+,.2f}).")
        print(f"     Sebep muhtemelen main.py'nin 'bogus startup value' yolu:")
        print(f"     inception <$1 görülünce O ANKİ bakiyeyle EZİLİYOR — yani")
        print(f"     gerçek sermaye değil, bir ara bakiye yazılmış olabilir.")
        print(f"\n     Bu durumda A) YANLIŞ taban kuruyor. Borsa kaydı tek")
        print(f"     doğrulanabilir kaynak:")
        print(f"       GERÇEK yatırılan sermaye : ${R['tum']:,.2f}")
        print(f"       GERÇEK kâr               : ${R['gercek_kar']:+,.2f} "
              f"({R['gercek_kar']/R['tum']*100:+.1f}%)")
        print(f"       (defterin iddiası        : ${R['defter_kar']:+,.2f} — "
              f"${R['defter_kar']-R['gercek_kar']:+,.2f} fazla)")
        print(f"\n     DÜZELTME: total_deposits ${dep:,.2f} → "
              f"${R['gereken_dep']:,.2f} olmalı")
        print(f"       venv/bin/python para_ekle.py {R['duzeltme']:.2f} --kaydet")
    else:
        print(f"\n  ✓ inception köken öncesi transferlerle tutarlı "
              f"(fark ${R['inception_farki']:+,.2f}).")
        if abs(R["duzeltme"]) > 1.0:
            print(f"    KAYIT EKSİĞİ: ${R['duzeltme']:+,.2f}")
            print(f"       venv/bin/python para_ekle.py {R['duzeltme']:.2f} --kaydet")
        else:
            print(f"    ✓ Kayıt eksiği yok.")

    print(f"\n  ⚠ İKİ KONTROL — rakamı kaydetmeden ÖNCE:")
    print(f"     1) fetch_withdrawals satırı: para ÇIKIŞI varsa yatırılan sermaye")
    print(f"        daha DÜŞÜKTÜR ve bu rakam değişir.")
    print(f"     2) {gun} günlük pencere botun tüm ömrünü kapsıyor mu? İlk işlem")
    print(f"        {ilk[:16] if ilk else '?'}, en eski transfer "
          f"{sorted(kalem)[0][0] if kalem else '?'} — kapsamıyorsa daha eski")
    print(f"        transferler bu toplamda YOK demektir.")

    print(f"\n{'─'*74}\nNE YAPMALI\n{'─'*74}")
    print("  Bu mod OTOMATİK KAYIT YAPMAZ — yanlış tabanla kayıt, hatayı KALICI")
    print("  hale getirir. Yukarıdaki iki okumadan hangisinin doğru olduğuna")
    print("  MEXC uygulamasındaki transfer geçmişine bakarak karar ver.")


async def kaydet(tutar):
    """Geçmişte YAPILMIŞ bir transferi deftere işler (borsa doğrulaması YOK —
    para zaten geldiği için --once/--sonra karşılaştırması yapılamaz).
    Yeni bir transfer için bunu DEĞİL, --once/--sonra akışını kullan."""
    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")
    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await lx.initialize(cfg.exchange.symbols[0])
    except Exception:
        pass
    eq = await lx.get_equity()
    try:
        await lx.close()
    except Exception:
        pass
    db = Database(cfg.db_path); await db.initialize()
    inc = await db.get_meta_float("inception_balance", 0.0)
    onceki = await db.get_meta_float("total_deposits", 0.0)
    yeni = await db.add_deposit(tutar)
    await db.close()
    print(f"  ✓ ${tutar:+,.2f} deftere işlendi (geçmiş transfer).")
    print(f"    kaydedilen ek : ${onceki:,.2f} → ${yeni:,.2f}")
    print(f"    yatırılan TOP : ${inc+yeni:,.2f}")
    if eq > 0:
        print(f"    Gerçek kâr    : ${eq-inc-yeni:+,.2f}  (equity ${eq:,.2f})")
    print(f"  ✓ Günlük zarar freni de bu akışı sayar (execution.py:238/473).")
    print(f"  Yanlış girdiysen tersini işle:  para_ekle.py -- {-tutar:g} --kaydet")


def main():
    args = [a for a in sys.argv[1:] if a != "--"]
    mod = None
    for m in ("--once", "--sonra", "--tespit", "--kaydet"):
        if m in args:
            mod = m; args.remove(m)
    if mod == "--tespit":
        gun = int(args[0]) if args else 89
        return asyncio.run(tespit(gun))
    if not args or mod is None:
        raise SystemExit(__doc__)
    try:
        tutar = float(args[0])
    except ValueError:
        raise SystemExit(f"Geçersiz tutar: {args[0]!r}")
    if tutar == 0:
        raise SystemExit("Tutar 0 olamaz.")
    asyncio.run({"--once": once, "--sonra": sonra, "--kaydet": kaydet}[mod](tutar))


if __name__ == "__main__":
    main()
