"""
edge_lab.py — YENİ STRATEJİ ARAŞTIRMASININ ORTAK İSKELETİ.

Brief üç strateji istiyor (Liquidity Sweep+Reclaim · VWAP Mean Reversion ·
BB/Keltner Volatility Expansion), ortak kurallarla: 1H rejim / 15M setup / 5M
teyit / 1M timing · yapısal SL · look-ahead YOK · ücret+kayma DAHİL ·
baseline → tek filtre → kombinasyon → walk-forward → OOS.

Bu dosya o kuralların TEK uygulamasıdır. Üç strateji de aynı motoru kullanır ki
aralarındaki fark stratejiden gelsin, muhasebeden değil.

── TASARIM KARARLARI (hepsi gerekçeli) ──────────────────────────────────────────

1. LOOK-AHEAD: mtf.hizala() ile. O modül üst-dilim barını ancak KAPANIŞI alt barın
   kapanışına eşit/öncesindeyse gösterir ve her eşlemeyi assert eder. Naif
   reindex+ffill barların %67'sinde geleceği sızdırıyordu (mtf.py self-test).

2. SWING/LİKİDİTE SEVİYESİ *ONAYLI* KULLANILIR. i barındaki fractal swing low
   ancak i+k barında BİLİNEBİLİR (sağındaki k barı görmek gerekir). Onu i anında
   kullanmak klasik ve sinsi bir look-ahead'dir. Motor bunu `swing_k` bar
   geciktirerek uygular; `--lookahead-testi` bu gecikmeyi kaldırıp farkı gösterir.

3. MALİYET İHMAL EDİLEMEZ, ÖLÇÜLENİ KULLANILIR:
     giriş kayması 15.3bp  (kayma_denetim.py, canlı defter n=21)
     ücret 2.5bp/taraf     (gercek_pnl.py, 114 gerçek dolum — botun kaydettiği
                            1bp DEĞİL; defter ücreti 5.1 kat düşük yazıyordu)
   ⚠ BU, İNTRADAY İÇİN ÖLÜM KALIM MESELESİ. Toplam ~20bp gidiş-dönüş. Stop %2 ise
   maliyet 0.10R; stop %0.5 ise 0.40R. Aynı strateji stop mesafesine göre yaşar
   ya da ölür. Motor bu yüzden "maliyet / R" oranını HER raporda basar.

4. BASELINE PORTFÖY KISITSIZ ölçülür (koltuk/eşzamanlılık yok). Sebep: önce
   EDGE'in var olup olmadığı sorulur; portföy kısıtları edge'i seyreltir ama
   yaratmaz. Kısıtlar bir strateji baseline'ı geçerse eklenir.

5. HER PARAMETRE CONFIG'DE. Kod içinde çıplak sayı yok. Brief'in şartı.

── KULLANIM ────────────────────────────────────────────────────────────────────
    python3 edge_lab.py --self-test
    (stratejiler: edge_sweep.py / edge_vwap.py / edge_squeeze.py bunu import eder)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

import mtf

CACHE = "data"
COINS = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB",
         "XRP", "DOGE", "TRX", "XLM", "LTC", "BTC"]


# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Cfg:
    """TÜM parametreler burada. Kodda çıplak sayı YOK."""
    # zaman dilimleri
    tf_base: str = "5m"          # sinyal/teyit dilimi (veri tabanı)
    tf_setup: str = "15m"        # setup bölgesi
    tf_regime: str = "1h"        # rejim/yön
    tf_timing: str | None = None # 1m entry timing — ÖLÇÜLEN DEĞERİ ~0 (gecikme_olc)
                                 # None = kapalı. Bir strateji baseline'ı geçerse aç.
    # yapı
    swing_k: int = 3             # fractal yarı-pencere (onay gecikmesi de bu kadar)
    swing_lookback: int = 40     # "anlamlı" olmak için bu kadar barın uç değeri olmalı
    atr_period: int = 14
    # risk / çıkış
    sl_atr: float = 1.0          # yapısal seviyeye eklenen ATR tamponu
    rr_min: float = 1.5          # minimum hedef R:R — altındaysa sinyal ELENİR
    max_hold_bar: int = 96       # 5dk × 96 = 8 saat
    # maliyet (ÖLÇÜLEN — varsayılan değil)
    slip_bp: float = 15.3        # giriş kayması, kayma_denetim.py
    fee_bp: float = 2.5          # taraf başına, gercek_pnl.py (114 gerçek dolum)
    # bölme
    train_son: str = "2025-09-01"   # < bu tarih = TRAIN (parametre burada seçilir)
    test_son: str = "2026-03-01"    # TRAIN..bu = TEST (walk-forward)
                                    # bu tarihten sonrası = OOS (hiç bakılmaz)
    # motor
    bir_pozisyon_per_coin: bool = True
    ekstra: dict = field(default_factory=dict)   # stratejiye özel parametreler

    def ozet(self) -> str:
        d = asdict(self); d.pop("ekstra")
        return " · ".join(f"{k}={v}" for k, v in d.items())


# ══════════════════════════════════════════════════════════════════════════════
def yukle(coin: str, cfg: Cfg) -> dict | None:
    """5dk tabanı okur, üst dilimleri LOOK-AHEAD'SİZ hizalar."""
    p = os.path.join(CACHE, f"{coin}_bnc_{cfg.tf_base}.csv")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p, index_col=0, parse_dates=True)
    if d.index.tz is None:
        d.index = d.index.tz_localize("UTC")
    out = {"base": d}
    for ad, tf in (("setup", cfg.tf_setup), ("regime", cfg.tf_regime)):
        u = mtf.resample_tf(d, tf)
        out[ad] = u
        out[f"{ad}_pos"] = mtf.mtf_pos(d.index, u.index, cfg.tf_base, tf)
        mtf.dogrula(d.index, u.index, cfg.tf_base, tf, out[f"{ad}_pos"])
    return out


def atr(h, l, c, p: int) -> np.ndarray:
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.empty_like(tr); a[0] = tr[0]
    k = 1.0 / p
    for i in range(1, len(tr)):
        a[i] = a[i - 1] + k * (tr[i] - a[i - 1])
    return a


def swing_seviyeleri(df: pd.DataFrame, k: int, lookback: int):
    """ONAYLI fractal swing high/low.

    i barı swing low ise bunu ancak i+k barında BİLEBİLİRİZ (sağdaki k barı
    görmek gerekir). Döner diziler bu gecikmeyi İÇERİR:
        low_lvl[j]  = j barının KAPANIŞINDA bilinen en son onaylı swing low fiyatı
        low_age[j]  = o seviyenin kaç bar önce oluştuğu
    'Anlamlı' şartı: seviye, kendi oluştuğu andaki son `lookback` barın uç değeri
    olmalı — tek mumluk rastgele iğneler böyle elenir (brief'in şartı)."""
    lo = df["low"].values; hi = df["high"].values
    n = len(lo)
    lo_lvl = np.full(n, np.nan); lo_idx = np.full(n, -1, dtype=int)
    hi_lvl = np.full(n, np.nan); hi_idx = np.full(n, -1, dtype=int)
    son_lo = np.nan; son_lo_i = -1
    son_hi = np.nan; son_hi_i = -1
    for j in range(n):
        # j barında, i = j-k barının fractal olup olmadığı YENİ öğrenilir
        i = j - k
        if i - k >= 0 and i + k < n:
            pen_lo = lo[i - k:i + k + 1]
            if lo[i] == pen_lo.min() and (pen_lo == lo[i]).sum() == 1:
                gec = lo[max(0, i - lookback):i + 1]
                if lo[i] == gec.min():
                    son_lo, son_lo_i = lo[i], i
            pen_hi = hi[i - k:i + k + 1]
            if hi[i] == pen_hi.max() and (pen_hi == hi[i]).sum() == 1:
                gec = hi[max(0, i - lookback):i + 1]
                if hi[i] == gec.max():
                    son_hi, son_hi_i = hi[i], i
        lo_lvl[j], lo_idx[j] = son_lo, son_lo_i
        hi_lvl[j], hi_idx[j] = son_hi, son_hi_i
    return lo_lvl, lo_idx, hi_lvl, hi_idx


# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Sinyal:
    yon: int          # +1 long / -1 short
    sl: float         # YAPISAL invalidation fiyatı
    tp: float         # en yakın anlamlı karşı bölge
    etiket: str = ""


def kos(coin: str, veri: dict, cfg: Cfg, strateji) -> list[dict]:
    """strateji(i, veri, cfg, ctx) -> Sinyal | None    (i = 5dk bar konumu)
    Sinyal SADECE bar KAPANIŞINDA üretilir; giriş o kapanışta + kayma."""
    d = veri["base"]
    op = d["open"].values; hi = d["high"].values
    lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    ctx: dict = {}
    out = []
    kapali_kadar = -1                      # bir-pozisyon-per-coin
    for i in range(max(cfg.swing_lookback + cfg.swing_k, 300), n - 1):
        if cfg.bir_pozisyon_per_coin and i <= kapali_kadar:
            continue
        s = strateji(i, veri, cfg, ctx)
        if s is None:
            continue
        e = cl[i] * (1 + s.yon * cfg.slip_bp / 1e4)      # kayma HER ZAMAN aleyhe
        risk = abs(e - s.sl)
        if risk <= 0:
            continue
        rr = abs(s.tp - e) / risk
        if rr < cfg.rr_min:                              # brief: min RR şartı
            continue
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + cfg.max_hold_bar, n)):
            if s.yon == 1:
                if lo[j] <= s.sl: ep = s.sl; break       # aynı barda ikisi de:
                if hi[j] >= s.tp: ep = s.tp; break       # STOP önce (kötümser)
            else:
                if hi[j] >= s.sl: ep = s.sl; break
                if lo[j] <= s.tp: ep = s.tp; break
        if ep is None:
            j = min(i + cfg.max_hold_bar, n - 1); ep = cl[j]
        ucret = 2 * cfg.fee_bp / 1e4 * e                 # gidiş-dönüş taker
        R = (s.yon * (ep - e) - ucret) / risk
        out.append(dict(coin=coin, i=i, t=idx[i], cikis_t=idx[j], yon=s.yon,
                        R=float(R), rr=float(rr), risk_pct=float(risk / e),
                        maliyet_R=float((cfg.slip_bp / 1e4 * e + ucret) / risk),
                        etiket=s.etiket, bar=j - i))
        kapali_kadar = j
    return out


# ══════════════════════════════════════════════════════════════════════════════
def sentetik(n: int, tohum: int = 1, vol: float = 0.0008) -> pd.DataFrame:
    """GERÇEKÇİ sentetik OHLCV — duman testleri için.

    ⚠ NEDEN AYRI BİR FONKSİYON: ilk duman testlerimde bar şöyle üretiliyordu:
        high = c + w · low = c - w · close = c
    Kapanış HER ZAMAN barın TAM ORTASINDA kalıyordu. Mum ŞEKLİNE bakan her filtre
    (rejection, gövde, pin bar) böyle bir veride %100 eleniyor ve strateji "sinyal
    üretmiyor" gibi görünüyor — oysa hata veridedir. edge_vwap tam buna takıldı.

    Burada kapanış bar aralığı İÇİNDE rastgele konumlanıyor, açılış bir önceki
    kapanışa zincirleniyor, high/low ikisini de kapsıyor."""
    rng = np.random.default_rng(tohum)
    c = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    o = np.empty(n); o[0] = c[0]; o[1:] = c[:-1]
    tas = np.abs(rng.normal(0, vol * 1.5, n)) * c
    h = np.maximum(o, c) + tas * rng.random(n)
    l = np.minimum(o, c) - tas * rng.random(n)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": np.abs(rng.normal(100, 25, n))}, index=idx)


def veri_paketi(df: pd.DataFrame, cfg: Cfg) -> dict:
    """Bir DataFrame'i motorun beklediği çok-dilimli pakete çevirir (test/üretim ortak)."""
    out = {"base": df}
    for ad, tf in (("setup", cfg.tf_setup), ("regime", cfg.tf_regime)):
        u = mtf.resample_tf(df, tf)
        out[ad] = u
        p = mtf.mtf_pos(df.index, u.index, cfg.tf_base, tf)
        mtf.dogrula(df.index, u.index, cfg.tf_base, tf, p)
        out[f"{ad}_pos"] = p
    return out


def cli_maliyet(cfg: Cfg, argv: list[str]) -> Cfg:
    """--slip X / --fee X ile maliyet devreye alınır.

    ⚠ NEDEN BU VAR — ve neden 'parametre oynatmak' DEĞİL:
    Varsayılan 15.3bp kayma, canlı defterde DONCHIAN için ölçüldü (kayma_denetim.py).
    Donchian bir MOMENTUM kolu: piyasa emriyle, kaçan fiyatın peşinden giriyor.
    Buradaki üç strateji ise TERSİ profilde — sweep-reclaim ve VWAP dönüşü,
    zayıflığa KARŞI alım yapar. Aynı denetimde BB/MR kolu (ortalamaya dönüş,
    maker limit + piyasa yedeği) **−2.95bp** ölçüldü: sinyal fiyatından DAHA İYİ.

    Yani bu stratejilerin gerçek kayması 15.3bp ile −3bp ARASINDA bir yerde ve
    hangisi olduğu stratejiye göre değişir. Tek bir sayı seçip "işte cevap" demek
    yerine İKİ UÇ da koşulur ve sonuç BANT olarak raporlanır.
      --slip 15.3  → taker senaryosu (kötümser, momentum gibi girildiği varsayımı)
      --slip 0     → maker dolumu (BB/MR'ın canlıda başardığı şey)
    Karar KÖTÜMSER uçtan verilir; iyimser uç yalnız "ne kadarı yürütmeye bağlı"
    sorusunu yanıtlar."""
    for bayrak, alan in (("--slip", "slip_bp"), ("--fee", "fee_bp")):
        if bayrak in argv:
            i = argv.index(bayrak)
            if i + 1 < len(argv):
                setattr(cfg, alan, float(argv[i + 1]))
                print(f"  ⚠ {alan} = {getattr(cfg, alan)} (komut satırından)")
    return cfg


def _dd(r: np.ndarray) -> float:
    eq = np.cumsum(r); return float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0


def _ardisik(r: np.ndarray) -> int:
    m = c = 0
    for x in r:
        c = c + 1 if x <= 0 else 0
        m = max(m, c)
    return m


def metrik(tr: list[dict]) -> dict:
    if not tr:
        return dict(n=0)
    r = np.array([t["R"] for t in tr]); y = np.array([t["yon"] for t in tr])
    kz, kb = r[r > 0], r[r <= 0]
    def pf(x):
        a, b = x[x > 0].sum(), -x[x <= 0].sum()
        return float(a / b) if b > 0 else float("inf")
    return dict(
        n=len(r), toplamR=float(r.sum()), ortR=float(r.mean()),
        pf=pf(r), wr=float((r > 0).mean() * 100),
        ort_kazanc=float(kz.mean()) if len(kz) else 0.0,
        ort_kayip=float(kb.mean()) if len(kb) else 0.0,
        maxdd_R=_dd(r), ardisik_kayip=_ardisik(r),
        sharpe=float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if r.std(ddof=1) > 0 else 0.0,
        pf_long=pf(r[y > 0]) if (y > 0).any() else float("nan"),
        pf_short=pf(r[y < 0]) if (y < 0).any() else float("nan"),
        n_long=int((y > 0).sum()), n_short=int((y < 0).sum()),
        maliyet_R=float(np.mean([t["maliyet_R"] for t in tr])),
        risk_pct=float(np.mean([t["risk_pct"] for t in tr])),
        se=float(r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 1 else float("nan"),
    )


def satir(ad: str, m: dict) -> str:
    if not m.get("n"):
        return f"  {ad:<26s} {'—':>6s}  (işlem yok)"
    lo = m["ortR"] - 1.96 * m["se"]; hi = m["ortR"] + 1.96 * m["se"]
    return (f"  {ad:<26s} {m['n']:>6d} {m['toplamR']:>+9.1f}R {m['ortR']:>+8.4f} "
            f"[{lo:>+7.4f},{hi:>+7.4f}] {m['pf']:>6.2f} {m['wr']:>5.1f}% "
            f"{m['maxdd_R']:>7.1f} {m['ardisik_kayip']:>4d} {m['maliyet_R']:>7.3f}")


BASLIK = (f"  {'kesit':<26s} {'n':>6s} {'toplam':>10s} {'ort R':>8s} "
          f"{'%95 aralık':>18s} {'PF':>6s} {'WR':>6s} {'maxDD':>7s} {'ardk':>4s} "
          f"{'mlyt/R':>7s}")


def rapor(ad: str, tr: list[dict], cfg: Cfg) -> dict:
    print(f"\n{'='*118}\n=== {ad} ===")
    print(f"  config: {cfg.ozet()}")
    if not tr:
        print("  ⛔ HİÇ İŞLEM YOK — strateji sinyal üretmiyor."); return {}
    m = metrik(tr)
    print(f"\n{BASLIK}")
    print(satir("TÜMÜ", m))
    t = pd.to_datetime([x["t"] for x in tr], utc=True)
    tr_a = np.array(tr, dtype=object)
    for ad2, msk in (("TRAIN (<%s)" % cfg.train_son, t < cfg.train_son),
                     ("TEST (walk-forward)", (t >= cfg.train_son) & (t < cfg.test_son)),
                     ("OOS (hiç görülmedi)", t >= cfg.test_son)):
        print(satir(ad2, metrik(list(tr_a[msk]))))
    print(f"\n  yön: long n={m['n_long']} PF {m['pf_long']:.2f} · "
          f"short n={m['n_short']} PF {m['pf_short']:.2f}")
    print(f"  ort kazanç {m['ort_kazanc']:+.3f}R · ort kayıp {m['ort_kayip']:+.3f}R · "
          f"Sharpe {m['sharpe']:.2f}")
    print(f"  ort stop mesafesi %{m['risk_pct']*100:.2f} · "
          f"MALİYET {m['maliyet_R']:.3f}R/işlem  ← kayma {cfg.slip_bp}bp + ücret "
          f"{cfg.fee_bp}bp×2")
    if m["maliyet_R"] > 0.15:
        print(f"  ⚠ MALİYET AĞIR: brüt edge {m['ortR']+m['maliyet_R']:+.4f}R'nin "
              f"%{m['maliyet_R']/(abs(m['ortR'])+m['maliyet_R'])*100:.0f}'i yürütmeye gidiyor.")
    yil = pd.Series([x["R"] for x in tr]).groupby(t.year).agg(["sum", "count"])
    print(f"\n  yıl: " + " · ".join(f"{y} {v['sum']:+.1f}R (n{int(v['count'])})"
                                    for y, v in yil.iterrows()))
    return m


# ══════════════════════════════════════════════════════════════════════════════
def _self_test() -> bool:
    print("=== edge_lab SELF-TEST ===")
    ok = True
    n = 600
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    c = 100 + np.cumsum(rng.normal(0, 0.05, n))
    df = pd.DataFrame({"open": c, "high": c + 0.1, "low": c - 0.1,
                       "close": c, "volume": 1.0}, index=idx)

    lo_lvl, lo_idx, hi_lvl, hi_idx = swing_seviyeleri(df, k=3, lookback=40)
    # ONAY GECİKMESİ: j'de bilinen seviye en az k bar ÖNCE oluşmuş olmalı
    gec = [j - lo_idx[j] for j in range(n) if lo_idx[j] >= 0]
    iyi = len(gec) > 0 and min(gec) >= 3
    print(f"  swing onay gecikmesi: min {min(gec) if gec else '—'} bar (k=3) "
          f"{'✓' if iyi else '✗ LOOK-AHEAD'}")
    ok &= iyi
    # seviye gerçekten o barın low'u mu?
    j = next(j for j in range(n) if lo_idx[j] >= 0)
    iyi2 = abs(lo_lvl[j] - df["low"].values[lo_idx[j]]) < 1e-12
    print(f"  seviye fiyatı kaynağıyla eşleşiyor {'✓' if iyi2 else '✗'}")
    ok &= iyi2

    # MALİYET aritmetiği: sinyal hemen stop olursa R, −1'den maliyet kadar KÖTÜ olmalı
    cfg = Cfg(swing_lookback=10, swing_k=2, rr_min=0.1, max_hold_bar=20)
    def hep_long(i, veri, cfg, ctx):
        if i != 320: return None
        e = veri["base"]["close"].values[i]
        return Sinyal(1, e * 0.99, e * 1.02, "test")
    tr = kos("X", {"base": df}, cfg, hep_long)
    if tr:
        t0 = tr[0]
        bekl = cfg.slip_bp / 1e4 + 2 * cfg.fee_bp / 1e4
        print(f"  maliyet/R okundu {t0['maliyet_R']:.4f} · "
              f"stop %{t0['risk_pct']*100:.2f} · beklenen ≈{bekl/t0['risk_pct']:.4f} "
              f"{'✓' if abs(t0['maliyet_R'] - bekl/t0['risk_pct']) < 0.02 else '✗'}")
        ok &= abs(t0["maliyet_R"] - bekl / t0["risk_pct"]) < 0.02
    else:
        print("  ✗ test sinyali işlem üretmedi"); ok = False

    # rr_min GERÇEKTEN eliyor mu?
    cfg2 = Cfg(swing_lookback=10, swing_k=2, rr_min=5.0, max_hold_bar=20)
    tr2 = kos("X", {"base": df}, cfg2, hep_long)
    print(f"  rr_min=5.0 elemesi: {len(tr2)} işlem {'✓' if len(tr2) == 0 else '✗ ELEMİYOR'}")
    ok &= len(tr2) == 0

    # aynı barda SL+TP → STOP seçilmeli (kötümser)
    df2 = df.copy()
    df2.iloc[321, df2.columns.get_loc("low")] = 90.0
    df2.iloc[321, df2.columns.get_loc("high")] = 110.0
    tr3 = kos("X", {"base": df2}, cfg, hep_long)
    iyi3 = bool(tr3) and tr3[0]["R"] < 0
    print(f"  aynı barda SL+TP → {'STOP ✓' if iyi3 else '✗ TP seçildi (İYİMSER)'}")
    ok &= iyi3

    print(f"\n{'✓ edge_lab GÜVENİLİR' if ok else '✗ edge_lab BOZUK'}")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if _self_test() else 1)
