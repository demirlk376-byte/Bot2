"""
Muhasebe (şartname §12.3, §13, §16). Doğrusal USDT sözleşme; Q_base = temel varlık miktarı.

  E_fill = O * (1 + d*entry_slip)   → tick'e ALEYHE (alış yukarı, satış aşağı)
  X_fill = X_ref * (1 - d*exit_slip) → tick'e ALEYHE (long kapanış=satış aşağı, short kapanış=alış yukarı)
  gross  = d*(X_fill - E_fill)*Q_base
  fees   = |E_fill*Q|*fee_in + |X_fill*Q|*fee_out      (giriş ücreti DOLUM ANINDA cüzdandan düşülür;
                                                      tahakkuk sütunu bu yüzden hep 0'dır)
  funding_cf(τ) = -d * Q_base * mark(τ) * rate(τ)    (pozitif oranda long öder)
  net    = gross - fees + Σ funding
  R0     = |E_fill - S| * Q_base ;  net_R = net / R0
  wallet = C0 + realized_gross - fees + funding ; equity = wallet + unrealized ;
  free_collateral = wallet - reserved_margin       (marjin zarar DEĞİLDİR)
Kayma dolum fiyatının içindedir; "kayma maliyeti" sütunu teşhis içindir, PnL'den TEKRAR düşülmez.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .setups import floor_tick, ceil_tick


def entry_fill(O, d, slip_bp, tick):
    raw = O * (1 + d * slip_bp / 10_000.0)
    return ceil_tick(raw, tick) if d > 0 else floor_tick(raw, tick)


def exit_fill(ref, d, slip_bp, tick):
    raw = ref * (1 - d * slip_bp / 10_000.0)
    return floor_tick(raw, tick) if d > 0 else ceil_tick(raw, tick)


def floor_step(x, step):
    """Miktarı adıma AŞAĞI yuvarla (tam adım sayısı; kayan nokta payı adım*1e-9)."""
    n = math.floor(x / step + 1e-9)
    return max(0, n) * step


def funding_cashflow(d, q_base, mark, rate):
    return -d * q_base * mark * rate


@dataclass
class Position:
    trade_id: str
    symbol: str
    d: int
    q_contracts: float
    q_base: float
    contract_size: float
    E_fill: float
    S: float
    T: float
    entry_k: int
    entry_time: int
    entry_open: float
    E_budget: float
    margin: float
    entry_fee: float
    R0: float
    rec: object                       # SetupRecord
    funding: float = 0.0
    data_gap: bool = False
    funding_events: int = 0

    def unrealized(self, mark):
        return self.d * (mark - self.E_fill) * self.q_base

    def loss_to_stop(self, mark):
        return max(0.0, self.d * (mark - self.S)) * self.q_base


@dataclass
class Ledger:
    C0: float
    wallet: float = 0.0
    reserved_margin: float = 0.0
    realized_gross: float = 0.0
    fees: float = 0.0
    funding: float = 0.0
    entry_fees: float = 0.0
    exit_fees: float = 0.0
    slip_cost_diag: float = 0.0       # teşhis: |dolum - referans| × Q (PnL'den ayrıca DÜŞÜLMEZ)

    def __post_init__(self):
        self.wallet = self.C0

    def open(self, notional_margin, fee):
        self.wallet -= fee
        self.fees += fee
        self.entry_fees += fee
        self.reserved_margin += notional_margin

    def close(self, gross, fee, margin):
        self.wallet += gross - fee
        self.realized_gross += gross
        self.fees += fee
        self.exit_fees += fee
        self.reserved_margin -= margin

    def fund(self, cf):
        self.wallet += cf
        self.funding += cf

    def identity_gap(self):
        """Defter kimliği: wallet - (C0 + realized - fees + funding)."""
        return self.wallet - (self.C0 + self.realized_gross - self.fees + self.funding)

    @property
    def free_collateral(self):
        return self.wallet - self.reserved_margin


def economic_equity_from_paper(paper_free_balance, reserved_margin, unrealized, unposted_entry_fees):
    """Legacy PaperExchange uyarlaması: get_balance() SERBEST bakiye döndürür (marjin düşülmüş),
    giriş ücretini ise ancak KAPANIŞTA düşer. Ekonomik özsermaye = serbest + marjin + açık PnL
    − henüz motorca düşülmemiş giriş ücreti tahakkuku. (Marjin zarar değildir; ücret iki kez düşülmez.)"""
    return paper_free_balance + reserved_margin + unrealized - unposted_entry_fees
