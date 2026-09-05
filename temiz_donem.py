"""
temiz_donem.py — "temiz dönem" çıpasını DOĞRULA ve KUR.

KULLANICI İSTEĞİ: her komuttaki kâr/zarar TEMİZ DÖNEME göre verilsin; o
tarihten geriye hiçbir iz kalmasın.

SORUN: 'Gerçek kâr' = equity − yatırılan sermaye. Bu HER ZAMANIN rakamı.
Temiz döneme indirmek için çıpa lazım:

    temiz kâr = equity_şimdi − equity_çıpa − (sermaye_şimdi − sermaye_çıpa)

Yani "çıpadan bu yana kazanılan", araya giren sermaye eklemeleri düşülmüş.
İki çıpa değeri bir kez ölçülüp meta'ya yazılır; sonrası kendiliğinden döner.

BU ARAÇ ÜÇ İŞ YAPAR:
  1) CUT tarihini DOĞRULAR — kapalı sleeve'lerin gerçekten o tarihte bitip
     bitmediğini defterden okur. Bitmemişse tarih YANLIŞ, söyler.
  2) equity_çıpa'yı daily_stats'ten çeker (starting_balance = o günün
     BAŞLANGIÇ EQUITY'si; capture_daily_start onu borsadan alır).
     ⚠ ending_balance KULLANILMAZ: gün başında yazılıp güncellenmiyor
     (DURUM 8'de bu hata düzeltilmişti).
  3) sermaye_çıpa'yı borsanın transfer kaydından toplar (çıpa tarihine kadar).

Hiçbiri okunamazsa HİÇBİR ŞEY YAZMAZ — yanlış çıpa, yanlış kârı KALICI yapar.

Kullanım (VPS'te):
    venv/bin/python temiz_donem.py              # DOĞRULA, yazma (kuru koşu)
    venv/bin/python temiz_donem.py --yaz        # çıpayı meta'ya yaz
    venv/bin/python temiz_donem.py --yaz 2026-07-16   # tarihi elle ver
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from config import load_config          # noqa: E402
from database import Database           # noqa: E402
from exchange import LiveExchange       # noqa: E402

# Canlıda AÇIK olan kollar. Bunların dışındakiler "kapalı" (emekli) sayılır.
ACIK_KOLLAR = {"donchian", "squeeze", "mean_rev", "bb"}
VARSAYILAN_CUT = "2026-07-16"


def _kol(js):
    try:
        d = json.loads(js or "{}")
        for k in ("strategy", "sleeve", "source"):
            if k in d:
                return str(d[k])
    except Exception:
        pass
    return "?"


def dogrula_cut(db_path, cut):
    """CUT tarihi gerçekten 'kapalı kolların bittiği an' mı? Defterden oku."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT entry_time, strategy_scores, pnl_usdt, exit_time FROM trades "
        "WHERE is_paper=0 ORDER BY entry_time").fetchall()
    con.close()
    if not rows:
        return None, "defterde canlı işlem yok"
    kapali = [(r[0], _kol(r[1]), r[2]) for r in rows if _kol(r[1]) not in ACIK_KOLLAR]
    acik = [(r[0], _kol(r[1]), r[2]) for r in rows if _kol(r[1]) in ACIK_KOLLAR]
    son_kapali = max((t for t, _, _ in kapali), default=None)
    ilk_acik = min((t for t, _, _ in acik), default=None)
    print(f"  defterde {len(rows)} canlı işlem "
          f"({len(kapali)} kapalı kol, {len(acik)} açık kol)")
    print(f"  kapalı kolların SON işlemi : {son_kapali or '—'}")
    print(f"  açık kolların İLK işlemi   : {ilk_acik or '—'}")
    print(f"  kullanılacak CUT           : {cut}")
    sorun = []
    sonra = [(t, k) for t, k, _ in kapali if str(t) >= cut]
    if sonra:
        sorun.append(f"CUT'tan SONRA {len(sonra)} kapalı-kol işlemi var "
                     f"(ilk: {sonra[0][0][:16]} {sonra[0][1]}) — tarih ERKEN")
        for t, k in sonra[:5]:
            print(f"    ⚠ {t[:16]} {k}")
    kesilen = [(t, k) for t, k, _ in acik if str(t) < cut]
    if kesilen:
        pnl_k = sum(p or 0 for t, k, p in acik if str(t) < cut)
        print(f"  ⓘ CUT açık-kol işlemlerinden de {len(kesilen)} tanesini "
              f"kesiyor (${pnl_k:+.2f})")
        print(f"     — bu KASITLI: temiz dönem TARİHE göre, kola göre değil.")
    return (son_kapali, "; ".join(sorun) if sorun else None)


async def main():
    args = [a for a in sys.argv[1:]]
    yaz = "--yaz" in args
    if yaz:
        args.remove("--yaz")
    cut = args[0] if args else VARSAYILAN_CUT
    try:
        datetime.strptime(cut, "%Y-%m-%d")
    except ValueError:
        raise SystemExit(f"Tarih biçimi YYYY-MM-DD olmalı: {cut!r}")

    cfg = load_config()
    if cfg.exchange.paper_mode:
        raise SystemExit("PAPER modda — .env LIVE olmalı.")

    print("=" * 72)
    print(f"TEMİZ DÖNEM ÇIPASI — {'YAZMA' if yaz else 'KURU KOŞU (yazmaz)'}")
    print("=" * 72)

    # ── 1) CUT DOĞRULAMASI ───────────────────────────────────────────────────
    print(f"\n1) CUT tarihi doğru mu?")
    son_kapali, sorun = dogrula_cut(cfg.db_path, cut)
    if sorun:
        print(f"  ⛔ {sorun}")
        if son_kapali:
            from datetime import timedelta as _td
            oner = (datetime.strptime(str(son_kapali)[:10], "%Y-%m-%d")
                    + _td(days=1)).strftime("%Y-%m-%d")
            print(f"\n     Sebep: karşılaştırma `entry_time >= CUT` ve son kapalı-kol")
            print(f"     işlemi {str(son_kapali)[:19]} — yani CUT gününün İÇİNDE.")
            print(f"     Bir gün ileri alınca temizlenir:")
            print(f"       venv/bin/python temiz_donem.py {oner}          # doğrula")
            print(f"       venv/bin/python temiz_donem.py --yaz {oner}    # yaz")
        raise SystemExit(2)
    print(f"  ✓ CUT tutarlı — bu tarihten sonra kapalı-kol işlemi yok.")

    # ── 2) equity ÇIPASI ─────────────────────────────────────────────────────
    print(f"\n2) Çıpa equity'si (daily_stats.starting_balance)")
    con = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=15)
    row = con.execute(
        "SELECT date, starting_balance FROM daily_stats WHERE is_paper=0 "
        "AND starting_balance IS NOT NULL AND starting_balance>0 AND date>=? "
        "ORDER BY date LIMIT 1", (cut,)).fetchone()
    con.close()
    if not row:
        print(f"  ⛔ {cut} veya sonrası için daily_stats kaydı YOK.")
        print(f"     Çıpa kurulamaz — HİÇBİR ŞEY YAZILMADI.")
        raise SystemExit(2)
    cq_gun, cq_eq = str(row[0]), float(row[1])
    print(f"  ✓ {cq_gun} günü başlangıç equity'si: ${cq_eq:,.2f}")
    if cq_gun != cut:
        print(f"  ⓘ {cut} için kayıt yoktu, en yakın SONRAKİ gün kullanıldı.")
    # ⚠ KÖKEN GUARD'I: bu alan HER ZAMAN equity değildi. capture_daily_start
    # 2026-06-14'te (commit a68a535) equity'ye geçti; ondan ÖNCE yazılmış
    # satırlar serbest bakiye olabilir ve çıpayı DÜŞÜK kurar → kâr ŞİŞER.
    # (git ile doğrulandı: 2026-07-18 tarihli kodda current_equity zaten
    #  borsanın get_equity()'sini tercih ediyordu.)
    EQUITY_GECIS = "2026-06-14"
    if cq_gun < EQUITY_GECIS:
        print(f"  ⛔ {cq_gun} < {EQUITY_GECIS}: o tarihte daily_stats SERBEST")
        print(f"     BAKİYE yazıyor olabilir (equity değil). Çıpa düşük kurulur")
        print(f"     ve kâr ŞİŞER. Daha geç bir CUT seç. YAZILMADI.")
        raise SystemExit(2)
    print(f"     (köken ✓: capture_daily_start {EQUITY_GECIS}'ten beri borsanın")
    print(f"      equity'sini yazıyor — bu satır güvenilir)")

    # Komşu günleri de göster: rakam gözle makul mü?
    con2 = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=15)
    komsu = con2.execute(
        "SELECT date, starting_balance FROM daily_stats WHERE is_paper=0 "
        "AND starting_balance>0 AND date BETWEEN date(?,'-3 day') AND date(?,'+3 day') "
        "ORDER BY date", (cq_gun, cq_gun)).fetchall()
    con2.close()
    if len(komsu) > 1:
        print(f"     komşu günler: " + " · ".join(
            f"{d[5:]}:${float(v):,.0f}" for d, v in komsu))

    # ── 3) sermaye ÇIPASI ────────────────────────────────────────────────────
    print(f"\n3) Çıpa sermayesi (borsanın transfer kaydı, {cut}'a kadar)")
    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await lx.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"  (initialize uyarısı: {e})")
    try:
        cut_ms = int(datetime.strptime(cq_gun, "%Y-%m-%d")
                     .replace(tzinfo=timezone.utc).timestamp() * 1000)
        eski_ms = int(cut_ms - 400 * 86400 * 1000)
        toplam = await lx.fetch_transfers_in(eski_ms)          # tümü
        sonrasi = await lx.fetch_transfers_in(cut_ms)          # çıpadan sonrası
        eq_now = await lx.get_equity()
    finally:
        try:
            await lx.close()
        except Exception:
            pass
    if toplam is None or sonrasi is None:
        print(f"  ⛔ Transfer kaydı okunamadı — çıpa kurulamaz, YAZILMADI.")
        raise SystemExit(2)
    cq_sermaye = toplam - sonrasi
    print(f"  toplam transfer      : ${toplam:,.2f}")
    print(f"  çıpadan SONRA gelen  : ${sonrasi:,.2f}")
    print(f"  → çıpa sermayesi     : ${cq_sermaye:,.2f}")
    if cq_sermaye <= 0:
        print(f"  ⛔ Çıpa sermayesi 0 veya negatif — 90 günlük pencere çıpa")
        print(f"     tarihine ULAŞMIYOR olabilir. YAZILMADI.")
        raise SystemExit(2)

    # ── SONUÇ ────────────────────────────────────────────────────────────────
    db = Database(cfg.db_path); await db.initialize()
    serm_now = await db.get_meta_float("sermaye_taban", 0.0)
    if serm_now <= 0:
        serm_now = (await db.get_meta_float("inception_balance", 0.0)
                    + await db.get_meta_float("total_deposits", 0.0))
    temiz_kar = eq_now - cq_eq - (serm_now - cq_sermaye)
    print(f"\n{'='*72}\nSONUÇ\n{'='*72}")
    print(f"  temiz kâr = equity_şimdi − equity_çıpa − (sermaye_şimdi − sermaye_çıpa)")
    print(f"            = {eq_now:,.2f} − {cq_eq:,.2f} − "
          f"({serm_now:,.2f} − {cq_sermaye:,.2f})")
    print(f"            = ${temiz_kar:+,.2f}")
    taban = cq_eq if cq_eq > 0 else 1.0
    print(f"  temiz dönem getirisi: {temiz_kar/taban*100:+.1f}% "
          f"(çıpa equity'sine göre)")
    her_zaman = eq_now - serm_now
    once = her_zaman - temiz_kar
    print(f"\n  karşılaştırma — HER ZAMANIN kârı: ${her_zaman:+,.2f}")
    print(f"  aradaki fark = çıpa ÖNCESİ dönemin katkısı: ${once:+,.2f}")
    print(f"     (çıpa equity ${cq_eq:,.2f} − çıpa sermaye ${cq_sermaye:,.2f})")
    # MAKULLUK: çıpa öncesi katkı sermayeye göre absürt mü?
    if cq_sermaye > 0 and abs(once) > cq_sermaye * 0.8:
        print(f"  ⛔ Çıpa öncesi katkı sermayenin %{abs(once)/cq_sermaye*100:.0f}'i —")
        print(f"     bu absürt. Çıpa equity'si ya da sermayesi YANLIŞ okunmuş")
        print(f"     olabilir. Rakamları elle doğrulamadan --yaz KULLANMA.")

    if not yaz:
        print(f"\n  KURU KOŞU — hiçbir şey yazılmadı.")
        print(f"  Yazmak için:  venv/bin/python temiz_donem.py --yaz {cut}")
        await db.close()
        return
    await db.set_meta("temiz_cut", cq_gun)
    await db.set_meta("temiz_equity", str(cq_eq))
    await db.set_meta("temiz_sermaye", str(cq_sermaye))
    await db.close()
    print(f"\n  ✓ ÇIPA YAZILDI: temiz_cut={cq_gun} · temiz_equity=${cq_eq:,.2f} "
          f"· temiz_sermaye=${cq_sermaye:,.2f}")
    print(f"  Artık /status, /rapor, /stats ve heartbeat TEMİZ DÖNEM kârını")
    print(f"  gösterir. Bot'u yeniden başlatmana gerek yok.")


if __name__ == "__main__":
    asyncio.run(main())
