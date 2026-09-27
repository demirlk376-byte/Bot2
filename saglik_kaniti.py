"""
saglik_kaniti.py — "bot neden işlem açmıyor / sağlam mı?" sorusunun KANITI. İstatistik değil, SAYIM.

sessizlik.py "4-5 gün sessizlik dağılıma uyuyor" dedi. Bu 'SORUN YOK' DEMEK DEĞİL —
sadece 'sessizlik tek başına kanıt değil' demek. Bu araç farklı bir soru soruyor:

    SON N GÜNDE KAÇ SİNYAL OLUŞMALIYDI?  KAÇ TANESİ AÇILDI?  AÇILMAYANLAR NEDEN?

Log'a GÜVENMİYOR: canlı kod direction==0 iken hiçbir şey yazmıyor, yani boş log
"sinyal yok" ile "sinyal yutuldu"yu ayırt etmiyor. Bu yüzden sinyaller ÜRETİM
SINIFLARIYLA, main.py'deki kurulum ve kapılarla BİREBİR sıfırdan yeniden hesaplanıyor.

DÖRT BAĞIMSIZ KONTROL:
  A) AYAR    — canlının kullandığı değerler (VOL_MULT, MTF, RR, rejim eşikleri, kol coinleri)
  B) VERİ    — borsa mumları taze mi? (bayat veri = sessizce kör bot)
  C) SİNYAL  — her kol için canlı kapılarla yeniden hesap; her aday için HÜKÜM
  D) SAYIM   — trades.db'deki GERÇEK girişler, açık pozisyon yaşı, son giriş/sessizlik

2026-09-27 DÜZELTMESİ — eski sürüm 14 YALANCI "⛔ AÇIKLANAMADI" bastı. Sebepler:
  1) DonchianStrategy canlının parametrelerinin yarısıyla kuruluyordu (VOL_MULT YOK) →
     canlının hacim filtresiyle bilerek elediği kırılımlar "açılmalıydı" sanıldı.
     Artık her kol main.py'deki çağrıyla BİREBİR kuruluyor (satır atıfları kodda).
  2) Sinyal 4h bar AÇILIŞIYLA etiketlenip ±3 saat eşleniyordu; Donchian girişi bar
     KAPANIŞINDA olur (+4h, main.py:769). Artık sinyal zamanı = bar KAPANIŞI, beklenen
     giriş [kapanış, kapanış+90dk).
  3) Oluşmakta olan 1h mum ve yarım 4h bar taranıyordu → artık yalnız KAPANMIŞ barlar.
  4) Defter yalnız pencerede GİRİLEN işlemleri okuyor, açık pozisyonları İKİ KEZ sayıyordu.
  5) Bayat "RR 2.0 ankor" SAPMA uyarısı kaldırıldı (canlı 2026-07-21'den beri 2.5).
  6) BB/LTC (yalnız hafta sonu) kolu HİÇ modellenmiyordu.
  7) --dogrula ankor parametrelerini elle kopyalıyordu; artık deployed_backtest.py'den OKUYOR.

⚠ SALT-OKUR: trades.db `mode=ro` açılır; data/ altına ve repoya HİÇBİR ŞEY yazılmaz
(fast_bt.load/_save_cache yoluna girilmez); borsaya yalnız HALKA AÇIK mum isteği gider,
emir/hesap çağrısı YOK.

Kullanım:
    python3 saglik_kaniti.py 7              # VPS: son 7 gün, MEXC mumları + trades.db (gerçek)
    python3 saglik_kaniti.py 7 --db-yok     # DB'siz (GitHub Actions): filtreleri geçenleri listeler
    python3 saglik_kaniti.py 14 --veri data --db ikiz.db --paper --simdi 2026-07-18T23:00
    python3 saglik_kaniti.py --dogrula      # öz-test: yeniden hesap ankorla örtüşüyor mu?
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from indicators import atr as atr_fn, adx as adx_fn
from config import load_config

SAAT = pd.Timedelta(hours=1)
DORT_SAAT = pd.Timedelta(hours=4)
# market giriş kapanıştan saniyeler sonra; maker 45sn + piyasa yedeği (execution.py:704-711).
# 90 dk: poll gecikmesi + yeniden deneme payı. Bir sonraki 1h kapanışı da kapsar; o yüzden
# eşleme BİRE-BİR ve "en geç kapanış" kuralıyla yapılır (aynı girişi iki sinyal yiyemez).
GIRIS_TOLERANS = pd.Timedelta(minutes=90)
ERKEN_TOLERANS = pd.Timedelta(minutes=1)   # sunucu saati kayması: giriş kapanıştan az ÖNCE yazılmış olabilir
# Aynı kapanış turu: canlıda coinlerin 1h poll'u 30 sn fazlı, ikizde (zaman, sembol)
# sırası. Bu turda BAŞKA coinde açılan/kapanan pozisyon, koltuk/coin kilidini açıklayabilir.
AYNI_TUR = pd.Timedelta(minutes=5)
ISLENIYOR = pd.Timedelta(minutes=5)        # kapanıştan bu kadar yeniyse giriş DB'ye düşmemiş olabilir
DEFTER_GERI = pd.Timedelta(days=10)        # doluluk defteri: exit >= pencere başı − 10 gün
ISITMA_GUN = 50                            # 260×4h = 43.3 gün tampon + pay
MAX_HOLD_PAYI = 1.5                        # max_hold 1h KAPANIŞINDA uygulanır (main.py:217) → ≤1 saat gecikme doğal
SESSIZ_KONTROL, SESSIZ_ARIZA = 6.0, 8.0    # ikiz 3.3 yıl: 4-5 gün olağan, p99 6.2, en uzun 7.7 gün
# execution.py:1282/1320 — bu nedenlerle kapanan işlemler de sayaca girer; ancak
# cd_canli_denetim.py:12'nin tespiti: halted_entry / no_stop_safety kapanışları SAYACA GİRMEZ.
SAYACI_ATLAYAN = ("halted_entry", "no_stop_safety")
# execution.py:21-23 _CORRELATED_GROUPS (modülü import etmemek için kopya — yan etkisiz kalsın)
KORELE_GRUPLAR = (frozenset({"BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"}),)
KOL_AD = {"donchian": "donchian", "squeeze": "squeeze", "mean_rev": "BB"}
KOL_SIRA = ("donchian", "squeeze", "mean_rev")


def _simdi(v=None) -> pd.Timestamp:
    if v is None:
        return pd.Timestamp.now(tz="UTC")
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _ts(v):
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


# ───────────────────────── veri (ankor önbelleğine DOKUNMAZ) ─────────────────
def kapanmis(m: pd.DataFrame, simdi) -> pd.DataFrame:
    """Yalnız KAPANMIŞ 1h mumlar (açılış + 1h <= şimdi). ccxt son satırda oluşmakta olan
    mumu döndürür; canlı onu atar (data.py:146-147, :258) — burada da atılır."""
    return m[m.index + SAAT <= _simdi(simdi)]


_BORSA = None          # tek ccxt nesnesi: load_markets 11 kez değil BİR kez


def cek(coin: str, gun: int = 220, simdi=None) -> pd.DataFrame:
    """MEXC vadeli 1h — pencereli, YALNIZ KAPANMIŞ mumlar. fast_bt.load KULLANMAZ (o 1200
    gün çeker ve _save_cache yoluna girer). Burada data/ altına hiçbir şey yazılmaz.
    Yalnız halka açık fetch_ohlcv — anahtar/emir yok."""
    global _BORSA
    simdi = _simdi(simdi)
    if _BORSA is None:
        import ccxt
        _BORSA = ccxt.mexc({"options": {"defaultType": "swap"}})
    ex = _BORSA
    sym = f"{coin}/USDT:USDT"
    since = int((simdi - pd.Timedelta(days=gun)).timestamp() * 1000)
    rows = []
    for _ in range(60):                      # ≤30k mum; borsa 'since'ı yok sayarsa sonsuz döngü OLMASIN
        b = ex.fetch_ohlcv(sym, "1h", since=since, limit=500)
        if not b:
            break
        rows += b
        if len(b) < 500 or b[-1][0] < since:
            break
        since = b[-1][0] + 1
    if not rows:
        # SystemExit DEĞİL: çağıran `except Exception` ile yakalayıp diğer coinlere devam eder.
        raise RuntimeError(f"{coin}: MEXC vadeli veri çekilemedi ({sym})")
    m = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    m = m.drop_duplicates("ts", keep="last")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    m = m.drop(columns=["ts"]).astype(float).sort_index()
    return kapanmis(m, simdi)


def _yerel_ham(coin: str, klasor: str) -> pd.DataFrame:
    """{klasor}/{COIN}_fut_1h.csv — fast_bt.load(source='local') ile AYNI okuma, ama o
    fonksiyonu çağırmadan (salt-okur; hiçbir önbellek yoluna girmez)."""
    p = os.path.join(klasor, f"{coin}_fut_1h.csv")
    if not os.path.exists(p):
        raise FileNotFoundError(f"{coin}: yerel veri yok ({p})")
    return pd.read_csv(p, index_col=0, parse_dates=True)


def yerel_oku(coin: str, klasor: str, simdi=None, gun: int | None = None) -> pd.DataFrame:
    m = _yerel_ham(coin, klasor)
    m.index = (m.index.tz_localize("UTC") if m.index.tz is None
               else m.index.tz_convert("UTC"))
    m = m[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    m = m[~m.index.duplicated(keep="last")]
    if simdi is not None:
        m = kapanmis(m, simdi)
        if gun is not None:
            m = m[m.index >= _simdi(simdi) - pd.Timedelta(days=gun)]
    return m


def resample(m, tf):
    return m.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()


def dort_saat(m1: pd.DataFrame) -> pd.DataFrame:
    """1h → 4h (MEXC 4h mumları da 00:00 UTC hizalı). Kapanışı son KAPANMIŞ 1h mumun
    kapanışından sonra olan (yarım) 4h bar ATILIR."""
    d4 = resample(m1, "4h")
    if not len(m1):
        return d4
    son = m1.index[-1] + SAAT
    return d4[d4.index + DORT_SAAT <= son]


# ───────────────────────── canlı kurulumun AYNASI ────────────────────────────
def donchian_kwargs(cfg) -> dict:
    """main.py:2107-2126 DonchianStrategy(...) çağrısının BİREBİR kopyası."""
    s = cfg.strategy
    return dict(channel=s.donchian_channel, rr=s.donchian_rr, sl_atr=s.donchian_sl_atr,
                ema_trend=s.donchian_ema_trend, buffer_atr=s.donchian_buffer_atr,
                confirm_bars=s.donchian_confirm_bars, retest_bars=s.donchian_retest_bars,
                vol_mult=s.donchian_vol_mult, vol_lookback=s.donchian_vol_lookback,
                obv_confirm=s.donchian_obv, adx_min=s.donchian_adx_min,
                govde_oran=s.donchian_govde_oran, kapanis_konum=s.donchian_kapanis_konum,
                fitil_oran=s.donchian_fitil_oran, chase_atr=s.donchian_chase_atr,
                atr_genisleme=s.donchian_atr_genisleme, mod=s.donchian_mod,
                ters_trend=s.donchian_ters_trend)


def squeeze_kwargs(cfg) -> dict:
    """main.py:2074-2084 SqueezeStrategy(...) çağrısının BİREBİR kopyası."""
    s = cfg.strategy
    return dict(kc_mult=s.squeeze_kc_mult, min_squeeze_bars=s.squeeze_min_bars,
                sl_atr=s.squeeze_sl_atr, rr=s.squeeze_rr, mtf_filter=s.squeeze_mtf,
                vol_mult=s.squeeze_vol_mult, mod=s.squeeze_mod,
                takip_bar=s.squeeze_takip_bar, vol_lookback=s.squeeze_vol_lookback)


def stratejiler(cfg, dc_kw: dict | None = None, sq_kw: dict | None = None) -> dict:
    """Tam (canlı) sınıflar + 'ham' eşleri. Ham eş YALNIZ kanıt içindir: tam sınıf bir
    sinyali eleyince, elenenin NE olduğunu (hacim oranı, 4h çelişkisi, sniper) göstermek."""
    from strategies.donchian import DonchianStrategy
    from strategies.squeeze import SqueezeStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    dc_kw = dict(dc_kw or donchian_kwargs(cfg))
    sq_kw = dict(sq_kw or squeeze_kwargs(cfg))
    bb_ham = dataclasses.replace(cfg.strategy, vol_filter_enabled=False, sniper_min_grade=0)
    return {
        "dc": DonchianStrategy(**dc_kw),
        "dc_ham": DonchianStrategy(**{**dc_kw, "vol_mult": 0.0}),     # VOL_MULT=0: ham kırılım
        "sq": SqueezeStrategy(**sq_kw),
        "sq_ham": SqueezeStrategy(**{**sq_kw, "mtf_filter": False, "vol_mult": 0.0}),
        "bb": MeanReversionStrategy(cfg.strategy),                   # main.py:2022
        "bb_ham": MeanReversionStrategy(bb_ham),
        "dc_kw": dc_kw, "sq_kw": sq_kw,
    }


def kollar(cfg) -> dict:
    """coin → canlıda o coinde GERÇEKTEN işlem açabilen kollar.
    Kurulum main.py:2014-2126 (yalnız SYMBOLS'taki coinler için bağlam kurulur);
    BB her coinde kurulur ama çalışma anında bb_symbols ile kapılanır (main.py:280-282)."""
    s = cfg.strategy
    out = {}
    for sym in (cfg.exchange.symbols or [cfg.exchange.symbol]):
        k = []
        if s.donchian_enabled and (s.donchian_symbols is None or sym in s.donchian_symbols):
            k.append("donchian")
        if s.squeeze_enabled and (s.squeeze_symbols is None or sym in s.squeeze_symbols):
            k.append("squeeze")
        if s.bb_symbols is None or sym in s.bb_symbols:
            k.append("mean_rev")
        if k:
            out[sym.split("/")[0]] = k
    return out


def rejim(adx_val: float, cfg) -> str:
    """main.py:1130-1138 _get_regime ile BİREBİR."""
    trending = getattr(cfg.risk, "adx_trending_threshold", 28.0)
    ranging = getattr(cfg.risk, "adx_ranging_threshold", 20.0)
    if adx_val >= trending:
        return "trending"
    if adx_val <= ranging:
        return "ranging"
    return "neutral"


def mtf_ok(df_4h, direction, aktif):
    """main.py:1141-1156 _donchian_mtf_ok ile BİREBİR (kapalıysa hep True)."""
    if not aktif:
        return True
    try:
        d1d = df_4h.resample("1D").agg({"close": "last"}).dropna()
        if len(d1d) < 20:
            return True
        dema20 = d1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        up = float(d1d["close"].iloc[-1]) > float(dema20)
        return (direction == 1 and up) or (direction == -1 and not up)
    except Exception:
        return True


def hacim_orani(df: pd.DataFrame, lookback: int, k: int = 0) -> float:
    """strategies/donchian.py:_hacim_tamam ile aynı oran: kırılım barı hacmi / ÖNCEKİ
    `lookback` barın ortalaması."""
    v = df["volume"].to_numpy(dtype="float64")
    son = -(k + 1)
    bas = son - max(2, int(lookback))
    if -bas > len(v):
        return float("nan")
    ort = float(np.mean(v[bas:son]))
    return float(v[son]) / ort if np.isfinite(ort) and ort > 0 else float("nan")


# ───────────────────────── C) SİNYAL YENİDEN HESABI ──────────────────────────
def _aday(coin, kol, t, yon, olcu, metrik, adx_val, filtre=None, ic=False, fiyat=None, sl_mes=None):
    return {"coin": coin, "sym": f"{coin}/USDT:USDT", "kol": kol, "t": t, "yon": int(yon),
            "olcu": olcu, "metrik": metrik, "adx": adx_val, "filtre": filtre, "ic": ic,
            "karar": None, "giris": None, "fiyat": fiyat, "sl_mes": sl_mes}


def adaylar_coin(coin, m1, cfg, kol_listesi, bas, st, mtf_aktif=None):
    """Tek coin: [bas, son kapanış] içindeki HER kapanmış 1h bar için canlı
    on_candle_close'u (main.py:186-900) yeniden kurar. Sinyal zamanı = bar KAPANIŞI.

    Aday satırları:
      filtre=None      → kolun TÜM kapılarını geçti; açılmış olmalı (D bölümü sayar)
      filtre=metin     → kol kapısı/iç filtre eledi (BEKLENEN)
      ic=True          → iç filtre (hacim/4h/sniper) ham eşin gördüğü ama tam sınıfın elediği
    İç filtre satırları yalnız kolun kendi kapıları AÇIKKEN listelenir (hafta içi BB'nin
    ya da rejimin kapattığı squeeze'in iç reddi gürültüdür)."""
    s, r = cfg.strategy, cfg.risk
    mtf_aktif = s.donchian_mtf_enabled if mtf_aktif is None else mtf_aktif
    out = []
    idx = m1.index
    d4 = dort_saat(m1) if "donchian" in kol_listesi else None
    d4_yer = {t: i for i, t in enumerate(d4.index)} if d4 is not None else {}
    dch_min = max(s.donchian_channel + 2, s.donchian_ema_trend)          # main.py:788-789
    lb = st["dc_kw"].get("vol_lookback", 20)
    kb = int(st["dc_kw"].get("confirm_bars", 0) or 0)
    # düz aralıkta (TR=0) ADX 0/0 uyarısı basar; canlı da aynı değeri (NaN→20) kullanır,
    # yalnız ekranı kirletmesin diye susturuluyor — hesap DEĞİŞMEZ.
    with np.errstate(invalid="ignore", divide="ignore"):
        for j in range(len(m1)):
            T = idx[j] + SAAT                                  # 1h mum KAPANIŞI = işlenme anı
            if T < bas:
                continue
            df = m1.iloc[max(0, j - 119):j + 1]                # main.py:191 get_candles(1h, 120)
            if len(df) < s.bb_period + 5:                      # main.py:192
                continue
            atr_val = atr_fn(df["high"], df["low"], df["close"], s.atr_period).iloc[-1]
            if not np.isfinite(atr_val) or atr_val <= 0:       # main.py:224-227: TÜM kollar atlanır
                continue
            adx_raw = adx_fn(df["high"], df["low"], df["close"], s.adx_period).iloc[-1]
            adx_val = float(adx_raw) if np.isfinite(adx_raw) else 20.0   # main.py:230-235
            rej = rejim(adx_val, cfg)
            filt = r.regime_filter_enabled                     # main.py:272
            bo_allowed = not (filt and rej == "ranging")       # main.py:273

            # ── BB / mean_rev (main.py:274-282, 286, 344) ────────────────────────
            if "mean_rev" in kol_listesi:
                # hafta sonu = datetime.now() mum KAPANIŞINDA okunur (main.py:274); ikiz de
                # saati kapanışa kurar (ikiz/kos.py:353). Cuma 23:00 mumu (kapanış Cmt 00:00)
                # HAFTA SONU, Pazar 23:00 mumu (kapanış Pzt 00:00) HAFTA İÇİ sayılır.
                hafta_sonu = T.weekday() >= 5
                gun_kapali = not getattr(r, "bb_weekday_enabled", True) and not hafta_sonu
                trend_kapali = filt and rej == "trending"      # main.py:275 (ADX ≥ 28)
                # sınıfın İÇ filtreleri canlı ayarla: VOL_FILTER_ENABLED=true → uç mumun hacmi
                # 20 bar SMA'nın altındaysa sinyal YOK (mean_reversion.py:117-125);
                # SNIPER_MIN_GRADE (vars. 2) → 3 puanlık teyitten <2 ise YOK (:133-137, :150-154).
                # FUNDING_ENABLED=false → funding kapısı yok (main.py:309-326); orderflow yalnız log.
                mr = st["bb"].analyze(df)
                if mr.direction != 0:
                    a = _aday(coin, "mean_rev", T, mr.direction, adx_val, f"ADX {adx_val:5.1f}", adx_val,
                              fiyat=float(df["close"].iloc[-1]),
                              sl_mes=float(atr_val) * r.atr_sl_multiplier)     # risk.py:34-36
                    if gun_kapali:
                        a["filtre"] = "hafta içi (BB kapalı) — BEKLENEN"
                    elif trend_kapali:
                        a["filtre"] = (f"rejim/ADX kapısı (ADX {adx_val:.1f} ≥ "
                                       f"{r.adx_trending_threshold:g}) — BEKLENEN")
                    out.append(a)
                elif not (gun_kapali or trend_kapali):
                    ham = st["bb_ham"].analyze(df)
                    if ham.direction != 0:
                        if mr.reason.startswith("low volume"):
                            neden = "BB hacim filtresi (hacim < 20 bar ort., VOL_FILTER)"
                        elif mr.reason.startswith("sniper filtered"):
                            neden = (f"BB sniper derecesi ({mr.reason.split('sniper ')[-1].split(':')[0]}"
                                     f" < {s.sniper_min_grade}/3)")
                        else:
                            neden = f"BB iç filtre ({mr.reason[:40]})"
                        out.append(_aday(coin, "mean_rev", T, ham.direction, adx_val,
                                         f"ADX {adx_val:5.1f}", adx_val, neden + " — BEKLENEN", True))

            # ── Squeeze (main.py:633-634; bo_allowed kapısı) ─────────────────────
            if "squeeze" in kol_listesi:
                sq = st["sq"].analyze(df, float(atr_val))
                if sq.direction != 0:
                    # canlı rejim kapalıyken analyze'ı HİÇ çağırmaz; burada "kapı olmasa ne
                    # olurdu" görünsün diye çağrılıp REJİM KAPISI hükmüyle listeleniyor.
                    a = _aday(coin, "squeeze", T, sq.direction, adx_val, f"ADX {adx_val:5.1f}", adx_val,
                              fiyat=float(df["close"].iloc[-1]),
                              sl_mes=float(atr_val) * st["sq_kw"].get("sl_atr", 2.0))
                    if not bo_allowed:
                        a["filtre"] = (f"rejim/ADX kapısı (ADX {adx_val:.1f} ≤ "
                                       f"{r.adx_ranging_threshold:g}) — BEKLENEN")
                    out.append(a)
                elif bo_allowed:
                    ham = st["sq_ham"].analyze(df, float(atr_val))
                    if ham.direction != 0:
                        if sq.reason.startswith("MTF filter"):
                            neden = "squeeze 4h yön çelişkisi (SQUEEZE_MTF)"
                        elif sq.reason.startswith("hacim"):
                            neden = f"squeeze hacim filtresi ({sq.reason})"
                        else:
                            neden = f"squeeze iç filtre ({sq.reason[:40]})"
                        out.append(_aday(coin, "squeeze", T, ham.direction, adx_val,
                                         f"ADX {adx_val:5.1f}", adx_val, neden + " — BEKLENEN", True))

            # ── Donchian (main.py:769-806): yalnız 4h kapanışında, rejim kapısı YOK ──
            if "donchian" in kol_listesi and idx[j].hour % 4 == 3:
                k = d4_yer.get(idx[j] - pd.Timedelta(hours=3))   # main.py:780 expected_4h_open
                if k is None:
                    continue                                        # canlı: "4h buffer stale" → atlar
                df4 = d4.iloc[max(0, k - 259):k + 1]               # main.py:770 get_candles(4h, 260)
                if len(df4) < dch_min:                             # main.py:798-800
                    continue
                atr4 = atr_fn(df4["high"], df4["low"], df4["close"], s.atr_period).iloc[-1]
                if not np.isfinite(atr4) or atr4 <= 0:             # main.py:804
                    continue
                sig = st["dc"].analyze(df4, float(atr4))
                oran = hacim_orani(df4, lb, kb)
                met = f"hacim {oran:4.2f}×"
                if sig.direction != 0:
                    a = _aday(coin, "donchian", T, sig.direction, oran, met, adx_val,
                              fiyat=float(df4["close"].iloc[-1]),
                              sl_mes=float(atr4) * st["dc_kw"].get("sl_atr", 2.0))
                    if not mtf_ok(df4, sig.direction, mtf_aktif):  # main.py:806
                        a["filtre"] = "MTF kapısı (günlük EMA20 ters) — BEKLENEN"
                    out.append(a)
                else:
                    ham = st["dc_ham"].analyze(df4, float(atr4))
                    if ham.direction != 0:
                        # tam sınıf ile ham eş YALNIZ vol_mult'ta farklı → eleyen hacim filtresi
                        out.append(_aday(coin, "donchian", T, ham.direction, oran, met, adx_val,
                                         f"hacim filtresi ({oran:.2f}× < {st['dc_kw']['vol_mult']:g}×)"
                                         " — BEKLENEN", True))
    return out


# ───────────────────────── D) GERÇEK GİRİŞLER ────────────────────────────────
def kol_of(rec):
    try:
        return json.loads(rec["strategy_scores"] or "{}").get("strategy", "?")
    except Exception:
        return "?"


def _baglan(db_path):
    """SALT-OKUR bağlantı: dosya yoksa OLUŞTURMAZ, yazma denemesi hata verir."""
    uri = Path(db_path).absolute().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def _kayit(r: dict) -> dict:
    try:
        sc = json.loads(r.get("strategy_scores") or "{}")
    except Exception:
        sc = {}
    return {"id": r["id"], "symbol": r["symbol"], "coin": r["symbol"].split("/")[0],
            "kol": sc.get("strategy", "?"),
            "yon": 1 if str(r["side"]).lower() in ("long", "buy") else -1,
            "side": r["side"], "giris": _ts(r["entry_time"]),
            "cikis": _ts(r["exit_time"]) if r.get("exit_time") else None,
            "pnl": float(r.get("pnl_usdt") or 0.0), "neden": r.get("exit_reason") or "",
            "max_hold": sc.get("max_hold"),
            "fiyat": float(r.get("entry_price") or 0.0), "miktar": float(r.get("quantity") or 0.0)}


def defter(db_path, bas, simdi, paper=False):
    """Döner: (poz, kapanan, e0)
      poz     — exit_time NULL ya da exit_time >= bas−10g olan işlemler, id başına BİR KEZ
                (eski sürüm açık pozisyonu hem 'girişler' hem 'açıklar' listesinde sayıyordu).
      kapanan — TÜM kapanmış işlemler (ardışık-kayıp sayacı 10 günden eskiye uzanabilir;
                anahtar başına işlem seyrek — donchian coin başına ~20 günde bir).
      e0      — marj tahmini için başlangıç sermayesi: meta inception_balance + total_deposits
                (yoksa None → marj kapısı tahmin EDİLMEZ).
    `simdi` sonrası YOK sayılır: sonra girilen atılır, sonra kapanan o an AÇIK sayılır."""
    con = _baglan(db_path)
    try:
        p = 1 if paper else 0
        alan = ("id,symbol,side,entry_time,exit_time,exit_reason,pnl_usdt,strategy_scores,"
                "entry_price,quantity")
        poz = [dict(r) for r in con.execute(
            f"SELECT {alan} FROM trades WHERE is_paper=? AND "
            "(exit_time IS NULL OR exit_time >= ?) ORDER BY entry_time",
            (p, (bas - DEFTER_GERI).isoformat()))]
        kap = [dict(r) for r in con.execute(
            f"SELECT {alan} FROM trades WHERE is_paper=? AND exit_time IS NOT NULL "
            "ORDER BY exit_time", (p,))]
        try:
            meta = {k: v for k, v in con.execute(
                "SELECT key, value FROM meta WHERE key IN ('inception_balance','total_deposits')")}
        except sqlite3.Error:
            meta = {}
    finally:
        con.close()
    tekil = {}
    for r in poz:
        tekil[r["id"]] = _kayit(r)
    poz = [g for g in tekil.values() if g["giris"] <= simdi]
    for g in poz:
        if g["cikis"] is not None and g["cikis"] > simdi:
            g["cikis"] = None
    kap = [_kayit(r) for r in kap]
    kap = [g for g in kap if g["cikis"] <= simdi]
    try:
        e0 = (float(meta["inception_balance"]) + float(meta.get("total_deposits") or 0.0)
              if "inception_balance" in meta else None)
    except (TypeError, ValueError):
        e0 = None
    return poz, kap, e0


def soguma_listesi(kapanan, limit, dakika):
    """execution.py:311-347 _record_trade_outcome'u kapanış sırasıyla yeniden oynatır.
    Anahtar (kol, sembol); zarar → seri++, seri >= limit → kapanıştan `dakika` kadar
    soğuma; kâr seriyi sıfırlar; soğuma tetiklenince seri SIFIRLANMAZ.
    ⚠ Canlıda sayaç bellekte — restart sıfırlar. Buradaki liste ÜST SINIRDIR."""
    seri = defaultdict(int)
    out = defaultdict(list)
    for g in sorted(kapanan, key=lambda x: x["cikis"]):
        if g["neden"] in SAYACI_ATLAYAN:
            continue
        key = (g["kol"], g["symbol"])
        if g["pnl"] < 0:
            seri[key] += 1
            if seri[key] >= limit:
                out[key].append((g["cikis"], g["cikis"] + pd.Timedelta(minutes=dakika)))
        else:
            seri[key] = 0
    return out


def cooldown_aktif(tum, sym, kol, t, limit, dakika):
    """Geriye uyum (arastirma/sessizlik_kontrol/*): ham trades satırlarıyla soğuma var mı."""
    if not dakika:
        return False
    rows = [dict(g) for g in tum if g["symbol"] == sym and kol_of(g) == kol and g.get("exit_time")]
    kap = [{"kol": kol, "symbol": sym, "cikis": _ts(g["exit_time"]),
            "pnl": float(g.get("pnl_usdt") or 0.0), "neden": g.get("exit_reason") or ""}
           for g in rows if _ts(g["exit_time"]) <= t]
    return any(b <= t < e for b, e in soguma_listesi(kap, limit, dakika).get((kol, sym), []))


def _acik(g, t):
    """t kapanışı işlenirken AÇIK: t'den ÖNCE girilmiş, t'de ya da önce kapanmamış.
    Aynı coinin t kapanışındaki SL/TP/max_hold çıkışı girişten ÖNCE işlenir
    (main.py:205-217 → 634/805), o yüzden cikis == t açık SAYILMAZ."""
    return g["giris"] < t and (g["cikis"] is None or g["cikis"] > t)


def _ayni_tur(g, t):
    """Aynı kapanış turunda açılan / kapanan pozisyon — işlenme sırası belirsiz:
      • canlıda coinlerin 1h poll'u 30 sn fazlı; ikizde (zaman, sembol) sırası
      • PAPER'da SL/TP kapanışı portföyden create_task ile SONRADAN düşer (exchange.py:
        _close_paper_position → cb görevi), yani cikis == t olan pozisyon, aynı turdaki
        giriş denetiminde hâlâ portföyde olabilir (ikizde ölçüldü: BNB 2023-06-05 16:00)."""
    return (t <= g["giris"] < t + AYNI_TUR) or (
        g["giris"] < t and g["cikis"] is not None and t <= g["cikis"] < t + AYNI_TUR)


class Kasa:
    """Marj kapısı (execution.py:663) için DB'den bakiye TAHMİNİ. Kesin değil:
    funding/ücret sapmaları ve kayıt dışı para hareketleri görünmez."""

    def __init__(self, e0, kapanan, fiyatlar, cfg):
        self.e0 = e0
        self.kapanan = sorted(((g["cikis"], g["id"], g["pnl"]) for g in kapanan), key=lambda x: x[0])
        self.fiyatlar = fiyatlar            # coin → 1h kapanış serisi (index = KAPANIŞ anı)
        self.cfg = cfg

    def _fiyat(self, coin, t):
        c = self.fiyatlar.get(coin)
        if c is None or not len(c):
            return None
        i = int(c.index.searchsorted(t, side="right")) - 1
        return float(c.iloc[i]) if i >= 0 else None

    def gerekli_ve_serbest(self, a, acik):
        """Döner (gerekli marj, serbest×0.95) ya da None. `acik` = o anda marj kilitleyen
        pozisyonlar. Boyutlama risk.py ile aynı: miktar = min(özsermaye×risk/SL,
        özsermaye×CAP/fiyat) (risk.py:185-194, :64-67); sabit marj kipi (FIXED_MARGIN_USDT>0)."""
        if self.e0 is None or not a.get("fiyat") or not a.get("sl_mes"):
            return None
        r, lev = self.cfg.risk, max(int(self.cfg.exchange.leverage), 1)
        t = a["t"]
        acik_id = {g["id"] for g in acik}
        gercek = sum(p for c, i, p in self.kapanan if c <= t and i not in acik_id)
        kilit = sum(g["fiyat"] * g["miktar"] / lev for g in acik)
        kagit = 0.0
        for g in acik:
            px = self._fiyat(g["coin"], t)
            if px is not None:
                kagit += g["yon"] * (px - g["fiyat"]) * g["miktar"]
        ozs = self.e0 + gercek + kagit                   # execution.py:188 serbest+kilit+kağıt
        serbest = self.e0 + gercek - kilit               # PaperExchange: yalnız marj düşülür
        sabit = getattr(r, "fixed_margin_usdt", 0.0)
        if sabit > 0:
            gerekli = min(ozs, sabit)
        else:
            risk_pct = {"donchian": getattr(r, "donchian_risk_pct", r.max_risk_per_trade),
                        "squeeze": getattr(r, "squeeze_risk_pct", r.max_risk_per_trade)
                        }.get(a["kol"], r.max_risk_per_trade)
            miktar = min(ozs * risk_pct / a["sl_mes"],
                         ozs * getattr(r, "position_cap_fraction", 1.0) / a["fiyat"])
            gerekli = max(miktar, 0.0) * a["fiyat"] / lev
        return gerekli, serbest * 0.95


def karar(a, poz, soguma, cfg, tek_poz, simdi, kasa=None):
    """Açılmamış (filtreleri geçmiş) aday için execution.py:_execute_signal_guarded
    kapılarını KOD SIRASIYLA dener (402-521), sonra _execute_signal_inner'in marj
    kapısını (663) TAHMİNLE. Döner: hüküm metni."""
    r = cfg.risk
    t, sym, kol, yon = a["t"], a["sym"], a["kol"], a["yon"]
    # 1) halt (günlük zarar) — execution.py:402: ÇOĞALTILAMAZ (özsermaye gerekir)
    # 2) (kol:sembol) soğuması — execution.py:409-417
    if any(b <= t < e for b, e in soguma.get((kol, sym), [])):
        return "ardışık kayıp soğuması — BEKLENEN"
    kendi = [g for g in poz if g["symbol"] == sym]
    sert = [g for g in poz if _acik(g, t)]
    sert_id = {g["id"] for g in sert}
    gevsek = sert + [g for g in poz if _ayni_tur(g, t) and g["id"] not in sert_id]
    # 3) MAX_POSITIONS — execution.py:422-425 (portföy + uçuştaki)
    mp = r.max_positions
    if len(sert) >= mp:
        return f"koltuk dolu ({len(sert)}/{mp}) — BEKLENEN"
    if len(gevsek) >= mp:
        return f"koltuk dolu ({len(gevsek)}/{mp}, aynı kapanış turunda) — BEKLENEN"

    def _sayi(kosul):
        return sum(1 for g in sert if kosul(g)), sum(1 for g in gevsek if kosul(g))

    # 4) korelasyon tavanı — execution.py:431-449
    mc = getattr(r, "max_correlated_direction", 2)
    if mc > 0:
        for grp in KORELE_GRUPLAR:
            if sym in grp:
                n_s, n_g = _sayi(lambda g: g["symbol"] in grp and g["yon"] == yon)
                if n_s >= mc:
                    return f"korelasyon tavanı ({n_s}/{mc}) — BEKLENEN"
                if n_g >= mc:
                    return f"korelasyon tavanı ({n_g}/{mc}, aynı kapanış turunda) — BEKLENEN"
                break
    # 5) portföy stopu soğuması — execution.py:454-460: PORTFOY_STOP>0 ise ÇOĞALTILAMAZ
    # 6) kitap geneli aynı-yön — execution.py:469-481
    ma = getattr(r, "max_same_direction", 0)
    if ma > 0:
        n_s, n_g = _sayi(lambda g: g["yon"] == yon)
        if n_s >= ma:
            return f"aynı-yön kısıtı ({n_s}/{ma}) — BEKLENEN"
        if n_g >= ma:
            return f"aynı-yön kısıtı ({n_g}/{ma}, aynı kapanış turunda) — BEKLENEN"
    # 7) tek pozisyon/coin — execution.py:503-515
    if tek_poz:
        if any(_acik(g, t) for g in kendi):
            return "coin dolu — BEKLENEN"
        if any(g["giris"] < t and g["cikis"] is not None and t <= g["cikis"] < t + AYNI_TUR
               for g in kendi):
            return "coin dolu (aynı kapanışta kapanan pozisyon) — BEKLENEN"
        if any(g["kol"] != kol and t <= g["giris"] < t + AYNI_TUR for g in kendi):
            return "coin dolu (aynı turda başka kol) — BEKLENEN"
    # 8) slot dolu — execution.py:518-521
    if any(_acik(g, t) and g["kol"] == kol for g in kendi):
        return "slot dolu — BEKLENEN"
    # 9) serbest marj — execution.py:663 (Telegram'a 'Yetersiz bakiye' uyarısı da gider)
    if kasa is not None:
        m = kasa.gerekli_ve_serbest(a, gevsek)
        if m is not None and m[0] > m[1]:
            return f"yetersiz marj (tahmini: gerekli ~{m[0]:,.0f}$ > serbest×0.95 ~{m[1]:,.0f}$) — BEKLENEN"
    if simdi - t < ISLENIYOR:
        return "giriş işleniyor olabilir (<5 dk) — tekrar çalıştır"
    return "⛔ AÇIKLANAMADI"


def esle(adaylar, girisler):
    """DB girişlerini, KAPILARI GEÇMİŞ adaylarla BİRE-BİR eşler: giriş ∈ [t−1dk, t+90dk),
    birden çok aday uyarsa en GEÇ kapanışlı olan (bir sonraki kapanışın sinyali önceki
    sinyalin girişini 'çalamaz' ve tersi). Döner: eşleşmeyen girişler."""
    uygun = defaultdict(list)
    for a in adaylar:
        if a["filtre"] is None:
            uygun[(a["coin"], a["kol"])].append(a)
    eslesmeyen = []
    for g in sorted(girisler, key=lambda x: x["giris"]):
        adaylar_ = [a for a in uygun.get((g["coin"], g["kol"]), [])
                    if a["t"] - ERKEN_TOLERANS <= g["giris"] < a["t"] + GIRIS_TOLERANS
                    and a["giris"] is None]
        if adaylar_:
            a = max(adaylar_, key=lambda x: x["t"])
            a["giris"] = g
            a["karar"] = "AÇILDI"
        else:
            eslesmeyen.append(g)
    return eslesmeyen


# ───────────────────────── A) AYAR — ikiz referansı ──────────────────────────
def _ikiz_referansi():
    """ikiz/kos.py CANLI_ENV sözlüğünü KAYNAKTAN okur (import YOK — yan etkisiz)."""
    import ast
    p = Path(__file__).resolve().parent / "ikiz" / "kos.py"
    try:
        agac = ast.parse(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    for n in agac.body:
        if isinstance(n, ast.Assign) and any(getattr(x, "id", "") == "CANLI_ENV" for x in n.targets):
            try:
                return ast.literal_eval(n.value)
            except Exception:
                return None
    return None


def _ayar_karsilastir(cfg):
    ref = _ikiz_referansi()
    if not ref:
        return None
    s, r = cfg.strategy, cfg.risk
    coin = lambda lst: sorted(x.split("/")[0] for x in (lst or []))
    liste = lambda v: sorted(x.strip().upper() for x in v.split(",") if x.strip())
    bool_ = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")
    esle_ = {
        "DONCHIAN_SYMBOLS": (coin(s.donchian_symbols), liste),
        "SQUEEZE_SYMBOLS": (coin(s.squeeze_symbols), liste),
        "BB_SYMBOLS": (coin(s.bb_symbols), liste),
        "BB_WEEKDAY_ENABLED": (r.bb_weekday_enabled, bool_),
        "DONCHIAN_RR": (s.donchian_rr, float),
        "DONCHIAN_VOL_MULT": (s.donchian_vol_mult, float),
        "DONCHIAN_MTF": (s.donchian_mtf_enabled, bool_),
        "MAX_POSITIONS": (r.max_positions, int),
        "CONSECUTIVE_LOSS_LIMIT": (getattr(r, "consecutive_loss_limit", None), int),
        "COOLDOWN_MINUTES": (getattr(r, "cooldown_minutes", None), int),
        "VOL_FILTER_ENABLED": (s.vol_filter_enabled, bool_),
        "FUNDING_ENABLED": (s.funding_enabled, bool_),
        "MAX_HOLD_CANDLES": (r.max_hold_candles, int),
    }
    fark = []
    for k, (canli, cev) in esle_.items():
        if k in ref and canli != cev(ref[k]):
            fark.append((k, canli, ref[k]))
    return fark


def _modellenmeyen_kollar(cfg):
    s = cfg.strategy
    ad = [("ORB", s.orb_enabled), ("ASIA_BO", s.asia_bo_enabled), ("FVG", s.fvg_enabled),
          ("IFVG", s.ifvg_enabled), ("SR_BREAKOUT", s.sr_breakout_enabled),
          ("YAPI", s.yapi_enabled),
          ("WHALE(trade)", s.whale_enabled and getattr(s, "whale_mode", "monitor") == "trade")]
    return [a for a, acik in ad if acik]


# ───────────────────────────────── ana ───────────────────────────────────────
def _yon(y):
    return "LONG " if y == 1 else "SHORT"


def kontrol(gun=12, simdi=None, db=None, paper=False, veri=None, db_yok=False, cfg=None):
    simdi = _simdi(simdi)
    bas = simdi - pd.Timedelta(days=gun)
    cfg = cfg or load_config()
    s, r = cfg.strategy, cfg.risk
    kaynak = f"yerel veri ({veri}, çevrimdışı)" if veri else "MEXC vadeli (halka açık)"
    print(f"saglik_kaniti.py — son {gun} gün ({bas:%Y-%m-%d %H:%M} → {simdi:%Y-%m-%d %H:%M} UTC)"
          f" · veri: {kaynak}")

    # ── A) AYAR ──────────────────────────────────────────────────────────────
    print(f"\n{'='*84}\nA) CANLI AYAR — main.py'nin bu ortamda GERÇEKTEN kullanacağı değerler\n{'='*84}")
    harita = kollar(cfg)
    semb = [x.split("/")[0] for x in (cfg.exchange.symbols or [cfg.exchange.symbol])]
    dsym = [c for c, k in harita.items() if "donchian" in k]
    ssym = [c for c, k in harita.items() if "squeeze" in k]
    bsym = [c for c, k in harita.items() if "mean_rev" in k]
    dk = donchian_kwargs(cfg)
    sk = squeeze_kwargs(cfg)
    print(f"  SYMBOLS={semb}")
    print(f"  donchian açık={s.donchian_enabled} coinler={dsym}  (4h; giriş 4h bar KAPANIŞINDA)")
    print(f"    channel={dk['channel']} ema={dk['ema_trend']} sl_atr={dk['sl_atr']} RR={dk['rr']} "
          f"buffer={dk['buffer_atr']} VOL_MULT={dk['vol_mult']} vol_lookback={dk['vol_lookback']} "
          f"MTF={s.donchian_mtf_enabled}")
    print(f"    confirm={dk['confirm_bars']} retest={dk['retest_bars']} obv={dk['obv_confirm']} "
          f"adx_min={dk['adx_min']} govde={dk['govde_oran']} kapanis={dk['kapanis_konum']} "
          f"fitil={dk['fitil_oran']} chase={dk['chase_atr']} atr_gen={dk['atr_genisleme']} "
          f"mod={dk['mod']} ters_trend={dk['ters_trend']}")
    print(f"  squeeze  açık={s.squeeze_enabled} coinler={ssym}  (1h)")
    print(f"    kc={sk['kc_mult']} min_bar={sk['min_squeeze_bars']} sl_atr={sk['sl_atr']} RR={sk['rr']} "
          f"4h_MTF={sk['mtf_filter']} vol_mult={sk['vol_mult']} mod={sk['mod']}")
    print(f"    rejim kapısı: ADX(1h,{s.adx_period}) ≤ {r.adx_ranging_threshold:g} → squeeze KAPALI "
          f"(REGIME_FILTER={r.regime_filter_enabled})")
    print(f"  BB       coinler={bsym}  (1h) BB_WEEKDAY_ENABLED={r.bb_weekday_enabled} "
          f"(hafta sonu = mum KAPANIŞ saati UTC Cmt/Paz)")
    print(f"    VOL_FILTER={s.vol_filter_enabled} (hacim ≥ 20 bar ort.)  sniper_min_grade={s.sniper_min_grade}"
          f"  rejim kapısı: ADX ≥ {r.adx_trending_threshold:g} → BB KAPALI")
    print(f"    FUNDING_ENABLED={s.funding_enabled} (mod={s.funding_mode})  "
          f"ORDERFLOW={getattr(s, 'orderflow_enabled', False)} (mod={getattr(s, 'orderflow_mode', '?')}, "
          f"yalnız log — karar dışı)")
    _ops = getattr(r, "one_per_symbol", "auto")
    tek_poz = _ops == "true" or (_ops == "auto" and not paper)
    print(f"  risk: MAX_POSITIONS={r.max_positions}  "
          f"CONSEC_LOSS={getattr(r, 'consecutive_loss_limit', '?')}  "
          f"COOLDOWN={getattr(r, 'cooldown_minutes', '?')}dk  "
          f"MAX_CORR_DIR={getattr(r, 'max_correlated_direction', '?')}  "
          f"MAX_SAME_DIR={getattr(r, 'max_same_direction', 0)}  "
          f"ONE_PER_SYMBOL={_ops}→{'uygulanıyor' if tek_poz else 'YOK'}  "
          f"MAX_HOLD={r.max_hold_candles}h (donchian 120h)")
    for kol_ad, liste in (("DONCHIAN", s.donchian_symbols), ("SQUEEZE", s.squeeze_symbols),
                          ("BB", s.bb_symbols)):
        disari = [x.split("/")[0] for x in (liste or [])
                  if x not in (cfg.exchange.symbols or [cfg.exchange.symbol])]
        if disari:
            print(f"  ⚠ {kol_ad}_SYMBOLS içinde SYMBOLS'ta OLMAYAN coin: {disari} — canlı onları HİÇ taramaz")
    fark = _ayar_karsilastir(cfg)
    if fark is None:
        print("  (ikiz referansı ikiz/kos.py CANLI_ENV okunamadı — karşılaştırma yok)")
    elif fark:
        for k, g, b in fark:
            print(f"  ⚠ FARK: {k} canlı={g} ikiz_referansı={b}  → ikiz eşikleri bu ayarda GEÇERSİZ olabilir")
    else:
        print("  ✓ ayarlar ikiz referansıyla (ikiz/kos.py CANLI_ENV) aynı")
    mk = _modellenmeyen_kollar(cfg)
    if mk:
        print(f"  ⚠ MODELLENMEYEN kol AÇIK: {mk} — bu araç onların sinyallerini SAYMIYOR")
    if s.funding_enabled and s.funding_mode == "filter":
        print("  ⚠ FUNDING filtre modunda: BB sinyalini canlı funding eleyebilir — MODELLENMİYOR")

    # ── B) VERİ TAZELİĞİ ─────────────────────────────────────────────────────
    print(f"\n{'='*84}\nB) VERİ TAZELİĞİ (bayat veri = sessizce kör bot)\n{'='*84}")
    coinler = list(harita.keys())
    veri_, eksik_veri = {}, []
    for c in coinler:
        try:
            m = (yerel_oku(c, veri, simdi, gun + ISITMA_GUN) if veri
                 else cek(c, gun=gun + ISITMA_GUN, simdi=simdi))
            if not len(m):
                raise RuntimeError("kapanmış mum yok")
            # canlı tampon: 4h'te 260 bar (≈43.3 gün), 1h'te 120 bar (5 gün). Geçmiş kısaysa
            # Donchian HİÇ sinyal üretemez (dch_min=200) → "sinyal yok" YALAN olur.
            derin = pd.Timedelta(days=44) if "donchian" in harita[c] else pd.Timedelta(days=5.5)
            if m.index[0] > bas - derin:
                raise RuntimeError(f"geçmiş yetersiz: ilk mum {m.index[0]:%Y-%m-%d %H:%M}, "
                                   f"gereken ≤ {bas - derin:%Y-%m-%d %H:%M} (canlı tampon derinliği)")
        except Exception as e:
            print(f"  {c:<5s} ⛔ VERİ ALINAMADI: {type(e).__name__}: {e} — bu coin için HÜKÜM YOK, devam")
            eksik_veri.append(c)
            continue
        veri_[c] = m
        son_kap = m.index[-1] + SAAT
        yas = (simdi - son_kap).total_seconds() / 3600.0
        bayrak = "✓" if yas < 2 else "⚠ BAYAT"
        print(f"  {c:<5s} son KAPANMIŞ 1h mum {m.index[-1]:%Y-%m-%d %H:%M} (kapanış {son_kap:%H:%M})"
              f"  yaş {yas:5.2f} saat  {bayrak}", flush=True)
    if eksik_veri:
        print(f"\n  ⛔ {eksik_veri} için veri yok. 'Sinyal yok' ile 'bakamadık' KARIŞMASIN diye bu")
        print("     coinler SAYILMIYOR ve HÜKÜM 'SAĞLAM' demez. Diğer coinlerle devam ediliyor.")
        print("       pip3 install ccxt        # modül yoksa")
        print("       (ağ/borsa erişimi VPS'te olmalı — PC'de MEXC engelli olabilir)")

    if not veri_:
        hukum = "⛔ HÜKÜM YOK — hiçbir coin için veri alınamadı (ağ/ccxt/--veri klasörünü kontrol et)"
        print(f"\n{'='*84}\nHÜKÜM\n{'='*84}\n  HÜKÜM: {hukum}")
        return {"adaylar": [], "pencere": [], "girisler": [], "eslesmeyen": [],
                "eksik_veri": eksik_veri, "hukum": hukum, "db_yok": db_yok, "bas": bas,
                "simdi": simdi, "veri_var": False}

    # ── C) SİNYAL ────────────────────────────────────────────────────────────
    print(f"\n{'='*84}\nC) SİNYAL YENİDEN HESABI (üretim sınıfları + canlı kapılar; loga güvenilmedi)\n"
          f"   sinyal zamanı = bar KAPANIŞI (UTC) · beklenen giriş [kapanış, kapanış+90dk)\n{'='*84}")
    st = stratejiler(cfg)
    tarama_bas = bas - GIRIS_TOLERANS - SAAT         # pencere başındaki girişi eşleyebilmek için
    adaylar = []
    for c, m in veri_.items():
        adaylar += adaylar_coin(c, m, cfg, harita[c], tarama_bas, st)
    adaylar.sort(key=lambda a: (a["t"], a["coin"]))

    # ── D) SAYIM ─────────────────────────────────────────────────────────────
    db_yolu = db or cfg.db_path
    poz, kap, db_notu = None, None, None
    if not db_yok:
        if not os.path.exists(db_yolu):
            db_notu = (f"⚠ trades.db bulunamadı ({db_yolu}) → --db-yok kipine düşüldü: "
                       "girişlerle eşleştirme YOK, yalnız 'filtreleri geçti' listesi.")
            db_yok = True
        else:
            try:
                poz, kap, e0 = defter(db_yolu, bas, simdi, paper)
            except Exception as e:
                db_notu = (f"⚠ trades.db okunamadı ({db_yolu}: {type(e).__name__}: {e}) → "
                           "--db-yok kipine düşüldü.")
                db_yok = True
    girisler, eslesmeyen = [], []
    if not db_yok:
        girisler = [g for g in poz if tarama_bas <= g["giris"] <= simdi
                    and g["kol"] in KOL_SIRA]
        baska_kol = [g for g in poz if bas <= g["giris"] <= simdi and g["kol"] not in KOL_SIRA]
        if baska_kol:
            db_notu = ((db_notu + " ") if db_notu else "") + (
                f"ⓘ modellenmeyen kollardan {len(baska_kol)} giriş var "
                f"({sorted({g['kol'] for g in baska_kol})}) — eşleştirmeye katılmadı.")
        eslesmeyen = esle(adaylar, girisler)
        eslesmeyen = [g for g in eslesmeyen if g["giris"] >= bas]
        soguma = soguma_listesi(kap, getattr(r, "consecutive_loss_limit", 2),
                                getattr(r, "cooldown_minutes", 240))
        kasa = Kasa(e0, kap, {c: pd.Series(m["close"].values, index=m.index + SAAT)
                              for c, m in veri_.items()}, cfg)
    for a in adaylar:
        if a["filtre"] is not None:
            a["karar"] = a["filtre"]
        elif a["karar"] is None:
            a["karar"] = ("filtreleri geçti — DB yok, VPS'te eşleştir" if db_yok
                          else karar(a, poz, soguma, cfg, tek_poz, simdi, kasa))
    pencere = [a for a in adaylar if a["t"] >= bas]
    if db_notu:
        print(f"  {db_notu}")
    print(f"  {'kapanış UTC':<12s} {'coin':<5s} {'kol':<8s} {'yön':<5s} {'ölçü':<11s}  hüküm")
    for a in pencere:
        print(f"  {a['t']:%m-%d %H:%M}  {a['coin']:<5s} {KOL_AD[a['kol']]:<8s} {_yon(a['yon'])} "
              f"{a['metrik']:<11s}  {a['karar']}")
    if not pencere:
        print("  (hiç aday yok — ne sinyal ne de filtrelenmiş ham kırılım oluştu)")
    if eksik_veri:
        print(f"  ⛔ {eksik_veri} verisiz — bu coinlerin adayları BİLİNMİYOR (yukarıdaki liste eksik)")

    # özet: kol başına
    def _anahtar(k):
        return k.split(" (")[0].split(" —")[0]
    ozet = {kl: Counter(_anahtar(a["karar"]) for a in pencere if a["kol"] == kl) for kl in KOL_SIRA}
    print(f"\n  ÖZET (kol başına, son {gun} gün):")
    for kl in KOL_SIRA:
        cs = [c for c, k in harita.items() if kl in k and c in veri_]
        if not cs and not ozet[kl]:
            continue
        metin = ", ".join(f"{k}: {n}" for k, n in sorted(ozet[kl].items(), key=lambda x: -x[1]))
        print(f"    {KOL_AD[kl]:<8s} {cs}  →  {metin or 'aday yok'}")
    # Donchian KANIT: hacim filtresinin elediği ham kırılımlar
    ham = [a for a in pencere if a["kol"] == "donchian" and a["ic"]]
    if ham or dsym:
        print(f"\n  KANIT — Donchian ham kırılımlar (VOL_MULT=0 ile oluşan) ve hacim filtresi "
              f"(eşik {dk['vol_mult']:g}×, önceki {dk['vol_lookback']} bar ort.):")
        gecen = [a for a in pencere if a["kol"] == "donchian" and not a["ic"]]
        for c in dsym:
            e = [a for a in ham if a["coin"] == c]
            g_ = [a for a in gecen if a["coin"] == c]
            if c not in veri_:
                print(f"    {c:<5s} ⛔ veri yok — BAKILAMADI")
                continue
            if not e and not g_:
                print(f"    {c:<5s} ham kırılım yok")
                continue
            print(f"    {c:<5s} elenen {len(e)}: "
                  + (" ".join(f"{a['t']:%m-%d %H}h {a['olcu']:.2f}×" for a in e) or "-")
                  + (f" | eşiği geçen {len(g_)}: " + " ".join(f"{a['olcu']:.2f}×" for a in g_)
                     if g_ else ""))

    # ── D) defter çıktısı ─────────────────────────────────────────────────────
    print(f"\n{'='*84}\nD) GERÇEK GİRİŞLER · AÇIK POZİSYONLAR · SESSİZLİK\n{'='*84}")
    asim, sessiz_gun, son_kol = [], None, {}
    if db_yok:
        print("  DB yok → gerçek girişlerle eşleştirme ve sessizlik ölçümü YAPILAMADI.")
        print("  'filtreleri geçti' yazan her satır canlıda ya AÇILMIŞ ya da koltuk/coin/soğuma")
        print("  kilidine takılmış olmalı. Hangisi olduğunu yalnız trades.db söyler: VPS'te")
        print("  'python3 saglik_kaniti.py <gün>' ile eşleştir. HİÇ satır yoksa sessizlik = sinyal yokluğu.")
    else:
        tur = "paper" if paper else "GERÇEK"
        pg = [g for g in girisler if g["giris"] >= bas]
        print(f"  trades.db ({db_yolu}): son {gun} günde {len(pg)} {tur} giriş")
        for g in pg:
            print(f"    {g['giris']:%m-%d %H:%M}  {g['coin']:<5s} {KOL_AD.get(g['kol'], g['kol']):<8s} "
                  f"{g['side']:<5s} {'AÇIK' if g['cikis'] is None else g['neden']}")
        if eslesmeyen:
            print(f"\n  ⚠ YENİDEN HESAPTA KARŞILIĞI OLMAYAN {len(eslesmeyen)} giriş (replay ≠ canlı):")
            for g in eslesmeyen:
                yakin = [a for a in adaylar if a["coin"] == g["coin"] and a["kol"] == g["kol"]
                         and a["t"] <= g["giris"] < a["t"] + GIRIS_TOLERANS]
                ek = f"  (o barda araç: {yakin[-1]['karar']})" if yakin else "  (o barda aday YOK)"
                print(f"    {g['giris']:%m-%d %H:%M} {g['coin']:<5s} {KOL_AD.get(g['kol'], g['kol'])}{ek}")

        print(f"\n  --- AÇIK POZİSYONLAR (max_hold aşımı = GERÇEK arıza) ---")
        acik = [g for g in poz if g["cikis"] is None]
        if not acik:
            print("    yok")
        for g in acik:
            yas = (simdi - g["giris"]).total_seconds() / 3600.0
            limit = float(g["max_hold"] or r.max_hold_candles)       # main.py:1331
            asti = yas > limit + MAX_HOLD_PAYI
            if asti:
                asim.append(g)
            print(f"    {g['coin']:<5s} {KOL_AD.get(g['kol'], g['kol']):<8s} {g['side']:<5s} "
                  f"yaş {yas:6.1f}s / limit {limit:.0f}s  "
                  f"{'⛔ MAX_HOLD AŞILMIŞ — kapanmalıydı!' if asti else '✓'}")

        print(f"\n  --- SON GİRİŞ / SESSİZLİK (ikiz 3.3 yıl: 4-5 gün olağan, p99 6.2, en uzun 7.7 gün) ---")
        tum = {g["id"]: g for g in kap}
        tum.update({g["id"]: g for g in poz})
        for g in tum.values():
            if g["giris"] <= simdi and g["kol"] in KOL_SIRA:
                if g["kol"] not in son_kol or g["giris"] > son_kol[g["kol"]]:
                    son_kol[g["kol"]] = g["giris"]
        for kl in KOL_SIRA:
            if kl in son_kol:
                gg = (simdi - son_kol[kl]).total_seconds() / 86400
                print(f"    {KOL_AD[kl]:<8s} son giriş {son_kol[kl]:%Y-%m-%d %H:%M}  ({gg:4.1f} gün önce)")
            else:
                print(f"    {KOL_AD[kl]:<8s} kayıtlı giriş yok")
        if son_kol:
            sessiz_gun = (simdi - max(son_kol.values())).total_seconds() / 86400
            if sessiz_gun >= SESSIZ_ARIZA:
                sd = "⛔ ARIZA VARSAY (ikizde 3.3 yılda en uzun 7.7 gün)"
            elif sessiz_gun >= SESSIZ_KONTROL:
                sd = "⚠ KONTROL ET (ikiz p99 6.2 gün)"
            else:
                sd = "✓ normal aralık (ikizde 4-5 gün sessizlik olağan)"
            print(f"    TÜM KOLLAR: sessizlik {sessiz_gun:.1f} gün → {sd}")

    # ── HÜKÜM ────────────────────────────────────────────────────────────────
    print(f"\n{'='*84}\nHÜKÜM\n{'='*84}")
    eksik = [a for a in pencere if a["karar"].startswith("⛔")]
    gecti = [a for a in pencere if a["filtre"] is None]
    acildi = [a for a in pencere if a["karar"] == "AÇILDI"]
    isleniyor = [a for a in pencere if a["karar"].startswith("giriş işleniyor")]
    bayat = [c for c, m in veri_.items()
             if (simdi - (m.index[-1] + SAAT)).total_seconds() / 3600 >= 2]
    sorun = []
    if eksik_veri:
        # ⚠ veri yoksa "sinyal yok" ile "bakamadık" ayırt EDİLEMEZ → o coin(ler) için SAĞLAM denmez
        sorun.append(f"veri alınamadı {eksik_veri} (o coinler için sayım YOK)")
    if eksik:
        sorun.append(f"{len(eksik)} sinyal AÇIKLANAMADI")
    if eslesmeyen:
        sorun.append(f"{len(eslesmeyen)} giriş yeniden hesapta yok")
    if bayat:
        sorun.append(f"veri bayat {bayat}")
    if asim:
        sorun.append(f"max_hold aşımı {[g['coin'] for g in asim]}")
    if sessiz_gun is not None and sessiz_gun >= SESSIZ_ARIZA:
        sorun.append(f"sessizlik {sessiz_gun:.1f} gün ≥ {SESSIZ_ARIZA:g}")
    if sorun:
        hukum = f"⛔ İNCELE — {'; '.join(sorun)}"
    elif db_yok:
        hukum = (f"ⓘ DB YOK — filtreleri geçen {len(gecti)} sinyal var"
                 + (" (liste C bölümünde; VPS'te trades.db ile eşleştir)" if gecti
                    else "; sessizlik tamamen sinyal yokluğu/filtre, arıza DEĞİL"))
    elif not gecti:
        hukum = (f"✓ SAĞLAM — son {gun} günde TÜM kapıları geçen sinyal YOK; sessizlik filtre/"
                 f"sinyal yokluğu, arıza DEĞİL")
    else:
        kilit = len(gecti) - len(acildi) - len(isleniyor)
        hukum = (f"✓ SAĞLAM — kapıları geçen {len(gecti)} sinyal: {len(acildi)} AÇILDI, {kilit} "
                 f"beklenen kilit (koltuk/coin/soğuma)"
                 + (f", {len(isleniyor)} işleniyor (tekrar çalıştır)" if isleniyor else "")
                 + "; kayıp sinyal YOK")
    if sessiz_gun is not None:
        hukum += f" · sessizlik {sessiz_gun:.1f} gün"
    print(f"  HÜKÜM: {hukum}")
    if sessiz_gun is not None and SESSIZ_KONTROL <= sessiz_gun < SESSIZ_ARIZA:
        print(f"  ⚠ sessizlik {sessiz_gun:.1f} gün — ikiz p99'un üstünde; sayım temizse bile izle.")
    if eksik:
        print(f"  ⛔ {len(eksik)} sinyal açıklanamadı. Elenen ihtimaller: kol kapıları, coin/slot kilidi,")
        print("     MAX_POSITIONS, korelasyon, (kol:coin) soğuması. Kalan (MODELLENMEYEN) ihtimaller:")
        print("     günlük zarar halt'ı, yetersiz marj/kurulum hatası, emir hatası, bayat besleme,")
        print("     elle duraklatma, bot kapalı. Bu barlar için journalctl'e BAKILMALI:")
        for a in eksik:
            print(f"       {a['t']:%m-%d %H:%M} {a['coin']} {KOL_AD[a['kol']]}  →  "
                  f"journalctl -u btc-bot --since '{a['t'] - pd.Timedelta(minutes=5):%Y-%m-%d %H:%M}' "
                  f"--until '{a['t'] + GIRIS_TOLERANS:%Y-%m-%d %H:%M}' | grep -i {a['coin']}")
    print("  MODELLENMEYEN (çevrimdışı çoğaltılamaz, aday '⛔' ise akla gelmeli): günlük zarar halt'ı")
    print("    (execution.py:402/582), bayat besleme koruması (main.py:250), Donchian 4h tampon bayatlığı")
    print("    (main.py:791), yetersiz marj/kurulum/emir hatası ve maker dolumu (execution.py:653-736),")
    print("    restart'ta sıfırlanan soğuma sayacı (burada ÜST SINIR), orderflow (yalnız log),")
    print("    funding filtresi (FUNDING_ENABLED=false iken kapalı), portföy stopu (PORTFOY_STOP=0 iken kapalı).")
    return {"adaylar": adaylar, "pencere": pencere, "girisler": girisler, "eslesmeyen": eslesmeyen,
            "eksik_veri": eksik_veri, "hukum": hukum, "db_yok": db_yok, "bas": bas, "simdi": simdi,
            "veri_var": bool(veri_)}


# ───────────────────────────────── öz-test ───────────────────────────────────
def _ankor_parametreleri():
    """deployed_backtest.gen'in strateji kurulumunu KAYNAĞINDAN okur (ast; elle kopya YOK).
    Ankor değerlerini değiştirirse öz-test onları KENDİLİĞİNDEN izler."""
    import ast
    import inspect
    import textwrap
    import deployed_backtest as DBT
    agac = ast.parse(textwrap.dedent(inspect.getsource(DBT.gen)))
    out = {}
    for n in ast.walk(agac):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in ("DonchianStrategy", "SqueezeStrategy"):
            out[n.func.id] = {k.arg: ast.literal_eval(k.value) for k in n.keywords}
    if set(out) != {"DonchianStrategy", "SqueezeStrategy"}:
        raise SystemExit("⛔ deployed_backtest.gen içinde strateji kurulumu bulunamadı — öz-test kurulamıyor")
    return out


def _varsayilanlar(sinif) -> dict:
    import inspect
    return {k: p.default for k, p in inspect.signature(sinif.__init__).parameters.items()
            if p.default is not inspect.Parameter.empty}


def dogrula():
    """ÖZ-TEST: bu aracın yeniden hesap MOTORU ankorla aynı sinyalleri üretiyor mu?

    Ankor (deployed_backtest.gen / gen_bb) occ uyguladığı için ALT KÜME; dolayısıyla
    ankorun ürettiği HER giriş bu aracın 'kapıları geçti' listesinde OLMALI. Ankor
    parametreleri (hacim filtresi YOK, RR 2.0) canlıdan FARKLI — bu test PARAMETREYİ değil
    MOTORU (pencere, bar hizası, MTF, rejim, hafta sonu kapısı) sınar; parametreler
    deployed_backtest.py kaynağından okunur.

    Bilinen İKİ motor farkı (canlı-birebir olan BU araçtır), eksik SAYILMAZ, ayrı raporlanır:
      • squeeze ADX: ankor TAM seriden, canlı 120 barlık pencereden (main.py:191,230)
      • BB hafta sonu: ankor bar AÇILIŞINA, canlı KAPANIŞ anına bakar (main.py:274)
    Çevrimdışı: data/*.csv SALT-OKUNUR (fast_bt.load çağrılmaz)."""
    import copy
    import deployed_backtest as DBT
    from strategies.donchian import DonchianStrategy
    from strategies.squeeze import SqueezeStrategy
    cfg = copy.deepcopy(load_config())
    cfg.risk.bb_weekday_enabled = False           # ankor gen_bb: YALNIZ hafta sonu (deployed_backtest.py:142)
    cfg.risk.regime_filter_enabled = True
    ank = _ankor_parametreleri()
    dc_kw = {**_varsayilanlar(DonchianStrategy), **ank["DonchianStrategy"]}
    sq_kw = {**_varsayilanlar(SqueezeStrategy), **ank["SqueezeStrategy"]}
    st = stratejiler(cfg, dc_kw, sq_kw)
    klasor = str(Path(__file__).resolve().parent / "data")
    print("ÖZ-TEST: yeniden hesap motoru ankorla örtüşüyor mu? (çevrimdışı, data/ salt-okunur)")
    print(f"  ankor Donchian: {ank['DonchianStrategy']}  (MTF hep açık)")
    print(f"  ankor Squeeze : {ank['SqueezeStrategy']}  (ADX ≤ {cfg.risk.adx_ranging_threshold:g} kapısı)")
    print(f"  ankor BB      : canlı MeanReversionStrategy, hafta sonu, ADX < {DBT.BB_ADX_MAX:g}\n")
    toplam_a = toplam_e = toplam_b = 0

    def _rapor(c, ank_t, ben, bilinen):
        nonlocal toplam_a, toplam_e, toplam_b
        eksik = [t for t in ank_t if t not in ben]
        acik_ = [t for t in eksik if bilinen(t)]
        eksik = [t for t in eksik if t not in acik_]
        toplam_a += len(ank_t); toplam_e += len(eksik); toplam_b += len(acik_)
        durum = "✓" if not eksik else f"⛔ {len(eksik)} EKSİK"
        ek = f"  (+{len(acik_)} bilinen motor farkı)" if acik_ else ""
        print(f"  {c:<5s} ankor {len(ank_t):>3d} giriş | aracın kapıyı geçen adayı {len(ben):>3d}  {durum}{ek}")
        for t in eksik:
            print(f"        EKSİK: kapanış {t}")
        for t in acik_:
            print(f"        bilinen fark: kapanış {t}")

    for c in DBT.DONCH:
        m = _yerel_ham(c, klasor)
        d4 = resample(m, "4h")
        bas, son = d4.index[-400], d4.index[-2]                  # ≈66 gün; DB.gen son barı üretmez
        ank_t = [pd.Timestamp(t[0], tz="UTC") + DORT_SAAT for t in DBT.gen("donchian", m)]
        ank_t = [t for t in ank_t if bas + DORT_SAAT <= t <= son + DORT_SAAT]
        mm = yerel_oku(c, klasor)
        ben = {a["t"] for a in adaylar_coin(c, mm, cfg, ["donchian"], bas + DORT_SAAT, st, mtf_aktif=True)
               if a["filtre"] is None}
        _rapor(c, ank_t, ben, lambda t: False)
    print()
    for c in DBT.SQZ:
        m = _yerel_ham(c, klasor)
        d1 = resample(m, "1h")
        bas, son = d1.index[-1600], d1.index[-2]                 # ≈66 gün, 1h kolda
        ank_t = [pd.Timestamp(t[0], tz="UTC") + SAAT for t in DBT.gen("squeeze", m)]
        ank_t = [t for t in ank_t if bas + SAAT <= t <= son + SAAT]
        mm = yerel_oku(c, klasor)
        ben = {a["t"] for a in adaylar_coin(c, mm, cfg, ["squeeze"], bas + SAAT, st)
               if a["filtre"] is None}
        adx_tam = pd.Series(adx_fn(d1["high"], d1["low"], d1["close"], cfg.strategy.adx_period).values,
                            index=d1.index + SAAT)

        def _adx_farki(t, adx_tam=adx_tam, mm=mm):
            # ankor tam-seri ADX eşiği geçiyor, canlı 120-bar pencere ADX'i geçmiyor mu?
            j = mm.index.get_loc(t - SAAT)
            df = mm.iloc[max(0, j - 119):j + 1]
            x = adx_fn(df["high"], df["low"], df["close"], cfg.strategy.adx_period).iloc[-1]
            x = float(x) if np.isfinite(x) else 20.0
            return adx_tam.get(t, np.nan) > cfg.risk.adx_ranging_threshold >= x
        _rapor(c, ank_t, ben, _adx_farki)
    print()
    for c in DBT.BB_COINS:
        m = _yerel_ham(c, klasor)
        d1 = resample(m, "1h")
        bas, son = d1.index[-1600], d1.index[-2]
        ank_t = [pd.Timestamp(t[0], tz="UTC") + SAAT for t in DBT.gen_bb(m)]
        ank_t = [t for t in ank_t if bas + SAAT <= t <= son + SAAT]
        mm = yerel_oku(c, klasor)
        ben = {a["t"] for a in adaylar_coin(c, mm, cfg, ["mean_rev"], bas + SAAT, st)
               if a["filtre"] is None}
        # ankor açılış hafta sonu, kapanış Pazartesi 00:00 → canlı hafta İÇİ sayar
        _rapor(c, ank_t, ben, lambda t: (t - SAAT).weekday() >= 5 and t.weekday() < 5)

    print(f"\n  ankor girişi {toplam_a}, araçta bulunamayan {toplam_e}, bilinen motor farkı {toplam_b}")
    if toplam_e == 0:
        print("  ✓ ÖZ-TEST GEÇTİ — araç ankorun ürettiği her girişi (bilinen farklar dışında) yakalıyor.")
        print("    (Aday sayısı daha büyük: occ uygulanmıyor, bu BEKLENEN.)")
    else:
        raise SystemExit("  ⛔ ÖZ-TEST KALDI — bu araçla hüküm verilemez.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Son N günde oluşması gereken sinyalleri canlı kapılarla yeniden hesaplar ve "
                    "trades.db'deki girişlerle SAYAR (salt-okur).")
    ap.add_argument("gun", nargs="?", type=int, default=12, help="geriye bakılacak gün (varsayılan 12)")
    ap.add_argument("--dogrula", action="store_true", help="öz-test (çevrimdışı, ankora karşı)")
    ap.add_argument("--db", help="trades.db yolu (varsayılan: config DB_PATH)")
    ap.add_argument("--paper", action="store_true", help="is_paper=1 satırlarını say (ikiz/paper DB)")
    ap.add_argument("--simdi", help="'şimdi' yerine bu ISO an (UTC) — geçmiş pencere denetimi")
    ap.add_argument("--veri", help="MEXC yerine bu klasördeki {COIN}_fut_1h.csv (salt-okunur)")
    ap.add_argument("--db-yok", action="store_true",
                    help="DB eşleştirmesi yapma; filtreleri geçenleri listele (GitHub Actions)")
    a = ap.parse_args(argv)
    if a.dogrula:
        return dogrula()
    return kontrol(a.gun, simdi=a.simdi, db=a.db, paper=a.paper, veri=a.veri, db_yok=a.db_yok)


if __name__ == "__main__":
    _s = main()
    # eski DURDURULDU davranışı: hiç veri yoksa çıkış kodu 2 (CI/cron "bakamadık"ı görsün)
    sys.exit(2 if isinstance(_s, dict) and not _s.get("veri_var", True) else 0)
