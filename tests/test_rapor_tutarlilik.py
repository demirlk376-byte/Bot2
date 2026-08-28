"""
test_rapor_tutarlilik.py — Telegram raporunun DOĞRU sayıyı göstermesi.

NEDEN VAR: 28 Ağustos 2026'da kullanıcı para ekledi ve rapor bunun tamamını
"Gerçek kâr" diye gösterdi ($82.64 → $152.40; bakiye artışı da tam $69.76).
Aynı gün üç farklı sayı "bakiye" etiketiyle görünüyordu:
    03:00 günlük özet   $283.29   (aslında YENİ GÜNÜN BAŞLANGIÇ equity'si)
    03:20 heartbeat     $266.42   (aslında SERBEST bakiye, kilitli marj hariç)
    11:27 /status       $280.51   (equity)
Arada tek işlem yok. Bu testler o üç hatanın geri gelmesini engelliyor.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram_bot import TelegramNotifier


class _SahteBorsa:
    """get_equity() borsanın gerçeği; get_balance() SERBEST bakiye (daha düşük)."""
    def __init__(self, free, equity):
        self._free, self._equity = free, equity
    async def get_balance(self): return self._free
    async def get_equity(self): return self._equity
    async def get_current_price(self, sym): return 100.0


class _SahteBorsaEquitysiz:
    """get_equity YOK → yeniden kurulum yoluna düşmeli."""
    def __init__(self, free): self._free = free
    async def get_balance(self): return self._free
    async def get_current_price(self, sym): return 100.0


class _SahtePortfoy:
    def __init__(self, poz=()): self._p = list(poz)
    def get_open_positions(self): return self._p
    def get_open_position_count(self): return len(self._p)
    def get_total_unrealized_pnl(self): return sum(
        p.direction * (100.0 - p.entry_price) * p.quantity for p in self._p)


class _SahteDB:
    def __init__(self, inception, deposits, defter_pnl):
        self._m = {"inception_balance": inception, "total_deposits": deposits}
        self._pnl = defter_pnl
    async def get_meta_float(self, k, d=0.0): return self._m.get(k, d)
    async def get_performance_summary(self, is_paper=None):
        return SimpleNamespace(total_pnl_usdt=self._pnl)


def _bot(borsa, portfoy, db):
    b = TelegramNotifier(SimpleNamespace(enabled=False, bot_token="", chat_id=""))
    b._exchange = borsa
    b._portfolio = portfoy
    b._db = db
    b._executor = SimpleNamespace(is_halted=lambda: False)
    b._app_config = SimpleNamespace(
        exchange=SimpleNamespace(paper_mode=False, leverage=10))
    b._initial_balance = 0.0
    return b


def test_equity_borsadan_okunur():
    """/status SERBEST bakiyeyi değil BORSANIN equity'sini göstermeli.
    Eski kod free+locked+uPnL diye YENİDEN KURUYORDU ve borsadan sapabiliyordu."""
    poz = [SimpleNamespace(symbol="BTC/USDT:USDT", direction=1,
                           entry_price=90.0, quantity=1.0)]
    b = _bot(_SahteBorsa(free=266.42, equity=280.51), _SahtePortfoy(poz),
             _SahteDB(190.0, 0.0, 90.51))
    eq, upnl = asyncio.run(b._equity_and_upnl())
    assert abs(eq - 280.51) < 1e-6, f"equity borsadan gelmeli, geldi: {eq}"
    assert abs(eq - 266.42) > 1.0, "SERBEST bakiye gösterilmemeli"
    print(f"  equity borsadan: ${eq:.2f} (serbest $266.42 DEĞİL) ✓")


def test_equity_okunamazsa_yeniden_kurulum():
    """get_equity yoksa/0 ise yeniden kurulum yoluna düşmeli — çökmemeli."""
    poz = [SimpleNamespace(symbol="BTC/USDT:USDT", direction=1,
                           entry_price=90.0, quantity=1.0)]
    b = _bot(_SahteBorsaEquitysiz(free=266.42), _SahtePortfoy(poz),
             _SahteDB(190.0, 0.0, 0.0))
    eq, upnl = asyncio.run(b._equity_and_upnl())
    beklenen = 266.42 + (90.0 * 1.0 / 10) + 10.0     # free + kilitli marj + uPnL
    assert abs(eq - beklenen) < 1e-6, f"yedek yol: {eq} != {beklenen}"
    print(f"  get_equity yokken yedek yol: ${eq:.2f} ✓")


def test_kaydedilmemis_para_yakalanir():
    """ASIL TEST — 28 Ağustos senaryosu.
    $190 sermaye, defterde $10 işlem kârı, ama equity $270: aradaki $70
    kaydedilmemiş bir para girişi. Rapor bunu SÖYLEMELİ."""
    b = _bot(_SahteBorsa(free=270.0, equity=270.0), _SahtePortfoy(),
             _SahteDB(inception=190.0, deposits=0.0, defter_pnl=10.0))
    uyari = asyncio.run(b._tutarlilik(equity=270.0, invested=190.0, upnl=0.0))
    assert uyari, "kaydedilmemiş $70 giriş YAKALANMALIYDI"
    assert "GİRİŞ" in uyari, uyari
    assert "para_ekle" in uyari, uyari
    print(f"  kaydedilmemiş $70 giriş yakalandı ✓")


def test_kayit_dogruysa_uyari_yok():
    """$70 deftere işlenmişse uyarı OLMAMALI — yanlış alarm sessizlikten kötü."""
    b = _bot(_SahteBorsa(free=270.0, equity=270.0), _SahtePortfoy(),
             _SahteDB(inception=190.0, deposits=70.0, defter_pnl=10.0))
    uyari = asyncio.run(b._tutarlilik(equity=270.0, invested=260.0, upnl=0.0))
    assert uyari == "", f"yanlış alarm: {uyari}"
    print("  kayıt doğruyken uyarı yok ✓")


def test_kucuk_sapma_alarm_uretmez():
    """Ücret/fonlama kaymaları eşiğin altında kalmalı."""
    b = _bot(_SahteBorsa(free=263.0, equity=263.0), _SahtePortfoy(),
             _SahteDB(inception=190.0, deposits=70.0, defter_pnl=5.0))
    uyari = asyncio.run(b._tutarlilik(equity=263.0, invested=260.0, upnl=0.0))
    assert uyari == "", f"küçük sapma alarm üretmemeli: {uyari}"
    print("  $2 sapma alarm üretmedi ✓")


def test_db_okunamazsa_sessiz():
    """DB patlarsa uyarı basma — yanlış hüküm, hükümsüzlükten kötü."""
    class _Patlak:
        async def get_meta_float(self, k, d=0.0): return d
        async def get_performance_summary(self, is_paper=None):
            raise RuntimeError("db kapalı")
    b = _bot(_SahteBorsa(free=270.0, equity=270.0), _SahtePortfoy(), _Patlak())
    uyari = asyncio.run(b._tutarlilik(equity=270.0, invested=190.0, upnl=0.0))
    assert uyari == "", "DB okunamazken sessiz kalmalı"
    print("  DB okunamazken sessiz ✓")


def test_heartbeat_equity_kullaniyor():
    """main.py heartbeat'i get_balance() (SERBEST) DEĞİL current_equity()
    kullanmalı — 03:20'deki $266.42 tam olarak bu hataydı."""
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    i = src.index("async def heartbeat_loop")
    blok = src[i:i + 4000]
    assert "executor.current_equity()" in blok, \
        "heartbeat equity okumuyor"
    assert "bal = await exchange.get_balance()" not in blok, \
        "heartbeat hâlâ SERBEST bakiye okuyor"
    assert "yatırılan" in blok, "heartbeat yatırılan sermayeyi göstermiyor"
    print("  heartbeat equity + yatırılan sermaye kullanıyor ✓")


def test_gunluk_ozet_etiketi_duzeltildi():
    """Günlük özete main.py start_equity gönderiyor; 'Balance' etiketi yanlıştı."""
    src = (Path(__file__).resolve().parent.parent / "telegram_bot.py").read_text()
    i = src.index("async def send_daily_summary")
    blok = src[i:i + 1500]
    assert "başlangıç equity" in blok, "günlük özet etiketi hâlâ yanıltıcı"
    assert 'f"Balance:' not in blok, "'Balance' etiketi hâlâ duruyor"
    print("  günlük özet etiketi düzeltildi ✓")


if __name__ == "__main__":
    print("test_rapor_tutarlilik — Telegram raporu doğru sayıyı gösteriyor mu?\n")
    for fn in (test_equity_borsadan_okunur,
               test_equity_okunamazsa_yeniden_kurulum,
               test_kaydedilmemis_para_yakalanir,
               test_kayit_dogruysa_uyari_yok,
               test_kucuk_sapma_alarm_uretmez,
               test_db_okunamazsa_sessiz,
               test_heartbeat_equity_kullaniyor,
               test_gunluk_ozet_etiketi_duzeltildi):
        fn()
    print("\n✓ RAPOR TUTARLILIK TESTLERİ GEÇTİ")
