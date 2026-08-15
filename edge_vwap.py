"""
edge_vwap.py — STRATEJİ 2: VWAP MEAN REVERSION (baseline, filtresiz).

BRIEF'İN ZORUNLU KURALLARI → NEREDE:
  "fiyat VWAP'tan anlamlı uzaklaşmalı"        → sapma / ATR >= vwap_atr_min
  "15M rejim GÜÇLÜ TREND OLMAMALI"            → setup diliminde EMA-mesafesi kapısı
  "aşırı uzama bölgesine girmeli"             → aynı eşik, ATR ile normalize
  "5M'de rejection / momentum zayıflaması"    → ZORUNLU rejection mumu şartı
  "sadece uzaklaştı diye açma"                → rejection olmadan sinyal YOK
  "hedef VWAP veya çevresi"                   → TP = VWAP
  "stop YAPISAL invalidation'da"              → uzama ucunun ötesi + ATR tamponu
  "1M yalnız entry timing"                    → kapalı (gecikme_olc: değeri ~0)

VWAP ÇAPASI: UTC GÜNLÜK. Kripto 7/24 olduğu için "seans" yok; günlük çapa
standart ve tekrarlanabilir. Kümülatif toplam yalnız GÜN İÇİNDE ve YALNIZ GEÇMİŞE
bakar → look-ahead yok. (Tüm veriye tek VWAP hesaplamak klasik bir sızıntıdır:
günün sonundaki hacim, günün başındaki kararı etkilerdi.)

⚠ ÖN-KAYIT: parametreler VERİYE BAKILMADAN yazıldı.
⚠ Opsiyonel filtreler (ATR deviation, BB deviation, 15M trend strength, hacim
  tükenmesi, 5M rejection mum tipi, VWAP EĞİMİ) BU DOSYADA YOK — B aşamasında.
  Brief özellikle VWAP eğiminin range/trend ayrımına katkısını soruyor; o ölçüm
  baseline çıktıktan SONRA yapılacak ki katkısı izole görülebilsin.

Kullanım:  python3 edge_vwap.py            |  python3 edge_vwap.py SOL ETH
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import edge_lab as EL
from edge_lab import Cfg, Sinyal


def varsayilan_cfg() -> Cfg:
    c = Cfg(
        tf_base="5m", tf_setup="15m", tf_regime="1h", tf_timing=None,
        swing_k=3, swing_lookback=40, atr_period=14,
        sl_atr=0.5, rr_min=1.5, max_hold_bar=96,
    )
    c.ekstra = dict(
        vwap_atr_min=2.0,      # VWAP'tan en az bu kadar ATR uzak
        uzama_bar=12,          # son 12×5dk=1s içinde uç noktayı yapmış olmalı
        rejection_govde=0.35,  # kapanışın bar aralığındaki konumu (geri dönüş payı)
        trend_ema=50,          # 15dk EMA
        trend_guc_atr=2.5,     # fiyat EMA'dan bu kadar ATR uzaksa GÜÇLÜ TREND → ELE
        tp_vwap_pay=0.0,       # TP'yi VWAP'ın bu kadar berisine koy (0 = tam VWAP)
    )
    return c


def _gunluk_vwap(df: pd.DataFrame) -> np.ndarray:
    """UTC gün içi kümülatif VWAP. YALNIZ geçmişe bakar; gün değişince sıfırlanır."""
    tp = (df["high"].values + df["low"].values + df["close"].values) / 3.0
    v = df["volume"].values
    gun = df.index.normalize()
    yeni = np.empty(len(df), dtype=bool)
    yeni[0] = True
    yeni[1:] = gun.values[1:] != gun.values[:-1]
    grup = np.cumsum(yeni) - 1
    pv = tp * v
    # grup bazlı kümülatif toplam (bar i DAHİL — o bar kapanmıştır, meşru)
    cpv = np.zeros(len(df)); cv = np.zeros(len(df))
    a = b = 0.0
    for i in range(len(df)):
        if yeni[i]:
            a = b = 0.0
        a += pv[i]; b += v[i]
        cpv[i] = a; cv[i] = b
    return np.where(cv > 0, cpv / np.maximum(cv, 1e-12), df["close"].values)


def _hazirla(veri: dict, cfg: Cfg) -> None:
    b = veri["base"]
    veri["vwap"] = _gunluk_vwap(b)
    veri["b_atr"] = EL.atr(b["high"].values, b["low"].values,
                           b["close"].values, cfg.atr_period)
    su = veri["setup"]
    veri["s_ema"] = su["close"].ewm(span=cfg.ekstra["trend_ema"],
                                    adjust=False).mean().values
    veri["s_atr"] = EL.atr(su["high"].values, su["low"].values,
                           su["close"].values, cfg.atr_period)


def strateji(i: int, veri: dict, cfg: Cfg, ctx: dict):
    if "hazir" not in ctx:
        _hazirla(veri, cfg); ctx["hazir"] = True
    E = cfg.ekstra
    b = veri["base"]
    op = b["open"].values; hi = b["high"].values
    lo = b["low"].values; cl = b["close"].values
    sp = veri["setup_pos"][i]
    if sp < 0:
        return None
    a = veri["b_atr"][i]
    vw = veri["vwap"][i]
    if not np.isfinite(a) or a <= 0 or not np.isfinite(vw):
        return None

    # ── ZORUNLU: GÜÇLÜ TREND'de mean-reversion YOK ──
    sc = veri["setup"]["close"].values[sp]
    sema = veri["s_ema"][sp]; satr = veri["s_atr"][sp]
    if not np.isfinite(satr) or satr <= 0:
        return None
    if abs(sc - sema) > E["trend_guc_atr"] * satr:
        return None

    sapma = (cl[i] - vw) / a          # + = VWAP'ın üstünde
    if abs(sapma) < E["vwap_atr_min"]:
        return None
    yon = 1 if sapma < 0 else -1      # aşağıdaysa LONG (VWAP'a dönüş)

    # ── ZORUNLU: UZAMA gerçekten TAZE olmalı (son uzama_bar içinde uç yapılmış) ──
    w0 = max(0, i - E["uzama_bar"] + 1)
    if yon == 1:
        uc = lo[w0:i + 1].min()
        if lo[i] > uc + 0.25 * a:      # uç noktadan çok uzaklaşmışsa fırsat geçmiş
            return None
    else:
        uc = hi[w0:i + 1].max()
        if hi[i] < uc - 0.25 * a:
            return None

    # ── ZORUNLU: REJECTION — bar aralığında kapanış GERİ DÖNÜŞ tarafında ──
    rng = hi[i] - lo[i]
    if rng <= 0:
        return None
    konum = (cl[i] - lo[i]) / rng      # 0 = dipte kapanış, 1 = tepede
    if yon == 1 and konum < (1.0 - E["rejection_govde"]):
        return None                     # long için kapanış barın ÜST kısmında olmalı
    if yon == -1 and konum > E["rejection_govde"]:
        return None

    # ── YAPISAL SL: uzama ucunun ötesi + tampon ·  TP: VWAP ──
    if yon == 1:
        sl = uc - cfg.sl_atr * a
        tp = vw - E["tp_vwap_pay"] * a
        if tp <= cl[i]:
            return None
    else:
        sl = uc + cfg.sl_atr * a
        tp = vw + E["tp_vwap_pay"] * a
        if tp >= cl[i]:
            return None
    return Sinyal(yon, float(sl), float(tp), f"vwap{abs(sapma):.1f}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    args = [a for a in args if a in EL.COINS]   # --slip 0 gibi sayılar coin değil
    coins = args or EL.COINS
    cfg = EL.cli_maliyet(varsayilan_cfg(), sys.argv)
    print("=== STRATEJİ 2: VWAP MEAN REVERSION — BASELINE (filtresiz) ===")
    print("  ⚠ opsiyonel filtreler YOK (VWAP eğimi dahil — brief onun katkısını")
    print("    ayrıca soruyor, izole ölçülebilsin diye baseline'a KONMADI)")
    tum = []
    for c in coins:
        v = EL.yukle(c, cfg)
        if v is None:
            print(f"  {c:<5s} veri YOK"); continue
        tr = EL.kos(c, v, cfg, strateji)
        tum += tr
        m = EL.metrik(tr)
        print(f"  {c:<5s} n={m.get('n',0):>4d}  toplam {m.get('toplamR',0):>+7.1f}R  "
              f"ort {m.get('ortR',0):>+7.4f}  PF {m.get('pf',0):>5.2f}")
    EL.rapor("VWAP MEAN REVERSION · BASELINE", tum, cfg)


if __name__ == "__main__":
    main()
