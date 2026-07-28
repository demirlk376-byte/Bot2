"""
trade_detail.py — Bir sleeve'in TÜM işlemlerini tek tek dök (mekanik hata mı, şanssızlık mı?).

Az işlemli bir sleeve zararda görününce iki ihtimal var:
  (a) ŞANSSIZLIK — R:R doğru, boyut doğru, sadece kaybetmiş → yapacak bir şey yok
  (b) MEKANİK HATA — R:R sapmış, boyut yanlış, çıkış sebebi tuhaf → düzeltilir
Bu araç ikisini ayırır: her işlemin giriş/SL/TP/çıkış, R:R, gerçekleşen R, risk%, çıkış sebebi.

Kullanım:  python3 trade_detail.py /opt/bot2/trades.db squeeze [bakiye]
"""
import sys, sqlite3, json
import pandas as pd, numpy as np

DB = sys.argv[1] if len(sys.argv) > 1 else "trades.db"
WANT = (sys.argv[2] if len(sys.argv) > 2 else "squeeze").lower()
BAL = float(sys.argv[3]) if len(sys.argv) > 3 else None

df = pd.read_sql_query("SELECT * FROM trades WHERE is_paper=0", sqlite3.connect(DB))
def sv(x):
    try:
        s = json.loads(x or "{}")
        for k in ("sleeve", "strategy", "source"):
            if k in s: return str(s[k])
    except Exception: pass
    return "?"
df["sleeve"] = df["strategy_scores"].map(sv)
g = df[df["sleeve"].str.lower() == WANT].copy()
if g.empty:
    print(f"'{WANT}' sleeve'inde işlem yok. Mevcut: {sorted(df.sleeve.unique())}"); sys.exit()

g["entry_time"] = pd.to_datetime(g["entry_time"], errors="coerce")
g = g.sort_values("entry_time")
print(f"\n{'='*100}\n=== {WANT.upper()} — {len(g)} işlem ===")
tot_r = []
for _, r in g.iterrows():
    e = float(r["entry_price"]); sl = float(r["sl_price"]); tp = float(r["tp_price"])
    risk_d = abs(e - sl)
    rr = abs(tp - e) / max(risk_d, 1e-12)
    long = str(r["side"]).lower() in ("long", "buy")
    xp = r["exit_price"]
    realR = (((float(xp) - e) if long else (e - float(xp))) / max(risk_d, 1e-12)) if pd.notna(xp) else np.nan
    if np.isfinite(realR): tot_r.append(realR)
    qty = float(r["quantity"]); risk_usd = risk_d * qty; notional = e * qty
    rp = f"{risk_usd/BAL*100:5.2f}%" if BAL else "  n/a"
    print(f"\n  {str(r['entry_time'])[:16]}  {r['symbol']:14s} {str(r['side']).upper():5s}")
    print(f"    giriş {e:.6f}  SL {sl:.6f}  TP {tp:.6f}   R:R {rr:5.3f}")
    print(f"    çıkış {('%.6f' % float(xp)) if pd.notna(xp) else 'AÇIK':>10s}  sebep {str(r['exit_reason']):12s}"
          f"  gerçekleşen {realR:+5.2f}R   PnL ${float(r['pnl_usdt'] or 0):+7.2f}")
    print(f"    miktar {qty:.4f}  nominal ${notional:8.2f}  risk ${risk_usd:5.2f} ({rp} bakiyenin)")
if tot_r:
    a = np.array(tot_r)
    print(f"\n  --- ÖZET ---")
    print(f"    toplam {a.sum():+.2f}R | ort {a.mean():+.2f}R | kazanan {(a>0).sum()}/{len(a)}")
    print(f"    kazançlar: {np.round(a[a>0],2).tolist()}")
    print(f"    kayıplar : {np.round(a[a<=0],2).tolist()}")
    print(f"    BEKLENEN: kayıp ≈ −1.00R, TP kazancı ≈ +2.50R")
    bad = a[(a < -1.15)]
    if len(bad): print(f"    ⚠ −1R'den KÖTÜ {len(bad)} kayıp: {np.round(bad,2).tolist()} → slippage/gap incele")
print("\nDETAILDONE")
