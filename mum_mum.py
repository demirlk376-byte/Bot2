"""
mum_mum.py — OLAY GÜDÜMLÜ, MUM MUM BACKTEST. Botun canlıda yaptığının aynısı.

NEDEN YAZILDI (kullanıcı tespiti, doğrulandı):
  Mevcut yığın ÖNCE coin coin bütün işlem listesini üretiyor (`deployed_backtest.gen`),
  SONRA `seat_select` ile 7 koltuk filtresini uyguluyor. İki yapısal sapma doğuruyor:

  1. HAYALET BLOKAJ: `gen()` satır 110'da `occ = j` HER üretilen işlem için ilerliyor —
     o işlem koltuk bulamayıp elense bile. Yani backtest'te koltuk yokluğundan reddedilen
     bir sinyal, o coini işlem süresi boyunca BLOKE ediyor. Canlı bot öyle yapmaz:
     koltuk yoksa sinyal düşer, coin serbest kalır, sonraki sinyal girebilir.
  2. GELECEK BİLGİSİ İLE KOLTUK: `seat_select` bütün işlemleri (çıkış zamanları dahil)
     önceden bilerek dağıtım yapıyor. Canlı bot koltuğu O AN bilir.

  Bu motor tek bir zaman çizgisinde ilerler: her damgada ÖNCE çıkışlar işlenir
  (koltuk boşalır), SONRA girişler değerlendirilir (koltuk o an sorulur).

BİREBİR KORUNAN ANKOR MEKANİĞİ:
  · sinyal üretimi `gen`/`gen_bb` ile AYNI (aynı sınıflar, aynı pencere, aynı kapılar)
  · giriş bar KAPANIŞINDA, çıkış taraması i+1'den
  · bar içi belirsizlikte STOP önce (muhafazakâr) — gen() ile aynı sıra
  · eşit damgada kol önceliği donchian → squeeze → bb (seat_select'in liste sırası)
  · R = yön*(çıkış-giriş)/sld − 2*FEE*e/sld
  · boyut eff = min(RISKF, CAP*sl_pct)

Kullanım:  py mum_mum.py local
"""
import sys, os, pickle
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn

ONBELLEK = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/sinyal_v1.pkl"


# ─────────────── sinyal üretimi: gen() ile AYNI, ama occ KAPISI YOK ───────────────
def sinyaller(sleeve, m):
    """(idx, hi, lo, cl, {i: (yon, sld)}) — occ gating YOK. Ankorun gen()'i ile
    satır satır aynı; tek fark `i <= occ` kontrolünün OLMAMASI."""
    if sleeve == "bb":
        from indicators import bollinger_bands
        from strategies.mean_reversion import MeanReversionStrategy
        from config import load_config
        s = MeanReversionStrategy(load_config().strategy)
        d = fast_bt.resample(m, A.BB_TF)
        hi, lo, cl, idx, n = d["high"].values, d["low"].values, d["close"].values, d.index, len(d)
        ub, _mid, lb = bollinger_bands(d["close"], 20, 2.0)
        dis = (cl < lb.values) | (cl > ub.values)
        vma = d["volume"].rolling(20).mean().values
        vok = ~(np.isfinite(vma) & (d["volume"].values < vma))
        sig = {}
        for i in np.where(dis & vok)[0]:
            i = int(i)
            if i < 260 or i >= n - 1: continue
            if idx[i].weekday() < 5: continue
            sub = d.iloc[max(0, i - 119):i + 1]
            av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            if not np.isfinite(av) or av <= 0: continue
            ax = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
            if (float(ax) if np.isfinite(ax) else 20.0) >= A.BB_ADX_MAX: continue
            d_ = s.analyze(sub).direction
            if d_ == 0: continue
            sig[i] = (d_, A.BB_SL_ATR * float(av))
        return idx, hi, lo, cl, sig, A.BB_RR, A.BB_MH

    from strategies.donchian import DonchianStrategy
    from strategies.squeeze import SqueezeStrategy
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    at = atr_fn(d["high"], d["low"], d["close"], 14).values
    ax = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dp = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dp
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi, lo, cl, idx, n = d["high"].values, d["low"].values, d["close"].values, d.index, len(d)
    sig = {}
    for i in range(260, n - 1):
        a = at[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = ax[i] if np.isfinite(ax[i]) else 20.0
            if xv <= 20.0: continue
        d_ = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)).direction
        if d_ == 0: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        sig[i] = (d_, sl_a * a)
    return idx, hi, lo, cl, sig, rr, mh


def yukle(src):
    if os.path.exists(ONBELLEK):
        with open(ONBELLEK, "rb") as f: return pickle.load(f)
    seri = {}
    for sl, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ), ("bb", A.BB_COINS)):
        for c in coins:
            seri[(sl, c)] = sinyaller(sl, fast_bt.load(c, source=src))
    os.makedirs(os.path.dirname(ONBELLEK), exist_ok=True)
    with open(ONBELLEK, "wb") as f: pickle.dump(seri, f)
    return seri


# ───────────────────────── OLAY GÜDÜMLÜ MOTOR ─────────────────────────
def kos(seri, maxpos=A.MAXPOS, hayalet_blokaj=False, ayni_bar_giris=True):
    """Tek zaman çizgisi. Her damgada: ÖNCE çıkışlar, SONRA girişler.

    hayalet_blokaj=True → ankorun davranışını taklit eder (elenen sinyal de coini
    bloke eder). İki modu karşılaştırmak sapmanın büyüklüğünü verir.

    ayni_bar_giris=False → ankorun `i <= occ` kuralı: pozisyonun ÇIKTIĞI barda o coine
    yeni giriş YASAK. Ankorla denklik testi için gerekli. Canlıda ise bot bar
    kapanışında tarama yapar ve pozisyon o an zaten kapanmıştır → True canlı-doğrudur."""
    # öncelik: kol sırası (donchian→squeeze→bb), sonra liste içindeki coin sırası
    oncelik = {}
    for k, (sl, coins) in enumerate((("donchian", A.DONCH), ("squeeze", A.SQZ), ("bb", A.BB_COINS))):
        for ci, c in enumerate(coins): oncelik[(sl, c)] = (k, ci)

    olay = []                                  # (ts_ns, oncelik_k, oncelik_ci, anahtar, i)
    for anh, (idx, *_r) in seri.items():
        k, ci = oncelik[anh]
        ns = idx.asi8
        for i in range(len(ns)): olay.append((ns[i], k, ci, anh, i))
    olay.sort(key=lambda x: (x[0], x[1], x[2]))

    acik = {}          # anahtar -> dict(yon, e, sld, slp, tp, i0, rr, mh)
    engel = {}         # anahtar -> bloke olunan son bar (yalnız hayalet_blokaj modunda)
    islem = []
    j = 0; N = len(olay)
    while j < N:
        ts = olay[j][0]; k = j
        while k < N and olay[k][0] == ts: k += 1
        grup = olay[j:k]

        # ── 1) ÇIKIŞLAR (koltuk boşalt) ──
        cikan = set()
        for _ns, _k, _ci, anh, i in grup:
            p = acik.get(anh)
            if p is None or i <= p["i0"]: continue
            idx, hi, lo, cl, _s, _rr, _mh = seri[anh]
            ep = None
            if p["yon"] == 1:
                if lo[i] <= p["slp"]: ep = p["slp"]
                elif hi[i] >= p["tp"]: ep = p["tp"]
            else:
                if hi[i] >= p["slp"]: ep = p["slp"]
                elif lo[i] <= p["tp"]: ep = p["tp"]
            if ep is None and i >= p["i0"] + p["mh"]: ep = cl[i]      # süre dolumu
            if ep is None: continue
            R = p["yon"] * (ep - p["e"]) / p["sld"] - 2 * A.FEE * p["e"] / p["sld"]
            islem.append((idx[p["i0"]].value, idx[i], R, p["sld"] / p["e"], anh[0], anh[1]))
            del acik[anh]; cikan.add(anh)

        # ── 2) GİRİŞLER (koltuk O AN sorulur) ──
        for _ns, _k, _ci, anh, i in grup:
            if anh in acik: continue
            if (not ayni_bar_giris) and anh in cikan: continue
            idx, hi, lo, cl, sig, rr, mh = seri[anh]
            t = sig.get(i)
            if t is None: continue
            if hayalet_blokaj and i <= engel.get(anh, -1): continue
            yon, sld = t
            if len(acik) >= maxpos:
                # koltuk yok → sinyal DÜŞER. Canlıda coin serbest kalır.
                if hayalet_blokaj:
                    son = min(i + mh, len(cl) - 1)
                    engel[anh] = son
                continue
            e = cl[i]
            acik[anh] = dict(yon=yon, e=e, sld=sld, slp=e - yon * sld,
                             tp=e + yon * rr * sld, i0=i, rr=rr, mh=mh)
            if hayalet_blokaj: engel[anh] = min(i + mh, len(cl) - 1)
        j = k

    # veri bitiminde açık kalanlar: son barda kapat (ankorla aynı davranış)
    for anh, p in acik.items():
        idx, hi, lo, cl, _s, _rr, _mh = seri[anh]
        i = min(p["i0"] + p["mh"], len(cl) - 1)
        R = p["yon"] * (cl[i] - p["e"]) / p["sld"] - 2 * A.FEE * p["e"] / p["sld"]
        islem.append((idx[p["i0"]].value, idx[i], R, p["sld"] / p["e"], anh[0], anh[1]))
    return sorted(islem, key=lambda t: (pd.Timestamp(t[1]).value, t[0]))


def olc(tk, riskf, cap, kayma=0.0):
    R = np.array([t[2] for t in tk]); sp = np.array([t[3] for t in tk])
    if kayma: R = R - kayma / sp
    ex = pd.to_datetime([t[1] for t in tk])
    eff = np.minimum(riskf, cap * sp); pnl = R * eff * A.BAL0
    eq = np.concatenate([[A.BAL0], A.BAL0 + np.cumsum(pnl)])
    ay = pd.Series(pnl, index=ex.tz_localize(None).to_period("M")).groupby(level=0).sum() / A.BAL0 * 100
    bil = np.concatenate([[1.0], np.cumprod(1 + R * eff)])
    return dict(n=len(R), kar=pnl.sum(), ortR=R.mean(), wr=(R > 0).mean() * 100,
                dd=A.maxdd(eq), bdd=float(((np.maximum.accumulate(bil) - bil) / np.maximum.accumulate(bil)).max() * 100),
                kotu=ay.min())


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "local"
    seri = yukle(src)
    tsig = sum(len(s[4]) for s in seri.values())
    print(f"\n{'='*100}\n=== MUM MUM (olay güdümlü) vs ANKOR (üret-sonra-filtrele) ===")
    print(f"  ham sinyal (occ kapısı yok): {tsig}")
    for ad, hb in (("MUM MUM (canlı-doğru)", False), ("hayalet blokaj AÇIK (ankor taklidi)", True)):
        tk = kos(seri, hayalet_blokaj=hb)
        for eti, rf, cp, ky in (("ankor  ", A.RISKF, A.CAP, 0.0),
                                ("canlı  ", A.CANLI_RISKF, A.CANLI_CAP, 0.0),
                                ("canlı+k", A.CANLI_RISKF, A.CANLI_CAP, 15.85/1e4)):
            m = olc(tk, rf, cp, ky)
            print(f"  {ad:<36s} {eti} n={m['n']:>5d} ${m['kar']:>+9.2f} ortR {m['ortR']:>+.4f} "
                  f"WR %{m['wr']:.1f} maxDD %{m['dd']:.2f} bileşik %{m['bdd']:.2f} kötüay %{m['kotu']:.2f}")
        kol = {}
        for t in tk: kol[t[4]] = kol.get(t[4], 0) + 1
        print(f"  {'':36s}         kol dağılımı: {kol}")
    print(f"\n  ANKOR referansı: n=1579 · ankor $+1420.66 · canlı $+1755.21 · canlı+kayma $+1331.66")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
