"""trend_genislet ON_KAYIT: bir (varyant, donem) kosusu. Kullanim: python3 kos_tek.py <T12|T38|T38_R1> <KESIF|BAGIMSIZ>
Cikti: <OUT>/<varyant>_<donem>.pkl (seri, islemler, olaylar, acik pozisyonlar, bot sayaclari)."""
import json, os, pickle, sqlite3, sys, time, glob
import pandas as pd

sys.path.insert(0, "/home/user/sweep")
from research.trend_gelistirme import birlesik as BL
from research.trend_gelistirme.veri import yukle, BOT12, D4
from research.trend_gelistirme.kos import MAL

OUT = os.path.dirname(os.path.abspath(__file__))
SP = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/ikiz_kanit"
T12 = "SOL ETH ADA NEAR BCH XRP DOGE TRX XLM LTC ICP BNB".split()
assert T12 == BOT12
T38 = sorted(os.path.basename(p)[:-len("_4h.csv")] for p in glob.glob(os.path.join(D4, "*_4h.csv")))
assert len(T38) == 38 and "ETH" in T38 and set(T12) <= set(T38)

VARY = {"T12": (T12, 0.015), "T38": (T38, 0.015), "T38_R1": (T38, 0.010)}
TAVAN = 0.24
DONEM = {"KESIF": (BL.ms("2023-04-07"), BL.ms("2026-07-18"), os.path.join(SP, "ikiz_gercek.db")),
         "BAGIMSIZ": (BL.ms("2020-02-01"), BL.ms("2023-04-07"), os.path.join(SP, "ikiz_eski.db"))}


def bot_islemleri(db, t_bas, t_bit):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute("select symbol,entry_price,quantity,entry_time,exit_time,pnl_usdt,strategy_scores from trades "
                     "order by entry_time").fetchall()
    f = lambda s: int(pd.Timestamp(s).timestamp() * 1000)
    out, atlanan_gecersiz = [], 0
    for sym, E, q, et, xt, pnl, sc in rows:
        j = json.loads(sc or "{}")
        kol = j.get("strategy")
        assert kol != "squeeze", "ikizde squeeze islemi var"
        sl0 = float(j.get("sl0") or 0)
        risk = abs(E - sl0) * q
        if risk <= 0 or pnl is None or xt is None:
            atlanan_gecersiz += 1
            continue
        out.append(dict(sym=sym, a=f(et), z=f(xt), R=pnl / risk, notional=E * q, pnl=pnl, kol=kol))
    df = pd.DataFrame(out).sort_values("a").reset_index(drop=True)
    kap = df.sort_values("z")[["z", "pnl"]].to_numpy()
    df["ikiz_bakiye"] = [10_000 + kap[kap[:, 0] <= a, 1].sum() for a in df.a]
    df["teminat_oran"] = (df.notional / df.ikiz_bakiye) / 10.0
    pen = df[(df.a >= t_bas) & (df.a < t_bit)]
    sayac = dict(db_toplam=len(rows), gecersiz=atlanan_gecersiz, pencere_giris=len(pen),
                 cikis_pencere_disi=int((pen.z >= t_bit).sum()),
                 cikis_pencere_disi_R=float(pen[pen.z >= t_bit].R.sum()))
    pen = pen[pen.z < t_bit].reset_index(drop=True)
    sayac["kullanilan"] = len(pen)
    sayac["kol"] = pen.kol.value_counts().to_dict()
    return pen, sayac


def main():
    v, d = sys.argv[1], sys.argv[2]
    coinler, risk = VARY[v]
    t_bas, t_bit, db = DONEM[d]
    bot, sayac = bot_islemleri(db, t_bas, t_bit)
    veri, ex = yukle(coinler)
    # EOS ve FIL: mexc_contract_detail.json icinde sozlesme metadatasi yok -> standart yukleyici disarida birakir
    assert set(ex) <= {"EOS", "FIL"} and all(x == "MEXC_METADATA_YOK" for x in ex.values()), ex
    assert set(veri) | set(ex) == set(coinler) and "ETH" in veri
    coinler = sorted(veri)
    t0 = time.time()
    m = BL.MotorBirlesik(veri, "ETH", "B0", MAL["NORMAL"], t_bas=t_bas, t_bit=t_bit, bot=bot, risk=risk,
                         acik_risk_tavan=TAVAN).kos()
    assert m.bi == len(bot) or all(bot.a[m.bi:] >= t_bit)
    # donem sonunda acik trend pozisyonlari (son kapanisla isaretli)
    acik = []
    for k, p in m.poz.items():
        coin = veri[k]
        i = coin.idx.get(m.saat[-1])
        px = coin.c[i] if i is not None else None
        acik.append(dict(coin=k, giris_t=p.giris_t, lots=len(p.lots), son_px=px,
                         son_veri_t=int(coin.t[-1]),
                         acik_pnl=(sum((px - l.E) * l.q for l in p.lots) if px is not None else
                                   sum((p.lots[-1].E - l.E) * l.q for l in p.lots)) + p.funding
                                  - sum(l.ucret for l in p.lots)))
    res = dict(varyant=v, donem=d, coinler=coinler, disarida=ex, risk=risk, tavan=TAVAN, t_bas=t_bas, t_bit=t_bit, db=db,
               bot_sayac=sayac, bot_alinan=m.bot_alinan, bot_atlanan=m.bot_atlanan,
               seri=m.seri, islemler=m.islemler, olaylar=m.olaylar, acik=acik, sure=time.time() - t0,
               son_deger=m.son_deger, cuzdan=m.cuzdan)
    pickle.dump(res, open(os.path.join(OUT, f"{v}_{d}.pkl"), "wb"))
    print(v, d, f"{time.time() - t0:.0f}s", "son", round(m.son_deger, 1), "trend", len(m.islemler),
          "bot", m.bot_alinan, "atlanan", m.bot_atlanan, sayac)


if __name__ == "__main__":
    main()
