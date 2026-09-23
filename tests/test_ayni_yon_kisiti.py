"""
Kitap geneli AYNI-YON kisiti (MAX_SAME_DIRECTION).

Kullanicinin gozlemi: "yukseliste kazaniyor ama sondaki dususte 5-6 islem
birden stop olunca hepsi batip gidiyor." Olculdu: ayni yonde 5 acikken acilan
6. pozisyon islem basi -0.1718R, kazanma %28.1 (taban %44), iki yarida da
negatif.

⚠ VARSAYILAN 0 = KAPALI. Acilmadikca canli davranis BIT BIT AYNI.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_VARSAYILAN_KAPALI():
    """⚠ EN KRITIK: acilmadikca canli bot etkilenmez."""
    import config as C
    assert C.load_config().risk.max_same_direction == 0


def test_env_ile_aciliyor(monkeypatch):
    import config as C
    monkeypatch.setenv("MAX_SAME_DIRECTION", "5")
    assert C.load_config().risk.max_same_direction == 5


# --- kisit mantigi: execution.py'deki sayim kuralini birebir taklit et
def _gecer_mi(acik_yonler, inflight_yonler, yon, max_ayni):
    if max_ayni <= 0 or yon == 0:
        return True
    ayni = sum(1 for d in acik_yonler if d == yon)
    ayni += sum(1 for d in inflight_yonler if d == yon)
    return ayni < max_ayni


def test_sinirin_ALTINDA_gecer():
    assert _gecer_mi([1, 1, 1, 1], [], yon=1, max_ayni=5)


def test_sinirda_ENGELLER():
    assert not _gecer_mi([1, 1, 1, 1, 1], [], yon=1, max_ayni=5)


def test_TERS_yon_engellenmez():
    """5 long acikken SHORT acilabilmeli -- kisit yone ozgu."""
    assert _gecer_mi([1, 1, 1, 1, 1], [], yon=-1, max_ayni=5)


def test_UCUSTAKI_emirler_de_sayilir():
    """Ayni anda gelen sinyaller kisiti birlikte asmamali; execution.py
    in-flight rezervasyonlari da sayiyor."""
    assert not _gecer_mi([1, 1, 1], [1, 1], yon=1, max_ayni=5)


def test_KAPALIYKEN_hicbir_sey_engellenmez():
    assert _gecer_mi([1] * 20, [1] * 5, yon=1, max_ayni=0)


def test_execution_kodu_bu_mantigi_ICERIYOR():
    """Kisit gercekten execution.py'de mi? Testin taklit ettigi mantigin
    uretimde OLDUGUNU dogrula -- yoksa test yesil, bot kisitsiz kalir."""
    kaynak = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "execution.py"), encoding="utf-8").read()
    assert "max_same_direction" in kaynak
    assert "Ayni-yon kisiti" in kaynak
    # sayim hem acik pozisyonlari hem ucustaki emirleri kapsamali
    i = kaynak.index("max_ayni = getattr")
    blok = kaynak[i:i + 900]
    assert "get_open_positions()" in blok
    assert "_inflight_direction" in blok
