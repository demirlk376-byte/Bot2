"""
squeeze_execution_audit.py — SQUEEZE'İN GERÇEK CANLI GİRİŞ KAYMASI (bp ve R). SALT OKUR.

Soru: ikiz squeeze'e donchian'dan ölçülmüş 15.85bp giriş kayması uyguluyor
(RESEARCH_LEDGER.md:4546 "SQUEEZE'İN KENDİ KAYMASINI ÖLÇ" — hiç yapılmadı).
Squeeze'in gerçek canlı kayması kaç bp, kaç R?

Kaynak: yalnız GERÇEK canlı işlemler (trades.is_paper = 0), kollar squeeze + donchian.
Her işlemin kaydı execution.py:905-928'de yazılır:
  strategy_scores.intended_entry  sinyal fiyatı (dolumdan ÖNCE)
  trades.entry_price              gerçek dolum
  strategy_scores.sl0             başlangıç stopu (sl_price sütunu stop taşındıkça değişir)
  strategy_scores.entry_fee_rate  0.0 = maker dolum, 0.0001 = taker
  strategy_scores.entry_price_estimated  True ise dolum TAHMİNİ → ana hesaptan çıkar

Tanım (ücret HARİÇ, ücret ayrı gösterilir):
  LONG  kayma_bp = (dolum - niyet) / niyet * 1e4
  SHORT kayma_bp = (niyet - dolum) / niyet * 1e4      (+ = aleyhe)
  stop_pct = |niyet - sl0| / niyet ;  kayma_R = (kayma_bp/1e4) / stop_pct

Ekonomik hesap (YENİ BACKTEST YOK): ikizin mevcut squeeze işlem dağılımı
(ikiz_k25_cap25_islemler.csv) üzerinde yalnız giriş kayması maliyeti yeniden fiyatlanır:
  brüt_R_i = R_i + ikiz_kayma_R_i   (ikizin kendi uyguladığı giriş kayması geri eklenir)
  kayıp%   = ort(kayma_R) / ort(brüt_R)   — varsayım (ikiz) ve ölçüm (canlı ort. bp) için ayrı.

Hüküm kuralı (önceden sabit, optimize edilmedi):
  squeeze n < 20                         → D
  %95 GA (bootstrap ort.) tamamen < 15.85 → A
  %95 GA tamamen > 15.85                  → C
  aksi (GA 15.85'i içeriyor)              → B

VPS'te:  cd /opt/bot2 && venv/bin/python arastirma/squeeze_execution_audit/squeeze_execution_audit.py
Seçenekler: --db trades.db  --cikti /tmp/squeeze_execution_audit  --ikiz <csv>  --paper (yalnız test)
Emir göndermez, borsaya bağlanmaz, .env okumaz; DB mode=ro. İşlem düzeyi CSV --cikti'ye yazılır.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

KOK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IKIZ_BP = 15.85
IKIZ_CSV = os.path.join(KOK, "arastirma", "paylasim_paketi_2026-09-26", "ikiz",
                        "ikiz_k25_cap25_islemler.csv")
KOLLAR = ("squeeze", "donchian")
TOHUM = 20260927
N_BOOT = 10000


def kol_of(ss: dict) -> str:
    """kayma_denetim.sleeve_of ile aynı kural."""
    s = str(ss.get("strategy") or ss.get("sleeve") or "").lower()
    if "donch" in s or "breakout" in s:
        return "donchian"
    if "squeeze" in s:
        return "squeeze"
    if "mean" in s or "bb" in s:
        return "bb"
    return s or "?"


# Stratejilerin ATR çarpanı (config: squeeze sl_atr=2.0, donchian sl_atr=2.0;
# strategies/squeeze.py:239, strategies/donchian.py:184). sl0 kaydı 2026-09-20'den
# önce YOKTU (execution.py:918-924). O işlemlerde trades.sl_price kullanılır, ama
# yalnız |niyet − sl_price| = sl_atr × atr (±%2) ise: bu hem stopun HİÇ
# TAŞINMADIĞINI hem de ATR'nin girişteki değer olduğunu doğrular. Tutmazsa R yok.
SL_ATR = {"squeeze": 2.0, "donchian": 2.0}
ATR_TOL = 0.02


def _stop_bul(kol, niyet, ss, sl_price_sutun):
    """(stop, kaynak). kaynak: 'sl0' | 'sl_price(ATR doğrulandı)' | 'yok'."""
    try:
        sl0 = float(ss.get("sl0"))
        if sl0 > 0 and abs(niyet - sl0) > 0:
            return sl0, "sl0"
    except (TypeError, ValueError):
        pass
    try:
        sp, atr = float(sl_price_sutun), float(ss.get("atr"))
    except (TypeError, ValueError):
        return float("nan"), "yok"
    if not (sp > 0 and atr > 0 and abs(niyet - sp) > 0):
        return float("nan"), "yok"
    oran = abs(niyet - sp) / (SL_ATR.get(kol, float("nan")) * atr)
    if abs(oran - 1.0) <= ATR_TOL:
        return sp, "sl_price(ATR doğrulandı)"
    return float("nan"), "yok"


def _yon(side) -> int:
    return 1 if str(side).lower() in ("long", "buy", "1") else -1


def defter_oku(db: str, paper: bool) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id, symbol, side, entry_price, quantity, sl_price, entry_time, exit_time, "
        "exit_reason, strategy_scores FROM trades WHERE is_paper=? ORDER BY entry_time",
        (1 if paper else 0,))]
    con.close()
    return pd.DataFrame(rows)


def hazirla(df: pd.DataFrame):
    """Her işlem için kayma alanlarını çıkarır. (temiz, elenen_sayim, diger_kol_sayim)"""
    kayit, elenen, diger = [], {}, {}
    elenen_R = elenen      # aynı sayımda, ayrı etiketle (bp'den ELENMEZ)
    for r in df.to_dict("records"):
        try:
            ss = json.loads(r.get("strategy_scores") or "{}")
        except Exception:
            ss = {}
        kol = kol_of(ss)
        if kol not in KOLLAR:
            diger[kol] = diger.get(kol, 0) + 1
            continue

        def ele(neden):
            elenen[(kol, neden)] = elenen.get((kol, neden), 0) + 1

        niyet = ss.get("intended_entry")
        sl0 = ss.get("sl0")
        dolum = r.get("entry_price")
        try:
            niyet, dolum = float(niyet), float(dolum)
        except (TypeError, ValueError):
            ele("intended_entry/dolum yok")
            continue
        if not (niyet > 0 and dolum > 0):
            ele("intended_entry/dolum yok")
            continue
        if ss.get("entry_price_estimated"):
            ele("dolum TAHMİNİ (entry_price_estimated)")
            continue
        d = _yon(r.get("side"))
        bp = d * (dolum - niyet) / niyet * 1e4
        # STOP yalnız R için gerekir; bp'yi ETKİLEMEZ (sl0 yok diye bp atılmaz).
        stop, kaynak = _stop_bul(kol, niyet, ss, r.get("sl_price"))
        if kaynak == "yok":
            elenen_R[(kol, "stop bilinmiyor (R hesaplanamaz, bp sayılır)")] = \
                elenen_R.get((kol, "stop bilinmiyor (R hesaplanamaz, bp sayılır)"), 0) + 1
        stop_pct = abs(niyet - stop) / niyet if kaynak != "yok" else float("nan")
        rate = ss.get("entry_fee_rate")
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            rate = float("nan")
        qty = float(r.get("quantity") or 0.0)
        nom = dolum * qty
        kayit.append(dict(
            symbol=str(r["symbol"]).split("/")[0], kol=kol,
            side="long" if d > 0 else "short", entry_time=r.get("entry_time"),
            intended_entry=niyet, entry_fill=dolum, stop0=stop, stop_kaynak=kaynak,
            quantity=qty,
            notional_usdt=nom,
            dolum_tipi=("maker" if rate == 0.0 else "taker" if rate > 0 else "?"),
            entry_fee_rate=rate, entry_fee_usdt=(nom * rate if np.isfinite(rate) else np.nan),
            fill_estimated=False, slippage_bp=bp, stop_pct=stop_pct,
            slippage_R=((bp / 1e4) / stop_pct) if np.isfinite(stop_pct) and stop_pct > 0
            else float("nan"),
            exit_reason=r.get("exit_reason")))
    return pd.DataFrame(kayit), elenen, diger


def boot_ga(x: np.ndarray):
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(TOHUM)
    ort = rng.choice(x, size=(N_BOOT, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(ort, 2.5)), float(np.percentile(ort, 97.5))


def ozet(t: pd.DataFrame) -> dict:
    x = t["slippage_bp"].to_numpy(float)
    r = t["slippage_R"].to_numpy(float)
    r = r[np.isfinite(r)]                 # R yalnız stopu bilinen işlemlerde
    if len(x) == 0:
        return dict(n=0)
    lo, hi = boot_ga(x)
    return dict(n=len(x), ort_bp=x.mean(), medyan_bp=float(np.median(x)),
                p25=float(np.percentile(x, 25)), p75=float(np.percentile(x, 75)),
                p90=float(np.percentile(x, 90)), ga_lo=lo, ga_hi=hi,
                n_R=len(r),
                ort_R=r.mean() if len(r) else float("nan"),
                medyan_R=float(np.median(r)) if len(r) else float("nan"),
                ort_stop_pct=float(np.nanmean(t["stop_pct"])) * 100
                if t["stop_pct"].notna().any() else float("nan"),
                ort_ucret_bp=float(np.nanmean(t["entry_fee_rate"])) * 1e4
                if t["entry_fee_rate"].notna().any() else float("nan"))


def orneklem(n: int) -> str:
    return "yalnız betimsel" if n < 10 else "zayıf örneklem" if n < 20 else "kıyaslanabilir"


def satir(ad, o) -> str:
    if not o.get("n"):
        return f"  {ad:<22s} n=0"
    return (f"  {ad:<22s} n={o['n']:>3d}  ort {o['ort_bp']:+7.2f}bp  medyan {o['medyan_bp']:+7.2f}  "
            f"p25/p75 {o['p25']:+6.2f}/{o['p75']:+6.2f}  p90 {o['p90']:+7.2f}  "
            f"%95GA [{o['ga_lo']:+.2f}, {o['ga_hi']:+.2f}]  R(n={o['n_R']}) ort {o['ort_R']:+.4f}  "
            f"medyan {o['medyan_R']:+.4f}  ({orneklem(o['n'])})")


def spearman(x: np.ndarray, y: np.ndarray):
    """Spearman rho + permütasyon p (iki yönlü, scipy gerekmez)."""
    if len(x) < 3:
        return float("nan"), float("nan")
    rx, ry = pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(TOHUM)
    perm = np.array([np.corrcoef(rx, rng.permutation(ry))[0, 1] for _ in range(5000)])
    p = float((np.abs(perm) >= abs(rho) - 1e-12).mean())
    return rho, p


def ikiz_ekonomi(ikiz_csv: str, olculen_bp: float):
    """İkizin squeeze işlemleri üzerinde yalnız giriş kayması maliyetini yeniden fiyatla."""
    if not os.path.exists(ikiz_csv):
        return None
    d = pd.read_csv(ikiz_csv)
    d = d[d["kol"] == "squeeze"].copy()
    rows = []
    for r in d.to_dict("records"):
        ss = json.loads(r["strategy_scores"])
        niyet, sl0 = float(ss["intended_entry"]), float(ss["sl0"])
        dy = _yon(r["side"])
        stop_pct = abs(niyet - sl0) / niyet
        ikiz_bp = dy * (float(r["entry_price"]) - niyet) / niyet * 1e4
        rows.append((float(r["R"]), stop_pct, ikiz_bp))
    a = np.array(rows)
    R, sp, ikiz_bp = a[:, 0], a[:, 1], a[:, 2]
    ikiz_kR = (ikiz_bp / 1e4) / sp
    brut = R + ikiz_kR
    olc_kR = (olculen_bp / 1e4) / sp if np.isfinite(olculen_bp) else np.full_like(sp, np.nan)
    return dict(n=len(R), ikiz_bp_ort=ikiz_bp.mean(), brut_R=brut.mean(), net_R_ikiz=R.mean(),
                kayma_R_ikiz=ikiz_kR.mean(), kayip_ikiz=ikiz_kR.mean() / brut.mean() * 100,
                kayma_R_olc=np.nanmean(olc_kR),
                net_R_olc=(brut - olc_kR).mean(),
                kayip_olc=np.nanmean(olc_kR) / brut.mean() * 100,
                ort_stop_pct=sp.mean() * 100)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--db", default="trades.db")
    ap.add_argument("--cikti", default="/tmp/squeeze_execution_audit")
    ap.add_argument("--ikiz", default=IKIZ_CSV)
    ap.add_argument("--paper", action="store_true", help="YALNIZ TEST: is_paper=1 satırları")
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        sys.exit(f"DB yok: {a.db}")

    ham = defter_oku(a.db, a.paper)
    t, elenen, diger = hazirla(ham)
    kaynak = "is_paper=1 (TEST — canlı DEĞİL)" if a.paper else "is_paper=0 (GERÇEK canlı)"
    print(f"squeeze_execution_audit · DB {a.db} · {kaynak} · toplam satır {len(ham)}")
    print(f"  ana hesaba alınmayan diğer kollar: {dict(sorted(diger.items())) or '-'}")
    for kol in KOLLAR:
        e = {k[1]: v for k, v in elenen.items() if k[0] == kol}
        print(f"  {kol:<9s} elenen: {e or 'yok'}")
    if len(t) and "entry_time" in t:
        print(f"  temiz işlem aralığı: {t['entry_time'].min()} → {t['entry_time'].max()}")

    os.makedirs(a.cikti, exist_ok=True)
    csv_yol = os.path.join(a.cikti, "squeeze_execution_trades.csv")
    t.to_csv(csv_yol, index=False)

    # ANA GRUP = TAKER (piyasa) dolumlar: canlının BUGÜNKÜ yolu ve ikizin modellediği
    # giriş. Maker dolumlar (reddedilmiş squeeze maker denemesi, eski donchian maker
    # dönemi) ayrı satırda gösterilir, hükme girmez. (Önceden sabitlendi.)
    sq_tum = t[t["kol"] == "squeeze"] if len(t) else t
    dc_tum = t[t["kol"] == "donchian"] if len(t) else t
    sq = sq_tum[sq_tum["dolum_tipi"] == "taker"] if len(sq_tum) else sq_tum
    dc = dc_tum[dc_tum["dolum_tipi"] == "taker"] if len(dc_tum) else dc_tum
    osq, odc = ozet(sq), ozet(dc)

    print("\n== 4) ANA KIYAS (ücret HARİÇ; + = aleyhe; ANA = taker/piyasa dolum)")
    print(satir("SQUEEZE taker (ANA)", osq))
    print(satir("SQUEEZE tüm dolumlar", ozet(sq_tum)))
    print(satir("DONCHIAN taker (ANA)", odc))
    print(satir("DONCHIAN tüm dolumlar", ozet(dc_tum)))
    print(f"  İKİZ varsayımı          {IKIZ_BP:.2f}bp")
    for ad, g in (("squeeze", sq_tum), ("donchian", dc_tum)):
        if len(g):
            print(f"  {ad} stop kaynağı: {g['stop_kaynak'].value_counts().to_dict()}")
    for ad, o in (("squeeze", osq), ("donchian", odc)):
        if o.get("n"):
            print(f"  {ad}: ort stop %{o['ort_stop_pct']:.2f} · giriş ücreti ort {o['ort_ucret_bp']:.2f}bp "
                  f"(kaymaya DAHİL DEĞİL)")

    print("\n== 5) SQUEEZE ALT GRUPLARI (n<10 betimsel, n<20 zayıf; hüküm verilmez)")
    if len(sq_tum):
        sq_tum = sq_tum.copy()
        print(satir("dolum_tipi=maker", ozet(sq_tum[sq_tum["dolum_tipi"] == "maker"])))
        print(satir("dolum_tipi=taker", ozet(sq_tum[sq_tum["dolum_tipi"] == "taker"])))
        print("  (aşağısı yalnız taker)")
        sq = sq.copy()
        try:
            sq["nom_dilim"] = pd.qcut(sq["notional_usdt"], 3, labels=["küçük", "orta", "büyük"],
                                      duplicates="drop")
        except ValueError:
            sq["nom_dilim"] = "tek"
        for kolon in ("symbol", "side", "nom_dilim"):
            for deger, g in sq.groupby(kolon, observed=True):
                print(satir(f"{kolon}={deger}", ozet(g)))
    else:
        print("  squeeze işlemi yok")

    print("\n== 7) NOMİNAL / KAYMA İLİŞKİSİ (squeeze)")
    iliski = "INSUFFICIENT"
    if len(sq) >= 20:
        rho, p = spearman(sq["notional_usdt"].to_numpy(float), sq["slippage_bp"].to_numpy(float))
        iliski = "YES" if (p < 0.05 and rho > 0) else "NO"
        print(f"  Spearman rho={rho:+.3f}  permütasyon p={p:.3f}  (n={len(sq)})")
        for deger, g in sq.groupby("nom_dilim", observed=True):
            print(f"    {deger:<6s} nominal ${g['notional_usdt'].min():,.0f}-${g['notional_usdt'].max():,.0f}"
                  f"  n={len(g)}  ort {g['slippage_bp'].mean():+.2f}bp")
    else:
        print(f"  n={len(sq)} < 20 → ölçülemiyor")
    if len(dc) >= 20:
        rho, p = spearman(dc["notional_usdt"].to_numpy(float), dc["slippage_bp"].to_numpy(float))
        print(f"  (karşılaştırma) donchian Spearman rho={rho:+.3f} p={p:.3f} n={len(dc)}")

    print("\n== 6) EKONOMİ — squeeze ham edge'inin ne kadarı giriş kaymasına gidiyor (backtest YOK)")
    eko = ikiz_ekonomi(a.ikiz, osq.get("ort_bp", float("nan")) if osq.get("n") else float("nan"))
    if eko is None:
        print(f"  ikiz CSV yok: {a.ikiz}")
    else:
        print(f"  ikiz squeeze işlemleri n={eko['n']} · ort stop %{eko['ort_stop_pct']:.2f} · "
              f"ikizin uyguladığı giriş kayması ort {eko['ikiz_bp_ort']:.2f}bp")
        print(f"  brüt (giriş kayması öncesi) ort R = {eko['brut_R']:+.4f}")
        print(f"  İKİZ varsayımı : kayma {eko['kayma_R_ikiz']:.4f}R · net {eko['net_R_ikiz']:+.4f}R · "
              f"ham edge'in %{eko['kayip_ikiz']:.1f}'i")
        if np.isfinite(eko["kayma_R_olc"]):
            print(f"  CANLI ÖLÇÜM    : kayma {eko['kayma_R_olc']:.4f}R · net {eko['net_R_olc']:+.4f}R · "
                  f"ham edge'in %{eko['kayip_olc']:.1f}'i  (ölçülen ort bp ikizin stop dağılımına uygulandı)")
        else:
            print("  CANLI ÖLÇÜM    : squeeze ölçümü yok")

    if not osq.get("n") or osq["n"] < 20:
        hukum = "D"
    elif osq["ga_hi"] < IKIZ_BP - 1e-6:
        hukum = "A"
    elif osq["ga_lo"] > IKIZ_BP + 1e-6:
        hukum = "C"
    else:
        hukum = "B"

    kayip = (f"{eko['kayip_olc']:.1f}" if eko and np.isfinite(eko["kayma_R_olc"]) else "ölçülemedi")
    kayip_ikiz = f"{eko['kayip_ikiz']:.1f}" if eko else "?"

    def f(o, k, fmt):
        return format(o[k], fmt) if o.get("n") else "-"

    print(f"\n(işlem düzeyi CSV: {csv_yol})")
    print("\n" + "=" * 60)
    print(f"SQUEEZE n: {osq.get('n', 0)} taker (R için stopu bilinen: {osq.get('n_R', 0)}) · "
          f"tüm dolumlar {len(sq_tum)}")
    print(f"SQUEEZE mean/median slippage bp: {f(osq, 'ort_bp', '+.2f')} / {f(osq, 'medyan_bp', '+.2f')}")
    print(f"SQUEEZE mean slippage R: {f(osq, 'ort_R', '+.4f')}")
    print()
    print(f"DONCHIAN n: {odc.get('n', 0)} taker · tüm dolumlar {len(dc_tum)}")
    print(f"DONCHIAN mean/median slippage bp: {f(odc, 'ort_bp', '+.2f')} / {f(odc, 'medyan_bp', '+.2f')}")
    print()
    print("IKIZ assumption:")
    print(f"{IKIZ_BP}bp")
    print()
    print("SQUEEZE gross edge lost to entry slippage:")
    not_ = "" if osq.get("n", 0) >= 20 else "  ⚠ n<20: hüküm için yetersiz"
    print(f"%{kayip}  (ikiz varsayımıyla %{kayip_ikiz}){not_}")
    print()
    print("notional-slippage relationship:")
    print(iliski)
    print()
    print("HÜKÜM:")
    print(hukum)
    return hukum


if __name__ == "__main__":
    main()
