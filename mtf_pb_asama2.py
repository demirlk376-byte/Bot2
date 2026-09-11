"""
mtf_pb_asama2.py — MTF-PULLBACK: ORTAK 7 KOLTUKTA ÖLÇÜM + kontroller.

1) 108 hücrenin HAM sinyalleri diske önbelleklenir.
2) Her hücre ORTAK HAVUZDA (donchian+squeeze+bb+aday → A.seat_select) ölçülür.
   ÖN-KAYITLI BAR: Δ$ >= +36 · en kötü ay kötüleşmeyecek · maxDD +2 puandan fazla
   artmayacak · hiçbir yıl %10'dan fazla kötüleşmeyecek.
3) KOLTUK REKABETİ MALİYETİ = (taban$ + kol tek başına$) − birleşik$.
4) PERMÜTASYON: trend-uygun barlardan AYNI SAYIDA rastgele giriş (tetik yok sayılır).
   Tetik bilgi taşıyor mu, yoksa sonuç "trendde olmak"tan mı geliyor?
5) KORELASYON: kolun aylık PnL'i ile mevcut kitabın aylık PnL'i.
6) YÜRÜYEN-İLERİ: train'de argmax seç, test'te ölç (4 kat).

Kullanım:  py mtf_pb_asama2.py
"""
import itertools, os, pickle, sys, time
import numpy as np, pandas as pd
import fast_bt, deployed_backtest as A
import mtf_pullback as P
from mtf_pb_taban import ham_taban, strip, olc
from mtf_pb_tara import COINS, TRENDS, TETIK, STOPS, RRS, veri, kol_uret, tek_basina

SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
HAM = f"{SCR}/hucre_ham.pkl"


def tum_hucreler(V):
    if os.path.exists(HAM):
        with open(HAM, "rb") as f: return pickle.load(f)
    out = {}
    for tr, te, st, rr in itertools.product(TRENDS, TETIK, STOPS, RRS):
        out[(tr, te, f"{st[0]}{st[1]}", rr)] = kol_uret(V, trend=tr, tetik=te, stop=st, rr=rr)
    with open(HAM, "wb") as f: pickle.dump(out, f)
    return out


def kes(t, t0=None, t1=None):
    """GİRİŞ zamanına göre pencere kes (entry_ns)."""
    o = t
    if t0 is not None: o = [x for x in o if x[0] >= t0.value]
    if t1 is not None: o = [x for x in o if x[0] < t1.value]
    return o


def portfoy_olc(taban_ham, aday_ham, t0=None, t1=None):
    tb = kes(taban_ham, t0, t1); ad = kes(aday_ham, t0, t1)
    a = olc(A.seat_select(tb))
    b = olc(A.seat_select(tb + ad))
    return a, b


def main():
    V = veri()
    d = ham_taban()
    taban_ham = strip(d["donch"]) + strip(d["sqz"]) + strip(d["bb"])
    T = olc(A.seat_select(taban_ham))
    print(f"\n  TABAN {T['n']} · ${T['kar']:+.2f} · maxDD %{T['dd']:.2f} · en kötü ay %{T['kotu']:.2f}")

    t0 = time.time()
    H = tum_hucreler(V)
    print(f"  108 hücre ham sinyal hazır ({time.time()-t0:.0f}s)")

    rows = []
    for k, t in H.items():
        st = tek_basina(t)
        C = olc(A.seat_select(taban_ham + t))
        dyil = (C["yil"] - T["yil"])
        # yıl kötüleşme oranı (taban yılı pozitif; %10'dan fazla kötüleşme yasak)
        kot = float((dyil / T["yil"].abs()).min() * 100)
        gec = (C["kar"] - T["kar"] >= 36 and C["kotu"] >= T["kotu"]
               and C["dd"] - T["dd"] <= 2.0 and kot >= -10.0)
        rows.append({"trend": k[0], "tetik": k[1], "stop": k[2], "rr": k[3],
                     "kol_n": st["n"], "kol_kar": st["kar"], "kol_ortR": st["ortR"],
                     "port_n": C["n"], "port_kar": C["kar"], "d_kar": C["kar"] - T["kar"],
                     "d_dd": C["dd"] - T["dd"], "d_kotu": C["kotu"] - T["kotu"],
                     "en_kotu_yil_pct": kot,
                     "koltuk_maliyet": (T["kar"] + st["kar"]) - C["kar"],
                     "bar": "GECTI" if gec else ""})
    df = pd.DataFrame(rows).sort_values("d_kar", ascending=False)
    df.to_csv(f"{SCR}/asama2.csv", index=False)
    pd.set_option("display.width", 250)
    print(f"\n  === ORTAK 7 KOLTUK — EN İYİ 12 (Δ$ sırası) ===")
    print(df.head(12).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\n  === EN KÖTÜ 3 ===")
    print(df.tail(3).to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\n  hücre {len(df)} · Δ$>0 olan {int((df.d_kar>0).sum())} · "
          f"BARI GEÇEN {int((df.bar=='GECTI').sum())} · medyan Δ$ {df.d_kar.median():+.1f}")
    print(f"  koltuk rekabeti maliyeti: medyan ${df.koltuk_maliyet.median():+.1f} · "
          f"min ${df.koltuk_maliyet.min():+.1f} · max ${df.koltuk_maliyet.max():+.1f}")


if __name__ == "__main__":
    main()
