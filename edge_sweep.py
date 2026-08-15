"""
edge_sweep.py — STRATEJİ 1: LIQUIDITY SWEEP + RECLAIM (baseline, filtresiz).

BRIEF'İN ZORUNLU KURALLARI, TEK TEK NEREDE UYGULANDI:
  "15M'de anlamlı swing low/liquidity"      → setup diliminde onaylı fractal,
                                              swing_lookback barın uç değeri
  "sadece tek mumluk rastgele low/high yok" → fractal + lookback uç şartı
  "fiyat seviyenin ALTINA sweep yapmalı"    → 5dk low < seviye
  "sonra 5M KAPANIŞ seviyenin ÜZERİNDE"     → close > seviye (aynı ya da sonraki bar)
  "fiyat seviyenin İÇİNE dönmeli"           → reclaim şartının ta kendisi
  "dışarıda kalıyorsa reclaim DEĞİL"        → sweep_pencere bar içinde geri
                                              gelmezse setup İPTAL
  "HTF yapı tamamen ters ve güçlü ise engelle" → ZORUNLU rejim kapısı (aşağıda)
  "aşırı volatilitede kalite düşür"         → ZORUNLU aşırı-vol kapısı
  "SL yapısal invalidation'da"              → sweep'in EN DİP noktası − ATR tamponu
  "TP en yakın anlamlı karşı bölge"         → karşı taraftaki onaylı swing seviyesi
  "1M yalnız entry timing"                  → tf_timing=None (kapalı, gerekçe altta)

⚠ BRIEF'İN "ZORUNLU" İLE "OPSİYONEL" AYRIMINA SADIK KALINDI.
Zorunlu filtreler baseline'ın İÇİNDE (brief onları stratejinin tanımı saymış).
Opsiyonel filtreler (15M trend, ATR vol, hacim, 5M market structure, 1M momentum)
BU DOSYADA YOK — onlar B aşamasında tek tek eklenecek. Baseline'a gizlice filtre
sokmak, sonra "filtre işe yaradı" demenin en kolay yoludur.

⚠ ÖN-KAYIT: aşağıdaki parametreler VERİYE BAKILMADAN yazıldı. Sonradan
değiştirilirse rapora "AYARLANDI" diye işaretlenecek.

⚠ VENUE ÇEKİNCESİ: bu strateji FİTİLLERE bakıyor. veri_binance --venue-fark
kapanışlarda 0.83bp/kor 0.99976 verdi, ama fitiller venue'ye çok daha duyarlı.
Bu dosya `--venue-sweep` ile sweep SAYISINI iki borsada karşılaştırır.

Kullanım:
    python3 edge_sweep.py                 # baseline, tüm coinler
    python3 edge_sweep.py SOL ETH
    python3 edge_sweep.py --lookahead-testi
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import edge_lab as EL
from edge_lab import Cfg, Sinyal


# ── ÖN-KAYITLI PARAMETRELER (veriye bakılmadan seçildi) ──────────────────────
def varsayilan_cfg() -> Cfg:
    c = Cfg(
        tf_base="5m", tf_setup="15m", tf_regime="1h", tf_timing=None,
        swing_k=3,              # 15dk'da 3 bar = 45dk her yandan
        swing_lookback=40,      # 40×15dk = 10 saat: "anlamlı" seviye
        atr_period=14,
        sl_atr=0.5,             # sweep dibine tampon
        rr_min=1.5,
        max_hold_bar=96,        # 8 saat
    )
    c.ekstra = dict(
        sweep_pencere=6,        # sweep'ten sonra reclaim için en fazla 6×5dk=30dk
        reclaim_min_bp=0.0,     # kapanış seviyenin ne kadar ÜSTÜNDE olmalı
        seviye_yas_max=200,     # seviye 200×15dk'dan eskiyse "likidite" saymayız
        rejim_ema=50,           # 1h EMA — HTF yön
        rejim_guc_atr=2.0,      # fiyat EMA'dan bu kadar ATR uzaksa "GÜÇLÜ ters"
        vol_ust_yuzde=95.0,     # ATR yüzdelik: üstü "aşırı volatilite" → ELE
    )
    return c


def _hazirla(veri: dict, cfg: Cfg) -> None:
    """Bir kez hesaplanan seriler. Hepsi geçmişe bakar; ileri bakan tek şey yok."""
    su = veri["setup"]
    lo_lvl, lo_idx, hi_lvl, hi_idx = EL.swing_seviyeleri(
        su, cfg.swing_k, cfg.swing_lookback)
    veri["s_lo_lvl"], veri["s_lo_idx"] = lo_lvl, lo_idx
    veri["s_hi_lvl"], veri["s_hi_idx"] = hi_lvl, hi_idx
    b = veri["base"]
    veri["b_atr"] = EL.atr(b["high"].values, b["low"].values,
                           b["close"].values, cfg.atr_period)
    # aşırı volatilite eşiği: GENİŞLEYEN yüzdelik (geçmişe bakar, ileriye DEĞİL)
    s = pd.Series(veri["b_atr"] / b["close"].values)
    veri["vol_esik"] = s.expanding(min_periods=2000).quantile(
        cfg.ekstra["vol_ust_yuzde"] / 100.0).values
    veri["vol_now"] = s.values
    r = veri["regime"]
    veri["r_ema"] = r["close"].ewm(span=cfg.ekstra["rejim_ema"],
                                   adjust=False).mean().values
    veri["r_atr"] = EL.atr(r["high"].values, r["low"].values,
                           r["close"].values, cfg.atr_period)


def strateji(i: int, veri: dict, cfg: Cfg, ctx: dict):
    if "hazir" not in ctx:
        _hazirla(veri, cfg); ctx["hazir"] = True
    E = cfg.ekstra
    b = veri["base"]
    lo = b["low"].values; hi = b["high"].values; cl = b["close"].values
    sp = veri["setup_pos"][i]; rp = veri["regime_pos"][i]
    if sp < 0 or rp < 0:
        return None

    # ── ZORUNLU: aşırı volatilite kapısı ──
    ve = veri["vol_esik"][i]
    if np.isfinite(ve) and veri["vol_now"][i] > ve:
        return None

    a = veri["b_atr"][i]
    if not np.isfinite(a) or a <= 0:
        return None

    # ── ZORUNLU: HTF yapı TAMAMEN ters ve GÜÇLÜ ise engelle ──
    rc = veri["regime"]["close"].values[rp]
    rema = veri["r_ema"][rp]; ratr = veri["r_atr"][rp]
    guclu_dusus = np.isfinite(ratr) and ratr > 0 and (rema - rc) > E["rejim_guc_atr"] * ratr
    guclu_yukselis = np.isfinite(ratr) and ratr > 0 and (rc - rema) > E["rejim_guc_atr"] * ratr

    for yon in (1, -1):
        if yon == 1:
            lvl = veri["s_lo_lvl"][sp]; lidx = veri["s_lo_idx"][sp]
            if guclu_dusus:                       # long ararken HTF güçlü düşüşte
                continue
        else:
            lvl = veri["s_hi_lvl"][sp]; lidx = veri["s_hi_idx"][sp]
            if guclu_yukselis:
                continue
        if not np.isfinite(lvl) or lidx < 0 or (sp - lidx) > E["seviye_yas_max"]:
            continue

        # ── SWEEP: son `sweep_pencere` bar içinde seviye DELİNDİ mi? ──
        w0 = max(0, i - E["sweep_pencere"] + 1)
        if yon == 1:
            delen = np.where(lo[w0:i + 1] < lvl)[0]
        else:
            delen = np.where(hi[w0:i + 1] > lvl)[0]
        if len(delen) == 0:
            continue
        ilk = w0 + int(delen[0])

        # ── RECLAIM: BU barın kapanışı seviyenin geri tarafında olmalı ──
        pay = E["reclaim_min_bp"] / 1e4 * lvl
        if yon == 1 and not (cl[i] > lvl + pay):
            continue
        if yon == -1 and not (cl[i] < lvl - pay):
            continue
        # sweep barının KENDİSİ zaten reclaim etmişse bu bir sweep değil, sadece
        # fitilli bir mumdur — brief "sweep SONRASI kapanış" diyor.
        if i == ilk:
            continue

        # ── YAPISAL SL: sweep'in en uç noktası + ATR tamponu ──
        if yon == 1:
            uc = lo[ilk:i + 1].min(); sl = uc - cfg.sl_atr * a
            tp_lvl = veri["s_hi_lvl"][sp]
            if not np.isfinite(tp_lvl) or tp_lvl <= cl[i]:
                continue
        else:
            uc = hi[ilk:i + 1].max(); sl = uc + cfg.sl_atr * a
            tp_lvl = veri["s_lo_lvl"][sp]
            if not np.isfinite(tp_lvl) or tp_lvl >= cl[i]:
                continue
        return Sinyal(yon, float(sl), float(tp_lvl), f"sweep{i-ilk}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    args = [a for a in args if a in EL.COINS]   # --slip 0 gibi sayılar coin değil
    coins = args or EL.COINS
    cfg = EL.cli_maliyet(varsayilan_cfg(), sys.argv)
    la = "--lookahead-testi" in sys.argv
    if la:
        cfg.swing_k = 0        # onay gecikmesini KALDIR → bilerek hile
        print("⚠⚠ LOOK-AHEAD TESTİ: swing onay gecikmesi KAPATILDI (k=0).")
        print("   Bu kol GELECEĞİ GÖRÜYOR. Sonucu gerçek koldan belirgin İYİYSE")
        print("   ölçüm hattı doğru kurulmuş demektir; AYNIYSA bir yerde sızıntı var.")
    print(f"=== STRATEJİ 1: LIQUIDITY SWEEP + RECLAIM — BASELINE (filtresiz) ===")
    print(f"  ⚠ opsiyonel filtrelerin HİÇBİRİ yok. Zorunlu kapılar (HTF rejim,")
    print(f"    aşırı vol) brief'te stratejinin TANIMI sayıldığı için içeride.")
    tum = []
    for c in coins:
        v = EL.yukle(c, cfg)
        if v is None:
            print(f"  {c:<5s} veri YOK — veri_binance.py ile çek"); continue
        tr = EL.kos(c, v, cfg, strateji)
        tum += tr
        m = EL.metrik(tr)
        print(f"  {c:<5s} n={m.get('n',0):>4d}  toplam {m.get('toplamR',0):>+7.1f}R  "
              f"ort {m.get('ortR',0):>+7.4f}  PF {m.get('pf',0):>5.2f}")
    EL.rapor("SWEEP+RECLAIM · BASELINE" + (" · LOOK-AHEAD KOLU" if la else ""),
             tum, cfg)


if __name__ == "__main__":
    main()
