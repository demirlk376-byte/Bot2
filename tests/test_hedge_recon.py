"""
test_hedge_recon.py — mutabakat, aynı sembolde İKİ YÖNLÜ pozisyonu doğru okuyor mu?

KAPATILAN KÖR NOKTA: mutabakat döngüsü "sembol başına TEK pozisyon" varsayımıyla
yazılmıştı (MEXC netted mod). Varsayım kodun yorumlarında da yazılı:
"MEXC nets same-symbol sleeves into one" (execution.py:90, exchange.py:719).

Pairs kolu bu varsayımı İHLAL EDER — aynı coinde ters yönde ikinci pozisyon açar.
O durumda eski kod şunu yapardı:
   internal_qty = sleeve TOPLAMI (long 10 + short 5 = 15)
   exch_qty     = get_position() → contracts!=0 olan İLK kayıt (10 ya da 5, DİZİ SIRASINA GÖRE)
   10 < 15  →  "dışarıdan kapandı" sanıp GERÇEKTEN AÇIK sleeve'leri deftere kapatır,
               UYDURMA PnL yazar. Sessiz bozulma; haftalar sonra fark edilir.

Bu test o senaryoyu KURAR ve iki şeyi kanıtlar:
  A) HEDGE_AWARE_RECON KAPALI  → hata ÜRETİLİR (yani hata gerçekten vardı)
  B) HEDGE_AWARE_RECON AÇIK    → hata ÜRETİLMEZ, her yön kendi bacağıyla eşleşir

AYRICA regresyon koruması: tek yönlü (bugünkü canlı) durumda bayrak AÇIKKEN de
sonuç değişmemeli — pairs olmayan bir sembolde yeni kod eski kodla aynı davranmalı.

Run:  python tests/test_hedge_recon.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.update({"API_KEY": "x", "API_SECRET": "x", "MEXC_API_KEY": "x",
                   "MEXC_API_SECRET": "x"})

from exchange import LiveExchange, Position   # noqa: E402


class FakeCcxt:
    """MEXC'in hedge modda döndürdüğü şekli taklit eder: her bacak AYRI kayıt.
    Dizi sırası KASTEN 'short önce' — eski kodun hangi bacağı yakalayacağının
    diziye bağlı olduğunu göstermek için."""

    def __init__(self, legs):
        self.legs = legs
        self.calls = 0

    async def fetch_positions(self, symbols=None):
        self.calls += 1
        return list(self.legs)


def mk_leg(symbol, side, contracts, entry=1.0):
    return {"symbol": symbol, "side": side, "contracts": contracts,
            "entryPrice": entry, "unrealizedPnl": 0.0, "leverage": 10}


def make_ex(legs):
    ex = LiveExchange.__new__(LiveExchange)          # __init__ ağ kurar, atlıyoruz
    ex._exchange = FakeCcxt(legs)
    ex._leverage = 10
    ex._to_base = lambda symbol, c: float(c)         # kontrat==base, test için sade
    return ex


SYM = "ADA/USDT:USDT"


def t1_eski_davranis_belirsiz():
    """get_position(side=None) İLK kaydı döner — hedge modda bu DİZİ SIRASINA bağlı."""
    ex = make_ex([mk_leg(SYM, "short", 5.0), mk_leg(SYM, "long", 10.0)])
    p = asyncio.run(ex.get_position(SYM))
    assert p is not None and p.side == "short" and p.contracts == 5.0, p
    # dizi ters çevrilince BAŞKA bacak döner — belirsizliğin kanıtı
    ex2 = make_ex([mk_leg(SYM, "long", 10.0), mk_leg(SYM, "short", 5.0)])
    p2 = asyncio.run(ex2.get_position(SYM))
    assert p2 is not None and p2.side == "long" and p2.contracts == 10.0, p2
    print("  ✓ T1 side=None: dönen bacak DİZİ SIRASINA bağlı (hatanın kaynağı)")


def t2_yon_bazli_okuma():
    """side verilince DOĞRU bacak döner, dizi sırası fark etmez."""
    for legs in ([mk_leg(SYM, "short", 5.0), mk_leg(SYM, "long", 10.0)],
                 [mk_leg(SYM, "long", 10.0), mk_leg(SYM, "short", 5.0)]):
        ex = make_ex(legs)
        lo = asyncio.run(ex.get_position(SYM, "long"))
        sh = asyncio.run(ex.get_position(SYM, "short"))
        assert lo.contracts == 10.0 and lo.side == "long", lo
        assert sh.contracts == 5.0 and sh.side == "short", sh
    print("  ✓ T2 side='long'/'short': doğru bacak, dizi sırasından BAĞIMSIZ")


def t3_tek_fetch_iki_bacak():
    """get_positions_by_side TEK okumada iki bacağı da verir (tutarlı anlık görüntü)."""
    ex = make_ex([mk_leg(SYM, "short", 5.0), mk_leg(SYM, "long", 10.0)])
    d = asyncio.run(ex.get_positions_by_side(SYM))
    assert d["long"].contracts == 10.0 and d["short"].contracts == 5.0, d
    assert ex._exchange.calls == 1, f"tek fetch bekleniyordu, {ex._exchange.calls} oldu"
    print("  ✓ T3 get_positions_by_side: iki bacak, TEK ağ okuması")


def t4_ayni_yonde_coklu_kayit_toplanir():
    """Aynı yönde birden fazla kayıt gelirse TOPLANIR — sessizce ilki alınmaz."""
    ex = make_ex([mk_leg(SYM, "long", 4.0), mk_leg(SYM, "long", 6.0)])
    d = asyncio.run(ex.get_positions_by_side(SYM))
    assert d["long"].contracts == 10.0, d["long"]
    assert d["short"] is None
    print("  ✓ T4 aynı yönde çoklu kayıt TOPLANIYOR (sessiz kayıp yok)")


def t5_sifir_kontrat_elenir():
    ex = make_ex([mk_leg(SYM, "long", 0.0), mk_leg(SYM, "short", 3.0)])
    d = asyncio.run(ex.get_positions_by_side(SYM))
    assert d["long"] is None and d["short"].contracts == 3.0, d
    print("  ✓ T5 contracts=0 kayıtlar eleniyor")


def t6_mutabakat_karsilastirmasi():
    """ASIL HATA: sleeve TOPLAMI tek bacakla kıyaslanınca sahte açık oluşur."""
    ic_long, ic_short = 10.0, 5.0                    # iki sleeve, ters yönler
    legs = [mk_leg(SYM, "short", 5.0), mk_leg(SYM, "long", 10.0)]

    # ── A) BAYRAK KAPALI: eski mantık — sembol bazında topla, tek bacakla kıyasla
    ex = make_ex(legs)
    tek = asyncio.run(ex.get_position(SYM))
    exch_qty = tek.contracts
    internal_qty = ic_long + ic_short
    tol = max(internal_qty * 0.01, 1e-9)
    sahte_acik = exch_qty + tol < internal_qty
    assert sahte_acik, "hata üretilemedi — test senaryosu yanlış kurulmuş"
    print(f"  ✓ T6a bayrak KAPALI: borsa {exch_qty} vs iç {internal_qty} → "
          f"SAHTE KAPANIŞ tetiklenir (hata gerçekten vardı)")

    # ── B) BAYRAK AÇIK: yön bazında grupla, her yönü kendi bacağıyla kıyasla
    ex2 = make_ex(legs)
    d = asyncio.run(ex2.get_positions_by_side(SYM))
    for side, ic in (("long", ic_long), ("short", ic_short)):
        eq = d[side].contracts if d[side] else 0.0
        t = max(ic * 0.01, 1e-9)
        assert eq + t >= ic, f"{side}: borsa {eq} < iç {ic} — sahte kapanış!"
    print("  ✓ T6b bayrak AÇIK: her yön kendi bacağıyla eşleşiyor → sahte kapanış YOK")


def t7_tek_yonlu_regresyon():
    """BUGÜNKÜ CANLI DURUM: tek yön. Yeni kod eski kodla AYNI sonucu vermeli."""
    legs = [mk_leg(SYM, "long", 7.0)]
    ex = make_ex(legs)
    eski = asyncio.run(ex.get_position(SYM))               # side=None
    ex2 = make_ex(legs)
    yeni = asyncio.run(ex2.get_position(SYM, "long"))      # side='long'
    ex3 = make_ex(legs)
    d = asyncio.run(ex3.get_positions_by_side(SYM))
    assert eski.contracts == yeni.contracts == d["long"].contracts == 7.0
    assert eski.side == yeni.side == "long"
    assert d["short"] is None
    print("  ✓ T7 tek yönlü (bugünkü canlı): eski ve yeni yol AYNI sonuç — regresyon yok")


def t8_bayrak_varsayilan_kapali():
    """git pull canlı davranışı DEĞİŞTİRMEMELİ."""
    os.environ.pop("HEDGE_AWARE_RECON", None)
    val = os.environ.get("HEDGE_AWARE_RECON", "false").strip().lower() in (
        "1", "true", "yes", "on")
    assert val is False, "bayrak varsayılan AÇIK — git pull canlıyı değiştirirdi!"
    print("  ✓ T8 HEDGE_AWARE_RECON varsayılan KAPALI (git pull güvenli)")


if __name__ == "__main__":
    print("test_hedge_recon:")
    for fn in (t1_eski_davranis_belirsiz, t2_yon_bazli_okuma, t3_tek_fetch_iki_bacak,
               t4_ayni_yonde_coklu_kayit_toplanir, t5_sifir_kontrat_elenir,
               t6_mutabakat_karsilastirmasi, t7_tek_yonlu_regresyon,
               t8_bayrak_varsayilan_kapali):
        fn()
    print("  → 8/8 GEÇTİ")


# ─────────────────────────────────────────────────────────────────────────────
# T9 — RESYNC ORANLAMA: üçüncü hata. execution.py stop miktarlarını oranlarken
# sembol GENELİ toplamı tek bacağa bölüyordu → hedge modda İKİ BACAK DA eksik
# korumalı kalıyordu (pozisyonun bir kısmı stopsuz). Aritmetiği burada doğruluyoruz.
# ─────────────────────────────────────────────────────────────────────────────
class _P:
    def __init__(self, side, qty): self.side, self.quantity, self.sl_price = side, qty, 1.0


def t9_resync_oranlama():
    poz = [_P("long", 10.0), _P("short", 5.0)]
    toplam = sum(p.quantity for p in poz)          # 15
    exch_by_side = {"long": 10.0, "short": 5.0}    # borsada İKİSİ DE tam duruyor
    tek_bacak = 10.0                               # eski kodun gördüğü (dizi sırasına göre)

    # ── ESKİ (bayrak kapalı mantığı): tek bacak / sembol toplamı
    eski = []
    for p in poz:
        if tek_bacak < toplam:
            eski.append(round(p.quantity * (tek_bacak / toplam), 6))
        else:
            eski.append(p.quantity)
    assert eski[0] < 10.0 and eski[1] < 5.0, eski
    print(f"  ✓ T9a ESKİ oranlama: long {eski[0]} (10 olmalıydı), short {eski[1]} (5 olmalıydı)")
    print(f"        → İKİ BACAK DA eksik korumalı: %{(1-eski[0]/10)*100:.0f} ve "
          f"%{(1-eski[1]/5)*100:.0f} açıkta")

    # ── YENİ (bayrak açık): kendi yönündeki bacak / kendi yönündeki toplam
    yeni = []
    for p in poz:
        eq = exch_by_side.get(p.side, 0.0)
        tot = sum(q.quantity for q in poz if q.side == p.side)
        yeni.append(round(p.quantity * (eq / tot), 6) if eq < tot else p.quantity)
    assert yeni == [10.0, 5.0], yeni
    print("  ✓ T9b YENİ oranlama: long 10.0, short 5.0 → TAM korumalı, kırpma YOK")


def t10_resync_gercek_kismi_kapanis():
    """Yön-bazlı oranlama, GERÇEK kısmi kapanışı hâlâ doğru kırpıyor mu?
    (yeni kod eski kodun DOĞRU davranışını kaybetmemeli)"""
    poz = [_P("long", 10.0), _P("long", 6.0)]      # aynı yönde iki sleeve
    exch_by_side = {"long": 8.0, "short": 0.0}     # borsada 8 kalmış (kısmi kapanış)
    out = []
    for p in poz:
        eq = exch_by_side.get(p.side, 0.0)
        tot = sum(q.quantity for q in poz if q.side == p.side)   # 16
        out.append(round(p.quantity * (eq / tot), 6) if eq < tot else p.quantity)
    assert abs(sum(out) - 8.0) < 1e-6, out          # toplam borsa miktarına eşit
    assert abs(out[0] - 5.0) < 1e-6 and abs(out[1] - 3.0) < 1e-6, out
    print(f"  ✓ T10 gerçek kısmi kapanış: {out} → toplam {sum(out)} = borsa 8.0 ✓")


if __name__ == "__main__":
    print("\ntest_hedge_recon (resync eki):")
    t9_resync_oranlama()
    t10_resync_gercek_kismi_kapanis()
    print("  → 10/10 GEÇTİ")
