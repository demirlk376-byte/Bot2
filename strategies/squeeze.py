"""
Volatility Squeeze strategy — BB tightens inside Keltner Channel, then explodes.

EDGE (research_squeeze.py, BTC 1h 2023-2026, honest TRAIN/TEST + year-by-year):
  MTF (1h squeeze + 4h trend filter): KC1.5, min_squeeze=5, SL=2.0×ATR, RR=2.5:
    PF 1.31, WR 43%, 240 trades, POSITIVE EVERY YEAR:
      2023 PF 1.31 | 2024 PF 1.46 | 2025 PF 1.15 | 2026 PF 1.34
    Max DD: 18%  |  26/36 months profitable  |  TR≈TE (1.30 vs 1.34 — no test inflation)

LOGIC:
  Squeeze detection: Bollinger Bands (20, 2.0) contract inside Keltner Channel
  (EMA20 ± 1.5×ATR). When BB upper < KC upper AND BB lower > KC lower, the market
  is coiling — low volatility accumulating energy. After >= 5 consecutive bars in
  squeeze, when the BB finally breaks OUT of the KC, momentum fires.

  Direction: close > KC_midline (EMA20) → long; < → short.
  MTF filter: 4h close vs 4h KC midline must agree with 1h direction.
    This is the key PF lift: 1h standalone PF 1.31 but max-DD 25%, train/test gap
    1.21/1.85; MTF version same PF with DD 18%, TR≈TE 1.30/1.34.

  SL = entry ± 2.0 × ATR.  TP = entry ± 2.5 × SL-distance.
  Position slot: {symbol}:squeeze (independent of BB/ORB/Asia/FVG).

WHY IT WORKS (hypothesis):
  Low-volatility consolidations (squeeze) represent equilibrium — supply and demand
  balanced. When one side wins (BB expands) the initial expansion tends to continue
  because stop hunts clear the other side's positions. The 4h agreement filter
  ensures we're not fighting a larger-timeframe trend reversal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from indicators import atr as atr_fn, ema as ema_fn

# ⚠ GIRIS MODU — kirilimin YONUNU VARSAYMAK yerine fiyatin DAVRANISINI beklemek.
# Bugunku kural (mod="orta"): cikis barinin kapanisi EMA20'nin ustundeyse long.
# Bu, yonu VARSAYMAKTIR: kapanis ortalamanin bir tik ustunde olsa da long der.
#   "orta"   : bugunku davranis (KC orta cizgisi)
#   "aralik" : cikis bari sikisma araliginin (coil high/low) DISINA kapanmali;
#              icerideyse ISLEM YOK -- piyasa henuz yon soylemedi
#   "takip"  : cikistan sonra en fazla `takip_bar` bar beklenir; aralik ILK
#              hangi tarafa kirilirsa o yone girilir, kirilmazsa islem yok
MODLAR = ("orta", "aralik", "takip")
DEFAULT_MOD = "orta"
DEFAULT_TAKIP_BAR = 3


@dataclass
class SqueezeSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 – 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0
    squeeze_bars: int = 0  # how many bars the market was in squeeze before firing


class SqueezeStrategy:
    """Pure volatility-squeeze signal. analyze() is called on each closed 1h candle
    with a recent OHLCV buffer. Computes 4h direction internally via resample."""

    def __init__(
        self,
        kc_period: int = 20,
        kc_mult: float = 1.5,
        bb_period: int = 20,
        bb_std: float = 2.0,
        min_squeeze_bars: int = 5,
        sl_atr: float = 2.0,
        rr: float = 2.5,
        mtf_filter: bool = True,
        vol_mult: float = 0.0,
        vol_lookback: int = 20,
        mod: str = DEFAULT_MOD,
        takip_bar: int = DEFAULT_TAKIP_BAR,
    ):
        # ⚠ HACIM KAPISI (varsayilan 0 = KAPALI, davranis aynen eski).
        # Bu kol hacme HIC bakmiyordu. Donchian'da olculdu: dusuk hacimli
        # kirilim sahte cikma egiliminde ve hacim esigi TEST MAR'i 1.47'den
        # 3.64'e cikardi. Squeeze de bir KIRILIM kolu (sikismadan cikis),
        # ayni mantik gecerli olmali -- ama SINANMADI, o yuzden kapali geliyor.
        self._vol_mult = float(vol_mult)
        self._vol_lookback = max(2, int(vol_lookback))
        self._kc_period = kc_period
        self._kc_mult = kc_mult
        self._bb_period = bb_period
        self._bb_std = bb_std
        self._min_sq = min_squeeze_bars
        self._sl_atr = sl_atr
        self._rr = rr
        self._mtf = mtf_filter
        self._mod = str(mod).strip().lower() or DEFAULT_MOD
        if self._mod not in MODLAR:
            # yazim hatasi SESSIZCE bugunku davranisa dusmemeli -- dusseydi
            # taramada "fark yok" diye YANLIS rapor verirdik.
            raise ValueError(f"bilinmeyen SQUEEZE_MOD={mod!r} -- gecerli: {list(MODLAR)}")
        self._takip = max(0, int(takip_bar))

    def _min_bars(self) -> int:
        ek = self._takip if self._mod == "takip" else 0
        return max(self._kc_period, self._bb_period) + self._min_sq + 5 + ek

    def analyze(self, df: pd.DataFrame, atr_val: float) -> SqueezeSignal:
        """df: recent 1h OHLCV (DatetimeIndex, columns open/high/low/close).
        atr_val: pre-computed 1h ATR for sizing (avoids recomputing twice)."""
        if len(df) < self._min_bars():
            return SqueezeSignal(0, 0.0, f"insufficient data ({len(df)} < {self._min_bars()})")
        if atr_val <= 0:
            return SqueezeSignal(0, 0.0, "ATR not available")

        close = df["close"]
        high  = df["high"]
        low   = df["low"]

        # Bollinger Bands
        bb_mid = close.rolling(self._bb_period).mean()
        bb_std = close.rolling(self._bb_period).std()
        bb_up  = bb_mid + self._bb_std * bb_std
        bb_lo  = bb_mid - self._bb_std * bb_std

        # Keltner Channel
        kc_mid = ema_fn(close, self._kc_period)
        at_kc  = atr_fn(high, low, close, self._kc_period)
        kc_up  = kc_mid + self._kc_mult * at_kc
        kc_lo  = kc_mid - self._kc_mult * at_kc

        # Squeeze: BB inside KC
        in_sq = (bb_up < kc_up) & (bb_lo > kc_lo)

        sq_vals = in_sq.values
        n = len(sq_vals)
        i_now = n - 1

        # ⚠ CIKIS BARI NEREDE ARANIR.
        #   orta/aralik -> cikis SU ANKI barda olmali (bugunku davranis)
        #   takip       -> cikis en fazla `takip_bar` bar once olabilir; bu
        #                  arada fiyatin aralikten cikmasini BEKLERIZ.
        # Her halde yalnizca <= su anki bar okunur -> gelecege bakis yok.
        azami = self._takip if self._mod == "takip" else 0
        i_cikis = None
        for k in range(0, azami + 1):
            i = i_now - k
            if i >= 1 and (not sq_vals[i]) and sq_vals[i - 1]:
                i_cikis = i
                break
        if i_cikis is None:
            return SqueezeSignal(
                0, 0.0,
                f"no release (in_sq={bool(sq_vals[i_now])}, "
                f"prev={bool(sq_vals[i_now - 1]) if n >= 2 else False})")

        # Count consecutive squeeze bars ending at the bar BEFORE the release
        count = 0
        j = i_cikis - 1
        while j >= 0 and sq_vals[j]:
            count += 1
            j -= 1

        # Threshold = min_sq, NOT min_sq+1. Both the research and this loop count
        # the same quantity — consecutive squeeze bars ending at the bar BEFORE
        # the release candle (research: sq_count.shift(1) on the release bar).
        # A 2026-06-19 audit "fix" added +1 believing live fired a bar early;
        # the 2026-07-14 audit re-derived both counters and settled it
        # EMPIRICALLY on 12mo of 1h BTC: research k>=5 fires 141 signals, the
        # +1 version fires 127 (every exactly-5-bar coil silently dropped, ~10%
        # of the validated signal class); k>=min_sq matches research 141/141.
        if count < self._min_sq:
            return SqueezeSignal(
                0, 0.0,
                f"squeeze too short ({count} < {self._min_sq} bars)"
            )

        if self._mod == "orta":
            # bugunku kural: yon VARSAYILIR -- kapanis KC orta cizgisinin ustunde mi
            direction_1h = 1 if float(close.iloc[-1]) > float(kc_mid.iloc[-1]) else -1
        else:
            # ⚠ FIKIR 3: yonu varsayma, fiyatin DAVRANISINI bekle. Sikisma
            # araliginin (coil high/low) hangi tarafina KAPANDIYSA o yon.
            # Iceride kapanmissa piyasa henuz bir sey soylememistir -> islem yok.
            if any(sq_vals[i_cikis + 1:i_now + 1]):
                return SqueezeSignal(0, 0.0, "sikismaya geri donuldu")
            h_np = high.to_numpy(dtype="float64")
            l_np = low.to_numpy(dtype="float64")
            c_np = close.to_numpy(dtype="float64")
            coil_h = float(np.max(h_np[i_cikis - count:i_cikis]))
            coil_l = float(np.min(l_np[i_cikis - count:i_cikis]))
            if not (coil_h > coil_l):
                return SqueezeSignal(0, 0.0, "coil araligi bozuk")
            # ILK kirilimda girilir: arada kirilmissa o firsat gecmistir
            for i in range(i_cikis, i_now):
                if c_np[i] > coil_h or c_np[i] < coil_l:
                    return SqueezeSignal(0, 0.0, "aralik daha once kirilmisti")
            c_now = float(c_np[i_now])
            if c_now > coil_h:
                direction_1h = 1
            elif c_now < coil_l:
                direction_1h = -1
            else:
                return SqueezeSignal(
                    0, 0.0,
                    f"sikisma araligi kirilmadi ({coil_l:.6g}..{coil_h:.6g})")

        # MTF filter: resample 1h to 4h, compare close vs KC midline on 4h
        if self._mtf:
            dir_4h = self._htf_direction(df)
            if dir_4h != 0 and dir_4h != direction_1h:
                return SqueezeSignal(
                    0, 0.0,
                    f"MTF filter: 1h={'+' if direction_1h==1 else '-'} "
                    f"4h={'+' if dir_4h==1 else '-'} (conflict)"
                )

        # ⚠ HACIM TEYIDI. Sikismadan cikis barinin hacmi, ONDAN ONCEKI
        # `vol_lookback` barin ortalamasinin `vol_mult` katindan buyuk olmali.
        # Kimse almazken olusan cikis, coğunlukla gurultudur.
        if self._vol_mult > 0:
            if "volume" not in df.columns:
                return SqueezeSignal(0, 0.0, "hacim verisi yok")
            v = df["volume"].to_numpy(dtype="float64")
            bas = -(self._vol_lookback + 1)
            if -bas > len(v):
                return SqueezeSignal(0, 0.0, "hacim gecmisi yetersiz")
            ort = float(np.mean(v[bas:-1]))
            if not np.isfinite(ort) or ort <= 0:
                return SqueezeSignal(0, 0.0, "hacim ortalamasi sifir")
            oran = float(v[-1]) / ort
            if oran < self._vol_mult:
                return SqueezeSignal(
                    0, 0.0,
                    f"hacim zayif ({oran:.2f}x < {self._vol_mult:.2f}x)")

        entry = float(close.iloc[-1])
        sl    = entry - direction_1h * self._sl_atr * atr_val
        tp    = entry + direction_1h * self._rr * self._sl_atr * atr_val
        side  = "long" if direction_1h == 1 else "short"

        return SqueezeSignal(
            direction=direction_1h,
            strength=min(1.0, 0.6 + 0.04 * count),
            reason=f"squeeze {side}: {count}bar coil → release",
            sl_price=sl,
            tp_price=tp,
            entry_price=entry,
            squeeze_bars=count,
        )

    def _htf_direction(self, df_1h: pd.DataFrame) -> int:
        """Compute 4h momentum direction by resampling the 1h buffer."""
        need = (self._kc_period + 2) * 4  # need enough 4h bars
        if len(df_1h) < need:
            return 0
        df4 = df_1h.resample("4h").agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last",
        }).dropna()
        if len(df4) < self._kc_period + 2:
            return 0
        kc_mid4 = ema_fn(df4["close"], self._kc_period)
        # Pick the correct 4h bar: if the last 1h candle is the final hour of a
        # 4h period (hours 3, 7, 11, 15, 19, 23 UTC), iloc[-1] is a fully closed
        # 4h bar — use it. Otherwise the last 4h bar is still forming, so fall
        # back to iloc[-2] (the previous complete bar). This halves the average
        # trend-filter lag from ~6h to ~2h vs always using iloc[-2].
        last_hour = df_1h.index[-1].hour
        four_h_closed = (last_hour % 4 == 3)
        bar_idx = -1 if four_h_closed else -2
        c4   = float(df4["close"].iloc[bar_idx])
        mid4 = float(kc_mid4.iloc[bar_idx])
        if pd.isna(mid4):
            return 0
        return 1 if c4 > mid4 else -1
