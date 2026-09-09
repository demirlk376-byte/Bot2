"""
ucret_coin.py — ÜCRET COIN BAZINDA nereye gidiyor?

KULLANICI: "coinlerin bazıları mesela NEAR zaten 0fee."

NEDEN ÖNEMLİ: `kar_farki.py` toplam ödenen ücreti ölçtü (~$104/yıl, brüt kârın
%23'ü) ama bunu HOMOJEN varsaydım. Bazı pariteler sıfır-ücretliyse yük
dağılımı eşit değil ve iki şey değişir:

  1) İNDİRİM KOLUNUN DEĞERİ. MX/VIP indirimi yalnız ÜCRET ÖDEYEN işlemlere
     uygulanır. Hacmimizin çoğu zaten sıfır-ücretliyse indirim kolu
     düşündüğümden KÜÇÜK; tersine yoğunlaşmışsa BÜYÜK.

  2) BACKTEST'İN ÜCRET VARSAYIMI YANLIŞ. `deployed_backtest.FEE = 0.0001`
     TÜM coinlere aynı 1bp/taraf uyguluyor. Sıfır-ücretli coinlerde ankor
     maliyeti FAZLA sayıyor (o coinlerin net edge'i göründüğünden İYİ),
     ücretli coinlerde ise ölçülen gerçek ~2.5bp olduğu için AZ sayıyor.
     Yani ankorun coin-bazlı ekonomisi çarpık.

⚠ BU BİR COIN SEÇİMİ ÖNERİSİ DEĞİL. coin_expand (DURUM 4) coin değiştirmenin
  en kötü ayı −21 → −58.8 yaptığını ölçtü; o duvar burada da geçerli.
  Buradaki fark: ücret tarifesi ÖNCEDEN BİLİNEN YAPISAL bir özellik, geçmiş
  performans DEĞİL — yani en azından aşırı-uydurma riski taşımıyor. Ama
  korelasyon duvarını aşmıyor. Bu araç ÖLÇER, öneri yapmaz.

Kullanım (VPS'te):  venv/bin/python ucret_coin.py [gun]
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from config import load_config          # noqa: E402
from exchange import LiveExchange       # noqa: E402


async def main():
    gun = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 89
    gun = min(gun, 89)
    since = int((time.time() - gun * 86400) * 1000)
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
        print("=" * 74)
        print(f"ÜCRET COIN BAZINDA — son {gun} gün, borsanın kendi dolum kaydı")
        print("=" * 74)
        satir = []
        okunamayan = []
        for sym in cfg.exchange.symbols:
            c = sym.split("/")[0]
            try:
                fills = await ex.fetch_my_trades(sym, since, 200)
            except Exception as e:
                okunamayan.append(f"{c}({type(e).__name__})")
                continue
            n = 0; ucret = 0.0; yabanci = {}
            for f in (fills or []):
                if not isinstance(f, dict):
                    continue
                n += 1
                fee = f.get("fee") or {}
                cur = (fee.get("currency") or "USDT").upper()
                try:
                    v = float(fee.get("cost") or 0.0)
                except (TypeError, ValueError):
                    continue
                if cur != "USDT":
                    yabanci[cur] = yabanci.get(cur, 0.0) + v
                    continue
                ucret += v
            if n:
                satir.append((c, n, ucret, yabanci))
            await asyncio.sleep(0.2)

        if okunamayan:
            print(f"  ⚠ OKUNAMAYAN: {', '.join(okunamayan)}")
            print(f"     Bu coinler aşağıdaki toplamda YOK — eksik sayılıyor,")
            print(f"     sıfır DEĞİL.\n")
        if not satir:
            print("  ⛔ Hiç dolum okunamadı — hüküm YOK.")
            return

        satir.sort(key=lambda r: -r[2])
        top_n = sum(r[1] for r in satir); top_u = sum(r[2] for r in satir)
        print(f"  {'coin':<6s}{'dolum':>7s}{'ücret$':>10s}{'$/dolum':>10s}  durum")
        sifir = []
        for c, n, u, yb in satir:
            bd = u / n if n else 0.0
            durum = "★ SIFIR-ÜCRET" if u < 0.005 else ""
            if u < 0.005:
                sifir.append(c)
            ek = ("  +" + ",".join(f"{k}:{v:.6f}" for k, v in yb.items())) if yb else ""
            print(f"  {c:<6s}{n:>7d}{u:>10.4f}{bd:>10.4f}  {durum}{ek}")
        print(f"  {'TOPLAM':<6s}{top_n:>7d}{top_u:>10.4f}")

        print(f"\n{'='*74}\nNE DEĞİŞİYOR\n{'='*74}")
        if sifir:
            n_sifir = sum(r[1] for r in satir if r[0] in sifir)
            print(f"  SIFIR-ÜCRETLİ coinler: {', '.join(sifir)}")
            print(f"    {n_sifir}/{top_n} dolum (%{n_sifir/top_n*100:.0f}) ücretsiz")
        odeyen = [r for r in satir if r[2] >= 0.005]
        if odeyen:
            n_od = sum(r[1] for r in odeyen); u_od = sum(r[2] for r in odeyen)
            yil = u_od * 365 / gun
            print(f"\n  ÜCRET ÖDEYEN coinler: {', '.join(r[0] for r in odeyen)}")
            print(f"    {n_od} dolum · ${u_od:.2f} ({gun} günde) · ~${yil:.0f}/yıl")
            print(f"\n  → İNDİRİM KOLUNUN GERÇEK DEĞERİ (yalnız bu kısma uygulanır):")
            for ind in (0.20, 0.50):
                print(f"      %{ind*100:.0f} indirim → yılda +${yil*ind:.0f}")
        print(f"\n  ⚠ Ankorun `FEE=0.0001` varsayımı TÜM coinlere aynı 1bp/taraf")
        print(f"    uyguluyor. Yukarıdaki $/dolum sütunu bununla karşılaştırılırsa")
        print(f"    hangi coinlerde ankorun maliyeti FAZLA, hangilerinde AZ saydığı")
        print(f"    görülür. Sıfır-ücretlilerde ankor o coinleri OLDUĞUNDAN KÖTÜ")
        print(f"    gösteriyor demektir.")
    finally:
        try:
            await lx.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
