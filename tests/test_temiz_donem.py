"""
test_temiz_donem.py — kâr rakamları TEMİZ DÖNEME göre mi veriliyor?

KULLANICI İSTEĞİ: "her komuttaki kâr/zarar temiz döneme göre verilsin, o
dönemden gerisini yok kabul edeceğiz, hiçbir iz olmayacak."

Formül:
    temiz kâr = equity_şimdi − equity_çıpa − (sermaye_şimdi − sermaye_çıpa)

Sondaki terim ŞART: araya giren sermaye eklemeleri düşülmezse yatırılan para
kâr sanılır — 2026-08-28'de tam bu oldu ($82.51 sermaye, kâr diye raporlandı).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram_bot import TelegramNotifier


class _DB:
    def __init__(self, cut=None, c_eq=0.0, c_sm=0.0):
        self._m = {"temiz_cut": cut, "temiz_equity": c_eq, "temiz_sermaye": c_sm}
    async def get_meta(self, k):
        return self._m.get(k)
    async def get_meta_float(self, k, d=0.0):
        v = self._m.get(k)
        return float(v) if v not in (None, "") else d


def _bot(db):
    b = TelegramNotifier(SimpleNamespace(enabled=False, bot_token="", chat_id=""))
    b._db = db
    return b


def test_cipa_yoksa_None():
    """Çıpa kurulmamışsa uydurma YAPILMAZ — çağıran her-zamana düşer."""
    assert asyncio.run(_bot(_DB())._temiz(341.0, 280.0)) is None
    assert asyncio.run(_bot(_DB("2026-07-16", 0.0, 209.0))._temiz(341.0, 280.0)) is None
    assert asyncio.run(_bot(_DB("2026-07-16", 209.0, 0.0))._temiz(341.0, 280.0)) is None
    print("  çıpa eksikse None (uydurma yok) ✓")


def test_araya_giren_sermaye_DUSULUYOR():
    """⚠ ASIL TEST. Çıpadan sonra $71.32 sermaye eklendi; bu KÂR DEĞİL.
    equity 209.05 → 323.38, sermaye 209.05 → 280.37.
    Doğru kâr = 323.38 − 209.05 − (280.37 − 209.05) = 43.01"""
    t = asyncio.run(_bot(_DB("2026-07-16", 209.05, 209.05))._temiz(323.38, 280.37))
    assert t is not None
    assert abs(t["kar"] - 43.01) < 0.01, \
        f"kâr {t['kar']:.2f} — eklenen sermaye düşülmemiş olabilir (114.33 = hata)"
    print(f"  eklenen sermaye kârdan düşüldü: ${t['kar']:+.2f} ✓")


def test_cipa_oncesi_kar_HIC_sayilmiyor():
    """Çıpadan önce kazanılan para temiz kâra girmemeli.
    Çıpada equity 250 ama sermaye 209 → çıpa öncesi $41 kâr var.
    Sonrasında hiç kâr yoksa temiz kâr 0 olmalı."""
    t = asyncio.run(_bot(_DB("2026-07-16", 250.0, 209.0))._temiz(250.0, 209.0))
    assert abs(t["kar"]) < 1e-6, f"çıpa öncesi kâr sızmış: {t['kar']:.2f}"
    print("  çıpa öncesi kâr sızmıyor ✓")


def test_zarar_da_dogru():
    t = asyncio.run(_bot(_DB("2026-07-16", 300.0, 209.0))._temiz(280.0, 209.0))
    assert abs(t["kar"] + 20.0) < 1e-6, t["kar"]
    print("  temiz dönemde zarar doğru ✓")


def test_status_ve_rapor_temizi_kullaniyor():
    src = (Path(__file__).resolve().parent.parent / "telegram_bot.py").read_text()
    i = src.index("async def _cmd_status")
    assert "_temiz(" in src[i:i + 2000], "/status temiz dönemi kullanmıyor"
    j = src.index("async def _cmd_rapor")
    blok = src[j:j + 7000]
    assert 'CUT = (temiz or {}).get("cut")' in blok, "/rapor CUT'u çıpadan almıyor"
    assert 'rows = [r for r in rows if str(r[7]) >= CUT]' in blok, \
        "/rapor çıpa öncesini atmıyor — 'hiçbir iz olmayacak' ihlali"
    k = src.index("async def _cmd_stats")
    assert "temiz_cut" in src[k:k + 2500], "/stats çıpa öncesini hâlâ sayıyor"
    print("  /status · /rapor · /stats üçü de çıpayı kullanıyor ✓")


def test_heartbeat_temizi_kullaniyor():
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    i = src.index("async def heartbeat_loop")
    blok = src[i:i + 5000]
    assert "temiz_equity" in blok, "heartbeat hâlâ her-zamanın kârını basıyor"
    print("  heartbeat temiz dönemi kullanıyor ✓")


def test_kurulum_araci_dogruluyor():
    """temiz_donem.py çıpayı YAZMADAN ÖNCE CUT'u defterden doğrulamalı ve
    okunamayan bir şey varsa HİÇBİR ŞEY yazmamalı."""
    src = (Path(__file__).resolve().parent.parent / "temiz_donem.py").read_text()
    assert "def dogrula_cut" in src, "CUT doğrulaması yok"
    assert "ending_balance KULLANILMAZ" in src, "bayat alan uyarısı yok"
    assert src.count("raise SystemExit(2)") >= 3, \
        "okunamayan kaynakta yazmayı durduran çıkış yolları eksik"
    assert src.index("dogrula_cut(") < src.index('set_meta("temiz_cut"'), \
        "doğrulama yazmadan SONRA — işe yaramaz"
    print("  temiz_donem.py yazmadan önce doğruluyor ✓")


if __name__ == "__main__":
    print("test_temiz_donem — kâr temiz döneme göre mi?\n")
    for fn in (test_cipa_yoksa_None,
               test_araya_giren_sermaye_DUSULUYOR,
               test_cipa_oncesi_kar_HIC_sayilmiyor,
               test_zarar_da_dogru,
               test_status_ve_rapor_temizi_kullaniyor,
               test_heartbeat_temizi_kullaniyor,
               test_kurulum_araci_dogruluyor):
        fn()
    print("\n✓ TEMİZ DÖNEM TESTLERİ GEÇTİ")
