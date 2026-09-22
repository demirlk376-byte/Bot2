"""
Donchian Channel Swing Breakout (4h) — higher-timeframe trend-continuation.

EDGE (scratch_cand_donchian_4h_swing.py + scratch_donchian_close.py, BTC 4h
2023-01..2026-04, honest TRAIN/TEST split at 2026-01-01, TAKER cost 0.08% RT):
  CLOSE-confirmed market entry, channel=40, RR=2.0, SL=2.0xATR, EMA200 trend
  filter:  ALL PF 1.35 (172t)  TRAIN PF 1.39  TEST PF 1.11
  POSITIVE EVERY YEAR: 2023 PF 1.72 | 2024 PF 1.35 | 2025 PF 1.08 | 2026 PF 1.11
  (A resting-stop "fill-at-level" execution backtests materially stronger — ~PF
   1.5, TEST 1.55 — but needs a tick-watcher like ORB; this sleeve ships the
   simpler, lower-risk close-confirmed market entry that needs no new infra.)

WHY A NEW SLEEVE:
  The live book is almost entirely 1h INTRADAY momentum (ORB, FVG, IFVG, Squeeze,
  S/R) plus the 1h BB fade. There was NO higher-timeframe / multi-day swing sleeve
  — the 4h was only ever used as a confirmation filter, never as a primary entry
  timeframe. Donchian trades the 4h channel with 1-5 day holds, so it is
  decorrelated from the intraday sleeves by HOLDING PERIOD even though it is the
  same (momentum) style.

LOGIC:
  • Channel: highest-high / lowest-low of the prior `channel` 4h bars, EXCLUDING
    the just-closed bar (no lookahead).
  • Long  when the 4h candle CLOSES above the channel high AND close > EMA200(4h).
  • Short when the 4h candle CLOSES below the channel low  AND close < EMA200(4h).
    The EMA200 trend filter is the key robustness lever — it keeps breakouts
    aligned with the higher-timeframe trend (HTF alignment, not a holistic-edge
    partition) and was what lifted every yearly PF above 1.0.
  • Entry: market at the close (force_market — taker fill ~close, as validated).
  • SL = entry -/+ sl_atr x ATR(14, 4h).  TP = entry +/- rr x (sl_atr x ATR).
  • Max hold: 30 x 4h bars = 120h (5 days) — stored as 120 in 1h-candle units for
    the max-hold enforcer (which counts in primary-tf candles).
  • One position per `{symbol}:donchian` slot; analyze() only fires a fresh signal
    when the slot is empty (enforced by the executor), so an extended trend does
    not stack entries.

DATA NOTE:
  analyze() is fed the 4h OHLCV buffer (confirm_tf, ~260 bars) and the 4h ATR.
  It is called from the 1h candle loop only on a 4h boundary (UTC hour % 4 == 3),
  i.e. once per just-closed 4h bar.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators import atr as atr_fn, ema as ema_fn, obv as obv_fn, adx as adx_fn

DEFAULT_CHANNEL = 40
DEFAULT_RR = 2.0
DEFAULT_SL_ATR = 2.0
DEFAULT_EMA_TREND = 200
DEFAULT_BUFFER_ATR = 0.0
# ⚠ SAHTE-KIRILIM FILTRELERI — HEPSI VARSAYILAN KAPALI.
# Varsayilanlarla analyze() bugunku davranisin BIT BIT AYNISINI uretir; her
# biri yalnizca .env ile acilir ve once IKIZ'de olculur.
DEFAULT_CONFIRM_BARS = 0    # kirilimdan sonra kac bar seviyenin otesinde KAPANSIN
DEFAULT_RETEST_BARS = 0     # kac bar icinde seviyeye geri donus (retest) aransin
DEFAULT_VOL_MULT = 0.0      # kirilim barinin hacmi SMA20'nin kac kati olsun
DEFAULT_VOL_LOOKBACK = 20
DEFAULT_OBV_CONFIRM = False # OBV de yeni uc yapmali mi
# ⚠ ADX BU KOLDA HIC UYGULANMAMIS. main.py:681'de rejim kapisi (bo_allowed)
# yalniz ORB/Asia/S-R/Squeeze kollarinda; Donchian ondan MUAF ve kodun
# gerekcesi main.py:678'de yazili: "NOT regime-gated - its own EMA200 trend
# filter is the regime filter". Gerekce makul ama SINANMAMIS. 0 = kapali.
DEFAULT_ADX_MIN = 0.0
# ⚠ TEST PROTOKOLU v1.0'DAN GELEN UC YENI KAPI — hepsi VARSAYILAN KAPALI.
# Bunlar denenmemis eksenler; ADX/tampon/retest zaten denenip elendi.
DEFAULT_GOVDE_ORAN = 0.0    # 1.5 mum kalitesi: govde/aralik en az
DEFAULT_KAPANIS_KONUM = 0.0 # 1.5 kapanis mumun neresinde (long icin ust)
DEFAULT_FITIL_ORAN = 1.0    # 1.5 ters fitil/aralik en fazla
DEFAULT_CHASE_ATR = 0.0     # 1.9 seviyeden UZAKLIK en fazla kac ATR (0=kapali)
DEFAULT_ATR_GENISLEME = 0.0 # 1.10 ATR(simdi)/ATR(20 ort) en az
# ⚠ GIRIS MODU — kirilimi degil KIRILIMIN BASARISIZLIGINI trade etmek.
# Gerekce: ham karne SL oraninin %51.4 oldugunu gosterdi, yani kirilimlarin
# YARIDAN FAZLASI basarisiz. O havuz ters yonde bilgi tasiyor mu?
#   "kirilim"  : bugunku davranis -- kanal disina KAPANIS -> o yone gir
#   "basarisiz": onceki bar disina kapandi, SU ANKI bar iceri dondu -> TERS gir
#   "supurme"  : su anki barin FITILI disari tasti ama KAPANIS iceride -> TERS gir
#                (likidite supurme + reclaim; fitil seviyeyi deliyor, kapanis
#                 geri aliyor)
DEFAULT_MOD = "kirilim"
MODLAR = ("kirilim", "basarisiz", "supurme")
# Ters modlarda EMA200 trend filtresi YENI yone uygulanir. Kapatmak icin
# ters_trend=False: "basarisiz kirilim trendin tersine de olsa gir" demek.
DEFAULT_TERS_TREND = True
# Max hold in PRIMARY-tf (1h) candles: 30 x 4h bars = 120h (5 days).
MAX_HOLD_1H_CANDLES = 120


@dataclass
class DonchianSignal:
    direction: int        # +1 long | -1 short | 0 none
    strength: float       # 0.0 - 1.0
    reason: str
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0
    channel_high: float = 0.0
    channel_low: float = 0.0


class DonchianStrategy:
    """Donchian channel breakout on 4h with an EMA200 trend filter. analyze() is
    called once per closed 4h candle (from the 1h loop at a 4h boundary)."""

    def __init__(
        self,
        channel: int = DEFAULT_CHANNEL,
        rr: float = DEFAULT_RR,
        sl_atr: float = DEFAULT_SL_ATR,
        ema_trend: int = DEFAULT_EMA_TREND,
        buffer_atr: float = DEFAULT_BUFFER_ATR,
        confirm_bars: int = DEFAULT_CONFIRM_BARS,
        retest_bars: int = DEFAULT_RETEST_BARS,
        vol_mult: float = DEFAULT_VOL_MULT,
        vol_lookback: int = DEFAULT_VOL_LOOKBACK,
        obv_confirm: bool = DEFAULT_OBV_CONFIRM,
        adx_min: float = DEFAULT_ADX_MIN,
        govde_oran: float = DEFAULT_GOVDE_ORAN,
        kapanis_konum: float = DEFAULT_KAPANIS_KONUM,
        fitil_oran: float = DEFAULT_FITIL_ORAN,
        chase_atr: float = DEFAULT_CHASE_ATR,
        atr_genisleme: float = DEFAULT_ATR_GENISLEME,
        mod: str = DEFAULT_MOD,
        ters_trend: bool = DEFAULT_TERS_TREND,
    ):
        self._channel = channel
        self._rr = rr
        self._sl_atr = sl_atr
        self._ema_trend = ema_trend
        self._buffer_atr = buffer_atr
        self._confirm_bars = max(0, int(confirm_bars))
        self._retest_bars = max(0, int(retest_bars))
        self._vol_mult = float(vol_mult)
        self._vol_lookback = max(2, int(vol_lookback))
        self._obv_confirm = bool(obv_confirm)
        self._adx_min = float(adx_min)
        self._govde_oran = float(govde_oran)
        self._kapanis_konum = float(kapanis_konum)
        self._fitil_oran = float(fitil_oran)
        self._chase_atr = float(chase_atr)
        self._atr_genisleme = float(atr_genisleme)
        self._mod = str(mod).strip().lower() or "kirilim"
        if self._mod not in MODLAR:
            # .env'de yazim hatasi SESSIZCE bugunku davranisa dusmemeli;
            # dusseydi taramada "fark yok" diye YANLIS rapor verirdik.
            raise ValueError(
                f"bilinmeyen DONCHIAN_MOD={mod!r} -- gecerli: {sorted(MODLAR)}")
        self._ters_trend = bool(ters_trend)

    def _min_bars(self) -> int:
        # Need the channel lookback plus enough history for EMA200 to settle.
        # Teyit/retest filtreleri kirilim barini GERIYE kaydirdigi icin o kadar
        # ek bar, hacim filtresi de kendi geriye bakisi kadar bar ister.
        gecikme = max(self._confirm_bars, self._retest_bars,
                      1 if self._mod == "basarisiz" else 0)
        gerek = self._channel + 2 + gecikme
        if self._vol_mult > 0:
            gerek = max(gerek, self._channel + 2 + gecikme + self._vol_lookback)
        return max(gerek, self._ema_trend)

    def analyze(self, df: pd.DataFrame, atr_val: float) -> DonchianSignal:
        """df: recent 4h OHLCV (DatetimeIndex, columns open/high/low/close).
        atr_val: pre-computed 4h ATR(14) for sizing/stops."""
        if df is None or len(df) < self._min_bars():
            return DonchianSignal(0, 0.0, f"insufficient data ({0 if df is None else len(df)} < {self._min_bars()})")
        if atr_val is None or atr_val <= 0:
            return DonchianSignal(0, 0.0, "ATR not available")

        high = df["high"].to_numpy(dtype="float64")
        low = df["low"].to_numpy(dtype="float64")
        close = df["close"].to_numpy(dtype="float64")

        ema_series = ema_fn(df["close"], self._ema_trend)
        ema_now = float(ema_series.iloc[-1])
        if np.isnan(ema_now):
            return DonchianSignal(0, 0.0, "EMA200 not ready")

        c = float(close[-1])
        buf = self._buffer_atr * atr_val
        sl_dist = self._sl_atr * atr_val

        # ⚠ KIRILIM BARI NEREDE ARANIR.
        #   retest kapali, confirm=k  -> kirilim TAM k bar once olmali ve o
        #     gunden beri HER bar seviyenin otesinde KAPANMIS olmali
        #     (k=0 ise kirilim bu bardadir = bugunku davranis).
        #   retest=r                  -> kirilim son r barin herhangi birinde
        #     olabilir; GUNCEL bar seviyeye geri donup (fitil dokunusu) yine
        #     otesinde kapanmis olmali.
        # Her iki halde de kanal, kirilim barindan ONCEKI barlardan kuruluyor;
        # kirilim bari da sonrasi da kanala DAHIL DEGIL -> gelecege bakis yok.
        if self._mod in ("basarisiz", "supurme"):
            return self._ters_mod(df, high, low, close, c, ema_now, buf,
                                  sl_dist, atr_val)

        if self._retest_bars > 0:
            adaylar = range(1, self._retest_bars + 1)
        else:
            adaylar = (self._confirm_bars,)

        son_sebep = f"no breakout (close {c:.0f})"
        for k in adaylar:
            ch, cl = self._kanal(high, low, k)
            if ch is None:
                son_sebep = "insufficient data for channel"
                continue
            if ch <= cl:
                son_sebep = "degenerate channel"
                continue

            kirilim_c = float(close[-(k + 1)])
            if kirilim_c > ch + buf:
                yon, seviye = 1, ch
            elif kirilim_c < cl - buf:
                yon, seviye = -1, cl
            else:
                continue

            # Trend hizasi (EMA200) -- stratejinin kilit saglamlik kaldiraci.
            if (yon == 1 and not c > ema_now) or (yon == -1 and not c < ema_now):
                son_sebep = "EMA200 trend hizasi yok"
                continue

            if self._retest_bars > 0:
                # RETEST: guncel bar seviyeye geri donup otesinde kapanmali.
                # Dokunus fitille sinanir (low/high) -- bu bar KAPANMIS oldugu
                # icin fitili bilmek gelecege bakis DEGIL.
                dokundu = (low[-1] <= seviye) if yon == 1 else (high[-1] >= seviye)
                otede = (c > seviye) if yon == 1 else (c < seviye)
                if not (dokundu and otede):
                    son_sebep = f"retest yok ({k} bar once kirilim)"
                    continue
                etiket = f"retest@{k}b"
            else:
                # COKLU MUM TEYIDI: kirilimdan sonraki her bar seviyenin
                # OTESINDE KAPANMIS olmali (k=0 ise kontrol edilecek bar yok).
                sonrakiler = close[-k:] if k > 0 else np.empty(0)
                tutuyor = (bool(np.all(sonrakiler > seviye)) if yon == 1
                           else bool(np.all(sonrakiler < seviye)))
                if not tutuyor:
                    son_sebep = f"teyit yok ({k} bar seviyeyi korumadi)"
                    continue
                etiket = f"teyit{k}b" if k > 0 else "kapanis"

            tamam, neden = self._hacim_tamam(df, k)
            if not tamam:
                son_sebep = neden
                continue
            tamam, neden = self._obv_tamam(df, k, yon)
            if not tamam:
                son_sebep = neden
                continue
            tamam, neden = self._adx_tamam(df, k)
            if not tamam:
                son_sebep = neden
                continue
            tamam, neden = self._mum_kalitesi(df, k, yon)
            if not tamam:
                son_sebep = neden
                continue
            tamam, neden = self._chase_tamam(c, seviye, atr_val)
            if not tamam:
                son_sebep = neden
                continue
            tamam, neden = self._atr_genisleme_tamam(df, k, atr_val)
            if not tamam:
                son_sebep = neden
                continue

            sl = c - yon * sl_dist
            tp = c + yon * self._rr * sl_dist
            ad = "long" if yon == 1 else "short"
            karsi = "high" if yon == 1 else "low"
            return DonchianSignal(
                direction=yon, strength=0.80,
                reason=(f"Donchian {ad} [{etiket}]: close {c:.0f} vs channel "
                        f"{karsi} {seviye:.0f} (EMA200 {ema_now:.0f})"),
                sl_price=sl, tp_price=tp, entry_price=c,
                channel_high=ch, channel_low=cl,
            )

        return DonchianSignal(0, 0.0, son_sebep)

    def _ters_mod(self, df, high, low, close, c, ema_now, buf, sl_dist, atr_val):
        """Kirilimin BASARISIZLIGINI trade et.

        basarisiz: onceki bar kanal disina KAPANDI, su anki bar geri DONDU
        supurme  : su anki barin FITILI disari tasti ama KAPANIS iceride

        Iki halde de yon TERSTIR: yukari kirilim basarisizsa SHORT.
        SL/TP yine ATR capali (sistemin geri kalaniyla ayni) -- boylece R
        karsilastirilabilir kalir ve yeni bir degisken girmez."""
        if self._mod == "basarisiz":
            # kanal, basarisiz kirilim barindan ONCEKI barlardan kurulur
            ch, cl = self._kanal(high, low, 1)
            if ch is None or ch <= cl:
                return DonchianSignal(0, 0.0, "degenerate channel")
            onceki = float(close[-2])
            if onceki > ch + buf and c <= ch:
                yon, seviye = -1, ch          # yukari kirilim COKTU -> SHORT
            elif onceki < cl - buf and c >= cl:
                yon, seviye = 1, cl           # asagi kirilim COKTU -> LONG
            else:
                return DonchianSignal(0, 0.0, "kirilim basarisizligi yok")
            etiket = "basarisiz"
        else:
            ch, cl = self._kanal(high, low, 0)
            if ch is None or ch <= cl:
                return DonchianSignal(0, 0.0, "degenerate channel")
            if float(high[-1]) > ch + buf and c <= ch:
                yon, seviye = -1, ch          # fitil ustu supurdu, kapanis geri
            elif float(low[-1]) < cl - buf and c >= cl:
                yon, seviye = 1, cl
            else:
                return DonchianSignal(0, 0.0, "supurme+reclaim yok")
            etiket = "supurme"

        if self._ters_trend:
            if (yon == 1 and not c > ema_now) or (yon == -1 and not c < ema_now):
                return DonchianSignal(0, 0.0, "EMA200 trend hizasi yok")

        for f in (lambda: self._hacim_tamam(df, 0),
                  lambda: self._obv_tamam(df, 0, yon),
                  lambda: self._adx_tamam(df, 0),
                  lambda: self._atr_genisleme_tamam(df, 0, atr_val)):
            tamam, neden = f()
            if not tamam:
                return DonchianSignal(0, 0.0, neden)

        sl = c - yon * sl_dist
        tp = c + yon * self._rr * sl_dist
        ad = "long" if yon == 1 else "short"
        return DonchianSignal(
            direction=yon, strength=0.80,
            reason=(f"Donchian {ad} [{etiket}]: close {c:.0f} vs seviye "
                    f"{seviye:.0f} (EMA200 {ema_now:.0f})"),
            sl_price=sl, tp_price=tp, entry_price=c,
            channel_high=ch, channel_low=cl,
        )

    # -- sahte-kirilim filtrelerinin yardimcilari -------------------------

    def _kanal(self, high, low, k):
        """k bar onceki bar kirilim bariysa, ONDAN ONCEKI `channel` barin
        kanali. Kirilim bari ve sonrasi DAHIL DEGIL."""
        son = -(k + 1)
        bas = son - self._channel
        if -bas > len(high):
            return None, None
        return float(np.max(high[bas:son])), float(np.min(low[bas:son]))

    def _hacim_tamam(self, df, k):
        """Kirilim barinin hacmi, ONDAN ONCEKI `vol_lookback` barin
        ortalamasinin `vol_mult` katindan buyuk olmali. Dusuk hacimli ihlal =
        sahte kirilimin en yaygin imzasi."""
        if self._vol_mult <= 0:
            return True, ""
        if "volume" not in df.columns:
            return False, "hacim verisi yok"
        v = df["volume"].to_numpy(dtype="float64")
        son = -(k + 1)
        bas = son - self._vol_lookback
        if -bas > len(v):
            return False, "hacim gecmisi yetersiz"
        ort = float(np.mean(v[bas:son]))
        if not np.isfinite(ort) or ort <= 0:
            return False, "hacim ortalamasi sifir"
        oran = float(v[son]) / ort
        if oran < self._vol_mult:
            return False, f"hacim zayif ({oran:.2f}x < {self._vol_mult:.2f}x)"
        return True, ""

    def _adx_tamam(self, df, k):
        """Kirilim barinda 4h ADX esigin uzerinde olmali: zayif trendde gelen
        kirilimlari pas gec. ADX, stratejinin KENDI gordugu 4h veriden
        hesaplanir (1h rejim degeri degil) -- kol 4h'te calisiyor."""
        if self._adx_min <= 0:
            return True, ""
        a = adx_fn(df["high"], df["low"], df["close"]).to_numpy(dtype="float64")
        son = -(k + 1)
        if -son > len(a):
            return False, "ADX gecmisi yetersiz"
        v = float(a[son])
        if not np.isfinite(v):
            return False, "ADX hazir degil"
        if v < self._adx_min:
            return False, f"ADX zayif ({v:.1f} < {self._adx_min:.1f})"
        return True, ""

    def _mum_kalitesi(self, df, k, yon):
        """1.5 — kirilim mumunun SEKLI. Fitille kirip kapanista geri donen mum
        klasik sahte kirilimdir; govdesi guclu ve kapanisi ucta olan mum
        gercek katilimi gosterir.
          govde/aralik      >= govde_oran
          kapanis konumu    long icin >= kapanis_konum (ustte), short icin <=
          ters fitil/aralik <= fitil_oran"""
        if (self._govde_oran <= 0 and self._kapanis_konum <= 0
                and self._fitil_oran >= 1.0):
            return True, ""
        i = -(k + 1)
        o = float(df["open"].iloc[i]); c = float(df["close"].iloc[i])
        h = float(df["high"].iloc[i]); l = float(df["low"].iloc[i])
        aralik = h - l
        if aralik <= 0:
            return False, "mum araligi sifir"
        if abs(c - o) / aralik < self._govde_oran:
            return False, f"govde zayif ({abs(c-o)/aralik:.2f})"
        konum = (c - l) / aralik if yon == 1 else (h - c) / aralik
        if konum < self._kapanis_konum:
            return False, f"kapanis ucta degil ({konum:.2f})"
        ters = (h - max(o, c)) if yon == 1 else (min(o, c) - l)
        if ters / aralik > self._fitil_oran:
            return False, f"ters fitil buyuk ({ters/aralik:.2f})"
        return True, ""

    def _chase_tamam(self, c, seviye, atr_val):
        """1.9 — seviyeden COK uzakta girme. ⚠ Bu, denenip elenen ATR
        TAMPONUNUN TERSI: tampon 'en az su kadar assin' diyordu, bu 'en fazla
        su kadar uzaklassin' diyor. Fiyat cok kacmissa R/R bozulur."""
        if self._chase_atr <= 0 or atr_val <= 0:
            return True, ""
        uzaklik = abs(c - seviye) / atr_val
        if uzaklik > self._chase_atr:
            return False, f"cok uzak ({uzaklik:.2f} ATR > {self._chase_atr:.2f})"
        return True, ""

    def _atr_genisleme_tamam(self, df, k, atr_val):
        """1.10 — sikismadan genislemeye gecis. Kirilim ANINDAKI ATR, son 20
        barin ATR ortalamasinin en az `atr_genisleme` kati olmali."""
        if self._atr_genisleme <= 0:
            return True, ""
        a = atr_fn(df["high"], df["low"], df["close"]).to_numpy(dtype="float64")
        son = -(k + 1)
        bas = son - 20
        if -bas > len(a):
            return False, "ATR gecmisi yetersiz"
        ort = float(np.nanmean(a[bas:son]))
        if not np.isfinite(ort) or ort <= 0:
            return False, "ATR ortalamasi sifir"
        oran = float(a[son]) / ort
        if oran < self._atr_genisleme:
            return False, f"ATR genislemedi ({oran:.2f}x)"
        return True, ""

    def _obv_tamam(self, df, k, yon):
        """Fiyat yeni uc yaparken OBV de yapmali. Yapmiyorsa para girisi yok
        demektir (uyumsuzluk) ve hareket buyuk ihtimalle sahte."""
        if not self._obv_confirm:
            return True, ""
        if "volume" not in df.columns:
            return False, "hacim verisi yok (OBV)"
        o = obv_fn(df["close"], df["volume"]).to_numpy(dtype="float64")
        son = -(k + 1)
        bas = son - self._channel
        if -bas > len(o):
            return False, "OBV gecmisi yetersiz"
        pencere = o[bas:son]
        if yon == 1 and o[son] <= float(np.max(pencere)):
            return False, "OBV yeni zirve yapmadi (uyumsuzluk)"
        if yon == -1 and o[son] >= float(np.min(pencere)):
            return False, "OBV yeni dip yapmadi (uyumsuzluk)"
        return True, ""
