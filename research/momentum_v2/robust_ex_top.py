"""Non-decisional robustness: rerun +W/+H with the sleeve's single largest-R trade removed (per period)."""
import importlib.util, json, sys
import pandas as pd
sys.path.insert(0, "/home/user/sweep")
OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/mom2_portfoy"
spec = importlib.util.spec_from_file_location("an", f"{OUT}/analiz.py"); A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
from research.trend_gelistirme import birlesik as BL
from research.trend_gelistirme.kos import MAL
from research.trend_gelistirme.veri import yukle, BOT12
veri, _ = yukle(BOT12)
res = {}
for don, (t_bas, t_bit, db) in A.DONEM.items():
    bot, _ = A.ikiz_islemleri(db, t_bas, t_bit)
    base = A.olc(A.aylik(pd.DataFrame(BL.MotorBirlesik(veri, "ETH", "B0", MAL["NORMAL"], C0=A.C0, t_bas=t_bas, t_bit=t_bit,
                                                         bot=bot, risk=A.TREND_RISK).kos().seri,
                                      columns=["t", "deger", "a", "b", "c"])))
    for strat in ("W", "H"):
        mom = A.mom_rows(strat, t_bas, t_bit)
        top = mom.R_raw.idxmax()
        info = dict(coin=mom.sym[top], entry=str(pd.to_datetime(mom.a[top], unit="ms")), R=round(float(mom.R_raw[top]), 2))
        mom = mom.drop(index=top)
        allb = pd.concat([bot, mom], ignore_index=True).sort_values("a", kind="mergesort").reset_index(drop=True)
        m = BL.MotorBirlesik(veri, "ETH", "B0", MAL["NORMAL"], C0=A.C0, t_bas=t_bas, t_bit=t_bit, bot=allb,
                             risk=A.TREND_RISK).kos()
        x = A.olc(A.aylik(pd.DataFrame(m.seri, columns=["t", "deger", "a", "b", "c"])))
        res[f"{strat}_ex_top|{don}"] = dict(removed=info, mult=round(x["mult"], 3), maxdd=round(x["maxdd"] * 100, 2),
                                            ratio=round(x["ratio"], 3), base_mult=round(base["mult"], 3),
                                            base_ratio=round(base["ratio"], 3), base_maxdd=round(base["maxdd"] * 100, 2))
        print(strat, don, res[f"{strat}_ex_top|{don}"])
json.dump(res, open(f"{OUT}/robust_ex_top.json", "w"), indent=1)
