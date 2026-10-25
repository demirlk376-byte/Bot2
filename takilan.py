"""Hacim filtresine takılan son 7 günün donchian kırılımları açılsaydı ne olurdu? (salt-okur, MEXC halka açık mum)
Kurallar canlı donchian'la aynı: SL = kapanış ∓ 2×ATR14(4h) (indicators.atr), TP = kapanış ± 2.5×SL mesafesi,
en fazla 120 saat; giriş kayması 15.85 bp aleyhe, çıkış 0.24 bp, komisyon 2.5 bp/taraf; funding dahil değil.
Aynı mumda SL ve TP → SL. Risk %3.5 × 257.81 USDT."""
import sys, time
import ccxt, pandas as pd
sys.path.insert(0, "bot")
from indicators import atr

SINYAL = [("BNB", 1, "2026-10-21 08:00"), ("ICP", -1, "2026-10-22 16:00"), ("ICP", -1, "2026-10-22 20:00"),
          ("NEAR", -1, "2026-10-24 12:00"), ("ADA", -1, "2026-10-24 16:00"), ("ETH", -1, "2026-10-24 16:00"),
          ("ICP", -1, "2026-10-24 16:00"), ("NEAR", -1, "2026-10-24 16:00"), ("SOL", -1, "2026-10-24 16:00")]
GIR, CIK, UCR, RISK_USDT = 15.85e-4, 0.24e-4, 2.5e-4, 0.035 * 257.81
H = 3_600_000
ex = ccxt.mexc({"options": {"defaultType": "swap"}})


def mumlar(coin, tf, limit):
    d = ex.fetch_ohlcv(f"{coin}/USDT:USDT", tf, limit=limit)
    return pd.DataFrame(d, columns=["t", "o", "h", "l", "c", "v"])


satirlar, acik_bitis = [], {}
simdi = None
for coin, yon, kap in SINYAL:
    T = int(pd.Timestamp(kap, tz="UTC").timestamp() * 1000)
    m4 = mumlar(coin, "4h", 300); m1 = mumlar(coin, "1h", 400)
    simdi = int(m1.t.iloc[-1]) + H
    i = m4.index[m4.t == T - 4 * H]
    if len(i) == 0:
        satirlar.append((coin, yon, kap, "4h mum bulunamadı")); continue
    i = i[0]
    a = atr(m4.h.iloc[:i + 1], m4.l.iloc[:i + 1], m4.c.iloc[:i + 1], 14).iloc[-1]
    c = float(m4.c.iloc[i]); sl = c - yon * 2.0 * a; tp = c + yon * 2.5 * 2.0 * a
    tetik = "evet" if (yon == 1 and c > m4.h.iloc[i - 40:i].max()) or (yon == -1 and c < m4.l.iloc[i - 40:i].min()) else "HAYIR"
    gir = c * (1 + yon * GIR)
    son = m1[(m1.t >= T) & (m1.t < T + 120 * H)]
    cikis, neden, t_cik = None, None, None
    for _, b in son.iterrows():
        if (yon == 1 and b.l <= sl) or (yon == -1 and b.h >= sl):
            cikis, neden, t_cik = sl, "STOP", int(b.t) + H; break
        if (yon == 1 and b.h >= tp) or (yon == -1 and b.l <= tp):
            cikis, neden, t_cik = tp, "HEDEF", int(b.t) + H; break
    if cikis is None:
        if T + 120 * H <= simdi:
            cikis, neden, t_cik = float(son.c.iloc[-1]), "SÜRE (120s)", T + 120 * H
        else:
            cikis, neden, t_cik = float(son.c.iloc[-1]), "HÂLÂ AÇIK (son fiyat)", simdi
    cik = cikis * (1 - yon * CIK)
    riskp = abs(gir - sl) / gir
    R = (yon * (cik / gir - 1) - 2 * UCR) / riskp
    blok = coin in acik_bitis and acik_bitis[coin] > T
    if not blok:
        acik_bitis[coin] = t_cik
    satirlar.append((coin, "LONG" if yon == 1 else "SHORT", kap, f"kırılım={tetik}", f"giriş {gir:.4g}", f"SL {sl:.4g}",
                     f"TP {tp:.4g}", neden, f"çıkış {cik:.4g}", f"R {R:+.2f}", f"${R * RISK_USDT:+.2f}",
                     "AYNI COİNDE AÇIK POZİSYON VAR → canlıda açılmazdı" if blok else ""))
    time.sleep(0.5)

with open("veri/takilan.txt", "w") as f:
    f.write(f"şimdi = {pd.to_datetime(simdi, unit='ms', utc=True)}\n")
    top_hepsi = top_gercek = 0.0
    for s in satirlar:
        f.write(" | ".join(map(str, s)) + "\n")
        if len(s) > 10:
            v = float(s[10].replace("$", "")); top_hepsi += v
            if not s[11]: top_gercek += v
    f.write(f"\nTOPLAM (9 kırılımın hepsi): ${top_hepsi:+.2f}  ·  canlıda açılabilecekler (coin başına tek pozisyon): ${top_gercek:+.2f}\n")
print(open("veri/takilan.txt").read())
