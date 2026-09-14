"""cd_altbar.py — C4/C5'i DAHA INCE cozunurlukte sinar.

donchian 4h barlar uzerinde calisir; 4h bar 4 adet 1h bardan olusur. Bu yuzden
donchian islemlerinde bar ici yol 1h cozunurlukte GERCEKTEN GORULEBILIR:
  · stop mu hedef mi ONCE dokunuldu (C5 belirsizligi COZULUR)
  · stopun tetiklendigi 1h alt-barin ACILISI stopun otesinde mi (C4 gap testi)
squeeze/bb zaten 1h bar kullaniyor -> daha ince veri YOK, cozulemez.
"""
import sys, pickle, os
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB

SRC = sys.argv[1] if len(sys.argv) > 1 else "local"
SCR = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
kitap = pickle.load(open(f"{SCR}/taban_kitap.pkl","rb"))
RRS = {"donchian":2.5, "squeeze":2.5, "bb":1.667}
H1 = {c: fast_bt.load(c, source=SRC) for c in sorted({t.coin for t in kitap})}

print(f"\n{'='*118}\n=== ALT-BAR (1h) COZUNURLUGU · donchian 4h islemler ===")
don = [t for t in kitap if t.kol == "donchian"]
oth = [t for t in kitap if t.kol != "donchian"]
print(f"  donchian {len(don)} islem (4h bar -> 1h alt-bar ile cozulebilir) · "
      f"squeeze+bb {len(oth)} islem (zaten 1h, daha ince veri YOK)")

belirsiz, gap_alt, cozum = [], [], {"tp_once":0,"sl_once":0,"ayni_altbarda":0}
sl_gap_n, sl_gap_R = 0, 0.0
for t in don:
    m = H1[t.coin]
    sub = m.loc[(m.index >= t.cikis_ts) & (m.index < t.cikis_ts + pd.Timedelta("4h"))]
    if len(sub) == 0: continue
    slp = t.giris - t.yon*t.sld
    tp  = t.giris + t.yon*RRS[t.kol]*t.sld
    hi_all, lo_all = sub["high"].max(), sub["low"].min()
    sl_var = (lo_all <= slp) if t.yon==1 else (hi_all >= slp)
    tp_var = (hi_all >= tp)  if t.yon==1 else (lo_all <= tp)
    # 1h cozunurlukte sira
    ilk_sl = ilk_tp = None
    for j,(ts,r) in enumerate(sub.iterrows()):
        s_ = (r.low <= slp) if t.yon==1 else (r.high >= slp)
        p_ = (r.high >= tp) if t.yon==1 else (r.low  <= tp)
        if s_ and ilk_sl is None: ilk_sl = j
        if p_ and ilk_tp is None: ilk_tp = j
        if s_ and t.neden=="sl" and ilk_sl==j:
            o_otede = (r.open < slp) if t.yon==1 else (r.open > slp)
            if o_otede:
                sl_gap_n += 1; sl_gap_R += t.yon*(r.open-slp)/t.sld
                gap_alt.append((t.coin,str(ts)[:16],float(r.open),float(slp),t.yon))
    if sl_var and tp_var:
        belirsiz.append(t)
        if ilk_sl is None or ilk_tp is None: cozum["ayni_altbarda"]+=1
        elif ilk_tp < ilk_sl: cozum["tp_once"]+=1
        elif ilk_sl < ilk_tp: cozum["sl_once"]+=1
        else: cozum["ayni_altbarda"]+=1
        print(f"    BELIRSIZ 4h bar: {t.coin} giris {str(t.giris_ts)[:16]} cikis {str(t.cikis_ts)[:16]} "
              f"yon={t.yon:+d} KRONOS={t.neden} | 1h sira: ilk_sl={ilk_sl} ilk_tp={ilk_tp} -> "
              f"{'TP ONCE' if (ilk_tp is not None and ilk_sl is not None and ilk_tp<ilk_sl) else 'SL ONCE' if (ilk_sl is not None and (ilk_tp is None or ilk_sl<ilk_tp)) else 'AYNI 1h BARDA'}")

print(f"\n  donchian belirsiz 4h bar sayisi: {len(belirsiz)} / {len(don)} (%{len(belirsiz)/max(len(don),1)*100:.2f})")
print(f"  1h cozunurlukle sonuc: TP once {cozum['tp_once']} · SL once {cozum['sl_once']} · "
      f"ayni 1h barda (cozulemedi) {cozum['ayni_altbarda']}")
print(f"\n  C4 alt-bar gap testi: stopu tetikleyen 1h barin ACILISI stopun otesinde: "
      f"{sl_gap_n} / {sum(1 for t in don if t.neden=='sl')} stop cikisinda")
print(f"    toplam ham R etkisi: {sl_gap_R:+.5f}R")
for g in gap_alt[:10]: print(f"      {g}")

# TP cikislarinda da ayni test (limit emri gap'te AVANTAJ saglamaz, kontrol amacli)
print(f"\n{'='*118}\n=== 1h VERI SUREKLILIK DENETIMI (gap fiziksel olarak var mi?) ===")
for c,m in sorted(H1.items()):
    o=m["open"].values[1:]; pc=m["close"].values[:-1]
    d=np.abs(o-pc)/np.maximum(pc,1e-12)
    dt=m.index.to_series().diff().dropna()
    bosluk=int((dt > pd.Timedelta("1h")).sum())
    print(f"    {c:<5s} n={len(m):>6d}  zaman boslugu(>1h) {bosluk:>3d}  acilis!=onceki_kapanis {int((d>1e-12).sum()):>3d}  "
          f"ort|gap| {d.mean()*1e4:>6.3f}bp  max {d.max()*1e4:>8.2f}bp")
print(f"{'='*118}\n")
