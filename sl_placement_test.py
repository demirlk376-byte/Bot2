"""
sl_placement_test.py — SL'i likidite havuzunun ÖTESİNE koymak SL-avını azaltır mı? (canlı-doğru)

Kullanıcı sezgisi (SMC/likidite): SL'lerimiz bariz likidite seviyelerinde (swing-low altı) oturup
süpürülüyor olabilir → gereksiz SL. Öngörü değil, EXIT-YERİ kolu: SL'i yapısal seviyenin (son N
barın düşüğü = likidite havuzu) ÖTESİNE koy, TP FİYATINI AYNI tut (entry+5×ATR), %2.25 riskle boyutla.

BİLİMSEL KONTROL: düz "daha geniş ATR stop" (2.5/3×ATR) da aynı işi yaparsa → "likidite" çerçevesi
bir şey katmıyor, sadece stop-genişliği. Yapısal ATR-geniş'i belirgin geçmeli ki gerçek olsun.

TAKAS: geniş SL → daha küçük pozisyon (aynı risk) → kazançta daha az $/işlem. Net iyileşme için
SL-avındaki düşüş bunu telafi etmeli. Bottom line = toplam $ (sabit %2.25 risk), yıl-yıl.

Filtreler donchian (7 coin). Kullanım:  py sl_placement_test.py local
"""
import sys
import numpy as np
import fast_bt
from indicators import atr as atr_fn, ema as ema_fn
from strategies.donchian import DonchianStrategy

BAL0 = 190.0; FEE = 0.0001; RISKF = 0.0225
DONCH = ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]
WIN, MH = 259, 30
TP_ATR = 5.0   # TP = entry ± 5×ATR (baseline 2.5×2ATR ile AYNI — DEĞİŞMEZ)
# (isim, sl_mode, param): atr → k×ATR | swing → son N barın düşüğü/yükseği − buffer×ATR
VARIANTS = [
    ("baseline2ATR", "atr", 2.0),
    ("wide2.5ATR",   "atr", 2.5),
    ("wide3ATR",     "atr", 3.0),
    ("swing10",      "swing", 10),
    ("swing20",      "swing", 20),
]
BUF = 0.25   # yapısal stop buffer (×ATR) — likidite havuzunun biraz ötesi


def gen(m, mode, param):
    d = fast_bt.resample(m, "4h")
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    ema200 = ema_fn(d["close"], 200).values
    dd = fast_bt.resample(m, "1d"); dema = ema_fn(dd["close"], 20)
    up = (dd["close"] > dema).reindex(d.index, method="ffill").values
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values; idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - WIN):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]
        # ── SL yerleşimi ──
        if mode == "atr":
            sl_dist = param * a
        else:  # swing: yapısal seviye (likidite havuzu) + buffer
            N = int(param)
            if d_ == 1:
                lvl = np.min(lo[max(0, i - N):i])   # son N barın düşüğü (mevcut hariç)
                sl_dist = (e - lvl) + BUF * a
            else:
                lvl = np.max(hi[max(0, i - N):i])
                sl_dist = (lvl - e) + BUF * a
            if sl_dist <= 0.1 * a: sl_dist = 2.0 * a   # dejenere → baseline
        slp = e - d_ * sl_dist
        tp = e + d_ * TP_ATR * a               # TP FİYATI SABİT (entry ± 5×ATR) — değişmez
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        # R = risk birimi cinsinden (sabit %2.25 risk → boyut = risk/sl_dist)
        R = d_ * (ep - e) / sl_dist - 2 * FEE * e / sl_dist
        out.append({"R": R, "year": idx[i].year, "sl": (ep == slp)}); occ = j
    return out


def st(tr):
    if not tr: return "yok"
    r = np.array([t["R"] for t in tr]); gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    pf = gp / gl if gl > 0 else 9.99
    slrate = np.mean([t["sl"] for t in tr]) * 100
    return f"n={len(r):>4d} WR{(r>0).mean():>3.0%} SL%{slrate:>3.0f} PF{pf:4.2f} ${r.sum()*RISKF*BAL0:+8.0f}"


def yrbits(tr):
    return " ".join(f"{y}:${np.array([t['R'] for t in tr if t['year']==y]).sum()*RISKF*BAL0:+.0f}"
                    for y in sorted(set(t["year"] for t in tr)))


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "mexc_futures"
    ms = {c: fast_bt.load(c, source=source) for c in DONCH}
    print(f"\n{'='*82}\n=== SL YERLEŞİMİ (TP fiyatı SABİT entry±5×ATR, %2.25 risk) — likidite kolu ===")
    res = {}
    for name, mode, param in VARIANTS:
        tr = []
        for c in DONCH: tr += gen(ms[c], mode, param)
        res[name] = tr
        print(f"  {name:13s}: {st(tr)}")
    print(f"\n  --- yıl-yıl ---")
    for name, _, _ in VARIANTS:
        print(f"  {name:13s}: {yrbits(res[name])}")
    print("\n  ARANAN: swing (yapısal) baseline'ı toplam+PF'te HER YIL geçmeli VE ATR-geniş kontrolü de")
    print("  geçmeli (yoksa sadece 'geniş stop' etkisi, likidite değil). SL% düşüp toplam artmalı.")


if __name__ == "__main__":
    main()
