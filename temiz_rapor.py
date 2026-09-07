"""
temiz_rapor.py — "temiz dönemde bot neler yapmış?" — TEK SAYFA CANLI RAPOR.

Kullanıcı bir ay beklemeyi kabul etmişti; temiz dönem (2026-07-17 sonrası)
artık ~1.7 ay. Bu araç o dönemin TAM dökümünü çıkarır: ne kazandı, hangi kol,
hangi coin, en iyi/en kötü işlemler, ve ankorun AYNI UZUNLUKTAKİ dönem için
beklentisiyle kıyas.

İKİ AYRI RAKAM, KARIŞTIRILMIYOR:
  • PARA  = equity − yatırılan sermaye, çıpaya göre düzeltilmiş (BORSA GERÇEĞİ)
  • DEFTER = işlem kayıtlarının toplamı (ŞİŞKİN: ücret 1bp yazılıyor, fonlama
    kalemi yok, eski çıkışlar seviye fiyatından — DURUM 4t'de ölçüldü)
Defter rakamı STRATEJİ değerlendirmesi için, PARA rakamı cebin için.

⚠ Kaç işlemle konuştuğumuzu her satırda söyler. n<30 iken WR/PF GÜRÜLTÜDÜR;
  ankorun σ_R'si 1.465 ve bu ölçekte aylık beklenti gürültünün altında kalır.

Kullanım (VPS'te):  venv/bin/python temiz_rapor.py
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


def _kol(js):
    try:
        d = json.loads(js or "{}")
        return str(d.get("strategy") or d.get("sleeve") or "?")
    except Exception:
        return "?"


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
    if not cut:
        raise SystemExit("⛔ Çıpa kurulmamış — önce temiz_donem.py --yaz")

    lx = LiveExchange(cfg.exchange.api_key, cfg.exchange.api_secret,
                      leverage=cfg.exchange.leverage,
                      margin_mode=cfg.exchange.margin_mode)
    try:
        await lx.initialize(cfg.exchange.symbols[0])
    except Exception as e:
        print(f"  (initialize uyarısı: {e})")
    try:
        eq = await lx.get_equity()
        upnl = 0.0
        for s in cfg.exchange.symbols:
            try:
                pz = await lx.get_position(s)
                if pz:
                    upnl += float(getattr(pz, "unrealized_pnl", 0.0) or 0.0)
            except Exception:
                pass
    finally:
        try:
            await lx.close()
        except Exception:
            pass

    con = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT symbol,side,entry_price,exit_price,quantity,sl_price,pnl_usdt,"
        "entry_time,exit_time,exit_reason,strategy_scores FROM trades "
        "WHERE is_paper=0 AND entry_time>=? ORDER BY entry_time", (str(cut),))]
    con.close()
    kapali = [r for r in rows if r["exit_time"]]
    acik = [r for r in rows if not r["exit_time"]]

    gun = (datetime.now(timezone.utc)
           - datetime.strptime(str(cut), "%Y-%m-%d").replace(tzinfo=timezone.utc)).days
    print("=" * 76)
    print(f"TEMİZ DÖNEM RAPORU — {cut} sonrası ({gun} gün ≈ {gun/30.4:.1f} ay)")
    print("=" * 76)

    # ── PARA (borsa gerçeği) ────────────────────────────────────────────────
    para = eq - c_eq - (s_now - c_sm) if (c_eq > 0 and c_sm > 0) else None
    print(f"\n  💰 PARA (borsa gerçeği)")
    print(f"     equity şimdi          ${eq:>9,.2f}")
    print(f"     equity çıpa ({cut})  ${c_eq:>9,.2f}")
    print(f"     çıpadan beri eklenen  ${s_now - c_sm:>+9,.2f}")
    if para is not None:
        print(f"     → TEMİZ DÖNEM KÂRI    ${para:>+9,.2f}")
        # sermaye-ağırlıklı getiri denemesi: para geç geldiyse payda şişer
        print(f"       (çıpa equity'sine göre %{para/c_eq*100:+.1f} — ama araya")
        print(f"        sermaye girdiyse gerçek oran bundan DÜŞÜKTÜR)")
        print(f"       aylık ortalama        ${para/max(gun/30.4, 0.1):>+9,.2f}")

    # ── DEFTER (strateji değerlendirmesi) ───────────────────────────────────
    d_pnl = sum(float(r["pnl_usdt"] or 0) for r in kapali)
    kaz = [r for r in kapali if (r["pnl_usdt"] or 0) > 0]
    gp = sum(r["pnl_usdt"] for r in kaz)
    gl = -sum(r["pnl_usdt"] for r in kapali if (r["pnl_usdt"] or 0) < 0)
    print(f"\n  📊 DEFTER (strateji için — PARA DEĞİL, şişkin)")
    print(f"     kapanan {len(kapali)} · açık {len(acik)} · uPnL ${upnl:+,.2f}")
    if kapali:
        print(f"     defter PnL ${d_pnl:+,.2f} · WR %{len(kaz)/len(kapali)*100:.0f} "
              f"· PF {gp/gl if gl > 0 else float('inf'):.2f}")
        if para is not None:
            print(f"     ⚠ defter ${d_pnl:+,.2f} vs para ${para:+,.2f} → fark "
                  f"${d_pnl-para:+,.2f} (ücret/fonlama/eski çıkış fiyatı)")
    if len(kapali) < 30:
        print(f"     ⚠ n={len(kapali)} < 30 → WR/PF GÜRÜLTÜ. Yön göstergesi,")
        print(f"       sonuç değil. σ_R=1.465, bu örneklemde ayırt edilemez.")

    # ── KOL ve COİN ─────────────────────────────────────────────────────────
    for ad, anahtar in (("KOL", lambda r: _kol(r["strategy_scores"])),
                        ("COİN", lambda r: r["symbol"].split("/")[0])):
        agg = {}
        for r in kapali:
            k = anahtar(r)
            a = agg.setdefault(k, [0, 0.0, 0])
            a[0] += 1; a[1] += float(r["pnl_usdt"] or 0)
            a[2] += 1 if (r["pnl_usdt"] or 0) > 0 else 0
        if not agg:
            continue
        print(f"\n  {ad} kırılımı")
        for k in sorted(agg, key=lambda x: -agg[x][1]):
            n, p, w = agg[k]
            print(f"     {k:<8s} n={n:<3d} ${p:>+8.2f}  WR %{w/n*100:>3.0f}")

    # ── EN İYİ / EN KÖTÜ ────────────────────────────────────────────────────
    if kapali:
        sirali = sorted(kapali, key=lambda r: float(r["pnl_usdt"] or 0))
        print(f"\n  EN KÖTÜ 3")
        for r in sirali[:3]:
            print(f"     {str(r['entry_time'])[:10]} {r['symbol'].split('/')[0]:<5s} "
                  f"{_kol(r['strategy_scores']):<8s} {r['side']:<5s} "
                  f"${float(r['pnl_usdt'] or 0):+7.2f}  {r['exit_reason']}")
        print(f"  EN İYİ 3")
        for r in sirali[-3:][::-1]:
            print(f"     {str(r['entry_time'])[:10]} {r['symbol'].split('/')[0]:<5s} "
                  f"{_kol(r['strategy_scores']):<8s} {r['side']:<5s} "
                  f"${float(r['pnl_usdt'] or 0):+7.2f}  {r['exit_reason']}")

    # ── ANKOR BEKLENTİSİYLE KIYAS ───────────────────────────────────────────
    print(f"\n  🎯 ANKOR BEKLENTİSİYLE KIYAS ({gun} gün)")
    print(f"     Ankor: 1579 işlem / 3.24 yıl → ayda ~40 işlem, $190 tabanda")
    print(f"     aylık ort +%18.7 · en kötü ay −%21.0 · maxDD %24.4")
    bek_islem = 40 * gun / 30.4
    print(f"     bu sürede BEKLENEN işlem ≈ {bek_islem:.0f} · GERÇEKLEŞEN {len(kapali)}")
    if para is not None and c_eq > 0:
        bek_kar = 0.187 * c_eq * gun / 30.4
        print(f"     bu sürede BEKLENEN kâr ≈ ${bek_kar:+,.0f} · GERÇEKLEŞEN ${para:+,.0f}")
        print(f"     ⚠ Bu kıyas TEK BAŞINA anlam taşımaz: {gun/30.4:.1f} ayda σ")
        print(f"       beklentiden büyük. Ankorun kendi aylık dağılımında")
        print(f"       pozitif ay oranı ~%80 — yani tek bir dönem hiçbir şey kanıtlamaz.")


if __name__ == "__main__":
    asyncio.run(main())
