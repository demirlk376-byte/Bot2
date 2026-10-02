"""
Bağımsız muhasebe / maliyet / funding testleri.

Kapsam: şartname §13 (maliyet sözleşmesi), §16 (funding ve muhasebe), §15'in funding sırası
paragrafları ve §21 sayısal kabul örnekleri No.26, 29, 30, 31, 32, 33, 38.

Kurallar:
  * Beklenen sayıların HEPSİ şartnameden elle türetilmiş literal değerlerdir (türetim yorumda);
    üretim fonksiyonu çağrılıp sonucu "beklenen" diye yeniden kullanılmaz.
  * Her long fixture için fiyatları p -> 200 - p ile 100 etrafında yansıtan short aynası vardır
    (bar high/low rolleri yer değiştirir, fiyatlar pozitif kalır). Çarpımsal kayma, ücret ve
    funding fiyat düzeyine bağlı olduğundan short beklenen sayıları AYRICA elle yazılmıştır.
  * §21: belirtilmedikçe ücret/kayma 0, contract_size=1, fiyat adımı 0,01.
  * Uçtan uca fixture'lar order intent (SetupRecord sinyali) -> gerçek araştırma adaptörü
    (replay_adapter.simulate) -> Ledger yolundan geçer (§22 uyum kapısı 1). Kurulum/ısınma
    durumu §21 izniyle hazır kabul edilir (sinyal doğrudan kurulur).

Boyutlama (§12.2/§12.3) beklenenleri: per_trade_risk = 0,0025*C0;
Q_contracts = floor(per_trade_risk / |E_budget - S| / contract_size); Q_base = Q_contracts*contract_size.
Fixture'larda notional/marjin kapıları bağlamayacak kadar geniştir (kaldıraç 1 olsa bile).
"""
import numpy as np
import pytest

from research.liquidity_sweep_v1 import accounting as A
from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1 import data_contract as D
from research.liquidity_sweep_v1 import metrics as MT
from research.liquidity_sweep_v1 import replay_adapter as RA
from research.liquidity_sweep_v1.setups import SetupRecord

# ───────────────────────────── zaman (config'ten bağımsız literal) ──────────────────────────
G0 = 1_672_531_200_000            # 2023-01-01 00:00 UTC (UTC gün başı)
MIN_MS = 60_000
M5 = 5 * MIN_MS
HOUR = 60 * MIN_MS
DAY = 24 * HOUR
SIDES = ("LONG", "SHORT")


def at(day, hh, mm=0):
    """G0 gününden itibaren day. günün hh:mm UTC anı (ms)."""
    return G0 + day * DAY + hh * HOUR + mm * MIN_MS


def ap(x):
    return pytest.approx(x, abs=1e-9)


# ───────────────────────────── fixture yardımcıları ──────────────────────────────────────────
class Bars:
    """Long yönünde yazılan 5m OHLC senaryosu. Varsayılan: her bar o=h=l=c=100 (düz).
    Short aynası: p -> 200 - p ve high <-> low."""

    def __init__(self, days=3, base=100.0):
        n = days * 288
        self.o = np.full(n, base)
        self.h = np.full(n, base)
        self.l = np.full(n, base)
        self.c = np.full(n, base)

    def bar(self, t, o, h, l, c):
        k = (t - G0) // M5
        self.o[k], self.h[k], self.l[k], self.c[k] = o, h, l, c
        return self

    def flat(self, t_from, t_to, p):
        """Açılışı [t_from, t_to) aralığındaki barları p'de düz yap."""
        k0, k1 = (t_from - G0) // M5, (t_to - G0) // M5
        for a in (self.o, self.h, self.l, self.c):
            a[k0:k1] = p
        return self

    def arrays(self, side):
        if side == "LONG":
            return self.o.copy(), self.h.copy(), self.l.copy(), self.c.copy()

        def m(x):
            return np.round(200.0 - x, 10)

        return m(self.o), m(self.l), m(self.h), m(self.c)      # yansıtmada high ile low yer değiştirir


def symbol(bars, side, tick=0.01, cs=1.0, vol_unit=1.0, min_vol=1.0, funding=()):
    """funding: [(t_ms, oran[, ızgarada_mı]), ...]"""
    o, h, l, c = bars.arrays(side)
    # fixture'ın kendisi geçerli OHLC olmalı (yanlış test kurgusunu yakala)
    assert np.all(l <= np.minimum(o, c)) and np.all(np.maximum(o, c) <= h) and np.all(l > 0)
    n = len(c)
    ft = np.array([f[0] for f in funding], dtype="int64")
    fr = np.array([f[1] for f in funding], dtype=float)
    fg = np.array([f[2] if len(f) > 2 else True for f in funding], dtype=bool)
    return D.SymbolData(symbol="AAA", source="TEST", g0=G0, o=o, h=h, l=l, c=c, v=np.ones(n),
                        valid5=np.ones(n, bool), tick=tick, contract_size=cs, vol_unit=vol_unit,
                        min_vol=min_vol, meta_source="test", funding_t=ft, funding_rate=fr,
                        funding_on_grid=fg, funding_source="TEST")


# Plan: long E=100, S=99, T=E+2(E-S)=102 ; short aynası E=100, S=101, T=98
PLAN = {"LONG": (100.0, 99.0, 102.0), "SHORT": (100.0, 101.0, 98.0)}


def signal(t, side, eid="EV1"):
    E, S, T = PLAN[side]
    return SetupRecord(variant_base="L1_K1", market_event_id=eid, symbol="AAA", side=side, level_id="LV1",
                       level_known_at=t - 4 * HOUR, level_expires_at=t + 44 * HOUR,
                       sweep_open=t - 15 * MIN_MS, sweep_close=t, ATR15_frozen=2.0, terminal_status="SIGNAL",
                       terminal_time=t, signal_time=t, E_plan=E, S_raw=S, S=S, T_raw=T, T=T)


def cost(fee_in=0.0, fee_out=0.0, slip_in=0.0, slip_out=0.0, name="TEST"):
    return C.CostProfile(name=name, entry_fee_rate=fee_in, exit_fee_rate=fee_out, entry_slip_bp=slip_in,
                         exit_slip_bp=slip_out, source="test")


ZERO = cost()


def run(sd, sigs, cst, C0, start=None, end=None):
    start = at(0, 2) if start is None else start
    end = G0 + len(sd.c) * M5 if end is None else end
    U = dict(symbols={"AAA": sd}, g0=G0)
    res = RA.simulate("L1_K1_F0", "DISCOVERY", (start, end), sigs, U, cst, C0)
    return res, (start, end)


def only_trade(res):
    assert len(res.trades) == 1, res.outcomes
    return res.trades[0]


def snap(res, t):
    rows = [r for r in res.equity if r[0] == t]
    assert len(rows) == 1
    return dict(zip(RA.EQUITY_FIELDS, rows[0]))


# ═════════════════════════════ §13 birimler ve dolum formülleri ═════════════════════════════
def test_bp_unit_15_85bp_equals_0_001585():
    # §13: 15,85 bp = 0,001585 ; 0,1585 veya 0,00001585 DEĞİL.
    # 1000*(1+0.001585)=1001.585 (0.1585 olsaydı 1158.5; 0.00001585 olsaydı 1000.01585→1000.0159)
    assert A.entry_fill(1000.0, +1, 15.85, 0.0001) == ap(1001.585)
    # short giriş = satış: 1000*(1-0.001585)=998.415
    assert A.entry_fill(1000.0, -1, 15.85, 0.0001) == ap(998.415)


def test_spec_fallback_cost_table_and_stress_doubles_only_slippage():
    # §13 yedek tablo: giriş/çıkış taker 0,0006 ; giriş kayması 15,85 bp ; çıkış kayması 5 bp
    p = C.SPEC_FALLBACK_PROFILE
    assert p.entry_fee_rate == ap(0.0006) and p.exit_fee_rate == ap(0.0006)
    assert p.entry_slip_bp == ap(15.85) and p.exit_slip_bp == ap(5.0)
    # STRESS: kayma ×2 (31,7 / 10 bp), komisyon oranları aynı
    s = p.stress()
    assert s.entry_slip_bp == ap(31.7) and s.exit_slip_bp == ap(10.0)
    assert s.entry_fee_rate == ap(0.0006) and s.exit_fee_rate == ap(0.0006)


@pytest.mark.parametrize("O,d,bp,tick,exp", [
    (100.0, +1, 15.85, 0.01, 100.16),     # long alış: 100.1585 → YUKARI
    (100.0, -1, 15.85, 0.01, 99.84),      # short satış: 99.8415 → AŞAĞI
    (100.0, +1, 10.0, 0.01, 100.10),      # tam tick (100.1): bir tick daha itilmez
    (100.0, -1, 10.0, 0.01, 99.90),       # tam tick (99.9)
    (100.0, +1, 0.0, 0.01, 100.00),
    (100.0, -1, 0.0, 0.01, 100.00),
    (100.1000001, +1, 0.0, 0.01, 100.11),  # tick*1e-6 toleransının dışında üstte → alış yukarı
    (100.0999999, -1, 0.0, 0.01, 100.09),  # aynası: toleransın dışında altta → satış aşağı
])
def test_entry_fill_formula_and_adverse_tick_rounding(O, d, bp, tick, exp):
    # §13: E_fill = O*(1 + d*bp/1e4), tek fiyatlı dolumda aleyhe tick: alış yukarı, satış aşağı
    assert A.entry_fill(O, d, bp, tick) == ap(exp)


@pytest.mark.parametrize("X,d,bp,tick,exp", [
    (102.0, +1, 5.0, 0.01, 101.94),       # long hedef kapanışı = satış: 101.949 → AŞAĞI
    (98.0, -1, 5.0, 0.01, 98.05),         # short hedef kapanışı = alış: 98.049 → YUKARI
    (99.0, +1, 5.0, 0.01, 98.95),         # long stop: 98.9505 → aşağı
    (101.0, -1, 5.0, 0.01, 101.06),       # short stop: 101.0505 → yukarı
    (100.0, +1, 10.0, 0.01, 99.90),       # tam tick
    (100.0, -1, 10.0, 0.01, 100.10),
])
def test_exit_fill_formula_and_adverse_tick_rounding(X, d, bp, tick, exp):
    # §13: X_fill = X_ref*(1 - d*bp/1e4); long kapanış satış (aşağı), short kapanış alış (yukarı)
    assert A.exit_fill(X, d, bp, tick) == ap(exp)


# ═════════════════════════════ No.26 — açılış boşluğu stopu ═════════════════════════════════
@pytest.mark.parametrize("side,ref,tick,exp", [
    ("LONG", 98.50, 0.001, 98.303),       # 98.50*(1-0.002)=98.303 (yuvarlama öncesi değer tick'te tam)
    ("LONG", 98.50, 0.01, 98.30),         # satış aşağı
    ("SHORT", 101.50, 0.001, 101.703),    # ayna: 101.50*(1+0.002)=101.703
    ("SHORT", 101.50, 0.01, 101.71),      # alış yukarı
])
def test_no26_exit_fill_unit(side, ref, tick, exp):
    d = +1 if side == "LONG" else -1
    assert A.exit_fill(ref, d, 20.0, tick) == ap(exp)


@pytest.mark.parametrize("side,tick,x_ref,x_fill,gross", [
    # Long: E_fill=100, S=99, Q=25 (C0=10000: 25/|100-99|); 12:30 açılışı 98.50 ≤ S → referans O=98.50
    ("LONG", 0.001, 98.50, 98.303, -42.425),   # (98.303-100)*25
    ("LONG", 0.01, 98.50, 98.30, -42.5),       # (98.30-100)*25
    # Short ayna: S=101, açılış 101.50 ≥ S
    ("SHORT", 0.001, 101.50, 101.703, -42.575),  # -(101.703-100)*25
    ("SHORT", 0.01, 101.50, 101.71, -42.75),     # -(101.71-100)*25
])
def test_no26_gap_stop_through_adapter(side, tick, x_ref, x_fill, gross):
    bars = Bars().bar(at(0, 12, 30), 98.50, 98.60, 98.40, 98.50)
    sd = symbol(bars, side, tick=tick)
    res, _ = run(sd, [signal(at(0, 10), side)], cost(slip_out=20.0), 10_000.0)
    tr = only_trade(res)
    assert tr["exit_reason"] == "STOP" and tr["exit_phase"] == "OPEN"
    assert tr["exit_interval_start"] == at(0, 12, 30) and tr["exit_interval_end"] == at(0, 12, 30)
    assert tr["E_fill"] == ap(100.0) and tr["quantity_base"] == ap(25.0)
    assert tr["X_reference"] == ap(x_ref)          # stop referansı açılış; S'den (99/101) dolum yok
    assert tr["X_fill"] == ap(x_fill)
    assert tr["gross_PnL"] == ap(gross) and tr["net_PnL"] == ap(gross)
    assert tr["R0_USDT"] == ap(25.0) and tr["net_R"] == ap(gross / 25.0)
    assert res.ledger.wallet == ap(10_000.0 + gross)


# ═════════════════════════════ No.29 — sözleşme adedi / base miktar ═════════════════════════
@pytest.mark.parametrize("C0", [140.0, 120.0])
@pytest.mark.parametrize("side", SIDES)
def test_no29_contracts_vs_base_quantity_through_adapter(side, C0):
    # C0=140: risk 0.35 → Q_risk=0.35/|100-99|=0.35 → 0.35/0.1=3.5 → 3 sözleşme → Q_base=0.3
    # C0=120: risk 0.30 → 0.30/0.1 = tam 3 sözleşme (kayan nokta 2.999… bir adım kaybettirmemeli)
    bars = Bars().bar(at(0, 16, 40), 100.0, 102.0, 100.0, 101.0)     # hedef 102 (short: 98) temas
    sd = symbol(bars, side, cs=0.1)
    res, _ = run(sd, [signal(at(0, 10), side)], ZERO, C0)
    tr = only_trade(res)
    assert tr["contract_size"] == ap(0.1)
    assert tr["quantity_contracts"] == ap(3.0)
    assert tr["quantity_base"] == ap(0.3)
    assert tr["E_fill"] == ap(100.0)
    assert tr["exit_reason"] == "TARGET" and tr["X_fill"] == ap(102.0 if side == "LONG" else 98.0)
    assert tr["gross_PnL"] == ap(0.6)               # (102-100)*0.3 ; ayna -(98-100)*0.3
    assert tr["R0_USDT"] == ap(0.3)                 # |100-99|*0.3 ; ayna |100-101|*0.3
    assert tr["net_PnL"] == ap(0.6) and tr["net_R"] == ap(2.0)
    # açık pozisyon kesitinde notional = Q_base*fiyat = 0.3*100 = 30 (3*100=300 veya 3 değil)
    row = snap(res, at(0, 10, 5))
    notional = row["long_notional"] if side == "LONG" else row["short_notional"]
    assert notional == ap(30.0)
    assert row["gross_initial_stop_risk"] == ap(0.3)
    assert res.ledger.wallet == ap(C0 + 0.6)


# ═════════════════════════════ No.30 — ücret + funding + net_R ══════════════════════════════
NO30 = {
    # entry_fee=|100*0.3|*0.001 ; exit_fee=|X*0.3|*0.001 ; funding=-d*0.3*mark*0.0001
    # long : X=102, mark=101 → 0.03 + 0.0306 ; funding=-0.00303 ; net=0.6-0.03-0.0306-0.00303=0.53637
    # short: X=98,  mark=99  → 0.03 + 0.0294 ; funding=+0.00297 ; net=0.6-0.03-0.0294+0.00297=0.54357
    "LONG": dict(x=102.0, exit_fee=0.0306, funding=-0.00303, net=0.53637, net_R=1.7879,
                 cash16=139.96697, eq16=140.26697),
    "SHORT": dict(x=98.0, exit_fee=0.0294, funding=0.00297, net=0.54357, net_R=1.8119,
                  cash16=139.97297, eq16=140.27297),
}


def _no30_bars():
    b = Bars()
    b.bar(at(0, 15, 55), 100.0, 101.0, 100.0, 101.0)      # 16:00 settlement'ında bilinen kapanış 101
    b.flat(at(0, 16), at(0, 16, 40), 101.0)
    b.bar(at(0, 16, 40), 101.0, 102.0, 101.0, 101.5)       # hedef 102 temas → çıkış 16:45 sınırında
    return b


def _no30_run(side, cs=0.1, C0=140.0):
    sd = symbol(_no30_bars(), side, cs=cs, funding=[(at(0, 16), 0.0001)])
    return run(sd, [signal(at(0, 10), side)], cost(fee_in=0.001, fee_out=0.001), C0)


@pytest.mark.parametrize("side", SIDES)
def test_no30_fees_funding_net_and_net_R_through_adapter(side):
    e = NO30[side]
    res, _ = _no30_run(side)
    tr = only_trade(res)
    assert tr["quantity_contracts"] == ap(3.0) and tr["quantity_base"] == ap(0.3)
    assert tr["exit_reason"] == "TARGET" and tr["X_fill"] == ap(e["x"])
    assert tr["gross_PnL"] == ap(0.6)
    assert tr["entry_fee"] == ap(0.03)
    assert tr["exit_fee"] == ap(e["exit_fee"])
    assert tr["funding_cashflow"] == ap(e["funding"])
    assert tr["funding_events"] == 1
    assert tr["net_PnL"] == ap(e["net"])
    assert tr["R0_USDT"] == ap(0.3)
    assert tr["net_R"] == pytest.approx(e["net_R"], abs=1e-9)
    # funding ve giriş ücreti cüzdanda TEK kez: wallet = C0 + net
    led = res.ledger
    assert led.wallet == ap(140.0 + e["net"])
    assert led.funding == ap(e["funding"])
    assert led.entry_fees == ap(0.03) and led.exit_fees == ap(e["exit_fee"])
    assert led.fees == ap(0.03 + e["exit_fee"])
    assert led.realized_gross == ap(0.6)
    assert led.reserved_margin == ap(0.0) and led.free_collateral == ap(140.0 + e["net"])


@pytest.mark.parametrize("side", SIDES)
def test_no30_equity_snapshots_entry_fee_once_and_margin_not_a_loss(side):
    e = NO30[side]
    res, _ = _no30_run(side)
    # 10:00 kesiti yeni girişten ÖNCE kaydedilir
    r0 = snap(res, at(0, 10))
    assert r0["cash_balance"] == ap(140.0) and r0["equity"] == ap(140.0) and r0["open_positions"] == 0
    # 10:05: giriş ücreti doğru anda nakitte; tahakkuk sütunu 0 (ikinci kez düşülmez); marjin zarar değil
    r1 = snap(res, at(0, 10, 5))
    assert r1["open_positions"] == 1
    assert r1["cash_balance"] == ap(139.97)
    assert r1["unposted_entry_fee_accrual"] == ap(0.0)
    assert r1["unrealized_PnL"] == ap(0.0)
    assert r1["equity"] == ap(139.97)
    assert r1["reserved_margin"] > 0
    assert r1["cumulative_fees"] == ap(0.03)
    # 16:00: kapanış 101 (short: 99) yayınlandı, funding işlendi, kesit alındı
    r2 = snap(res, at(0, 16))
    assert r2["cash_balance"] == ap(e["cash16"])
    assert r2["unrealized_PnL"] == ap(0.3)          # (101-100)*0.3 ; ayna -(99-100)*0.3
    assert r2["equity"] == ap(e["eq16"])
    assert r2["cumulative_funding"] == ap(e["funding"])
    # 16:45: hedef bar içi kapandı
    r3 = snap(res, at(0, 16, 45))
    assert r3["open_positions"] == 0 and r3["reserved_margin"] == ap(0.0)
    assert r3["cash_balance"] == ap(140.0 + e["net"]) and r3["equity"] == ap(140.0 + e["net"])
    assert r3["cumulative_fees"] == ap(0.03 + e["exit_fee"])
    assert r3["cumulative_funding"] == ap(e["funding"])
    # her kesitte ekonomik özsermaye = nakit + açık PnL (marjin düşülmez)
    for row in res.equity:
        d = dict(zip(RA.EQUITY_FIELDS, row))
        assert d["equity"] == ap(d["cash_balance"] + d["unrealized_PnL"])
    assert res.flags["identity_max_gap"] <= 1e-6


@pytest.mark.parametrize("side", SIDES)
def test_no30_run_metrics_cost_breakdown_and_reconciliation(side):
    e = NO30[side]
    res, win = _no30_run(side)
    m = MT.run_metrics(res, [], win, 140.0, "DISCOVERY")
    assert m["closed"] == 1
    assert m["entry_fees"] == ap(0.03) and m["exit_fees"] == ap(e["exit_fee"])
    assert m["funding"] == ap(e["funding"])
    assert m["net_USDT"] == ap(e["net"])
    assert m["end_wallet"] == ap(140.0 + e["net"])
    assert abs(m["reconciliation_gap"]) <= 1e-6
    assert m["metrics_valid"] is True


@pytest.mark.parametrize("side,funding,exit_fee,net", [
    ("LONG", -0.00303, 0.0306, 0.53637),
    ("SHORT", 0.00297, 0.0294, 0.54357),
])
def test_no30_ledger_identity_unit(side, funding, exit_fee, net):
    # §16 wallet = C0 + realized_gross - entry_fees - exit_fees + funding ; free = wallet - margin
    L = A.Ledger(140.0)
    L.open(3.0, 0.03)                 # marjin 3 ayrılır, ücret 0.03 düşülür
    assert L.wallet == ap(139.97)     # marjin cüzdandan zarar olarak düşülmez
    assert L.reserved_margin == ap(3.0) and L.free_collateral == ap(136.97)
    L.fund(funding)
    assert L.wallet == ap(139.97 + funding)
    L.close(0.6, exit_fee, 3.0)
    assert L.wallet == ap(140.0 + net)
    assert L.reserved_margin == ap(0.0) and L.free_collateral == ap(140.0 + net)
    assert L.realized_gross == ap(0.6) and L.funding == ap(funding)
    assert L.entry_fees == ap(0.03) and L.exit_fees == ap(exit_fee) and L.fees == ap(0.03 + exit_fee)
    assert abs(L.identity_gap()) <= 1e-12


def test_funding_sign_unit():
    # §16 funding_cf = -d*Q_base*mark*rate ; pozitif oranda long öder, short alır
    assert A.funding_cashflow(+1, 0.3, 101.0, 0.0001) == ap(-0.00303)
    assert A.funding_cashflow(-1, 0.3, 99.0, 0.0001) == ap(0.00297)
    # negatif oranda yönler tersine döner
    assert A.funding_cashflow(+1, 0.3, 101.0, -0.0001) == ap(0.00303)
    assert A.funding_cashflow(-1, 0.3, 99.0, -0.0001) == ap(-0.00297)


# ═════════════════════════════ contract_size ≠ 1 — base/sözleşme ayrımı ═════════════════════
@pytest.mark.parametrize("side,exit_fee,funding,net", [
    # cs=10, C0=10000: 25/|100-99|=25 → 25/10=2.5 → 2 sözleşme → Q_base=20
    # long : gross=(102-100)*20=40 ; ücret 100*20*0.001=2.0 + 102*20*0.001=2.04 ; funding -20*101*1e-4=-0.202
    #        net=40-2-2.04-0.202=35.758
    # short: gross=40 ; ücret 2.0 + 98*20*0.001=1.96 ; funding +20*99*1e-4=+0.198 ; net=40-2-1.96+0.198=36.238
    ("LONG", 2.04, -0.202, 35.758),
    ("SHORT", 1.96, 0.198, 36.238),
])
def test_contract_size_10_quantity_fees_funding_use_base(side, exit_fee, funding, net):
    res, _ = _no30_run(side, cs=10.0, C0=10_000.0)
    tr = only_trade(res)
    assert tr["quantity_contracts"] == ap(2.0) and tr["quantity_base"] == ap(20.0)
    assert tr["gross_PnL"] == ap(40.0)
    assert tr["entry_fee"] == ap(2.0) and tr["exit_fee"] == ap(exit_fee)
    assert tr["funding_cashflow"] == ap(funding)
    assert tr["net_PnL"] == ap(net)
    assert tr["R0_USDT"] == ap(20.0)
    assert tr["net_R"] == ap(net / 20.0)
    row = snap(res, at(0, 10, 5))
    assert (row["long_notional"] if side == "LONG" else row["short_notional"]) == ap(2000.0)   # 20*100
    assert res.ledger.wallet == ap(10_000.0 + net)


# ═════════════════════════════ No.31–33 — funding zamanlaması (§15) ═════════════════════════
@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("entry,exit_t,n_events,funding_long", [
    # No.31: giriş tam 08:00 açılışında → 08:00 settlement (oran 0.002) ÖDENMEZ;
    #        16:00 settlement (oran 0.001) ödenir: -25*100*0.001 = -2.5 ; zaman çıkışı 20:00
    (at(0, 8), at(0, 20), 1, -2.5),
    # karşıt durum: 07:55'te açılan pozisyon 08:00'a ulaşır → ikisi de: -5.0 + -2.5 = -7.5 ; çıkış 19:55
    (at(0, 7, 55), at(0, 19, 55), 2, -7.5),
])
def test_no31_entry_at_settlement_open_does_not_pay(side, entry, exit_t, n_events, funding_long):
    sd = symbol(Bars(), side, funding=[(at(0, 8), 0.002), (at(0, 16), 0.001)])
    res, _ = run(sd, [signal(entry, side)], ZERO, 10_000.0)
    tr = only_trade(res)
    exp = funding_long if side == "LONG" else -funding_long          # short alır
    assert tr["quantity_base"] == ap(25.0)
    assert tr["exit_reason"] == "TIME_EXIT" and tr["exit_interval_start"] == exit_t
    assert tr["funding_events"] == n_events
    assert tr["funding_cashflow"] == ap(exp)
    assert tr["gross_PnL"] == ap(0.0) and tr["net_PnL"] == ap(exp)
    assert res.ledger.funding == ap(exp)
    assert res.ledger.wallet == ap(10_000.0 + exp)


@pytest.mark.parametrize("side,x_ref,funding,net", [
    # Long: 20:00 giriş, 08:00 = 12 saat → TIME_EXIT 08:00 açılışında (O=100.40).
    # 08:00 funding önce, mark = 07:55–08:00 kapanışı 100.50 (08:00 açılışı değil):
    # -25*100.50*0.001 = -2.5125 ; gross=(100.40-100)*25=10 ; net=7.4875
    ("LONG", 100.40, -2.5125, 7.4875),
    # Short ayna: kapanış 99.50, açılış 99.60 → +25*99.50*0.001=+2.4875 ; gross=-(99.60-100)*25=10 ; net=12.4875
    ("SHORT", 99.60, 2.4875, 12.4875),
])
def test_no32_funding_before_single_time_exit(side, x_ref, funding, net):
    bars = Bars()
    bars.bar(at(1, 7, 55), 100.0, 100.50, 100.0, 100.50)
    bars.bar(at(1, 8), 100.40, 100.40, 100.40, 100.40)
    sd = symbol(bars, side, funding=[(at(1, 8), 0.001)])
    res, _ = run(sd, [signal(at(0, 20), side)], ZERO, 10_000.0)
    tr = only_trade(res)                                           # tek kapanış
    assert tr["exit_reason"] == "TIME_EXIT" and tr["exit_phase"] == "OPEN"
    assert tr["exit_interval_start"] == at(1, 8) and tr["exit_interval_end"] == at(1, 8)
    assert tr["X_reference"] == ap(x_ref) and tr["X_fill"] == ap(x_ref)
    assert tr["funding_events"] == 1
    assert tr["funding_cashflow"] == ap(funding)
    assert tr["gross_PnL"] == ap(10.0)
    assert tr["net_PnL"] == ap(net)
    assert res.ledger.wallet == ap(10_000.0 + net)
    closed = [o for o in res.outcomes if o["terminal_status"] == "CLOSED"]
    assert len(closed) == 1
    # 08:00 kesiti (zaman çıkışından ÖNCE): pozisyon hâlâ açık ve funding işlenmiş
    r = snap(res, at(1, 8))
    assert r["open_positions"] == 1 and r["cumulative_funding"] == ap(funding)
    assert snap(res, at(1, 8, 5))["open_positions"] == 0


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("stop_bar,iv_end,funding_long", [
    # No.33: 07:55–08:00 barında stop → 08:00 settlement'ına (oran 0.002) GİRMEZ.
    #        00:00 settlement (oran 0.001, giriş 22:00'de açık) ödenir: -25*100*0.001 = -2.5
    (at(1, 7, 55), at(1, 8), -2.5),
    # karşıt: stop 08:00–08:05 barında → pozisyon 08:00'da açıktı: -2.5 + (-25*100*0.002) = -7.5
    (at(1, 8), at(1, 8, 5), -7.5),
])
def test_no33_stopped_inside_prior_bar_skips_settlement(side, stop_bar, iv_end, funding_long):
    bars = Bars().bar(stop_bar, 100.0, 100.0, 98.90, 99.20)        # long S=99 ; ayna h=101.10 ≥ S=101
    sd = symbol(bars, side, funding=[(at(1, 0), 0.001), (at(1, 8), 0.002)])
    res, _ = run(sd, [signal(at(0, 22), side)], ZERO, 10_000.0)
    tr = only_trade(res)
    exp_f = funding_long if side == "LONG" else -funding_long
    assert tr["exit_reason"] == "STOP" and tr["exit_phase"] == "INTRABAR"
    assert tr["exit_interval_start"] == stop_bar and tr["exit_interval_end"] == iv_end
    assert tr["X_reference"] == ap(PLAN[side][1]) and tr["X_fill"] == ap(PLAN[side][1])
    assert tr["gross_PnL"] == ap(-25.0)                              # (99-100)*25 ; ayna -(101-100)*25
    assert tr["funding_cashflow"] == ap(exp_f)
    assert tr["net_PnL"] == ap(-25.0 + exp_f)
    assert res.ledger.funding == ap(exp_f)
    assert res.ledger.wallet == ap(10_000.0 - 25.0 + exp_f)


@pytest.mark.parametrize("side,funding,net", [
    # Gerçek settlement zamanları (8 saatlik sabit ızgara varsayımı yok): 11:00 (+0.001), 12:00 (-0.0005)
    # long : -25*100.20*0.001 = -2.505 ; -25*100.60*(-0.0005) = +1.2575 ; toplam -1.2475
    #        TIME_EXIT 22:00 açılışı 100.60 → gross=15 ; net=13.7525
    ("LONG", -1.2475, 13.7525),
    # short: +25*99.80*0.001 = +2.495 ; +25*99.40*(-0.0005) = -1.2425 ; toplam +1.2525 ; gross=15 ; net=16.2525
    ("SHORT", 1.2525, 16.2525),
])
def test_funding_real_settlement_times_summed_once(side, funding, net):
    bars = Bars()
    bars.bar(at(0, 10, 55), 100.0, 100.20, 100.0, 100.20)
    bars.flat(at(0, 11), at(0, 11, 55), 100.20)
    bars.bar(at(0, 11, 55), 100.20, 100.60, 100.20, 100.60)
    bars.flat(at(0, 12), at(3, 0), 100.60)
    sd = symbol(bars, side, funding=[(at(0, 11), 0.001), (at(0, 12), -0.0005)])
    res, win = run(sd, [signal(at(0, 10), side)], ZERO, 10_000.0)
    tr = only_trade(res)
    assert tr["exit_reason"] == "TIME_EXIT" and tr["exit_interval_start"] == at(0, 22)
    assert tr["funding_events"] == 2
    assert tr["funding_cashflow"] == ap(funding)
    assert tr["gross_PnL"] == ap(15.0)
    assert tr["net_PnL"] == ap(net)
    assert res.ledger.funding == ap(funding)
    assert res.ledger.wallet == ap(10_000.0 + net)
    m = MT.run_metrics(res, [], win, 10_000.0, "DISCOVERY")
    assert m["funding"] == ap(funding) and m["net_USDT"] == ap(net)
    assert abs(m["reconciliation_gap"]) <= 1e-6


# ═════════════════════════════ §13 NORMAL/STRESS, TP piyasa çıkışı, kayma tek kez ══════════
FALLBACK_EXP = {
    # LONG NORMAL: E=ceil(100.1585)=100.16 ; Q=floor(25/1.16=21.55)=21 ; X=floor(102*0.9995=101.949)=101.94
    #   gross=(101.94-100.16)*21=37.38 ; giriş ücreti 100.16*21*0.0006=1.262016 ; çıkış 101.94*21*0.0006=1.284444
    #   net=34.83354 ; R0=1.16*21=24.36
    ("LONG", "NORMAL"): dict(E=100.16, Q=21.0, X=101.94, gross=37.38, fin=1.262016, fout=1.284444,
                             net=34.83354, R0=24.36),
    # LONG STRESS (31.7/10 bp): E=ceil(100.317)=100.32 ; Q=floor(25/1.32=18.94)=18 ; X=floor(101.898)=101.89
    #   gross=1.57*18=28.26 ; 100.32*18*0.0006=1.083456 ; 101.89*18*0.0006=1.100412 ; net=26.076132 ; R0=23.76
    ("LONG", "STRESS"): dict(E=100.32, Q=18.0, X=101.89, gross=28.26, fin=1.083456, fout=1.100412,
                             net=26.076132, R0=23.76),
    # SHORT NORMAL: E=floor(99.8415)=99.84 ; Q=21 ; X=ceil(98*1.0005=98.049)=98.05
    #   gross=(99.84-98.05)*21=37.59 ; 99.84*21*0.0006=1.257984 ; 98.05*21*0.0006=1.23543 ; net=35.096586
    ("SHORT", "NORMAL"): dict(E=99.84, Q=21.0, X=98.05, gross=37.59, fin=1.257984, fout=1.23543,
                              net=35.096586, R0=24.36),
    # SHORT STRESS: E=floor(99.683)=99.68 ; Q=18 ; X=ceil(98.098)=98.10
    #   gross=1.58*18=28.44 ; 99.68*18*0.0006=1.076544 ; 98.10*18*0.0006=1.05948 ; net=26.303976
    ("SHORT", "STRESS"): dict(E=99.68, Q=18.0, X=98.10, gross=28.44, fin=1.076544, fout=1.05948,
                              net=26.303976, R0=23.76),
}


@pytest.mark.parametrize("scenario", ["NORMAL", "STRESS"])
@pytest.mark.parametrize("side", SIDES)
def test_fallback_profile_normal_and_stress_reexecuted(side, scenario):
    """Aynı olay yeni maliyetle yeniden yürütülür (miktar değişebilir); TP piyasa çıkışıdır
    (çıkış kayması uygulanır, sıfır kayma muafiyeti yok, taker ücreti); kayma yalnız dolum
    fiyatında — net PnL'den ikinci kez düşülmez; E_budget == E_fill."""
    e = FALLBACK_EXP[(side, scenario)]
    prof = C.SPEC_FALLBACK_PROFILE if scenario == "NORMAL" else C.SPEC_FALLBACK_PROFILE.stress()
    bars = Bars().bar(at(0, 16, 40), 100.0, 102.0, 100.0, 101.0)
    res, _ = run(symbol(bars, side), [signal(at(0, 10), side)], prof, 10_000.0)
    tr = only_trade(res)
    assert tr["entry_open"] == ap(100.0)
    assert tr["E_fill"] == ap(e["E"]) and tr["E_budget"] == ap(e["E"])
    assert tr["quantity_base"] == ap(e["Q"])
    assert tr["T"] == ap(PLAN[side][2])                # T dolumdan sonra yeniden 2R'ye taşınmaz
    assert tr["exit_reason"] == "TARGET"
    assert tr["X_reference"] == ap(PLAN[side][2]) and tr["X_fill"] == ap(e["X"])
    assert tr["gross_PnL"] == ap(e["gross"])
    assert tr["entry_fee"] == ap(e["fin"]) and tr["exit_fee"] == ap(e["fout"])
    assert tr["net_PnL"] == ap(e["net"])
    assert tr["R0_USDT"] == ap(e["R0"])
    assert tr["net_R"] == ap(e["net"] / e["R0"])
    assert res.ledger.wallet == ap(10_000.0 + e["net"])


@pytest.mark.parametrize("side,kind,x_fill,gross,exit_fee,net", [
    # §13 çıkış kayması "stop, hedef ve zaman çıkışına ortak" — yedek profil NORMAL (15.85 / 5 bp, 0.0006)
    # Long: E_fill=100.16, Q=21 (bkz. FALLBACK_EXP), giriş ücreti 1.262016
    #  STOP (bar içi, S=99): X=floor(99*0.9995=98.9505)=98.95 ; gross=(98.95-100.16)*21=-25.41
    #        çıkış ücreti 98.95*21*0.0006=1.24677 ; net=-25.41-1.262016-1.24677=-27.918786
    ("LONG", "STOP", 98.95, -25.41, 1.24677, -27.918786),
    #  TIME_EXIT (22:00 açılışı 100): X=floor(99.95)=99.95 ; gross=(99.95-100.16)*21=-4.41
    #        çıkış ücreti 99.95*21*0.0006=1.25937 ; net=-4.41-1.262016-1.25937=-6.931386
    ("LONG", "TIME_EXIT", 99.95, -4.41, 1.25937, -6.931386),
    # Short: E_fill=99.84, Q=21, giriş ücreti 1.257984
    #  STOP (S=101): X=ceil(101*1.0005=101.0505)=101.06 ; gross=-(101.06-99.84)*21=-25.62
    #        çıkış ücreti 101.06*21*0.0006=1.273356 ; net=-28.15134
    ("SHORT", "STOP", 101.06, -25.62, 1.273356, -28.15134),
    #  TIME_EXIT (açılış 100): X=ceil(100.05)=100.05 ; gross=-(100.05-99.84)*21=-4.41
    #        çıkış ücreti 100.05*21*0.0006=1.26063 ; net=-6.928614
    ("SHORT", "TIME_EXIT", 100.05, -4.41, 1.26063, -6.928614),
])
def test_exit_slippage_applies_to_stop_and_time_exit(side, kind, x_fill, gross, exit_fee, net):
    bars = Bars()
    if kind == "STOP":
        bars.bar(at(0, 12), 100.0, 100.0, 98.90, 99.20)
    res, _ = run(symbol(bars, side), [signal(at(0, 10), side)], C.SPEC_FALLBACK_PROFILE, 10_000.0)
    tr = only_trade(res)
    assert tr["exit_reason"] == kind
    x_ref = PLAN[side][1] if kind == "STOP" else 100.0
    assert tr["X_reference"] == ap(x_ref) and tr["X_fill"] == ap(x_fill)
    assert tr["quantity_base"] == ap(21.0)
    assert tr["gross_PnL"] == ap(gross)
    assert tr["exit_fee"] == ap(exit_fee)
    assert tr["net_PnL"] == ap(net)
    assert res.ledger.wallet == ap(10_000.0 + net)


@pytest.mark.parametrize("side,funding", [("LONG", -2.5), ("SHORT", 2.5)])
def test_duplicated_settlement_row_charged_once_end_to_end(tmp_path, side, funding):
    # Aynı 16:00 settlement'ı CSV'de ms titreşimiyle iki kez: veri katmanı → adaptör yolunda TEK kez
    # ücretlendirilir: -d*25*100*0.001 = ∓2.5 (iki kez sayılsaydı ∓5.0)
    p = tmp_path / "AAA.csv"
    p.write_text("calc_time,funding_interval_hours,last_funding_rate\n"
                 f"{at(0, 16)},8,0.001\n{at(0, 16) + 7},8,0.001\n")
    ft, fr, fg, src, q = D.load_funding(str(p), G0, at(3, 0))
    sd = symbol(Bars(), side, funding=list(zip(ft.tolist(), fr.tolist(), fg.tolist())))
    res, _ = run(sd, [signal(at(0, 10), side)], ZERO, 10_000.0)
    tr = only_trade(res)
    assert tr["funding_events"] == 1
    assert tr["funding_cashflow"] == ap(funding)
    assert res.ledger.funding == ap(funding)
    assert res.ledger.wallet == ap(10_000.0 + funding)


def test_missing_funding_data_is_not_modeled_not_measured_zero():
    # §16: hiç funding verisi yoksa NOT_MODELED; sıfır funding ölçülmüş gibi sunulmaz
    t, r, g, src, q = D.load_funding(None, G0, G0 + DAY)
    assert src == "NOT_MODELED" and len(t) == 0 and len(r) == 0


# ═════════════════════════════ No.38 — PaperExchange serbest bakiyesinden ekonomik özsermaye ═
def test_no38_economic_equity_from_paper_free_balance():
    # serbest 900 + marjin 100 + uPnL 20 − motorca henüz düşülmemiş giriş ücreti 1 = 1019
    assert A.economic_equity_from_paper(900.0, 100.0, 20.0, 1.0) == ap(1019.0)
    # motor ücreti düştükten sonra (serbest 899, tahakkuk 0) aynı 1019: ücret iki kez düşülmez,
    # marjin zarar sayılmaz (919 veya 1018 yanlış olurdu)
    assert A.economic_equity_from_paper(899.0, 100.0, 20.0, 0.0) == ap(1019.0)


@pytest.mark.parametrize("side,d,mark", [("LONG", +1, 102.0), ("SHORT", -1, 98.0)])
def test_no38_mirror_unrealized_from_long_and_short(side, d, mark):
    # Q_base=10, E_fill=100 ; long mark 102 → +20 ; short ayna mark 98 → +20
    S, T = (98.0, 104.0) if d > 0 else (102.0, 96.0)
    p = A.Position(trade_id="X", symbol="AAA", d=d, q_contracts=10.0, q_base=10.0, contract_size=1.0,
                   E_fill=100.0, S=S, T=T, entry_k=0, entry_time=G0, entry_open=100.0, E_budget=100.0,
                   margin=100.0, entry_fee=1.0, R0=20.0, rec=None)
    upnl = p.unrealized(mark)
    assert upnl == ap(20.0)
    assert A.economic_equity_from_paper(900.0, 100.0, upnl, 1.0) == ap(1019.0)


# ═════════════════════════════ ızgaraya oturmayan settlement (§15 son paragraf, §16 mark) ═══
# Not: gerçek veri setindeki 12 sembolün 49.284 settlement'ının hiçbiri ızgara dışında değil
# (load_funding ±1 sn oturtması sonrası), yani aşağıdaki iki hata mevcut koşularda gizli kalır.
@pytest.mark.parametrize("side,allowed", [
    # 16:02 settlement'ında BİLİNEN son fiyat: 15:55–16:00 kapanışı 100.50 (veya 16:00 açılışı 100.40).
    # 16:00–16:05 kapanışı 100.90 ancak 16:05'te bilinir → kullanılamaz.
    ("LONG", (-2.5125, -2.51)),           # -25*100.50*0.001 / -25*100.40*0.001
    ("SHORT", (2.4875, 2.49)),            # +25*99.50*0.001 / +25*99.60*0.001
])
def test_offgrid_settlement_uses_price_known_at_settlement(side, allowed):
    bars = Bars()
    bars.bar(at(0, 15, 55), 100.0, 100.50, 100.0, 100.50)
    bars.bar(at(0, 16), 100.40, 100.90, 100.40, 100.90)
    bars.flat(at(0, 16, 5), at(3, 0), 100.90)
    sd = symbol(bars, side, funding=[(at(0, 16, 2), 0.001, False)])
    res, _ = run(sd, [signal(at(0, 10), side)], ZERO, 10_000.0)
    tr = only_trade(res)
    assert tr["funding_events"] == 1
    assert any(tr["funding_cashflow"] == ap(v) for v in allowed), tr["funding_cashflow"]


@pytest.mark.parametrize("side", SIDES)
def test_offgrid_settlement_with_exit_in_same_interval_is_flagged(side):
    # 16:02 settlement ; pozisyon 16:00–16:05 barı içinde stoplandı → çıkış/funding sırası bilinemez,
    # belirsizlik işaretlenmeli (kesin net getiri onayına dayanak olamaz).
    bars = Bars().bar(at(0, 16), 100.0, 100.0, 98.90, 99.20)
    sd = symbol(bars, side, funding=[(at(0, 16, 2), 0.001, False)])
    res, win = run(sd, [signal(at(0, 10), side)], ZERO, 10_000.0)
    tr = only_trade(res)
    assert tr["exit_reason"] == "STOP" and tr["exit_interval_start"] == at(0, 16)
    m = MT.run_metrics(res, [], win, 10_000.0, "DISCOVERY")
    assert m["funding_order_ambiguous"] is True
