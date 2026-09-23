"""
/status ekrani. Canli para ekrani -- yanlis okunursa yanlis karar verilir.

IKI KALICI KURAL:
  1. PARA BLOGU KENDI ICINDE TUTAR: yatirilan + kâr = equity. Baska kalem yok.
     Onceki surumde kâr CIPADAN olculuyordu ve "280.38 + 117.21 = 397.59"
     equity 373.17'yi tutmuyordu; kullanici hakli olarak rakamdan suphelendi.
  2. YUZDE ONDE, dolar parantezde (kullanicinin kalici istegi).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram_bot import _durum_metni


def _m(**kw):
    v = dict(canli=True, equity=373.17, sermaye=280.38, upnl=16.15,
             n_acik=5, durduruldu=False, gun_tabani=365.37, gun_limiti=0.35)
    v.update(kw)
    return _durum_metni(**v)


def _sayi(metin, etiket):
    """Etiketli satirdaki dolar rakamini cikar."""
    import re
    for s in metin.split("\n"):
        if etiket in s:
            m = re.search(r"\$([+-]?[\d,]+\.\d\d)", s)
            if m:
                return float(m.group(1).replace(",", ""))
    raise AssertionError(f"'{etiket}' satiri yok:\n{metin}")


def test_PARA_BLOGU_KENDI_ICINDE_TUTAR():
    """⚠ EN KRITIK. yatirilan + kâr = equity. Tutmazsa kullanici -- hakli
    olarak -- tum ekrana guvenmez."""
    m = _m(equity=373.17, sermaye=280.38)
    yat = _sayi(m, "Yatırılan")
    eq = _sayi(m, "Equity")
    kar = _sayi(m, "Kâr")
    assert abs(yat + kar - eq) < 0.01, f"{yat} + {kar} != {eq}"


def test_zararda_da_TUTAR():
    m = _m(equity=240.0, sermaye=280.38)
    assert abs(_sayi(m, "Yatırılan") + _sayi(m, "Kâr") - _sayi(m, "Equity")) < 0.01
    assert "%-14.4" in m, m


def test_YUZDE_dolardan_ONCE():
    kar = [s for s in _m().split("\n") if "Kâr" in s][0]
    assert kar.index("%") < kar.index("$"), kar
    assert "%+33.1" in kar and "$+92.79" in kar


def test_CIPA_kalemleri_EKRANDA_YOK():
    """Kullanici: 'eklenen meklenen ekleme oraya'."""
    m = _m()
    for yasak in ("çıpa", "eklenen", "temiz dönem", "Gerçek kâr"):
        assert yasak not in m, f"'{yasak}' hala ekranda"


def test_BUGUN_satiri():
    m = _m(equity=373.17, gun_tabani=365.37)
    assert "Bugün" in m and "%+2.1" in m and "$+7.80" in m


def test_GUN_SINIRI_kalan_marj():
    """Bot -%35'te tum pozisyonlari kapatip gunu durduruyor; o esige ne kadar
    kaldigi ekranda olmaliydi."""
    assert "Gün sınırı %-35" in _m() and "%37.1" in _m()
    assert "%17.1" in _m(equity=300.0)          # 35 - 17.9


def test_esige_yaklasinca_UYARI():
    assert "⚠️" in _m(equity=275.0)             # kalan %10.3
    assert "⚠️" not in _m(equity=373.17)


def test_gun_tabani_yoksa_cokmuyor():
    m = _m(gun_tabani=0.0)
    assert "Gün sınırı" not in m and "Bugün" not in m
    assert "Yatırılan" in m and "Kâr" in m


def test_acik_yoksa_bolme_hatasi_yok():
    m = _m(n_acik=0, upnl=0.0, equity=0.0, sermaye=0.0, gun_tabani=0.0)
    assert "Açık" in m


def test_DURDURULDU_ve_PAPER():
    assert "DURDURULDU" in _m(durduruldu=True)
    assert "AKTİF" in _m(durduruldu=False)
    assert "PAPER" in _m(canli=False) and "CANLI" in _m(canli=True)


def test_HTML_etiketleri_dengeli():
    """Telegram bozuk HTML'de mesaji HIC gondermez -- ekran tamamen kaybolur."""
    m = _m()
    for e in ("b", "code"):
        assert m.count(f"<{e}>") == m.count(f"</{e}>"), f"{e} dengesiz"


def test_temiz_parametresi_GERIYE_UYUMLU():
    """Cagiran hala temiz=... geciyor; imza kabul etmeli ama KULLANMAMALI."""
    a = _m()
    b = _m(temiz={"kar": 117.21, "pct": 63.5, "cut": "2026-07-17"})
    assert a == b, "temiz parametresi ekrani degistiriyor"
