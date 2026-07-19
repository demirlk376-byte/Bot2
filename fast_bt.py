"""
fast_bt.py — VEKTÖREL, HIZLI backtest. Göstergeleri BİR KEZ hesaplar, sadece
sinyaller üzerinde döner → 3 yıl saniyeler sürer (replay_recent saatlerce
sürüyordu). Sleeve başına izole, yıl-yıl PF/WR/getiri.

Doğrulanmış kazananlar: donchian (BTC 4/4 yıl +) ve squeeze (BTC+SOL 4/4 yıl +).

Veri: yerel BTCUSDT-1m-*.csv (varsa) yoksa MEXC (VPS). Coin arg ile.
Kullanım:
  python fast_bt.py donchian BTC
  python fast_bt.py squeeze SOL
  python fast_bt.py all BTC          # tüm kazananlar tek coinde
"""
from __future__ import annotations
import sys, glob, os
from datetime import datetime, timezone
def datetimeutc(): return datetime.now(timezone.utc).timestamp()
import numpy as np, pandas as pd

RISK = 0.02          # sleeve başına per-trade risk (R ölçeği)
BAL = 190.0
FEE = 0.0001
CACHE_DIR = "data"   # MEXC vadeli veri önbelleği (VPS'te doldurulur, PC çevrimdışı okur)


def _cache_path(coin):
    return os.path.join(CACHE_DIR, f"{coin}_fut_1h.csv")


def _save_cache(coin, m):
    """VPS MEXC'ten çekince otomatik kaydeder → PC (MEXC engelli) çevrimdışı okur."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    m.to_csv(_cache_path(coin))
    print(f"  önbellek yazıldı: {_cache_path(coin)} ({len(m)} bar) — commit+push et, PC bunu okur")


def load(coin: str, source: str = "mexc_futures") -> pd.DataFrame:
    """CANLI-BİREBİR VERİ: varsayılan MEXC VADELİ (perp, COIN/USDT:USDT) — canlı
    botun GERÇEKTEN işlem gördüğü borsa+enstrüman. Eski hata: spot (COIN/USDT) ya
    da yerel Binance CSV çekiliyordu; spot/Binance ≠ MEXC vadeli, mumlar (wick'ler,
    funding/basis) farklı → sinyaller kayabiliyordu.
    source='local' → data/{COIN}_fut_1h.csv önbelleğinden okur (MEXC gerekmez;
      PC'de MEXC engelliyse: VPS'te bir kez fetch+kaydet+push, PC'de git pull+local).
    source='binance_csv' (yalnız BTC): yerel 1m CSV — HIZLI ama BINANCE venue,
    canlı MEXC vadeli DEĞİL. Sadece hızlı tarama; karar için mexc_futures kullan."""
    if source == "local":
        p = _cache_path(coin)
        if not os.path.exists(p):
            raise SystemExit(f"{coin}: yerel önbellek yok ({p}). Önce VPS'te "
                             f"'python faithful_all.py {coin}' çalıştır (data/ dolar), "
                             f"'git add data && git commit -m veri && git push' yap, "
                             f"PC'de 'git pull' çek.")
        m = pd.read_csv(p, index_col=0, parse_dates=True)
        print(f"  veri: yerel önbellek {p}, {len(m)} bar (ÇEVRİMDIŞI, MEXC gerekmez)")
        return m
    if source == "binance_csv" and coin == "BTC":
        files = sorted(glob.glob("BTCUSDT-1m-*.csv"))
        if files:
            print("  ⚠️  UYARI: yerel BTC CSV = BINANCE; canlı = MEXC VADELİ. Venue farkı var!")
            fr = []
            for f in files:
                d = pd.read_csv(f); d.columns = ["ts","o","h","l","c","v","ct","qv","n","a","b","g"]
                fr.append(d[["ts","o","h","l","c","v"]].astype(float))
            m = pd.concat(fr).drop_duplicates("ts").sort_values("ts")
            m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
            m = m.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
            return m.drop(columns=["ts"])
    # CANLI-BİREBİR: MEXC VADELİ (perp) — canlının fetch ettiği enstrümanın AYNISI
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}})
    sym = f"{coin}/USDT:USDT"
    since = int((datetimeutc() - 1200*86400)*1000)
    rows = []
    while True:
        b = ex.fetch_ohlcv(sym, "1h", since=since, limit=500)
        if not b: break
        rows += b
        if len(b) < 500: break
        since = b[-1][0] + 1
    if not rows:
        raise SystemExit(f"{coin}: MEXC VADELİ ({sym}) 1h verisi çekilemedi")
    m = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    m = m.drop_duplicates("ts")
    print(f"  veri: MEXC VADELİ {sym} 1h, {len(m)} bar (canlı-birebir borsa/enstrüman)")
    m = m.drop(columns=["ts"]).astype(float).iloc[:-1]   # 1h; sleeve'ler 4h'a resample eder
    try:
        _save_cache(coin, m)                              # VPS'te otomatik önbellek → PC çevrimdışı
    except Exception as e:
        print(f"  (önbellek yazılamadı: {e})")
    return m


def resample(m, tf):
    return m.resample(tf).agg({"open":"first","high":"max","low":"min",
                               "close":"last","volume":"sum"}).dropna()


def atr(df, p=14):
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/p, adjust=False).mean()


def sim(entries, df, sl_mult, rr, max_hold, atr_arr, is_atr_sl=True, rng_sl=None):
    """entries: list (i, dir). Sadece sinyaller üzerinde döner → hızlı."""
    hi = df["high"].values; lo = df["low"].values; c = df["close"].values
    idx = df.index; n = len(c)
    trades = []
    occ = -1
    for (i, d) in entries:
        if i <= occ or i >= n-1: continue
        a = atr_arr[i]
        if is_atr_sl:
            if np.isnan(a) or a <= 0: continue
            sld = sl_mult * a
        else:
            sld = rng_sl[i]
            if sld <= 0: continue
        e = c[i]
        sl = e - d*sld; tp = e + d*rr*sld
        ep = None
        for j in range(i+1, min(i+1+max_hold, n)):
            if d == 1:
                if lo[j] <= sl: ep = sl; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= sl: ep = sl; break
                if lo[j] <= tp: ep = tp; break
            occ_j = j
        if ep is None:
            j = min(i+max_hold, n-1); ep = c[j]
        r = d*(ep-e)/sld - 2*FEE*e/sld
        trades.append({"r": r, "year": idx[i].year})
        occ = j
    return trades


def donchian(m):
    # squeeze ile aynı gerekçe: TAM güven için üretim sınıfına delege edilir
    # (faithful_bt.prod_donchian = canlının get_candles(260) + DonchianStrategy'si +
    # pencere-yerel ATR). Vektörel kopya üretimden %99.1 örtüşüyordu (1 sınır barı
    # kayması); byte-denklik için üretim yolu kullanılır. 4h bar döngüsü zaten hızlı.
    import faithful_bt
    return faithful_bt.prod_donchian(m)


def squeeze(m):
    # NOT: squeeze'in VEKTÖREL kopyası ÜRETİM sınıfıyla %48 örtüşüyordu (tam-seri
    # vs 120-bar pencere göstergeleri sinyali ~1 bar kaydırıyor). verify_conformance
    # bunu yakaladı. Bu yüzden squeeze ARTIK ÜRETİM SINIFINA delege edilir
    # (faithful_bt.prod_squeeze = canlının get_candles(120) + SqueezeStrategy'si).
    # Sonuç: fast_bt squeeze == faithful_bt == CANLI, byte-denk. (donchian vektörel
    # kalır: %99 örtüşme, gerçekten hızlı, kapısız → sınır-çevirme riski yok.)
    import faithful_bt
    return faithful_bt.prod_squeeze(m)


def report(name, trades):
    if not trades:
        print(f"  {name}: sinyal yok"); return 0.0
    df = pd.DataFrame(trades)
    r = df["r"].values
    wr = (r>0).mean(); tot = r.sum()
    gp = r[r>0].sum(); gl = -r[r<0].sum()
    pf = gp/gl if gl>0 else 9.99
    usd = tot*BAL*RISK
    print(f"  {name:10s} n={len(r):>3d} WR{wr:>3.0%} PF{pf:4.2f} tot{tot:+6.1f}R ≈${usd:+7.2f}")
    for yr in sorted(df["year"].unique()):
        ry = df[df.year==yr]["r"].values
        g1 = ry[ry>0].sum(); g2 = -ry[ry<0].sum()
        pfy = g1/g2 if g2>0 else 9.99
        print(f"      {yr}  n={len(ry):>3d} WR{(ry>0).mean():>3.0%} PF{pfy:4.2f} {ry.sum()*BAL*RISK:+7.2f}$")
    return usd


def main():
    sleeve = sys.argv[1] if len(sys.argv) > 1 else "all"
    coin = sys.argv[2] if len(sys.argv) > 2 else "BTC"
    print(f"fast_bt: {sleeve} @ {coin} — veri yükleniyor...")
    m = load(coin)
    print(f"  {len(m)} 1m bar → {m.index[0].date()}..{m.index[-1].date()}")
    print(f"\n=== {coin} ===")
    if sleeve in ("donchian","all"):
        report("donchian", donchian(m))
    if sleeve in ("squeeze","all"):
        report("squeeze", squeeze(m))


if __name__ == "__main__":
    main()
