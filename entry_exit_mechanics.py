"""
entry_exit_mechanics.py — İşlem SİLMEYEN üç mekanik: giriş fiyatı · yeniden giriş · yapısal çıkış.

NEDEN BU ÜÇÜ: bugüne kadar reddedilen her şey ya FİLTREydi (işlem siler) ya PARAMETREydi.
Permütasyon bulgusu: işlem silmek HER KOŞULDA negatif beklentili. Bu üçü işlem SİLMİYOR —
aynı sinyalleri alıyor, sadece nasıl girildiğini/çıkıldığını değiştiriyor. Hiçbiri test edilmedi.

── A) GİRİŞ FİYATI RAFİNESİ (en güçlü gerekçe: ÖLÇÜLMÜŞ sorun) ──
Canlıda donchian giriş kayması ÖLÇÜLDÜ: +13.4 bp (medyan +11.3), diğer sleeve'lerde ~0.
Sebep: 4h mumu kapanınca piyasa emri gidiyor, o arada fiyat kırılım yönünde koşuyor.
Backtest ise sinyal barının KAPANIŞINDA dolduğunu varsayıyor → backtest ~%12 iyimser.
SORU: 4h sinyalinden sonra 1h granülaritesinde daha iyi bir dolum alınabilir mi?
Varyantlar (SL/TP sinyal kapanışına ÇAPALI kalır — canlıdaki gibi; sadece GİRİŞ değişir):
  lim0    : sinyal kapanışında limit, sonraki 4 adet 1h barı bekle, dolmazsa 4h kapanışında piyasa
  lim25   : sinyal kapanışı − 0.25×ATR'de limit (geri çekilme), aynı pencere, dolmazsa piyasa
  lim50   : sinyal kapanışı − 0.50×ATR'de limit, aynı pencere, dolmazsa piyasa
  next1h  : sonraki 1h barın kapanışında gir (beklemenin maliyeti/faydası saf ölçüm)
KRİTİK: dolmazsa PİYASAYA düşer → işlem SİLİNMEZ, sadece fiyat değişir.

── B) STOP SONRASI YENİDEN GİRİŞ ──
Stop olduktan sonra trend devam ederse, yeni bir 40-bar kırılımı gerekmiyor olabilir.
Varyant: stop olduktan sonraki N bar içinde kapanış ORİJİNAL kanal üstünü tekrar aşarsa yeniden gir.
(occ korunur: aynı anda tek pozisyon. Yeni işlem EKLER, silmez.)

── C) YAPISAL ÇIKIŞ (karşı kanal) ──
Çıkış şu an SL/TP/maxhold. Ek: long'da kapanış K-bar en düşüğünün altına inerse çık.
Bu trailing DEĞİL (volatiliteye değil YAPIYA bağlı) ve TP'yi kaldırmıyor — ek bir çıkış kapısı.

METODOLOJİ: TRAIN(2023-24) seç → TEST BİR KEZ → HER YIL → büyüklük %2 → doz-tepki.
Taban doğrulaması zorunlu (n=1579 $+1421).

Kullanım:  py entry_exit_mechanics.py local
"""
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB
from indicators import atr as atr_fn, ema as ema_fn

TRAIN_END_NS = pd.Timestamp("2025-01-01", tz="UTC").value
MH, SL_A, RR = 30, 2.0, 2.5


def gen(m1h, mode="base", lim_atr=0.0, reentry_n=0, exit_ch=0):
    """4h sinyal üretimi + 1h granülaritesinde giriş dolumu.

    m1h: ham 1h veri (4h bunun resample'ı). 4h bar i, 1h barlar [4i, 4i+3]'e karşılık gelir;
    sinyal 4h bar i'nin KAPANIŞINDA doğar → dolum penceresi 4h bar i+1'in 1h barlarıdır.
    """
    d = fast_bt.resample(m1h, "4h")
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    ema200 = ema_fn(d["close"], 200).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up_mtf = d["close"].values > _dprev
    ch_hi = d["high"].rolling(40).max().shift(1).values
    ch_lo = d["low"].rolling(40).min().shift(1).values
    ex_lo = d["low"].rolling(exit_ch).min().shift(1).values if exit_ch else None
    ex_hi = d["high"].rolling(exit_ch).max().shift(1).values if exit_ch else None
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    # 4h index → 1h dilim eşlemesi (dolum penceresi için)
    h1 = m1h if isinstance(m1h.index, pd.DatetimeIndex) else m1h
    h1i = h1.index; h1c = h1["close"].values; h1h = h1["high"].values; h1l = h1["low"].values
    pos = np.searchsorted(h1i.values, idx.values)     # her 4h barın 1h başlangıcı

    out = []; occ = -1
    i = 260
    while i < n - 1:
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ or not np.isfinite(ema200[i]):
            i += 1; continue
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i])): i += 1; continue
        c = cl[i]; d_ = 0
        if c > ch_hi[i] and c > ema200[i]: d_ = 1
        elif c < ch_lo[i] and c < ema200[i]: d_ = -1
        if d_ == 0: i += 1; continue
        dup = bool(up_mtf[i]) if not (isinstance(up_mtf[i], float) and np.isnan(up_mtf[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): i += 1; continue

        sig = c; sld = SL_A * a
        slp = sig - d_ * sld; tp = sig + d_ * RR * sld      # SL/TP SİNYALE ÇAPALI (canlı gibi)

        # ── GİRİŞ FİYATI ──
        entry = sig; start_bar = i + 1
        if mode in ("lim", "next1h"):
            s0 = int(pos[i + 1]) if i + 1 < n else len(h1c)
            s1 = min(s0 + 4, len(h1c))
            if mode == "next1h":
                entry = h1c[s0] if s0 < len(h1c) else sig
            else:
                lvl = sig - d_ * lim_atr * a          # geri çekilme limiti (lim_atr=0 → sinyalde)
                filled = False
                for k in range(s0, s1):
                    if (d_ == 1 and h1l[k] <= lvl) or (d_ == -1 and h1h[k] >= lvl):
                        entry = lvl; filled = True; break
                if not filled:
                    entry = cl[i + 1] if i + 1 < n else sig     # 4h kapanışında piyasa (İŞLEM SİLİNMEZ)

        # ── ÇIKIŞ ──
        ep = None; j = i
        for j in range(start_bar, min(start_bar + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
                if exit_ch and np.isfinite(ex_lo[j]) and cl[j] < ex_lo[j]: ep = cl[j]; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
                if exit_ch and np.isfinite(ex_hi[j]) and cl[j] > ex_hi[j]: ep = cl[j]; break
        if ep is None: j = min(start_bar + MH - 1, n - 1); ep = cl[j]
        R = d_ * (ep - entry) / sld - 2 * DB.FEE * entry / sld
        out.append((idx[i].value, idx[j], R, sld / entry)); occ = j

        # ── B) STOP SONRASI YENİDEN GİRİŞ ──
        if reentry_n and ep == slp:
            lvl = ch_hi[i] if d_ == 1 else ch_lo[i]
            for k in range(j + 1, min(j + 1 + reentry_n, n - 1)):
                if (d_ == 1 and cl[k] > lvl) or (d_ == -1 and cl[k] < lvl):
                    a2 = a_ser[k]
                    if not np.isfinite(a2) or a2 <= 0: break
                    e2 = cl[k]; s2 = SL_A * a2
                    sp2 = e2 - d_ * s2; tp2 = e2 + d_ * RR * s2
                    ep2 = None; j2 = k
                    for j2 in range(k + 1, min(k + 1 + MH, n)):
                        if d_ == 1:
                            if lo[j2] <= sp2: ep2 = sp2; break
                            if hi[j2] >= tp2: ep2 = tp2; break
                        else:
                            if hi[j2] >= sp2: ep2 = sp2; break
                            if lo[j2] <= tp2: ep2 = tp2; break
                    if ep2 is None: j2 = min(k + MH, n - 1); ep2 = cl[j2]
                    R2 = d_ * (ep2 - e2) / s2 - 2 * DB.FEE * e2 / s2
                    out.append((idx[k].value, idx[j2], R2, s2 / e2)); occ = j2
                    break
        i = occ + 1
    return out


def seat(tr):
    ev = sorted(tr, key=lambda t: t[0]); openh = []; tk = []; ctr = 0
    for ens, ex, R, sp in ev:
        while openh and openh[0][0].value <= ens: heapq.heappop(openh)
        if len(openh) < DB.MAXPOS:
            ctr += 1; heapq.heappush(openh, (ex, ctr, R)); tk.append((ens, ex, R, sp))
    return tk


def stats(tk):
    if not tk: return None
    r = np.array([t[2] for t in tk]); sp = np.array([t[3] for t in tk])
    ens = np.array([t[0] for t in tk], dtype="int64")
    ya = np.array([pd.Timestamp(t[1]).year for t in tk])
    pnl = r * np.minimum(DB.RISKF, DB.CAP * sp) * DB.BAL0
    gp = r[r > 0].sum(); gl = -r[r < 0].sum(); m = ens < TRAIN_END_NS
    return dict(n=len(r), pf=gp / max(gl, 1e-9), wr=(r > 0).mean() * 100, tot=float(pnl.sum()),
                train=float(pnl[m].sum()), test=float(pnl[~m].sum()),
                yrs={int(y): float(pnl[ya == y].sum()) for y in sorted(set(ya.tolist()))})


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    ms = {c: fast_bt.load(c, source=source) for c in DB.DONCH}
    others = []
    for c in DB.SQZ: others += DB.gen("squeeze", fast_bt.load(c, source=source))
    for c in DB.BB_COINS: others += DB.gen_bb(fast_bt.load(c, source=source))

    def run(**kw):
        tr = []
        for c in DB.DONCH: tr += gen(ms[c], **kw)
        return stats(seat(tr + others))

    VAR = [
        ("TABAN (4h kapanışta)", {}),
        ("A) lim @sinyal",        dict(mode="lim", lim_atr=0.0)),
        ("A) lim −0.25ATR",       dict(mode="lim", lim_atr=0.25)),
        ("A) lim −0.50ATR",       dict(mode="lim", lim_atr=0.50)),
        ("A) sonraki 1h kapanış", dict(mode="next1h")),
        ("B) yeniden giriş 5bar", dict(reentry_n=5)),
        ("B) yeniden giriş 10bar", dict(reentry_n=10)),
        ("C) çıkış: 10-bar kanal", dict(exit_ch=10)),
        ("C) çıkış: 20-bar kanal", dict(exit_ch=20)),
    ]
    print(f"\n{'='*112}\n=== İŞLEM SİLMEYEN MEKANİKLER — giriş fiyatı · yeniden giriş · yapısal çıkış ===")
    print(f"  {'varyant':>22s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'TRAIN$':>8s} {'TEST$':>8s} "
          f"{'toplam$':>9s}  yıl-yıl")
    res = {}
    for name, kw in VAR:
        s = run(**kw)
        if not s: continue
        res[name] = s
        ys = " ".join(f"{y}:${v:+.0f}" for y, v in s["yrs"].items())
        print(f"  {name:>22s} {s['n']:>5d} {s['wr']:>3.0f}% {s['pf']:>5.2f} {s['train']:>+8.0f} "
              f"{s['test']:>+8.0f} {s['tot']:>+9.0f}  {ys}")

    ref = res["TABAN (4h kapanışta)"]
    print(f"\n  --- MOTOR DOĞRULAMASI ---")
    ok = abs(ref["tot"] - 1421) < 30 and abs(ref["n"] - 1579) < 35
    print(f"  taban n={ref['n']} ${ref['tot']:+.0f} vs ankor n=1579 $+1421 → "
          f"{'✓ GEÇERLİ' if ok else '✗ MOTOR TUTMUYOR, sonuçlar GEÇERSİZ'}")
    if not ok: return

    alts = {k: v for k, v in res.items() if k != "TABAN (4h kapanışta)"}
    best = max(alts, key=lambda k: alts[k]["train"])
    b = alts[best]
    print(f"\n  ★ TRAIN argmax: {best} (${b['train']:+.0f} vs taban ${ref['train']:+.0f})")
    if b["train"] <= ref["train"]:
        print(f"  → TRAIN'de bile taban geçilemedi. TEST açılmadı. RET.")
    else:
        dte = b["test"] - ref["test"]
        dy = {y: b["yrs"].get(y, 0) - ref["yrs"].get(y, 0) for y in ref["yrs"]}
        okk = dte > 0 and all(v > 0 for v in dy.values()) and dte > 0.02 * ref["test"]
        print(f"  >>> TEST: Δ${dte:+.0f} | yıl-yıl " + " ".join(f"{y}:{v:+.0f}" for y, v in dy.items())
              + f"  {'★ KABUL adayı' if okk else 'RET'}")
    print(f"\n  NOT: A varyantlarında limit dolmazsa PİYASAYA düşülür → hiçbir işlem silinmez.")
    print(f"  Bu, 'filtre işlem siler, işlem silmek negatif beklentilidir' duvarını AŞAR.")


if __name__ == "__main__":
    main()
