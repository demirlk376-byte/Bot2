"""
edge_squeeze.py — STRATEJİ 3: BOLLINGER/KELTNER VOLATİLİTE EXPANSION (baseline).

⚠ BU ÜÇÜNÜN İÇİNDE ÖNSELİ EN İYİ OLAN. Sebep: canlı sistemde ZATEN ÇALIŞAN bir
squeeze kolu var (strategies/squeeze.py, 1 SAATLİK, XRP/DOGE/TRX/XLM). Yani
"BB'nin Keltner'a sıkışması sonrası genişleme" kavramı bu portföyde daha önce
kanıtlandı. Buradaki soru KAVRAM değil, ÖLÇEK: aynı şey 15 DAKİKADA da var mı?
Sweep ve VWAP sıfırdan hipotezdi; bu, bilinen bir edge'in alt dilime taşınması.

BRIEF'İN ZORUNLU KURALLARI → NEREDE:
  "15M/5M'de contraction tespit"          → setup diliminde BB ⊂ Keltner (TTM squeeze)
  "squeeze ÖNCESİ gerçek contraction"     → en az min_squeeze_bar bar sıkışık kalmalı
  "squeeze sonrası expansion"             → sıkışma BİTMELİ (BB Keltner'ı aşmalı)
  "sadece band kırılması sinyal DEĞİL"    → sıkışma geçmişi olmadan sinyal YOK
  "breakout mumunda yeterli gövde"        → |kapanış−açılış| / aralık >= min_govde
  "hemen range'e dönerse GEÇERSİZ"        → kapanış sıkışma aralığının DIŞINDA olmalı
  "çok düşük vol ve kaotik vol AYRI rejim"→ ikisi de ayrı etikete yazılıyor;
                                            kaotik ZORUNLU olarak eleniyor
  "HTF yön destekliyorsa kalite yükselir" → HTF ters ve GÜÇLÜ ise engelle
  "SL yapısal"                            → sıkışma aralığının karşı ucu + tampon
  "TP anlamlı karşı bölge"                → ölçülü hareket (aralık yüksekliği × çarpan)
  "1M yalnız timing"                      → kapalı

⚠ ÖN-KAYIT: parametreler veriye BAKILMADAN yazıldı. Opsiyonel filtreler
(ATR expansion, BB width expansion, Keltner breakout, hacim, HTF hizalama,
breakout mum kalitesi) BU DOSYADA YOK — B aşamasında tek tek.

Kullanım:  python3 edge_squeeze.py   |   python3 edge_squeeze.py --slip 0
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
        sl_atr=0.3, rr_min=1.5, max_hold_bar=96,
    )
    c.ekstra = dict(
        bb_period=20, bb_std=2.0,
        kc_period=20, kc_mult=1.5,       # canlı squeeze kolundaki değerle aynı
        min_squeeze_bar=5,               # canlı kolla aynı (strategies/squeeze.py)
        min_govde=0.50,                  # breakout mumunun gövde oranı
        # ── SL/TP MODU — bu bir tasarım kararı, sonuçlara BAKILMADAN verildi ──
        # "range" modunda SL sıkışma aralığının KARŞI ucunda (brief'in istediği
        # yapısal invalidation) ve TP = 1× aralık yüksekliği. Aritmetik:
        #     risk ≈ yükseklik + tampon   ·   ödül = 1× yükseklik
        #     → RR ≈ 1.0, rr_min=1.5'i ASLA geçemez
        # İlk sürüm bu yüzden 0 sinyal üretti (217 aday sessizce elendi).
        # Yükseltmek için tp_carpan'ı 1.5+ yapmak DA bir seçenek — ama o zaman
        # hedef "ölçülü hareket" olmaktan çıkar, uydurma bir çarpan olur.
        #
        # VARSAYILAN "atr": CANLIDA ÇALIŞAN 1h squeeze kolunun BİREBİR ayarı
        # (strategies/squeeze.py: sl_atr=2.0, rr=2.5). Böylece bu test gerçekten
        # "aynı edge 15 dakikada var mı" sorusunu sorar; benim uydurduğum bir
        # SL/TP şemasını değil. Kanıtlanmış kurgudan sapmamak için.
        sl_modu="atr",                   # "atr" (üretim aynası) | "range" (yapısal)
        sl_atr_carpan=2.0,               # üretimdeki değer
        rr_hedef=2.5,                    # üretimdeki değer
        tp_carpan=1.0,                   # yalnız sl_modu="range" iken kullanılır
        rejim_ema=50, rejim_guc_atr=2.5, # HTF ters+güçlü ise engelle
        vol_alt_yuzde=5.0,               # "çok düşük vol" etiketi
        vol_ust_yuzde=95.0,              # "kaotik vol" → ZORUNLU ELE
    )
    return c


def _hazirla(veri: dict, cfg: Cfg) -> None:
    E = cfg.ekstra
    su = veri["setup"]
    c = su["close"]
    ma = c.rolling(E["bb_period"]).mean()
    sd = c.rolling(E["bb_period"]).std(ddof=0)
    veri["bb_up"] = (ma + E["bb_std"] * sd).values
    veri["bb_dn"] = (ma - E["bb_std"] * sd).values
    veri["bb_mid"] = ma.values
    satr = EL.atr(su["high"].values, su["low"].values, c.values, E["kc_period"])
    veri["s_atr"] = satr
    kc_up = ma.values + E["kc_mult"] * satr
    kc_dn = ma.values - E["kc_mult"] * satr
    # TTM SQUEEZE: Bollinger tamamen Keltner'ın İÇİNDE
    sik = (veri["bb_up"] < kc_up) & (veri["bb_dn"] > kc_dn)
    veri["sikisik"] = sik
    # kaç bardır sıkışık (ardışık sayaç — yalnız geçmişe bakar)
    n = len(sik); ard = np.zeros(n, dtype=int)
    for i in range(1, n):
        ard[i] = ard[i - 1] + 1 if sik[i] else 0
    veri["sik_ard"] = ard
    b = veri["base"]
    veri["b_atr"] = EL.atr(b["high"].values, b["low"].values,
                           b["close"].values, cfg.atr_period)
    s = pd.Series(veri["b_atr"] / b["close"].values)
    veri["vol_ust"] = s.expanding(min_periods=2000).quantile(E["vol_ust_yuzde"] / 100).values
    veri["vol_alt"] = s.expanding(min_periods=2000).quantile(E["vol_alt_yuzde"] / 100).values
    veri["vol_now"] = s.values
    r = veri["regime"]
    veri["r_ema"] = r["close"].ewm(span=E["rejim_ema"], adjust=False).mean().values
    veri["r_atr"] = EL.atr(r["high"].values, r["low"].values, r["close"].values,
                           cfg.atr_period)


def strateji(i: int, veri: dict, cfg: Cfg, ctx: dict):
    if "hazir" not in ctx:
        _hazirla(veri, cfg); ctx["hazir"] = True
    E = cfg.ekstra
    b = veri["base"]
    op = b["open"].values; hi = b["high"].values
    lo = b["low"].values; cl = b["close"].values
    sp = veri["setup_pos"][i]; rp = veri["regime_pos"][i]
    if sp < 1 or rp < 0:
        return None

    # ── ZORUNLU: KAOTİK volatilite ELE (brief: ayrı rejim) ──
    vu = veri["vol_ust"][i]
    if np.isfinite(vu) and veri["vol_now"][i] > vu:
        return None
    va = veri["vol_alt"][i]
    dusuk_vol = bool(np.isfinite(va) and veri["vol_now"][i] < va)

    a = veri["b_atr"][i]
    if not np.isfinite(a) or a <= 0:
        return None

    # ── ZORUNLU: ÖNCE gerçek CONTRACTION, SONRA expansion ──
    # sp barı sıkışık DEĞİL ama sp-1 yeterince uzun sıkışıktıysa → SALIVERME anı
    if veri["sikisik"][sp]:
        return None
    if veri["sik_ard"][sp - 1] < E["min_squeeze_bar"]:
        return None

    # sıkışma aralığı: sıkışık barların yüksek/düşüğü (YAPISAL referans)
    uzun = int(veri["sik_ard"][sp - 1])
    s0 = max(0, sp - uzun)
    su = veri["setup"]
    rng_hi = su["high"].values[s0:sp].max()
    rng_lo = su["low"].values[s0:sp].min()
    yukseklik = rng_hi - rng_lo
    if yukseklik <= 0:
        return None

    # ── ZORUNLU: kapanış aralığın DIŞINDA (hemen içeri dönüyorsa geçersiz) ──
    if cl[i] > rng_hi:
        yon = 1
    elif cl[i] < rng_lo:
        yon = -1
    else:
        return None

    # ── ZORUNLU: breakout mumunda yeterli GÖVDE ──
    aralik = hi[i] - lo[i]
    if aralik <= 0:
        return None
    govde = abs(cl[i] - op[i]) / aralik
    if govde < E["min_govde"]:
        return None
    if yon == 1 and cl[i] <= op[i]:      # yukarı kırılımda mum YEŞİL olmalı
        return None
    if yon == -1 and cl[i] >= op[i]:
        return None

    # ── ZORUNLU: HTF ters ve GÜÇLÜ ise engelle ──
    rc = veri["regime"]["close"].values[rp]
    rema = veri["r_ema"][rp]; ratr = veri["r_atr"][rp]
    if np.isfinite(ratr) and ratr > 0:
        if yon == 1 and (rema - rc) > E["rejim_guc_atr"] * ratr:
            return None
        if yon == -1 and (rc - rema) > E["rejim_guc_atr"] * ratr:
            return None

    # ── YAPISAL SL: sıkışma aralığının KARŞI ucu + tampon · TP: ölçülü hareket ──
    if E["sl_modu"] == "atr":
        # ÜRETİM AYNASI: canlı 1h squeeze kolunun birebir SL/TP şeması.
        #
        # ⚠ BRACKET *BEKLENEN GİRİŞ FİYATI* ETRAFINA KURULUR, kapanışın değil.
        # İlk sürüm kapanışı çapa alıyordu ve sonuç şuydu: hedef RR 2.5 iken
        # motorun ölçtüğü GERÇEK RR 1.35'e düşüyordu, çünkü kayma girişi ittiriyor
        # (risk büyüyor, ödül küçülüyor) → sinyallerin %99'u rr_min=1.5'e takılıyordu.
        # Canlı risk.py de SL/TP'yi GİRİŞ fiyatından hesaplıyor (calculate_sl_tp),
        # yani bu bir uyum düzeltmesi, parametre oynatma DEĞİL.
        e_bek = cl[i] * (1 + yon * cfg.slip_bp / 1e4)
        sld = E["sl_atr_carpan"] * a
        sl = e_bek - yon * sld
        tp = e_bek + yon * E["rr_hedef"] * sld
    else:
        # YAPISAL: sıkışma aralığının karşı ucu + ölçülü hareket
        if yon == 1:
            sl = rng_lo - cfg.sl_atr * a
            tp = cl[i] + E["tp_carpan"] * yukseklik
        else:
            sl = rng_hi + cfg.sl_atr * a
            tp = cl[i] - E["tp_carpan"] * yukseklik
    etiket = ("dusukvol" if dusuk_vol else "normal") + f"_sq{uzun}"
    return Sinyal(yon, float(sl), float(tp), etiket)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    args = [a for a in args if a in EL.COINS]
    coins = args or EL.COINS
    cfg = EL.cli_maliyet(varsayilan_cfg(), sys.argv)
    print("=== STRATEJİ 3: BB/KELTNER VOLATİLİTE EXPANSION — BASELINE ===")
    print("  ⓘ Üçünün ÖNSELİ EN İYİ olanı: canlıda ZATEN çalışan 1h squeeze kolunun")
    print("    15 dakikalık versiyonu. Soru kavram değil, ÖLÇEK.")
    tum = []
    for c in coins:
        print(f"  {c:<5s} ...", end="", flush=True)
        v = EL.yukle(c, cfg)
        if v is None:
            print(f"\r  {c:<5s} veri YOK", flush=True); continue
        tr = EL.kos(c, v, cfg, strateji)
        tum += tr
        m = EL.metrik(tr)
        print(f"\r  {c:<5s} n={m.get('n',0):>4d}  toplam {m.get('toplamR',0):>+7.1f}R  "
              f"ort {m.get('ortR',0):>+7.4f}  PF {m.get('pf',0):>5.2f}", flush=True)
    m = EL.rapor("BB/KELTNER EXPANSION · BASELINE", tum, cfg)
    # brief: düşük vol vs normal vol AYRI rejim olarak raporlansın
    if tum:
        dv = [t for t in tum if t["etiket"].startswith("dusukvol")]
        nv = [t for t in tum if not t["etiket"].startswith("dusukvol")]
        print(f"\n  --- VOL REJİMİ (brief: ayrı test edilmeli) ---")
        print(f"{EL.BASLIK}")
        print(EL.satir("çok DÜŞÜK vol", EL.metrik(dv)))
        print(EL.satir("normal vol", EL.metrik(nv)))


if __name__ == "__main__":
    main()
