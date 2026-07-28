"""
test_protection_watchdog.py — açık pozisyonun borsa tarafı stop'u kaybolursa fark edilir mi?

KÖR NOKTA (bu testin kapattığı): koruma SADECE iki noktada doğrulanıyordu —
girişte (has_sltp_orders, 3 deneme) ve yeniden başlatmada (resync). Girişte
korumalı açılıp ORTA ÖMÜRDE stop'u kaybolan bir pozisyonu (MEXC tarafı iptal,
netleşme/kısmi dolum olayı) hiçbir şey tekrar kontrol etmiyordu. Bot başında
kimse yokken bu, hesabın büyük bir kısmını götürebilecek TEK arıza biçimi:
pozisyon aşağı sınırı olmadan koşar.

main._verify_protection doğrulananlar:
  1. Koruma VAR (True)          → hiçbir şey yapılmaz, resync ÇAĞRILMAZ (salt-okuma).
  2. Okuma BELİRSİZ (None)      → dokunulmaz. Tek bir başarısız okuma, gerçekte
                                  korumalı bir pozisyonda cancel+re-place tetiklemez.
  3. İlk okuma False, ikinci True → dokunulmaz (çift okuma teyidi; geçici boş yanıt).
  4. İKİ okuma da False         → CONFIRMED-naked: alarm + resync ile yeniden kurulur.
  5. Okuma istisna atarsa       → yutulur, resync ÇAĞRILMAZ (fail-quiet, fail-open değil).

Run:  python tests/test_protection_watchdog.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.update({"API_KEY": "x", "API_SECRET": "x", "MEXC_API_KEY": "x",
                   "MEXC_API_SECRET": "x"})

import main


class _FakeExchange:
    """has_sltp_orders için senaryolanmış cevaplar döner.

    None = okuma yapılamadı (belirsiz), False = teyitli korumasız, True = korumalı.
    Bir eleman Exception ise fırlatılır."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.reads = 0

    async def has_sltp_orders(self, symbol):
        self.reads += 1
        a = self.answers.pop(0) if self.answers else True
        if isinstance(a, Exception):
            raise a
        return a


class _FakeExecutor:
    def __init__(self):
        self.resyncs = []

    async def _resync_symbol_stops_locked(self, symbol):
        self.resyncs.append(symbol)
        return True


async def _case(name, answers, *, expect_resync, expect_alert):
    ex = _FakeExchange(answers)
    exe = _FakeExecutor()
    alerts = []

    async def _hook(msg, level="ERROR"):
        alerts.append((msg, level))

    main.exchange, main.executor, main._alert_hook = ex, exe, _hook
    # Çift-okuma teyidi arasındaki 3sn'yi testte bekleme.
    real_sleep = asyncio.sleep
    async def _fast_sleep(s, *a, **k): return await real_sleep(0)
    asyncio.sleep = _fast_sleep
    try:
        await main._verify_protection("SOL/USDT:USDT")
    finally:
        asyncio.sleep = real_sleep

    got_resync = exe.resyncs == ["SOL/USDT:USDT"]
    assert got_resync == expect_resync, (
        f"{name}: resync beklenen={expect_resync} gerçekleşen={exe.resyncs}")
    assert bool(alerts) == expect_alert, (
        f"{name}: alarm beklenen={expect_alert} gerçekleşen={alerts}")
    print(f"✓ {name}  (okuma={ex.reads}, resync={len(exe.resyncs)}, alarm={len(alerts)})")


async def _run():
    # 1) Korumalı: tek okuma yeter, hiçbir mutasyon yok.
    await _case("koruma VAR (True) → dokunulmaz",
                [True], expect_resync=False, expect_alert=False)

    # 2) Belirsiz okuma: her endpoint başarısız oldu → asla müdahale etme.
    await _case("okuma BELİRSİZ (None) → dokunulmaz",
                [None], expect_resync=False, expect_alert=False)

    # 3) Geçici boş yanıt: ikinci okuma korumayı görüyor → müdahale yok.
    await _case("False→True (geçici) → çift okuma kurtarır",
                [False, True], expect_resync=False, expect_alert=False)

    # 3b) İkinci okuma belirsizleşirse de müdahale yok (yalnız teyitli naked).
    await _case("False→None (belirsiz) → dokunulmaz",
                [False, None], expect_resync=False, expect_alert=False)

    # 4) Gerçek arıza: iki okuma da korumasız → yeniden kur + alarm.
    await _case("False→False (TEYİTLİ korumasız) → resync + alarm",
                [False, False], expect_resync=True, expect_alert=True)

    # 5) İstisna: sessizce geç, pozisyonu kurcalama.
    await _case("okuma istisna atıyor → dokunulmaz",
                [RuntimeError("mexc 510")], expect_resync=False, expect_alert=False)
    await _case("ilk False, ikinci istisna → dokunulmaz",
                [False, RuntimeError("timeout")], expect_resync=False, expect_alert=False)

    # 6) Borsa bu API'yi sunmuyorsa (paper/eski istemci) sessizce çık.
    class _NoApi:
        pass
    exe = _FakeExecutor()
    main.exchange, main.executor = _NoApi(), exe
    await main._verify_protection("SOL/USDT:USDT")
    assert exe.resyncs == [], "has_sltp_orders yoksa resync çağrılmamalı"
    print("✓ has_sltp_orders API yok → sessizce çıkar")

    # 7) Nöbet sıklığı: 2 dk'lık döngüde ~20 dk'ya denk gelmeli (hız limiti payı).
    assert main.PROTECTION_CHECK_EVERY == 10, "watchdog kadansı değişmiş"
    print(f"✓ kadans: her {main.PROTECTION_CHECK_EVERY} döngü = "
          f"{main.PROTECTION_CHECK_EVERY * 2} dk")


def main_() -> int:
    asyncio.run(_run())
    print("\n" + "=" * 66)
    print("✓ KORUMA NÖBETÇİSİ DOĞRU — yalnız TEYİTLİ korumasızda müdahale eder")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main_())
