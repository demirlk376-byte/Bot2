"""Bot ikizi + trend (botun 12 coini [+24 diğer]) — çakışma türleri ve tasarım seçeneklerinin değeri.
D0 bugünkü (coin başına tek pozisyon, yön fark etmez, ilk gelen kazanır)
D1 hedge modu (long ve short bacak ayrı; LONG bacakta ilk gelen kazanır, short serbest)
D3 tam çözüm (hedge + aynı bacakta ayrı stoplu çoklu pozisyon; hiç engelleme yok)
Giriş-anı bileşik, 2023-04 → 2025-08-08."""
import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")
exec(open("research/trend_takip_v1/birlesik_kisitsiz.py").read().split("bot = pd.read_csv")[0])
raw = pd.read_csv("/home/user/fpb/ikiz_y_taban_islemler.csv")
f = lambda s: (pd.to_datetime(s).map(lambda x: x.timestamp()) * 1000).astype("int64")
bot = pd.DataFrame(dict(a=f(raw.entry_time), z=f(raw.exit_time), R=raw.R, k="bot",
                        sym=raw.symbol.str.split("/").str[0], side=raw.side))
A = bot.a.min()

def trend_trades(keys):
    mods = []
    for k in keys:
        s1, s4 = sets[k]
        for N, bar, sy in ((50, C.DAY, s1), (180, V6.H4, s4)):
            mods.append(pd.DataFrame(E.simulate(f"N{N}_X5_L", (ms("2021-01-01"), B2), sy, C.TWIN_MARKET_PROFILE,
                                                early_days=10, bar_ms=bar, regime=reg, pyr_adds=2)[0]))
    tr = pd.concat(mods).sort_values("fill_time", kind="mergesort").reset_index(drop=True)
    keep, busy = [], {}
    for i, r in tr.iterrows():
        if busy.get(r.symbol, -1) > r.fill_time:
            continue
        keep.append(i); busy[r.symbol] = r.exit_time
    t = tr.loc[keep]
    return pd.DataFrame(dict(a=t.fill_time.values, z=t.exit_time.values, R=(t.net_PnL / 25.0).values, k="trend",
                             sym=t.symbol.values, side="long"))

def resolve(df, mode):
    """mode: D0/D1/D3 → engellenenler çıkarılmış işlem listesi (kronolojik ilk gelen kazanır)."""
    if mode == "D3":
        return df
    df = df.sort_values(["a", "k"]).reset_index(drop=True)
    held = []          # (z, sym, side, k)
    keep = []
    for i, r in df.iterrows():
        held = [h for h in held if h[0] > r.a]
        clash = False
        for z, sym, side, k in held:
            if sym != r.sym or k == r.k:
                continue                      # farklı coin ya da aynı sistem (sistem kendi içinde zaten tek)
            if mode == "D0" or (mode == "D1" and side == r.side):
                clash = True
        if clash:
            continue
        keep.append(i); held.append((r.z, r.sym, r.side, r.k))
    return df.loc[keep]

def run(df, rb, rt):
    df = df[(df.a >= A) & (df.z < B2)].reset_index(drop=True)
    ev = sorted([(a, 1, i) for i, a in enumerate(df.a)] + [(z, 0, i) for i, z in enumerate(df.z)])
    eq, risk, path = 1e4, {}, []
    for t, typ, i in ev:
        if typ == 1: risk[i] = eq * (rb if df.k[i] == "bot" else rt)
        else: eq += df.R[i] * risk.pop(i); path.append((t, eq))
    s = pd.Series([p for _, p in path], index=pd.to_datetime([t for t, _ in path], unit="ms"))
    m = s.resample("ME").last().ffill()
    return dict(aylik=round(100 * ((s.iloc[-1] / 1e4) ** (1 / len(m)) - 1), 1), maxDD=round(100 * (1 - s / s.cummax()).max(), 1))

T12 = trend_trades(["12"]); T24 = trend_trades(["24"])
win = lambda d: d[(d.a >= A) & (d.z < B2)]
b, t12 = win(bot), win(T12)
# çakışma sayımı: bot işlemi açılırken aynı coinde trend açık mı?
ov_same = ov_opp = 0
for _, r in b.iterrows():
    o = t12[(t12.sym == r.sym) & (t12.a <= r.a) & (t12.z > r.a)]
    if len(o):
        if r.side == "long": ov_same += 1
        else: ov_opp += 1
print(f"bot işlem {len(b)} | trend açıkken açılan bot işlemi: aynı yön (long) {ov_same}, ters yön (short) {ov_opp}")
print("bot tek:", run(b, 0.035, 0))
for lab, T in (("trend botun 12 coini", T12), ("trend 36 coin", pd.concat([T12, T24]))):
    df = pd.concat([bot, T])
    for mode in ("D0", "D1", "D3"):
        r = resolve(win(df), mode)
        nb, nt = (r.k == "bot").sum(), (r.k == "trend").sum()
        print(f"{lab} {mode}: bot {nb} trend {nt} →", run(r, 0.035, 0.01))
