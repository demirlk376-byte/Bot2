"""
/status ekrani. Canli para ekrani -- yanlis okunursa yanlis karar verilir.

⚠ Kullanicinin kalici istegi: "bana yuzdeliklerle konus". Ekran yuzdeyi ONE
alir, dolari parantezde tutar. Ama dolar KESIN, yuzde YAKLASIK (paydasi cipa
equity'si); o yuzden alttaki uyari notu KALMALI.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram_bot import _durum_metni

TEMIZ = {"kar": 117.21, "pct": 63.5, "cut": "2026-07-17"}


def _m(**kw):
    varsayilan = dict(canli=True, equity=373.17, sermaye=280.38, upnl=16.15,
                      n_acik=5, durduruldu=False, gun_tabani=365.37,
                      gun_limiti=0.35, temiz=TEMIZ)
    varsayilan.update(kw)
    return _durum_metni(**varsayilan)


def test_YUZDE_dolardan_ONCE_geliyor():
    """⚠ Kullanicinin kalici istegi."""
    m = _m()
    kar = [s for s in m.split("\n") if "Kâr" in s][0]
    assert kar.index("%") < kar.index("$"), f"dolar yuzdeden once: {kar}"
    assert "%+63.5" in kar and "$+117.21" in kar


def test_BUGUN_satiri_var_ve_dogru():
    """Eski ekranda gunluk PnL HIC yoktu."""
    m = _m(equity=373.17, gun_tabani=365.37)
    assert "Bugün" in m
    assert "%+2.1" in m, m          # (373.17-365.37)/365.37 = %2.13
    assert "$+7.80" in m


def test_GUN_SINIRI_kalan_marj_gosteriliyor():
    """⚠ EN ONEMLI YENI SATIR. Bot -%35'te tum pozisyonlari kapatip gunu
    durduruyor ama ekranda o esige ne kadar kaldigi HIC yazmiyordu."""
    m = _m(equity=373.17, gun_tabani=365.37, gun_limiti=0.35)
    assert "Gün sınırı %-35" in m
    # kayip = (365.37-373.17)/365.37 = -%2.13  -> kalan = 35 + 2.13 = %37.1
    assert "%37.1" in m, m


def test_zararda_kalan_marj_AZALIYOR():
    m = _m(equity=300.0, gun_tabani=365.37)
    # kayip = %17.9 -> kalan = 35 - 17.9 = %17.1
    assert "%17.1" in m, m


def test_esige_YAKLASINCA_uyari_isareti():
    m = _m(equity=275.0, gun_tabani=365.37)   # kayip %24.7 -> kalan %10.3
    assert "⚠️" in m, m
    m2 = _m(equity=373.17, gun_tabani=365.37)
    assert "⚠️" not in m2


def test_gun_tabani_YOKSA_cokmuyor():
    m = _m(gun_tabani=0.0)
    assert "Bugün" in m and "gün tabanı yok" in m
    assert "Gün sınırı" not in m


def test_acik_pozisyon_yoksa_yuzde_bolmuyor():
    m = _m(n_acik=0, upnl=0.0, equity=0.0)
    assert "Açık" in m


def test_DURDURULDU_gorunur():
    assert "DURDURULDU" in _m(durduruldu=True)
    assert "AKTİF" in _m(durduruldu=False)


def test_temiz_donem_uyarisi_KALIYOR():
    """Yuzdeyi one cikarmak bu uyariyi daha gerekli yapar, gereksiz degil."""
    m = _m()
    assert "temiz dönem 2026-07-17 sonrası" in m
    assert "dolar kesin" in m


def test_temiz_donem_yoksa_kar_HAM_hesaplaniyor():
    m = _m(temiz=None, equity=373.17, sermaye=280.38)
    assert "%+33.1" in m, m      # (373.17-280.38)/280.38
    assert "temiz dönem" not in m


def test_PAPER_ve_CANLI_ayirt_ediliyor():
    assert "CANLI" in _m(canli=True)
    assert "PAPER" in _m(canli=False)


def test_HTML_etiketleri_dengeli():
    """Telegram bozuk HTML'de mesaji HIC gondermez -- ekran tamamen kaybolur."""
    m = _m()
    for etiket in ("b", "code", "i"):
        assert m.count(f"<{etiket}>") == m.count(f"</{etiket}>"), f"{etiket} dengesiz"
