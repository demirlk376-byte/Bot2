"""
Codex'in bildirdiği iki hatanın regresyon testleri (production DEĞİŞTİRİLMEZ; testler hatanın
VAR olduğunu belgeler ve araştırma düzeltmesinin etkisini gösterir).

  #1 exchange._simdi_ts fonksiyon içinde `from datetime import datetime` yapıyor → ikizin sanal
     saat yaması (modül attribute'u `datetime`) ona ulaşmıyor → paper funding penceresi DUVAR
     saatinden ölçülüyor (~0 sn) → ikizde funding fiilen SIFIR.
  #2 [2026-09-28 geliştirme kopyasında düzeltildi] Canlı mutabakat (main.py) gerçek çıkış komisyonunu (fetch_close_fill → gercek_ucret) `fees`
     değişkenine koyuyor ama _close_position_internal'a AKTARMIYOR; içeride çıkış ücreti yeniden
     exit × 0.0001 olarak hesaplanıyor. Paper ikiz bu yola girmez (mutabakat döngüsü paper'da döner).
  #3 (bu çalışmada bulundu) exchange._funding_toplami zaman damgasını astype("int64")/1e9 ile saniyeye
     çeviriyor; pandas ≥ 2'de to_datetime(format="mixed") datetime64[us] dönebiliyor → değerler 1000 kat
     küçük → hiçbir oran pencereye düşmüyor → funding saat düzeltilse de SIFIR.

Çalıştır:  python3 -m pytest -q arastirma/squeeze_cost_aware_allocation/test_codex_bulgulari.py
"""
import ast
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOK)


def _sanal(t0):
    from ikiz.saat import SanalSaat, sanal_datetime
    s = SanalSaat(t0)
    return s, sanal_datetime(s)


def test_1_simdi_ts_sanal_saati_atliyor():
    import exchange as EX
    t0 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    saat, SD = _sanal(t0)
    eski = getattr(EX, "datetime", None)
    EX.datetime = SD                      # ikiz/kos.py'nin yaptığı yama
    try:
        gercek = EX._simdi_ts()
    finally:
        if eski is None:
            del EX.datetime
        else:
            EX.datetime = eski
    # 2026-10-05 DÜZELTİLDİ: _simdi_ts modül düzeyi datetime kullanıyor → ikizin yaması ulaşıyor
    assert abs(gercek - t0.timestamp()) < 1


def test_1_funding_ikizde_sifir_duzeltmeyle_degil():
    import exchange as EX
    os.environ["PAPER_FUNDING"] = "true"
    EX.PaperExchange.FUNDING_ACIK = True
    t0 = datetime(2024, 3, 1, tzinfo=timezone.utc)
    saat, SD = _sanal(t0)

    async def tur(duzelt):
        orj = EX._simdi_ts
        eski_dt = EX.datetime
        EX._FUNDING_ONBELLEK.clear()
        if not duzelt:
            EX.datetime = SD                     # ikiz/kos.py'nin yaptığı yama (düzeltmeden sonra yeterli)
        if duzelt:
            EX._simdi_ts = lambda: saat.simdi.timestamp()
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import importlib.util
            sp = importlib.util.spec_from_file_location("sqk_fund", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sq_kos.py"))
            src = open(sp.origin, encoding="utf-8").read()
            ns = {"os": os, "KOK": KOK}
            i = src.index("def funding_onbellek_duzelt"); j = src.index("def kanca_kayma")
            exec(src[i:j], ns)
            ns["funding_onbellek_duzelt"]()
        try:
            ex = EX.PaperExchange(10000.0, leverage=10)
            await ex.update_price(0.70, "ADA/USDT:USDT")
            await ex.place_market_order("ADA/USDT:USDT", "buy", 10000.0, {})
            pos = ex.get_open_positions()[0]
            saat.ileri(8 * 86400)                        # 8 gün tut
            ts0 = pos.giris_ts
            await ex.update_price(0.70, "ADA/USDT:USDT")
            fr = EX._funding_toplami("ADA/USDT:USDT", ts0, EX._simdi_ts())
            return ts0, fr
        finally:
            EX._simdi_ts = orj
            EX.datetime = eski_dt
            EX._FUNDING_ONBELLEK.clear()

    ts_bug, fr_bug = asyncio.run(tur(False))
    saat.ayarla(saat.simdi + timedelta(seconds=1))
    ts_fix, fr_fix = asyncio.run(tur(True))
    # 2026-10-05 DÜZELTİLDİ (exchange.py modül düzeyi datetime): yamasız tur da artık sanal saati görüyor
    assert abs(fr_bug) > 0
    assert abs(ts_fix - t0.timestamp()) < 86400 * 9
    assert abs(fr_fix) > 0                      # düzeltmeyle gerçek oranlar toplanıyor


def test_2_mutabakat_gercek_ucreti_aktarmiyor():
    """2026-09-28: hata geliştirme kopyasında DÜZELTİLDİ (dağıtılmadı). Davranış testi:
    tests/test_cikis_komisyonu.py. Bu test artık düzeltmenin yerinde olduğunu belgeler."""
    src = open(os.path.join(KOK, "main.py"), encoding="utf-8").read()
    agac = ast.parse(src)
    kw = None
    for n in ast.walk(agac):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_close_position_internal":
            kw = {k.arg for k in n.keywords}
    assert kw is not None and "exit_fee_usdt" in kw        # gerçek ücret açıkça aktarılıyor


def test_3_funding_zaman_birimi():
    import pandas as pd
    import exchange as EX
    EX._FUNDING_ONBELLEK.clear()
    bas = pd.Timestamp("2024-03-01", tz="UTC").timestamp()
    bit = pd.Timestamp("2024-03-09", tz="UTC").timestamp()
    # 2026-10-05 DÜZELTİLDİ: zaman damgası sürümden bağımsız saniyeye çevriliyor
    assert EX._funding_toplami("ADA/USDT:USDT", bas, bit) != 0.0      # 8 günde 24 oran toplanıyor
    ts = EX._FUNDING_ONBELLEK["ADA"][0]
    assert 1.5e9 < ts[0] < 2.5e9                                      # saniye
    EX._FUNDING_ONBELLEK.clear()
