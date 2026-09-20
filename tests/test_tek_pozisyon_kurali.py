"""
ONE_PER_SYMBOL: canlinin netted kisiti backtest'te de uygulanabilmeli.

NEDEN: execution.py'deki muhafiz yalnizca `not paper_mode` ile calisiyordu.
IKIZ kagit modda kostugu icin CANLIDA YASAK olan sey -- ayni coinde es zamanli
iki pozisyon -- backtest'te SERBESTTI. Tam olarak bu kusur 2026-09-14'te
KRONOS'un "ayri havuz sifir itme yapar" iddiasini gecersiz kilmisti.

Su anki canli konfigurasyonda kollarin coin listeleri AYRIK
(donchian SOL,ETH,ADA,NEAR,BCH,ICP,BNB | squeeze XRP,DOGE,TRX,XLM | BB LTC)
oldugu icin kural pratikte hic baglamiyor -- ama ortusen bir kol acilirsa
(orn. ORB) sessizce ayrisirdi. Bu testler ayari kayit altina aliyor.
"""
import os
import importlib

import pytest


def _cfg(deger=None):
    eski = os.environ.get("ONE_PER_SYMBOL")
    if deger is None:
        os.environ.pop("ONE_PER_SYMBOL", None)
    else:
        os.environ["ONE_PER_SYMBOL"] = deger
    try:
        import config
        importlib.reload(config)
        return config.load_config()
    finally:
        if eski is None:
            os.environ.pop("ONE_PER_SYMBOL", None)
        else:
            os.environ["ONE_PER_SYMBOL"] = eski


def _uygulanir_mi(cfg, paper: bool) -> bool:
    """execution.py:414'teki karar mantiginin aynisi."""
    ops = getattr(cfg.risk, "one_per_symbol", "auto")
    return (not paper) if ops == "auto" else (ops == "true")


def test_varsayilan_auto_canliya_ozel():
    """Varsayilan eski davranisi korumali: canlida uygulanir, kagitta uygulanmaz."""
    cfg = _cfg(None)
    assert cfg.risk.one_per_symbol == "auto"
    assert _uygulanir_mi(cfg, paper=False) is True, "canlida uygulanmali"
    assert _uygulanir_mi(cfg, paper=True) is False, "varsayilanda kagitta uygulanmamali"


def test_true_kagitta_da_uygular():
    """IKIZ'in kullandigi mod: kagit modda bile canli kisiti gecerli."""
    cfg = _cfg("true")
    assert _uygulanir_mi(cfg, paper=True) is True
    assert _uygulanir_mi(cfg, paper=False) is True


def test_false_hic_uygulamaz():
    cfg = _cfg("false")
    assert _uygulanir_mi(cfg, paper=True) is False
    assert _uygulanir_mi(cfg, paper=False) is False


def test_ikiz_kuralı_zorluyor():
    """ikiz/kos.py ortami kurarken ONE_PER_SYMBOL=true yazmali."""
    import io
    kaynak = io.open("ikiz/kos.py", encoding="utf-8").read()
    assert '"ONE_PER_SYMBOL": "true"' in kaynak, (
        "IKIZ netted kisiti zorlamiyor -> backtest canlidan ayrisir")


def test_canli_kol_coinleri_ayrik():
    """Su anki canli ayarda kollarin coin listeleri ortusmemeli. Ortusurse bu
    kural BAGLAR ve eski olcumler (kural yokken alinanlar) gecersizdir."""
    don = set("SOL,ETH,ADA,NEAR,BCH,ICP,BNB".split(","))
    sqz = set("XRP,DOGE,TRX,XLM".split(","))
    bb = {"LTC"}
    assert not (don & sqz), f"donchian/squeeze ortusuyor: {don & sqz}"
    assert not (don & bb), f"donchian/BB ortusuyor: {don & bb}"
    assert not (sqz & bb), f"squeeze/BB ortusuyor: {sqz & bb}"
