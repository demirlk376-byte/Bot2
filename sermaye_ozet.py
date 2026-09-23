"""
sermaye_ozet.py — "YATIRDIGIM PARA NE KADAR, KAR NE KADAR" — TEK EKRAN.

Kullanici hakli olarak sordu: /status'taki "Yatirilan $280.38" dogru mu?
Bu arac o rakamin NEREDEN geldigini ve borsanin ne dedigini yan yana basar.

HICBIR SEY YAZMAZ. Emir gondermez, meta degistirmez. Yalniz okur.

Kullanim (VPS'te):
    cd /opt/bot2 && venv/bin/python sermaye_ozet.py

⚠ 90 GUN SINIRI: MEXC transfer gecmisini 90 gunden eskiye vermiyor. O yuzden
"borsadan okunan" satiri YALNIZCA son 90 gunu kapsar; ondan eskisi
`sermaye_taban` icinde tohum olarak durur ve borsadan DOGRULANAMAZ. Rakam
yanlissa duzeltmek icin: para_ekle.py (tutari SEN verirsin).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BOT_DIR)

from config import load_config          # noqa: E402
from database import Database           # noqa: E402
from exchange import LiveExchange       # noqa: E402


def _ts(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


async def ana() -> None:
    cfg = load_config()
    db = Database(cfg.database.path)
    await db.connect()
    ex = LiveExchange(cfg.exchange)
    await ex.connect()

    taban = await db.get_meta_float("sermaye_taban", 0.0)
    damga = await db.get_meta_float("sermaye_taban_ts", 0.0)
    ince = await db.get_meta_float("inception_balance", 0.0)
    dep = await db.get_meta_float("total_deposits", 0.0)

    try:
        bakiye = await ex.get_balance()
        eq = await ex.get_equity() if hasattr(ex, "get_equity") else None
    except Exception as e:
        bakiye, eq = None, None
        print(f"  (bakiye okunamadi: {e})")
    if eq is None:
        eq = bakiye

    doksan = int((datetime.now(timezone.utc) - timedelta(days=89)).timestamp() * 1000)
    son90 = await ex.fetch_transfers_in(doksan)

    print()
    print("=" * 56)
    print("  YATIRILAN SERMAYE — nereden geliyor")
    print("=" * 56)
    print(f"  /status'un kullandigi deger   : ${taban:,.2f}"
          if taban > 0 else
          f"  /status'un kullandigi deger   : ${ince + dep:,.2f}  (eski yol)")
    if taban > 0:
        print(f"    bu damgadan beri birikimli  : {_ts(damga) if damga else '—'}")
    print(f"  tohum (inception + deposits)  : ${ince + dep:,.2f}"
          f"   [{ince:,.2f} + {dep:,.2f}]")
    if son90 is None:
        print("  borsadan son 90 gun           : OKUNAMADI (yanit yok)")
    else:
        print(f"  borsadan son 90 gun (SPOT->VADELI): ${son90:,.2f}")
    print()
    print("=" * 56)
    print("  SIMDIKI PARA ve KAR")
    print("=" * 56)
    kullanilan = taban if taban > 0 else (ince + dep)
    if eq is None:
        print("  equity OKUNAMADI — kâr hesaplanamaz")
    else:
        kar = eq - kullanilan
        pct = (kar / kullanilan * 100) if kullanilan > 0 else 0.0
        print(f"  Equity (borsadan)             : ${eq:,.2f}")
        print(f"  Yatirilan                     : ${kullanilan:,.2f}")
        print(f"  KAR                           : ${kar:+,.2f}   %{pct:+.1f}")
        print(f"  kontrol: {kullanilan:,.2f} + {kar:+,.2f} = {kullanilan + kar:,.2f}")
    print()
    print("  ⚠ 90 gunden ESKI transferler borsadan dogrulanamaz; onlar tohumun")
    print("    icinde. Rakam yanlissa: para_ekle.py --tespit (dokum) ve")
    print("    para_ekle.py <tutar> --kaydet (duzeltme; tutari SEN verirsin).")
    print()
    await ex.close()
    await db.close()


if __name__ == "__main__":
    asyncio.run(ana())
