"""
pyramid_test.py — Donchian PİRAMİTLEME (kazanana ekleme) gerçek +EV mi? (canlı-doğru, yıl-yıl)

Turtle-native fikir: trade lehe ilerledikçe pozisyona ünite ekle. Kesin test: eklenen
ünite (add-unit) TEK BAŞINA pozitif-EV mi? Birebir tarihsel fiyat yoluyla ölçülür.

Her donchian trade'i için ileri yolu (high/low) replay et. Add-tetik = giriş yönünde
+kATR (k=0.5/1.0/1.5). Yol SL'den ÖNCE tetiğe ulaşırsa: add-unit aç (giriş=tetik fiyatı,
kendi stop'u = tetik − 2ATR [standart risk birimi], TP = tabanın TP'si), kalan yoldan
sonucu hesapla. add-unit R = (çıkış−giriş)/(2ATR). PF>1 → piramitleme +EV; PF<1 → ölü.

DÜRÜST beklenti düşük (trailing zaten reddedilmişti). Ama add-unit farklı: geç-giriş
momentum. Sonuç ne olursa olsun kanıtla kapatılır.

Kullanım:  py pyramid_test.py local
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy

BAL = 190.0; FEE = 0.0001; RISK = 0.02
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
TF, WIN, SL_A, RR, MH = "4h", 259, 2.0, 2.5, 30
TRIGGERS = [0.5, 1.0, 1.5]   # kaç ATR lehe ilerleyince ekle


def gen(m):
    d = fast_bt.resample(m, TF)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    # CANLI-BİREBİR MTF (lookahead YOK): canlı d1d=df_4h.resample("1D").close.last() +
    # ewm20 dahil-bugün; cebirsel olarak == kapanış > DÜNE kadar tamamlanmış EMA20.
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    base = []; adds = {k: [] for k in TRIGGERS}; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - WIN):i + 1], float(a)); dr = sg.direction
        if dr == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((dr == 1 and dup) or (dr == -1 and not dup)): continue
        e = cl[i]; sld = SL_A * a; slp = e - dr * sld; tp = e + dr * RR * sld; yr = idx[i].year
        # ── TABAN trade (occ'u belirler; mevcut sistemle birebir) ──
        ep = None; jend = min(i + MH, n - 1)
        for j in range(i + 1, min(i + 1 + MH, n)):
            if dr == 1:
                if lo[j] <= slp: ep = slp; jend = j; break
                if hi[j] >= tp: ep = tp; jend = j; break
            else:
                if hi[j] >= slp: ep = slp; jend = j; break
                if lo[j] <= tp: ep = tp; jend = j; break
        if ep is None: ep = cl[jend]
        base.append({"R": dr * (ep - e) / sld - 2 * FEE * e / sld, "year": yr}); occ = jend
        # ── ADD-UNIT'ler: her tetik için ileri yolu replay et (occ'u DEĞİŞTİRMEZ) ──
        for k in TRIGGERS:
            trig = e + dr * k * a          # +kATR lehe
            astop_d = SL_A * a             # kendi 2ATR stop'u (standart risk birimi)
            got = False
            for j in range(i + 1, min(i + 1 + MH, n)):
                # önce SL'e mi tetiğe mi ulaştı? (aynı barda muhafazakâr: SL önce)
                if dr == 1:
                    if lo[j] <= slp: break                      # taban SL — add hiç açılmadı
                    if hi[j] >= trig: got = True; aj = j; break
                else:
                    if hi[j] >= slp: break
                    if lo[j] <= trig: got = True; aj = j; break
            if not got: continue
            ae = trig; aslp = ae - dr * astop_d; atp = tp       # add girişi=tetik, stop kendi 2ATR, TP=taban TP
            aep = None; ajend = min(i + MH, n - 1)
            for j in range(aj, min(i + 1 + MH, n)):             # add açıldıktan sonraki yol
                if dr == 1:
                    if lo[j] <= aslp: aep = aslp; ajend = j; break
                    if hi[j] >= atp: aep = atp; ajend = j; break
                else:
                    if hi[j] >= aslp: aep = aslp; ajend = j; break
                    if lo[j] <= atp: aep = atp; ajend = j; break
            if aep is None: aep = cl[ajend]
            adds[k].append({"R": dr * (aep - ae) / astop_d - 2 * FEE * ae / astop_d, "year": yr})
    return base, adds


def st(tr):
    if not tr: return "yok"
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    return f"n={len(r):>4d} WR{(r>0).mean():>3.0%} PF{pf:4.2f} ${r.sum()*BAL*RISK:+8.2f}"


def yrbits(tr):
    return " ".join(f"{y}:${np.array([t['R'] for t in tr if t['year']==y]).sum()*BAL*RISK:+.0f}"
                    for y in sorted(set(t["year"] for t in tr)))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    base_all = []; adds_all = {k: [] for k in TRIGGERS}
    for c in DONCH:
        try: b, a = gen(fast_bt.load(c, source=source))
        except Exception as e: print(f"  {c}: {e}"); continue
        base_all += b
        for k in TRIGGERS: adds_all[k] += a[k]
    print(f"\n{'='*70}\n=== DONCHIAN PİRAMİTLEME (add-unit tek-başına EV) ===")
    print(f"  TABAN         : {st(base_all)}")
    for k in TRIGGERS:
        print(f"  add +{k:.1f}ATR   : {st(adds_all[k])}")
    print(f"\n  --- add-unit yıl-yıl (PF>1 VE her yıl+ olmalı ki piramitleme gerçek olsun) ---")
    for k in TRIGGERS:
        print(f"  add +{k:.1f}ATR   : {yrbits(adds_all[k])}")
    print("\n  add-unit PF>1 → piramitleme +EV (risk-bütçesi içinde eklenebilir).")
    print("  add-unit PF≤1 veya karışık yıl → geç-giriş edge yok, piramitleme ÖLÜ (trailing gibi).")


if __name__ == "__main__":
    main()
