import numpy as np, pandas as pd
from research.oi_v1 import motor as M

H4 = M.H4


def df_yap(closes, ois, t0=None):
    t0 = t0 or M.BAS + 100 * H4
    n = len(closes)
    c = np.array(closes, float)
    df = pd.DataFrame(dict(open_time=t0 + np.arange(n) * H4, open=np.r_[c[0], c[:-1]], high=c * 1.001,
                           low=c * 0.999, close=c, volume=1.0))
    pc = df["close"].shift(1)
    tr = np.maximum(df.high - df.low, np.maximum((df.high - pc).abs(), (df.low - pc).abs()))
    df["atr"] = tr.rolling(20).mean()
    df["oi_kap"] = ois
    df["oi_ac"] = pd.Series(ois).shift(1)
    return df


def test_tc_long_sinyali_ve_zaman_cikisi():
    c = [100.0] * 30 + [90.0] + [91.0] * 10           # sert düşüş mumu (30. mum)
    oi = [1000.0] * 30 + [900.0] + [900.0] * 10        # OI −%10
    df = df_yap(c, oi)
    p = dict(k=2, theta=0.03, H=3, yon="L")
    y = M.sinyaller(df, "TC", p)
    assert y[30] == 1 and y[:30].sum() == 0
    tr = M.islemler(df, "TC", p)
    assert len(tr) == 1 and tr[0][1] == 1
    # giriş 31. mum açılışı (=90), çıkış 33. mum kapanışı (=91), stop 2×ATR
    dist = 2 * df["atr"].iloc[30]
    mal = 90 * (2 + 15.85) / 1e4 + 91 * 0.24 / 1e4
    assert abs(tr[0][2] - ((91 - 90) - mal) / dist) < 1e-9


def test_tc_oi_dusmezse_sinyal_yok():
    c = [100.0] * 30 + [90.0] + [91.0] * 10
    df = df_yap(c, [1000.0] * 41)
    assert M.sinyaller(df, "TC", dict(k=2, theta=0.03, H=3, yon="LS")).sum() == 0


def test_stop_cikisi_ve_short():
    c = [100.0] * 30 + [110.0] + [111.0] * 3 + [140.0] * 5   # yukarı tasfiye mumu → short, sonra fiyat kaçar
    oi = [1000.0] * 30 + [900.0] + [900.0] * 8
    df = df_yap(c, oi)
    p = dict(k=2, theta=0.03, H=6, yon="LS")
    tr = M.islemler(df, "TC", p)
    assert tr[0][1] == -1
    assert tr[0][2] < -0.99                                    # stopta ~−1R (+maliyet)


def test_od_tepe_short():
    c = list(np.linspace(100, 101, 30)) + [105.0] + [104.0] * 15
    oi = [1000.0] * 25 + [990, 980, 970, 960, 950] + [940.0] + [940.0] * 15
    df = df_yap(c, oi)
    y = M.sinyaller(df, "OD", dict(N=20, phi=0.05, H=6, yon="S"))
    assert y[30] == -1


def test_bootstrap_pozitif_seri():
    tr = [(M.BAS + k * 86_400_000, 1, 0.5 + 0.01 * (k % 3)) for k in range(400)]
    assert M.bootstrap_lcb(tr) > 0.4
