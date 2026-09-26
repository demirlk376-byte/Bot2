import sys, os, glob, sqlite3, json
import pandas as pd
sys.path.insert(0, "/home/user/Bot2")
import ikiz_donem_analiz as DA
BURA = os.path.dirname(os.path.abspath(__file__))
REF = {"c_cap25 (PC, KARAR)": dict(n=951, te_yil=206.6, te_dd=46.0, tr_mar=8.75, te_mar=4.49),
       "c_taban (PC, KARAR)": dict(n=952, te_yil=175.0, te_dd=41.5, tr_mar=6.47, te_mar=4.22)}
print(f"{'kosu':<22s} {'islem':>6s} {'TE yil%':>8s} {'TE DD%':>7s} {'aylik%':>7s} {'TR MAR':>7s} {'TE MAR':>7s}  donch TP R")
for ad, r in REF.items():
    print(f"{ad:<22s} {r['n']:>6d} {r['te_yil']:>8.1f} {r['te_dd']:>7.1f} {'':>7s} {r['tr_mar']:>7.2f} {r['te_mar']:>7.2f}")
sonuc = {}
for yol in sorted(glob.glob(os.path.join(BURA, "ikiz_k*.db"))):
    ad = os.path.basename(yol)[5:-3]
    m = DA.olc(yol)
    if "_hata" in m: print(ad, m["_hata"]); continue
    tr, te = m["train"], m["test"]
    con = sqlite3.connect(yol)
    t = pd.read_sql("SELECT entry_price, exit_price, exit_reason, strategy_scores FROM trades WHERE exit_time IS NOT NULL", con)
    n = len(t); con.close()
    sc = t.strategy_scores.map(json.loads)
    tp = t[(t.exit_reason == "tp_hit") & sc.map(lambda s: s.get("strategy") == "donchian")]
    sl0 = sc.loc[tp.index].map(lambda s: s.get("sl0"))
    rr = ((tp.exit_price - tp.entry_price).abs() / (tp.entry_price - sl0).abs()).median()
    aylik = ((1 + te["yillik"]) ** (1 / 12) - 1) * 100
    sonuc[ad] = dict(n=n, te_yil=te["yillik"]*100, te_dd=te["maxdd"]*100, aylik=aylik, tr_mar=tr["mar"], te_mar=te["mar"])
    print(f"{ad:<22s} {n:>6d} {te['yillik']*100:>8.1f} {te['maxdd']*100:>7.1f} {aylik:>7.2f} {tr['mar']:>7.2f} {te['mar']:>7.2f}  {rr:.2f}")
json.dump(sonuc, open(os.path.join(BURA, "sonuc.json"), "w"), indent=1)
