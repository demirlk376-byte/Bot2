import numpy as np, pandas as pd
d = pd.read_pickle("islemler2.pkl").sort_values(["giris", "coin"]).reset_index(drop=True)
# ayni mumda ayni yonde acilan grup buyuklugu
d["grup"] = d.groupby(["giris", "side"]).R.transform("size")
d["grup_kol"] = d.groupby(["giris", "side", "kol"]).R.transform("size")
d["grup_b"] = pd.cut(d.grup, [0, 1, 2, 3, 99], labels=["1", "2", "3", "4+"])
def oz(g): return pd.Series({"n": len(g), "WR%": (g.R > 0).mean()*100, "ortR": g.R.mean(), "ret_top%": g.ret.sum()*100})
print("=== AYNI MUMDA AYNI YONDE KAC ISLEM ACILDI -> sonuc (islem bazinda) ===")
print(d.groupby(["grup_b", "yari"], observed=True).apply(oz).round(3).unstack("yari").to_string())
# grup bazinda: grubun toplam sonucu
gr = d.groupby(["giris", "side"]).agg(n=("R", "size"), R_top=("R", "sum"), ret=("ret", "sum"), yari=("yari", "first"),
                                      kol=("kol", lambda x: ",".join(sorted(set(x)))), hepsi_sl=("exit_reason", lambda x: (x == "sl_hit").all()))
cok = gr[gr.n >= 3]
print(f"\n>=3'lu gruplar: {len(cok)} grup, {int(cok.n.sum())} islem | grubun HEPSI stop: %{cok.hepsi_sl.mean()*100:.0f} "
      f"| grup basi ort ret %{cok.ret.mean()*100:+.2f} (TR %{cok[cok.yari=='TR'].ret.mean()*100:+.2f}, TE %{cok[cok.yari=='TE'].ret.mean()*100:+.2f})")
print(cok.assign(ret=lambda x: (x.ret*100).round(1), R_top=lambda x: x.R_top.round(2)).sort_values("ret").to_string())
print("\nkol dagilimi (grup>=2 olan islemler):", d[d.grup >= 2].kol.value_counts().to_dict(), "| toplam islemde:", d.kol.value_counts().to_dict())
d.to_pickle("islemler3.pkl")
