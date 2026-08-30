"""
test_cikis_dolumu.py — mutabakat çıkışları GERÇEK dolumdan mı yazıyor?

NEDEN VAR: mutabakat yolu (main.py) borsanın kapattığı pozisyonu SL/TP
SEVİYESİNDEN defterlere yazıyordu. Stop-market emri seviyenin ÖTESİNDE dolar,
yani her SL çıkışı olduğundan İYİ kaydediliyordu; üstüne çıkış ücreti 1bp
sabitti (ölçülen gerçek ~2.5bp, DURUM 2d). Defter borsadan uzaklaşıyor ve
GÜNLÜK ZARAR FRENİ bu defteri okuyor — yani bu bir muhasebe süsü değil,
frenin girdisi.

Kritik davranış: gerçek dolum OKUNAMAZSA eski davranışa düşülmeli AMA kayıt
'tahmin' diye işaretlenmeli. Sessizce doğru sanmak yasak.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exchange import LiveExchange


def _borsa(fills):
    """fetch_my_trades'i sahteleyen minimal LiveExchange."""
    lx = LiveExchange.__new__(LiveExchange)      # __init__ ağ istiyor, atla
    class _C:
        async def fetch_my_trades(self, symbol, since, limit):
            return fills
    lx._exchange = _C()
    return lx


def test_gercek_dolum_vwap_ve_ucret():
    """İki kısmi dolum → VWAP fiyat + ücretlerin TOPLAMI."""
    fills = [
        {"timestamp": 200, "side": "sell", "price": 99.0, "amount": 0.6,
         "fee": {"cost": 0.03}},
        {"timestamp": 100, "side": "sell", "price": 98.0, "amount": 0.4,
         "fee": {"cost": 0.02}},
    ]
    r = asyncio.run(_borsa(fills).fetch_close_fill("X/USDT:USDT", "sell", 1.0, 0))
    assert r is not None
    px, ucret, n = r
    assert abs(px - (99.0 * 0.6 + 98.0 * 0.4)) < 1e-9, px
    assert abs(ucret - 0.05) < 1e-9, ucret
    assert n == 2
    print(f"  VWAP ${px:.4f}, gerçek ücret ${ucret:.4f}, {n} dolum ✓")


def test_ters_yon_dolumlari_sayilmaz():
    """GİRİŞ dolumları (ters yön) kapanış fiyatına karışmamalı."""
    fills = [
        {"timestamp": 50, "side": "buy", "price": 50.0, "amount": 1.0,
         "fee": {"cost": 0.10}},                       # giriş — sayılmamalı
        {"timestamp": 200, "side": "sell", "price": 99.0, "amount": 1.0,
         "fee": {"cost": 0.03}},
    ]
    px, ucret, n = asyncio.run(
        _borsa(fills).fetch_close_fill("X/USDT:USDT", "sell", 1.0, 0))
    assert abs(px - 99.0) < 1e-9, px
    assert abs(ucret - 0.03) < 1e-9, ucret
    print("  giriş dolumları çıkış fiyatına karışmadı ✓")


def test_yarim_eslesme_REDDEDILIR():
    """Miktarın çoğu eşleşmiyorsa None dönmeli — yarım eşleşmeden 'gerçek'
    fiyat üretmek, yanlış bir kesinlik yaratır."""
    fills = [{"timestamp": 200, "side": "sell", "price": 99.0, "amount": 0.3,
              "fee": {"cost": 0.01}}]
    r = asyncio.run(_borsa(fills).fetch_close_fill("X/USDT:USDT", "sell", 1.0, 0))
    assert r is None, f"yarım eşleşme kabul edildi: {r}"
    print("  yarım eşleşme (0.3/1.0) reddedildi ✓")


def test_dolum_yoksa_None():
    """Boş liste / hata → None (çağıran eski davranışa düşer)."""
    assert asyncio.run(_borsa([]).fetch_close_fill("X/USDT:USDT", "sell", 1.0, 0)) is None

    class _Patlak:
        async def fetch_my_trades(self, *a):
            raise RuntimeError("borsa yok")
    lx = LiveExchange.__new__(LiveExchange)
    lx._exchange = _Patlak()
    assert asyncio.run(lx.fetch_close_fill("X/USDT:USDT", "sell", 1.0, 0)) is None
    print("  dolum yok / borsa hatası → None ✓")


def test_ucret_kismi_kullanimda_oranlanir():
    """Dolumun bir KISMI kullanıldıysa ücreti de o oranda sayılmalı."""
    fills = [{"timestamp": 200, "side": "sell", "price": 100.0, "amount": 2.0,
              "fee": {"cost": 0.20}}]
    px, ucret, n = asyncio.run(
        _borsa(fills).fetch_close_fill("X/USDT:USDT", "sell", 1.0, 0))
    assert abs(px - 100.0) < 1e-9
    assert abs(ucret - 0.10) < 1e-9, f"ücret oranlanmadı: {ucret}"
    print("  kısmi kullanımda ücret oranlandı ✓")


def test_main_gercek_dolumu_kullaniyor():
    """main.py mutabakat yolu artık seviye fiyatını KÖRÜ KÖRÜNE yazmamalı."""
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    i = src.index("Reconciliation: %s %s externally closed on MEXC")
    blok = src[max(0, i - 3000):i]
    assert "fetch_close_fill" in blok, "mutabakat gerçek dolumu sormuyor"
    assert "exit_price_estimated" in blok, \
        "gerçek dolum okunamayınca kayıt 'tahmin' diye işaretlenmiyor"
    # eski sabit ücret satırı yalnız YEDEK yolda kalmalı
    assert blok.count("exit_price * pos.quantity * 0.0001") == 1, \
        "sabit 1bp çıkış ücreti hâlâ ana yolda"
    print("  main.py gerçek dolumu kullanıyor + yedeği işaretliyor ✓")


if __name__ == "__main__":
    print("test_cikis_dolumu — mutabakat çıkışı gerçek dolumdan mı?\n")
    for fn in (test_gercek_dolum_vwap_ve_ucret,
               test_ters_yon_dolumlari_sayilmaz,
               test_yarim_eslesme_REDDEDILIR,
               test_dolum_yoksa_None,
               test_ucret_kismi_kullanimda_oranlanir,
               test_main_gercek_dolumu_kullaniyor):
        fn()
    print("\n✓ ÇIKIŞ DOLUMU TESTLERİ GEÇTİ")
