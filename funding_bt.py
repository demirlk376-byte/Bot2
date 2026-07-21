"""
funding_bt.py — FUNDING-RATE stratejisi (pro, fiyat-deseni DEĞİL).
Perp funding aşırı pozitifse long'lar kalabalık → SHORT (funding'i topla + reversal),
aşırı negatifse short'lar kalabalık → LONG. Kontrarian + carry.

Getiri = fiyat hareketi + toplanan funding. Funding geçmişi MEXC'ten çekilir
(data/{coin}_funding.csv cache), 1h fiyat cache'iyle hizalanır. Her funding olayı
(8h) bir karar; sonraki funding'e kadar tutulur.

Kullanım:
  python funding_bt.py SOL,ETH,XRP,DOGE          # VPS: funding çeker+cache+backtest
  py funding_bt.py SOL,ETH,XRP,DOGE local          # PC: cache'ten (çevrimdışı)
"""
import sys, os
import numpy as np, pandas as pd
import fast_bt

BAL = 190.0
FUND_DIR = "data"
THRESHOLDS = [0.0001, 0.0003, 0.0005, 0.001]   # |funding| eşiği (8h başına oran)


def _fpath(coin):
    return os.path.join(FUND_DIR, f"{coin}_funding.csv")


def load_funding(coin, source):
    p = _fpath(coin)
    if source == "local":
        if not os.path.exists(p):
            raise SystemExit(f"{coin}: funding cache yok ({p}). Önce VPS'te fetch et.")
        f = pd.read_csv(p, index_col=0, parse_dates=True)
        print(f"  funding: {p} ({len(f)} kayıt, çevrimdışı)"); return f
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}})
    sym = f"{coin}/USDT:USDT"
    from datetime import datetime, timezone
    since = int((datetime.now(timezone.utc).timestamp() - 1200 * 86400) * 1000)
    rows = []; last_ts = None; guard = 0
    while guard < 500:                              # sonsuz döngü koruması
        guard += 1
        b = ex.fetch_funding_rate_history(sym, since=since, limit=1000)
        if not b: break
        if last_ts is not None and b[-1]["timestamp"] <= last_ts:
            break                                  # ilerleme yoksa dur (MEXC since'i yok saydı)
        rows += b; last_ts = b[-1]["timestamp"]
        if len(b) < 1000: break
        since = b[-1]["timestamp"] + 1
    if not rows:
        raise SystemExit(f"{coin}: funding geçmişi çekilemedi")
    f = pd.DataFrame([{"ts": r["timestamp"], "rate": r["fundingRate"]} for r in rows])
    f = f.drop_duplicates("ts").sort_values("ts")
    f.index = pd.to_datetime(f["ts"], unit="ms", utc=True)
    f = f.drop(columns=["ts"])
    os.makedirs(FUND_DIR, exist_ok=True); f.to_csv(p)
    print(f"  funding yazıldı: {p} ({len(f)} kayıt) — commit+push et")
    return f


_PRICE = {}
def backtest(coin, source, thr):
    if coin not in _PRICE:
        _PRICE[coin] = fast_bt.load(coin, source="local")   # fiyat HEP cache'ten (yeniden çekme yok)
        _PRICE[coin + "_f"] = load_funding(coin, source)     # funding bir kez
    m = _PRICE[coin]; f = _PRICE[coin + "_f"]
    close = m["close"]
    rates = f["rate"].values; ftimes = f.index
    trades = []
    for i in range(len(ftimes) - 1):
        rate = rates[i]
        if abs(rate) < thr:
            continue
        d = -1 if rate > 0 else 1                  # kontrarian: yüksek funding→short
        try:
            e = float(close.asof(ftimes[i]))       # funding anındaki fiyat
            x = float(close.asof(ftimes[i + 1]))   # sonraki funding
        except Exception:
            continue
        if not (e > 0 and x > 0):
            continue
        price_ret = d * (x - e) / e
        fund_ret = -d * rate                       # short+pozitif funding → funding AL
        trades.append({"r": price_ret + fund_ret, "fund": fund_ret,
                       "price": price_ret, "year": ftimes[i].year})
    return trades


def rep(coin, thr, tr):
    if not tr:
        print(f"  {coin:5s} thr{thr}: işlem yok"); return None
    r = np.array([t["r"] for t in tr]); fu = np.array([t["fund"] for t in tr])
    yrs = np.array([t["year"] for t in tr])
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); pf = gp / gl if gl > 0 else 9.99
    usd = r.sum() * BAL                            # 1x notional yaklaşık
    print(f"  {coin:5s} thr{thr:<6}: n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} "
          f"${usd:+8.2f}  (funding payı ${fu.sum()*BAL:+.1f})", flush=True)
    per = {y: r[yrs == y].sum() * BAL for y in sorted(set(yrs.tolist()))}
    return dict(coin=coin, thr=thr, n=len(r), pf=pf, usd=usd,
                yrs_pos=all(v > 0 for v in per.values()), per=per)


def main():
    coins = [c.strip().upper() for c in (sys.argv[1] if len(sys.argv) > 1 else "BTC").split(",")]
    source = sys.argv[2] if len(sys.argv) > 2 else "mexc_futures"
    print("FUNDING-RATE kontrarian (yüksek funding→short, düşük→long; +carry)\n")
    rows = []
    for coin in coins:
        print(f"=== {coin} ===", flush=True)
        for thr in THRESHOLDS:
            try:
                row = rep(coin, thr, backtest(coin, source, thr))
                if row: rows.append(row)
            except Exception as e:
                print(f"  {coin} thr{thr}: {str(e)[:70]}"); break
    print(f"\n=== ÖZET — en iyi (coin, eşik), $ (1x, BAL190) ===", flush=True)
    for row in sorted(rows, key=lambda x: -x["usd"])[:15]:
        flag = "✅her yıl+" if row["yrs_pos"] else ""
        print(f"  {row['coin']:5s} thr{row['thr']:<6} ${row['usd']:+8.2f} PF{row['pf']:.2f} n={row['n']} {flag}", flush=True)
    print("\n  Aranan: PF>1.2 + çok coinde + her yıl+ VE funding payı anlamlı.")
    print("  Bu fiyat-deseni değil → farklı edge. İyi çıkarsa gerçek yeni bir sleeve.")


if __name__ == "__main__":
    main()
