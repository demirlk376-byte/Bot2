"""
research_btcd.py

BTC Dominance (BTC.D) filtresi — BB fade edge'i nasıl etkiliyor?

HİPOTEZ:
  BTC.D yüksek/artıyor  → para BTC'ye akıyor, altcoinler geriliyor
                           → BTC mean-reversion daha güvenilir (kurumsal destek var)
  BTC.D düşük/azalıyor  → "alt season", BTC altcoinleri takip ediyor
                           → BTC kırılımları reversal değil, trend devamı olabilir

İKİ MOD:
  1. GERÇEK VERI: TradingView'den export edilen BTC.D CSV (günlük)
     Nasıl alınır:
       TradingView → TOTAL3/BTCUSDT değil, "BTC.D" sembolünü aç
       → Gösterge panel → Dışa Aktar → CSV
       Format beklentisi: Date,Open,High,Low,Close,Volume
     Komut: python research_btcd.py --btcd btcd_data.csv

  2. PROXY MOD (veri yokken): BTC/ETH oranı
     ETH'nin güçlendiği dönem = altcoin sezonu ≈ BTC.D düşüyor
     BTC/ETH artıyor           = BTC baskınlığı ≈ BTC.D yükseliyor
     Sadece 5 aylık örtüşme var (Sep-Dec 2025 + Apr 2026), bulgular sınırlı.
     Komut: python research_btcd.py --proxy

Run:
  python research_btcd.py --proxy           # ETH proxy ile hemen çalışır
  python research_btcd.py --btcd btcd.csv   # gerçek BTC.D verisi ile
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from indicators import bollinger_bands, atr

COST  = 0.0002
BAL   = 10_000.0
RISK  = 0.03
SL_M  = 3.0
TP_M  = 5.0
MH    = 48
SPLIT = pd.Timestamp("2026-01-01")


# ── Data ──────────────────────────────────────────────────────────────────────

def load_btc():
    files = sorted(glob.glob("/home/user/Bot2/BTCUSDT-1m-*.csv"))
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","open","high","low","close","volume"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"]).resample("1h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def load_eth():
    files = sorted(glob.glob("/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv"))
    if not files:
        return None
    frames = []
    for f in files:
        df = pd.read_csv(f).rename(columns={"open_time": "ts"})
        frames.append(df[["ts","close"]].astype(float))
    full = (pd.concat(frames, ignore_index=True)
            .drop_duplicates(subset="ts").sort_values("ts"))
    full.index = pd.to_datetime(full["ts"], unit="ms")
    return full.drop(columns=["ts"]).resample("1h").last()


def load_btcd_csv(pattern: str) -> pd.Series:
    """
    BTC.D CSV dosyalarını yükle (single file veya pattern).
    Binance format: open_time,open,high,low,close,volume,...
    BTC.D değeri 0-100 arasında yüzde (örn. 52.3 = %52.3)
    Multiple files → birleştir ve sort.
    """
    if "*" in pattern or "?" in pattern:
        # Pattern: glob ile çok dosya
        import glob
        files = sorted(glob.glob(pattern))
        if not files:
            raise FileNotFoundError(f"Dosya bulunamadı: {pattern}")
    else:
        # Single file
        files = [pattern]

    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = [c.lower().strip() for c in df.columns]
        if "open_time" in df.columns:
            df.rename(columns={"open_time": "time"}, inplace=True)
        date_col = next((c for c in df.columns if "time" in c), None)
        if date_col is None:
            raise ValueError(f"{f}: tarih kolonu yok. Kolonlar: {list(df.columns)}")
        df.index = pd.to_datetime(df[date_col], unit="ms", errors="coerce")
        close_col = next((c for c in df.columns if "close" in c), "close")
        frames.append(df[[close_col]].astype(float))

    btcd = pd.concat(frames).drop_duplicates().sort_index()[frames[0].columns[0]]
    # Binance BTCDOMUSDT 100x ile saklar (5028 = %50.28), normalize et
    if btcd.max() > 100:
        btcd = btcd / 100.0
    btcd.name = "btcd"
    return btcd


def build_btcd_proxy(df_btc_1h: pd.DataFrame, df_eth_1h: pd.DataFrame) -> pd.Series:
    """
    BTC/ETH fiyat oranı → normalize edilmiş dominance proxy.
    Yüksek oran = BTC güçlü = BTC.D yüksek.
    20 günlük z-score: 0 = nötr, + = BTC dominant, - = alt season
    """
    ratio = (df_btc_1h["close"] / df_eth_1h["close"]).dropna()
    # 480 saatlik (20 gün) rolling z-score
    roll_mean = ratio.rolling(480).mean()
    roll_std  = ratio.rolling(480).std()
    zscore = (ratio - roll_mean) / roll_std.replace(0, np.nan)
    zscore.name = "btcd_proxy"
    return zscore


# ── BB sinyallerini bul + dominance bilgisi ekle ──────────────────────────────

def find_signals_with_dom(df_1h: pd.DataFrame, dom: pd.Series) -> list[dict]:
    """
    dom: Saatlik veya günlük dominance serisi (1h'e forward-fill edilir).
    Her sinyale o andaki dominance seviyesi eklenir.
    """
    upper, _, lower = bollinger_bands(df_1h["close"], 20, 2.0)
    atr_s  = atr(df_1h["high"], df_1h["low"], df_1h["close"], 14)
    vol_ma = df_1h["volume"].rolling(20).mean()
    bb_pos = ((df_1h["close"] - lower) / (upper - lower).replace(0, np.nan))

    # Dominance → saatliğe hizala (forward-fill)
    dom_1h = dom.reindex(df_1h.index, method="ffill")

    # Dominance 20 günlük trendi (480 bar 1h)
    dom_trend = dom_1h.rolling(480).mean()
    dom_slope = dom_1h - dom_trend   # > 0 artiyor, < 0 azalıyor

    signals = []
    for i in range(60, len(df_1h)):
        bpos = bb_pos.iloc[i]
        if np.isnan(bpos) or not (bpos < 0 or bpos > 1):
            continue
        vol = df_1h["volume"].iloc[i]; vma = vol_ma.iloc[i]
        if np.isnan(vma) or vol < vma:
            continue
        a = atr_s.iloc[i]
        if np.isnan(a) or a <= 0:
            continue
        d_val  = dom_1h.iloc[i]
        d_slp  = dom_slope.iloc[i]
        if np.isnan(d_val) or np.isnan(d_slp):
            continue

        direction = 1 if bpos < 0 else -1
        ep = df_1h["close"].iloc[i]
        signals.append({
            "ts": df_1h.index[i], "i": i,
            "direction": direction, "entry": ep, "atr": a,
            "dom": d_val, "dom_slope": d_slp,
        })
    return signals


# ── Backtest ──────────────────────────────────────────────────────────────────

def run(signals: list[dict], df_1h: pd.DataFrame,
        dom_filter=None) -> list[dict]:
    """
    Tek pozisyon kuralı: açık trade varken yeni sinyal alınmaz.
    Dominance filtresi sinyal seviyesinde uygulanır (trade açılmadan önce).
    """
    c  = df_1h["close"].values
    h  = df_1h["high"].values
    lo = df_1h["low"].values

    balance    = BAL
    trades: list[dict] = []
    open_until = pd.Timestamp("2000-01-01")   # son trade kapanış zamanı

    for sig in signals:
        # Önceki trade hala açık mı?
        if sig["ts"] <= open_until:
            continue

        # Dominance filtresi
        if dom_filter is not None and not dom_filter(sig):
            continue

        i    = sig["i"]
        a    = sig["atr"]
        ep   = sig["entry"]
        d    = sig["direction"]
        sl_d = SL_M * a

        qty = min(
            round((balance * RISK) / (ep * (sl_d / ep)), 3),
            balance * 0.5 / ep
        )
        if qty < 0.001:
            continue

        sl = ep - d * sl_d
        tp = ep + d * TP_M * a

        exit_p = None; reason = None
        for j in range(i + 1, min(i + MH + 1, len(c))):
            held = j - i
            if d == 1:
                if lo[j] <= sl: exit_p, reason = sl, "sl"
                elif h[j] >= tp: exit_p, reason = tp, "tp"
            else:
                if h[j] >= sl: exit_p, reason = sl, "sl"
                elif lo[j] <= tp: exit_p, reason = tp, "tp"
            if exit_p is None and held >= MH:
                exit_p, reason = c[j], "mh"
            if exit_p is not None:
                open_until = df_1h.index[j]
                break

        if exit_p is None:
            exit_p, reason = c[min(i + MH, len(c)-1)], "mh"
            open_until = df_1h.index[min(i + MH, len(c)-1)]

        pnl = d * (exit_p - ep) * qty - (ep + exit_p) * qty * COST
        balance += pnl
        trades.append({
            "ts": open_until, "ts_entry": sig["ts"],
            "pnl": pnl, "reason": reason,
            "dom": sig["dom"], "dom_slope": sig["dom_slope"],
        })

    return trades


def stat(trades: list[dict], label: str) -> str:
    if not trades:
        return f"{label:<48}  0 trade"
    p  = np.array([t["pnl"] for t in trades])
    wr = (p > 0).mean()
    pos = p[p > 0].sum(); neg = -p[p < 0].sum()
    pf = pos / neg if neg > 0 else float("inf")
    eq = BAL + np.cumsum(p); pk = np.maximum.accumulate(eq)
    dd = ((pk - eq) / pk).max()
    tr = [t for t in trades if t["ts_entry"] < SPLIT]
    te = [t for t in trades if t["ts_entry"] >= SPLIT]
    s_tr = f"WR{(np.array([t['pnl'] for t in tr])>0).mean():.0%} ${sum(t['pnl'] for t in tr):>+7,.0f}" if tr else "—"
    s_te = f"WR{(np.array([t['pnl'] for t in te])>0).mean():.0%} ${sum(t['pnl'] for t in te):>+7,.0f}" if te else "—"
    return (f"{label:<48} {len(p):>3}t WR{wr:.0%} PF{pf:.2f} "
            f"${p.sum():>+7,.0f} ({p.sum()/100:>+5.1f}%) DD{dd*100:.0f}%"
            f" | TR {s_tr} | TE {s_te}")


def dom_bucket_analysis(trades: list[dict], dom_col: str = "dom",
                         is_proxy: bool = False) -> None:
    """Her dominance dilimindeki WR ve PnL'i göster."""
    if not trades:
        return
    df = pd.DataFrame(trades)
    vals = df[dom_col].dropna()
    if len(vals) == 0:
        return

    if is_proxy:
        # Z-score buckets
        edges  = [-3, -1.5, -0.5, 0.5, 1.5, 3]
        labels = ["çok düşük(<-1.5)", "düşük(-1.5/-0.5)",
                  "nötr(-0.5/+0.5)", "yüksek(+0.5/+1.5)", "çok yüksek(>+1.5)"]
    else:
        # Gerçek BTC.D yüzde buckets
        q = np.percentile(vals, [20, 40, 60, 80])
        edges  = [vals.min()-1] + list(q) + [vals.max()+1]
        labels = [f"D1 <{q[0]:.1f}%", f"D2 {q[0]:.1f}-{q[1]:.1f}%",
                  f"D3 {q[1]:.1f}-{q[2]:.1f}%", f"D4 {q[2]:.1f}-{q[3]:.1f}%",
                  f"D5 >{q[3]:.1f}%"]

    print(f"\n  {'Dominance dilimi':<28} {'Trade':>5}  {'WR':>5}  {'PnL':>9}  Yorum")
    for i, lbl in enumerate(labels):
        mask = (df[dom_col] > edges[i]) & (df[dom_col] <= edges[i+1])
        grp  = df[mask]
        if len(grp) == 0:
            continue
        p  = grp["pnl"].values
        wr = (p > 0).mean()
        note = "✓ iyi" if wr > 0.50 else ("✗ kötü" if wr < 0.40 else "~nötr")
        print(f"  {lbl:<28} {len(p):>5}  {wr*100:>4.0f}%  ${p.sum():>+8,.0f}  {note}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--btcd", type=str, default=None,
                        help="BTC.D CSV dosyası veya pattern (örn: BTCDOMUSDT-4h-*.csv)")
    parser.add_argument("--proxy", action="store_true",
                        help="BTC/ETH oranını BTC.D proxy olarak kullan")
    args = parser.parse_args()

    df_btc = load_btc()
    print(f"BTC 1h: {len(df_btc)} bar  ({df_btc.index[0]:%Y-%m-%d} → {df_btc.index[-1]:%Y-%m-%d})")

    is_proxy = False

    # Otomatik: BTC.D CSV'sini ara (hiçbir flag verilmemişse)
    if not args.proxy and not args.btcd:
        import glob
        if glob.glob("BTCDOMUSDT-4h-*.csv"):
            args.btcd = "BTCDOMUSDT-4h-*.csv"
            print("✓ BTCDOMUSDT-4h-*.csv bulundu, otomatik kullanılıyor\n")
        else:
            print("\nKullanım:")
            print("  python research_btcd.py                           # BTCDOMUSDT-4h-*.csv otomatik ara")
            print("  python research_btcd.py --btcd pattern            # kendi CSV pattern'i")
            print("  python research_btcd.py --proxy                   # ETH proxy (proxy mod)")
            print()
            print("Binance Data: BTCDOMUSDT-4h-YYYY-MM.csv dosyaları")
            print("  (open_time, open, high, low, close, volume format)")
            return

    # Şimdi args.btcd veya args.proxy kesin set'tir
    if args.btcd:
        # Gerçek BTC.D verisi
        btcd = load_btcd_csv(args.btcd)
        print(f"BTC.D: {len(btcd)} bar yüklendi  "
              f"({btcd.index[0]:%Y-%m-%d} → {btcd.index[-1]:%Y-%m-%d})  "
              f"ortalama {btcd.mean():.1f}%  min {btcd.min():.1f}% max {btcd.max():.1f}%")
        # 4h veya başka zaman diliminden → 1h'e dönüştür (forward-fill)
        # BTC.D her 4h değiştiği için, araya forward-fill yeterli
        btcd_1h = btcd.reindex(df_btc.index, method="ffill")
        btcd = btcd_1h
        dom_label = "BTC.D (%)"
    elif args.proxy:
        # ETH proxy modu
        df_eth = load_eth()
        if df_eth is None:
            print("ETH verisi bulunamadı (eth_data/ klasörüne bak)")
            return
        btcd = build_btcd_proxy(df_btc, df_eth)
        is_proxy = True
        print(f"BTC/ETH proxy: {btcd.dropna().shape[0]} saatlik nokta  "
              f"({btcd.dropna().index[0]:%Y-%m-%d} → {btcd.dropna().index[-1]:%Y-%m-%d})")
        print("NOT: Proxy sadece 5 aylık ETH verisi kapsıyor — bulgular sınırlı")
        dom_label = "BTC/ETH z-score"

    print("=" * 120)

    # Sinyalleri bul
    sigs = find_signals_with_dom(df_btc, btcd)
    print(f"Dominance bilgisi olan BB sinyali: {len(sigs)}")

    # Baseline (dominance filtresi yok)
    base = run(sigs, df_btc, dom_filter=None)
    print(f"\n{stat(base, 'BASELINE (dominance filtresi yok)')}")
    dom_bucket_analysis(base, is_proxy=is_proxy)

    print("\n" + "="*120)
    print("\n[DOMINANCE SEVİYESİ FİLTRELERİ]\n")

    if is_proxy:
        # Z-score tabanlı filtreler
        filters = [
            ("dom > 0 (BTC güçlü, z>0)",      lambda s: s["dom"] > 0),
            ("dom < 0 (alt season, z<0)",       lambda s: s["dom"] < 0),
            ("dom > +0.5 (belirgin BTC güçlü)", lambda s: s["dom"] > 0.5),
            ("dom < -0.5 (belirgin alt season)",lambda s: s["dom"] < -0.5),
            ("dom > +1.0 (güçlü BTC dominant)", lambda s: s["dom"] > 1.0),
        ]
    else:
        # Gerçek yüzde tabanlı filtreler
        vals = [s["dom"] for s in sigs if not np.isnan(s["dom"])]
        p40, p60 = np.percentile(vals, [40, 60])
        filters = [
            (f"dom > %{p60:.1f} (üst %40)",   lambda s, p=p60: s["dom"] > p),
            (f"dom < %{p40:.1f} (alt %40)",    lambda s, p=p40: s["dom"] < p),
            ("dom > %50",                       lambda s: s["dom"] > 50),
            ("dom > %52",                       lambda s: s["dom"] > 52),
            ("dom > %55",                       lambda s: s["dom"] > 55),
        ]

    for label, filt in filters:
        t = run(sigs, df_btc, dom_filter=filt)
        print(stat(t, label))

    print("\n" + "="*120)
    print("\n[DOMINANCE TREND FİLTRELERİ — artıyor mu, azalıyor mu?]\n")

    trend_filters = [
        ("slope > 0 (dom artıyor, BTC güçleniyor)",  lambda s: s["dom_slope"] > 0),
        ("slope < 0 (dom azalıyor, alt season başlıyor)", lambda s: s["dom_slope"] < 0),
        ("dom > 0 VE artıyor",                        lambda s: s["dom"] > 0 and s["dom_slope"] > 0),
        ("dom < 0 VE azalıyor (tam alt season)",      lambda s: s["dom"] < 0 and s["dom_slope"] < 0),
    ]

    for label, filt in trend_filters:
        t = run(sigs, df_btc, dom_filter=filt)
        print(stat(t, label))

    print("\n" + "="*120)
    print("\n[UZUN/KISA YÖN × DOMINANCE]\n")
    print("Hipotez: BTC.D yükselirken LONG, düşerken SHORT daha iyi çalışır mı?")

    dir_dom_filters = [
        ("LONG + dom > 0 (BTC güçlü → long daha güvenli)",
         lambda s: s["direction"] == 1 and s["dom"] > 0),
        ("LONG + dom < 0 (alt season → long riskli)",
         lambda s: s["direction"] == 1 and s["dom"] < 0),
        ("SHORT + dom > 0 (BTC güçlü → short riskli)",
         lambda s: s["direction"] == -1 and s["dom"] > 0),
        ("SHORT + dom < 0 (alt season → short daha güvenli)",
         lambda s: s["direction"] == -1 and s["dom"] < 0),
    ]

    for label, filt in dir_dom_filters:
        t = run(sigs, df_btc, dom_filter=filt)
        print(stat(t, label))

    print()
    print("Gerçek BTC.D verisi için: python research_btcd.py --btcd btcd_data.csv")
    print("TradingView → 'BTC.D' → Günlük → Sağ tık → Verileri Dışa Aktar")


if __name__ == "__main__":
    main()
