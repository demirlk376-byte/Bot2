"""
live_report.py — CANLI DURUM RAPORU: bot ne yapmış, backtest'i tutuyor mu?

Fiyat cache'i GEREKMEZ, sadece trades.db okur → VPS'te doğrudan çalışır.

KONTROL EDİLENLER:
 1) Kapanmış işlemler: n, WR, PF, toplam PnL  → BACKTEST BEKLENTİSİ ile karşılaştırma
 2) Çıkış sebebi dağılımı → backtest: SL %52 / TP %25 / max-hold %23
 3) R:R doğrulaması: (tp−giriş)/(giriş−sl) donchian+squeeze'de 2.5, BB'de 1.667 OLMALI
 4) Boyutlandırma: gerçekleşen risk% = |giriş−sl|×miktar / bakiye  → hedef %2.25 (tavana takılanlar
    daha düşük olur, bu NORMAL — işlemlerin ~%25'i öyle)
 5) Sleeve/coin kırılımı + açık pozisyonlar

BACKTEST ÇIPASI (düzeltilmiş, cap-aware): PF 1.44 | WR %43 | SL%52 TP%25 hold%23
UYARI: az işlemle (n<30) PF/WR gürültüdür. Asıl bakılacak: R:R ve boyut TUTUYOR MU (yapısal).

Kullanım:  python3 live_report.py /opt/bot2/trades.db [bakiye]
"""
import sys, sqlite3, json
import pandas as pd, numpy as np

DB = sys.argv[1] if len(sys.argv) > 1 else "trades.db"
BAL = float(sys.argv[2]) if len(sys.argv) > 2 else None

con = sqlite3.connect(DB)
df = pd.read_sql_query("SELECT * FROM trades", con)
con.close()
if df.empty:
    print("trades tablosu BOŞ"); sys.exit()

df["is_paper"] = df["is_paper"].astype(int)
live = df[df["is_paper"] == 0].copy()
print(f"\n{'='*88}\n=== CANLI RAPOR — {DB} ===")
print(f"  toplam kayıt {len(df)} | canlı {len(live)} | kağıt {len(df)-len(live)}")
if live.empty:
    print("  canlı işlem YOK"); sys.exit()

def sleeve_of(row):
    try:
        s = json.loads(row["strategy_scores"] or "{}")
        for k in ("sleeve", "strategy", "source"):
            if k in s: return str(s[k])
    except Exception: pass
    return "?"
live["sleeve"] = live.apply(sleeve_of, axis=1)
live["entry_time"] = pd.to_datetime(live["entry_time"], errors="coerce")
live["exit_time"] = pd.to_datetime(live["exit_time"], errors="coerce")
closed = live[live["exit_price"].notna()].copy()
open_ = live[live["exit_price"].isna()].copy()

print(f"\n  --- AÇIK POZİSYONLAR ({len(open_)}) ---")
for _, r in open_.iterrows():
    rr = abs(r["tp_price"]-r["entry_price"]) / max(abs(r["entry_price"]-r["sl_price"]), 1e-12)
    print(f"    {r['symbol']:16s} {r['side']:5s} giriş {r['entry_price']:.5f} SL {r['sl_price']:.5f} "
          f"TP {r['tp_price']:.5f}  R:R {rr:.3f}  {r['sleeve']}")

if closed.empty:
    print("\n  Kapanmış işlem YOK — R:R kontrolü açıklardan yapıldı, gerisi için bekle.")
    sys.exit()

print(f"\n  --- KAPANMIŞ İŞLEMLER ({len(closed)}) ---")
p = closed["pnl_usdt"].astype(float)
gp = p[p > 0].sum(); gl = -p[p < 0].sum()
pf = gp/gl if gl > 0 else float("inf")
print(f"    ilk {closed['entry_time'].min()}  son {closed['exit_time'].max()}")
print(f"    net PnL ${p.sum():+.2f} | WR %{(p>0).mean()*100:.0f} | PF {pf:.2f} | ort ${p.mean():+.3f}")
print(f"    BACKTEST ÇIPASI: PF 1.44 | WR %43   ← n={len(closed)} ise" +
      (" GÜRÜLTÜ, yorumlama" if len(closed) < 30 else " karşılaştırılabilir"))

print(f"\n    çıkış sebebi (backtest: sl %52 / tp %25 / hold %23):")
for rsn, cnt in closed["exit_reason"].value_counts().items():
    sub = closed[closed["exit_reason"] == rsn]["pnl_usdt"].astype(float)
    print(f"      {str(rsn):14s} n={cnt:>3d} (%{cnt/len(closed)*100:>3.0f})  PnL ${sub.sum():+7.2f}")

print(f"\n    sleeve kırılımı:")
for sv, g in closed.groupby("sleeve"):
    q = g["pnl_usdt"].astype(float)
    gp2 = q[q>0].sum(); gl2 = -q[q<0].sum()
    print(f"      {sv:12s} n={len(g):>3d} WR%{(q>0).mean()*100:>3.0f} "
          f"PF {gp2/gl2 if gl2>0 else 9.99:4.2f} PnL ${q.sum():+7.2f}")

print(f"\n    coin kırılımı:")
for sy, g in closed.groupby("symbol"):
    q = g["pnl_usdt"].astype(float)
    print(f"      {sy:16s} n={len(g):>3d} WR%{(q>0).mean()*100:>3.0f} PnL ${q.sum():+7.2f}")

# R:R yapısal doğrulama (TÜM işlemler)
print(f"\n  --- R:R DOĞRULAMASI (yapısal — az işlemle bile anlamlı) ---")
allt = live.copy()
# entry_price=0 olan kayıtlar (dolum fiyatı hiçbir yoldan okunamamış) R:R'yi
# ANLAMSIZ yapar: |tp-0|/|0-sl| = tp/sl, sinyalle ilgisi yok. Bunları ölçüme
# katmak "beklenmedik R:R" listesini gerçek olmayan satırlarla şişirir.
# Ayrıca execution.py, dolum okunamayıp niyetlenen girişin kaydedildiği işlemleri
# entry_price_estimated ile işaretler — onlar da temiz gözlem değildir.
def _estimated(row):
    try: return bool(json.loads(row["strategy_scores"] or "{}").get("entry_price_estimated"))
    except Exception: return False
allt["est"] = allt.apply(_estimated, axis=1)
_bad_entry = (allt["entry_price"] <= 0) | allt["est"]
if _bad_entry.any():
    print(f"      NOT: {_bad_entry.sum()} işlem ölçüm dışı "
          f"(giriş fiyatı okunamamış/tahmini) — R:R ve boyut istatistiklerine katılmıyor")
    allt = allt[~_bad_entry].copy()
allt["rr"] = (allt["tp_price"]-allt["entry_price"]).abs() / (allt["entry_price"]-allt["sl_price"]).abs().clip(lower=1e-12)
for sv, g in allt.groupby("sleeve"):
    exp = 1.667 if "bb" in sv.lower() or "mean" in sv.lower() else 2.5
    ok = (g["rr"].sub(exp).abs() < 0.02).mean()*100
    print(f"      {sv:12s} n={len(g):>3d} ort R:R {g['rr'].mean():.3f} (beklenen {exp}) → uyum %{ok:.0f}")
bad = allt[(allt["rr"].sub(2.5).abs() > 0.02) & (allt["rr"].sub(1.667).abs() > 0.02)]
if len(bad):
    print(f"      ⚠ BEKLENMEDİK R:R ({len(bad)} işlem):")
    for _, r in bad.head(5).iterrows():
        print(f"        {r['symbol']:14s} R:R {r['rr']:.3f} giriş {r['entry_price']:.5f} sleeve {r['sleeve']}")
else:
    print(f"      ✅ TÜM işlemler beklenen R:R'de — sinyal→emir zinciri doğru")

# boyutlandırma
if BAL:
    print(f"\n  --- BOYUTLANDIRMA (bakiye ${BAL:.2f}, hedef %2.25) ---")
    allt["risk_usd"] = (allt["entry_price"]-allt["sl_price"]).abs()*allt["quantity"].astype(float)
    allt["risk_pct"] = allt["risk_usd"]/BAL*100
    allt["notional"] = allt["entry_price"]*allt["quantity"].astype(float)
    print(f"      ort risk %{allt['risk_pct'].mean():.2f} | medyan %{allt['risk_pct'].median():.2f}")
    print(f"      tavana takılan (notional≥bakiye): {(allt['notional']>=BAL*0.98).sum()}/{len(allt)}")
    for _, r in allt.head(8).iterrows():
        print(f"        {r['symbol']:14s} risk %{r['risk_pct']:.2f} nominal ${r['notional']:.2f}")
else:
    print(f"\n  (boyutlandırma kontrolü için bakiye ver: python3 live_report.py {DB} 340)")
# ── KAPALI SLEEVE'LER NE ZAMAN DURDU + SONRASI ──────────────────────────────
DEPLOYED_SLEEVES = {"donchian", "squeeze", "mean_rev", "bb"}
print(f"\n  --- SLEEVE ZAMAN ÇİZELGESİ (ilk/son işlem) ---")
tl = live.groupby("sleeve").agg(n=("entry_time","size"), ilk=("entry_time","min"),
                                son=("entry_time","max"), pnl=("pnl_usdt","sum")).sort_values("son")
for sv, r in tl.iterrows():
    tag = "DEPLOY" if sv in DEPLOYED_SLEEVES else "KAPALI"
    print(f"      {sv:12s} [{tag}] n={int(r['n']):>3d}  {str(r['ilk'])[:16]} → {str(r['son'])[:16]}  PnL ${float(r['pnl'] or 0):+7.2f}")

off = live[~live["sleeve"].isin(DEPLOYED_SLEEVES)]
if len(off):
    cutoff = off["entry_time"].max()
    print(f"\n  --- KAPALI SLEEVE'LERİN SON İŞLEMİ: {str(cutoff)[:19]} ---")
    after = closed[closed["entry_time"] > cutoff]
    before = closed[closed["entry_time"] <= cutoff]
    for lbl, seg in (("ÖNCE (karışık)", before), ("SONRA (temiz)", after)):
        if seg.empty:
            print(f"      {lbl:16s}: işlem yok"); continue
        q = seg["pnl_usdt"].astype(float)
        gp2 = q[q > 0].sum(); gl2 = -q[q < 0].sum()
        print(f"      {lbl:16s}: n={len(seg):>3d}  PnL ${q.sum():+7.2f}  WR %{(q>0).mean()*100:>3.0f}  "
              f"PF {gp2/gl2 if gl2>0 else 9.99:4.2f}")
        for sv, g in seg.groupby("sleeve"):
            qq = g["pnl_usdt"].astype(float)
            print(f"          {sv:12s} n={len(g):>3d} PnL ${qq.sum():+7.2f}")
    if not after.empty:
        qa = after["pnl_usdt"].astype(float)
        print(f"\n      → KAPANDIKTAN SONRA: ${qa.sum():+.2f} ({len(after)} işlem)")
        print(f"        (n<30 ise bu rakam GÜRÜLTÜ — yön göstergesi, sonuç değil)")
else:
    print("\n  Kapalı sleeve işlemi yok — tüm işlemler deploy edilmiş kollardan.")
print("\nLIVEDONE")

