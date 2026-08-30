"""
kar_farki.py — "Defter $123.86 diyor, borsa $61.06 diyor. $62.80 NEREYE GİTTİ?"

SERMAYE DENKLEMİ KAPANDI (DURUM 4s): yatırılan $280.38, equity $341.44,
GERÇEK kâr $+61.06. Ama defterin kapanan işlem PnL'i $+123.86. Defter
2.5 ayda $62.80 FAZLA yazmış — gerçek kârın kendisinden büyük bir sapma.
Yıllığa vurulursa ~$300; ankorun bu ölçekteki beklentisinin yarısı kadar.

Bu araç farkı KALEM KALEM kapatmaya çalışır — hepsi BORSA kaydından:
  1) ÜCRET   — defter nominal×1bp yazıyor; gerçek dolumların ücreti kaç?
  2) FONLAMA — defterde HİÇ kalemi yok, borsa öder/alır
  3) ÇIKIŞ KAYMASI — main.py mutabakat yolu çıkışı SEVİYE fiyatından
     yazıyordu (2026-08-29'da düzeltildi). Geçmiş kayıtlarda etkisi ne?
  4) KALAN   — kapanmayan kısım

⚠ HÜKÜM KURALLARI (önceki araçların dersleri):
  • Okunamayan kaynak SIFIR sayılmaz — "okunamadı" diye raporlanır.
  • Dolum kapsaması %80'in altındaysa oran-dışı hüküm VERİLMEZ.
  • Aynı para iki kez sayılmaz (deposits/transfers dersi).

Kullanım (VPS'te):  cd /opt/bot2 && venv/bin/python kar_farki.py
                    venv/bin/python kar_farki.py 89     # pencere (gün)
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from config import load_config          # noqa: E402
from exchange import LiveExchange       # noqa: E402


async def dene(ad, coro):
    """Bir kaynağı dener. Başarısızsa SESSİZ GEÇMEZ — sebebini döner."""
    try:
        return True, await coro, None
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"


def defter(db_path, since_iso):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id,symbol,side,entry_price,exit_price,quantity,sl_price,tp_price,"
        "entry_time,exit_time,pnl_usdt,fees_usdt,exit_reason,strategy_scores "
        "FROM trades WHERE is_paper=0 AND exit_time IS NOT NULL "
        "AND entry_time >= ? ORDER BY entry_time", (since_iso,))]
    acik = con.execute(
        "SELECT COUNT(*) FROM trades WHERE is_paper=0 AND exit_time IS NULL"
    ).fetchone()[0]
    inc = con.execute("SELECT value FROM meta WHERE key='inception_balance'").fetchone()
    dep = con.execute("SELECT value FROM meta WHERE key='total_deposits'").fetchone()
    con.close()
    return rows, acik, float(inc[0] if inc else 0), float(dep[0] if dep else 0)


async def main():
    gun = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 89
    gun = min(gun, 89)                     # MEXC varlık uç noktaları 90 günle sınırlı
    since_ms = int((time.time() - gun * 86400) * 1000)
    since_iso = datetime.fromtimestamp(since_ms / 1000, timezone.utc).isoformat()

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
    ex = lx._exchange
    try:
        await _govde(lx, ex, cfg, gun, since_ms, since_iso)
    finally:
        try:
            await lx.close()
        except Exception:
            pass


async def _govde(lx, ex, cfg, gun, since_ms, since_iso):
    syms = list(cfg.exchange.symbols)
    eq = await lx.get_equity()
    rows, acik, inc, dep = defter(cfg.db_path, since_iso)
    yatirilan = inc + dep
    d_pnl = sum(float(r["pnl_usdt"] or 0) for r in rows)
    d_fee = sum(float(r["fees_usdt"] or 0) for r in rows)

    print("=" * 78)
    print(f"KÂR FARKI — defter neden borsadan fazla yazıyor? (son {gun} gün)")
    print("=" * 78)
    print(f"  Borsa equity              : ${eq:,.2f}")
    print(f"  Yatırılan sermaye (defter): ${yatirilan:,.2f}  "
          f"(köken ${inc:,.2f} + ek ${dep:,.2f})")
    gercek = eq - yatirilan
    print(f"  → GERÇEK kâr              : ${gercek:+,.2f}")
    print(f"  Defter: {len(rows)} kapanan işlem PnL ${d_pnl:+,.2f} "
          f"(kaydettiği ücret ${d_fee:,.2f})")
    if acik:
        print(f"  ⚠ {acik} AÇIK pozisyon var — uPnL farkı bozar, "
              f"pozisyon yokken tekrar çalıştır.")
    fark = d_pnl - gercek
    print(f"\n  KAPATILACAK FARK: ${fark:+,.2f}")

    # ── 1) GERÇEK ÜCRET ──────────────────────────────────────────────────────
    print(f"\n{'='*78}\n1) ÜCRET — defter nominal×1bp yazıyor, gerçek ne?\n{'='*78}")
    fills = []
    hata_f = 0
    for s in syms:
        ok, r, err = await dene("fetch_my_trades", ex.fetch_my_trades(s, since_ms, 200))
        if not ok:
            print(f"  {s:<18s} — HATA: {err}")
            hata_f += 1
            continue
        fills += list(r or [])
        await asyncio.sleep(0.25)
    g_fee = None
    if fills:
        g_fee = 0.0
        okunmayan = 0
        for f in fills:
            c = (f.get("fee") or {}).get("cost")
            if c is None:
                okunmayan += 1
                continue
            try:
                g_fee += float(c)
            except (TypeError, ValueError):
                okunmayan += 1
        print(f"  {len(fills)} dolum okundu ({hata_f} sembol hatalı, "
              f"{okunmayan} dolumda ücret alanı boş)")
        print(f"  GERÇEK ücret ${g_fee:,.4f}  ·  defterin yazdığı ${d_fee:,.4f}")
        print(f"  → ÜCRET AÇIĞI: ${g_fee - d_fee:+,.4f}")
        # kapsama: her işlem en az 2 dolum (giriş+çıkış) üretir
        bek = max(1, len(rows) * 2)
        kaps = len(fills) / bek
        print(f"  kapsama: {len(fills)} dolum / ~{bek} beklenen = %{kaps*100:.0f}")
        if kaps < 0.8:
            print(f"  ⚠ Kapsama %80'in ALTINDA — bu kalem EKSİK, toplam hüküm")
            print(f"    bu rakamla kapatılamaz.")
    else:
        print("  ⚠ HİÇ dolum okunamadı — ücret kalemi BİLİNMİYOR (sıfır DEĞİL).")

    # ── 2) FONLAMA ───────────────────────────────────────────────────────────
    print(f"\n{'='*78}\n2) FONLAMA — defterde HİÇ kalemi yok\n{'='*78}")
    fon = None
    if hasattr(ex, "fetch_funding_history"):
        tot = 0.0; n = 0; hata = 0
        for s in syms:
            ok, r, err = await dene("fetch_funding_history",
                                    ex.fetch_funding_history(s, since_ms, 200))
            if not ok:
                hata += 1
                continue
            for x in (r or []):
                try:
                    tot += float(x.get("amount") or 0.0); n += 1
                except (TypeError, ValueError):
                    pass
            await asyncio.sleep(0.25)
        if hata == len(syms):
            print(f"  ⚠ HİÇBİR sembolde okunamadı — fonlama BİLİNMİYOR.")
        else:
            fon = tot
            print(f"  {n} fonlama kaydı ({hata} sembol okunamadı) · "
                  f"toplam ${fon:+,.4f}")
    else:
        print("  fetch_funding_history — ccxt'de YOK")

    # ── 3) ÇIKIŞ KAYMASI ─────────────────────────────────────────────────────
    print(f"\n{'='*78}\n3) ÇIKIŞ KAYMASI — defter SEVİYE fiyatı mı yazmış?\n{'='*78}")
    print("  main.py mutabakat yolu çıkışı sl_price/tp_price'tan yazıyordu")
    print("  (2026-08-29'da gerçek dolumdan yazacak şekilde düzeltildi).")
    print("  Geçmiş kayıtlarda: defterin çıkış fiyatı SEVİYEYE ne kadar yakın?")
    tam = yakin = uzak = 0
    for r in rows:
        xp = float(r["exit_price"] or 0)
        if xp <= 0:
            continue
        for lvl_ad, lvl in (("sl", float(r["sl_price"] or 0)),
                            ("tp", float(r["tp_price"] or 0))):
            if lvl <= 0:
                continue
            d = abs(xp - lvl) / lvl
            if d < 1e-9:
                tam += 1; break
            if d < 5e-4:
                yakin += 1; break
        else:
            uzak += 1
    top = tam + yakin + uzak
    if top:
        print(f"  {top} kapanan işlem: seviyeye TAM eşit {tam} (%{tam/top*100:.0f}) · "
              f"<5bp {yakin} · uzak {uzak}")
        print(f"  → 'TAM eşit' oranı yüksekse defter gerçek dolumu DEĞİL seviyeyi")
        print(f"    yazmış demektir; her birinde kayma kadar FAZLA kâr yazılmıştır.")
        if tam and fills:
            print(f"    Ölçülen giriş kayması 15.3bp (DURUM). {tam} çıkışta benzer")
            print(f"    bir kayma ~${tam * 0.00153 * (sum(float(r['entry_price'] or 0)*float(r['quantity'] or 0) for r in rows)/max(len(rows),1)):.2f} eder — KABA tahmin, ölçüm değil.")
    else:
        print("  (karşılaştırılacak kayıt yok)")

    # ── KÖPRÜ ────────────────────────────────────────────────────────────────
    print(f"\n{'='*78}\nKÖPRÜ — fark kapandı mı?\n{'='*78}")
    print(f"  defter kapanan PnL                 ${d_pnl:>+9.2f}")
    bilinen = 0.0
    eksik = []
    if g_fee is not None:
        print(f"  − ücret açığı (gerçek−defter)      ${-(g_fee-d_fee):>+9.2f}")
        bilinen += -(g_fee - d_fee)
    else:
        eksik.append("ücret")
    if fon is not None:
        print(f"  + fonlama                          ${fon:>+9.2f}")
        bilinen += fon
    else:
        eksik.append("fonlama")
    kalan = d_pnl + bilinen - gercek
    print(f"  {'─'*46}")
    print(f"  = açıklanan sonrası                ${d_pnl+bilinen:>+9.2f}")
    print(f"    gerçek kâr                       ${gercek:>+9.2f}")
    print(f"    KAPANMAYAN                       ${kalan:>+9.2f}")
    if eksik:
        print(f"\n  ⚠ HÜKÜM EKSİK — okunamayan kalem(ler): {', '.join(eksik)}.")
        print(f"    Bunlar SIFIR sayılmadı; kapanmayan rakam bu yüzden şişkin.")
    elif abs(kalan) < max(3.0, abs(gercek) * 0.05):
        print(f"\n  ✓ FARK KAPANDI. Kalan ${kalan:+.2f} ölçüm gürültüsü seviyesinde.")
    else:
        print(f"\n  ⛔ ${kalan:+.2f} HÂLÂ AÇIK. Ücret ve fonlama açıklamıyor.")
        print(f"    En güçlü kalan aday: ÇIKIŞ KAYMASI (bölüm 3) — defter")
        print(f"    seviye fiyatından yazdıysa her çıkışta kayma kadar fazla")
        print(f"    kâr yazılmıştır. 2026-08-29 düzeltmesi bunu İLERİYE dönük")
        print(f"    kapatıyor; geçmiş kayıtlar düzelmiyor.")


if __name__ == "__main__":
    asyncio.run(main())
