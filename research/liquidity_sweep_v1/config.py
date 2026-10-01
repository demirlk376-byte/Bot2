"""
LIQUIDITY_SWEEP_V1 — dondurulmuş deney sabitleri (şartname SWEEP_V1_2026-10-01, Ek B).

Bu dosyadaki sayılar deneyin ÖNCEDEN belirlenmiş tercihleridir; sonuç görüldükten sonra
değiştirilmez. Değişiklik yeni deney sürümü (SPEC_VERSION) demektir.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

SPEC_VERSION = "SWEEP_V1_2026-10-01"
EVENT_ORDER_VERSION = "EO1-sartname-15"

# ── zaman ──────────────────────────────────────────────────────────────────────
MS = 1
SEC = 1000
MIN = 60 * SEC
M5 = 5 * MIN
M15 = 15 * MIN
H1 = 60 * MIN
DAY = 24 * H1
GRID_PER_15M = 3
GRID_PER_1H = 12
GRID_PER_DAY = 288
SESSION_END_MS = 8 * H1             # L2 penceresi [00:00, 08:00)
SESSION_BARS = 96

# ── evren (güncel ikiz CANLI_ENV SYMBOLS sırası; PnL görmeden) ────────────────
UNIVERSE = ["SOL", "ETH", "ADA", "NEAR", "BCH", "XRP", "DOGE", "TRX", "XLM", "LTC", "ICP", "BNB"]

# ── strateji parametreleri (Ek B) ──────────────────────────────────────────────
PIVOT_LEFT = 2
PIVOT_RIGHT = 2
LEVEL_MAX_AGE_MS = 48 * H1                # L3/L4 onaydan sonra
EQUAL_PIVOT_MAX_GAP_MS = 48 * H1          # L4 oluşumlar arası
EQUAL_PIVOT_TOL_ATR = 0.10                # L4: |fark| <= 0.10 * ATR1h14
MICRO_PIVOT_MAX_AGE_MS = 24 * H1          # K3/K4 mikro pivot
PENETRATION_ATR = 0.10                    # ihlal derinliği
STOP_BUFFER_ATR = 0.10
K2_WINDOW_15M = 3
K3_WINDOW_5M = 6
DISPLACEMENT_BODY_ATR = 0.50
K4_WINDOW_5M = 6
TARGET_R = 2.0
MAX_HOLD_MS = 12 * H1
ATR_PERIOD = 14
EMA_PERIOD = 200
EMA_SLOPE_BARS = 3
WARMUP_1H = 1000
WARMUP_LOWER_TF = 100

# ── dönem bölmesi ─────────────────────────────────────────────────────────────
SPLIT_1 = 0.60
SPLIT_2 = 0.80
PARTITION_TAIL_MS = 12 * H1

# ── risk ──────────────────────────────────────────────────────────────────────
C0_FALLBACK = 10_000.0
PER_TRADE_RISK_FRAC = 0.0025
PORTFOLIO_RISK_CAP_FRAC = 0.01

# ── istatistik ────────────────────────────────────────────────────────────────
BOOT_REPS = 10_000
BOOT_BLOCK_WEEKS = 4
BOOT_SEED = 20261001
BOOT_INVALID_MAX = 0.05
SAMPLE_FLOORS = {          # kapanmış işlem, işlemli tam hafta, tam takvim haftası
    "DISCOVERY": (100, 12, 26),
    "VALIDATION": (50, 8, 13),
    "FINAL": (30, 6, 13),
}
CANDIDATE_LIMITS = {"DISCOVERY": 3, "VALIDATION": 1}

# ── varyantlar ────────────────────────────────────────────────────────────────
LEVEL_FAMILIES = ("L1", "L2", "L3", "L4")
ENTRY_MODELS = ("K1", "K2", "K3", "K4")
TREND_OPTS = ("F0", "F1")
VARIANT_IDS = [f"{l}_{k}_{f}" for l in LEVEL_FAMILIES for k in ENTRY_MODELS for f in TREND_OPTS]
assert len(VARIANT_IDS) == 32

# ── sabit neden kodları (şartname §20; "en az" listesi + açıkça eklenenler) ───
REASONS = {
    "DATA_INVALID", "INVALID_INDICATOR", "LEVEL_EXPIRED", "LEVEL_CONSUMED", "DOUBLE_SIDED_SWEEP",
    "BLOCKED_ACTIVE_SETUP", "K1_RECLAIM_MISSING", "K2_NOT_APPLICABLE", "K2_TIMEOUT", "NO_MICRO_PIVOT",
    "STRUCTURE_ALREADY_BROKEN", "WEAK_FIRST_BREAK", "K3_TIMEOUT", "NO_FVG", "FVG_INVALIDATED",
    "K4_TIMEOUT", "STOP_BEFORE_ENTRY", "TREND_REJECTED", "OPEN_OUTSIDE_PLAN", "POSITION_BLOCKED",
    "OPPOSITE_SIGNALS_SAME_TIME", "RISK_CAP_BLOCKED", "MARGIN_BLOCKED", "MIN_ORDER_BLOCKED",
    "PARTITION_TAIL_BLOCKED", "FILLED", "CLOSED",
    # ekler (şartnamede ad verilmemiş ama ayrı tutulması gereken durumlar)
    "SIGNAL",                 # setup makinesinin nihai sinyali (portföy kararı öncesi)
    "INVALID_GEOMETRY",       # tick yuvarlaması sonrası S<E<T bozuldu
    "PARTITION_RESET",        # bölüm başında bekleyen kurulum iptali
    "OUTSIDE_PARTITION",      # sinyal hiçbir değerlendirme bölümünde değil (ısınma vb.)
    "DAILY_LOSS_BLOCKED",     # canlı DAILY_MAX_LOSS_PCT kapısı
    "MAX_POSITIONS_BLOCKED",  # canlı MAX_POSITIONS kapısı
    "GEOMETRY_PROTECT_CLOSE",  # dolum sonrası plan geometrisi bozuldu → koruma kapanışı
    "PENDING", "CENSORED",
}
EXIT_REASONS = ("STOP", "TARGET", "TIME_EXIT", "AMBIGUOUS_SL_TP", "GEOMETRY_PROTECT_CLOSE")


@dataclass(frozen=True)
class CostProfile:
    name: str
    entry_fee_rate: float
    exit_fee_rate: float
    entry_slip_bp: float
    exit_slip_bp: float
    source: str

    def stress(self) -> "CostProfile":
        return CostProfile(name="STRESS", entry_fee_rate=self.entry_fee_rate,
                           exit_fee_rate=self.exit_fee_rate, entry_slip_bp=2 * self.entry_slip_bp,
                           exit_slip_bp=2 * self.exit_slip_bp, source=self.source + " ×2 kayma")

    def as_dict(self):
        return asdict(self)


# Güncel düzeltilmiş ikizin belgelenmiş PİYASA emri profili (ikiz/kos.py + exchange.PaperExchange,
# 936 referansının maliyet damgası): taker 1bp/taraf (FEE_RATE=0.0001), giriş kayması 15.85bp,
# piyasa çıkış kayması 0.24bp. Maker / squeeze limit kısmı AKTARILMADI. TP bu deneyde piyasa
# çıkışıdır → 0.24bp TP'ye de uygulanır (PaperExchange'in tp_hit muafiyeti KULLANILMAZ).
TWIN_MARKET_PROFILE = CostProfile(
    name="NORMAL", entry_fee_rate=0.0001, exit_fee_rate=0.0001, entry_slip_bp=15.85,
    exit_slip_bp=0.24,
    source="ikiz/kos.py 936 referansı: PAPER_SLIP_GIRIS_BP=15.85, PAPER_SLIP_CIKIS_BP=0.24, "
           "exchange.PaperExchange.FEE_RATE=0.0001 (taker); ölçüm kaynağı: canlı Donchian/çıkış denetimleri")

# Şartnamenin profil bulunamazsa kullanılacak yedeği (yalnız kayıt; profil bulunduğu için kullanılmıyor)
SPEC_FALLBACK_PROFILE = CostProfile(
    name="FALLBACK", entry_fee_rate=0.0006, exit_fee_rate=0.0006, entry_slip_bp=15.85,
    exit_slip_bp=5.0, source="şartname §13 yedek tablo")

# Canlı/ikiz sermaye-güvenlik kapıları (CANLI_ENV + config.py); araştırma motorunda uygulanır
LIVE_GATES = {
    "LEVERAGE": 10,                  # CANLI_ENV LEVERAGE
    "MAX_POSITIONS": 7,              # CANLI_ENV MAX_POSITIONS
    "POSITION_CAP_FRACTION": 2.5,    # CANLI_ENV; risk.build_trade_setup_from_levels: notional <= bakiye×2.5
    "DAILY_MAX_LOSS_PCT": 0.35,      # CANLI_ENV; execution: günlük başlangıca göre özsermaye kaybı
    "ONE_PER_SYMBOL": True,          # ikiz _ortam(); execution one-per-symbol
    "MARGIN_PREFLIGHT_FRAC": 0.95,   # execution: margin_required > free_balance*0.95 → ret
}
# Uygulanmayan canlı kapılar ve gerekçe (manifestte listelenir)
LIVE_GATES_NOT_APPLIED = {
    "CONSECUTIVE_LOSS_LIMIT/COOLDOWN_MINUTES (2/240)":
        "kol:sembol bazlı kayıp serisi soğuması — kayba bağlı sinyal filtresi; şartname §2 eski "
        "stratejiye özgü filtreleri miras almayı yasaklıyor",
    "max_correlated_direction=2 (grup BTC/ETH/SOL)":
        "evrende gruptan yalnız ETH+SOL var; aynı yönde en fazla 2 → kapı hiç bağlamaz",
    "regime/volume/MTF/score filtreleri": "şartname §2: F0/F1 dışında giriş filtresi yok",
}
