"""IKIZ taban islemlerini zenginlestir: ozsermaye, maliyet R'leri, eszamanlilik."""
import json, numpy as np, pandas as pd
K = "/home/user/Bot2/"
d = pd.read_csv(K + "ikiz_a_taban_islemler.csv")
d["giris"] = pd.to_datetime(d.giris, utc=True); d["cikis"] = pd.to_datetime(d.cikis, utc=True)
sc = d.strategy_scores.map(json.loads)
d["intended"] = sc.map(lambda s: s.get("intended_entry", np.nan))
d["sl0"] = sc.map(lambda s: s.get("sl0", np.nan))
d["fee_rate"] = sc.map(lambda s: s.get("entry_fee_rate", np.nan))
d["sgn"] = np.where(d.side == "long", 1.0, -1.0)
d["coin"] = d.symbol.str.split("/").str[0]
# risk birimi: niyet edilen giris ile ilk stop arasi
d["risk_px"] = (d.intended - d.sl0).abs()
d["stop_pct"] = d.risk_px / d.intended
d["R_fiyat"] = d.sgn * (d.exit_price - d.entry_price) / d.risk_px          # dolum fiyatlariyla
d["R_kaymasiz"] = d.sgn * (d.exit_price - d.intended) / d.risk_px          # giris kaymasi yokmus gibi
d["kayma_R"] = d.sgn * (d.entry_price - d.intended) / d.risk_px            # + = maliyet
d["risk_usd"] = d.quantity * d.risk_px
d["R_net"] = d.pnl_usdt / d.risk_usd                                       # ucret+funding dahil
d["ucret_fund_R"] = d.R_fiyat - d.R_net
# ozsermaye: cikis sirasina gore gerceklesen
d = d.sort_values(["cikis", "giris"]).reset_index(drop=True)
d["eq_sonra"] = 10000 + d.pnl_usdt.cumsum()
cik = d.cikis.values; cum = d.pnl_usdt.cumsum().values
def eq_at(t):
    i = np.searchsorted(cik, t, side="left")
    return 10000 + (cum[i-1] if i > 0 else 0.0)
d["eq_giris"] = [eq_at(t) for t in d.giris.values]
d["ret"] = d.pnl_usdt / d.eq_giris                                         # islemin ozsermayeye etkisi
d["risk_pct"] = d.risk_usd / d.eq_giris
d["notional_x"] = d.quantity * d.entry_price / d.eq_giris
# giris aninda acik pozisyonlar (ayni yon / toplam)
g = d.giris.values; c = d.cikis.values; s = d.sgn.values
acik_ayni, acik_top = [], []
for i in range(len(d)):
    m = (g < g[i]) & (c > g[i])
    acik_top.append(int(m.sum())); acik_ayni.append(int((m & (s == s[i])).sum()))
d["acik_top"] = acik_top; d["acik_ayni"] = acik_ayni
d["yari"] = np.where(d.cikis < pd.Timestamp("2025-01-01", tz="UTC"), "TR", "TE")
d["ay"] = d.cikis.dt.tz_localize(None).dt.to_period("M")
d.to_pickle("islemler.pkl")
print(d[["R", "R_net", "R_fiyat", "kayma_R", "ucret_fund_R", "ret", "risk_pct", "notional_x"]].describe().round(4).to_string())
print("R vs R_net max fark:", (d.R - d.R_net).abs().max())
