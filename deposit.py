"""deposit.py — para yatırma/çekme kaydı (panelin gerçek kârı doğru göstermesi için).

Canlı bot bakiyeyi MEXC'ten okur; ama "kâr" demek için botun ne kadar parayla
başladığını + sonradan ne kadar EKLEDİĞİNİ bilmesi gerekir. Yoksa her ay
eklediğin $150 panelde sahte "kâr" gibi görünür.

Bu script yatırdığın/çektiğin parayı trades.db'ye kaydeder. Panel her tick'te
bunu okur — bot'u yeniden başlatmana GEREK YOK.

Kullanım (VPS'te, /opt/bot2 içinde):
    venv/bin/python deposit.py 150        # 150$ yatırdın → ekle
    venv/bin/python deposit.py -- -50     # 50$ çektin   → çıkar (negatif)
    venv/bin/python deposit.py            # mevcut durumu göster

Not: Bu sadece MUHASEBE kaydıdır — gerçek parayı MEXC'e ayrıca yatırman gerekir.
"""
from __future__ import annotations

import asyncio
import os
import sys

from database import Database


def _db_path() -> str:
    # config.py'deki DB_PATH ile aynı varsayılan (./trades.db).
    return os.getenv("DB_PATH", "./trades.db")


async def _run(amount: float | None) -> int:
    db = Database(_db_path())
    await db.initialize()
    try:
        inception = await db.get_meta_float("inception_balance", 0.0)
        deposits = await db.get_meta_float("total_deposits", 0.0)

        if amount is None:
            invested = inception + deposits
            print("─" * 44)
            print(f"  Başlangıç bakiyesi : ${inception:,.2f}")
            print(f"  Sonradan eklenen   : ${deposits:,.2f}")
            print(f"  TOPLAM YATIRILAN   : ${invested:,.2f}")
            print("─" * 44)
            print("  Yeni yatırma için:  venv/bin/python deposit.py <tutar>")
            return 0

        new_total = await db.add_deposit(amount)
        invested = inception + new_total
        verb = "eklendi" if amount >= 0 else "çıkarıldı"
        print(f"✓ ${abs(amount):,.2f} {verb}.")
        print(f"  Toplam eklenen   : ${new_total:,.2f}")
        print(f"  TOPLAM YATIRILAN : ${invested:,.2f}")
        print("  Panel birkaç saniye içinde güncellenir (restart gerekmez).")
        return 0
    finally:
        await db.close()


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--"]
    amount: float | None = None
    if args:
        try:
            amount = float(args[0])
        except ValueError:
            print(f"Geçersiz tutar: {args[0]!r}. Örnek: deposit.py 150")
            return 1
    return asyncio.run(_run(amount))


if __name__ == "__main__":
    sys.exit(main())
