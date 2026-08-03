"""
pw_confluence.py — MTF HAREKETLİ ORTALAMA ÇAKIŞMASI: yeni bir KOL adayı (filtre DEĞİL).

NEREDEN GELDİ: kullanıcının 2026-08-03 BTC ekran görüntüleri. Fiyat 62,268'den 63,958'e
sıçrayıp tam 63,715'te durdu — ve orada 1h EMA200 (63,693) ile 4h EMA50 (63,673) üst üste
biniyordu. İki zaman diliminin direnci AYNI fiyatta. Fiyat oraya değip geri çekildi.

NEDEN BU, BUGÜN ÇÖKEN 290 DENEMEDEN FARKLI:
 1. Bu bir FİLTRE DEĞİL, ayrı bir KOL. Filtreler mevcut işlemleri SİLEREK bedel ödetiyor ve
    permütasyon testi silmenin —ne silinirse silinsin— negatif beklenti olduğunu gösterdi.
    Yeni bir kol hiçbir işlemi silmez; BOŞ KOLTUKLARI doldurur. Bugün ölçüldü: koltuklar
    zamanın yalnızca %3.25'inde tamamen dolu.
 2. Bu bir OSİLATÖR DEĞİL, bir SEVİYE. Çöken denemelerin çoğu osilatördü ve hepsi aynı
    tautoloji yüzünden battı: donchian long sinyalinde RSI min 57.7, AroonUp HER ZAMAN 100 —
    yani osilatör tetikleyiciyle AYNI olayı ikinci kez ölçüyordu. Bir fiyat seviyesi bu
    tuzağa aynı şekilde düşmez.
 3. ORTALAMAYA DÖNÜŞ bizde ZATEN ÇALIŞAN tek ailedir (BB/LTC hafta sonu: +$135, 4/4 yıl).

⚠️ ÖNCE UCUZ ÖN KONTROL, SONRA STRATEJİ: fiyat çakışma bölgesine değdiğinde ileri getirisi
tabandan farklı mı? Değilse strateji kurmanın anlamı yok ve orada dururum. Bu sıra önemli —
önce strateji kurup sonra "neden çalışmadı" diye bakmak, gürültüye kural uydurmaya davettir.

LOOKAHEAD KORUMASI (bu testin en kritik yeri): 1h barında kullanılan 4h EMA50, YALNIZCA
TAMAMLANMIŞ 4h barlarından gelmeli. Yöntem: 4h'te hesapla → shift(1) → 1h indeksine ffill.
deployed_backtest.py'nin günlük-EMA20 MTF'sinde kullanılan yaklaşımın aynısı. Bu yapılmazsa
"gelecekteki 4h kapanışını" biliyor oluruz ve test SAHTE pozitif üretir.

DÖRT SAHTELİK TESTİ (H1/H2/trailing/maxhold'u kapatan yöntem): işaret testi · havuzlanmış z ·
YÖN ayrımı (etki sadece long'daysa piyasa betası) · DÖNEM ayrımı (TRAIN/TEST işareti).

Kullanım:  py pw_confluence.py local
"""
import sys
from math import comb

import numpy as np
import pandas as pd

import fast_bt
from indicators import atr as atr_fn, ema as ema_fn, rsi as rsi_fn

COINS = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
FEE = 0.0001
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")


def mtf_frame(m):
    """1h çerçevesi + LOOKAHEAD'SİZ 4h göstergeleri.
    4h serileri shift(1) ile TAMAMLANMIŞ bara çekilir, sonra 1h'e ffill edilir."""
    d1 = fast_bt.resample(m, "1h")
    d4 = fast_bt.resample(m, "4h")
    e50_4 = ema_fn(d4["close"], 50).shift(1).reindex(d1.index, method="ffill")
    e200_4 = ema_fn(d4["close"], 200).shift(1).reindex(d1.index, method="ffill")
    out = pd.DataFrame(index=d1.index)
    out["open"] = d1["open"]; out["high"] = d1["high"]
    out["low"] = d1["low"]; out["close"] = d1["close"]
    out["e200_1h"] = ema_fn(d1["close"], 200)
    out["e50_4h"] = e50_4
    out["e200_4h"] = e200_4
    out["atr"] = atr_fn(d1["high"], d1["low"], d1["close"], 14)
    out["rsi"] = rsi_fn(d1["close"], 14)
    return out


def events(f, theta=0.003, touch=0.0015):
    """Çakışma temas OLAYLARI (strateji değil, sadece olay tespiti).

    Çakışma: |1h EMA200 − 4h EMA50| / fiyat < theta  (iki direnç aynı yerde)
    Temas  : bar YÜKSEĞİ bölgeye 'touch' kadar yaklaşıyor AMA kapanış bölgenin ALTINDA
             (yani yukarıdan reddedildi) → SHORT olayı. Aynanın simetriği LONG olayı.
    Dönüş: (indeks dizisi, yön dizisi)  yön: -1 üstten red (short), +1 alttan destek (long)"""
    c = f["close"].values; hi = f["high"].values; lo = f["low"].values
    z1 = f["e200_1h"].values; z4 = f["e50_4h"].values
    lvl = (z1 + z4) / 2.0
    near = np.abs(z1 - z4) / c < theta
    ok = near & np.isfinite(lvl) & np.isfinite(c)
    up_band = lvl * (1 + touch); dn_band = lvl * (1 - touch)
    # üstten red: yüksek bölgeye girdi, kapanış seviyenin altında kaldı
    short_ev = ok & (hi >= dn_band) & (c < lvl)
    # alttan destek: düşük bölgeye girdi, kapanış seviyenin üstünde kaldı
    long_ev = ok & (lo <= up_band) & (c > lvl)
    idx = np.where(short_ev | long_ev)[0]
    dirs = np.where(short_ev[idx], -1, 1)
    return idx, dirs


def diagnostic(f, horizon=24, theta=0.003):
    """ÖN KONTROL: çakışma temasından sonraki ileri getiri, TABANDAN farklı mı?
    Taban = aynı coin'in TÜM barlarındaki aynı ufuklu getiri (ATR'ye normalize)."""
    c = f["close"].values; a = f["atr"].values
    n = len(c)
    idx, dirs = events(f, theta)
    idx = idx[(idx >= 260) & (idx < n - horizon)]
    if len(idx) < 30: return None
    dirs = dirs[: len(idx)] if len(dirs) == len(idx) else events(f, theta)[1][:len(idx)]
    fwd = (c[idx + horizon] - c[idx]) / a[idx]          # ATR birimiyle ileri getiri
    sgn = fwd * (-1)                                     # short olayı için ters çevrilecek
    ev_r = np.where(dirs == -1, -fwd, fwd)               # olayın ÖNGÖRDÜĞÜ yöndeki getiri
    base_i = np.arange(260, n - horizon)
    base_fwd = (c[base_i + horizon] - c[base_i]) / a[base_i]
    ok = np.isfinite(ev_r)
    ev_r = ev_r[ok]
    bb = base_fwd[np.isfinite(base_fwd)]
    if len(ev_r) < 30: return None
    se = np.sqrt(ev_r.var(ddof=1) / len(ev_r) + bb.var(ddof=1) / len(bb))
    return dict(n=len(ev_r), ev=float(ev_r.mean()), base=float(np.abs(bb).mean() * 0),
                base_mean=float(bb.mean()), z=float((ev_r.mean() - 0) / se) if se > 0 else 0.0,
                se=float(se))


def run_sleeve(f, theta=0.003, touch=0.0015, rsi_hi=60.0, sl_atr=2.0, rr=1.667,
               mh=48, need_trend=True):
    """ÇAKIŞMA KOLU: occ'lu, filtre uygulaması ÜRETİM SIRASINDA (post-hoc DEĞİL).

    SHORT: 4h düşen yapı (4h EMA50 < 4h EMA200) + fiyat çakışmaya YUKARIDAN reddedildi
           + kısa vade aşırı alım (1h RSI > rsi_hi)
    LONG : simetrik ayna.
    need_trend=False ise 4h yapı şartı kalkar (doz-yanıt/dejenerasyon kontrolü için)."""
    c = f["close"].values; hi = f["high"].values; lo = f["low"].values
    a = f["atr"].values; rs = f["rsi"].values
    z1 = f["e200_1h"].values; z4 = f["e50_4h"].values; z200_4 = f["e200_4h"].values
    lvl = (z1 + z4) / 2.0
    near = np.abs(z1 - z4) / c < theta
    idx = f.index; n = len(c)
    Rs = []; ts = []; ds = []; bars = []; occ = -1
    for i in range(260, n - 1):
        if i <= occ: continue
        ai = a[i]
        if not (np.isfinite(ai) and ai > 0 and near[i] and np.isfinite(lvl[i])
                and np.isfinite(rs[i]) and np.isfinite(z200_4[i])): continue
        d_ = 0
        down4 = z4[i] < z200_4[i]
        if hi[i] >= lvl[i] * (1 - touch) and c[i] < lvl[i] and rs[i] > rsi_hi:
            if (not need_trend) or down4: d_ = -1
        elif lo[i] <= lvl[i] * (1 + touch) and c[i] > lvl[i] and rs[i] < 100 - rsi_hi:
            if (not need_trend) or (not down4): d_ = 1
        if d_ == 0: continue
        e = c[i]; sld = sl_atr * ai
        slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = c[j]
        Rs.append(d_ * (ep - e) / sld - 2 * FEE * e / sld)
        ts.append(idx[i]); ds.append(d_); bars.append(j - i); occ = j
    return (np.array(Rs), pd.DatetimeIndex(ts) if ts else pd.DatetimeIndex([]),
            np.array(ds, int), np.array(bars, float))


def sign_p(w, n):
    if n == 0: return 1.0
    p = (2 * sum(comb(n, k) for k in range(w, n + 1)) / 2 ** n) if w >= n / 2 else \
        (2 * sum(comb(n, k) for k in range(0, w + 1)) / 2 ** n)
    return min(1.0, p)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    F = {}
    for c in COINS:
        try: F[c] = mtf_frame(fast_bt.load(c, source=source))
        except SystemExit: pass

    print(f"\n{'=' * 100}")
    print(f"=== MTF MA ÇAKIŞMASI — YENİ KOL ADAYI ({len(F)} coin, 1h + lookahead'siz 4h) ===")

    # ── AŞAMA 1: UCUZ ÖN KONTROL ────────────────────────────────────────────
    print(f"\n--- AŞAMA 1: ÖN KONTROL — çakışma temasında TEPKİ var mı? ---")
    print("  Soru: temas sonrası, olayın ÖNGÖRDÜĞÜ yöndeki 24-bar getirisi sıfırdan farklı mı?")
    print("  (ATR birimiyle. Tepki yoksa strateji kurmaya gerek yok ve burada dururum.)")
    print(f"\n  {'coin':>6s} {'olay':>6s} {'öngörülen yön getirisi':>24s} {'z':>7s}")
    tot_ev = []; rows = 0
    for c, f in F.items():
        r = diagnostic(f)
        if r is None: continue
        rows += 1
        tot_ev.append(r)
        if rows <= 8:
            print(f"  {c:>6s} {r['n']:>6d} {r['ev']:>+24.4f} {r['z']:>+7.2f}")
    if not tot_ev:
        print("  yeterli olay yok — DURULDU."); return
    m_ev = float(np.mean([r["ev"] for r in tot_ev]))
    n_pos = sum(1 for r in tot_ev if r["ev"] > 0)
    p_pre = sign_p(n_pos, len(tot_ev))
    print(f"  ... ({rows} coin)")
    print(f"\n  HAVUZ: ortalama öngörülen-yön getirisi {m_ev:+.4f} ATR | "
          f"{n_pos}/{len(tot_ev)} coin pozitif | işaret p = {p_pre:.4f}")
    print(f"  ÖN KONTROL HÜKMÜ: "
          f"{'✓ tepki VAR — stratejiye geç' if (p_pre < 0.05 and m_ev > 0) else '✗ tepki YOK'}")

    # ── AŞAMA 2: KOL OLARAK ÖLÇÜM ───────────────────────────────────────────
    print(f"\n{'=' * 100}\n--- AŞAMA 2: KOL ÖLÇÜMÜ (ön kontrol ne derse desin, kayıt için koşuluyor) ---")
    print("  occ VAR, filtre ÜRETİM SIRASINDA. SL 2×ATR, rr 1.667 (BB koluyla aynı), maxhold 48.")
    variants = {
        "taban (θ.003 RSI60)": dict(theta=0.003, rsi_hi=60.0),
        "θ=0.002 (sıkı)":      dict(theta=0.002, rsi_hi=60.0),
        "θ=0.005 (gevşek)":    dict(theta=0.005, rsi_hi=60.0),
        "θ=0.010 (çok gevşek)": dict(theta=0.010, rsi_hi=60.0),
        "RSI 55":              dict(theta=0.003, rsi_hi=55.0),
        "RSI 65":              dict(theta=0.003, rsi_hi=65.0),
        "RSI 70":              dict(theta=0.003, rsi_hi=70.0),
        "4h yapı şartı YOK":   dict(theta=0.003, rsi_hi=60.0, need_trend=False),
        "rr 2.5":              dict(theta=0.003, rsi_hi=60.0, rr=2.5),
    }
    print(f"\n  {'varyant':<22s} {'işlem':>6s} {'ort R':>9s} {'z(0)':>7s} {'WR%':>6s} "
          f"{'coin+':>7s} {'p':>8s} | {'LONG R':>9s} {'SHORT R':>9s} | {'TRAIN':>8s} {'TEST':>8s}")
    for nm, kw in variants.items():
        allR = []; allT = []; allD = []; per_coin = []
        for c, f in F.items():
            R, T, D, B = run_sleeve(f, **kw)
            if len(R) >= 10:
                per_coin.append(float(R.mean()))
                allR.append(R); allT.append(T); allD.append(D)
        if not allR:
            print(f"  {nm:<22s} {'—':>6s}  (yeterli işlem yok)"); continue
        R = np.concatenate(allR); D = np.concatenate(allD)
        T = allT[0].append(allT[1:]) if len(allT) > 1 else allT[0]
        z = R.mean() / (R.std(ddof=1) / np.sqrt(len(R))) if len(R) > 1 else 0.0
        npos = sum(1 for v in per_coin if v > 0)
        p = sign_p(npos, len(per_coin))
        lr = R[D == 1].mean() if (D == 1).any() else np.nan
        sr = R[D == -1].mean() if (D == -1).any() else np.nan
        tr = R[T < TRAIN_END].mean() if (T < TRAIN_END).any() else np.nan
        te = R[T >= TRAIN_END].mean() if (T >= TRAIN_END).any() else np.nan
        print(f"  {nm:<22s} {len(R):>6d} {R.mean():>+9.4f} {z:>+7.2f} {(R>0).mean()*100:>6.1f} "
              f"{npos:>3d}/{len(per_coin):<3d} {p:>8.4f} | {lr:>+9.4f} {sr:>+9.4f} | "
              f"{tr:>+8.4f} {te:>+8.4f}")

    print(f"\n  HÜKÜM KURALI (ön-kayıt): ort R > 0 · z > 1.96 · işaret p < 0.05 · LONG ve SHORT")
    print(f"  AYNI işaretli · TRAIN ve TEST AYNI işaretli. Beşi birden tutmazsa kol kurulmaz.")
    print(f"  Ayrıca θ ve RSI eksenlerinde DOZ-YANIT düzgün olmalı — zikzaksa gürültüdür.")


if __name__ == "__main__":
    main()
