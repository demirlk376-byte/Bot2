"""
Bağımsız davranış testleri — şartname §9 (K3), §10 (K4), §11 (stop/hedef), §21 fixture
No.16, 17, 18, 19, 20, 21, 22 ve ek zorunlu test "yalnız teyit sonrası barların K3/K4 zaman
sayacına girmesi".

Beklenen bütün sayılar ŞARTNAMEDEN elle türetilmiş sabitlerdir; üretim fonksiyonu yeniden
çağrılarak hesaplanmaz. §21 varsayımları: fiyat adımı 0,01; contract_size=1; ücret/kayma sıfır.

Fixture düzeni (long biçim, doğrudan 5m ızgara; G0 = 2024-01-01 00:00 UTC, k = 5m bar indeksi):
  * Gün 0 (k 0..287) düz 102,00; k=6 low=100,00 ve k=12 high=104,00 → gün 1 için L1 LOW=100,00,
    L1 HIGH=104,00 (known=gün1 00:00, expires=gün2 00:00). Bu iki 5m pivot gün 0 ~01:00'de
    onaylanır, t başlangıcından >24 saat önce → mikro referans olamaz.
  * Gün 1 ve 2 düz 100,50 (düz barlar eşitlik nedeniyle hiçbir pivot üretmez).
  * Mikro pivot high H=101,00: k=432 (gün1 12:00) high=101,00; onayı p+2 kapanışı = k=435 açılışı
    (12:15) → t başlangıcından 45 dk önce.
  * Sweep 15m barı t = gün1 13:00 → 5m k=444,445,446; 15m O/H/L/C = 100,50/100,70/99,50/100,60.
    A (15m ATR14[t−1]) §21 izniyle 2,0 sabitine ayarlanır; ATR5 sabit 1,0 ("önceki ATR5=1").
      → L=100, low 99,50 <= 100−0,20 → ihlal; close 100,60 > 100 → K1 reclaim (No.9 ile aynı).
      → sweep_extreme=99,50; S_raw=99,50−0,10·2=99,30; S=99,30 (aşağı tick).
  * K3 penceresi: K1 kapanışından (13:15) sonra açılan ilk altı 5m bar = k=447..452.
  * No.18: m=448 open=100,70 close=101,30 → gövde 0,60 >= 0,50·ATR5[m−1]=0,50 → K3 sinyali
      E_plan=101,30; S=99,30 (K1'de sabit); T=101,30+2·(101,30−99,30)=105,30.
  * No.19: m−1=447 high=100,90; m+1=449 low=101,10 → FVG [100,90; 101,10], G_mid=101,00;
      fvg_known_at = 449 kapanışı = k=450 açılışı (13:30).
  * No.20: K4 penceresi k=450..455; r=450 low=100,95 <= 101,00, close=101,20 > 101,10 → K4 sinyali
      E_plan=101,20 (G_mid değil); T=101,20+2·(101,20−99,30)=105,00. Dolum k=451 açılışı (101,25).

Kısa yön aynası: x → 200 − x. OHLC rolleri değişir: (O,H,L,C) → (200−O, 200−L, 200−H, 200−C).
Kısa yön beklenen değerleri de aşağıdaki tabloda elle yazılmıştır (ör. S=100,70; D=99,00;
E_K3=98,70; T_K3=98,70−2·(100,70−98,70)=94,70; FVG [98,90; 99,10]; E_K4=98,80; T_K4=95,00).
"""
from __future__ import annotations

import numpy as np
import pytest

from research.liquidity_sweep_v1 import config as C
from research.liquidity_sweep_v1 import data_contract as D
from research.liquidity_sweep_v1 import events as EV
from research.liquidity_sweep_v1 import levels as LV
from research.liquidity_sweep_v1 import replay_adapter as RA
from research.liquidity_sweep_v1 import setups as SU

SYM = "TST"
G0 = 1_704_067_200_000            # 2024-01-01 00:00 UTC
M5_MS = 300_000
DAY_MS = 86_400_000
P_MIRROR = 200.0
K0 = 288 + 52 * 3                 # 444: t (gün1 13:00) ilk 5m barı
EXPIRY = G0 + 2 * DAY_MS          # gün 1 L1 seviyesinin expires_at'i
AP = dict(abs=1e-9)
SIDES = ["LONG", "SHORT"]


def TS(k):
    """5m bar k'nin açılış zamanı (ms) = bar k−1'in kapanışı."""
    return G0 + k * M5_MS


# ─────────────────────────── elle türetilmiş beklenen değerler ────────────────────────────
EXP = {
    "LONG": dict(L=100.00, extreme=99.50, S_raw=99.30, S=99.30, H=101.00,
                 E3=101.30, T3=105.30, G_lo=100.90, G_hi=101.10, G_mid=101.00,
                 E4=101.20, T4=105.00, fill=101.25,
                 E_half=101.20, T_half=105.00,          # gövde tam 0,50 durumu
                 E4b=101.25, T4b=105.15,                # low == G_mid ile teyit durumu
                 H_old=103.00, H_hi=101.50),
    "SHORT": dict(L=100.00, extreme=100.50, S_raw=100.70, S=100.70, H=99.00,
                  E3=98.70, T3=94.70, G_lo=98.90, G_hi=99.10, G_mid=99.00,
                  E4=98.80, T4=95.00, fill=98.75,
                  E_half=98.80, T_half=95.00,
                  E4b=98.75, T4b=94.85,
                  H_old=97.00, H_hi=98.50),
}

# ─────────────────────────── 5m bar yapı taşları (long biçim) ─────────────────────────────
DAY0_FLAT = (102.0, 102.0, 102.0, 102.0)
FLAT = (100.5, 100.5, 100.5, 100.5)
PIV_H101 = {432: (100.5, 101.0, 100.5, 100.5)}                 # H=101, onay k=435 açılışı
SWEEP = {444: (100.5, 100.5, 99.5, 99.6),
         445: (99.6, 100.4, 99.6, 100.3),
         446: (100.3, 100.7, 100.3, 100.6)}                     # 15m: 100.5/100.7/99.5/100.6
NK3 = (100.6, 100.7, 100.5, 100.6)        # K3 nötr bekleme: close<=H, low>S
M_PREV = (100.6, 100.9, 100.5, 100.7)     # m−1: high=100,90, close<=H
M_STRONG = (100.7, 101.4, 100.65, 101.3)  # No.18 ilk kırılım: gövde 0,60
M_PLUS1 = (101.3, 101.5, 101.1, 101.4)    # m+1: low=101,10 → FVG
NK4 = (101.3, 101.35, 101.15, 101.3)      # K4 nötr bekleme: low>G_mid, G_lo<=close
RETEST = (101.4, 101.45, 100.95, 101.2)   # No.20 retest: low 100,95, close 101,20
ENTRY_BAR = (101.25, 101.3, 101.2, 101.25)


def base(**extra):
    d = {}
    d.update(PIV_H101)
    d.update(SWEEP)
    d.update(extra)
    return d


def k4_base(**extra):
    d = base()
    d.update({447: M_PREV, 448: M_STRONG, 449: M_PLUS1, 450: RETEST, 451: ENTRY_BAR})
    d.update(extra)
    return d


def mirror(bar):
    O, H, L, Cc = bar
    P = P_MIRROR
    return (round(P - O, 2), round(P - L, 2), round(P - H, 2), round(P - Cc, 2))


def build(over, side, n_days=3, atr5=1.0, atr5_at=None, A=2.0):
    bars = [DAY0_FLAT] * 288 + [FLAT] * (288 * (n_days - 1))
    bars[6] = (102.0, 102.0, 100.0, 102.0)     # gün 0 dibi → L1 LOW=100
    bars[12] = (102.0, 104.0, 102.0, 102.0)    # gün 0 tepesi → L1 HIGH=104
    for k, b in over.items():
        bars[k] = b
    if side == "SHORT":
        bars = [mirror(b) for b in bars]
    for b in bars:
        O, H, L, Cc = b
        assert 0 < L <= min(O, Cc) and max(O, Cc) <= H, b
    arr = np.array(bars, float)
    n = len(bars)
    sd = D.SymbolData(symbol=SYM, source="TEST", g0=G0, o=arr[:, 0].copy(), h=arr[:, 1].copy(),
                      l=arr[:, 2].copy(), c=arr[:, 3].copy(), v=np.ones(n), valid5=np.ones(n, bool),
                      tick=0.01, contract_size=1.0, vol_unit=0.1, min_vol=0.1, meta_source="test")
    dv = LV.Derived(sd)
    dv.atr15 = np.full(len(dv.c15), float(A))          # §21: warmup hazır (A=2)
    dv.atr5 = np.full(n, float(atr5))                  # §21: "önceki ATR5=1"
    for k, a in (atr5_at or {}).items():
        dv.atr5[k] = a
    book = LV.LevelBook("L1", dv)
    evs, _ = EV.detect("L1", dv, book)
    return sd, dv, evs


def event_at(evs, side, k0=K0, A=2.0):
    ev = [e for e in evs if e.side == side and e.sweep_open == TS(k0)]
    assert len(ev) == 1, [(e.side, e.sweep_open) for e in evs]
    ev = ev[0]
    assert ev.level_price == pytest.approx(100.0, **AP)
    assert ev.A == pytest.approx(A, **AP)
    assert ev.sweep_close == TS(k0 + 3)
    return ev


def run(model, over, side, **kw):
    sd, dv, evs = build(over, side, **kw)
    ev = event_at(evs, side, A=kw.get("A", 2.0))
    fn = SU.eval_K3 if model == "K3" else SU.eval_K4
    return fn(ev, dv), ev, sd, dv


def run_k0(model, over, side, k0):
    sd, dv, evs = build(over, side)
    ev = event_at(evs, side, k0)
    fn = SU.eval_K3 if model == "K3" else SU.eval_K4
    return fn(ev, dv), ev


def assert_terminal(r, status, t):
    assert r.terminal_status == status, (r.terminal_status, r.reason_code)
    assert r.reason_code == status
    assert r.terminal_time == t


# ═════════════════════════ §9 K3 sinyali — No.18 ══════════════════════════════════════════
@pytest.mark.parametrize("side", SIDES)
def test_no18_k3_signal_values(side):
    e = EXP[side]
    r, ev, _, _ = run("K3", k4_base(), side)
    assert ev.micro_ref is not None
    assert ev.micro_ref[0] == pytest.approx(e["H"], **AP)
    assert ev.micro_ref[1] == TS(435)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.reclaim_time == TS(447)                    # K1 reclaim = t kapanışı
    assert r.micro_reference == pytest.approx(e["H"], **AP)
    assert r.micro_reference_known_at == TS(435)
    assert r.first_break_time == TS(449)                # m=448 kapanışı
    assert r.signal_time == TS(449)
    assert r.displacement_ATR5_prev == pytest.approx(0.60, abs=1e-6)
    assert r.sweep_extreme == pytest.approx(e["extreme"], **AP)
    assert r.E_plan == pytest.approx(e["E3"], **AP)
    assert r.S_raw == pytest.approx(e["S_raw"], **AP)
    assert r.S == pytest.approx(e["S"], **AP)
    assert r.T_raw == pytest.approx(e["T3"], **AP)
    assert r.T == pytest.approx(e["T3"], **AP)


# ═════════════════════════ §9 mikro pivot referansı ═══════════════════════════════════════
@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_no_micro_pivot(model, side):
    """Gün 1'de pivot yok; en son pivot gün 0 ~01:00'de onaylı (>24 saat) → NO_MICRO_PIVOT."""
    over = dict(SWEEP)
    over.update({447: M_PREV, 448: M_STRONG, 449: M_PLUS1, 450: RETEST})
    r, ev, _, _ = run(model, over, side)
    assert ev.micro_ref is None
    assert_terminal(r, "NO_MICRO_PIVOT", TS(447))
    assert r.signal_time is None and r.E_plan is None


@pytest.mark.parametrize("side", SIDES)
def test_micro_pivot_confirmed_exactly_24h_before_t_is_accepted(side):
    """Pivot k=153 (gün0 12:45) → onay k=156 açılışı = gün0 13:00 = t başı − 24 saat → kabul."""
    over = dict(SWEEP)
    over[153] = (102.0, 103.0, 102.0, 102.0)
    r, ev, _, _ = run("K3", over, side)
    assert ev.micro_ref is not None
    assert ev.micro_ref[0] == pytest.approx(EXP[side]["H_old"], **AP)
    assert ev.micro_ref[1] == TS(156)
    assert r.micro_reference == pytest.approx(EXP[side]["H_old"], **AP)
    # pencerede close > 103 yok → K3_TIMEOUT (NO_MICRO_PIVOT DEĞİL)
    assert_terminal(r, "K3_TIMEOUT", TS(453))


@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_micro_pivot_confirmed_24h_plus_5m_before_t_is_rejected(model, side):
    """Pivot k=152 → onay gün0 12:55 = t başı − 24s05dk → yaş sınırı aşılır → NO_MICRO_PIVOT."""
    over = dict(SWEEP)
    over[152] = (102.0, 103.0, 102.0, 102.0)
    r, ev, _, _ = run(model, over, side)
    assert ev.micro_ref is None
    assert_terminal(r, "NO_MICRO_PIVOT", TS(447))


@pytest.mark.parametrize("side", SIDES)
def test_micro_pivot_confirmed_exactly_at_t_start_is_known(side):
    """Eski pivot k=432 (101,50); yeni pivot k=441 (101,00) onayı k=444 açılışı = t başı → bilinir.
    m=448 close 101,30 yalnız H=101,00 ile kırılımdır (101,50 ile değil)."""
    over = dict(SWEEP)
    over.update({432: (100.5, 101.5, 100.5, 100.5), 441: (100.5, 101.0, 100.5, 100.5),
                 447: M_PREV, 448: M_STRONG})
    r, ev, _, _ = run("K3", over, side)
    assert ev.micro_ref[0] == pytest.approx(EXP[side]["H"], **AP)
    assert ev.micro_ref[1] == TS(444)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == TS(449)
    assert r.E_plan == pytest.approx(EXP[side]["E3"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_micro_pivot_confirmed_after_t_start_is_not_used(side):
    """Yeni pivot k=442 (101,00) onayı k=445 açılışı (t içinde) → t başında bilinmez; referans
    eski pivot 101,50 olarak donar. m=448 close 101,30 <= 101,50 → kırılım yok → K3_TIMEOUT."""
    over = dict(SWEEP)
    over.update({432: (100.5, 101.5, 100.5, 100.5), 442: (100.5, 101.0, 100.5, 100.5),
                 447: M_PREV, 448: M_STRONG})
    r, ev, _, _ = run("K3", over, side)
    assert ev.micro_ref[0] == pytest.approx(EXP[side]["H_hi"], **AP)
    assert ev.micro_ref[1] == TS(435)
    assert r.micro_reference == pytest.approx(EXP[side]["H_hi"], **AP)
    assert_terminal(r, "K3_TIMEOUT", TS(453))


@pytest.mark.parametrize("side", SIDES)
def test_micro_reference_frozen_later_more_favorable_pivot_ignored(side):
    """t içinde k=446 high=100,85 yeni pivot (onay k=449 açılışı). Bekleme barı k=449 close=100,95
    (> 100,85 ama <= 101,00). Referans t başında 101,00 olarak dondu → kırılım değil → K3_TIMEOUT
    (dinamik referans kullanılsaydı gövde 0,35 → WEAK_FIRST_BREAK olurdu)."""
    over = base()
    over.update({446: (100.3, 100.85, 100.3, 100.6), 447: NK3, 448: NK3,
                 449: (100.6, 100.97, 100.55, 100.95), 450: NK3, 451: NK3, 452: NK3})
    r, ev, _, _ = run("K3", over, side)
    assert ev.micro_ref[0] == pytest.approx(EXP[side]["H"], **AP)
    assert r.micro_reference == pytest.approx(EXP[side]["H"], **AP)
    assert_terminal(r, "K3_TIMEOUT", TS(453))
    assert r.first_break_time is None


# ═════════════════════════ No.16 STRUCTURE_ALREADY_BROKEN ═════════════════════════════════
@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_no16_structure_already_broken(model, side):
    """H=101, K1 close=101,10 > H → STRUCTURE_ALREADY_BROKEN; sonraki güçlü kırılım giriş sayılmaz."""
    over = k4_base()
    over[446] = (100.3, 101.15, 100.3, 101.1)
    r, ev, _, _ = run(model, over, side)
    assert ev.micro_ref[0] == pytest.approx(EXP[side]["H"], **AP)
    assert_terminal(r, "STRUCTURE_ALREADY_BROKEN", TS(447))
    assert r.signal_time is None


@pytest.mark.parametrize("side", SIDES)
def test_k1_close_equal_to_H_is_not_already_broken(side):
    """close[t] <= H şartı: K1 close=101,00 = H → kırılmamış sayılır; m=448 ile K3 sinyali."""
    over = k4_base()
    over[446] = (100.3, 101.05, 100.3, 101.0)
    r, _, _, _ = run("K3", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == TS(449)
    assert r.E_plan == pytest.approx(EXP[side]["E3"], **AP)
    assert r.T == pytest.approx(EXP[side]["T3"], **AP)


@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_k2_type_event_not_carried_to_k3_k4(model, side):
    """İhlal barı reclaim yapmazsa (close[t]=100,00=L) K3/K4 başlamaz: K1_RECLAIM_MISSING."""
    over = base()
    over.update({446: (100.3, 100.7, 100.0, 100.0), 447: (100.0, 100.7, 100.0, 100.6),
                 448: M_STRONG, 449: M_PLUS1, 450: RETEST})
    r, _, _, _ = run(model, over, side)
    assert_terminal(r, "K1_RECLAIM_MISSING", TS(447))


# ═════════════════════════ No.17 WEAK_FIRST_BREAK ═════════════════════════════════════════
@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_no17_weak_first_break_not_rescued(model, side):
    """İlk close>H barı open=100,70 close=101,10 → gövde 0,40 < 0,50 → WEAK_FIRST_BREAK.
    Sonraki k=449 güçlü (gövde 0,60) ve K4 için FVG üretecek olsa da kurtarmaz."""
    over = base()
    over.update({447: M_PREV, 448: (100.7, 101.15, 100.65, 101.1),
                 449: (101.2, 101.9, 101.15, 101.8), 450: RETEST})
    r, _, _, _ = run(model, over, side)
    assert_terminal(r, "WEAK_FIRST_BREAK", TS(449))
    assert r.first_break_time == TS(449)
    assert r.displacement_ATR5_prev == pytest.approx(0.40, abs=1e-6)
    assert r.signal_time is None


@pytest.mark.parametrize("side", SIDES)
def test_first_break_wrong_direction_body_is_weak(side):
    """Long ilk kırılım close>H ama close<open (gövde 0,70 yeterli büyük) → yön şartı yok → WEAK."""
    over = base()
    over.update({447: M_PREV, 448: (101.9, 102.0, 101.1, 101.2), 449: M_STRONG})
    r, _, _, _ = run("K3", over, side)
    assert_terminal(r, "WEAK_FIRST_BREAK", TS(449))


@pytest.mark.parametrize("side", SIDES)
def test_body_exactly_half_atr_is_enough(side):
    """Gövde 101,20−100,70 = 0,50 = 0,50·ATR5 → >= sağlanır; E=101,20, T=101,20+2·1,90=105,00."""
    over = base()
    over.update({447: M_PREV, 448: (100.7, 101.25, 100.65, 101.2)})
    r, _, _, _ = run("K3", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == TS(449)
    assert r.E_plan == pytest.approx(EXP[side]["E_half"], **AP)
    assert r.S == pytest.approx(EXP[side]["S"], **AP)
    assert r.T == pytest.approx(EXP[side]["T_half"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_displacement_uses_atr5_of_bar_m_minus_1(side):
    """ATR5[m]=5 (m'nin kendi ATR'si) dikkate alınmaz: ATR5[m−1]=1 → gövde 0,60 yeterli → SIGNAL."""
    r, _, _, _ = run("K3", k4_base(), side, atr5_at={448: 5.0})
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.displacement_ATR5_prev == pytest.approx(0.60, abs=1e-6)


@pytest.mark.parametrize("side", SIDES)
def test_displacement_atr5_m_minus_1_too_large_is_weak(side):
    """ATR5[m−1]=2 → eşik 1,00; gövde 0,60 yetmez → WEAK_FIRST_BREAK (ATR5[m]=1 olsa da)."""
    r, _, _, _ = run("K3", k4_base(), side, atr5_at={447: 2.0})
    assert_terminal(r, "WEAK_FIRST_BREAK", TS(449))
    assert r.displacement_ATR5_prev == pytest.approx(0.30, abs=1e-6)


@pytest.mark.parametrize("side", SIDES)
def test_close_equal_to_H_is_not_a_break(side):
    """k=447 close=101,00 = H (gövde 0,40) kırılım değildir; ilk kırılım k=448 (güçlü) → SIGNAL.
    (447 kırılım sayılsaydı WEAK_FIRST_BREAK olurdu.)"""
    over = base()
    over.update({447: (100.6, 101.05, 100.55, 101.0), 448: M_STRONG})
    r, _, _, _ = run("K3", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.first_break_time == TS(449)
    assert r.E_plan == pytest.approx(EXP[side]["E3"], **AP)


# ═════════════════ ek zorunlu: yalnız reclaim SONRASI barlar pencereye girer ══════════════
@pytest.mark.parametrize("side", SIDES)
def test_5m_close_above_H_inside_sweep_bar_does_not_count(side):
    """t içindeki k=445 5m close=101,20 > H (gövde 0,30, zayıf); 15m close[t]=100,60 <= H.
    Pencere 447'den başlar; ilk kırılım 448 (güçlü) → SIGNAL (445 sayılsaydı WEAK olurdu)."""
    over = base()
    over.update({444: (100.5, 100.95, 99.5, 100.9), 445: (100.9, 101.25, 100.85, 101.2),
                 446: (101.2, 101.2, 100.55, 100.6), 447: NK3, 448: M_STRONG})
    r, ev, _, _ = run("K3", over, side)
    assert ev.micro_ref[0] == pytest.approx(EXP[side]["H"], **AP)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.first_break_time == TS(449)
    assert r.signal_time == TS(449)
    assert r.S == pytest.approx(EXP[side]["S"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_k3_break_on_sixth_window_bar_is_accepted(side):
    """Pencere = 447..452. Kırılım 452'de (6.) → kabul; signal_time = 452 kapanışı."""
    over = base()
    over.update({447: NK3, 448: NK3, 449: NK3, 450: NK3, 451: NK3, 452: M_STRONG})
    r, _, _, _ = run("K3", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == TS(453)
    assert r.E_plan == pytest.approx(EXP[side]["E3"], **AP)
    assert r.T == pytest.approx(EXP[side]["T3"], **AP)


@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_k3_break_on_seventh_bar_times_out(model, side):
    """Kırılım 453'te (7.) → K3_TIMEOUT; zaman aşımı 6. barın (452) kapanışında bilinir."""
    over = base()
    over.update({447: NK3, 448: NK3, 449: NK3, 450: NK3, 451: NK3, 452: NK3, 453: M_STRONG})
    r, _, _, _ = run(model, over, side)
    assert_terminal(r, "K3_TIMEOUT", TS(453))


# ═════════════════ stop K1 reclaim'de sabit; bekleyişte stop teması ═══════════════════════
@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_k3_stop_touch_on_break_bar_cancels(model, side):
    """Kırılım barı (gövde 0,60) low=99,30=S'ye eşit temas → STOP_BEFORE_ENTRY (teyit kurtarmaz)."""
    over = k4_base()
    over[448] = (100.7, 101.4, 99.3, 101.3)
    r, _, _, _ = run(model, over, side)
    assert_terminal(r, "STOP_BEFORE_ENTRY", TS(449))
    assert r.signal_time is None


@pytest.mark.parametrize("model", ["K3", "K4"])
@pytest.mark.parametrize("side", SIDES)
def test_k3_stop_touch_on_earlier_wait_bar_cancels(model, side):
    over = k4_base()
    over[447] = (100.6, 100.9, 99.3, 100.6)
    r, _, _, _ = run(model, over, side)
    assert_terminal(r, "STOP_BEFORE_ENTRY", TS(448))


@pytest.mark.parametrize("side", SIDES)
def test_stop_fixed_at_k1_reclaim_not_updated_by_new_extreme(side):
    """Bekleme barı low=99,31 (S'nin 1 tick üstü, yeni dip) → iptal yok; stop yeni dibe göre
    (99,31−0,20=99,11) güncellenmez: S=99,30. K3: T=105,30; K4: T=105,00."""
    over = k4_base()
    over[447] = (100.6, 100.9, 99.31, 100.6)
    e = EXP[side]
    r3, _, _, _ = run("K3", over, side)
    assert r3.terminal_status == "SIGNAL", r3.terminal_status
    assert r3.sweep_extreme == pytest.approx(e["extreme"], **AP)
    assert r3.S_raw == pytest.approx(e["S_raw"], **AP)
    assert r3.S == pytest.approx(e["S"], **AP)
    assert r3.T == pytest.approx(e["T3"], **AP)
    r4, _, _, _ = run("K4", over, side)
    assert r4.terminal_status == "SIGNAL", r4.terminal_status
    assert r4.sweep_extreme == pytest.approx(e["extreme"], **AP)
    assert r4.S == pytest.approx(e["S"], **AP)
    assert r4.E_plan == pytest.approx(e["E4"], **AP)
    assert r4.T == pytest.approx(e["T4"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_k3_k4_stop_tick_rounding_away_from_entry(side):
    """A=2,05 → tampon 0,205. Long S_raw=99,50−0,205=99,295 → aşağı tick S=99,29;
    short S_raw=100,50+0,205=100,705 → yukarı tick S=100,71.
    K3: long T=101,30+2·(101,30−99,29)=105,32; short T=98,70−2·(100,71−98,70)=94,68.
    K4: long T=101,20+2·(101,20−99,29)=105,02; short T=98,80−2·(100,71−98,80)=94,98."""
    exp = {"LONG": dict(S_raw=99.295, S=99.29, T3=105.32, T4=105.02),
           "SHORT": dict(S_raw=100.705, S=100.71, T3=94.68, T4=94.98)}[side]
    r3, ev, _, _ = run("K3", k4_base(), side, A=2.05)
    assert ev.A == pytest.approx(2.05, **AP)
    assert r3.terminal_status == "SIGNAL", r3.terminal_status
    assert r3.S_raw == pytest.approx(exp["S_raw"], abs=1e-9)
    assert r3.S == pytest.approx(exp["S"], **AP)
    assert r3.E_plan == pytest.approx(EXP[side]["E3"], **AP)
    assert r3.T == pytest.approx(exp["T3"], **AP)
    r4, _, _, _ = run("K4", k4_base(), side, A=2.05)
    assert r4.terminal_status == "SIGNAL", r4.terminal_status
    assert r4.S == pytest.approx(exp["S"], **AP)
    assert r4.E_plan == pytest.approx(EXP[side]["E4"], **AP)
    assert r4.T == pytest.approx(exp["T4"], **AP)


# ═════════════════════════ §10 K4 — No.19, No.20 ══════════════════════════════════════════
@pytest.mark.parametrize("side", SIDES)
def test_no19_no20_k4_signal_values(side):
    e = EXP[side]
    r, _, _, _ = run("K4", k4_base(), side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.first_break_time == TS(449)                 # m=448
    assert r.fvg_known_at == TS(450)                     # m+1=449 kapanışı
    assert r.G_lo == pytest.approx(e["G_lo"], **AP)
    assert r.G_hi == pytest.approx(e["G_hi"], **AP)
    assert r.G_mid == pytest.approx(e["G_mid"], **AP)
    assert r.retest_time == TS(451)                      # r=450 kapanışı
    assert r.signal_time == TS(451)
    assert r.reclaim_time == TS(447)
    assert r.sweep_extreme == pytest.approx(e["extreme"], **AP)
    assert r.E_plan == pytest.approx(e["E4"], **AP)      # close[r], G_mid DEĞİL
    assert abs(r.E_plan - e["G_mid"]) > 0.1
    assert r.S_raw == pytest.approx(e["S_raw"], **AP)
    assert r.S == pytest.approx(e["S"], **AP)            # K1 reclaim'de sabitlenmiş stop
    assert r.T_raw == pytest.approx(e["T4"], **AP)       # nihai E_plan'dan
    assert r.T == pytest.approx(e["T4"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_no20_k4_fill_at_next_open_not_gmid(side):
    """K4 sinyali 13:30 (r=450 kapanışı); dolum 13:30 açılışından (k=451 open=101,25), G_mid=101
    veya E_plan=101,20'den değil. Kayma/ücret sıfır."""
    e = EXP[side]
    sd, dv, evs = build(k4_base(), side)
    r = SU.eval_K4(event_at(evs, side), dv)
    assert r.terminal_status == "SIGNAL"
    zero = C.CostProfile(name="ZERO", entry_fee_rate=0.0, exit_fee_rate=0.0, entry_slip_bp=0.0,
                         exit_slip_bp=0.0, source="test")
    uni = dict(symbols={SYM: sd}, g0=G0)
    res = RA.simulate("L1_K4_F0", "TEST", (G0 + DAY_MS, G0 + 3 * DAY_MS), [r], uni, zero, 10_000.0,
                      record_equity=False)
    filled = [o for o in res.outcomes if o["terminal_status"] == "FILLED"]
    assert len(filled) == 1
    assert len(res.trades) == 1
    tr = res.trades[0]
    assert tr["fill_time"] == TS(451)
    assert tr["entry_open"] == pytest.approx(e["fill"], **AP)
    assert tr["E_fill"] == pytest.approx(e["fill"], **AP)
    assert tr["E_fill"] != pytest.approx(e["G_mid"], abs=1e-6)
    assert tr["E_plan"] == pytest.approx(e["E4"], **AP)
    assert tr["S"] == pytest.approx(e["S"], **AP)
    assert tr["T"] == pytest.approx(e["T4"], **AP)        # T dolumdan sonra yeniden 2R'ye taşınmaz


@pytest.mark.parametrize("side", SIDES)
def test_no_fvg_when_triplet_equal_bounds(side):
    """low[m+1]=100,90 = high[m−1] → sıkı eşitsizlik yok → NO_FVG (m+1 kapanışında)."""
    over = k4_base()
    over[449] = (101.3, 101.5, 100.9, 101.4)
    r, _, _, _ = run("K4", over, side)
    assert_terminal(r, "NO_FVG", TS(450))
    assert r.G_lo is None and r.signal_time is None


@pytest.mark.parametrize("side", SIDES)
def test_no_fvg_later_gap_not_selected(side):
    """m−1,m,m+1 boşluk yok (low[449]=100,85 < 100,90); m,m+1,m+2 boşluğu (low[450]=101,45 >
    high[448]=101,40) seçilmez → NO_FVG."""
    over = k4_base()
    over.update({449: (101.3, 101.5, 100.85, 101.4), 450: (101.45, 101.8, 101.45, 101.7),
                 451: RETEST})
    r, _, _, _ = run("K4", over, side)
    assert_terminal(r, "NO_FVG", TS(450))


@pytest.mark.parametrize("side", SIDES)
def test_no21_fvg_invalidated(side):
    """Bekleme close=100,80 < G_lo=100,90 → FVG_INVALIDATED; sonraki teyit kurtarmaz."""
    over = k4_base()
    over.update({450: (101.4, 101.45, 100.75, 100.8), 451: (100.8, 101.3, 100.8, 101.2)})
    r, _, _, _ = run("K4", over, side)
    assert_terminal(r, "FVG_INVALIDATED", TS(451))
    assert r.G_lo == pytest.approx(EXP[side]["G_lo"], **AP)
    assert r.signal_time is None


@pytest.mark.parametrize("side", SIDES)
def test_close_equal_to_fvg_outer_bound_is_not_invalidation(side):
    """Bekleme close=100,90 = G_lo (low 100,85 <= G_mid) → iptal değil, giriş değil. Sonraki
    450+1 barı low 100,90 <= 101, close 101,20 > 101,10 → SIGNAL (r=451)."""
    over = k4_base()
    over.update({450: (101.4, 101.45, 100.85, 100.9), 451: (100.9, 101.3, 100.9, 101.2),
                 452: ENTRY_BAR})
    r, _, _, _ = run("K4", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.retest_time == TS(452)
    assert r.signal_time == TS(452)
    assert r.E_plan == pytest.approx(EXP[side]["E4"], **AP)
    assert r.T == pytest.approx(EXP[side]["T4"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_close_equal_to_G_hi_is_not_entry(side):
    """Retest low 100,95 <= G_mid ama close=101,10 = G_hi → teyit değil; sonraki RETEST teyit."""
    over = k4_base()
    over.update({450: (101.4, 101.45, 100.95, 101.1), 451: RETEST, 452: ENTRY_BAR})
    r, _, _, _ = run("K4", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == TS(452)
    assert r.E_plan == pytest.approx(EXP[side]["E4"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_retest_low_equal_to_G_mid_confirms(side):
    """low=101,00 = G_mid (<= sağlanır), close 101,25 > G_hi → teyit. E=101,25;
    T=101,25+2·(101,25−99,30)=105,15."""
    over = k4_base()
    over[450] = (101.4, 101.45, 101.0, 101.25)
    r, _, _, _ = run("K4", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.signal_time == TS(451)
    assert r.E_plan == pytest.approx(EXP[side]["E4b"], **AP)
    assert r.S == pytest.approx(EXP[side]["S"], **AP)
    assert r.T == pytest.approx(EXP[side]["T4b"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_k4_cancel_priority_stop_over_fvg_invalidation(side):
    """Aynı bar low=99,30=S ve close=100,80 < G_lo → öncelik 1: STOP_BEFORE_ENTRY."""
    over = k4_base()
    over[450] = (101.4, 101.45, 99.3, 100.8)
    r, _, _, _ = run("K4", over, side)
    assert_terminal(r, "STOP_BEFORE_ENTRY", TS(451))


@pytest.mark.parametrize("side", SIDES)
def test_no22_stop_equal_touch_with_strong_confirmation(side):
    """Beklerken S=99,30, low=99,30; aynı bar low<=G_mid ve close 101,20 > G_hi (güçlü teyit)
    → STOP_BEFORE_ENTRY; eşit temas da iptal."""
    over = k4_base()
    over[450] = (101.4, 101.45, 99.3, 101.2)
    r, _, _, _ = run("K4", over, side)
    assert_terminal(r, "STOP_BEFORE_ENTRY", TS(451))
    assert r.signal_time is None


@pytest.mark.parametrize("side", SIDES)
def test_k4_retest_on_sixth_bar_after_fvg_is_accepted(side):
    """K4 penceresi m+1 (449) kapanışından sonra: 450..455. Teyit 455'te (6.) → kabul."""
    over = k4_base()
    over.update({450: NK4, 451: NK4, 452: NK4, 453: NK4, 454: NK4, 455: RETEST})
    r, _, _, _ = run("K4", over, side)
    assert r.terminal_status == "SIGNAL", r.terminal_status
    assert r.fvg_known_at == TS(450)
    assert r.signal_time == TS(456)
    assert r.E_plan == pytest.approx(EXP[side]["E4"], **AP)


@pytest.mark.parametrize("side", SIDES)
def test_k4_retest_on_seventh_bar_times_out(side):
    over = k4_base()
    over.update({450: NK4, 451: NK4, 452: NK4, 453: NK4, 454: NK4, 455: NK4, 456: RETEST})
    r, _, _, _ = run("K4", over, side)
    assert_terminal(r, "K4_TIMEOUT", TS(456))
    assert r.G_mid == pytest.approx(EXP[side]["G_mid"], **AP)


# ═════════════════ §5/§10 seviye ömrü: bekleyişte LEVEL_EXPIRED ═══════════════════════════
# Sweep t = gün1 23:30 (k=570..572); pencere 573 (23:45), 574 (23:50), 575 (23:55 → 00:00 kapanış
# = seviye expires_at). Mikro pivot k=558 (22:30) high=101.
KX = 570


def late():
    d = {558: (100.5, 101.0, 100.5, 100.5)}
    for i, b in enumerate((SWEEP[444], SWEEP[445], SWEEP[446])):
        d[KX + i] = b
    return d


@pytest.mark.parametrize("side", SIDES)
def test_k3_break_at_level_expiry_is_rejected(side):
    over = late()
    over.update({573: M_PREV, 574: NK3, 575: M_STRONG})
    r, _ = run_k0("K3", over, side, KX)
    assert_terminal(r, "LEVEL_EXPIRED", EXPIRY)
    assert r.signal_time is None


@pytest.mark.parametrize("side", SIDES)
def test_k3_break_one_bar_before_expiry_accepted_k4_expires(side):
    over = late()
    over.update({573: M_PREV, 574: M_STRONG, 575: M_PLUS1})
    r3, ev = run_k0("K3", over, side, KX)
    assert ev.level_expires_at == EXPIRY
    assert r3.terminal_status == "SIGNAL", r3.terminal_status
    assert r3.signal_time == TS(575)
    assert r3.E_plan == pytest.approx(EXP[side]["E3"], **AP)
    r4, _ = run_k0("K4", over, side, KX)
    assert_terminal(r4, "LEVEL_EXPIRED", EXPIRY)            # m+1 kapanışı = expires_at
