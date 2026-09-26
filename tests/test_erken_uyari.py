"""
test_erken_uyari.py — "kayıp normal mi, alarm mı?" aracının hesapları.

NEDEN KRİTİK: bu araç yanlış ALARM verirse kullanıcı sağlıklı botu dipte kapatır
(defterde 30+ kez para kaybettiren hata); yanlış SESSİZ kalırsa ölü edge aylarca
para yer. İkisi de üç hesaba bağlı: CUSUM, katkıdan bağımsız birim değer, R tanımı.

Run:  python tests/test_erken_uyari.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database
import erken_uyari as E


def _islem(pnl=-10.0, kol="donchian", giris=100.0, sl0=98.0, sl=None, miktar=5.0,
           niyet=None, yon="long", bas="2026-09-01T00:00:00+00:00",
           bit="2026-09-01T04:00:00+00:00"):
    skor = {"strategy": kol, "sl0": sl0}
    if niyet is not None:
        skor["intended_entry"] = niyet
    return {"symbol": "SOL/USDT:USDT", "side": yon, "entry_price": giris, "exit_price": giris,
            "quantity": miktar, "sl_price": sl if sl is not None else sl0, "entry_time": bas,
            "exit_time": bit, "pnl_usdt": pnl, "exit_reason": "sl_hit",
            "strategy_scores": json.dumps(skor)}


def test_cusum_saglikli_akista_sifirda_kalir():
    assert E.cusum([1.0, 2.0, 0.5, 1.5]) == [0.0, 0.0, 0.0, 0.0]


def test_cusum_kayiplarda_k_arti_bir_buyur_ve_sifirlanir():
    S = E.cusum([-1.0, -1.0, 5.0])
    assert abs(S[0] - (E.CUSUM_K + 1)) < 1e-12
    assert abs(S[1] - 2 * (E.CUSUM_K + 1)) < 1e-12
    assert S[2] == 0.0


def test_r_ILK_STOPU_kullanir_hareket_eden_stopu_degil():
    # sl0=98 (risk 2), sonradan stop 99'a çekilmiş; R ilk riske göre ölçülmeli
    t = _islem(pnl=-10.0, giris=100.0, sl0=98.0, sl=99.0, miktar=5.0)
    assert abs(E.r_net(t) - (-1.0)) < 1e-12


def test_r_sifir_riskte_None():
    assert E.r_net(_islem(giris=100.0, sl0=100.0)) is None


def test_dusus_su_anki_ve_en_buyuk():
    simdi, en = E.dusus([0.10, -0.50, 0.20])
    assert abs(en - 0.50) < 1e-12
    assert abs(simdi - (1 - 1.1 * 0.5 * 1.2 / 1.1)) < 1e-12


def test_islem_riski_cap_baglayinca_kirpilir():
    dar = _islem(giris=100.0, sl0=99.0)        # stop %1 → cap 1.5 × %1 = %1.5
    genis = _islem(giris=100.0, sl0=90.0)      # stop %10 → hedef %3.5 bağlar
    assert abs(E.islem_riski(dar, 0.035, 1.5) - 0.015) < 1e-12
    assert abs(E.islem_riski(genis, 0.035, 1.5) - 0.035) < 1e-12


def test_kol_adlari():
    assert E.kol_adi(json.dumps({"strategy": "donchian"})) == "donchian"
    assert E.kol_adi(json.dumps({"strategy": "mean_rev"})) == "mean_rev"
    assert E.kol_adi(json.dumps({"strategy": "bb"})) == "mean_rev"
    assert E.kol_adi(json.dumps({"strategy": "orb"})) == "orb"
    assert E.kol_adi(None) == "?"


def test_dd_bantlari_ve_kirmizi_cizgi():
    assert E.dd_bandi(0.30).startswith("olağan")
    assert "5 yılda" in E.dd_bandi(0.45)
    assert "20 yılda" in E.dd_bandi(0.55)
    assert E.dd_bandi(0.60) == "KIRMIZI ÇİZGİ"


def test_saglikli_akis_NORMAL():
    # %40 kazanan +2R, %60 kaybeden −1R → ort R +0.2 (İKİZ ~+0.17)
    islemler = [_islem(pnl=(20.0 if i % 5 < 2 else -10.0)) for i in range(200)]
    s = E.degerlendir(islemler, 0.035, 1.5)
    assert s["n"] == 200 and not s["edge_alarm"] and E.hukum(s) == "NORMAL"


def test_olu_edge_ALARM():
    islemler = [_islem(pnl=(20.0 if i % 10 < 3 else -10.0)) for i in range(200)]   # ort R −0.1
    s = E.degerlendir(islemler, 0.035, 1.5)
    assert s["edge_alarm"] and E.hukum(s) == "ALARM"


def test_KATKI_birim_degeri_ETKILEMEZ():
    """Aynı işlemler, farklı hesap büyüklüğü (katkı sonrası miktar büyür): birim
    değer düşüşü AYNI kalmalı. Ham equity'ye bakan eski kırmızı çizginin körlüğü
    tam buydu."""
    kucuk = [_islem(pnl=-10.0, miktar=5.0) for _ in range(12)]
    buyuk = [_islem(pnl=-40.0, miktar=20.0) for _ in range(12)]
    a = E.degerlendir(kucuk, 0.035, 1.5)
    b = E.degerlendir(buyuk, 0.035, 1.5)
    assert abs(a["dd_simdi"] - b["dd_simdi"]) < 1e-12


def test_yabanci_kol_ve_stoptan_kotu_YURUTME():
    s = E.degerlendir([_islem(pnl=20.0)] * 30 + [_islem(kol="orb", pnl=-10.0)], 0.035, 1.5)
    assert s["yabanci"] == 1 and E.hukum(s) == "YÜRÜTME UYARISI"
    s = E.degerlendir([_islem(pnl=20.0)] * 30 + [_islem(pnl=-20.0)], 0.035, 1.5)   # −2R
    assert s["stoptan_kotu"] == 1 and E.hukum(s) == "YÜRÜTME UYARISI"


def test_kayma_modelden_anlamli_kotuyse_uyari_esitse_degil():
    esit = [_islem(pnl=20.0, giris=100.1585, niyet=100.0) for _ in range(30)]
    assert not E.degerlendir(esit, 0.035, 1.5)["yurutme"]
    kotu = [_islem(pnl=20.0, giris=100.40, niyet=100.0) for _ in range(30)]      # 40bp
    assert E.degerlendir(kotu, 0.035, 1.5)["yurutme"]
    maker = [_islem(pnl=20.0, kol="mean_rev", giris=100.40, niyet=100.0) for _ in range(30)]
    assert not E.degerlendir(maker, 0.035, 1.5)["yurutme"], "mean_rev maker; 15.85bp modeli ona ait değil"


def test_ESKI_yabanci_kol_ve_eski_stop_hatasi_KALICI_uyari_URETMEZ():
    """Canlı db'de 07-16'da kapatılan orb/fvg işlemleri ve düzeltilmiş eski stop
    hataları duruyor. Tüm geçmişe baksaydı araç SONSUZA DEK 'yürütme uyarısı'
    derdi ve kullanıcı uyarıyı görmezden gelmeyi öğrenirdi."""
    eski = [_islem(kol="orb", pnl=-10.0, bas="2026-06-20T00:00:00+00:00", bit="2026-06-20T04:00:00+00:00"),
            _islem(pnl=-20.0, bas="2026-06-21T00:00:00+00:00", bit="2026-06-21T04:00:00+00:00")]
    yeni = [_islem(pnl=20.0, bas="2026-09-20T00:00:00+00:00", bit="2026-09-20T04:00:00+00:00")] * 30
    s = E.degerlendir(eski + yeni, 0.035, 1.5)
    assert s["yabanci"] == 0 and s["yabanci_toplam"] == 1
    assert s["stoptan_kotu"] == 0 and s["stoptan_kotu_toplam"] == 1
    assert E.hukum(s) == "NORMAL"


def test_veritabani_okuma_filtreleri():
    yol = os.path.join(tempfile.mkdtemp(prefix="erken-uyari-"), "trades.db")
    c = sqlite3.connect(yol)
    c.execute(database._CREATE_TRADES)
    def ekle(t, paper, kapali=True):
        c.execute("INSERT INTO trades (id, symbol, side, entry_price, exit_price, quantity, sl_price,"
                  " tp_price, entry_time, exit_time, pnl_usdt, pnl_pct, exit_reason, strategy_scores,"
                  " is_paper) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (str(uuid.uuid4()), t["symbol"], t["side"], t["entry_price"], t["exit_price"],
                   t["quantity"], t["sl_price"], 0.0, t["entry_time"],
                   t["exit_time"] if kapali else None, t["pnl_usdt"] if kapali else None, 0.0,
                   t["exit_reason"], t["strategy_scores"], paper))
    ekle(_islem(bas="2026-09-01T00:00:00+00:00"), 0)
    ekle(_islem(bas="2026-09-25T00:00:00+00:00", bit="2026-09-25T04:00:00+00:00"), 0)
    ekle(_islem(), 1)                       # paper — canlıda sayılmaz
    ekle(_islem(), 0, kapali=False)         # açık — sayılmaz
    c.commit(); c.close()
    assert len(E.islemleri_oku(yol)) == 2
    assert len(E.islemleri_oku(yol, paper=True)) == 1
    assert len(E.islemleri_oku(yol, bas="2026-09-22")) == 1


if __name__ == "__main__":
    testler = [f for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for f in testler:
        f()
        print(f"  ✓ {f.__name__}")
    print(f"✓ {len(testler)} test geçti")
