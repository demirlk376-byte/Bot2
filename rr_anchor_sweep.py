"""
rr_anchor_sweep.py — 88 hücreli bulguyu DOLARA ve RİSKE çevir (ankor üstünde).

BULGU (power_rr.py, 13.201 işlem, 88 hücre): donchian hedefi rr2.5'te DAR.
Doz-yanıt 7 noktada MONOTON, etki HEM long HEM short'ta, TRAIN/TEST işareti AYNI.
Bunlar gürültünün üretmesi zor desenler.

AMA power_rr KOLTUK GÖRMÜYOR. Canlıda 7 koltuk var ve geniş hedef pozisyonu daha uzun
tutuyor (15.3 → 17.9 bar). Ayrıca TP'ye ulaşma oranı %21 → %8'e düşüyor: kazanma oranı
çöküyor. Canlıda CONSECUTIVE_LOSS_LIMIT=2 + COOLDOWN=240dk var — düşük WR bu freni çok
daha sık tetikler. R ortalaması iyileşse bile bu üç etki kârı yiyebilir.

BU YÜZDEN ANKOR: gerçek 12 coin, gerçek koltuk seçimi, gerçek boyutlandırma
(eff = min(RISKF, CAP×sl_pct)), gerçek yıl kırılımı, gerçek maxDD.

DÜRÜSTLÜK NOTU: bu sweep ankorun TAM DÖNEMİNDE koşuyor → örneklem-içi. Tek başına delil
DEĞİL; power_rr'ın dönem ayrımı (TEST'te de pozitif) + yön ayrımı (short'ta da var) +
monotonluk delili taşıyor. Buranın işi "kaç dolar ve ne riskle" sorusunu cevaplamak.

KABUL BARI (ön-kayıt): (1) toplam kâr artacak, (2) HİÇBİR YIL belirgin kötüleşmeyecek
(>%10 düşüş = ret — 2026-07-21'de squeeze rr3.0 tam bu kuralla reddedilmişti),
(3) maxDD artmayacak (>%2 puan artış = ret), (4) seçim MONOTON tepenin ilk düzleştiği
yerden yapılacak, tepe noktasından DEĞİL (ekstrema overfit'tir; rr2.5 de böyle seçilmişti).

Kullanım:  py rr_anchor_sweep.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A

RRS = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]


def precompute_donchian(m):
    """A.gen('donchian', ...)'ın PAHALI kısmını bir kez koştur: her bar için nihai yön.

    NEDEN GÜVENLİ: A.gen'de sıra şu — (1) atr kontrolü, (2) analyze → d_, (3) d_==0 veya
    i<=occ ise atla, (4) MTF kontrolü ise atla, (5) çıkış yürüyüşü. Adım (2) ve (4)'ün
    HİÇBİRİ occ'a bakmıyor; (4) başarısız olunca occ'a dokunmadan continue ediyor. Yani
    "MTF'yi geçen yön" occ'tan ve rr'den BAĞIMSIZ → önceden hesaplanabilir. Sadece çıkış
    yürüyüşü (5) ve onun ürettiği occ rr'ye bağlı. Sonuç A.gen ile birebir aynı olmalı;
    aşağıda rr2.5'te ankorla sayı/dolar karşılaştırması yapılarak DOĞRULANIYOR."""
    tf, win, sl_a, _rr, mh = A.CFG["donchian"]
    d = A.fast_bt.resample(m, tf)
    atr_ser = A.atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = A.DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    n = len(d)
    dirs = np.zeros(n, dtype=np.int8)
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        d_ = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)).direction
        if d_ == 0: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        dirs[i] = d_
    return d, atr_ser, dirs


def gen_donch_rr(pre, rr):
    """Önceden hesaplanmış yönlerle çıkışı yeniden koştur (A.gen'in 5. adımı, birebir)."""
    d, atr_ser, dirs = pre
    tf, win, sl_a, _rr, mh = A.CFG["donchian"]
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        d_ = int(dirs[i])
        if d_ == 0 or i <= occ: continue
        a = atr_ser[i]
        e = cl[i]; sld = sl_a * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * A.FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out


def evaluate(rr, pre_d, other):
    """Ankoru donchian rr'si değiştirilmiş halde koştur. Diğer her şey aynı."""
    # SLEEVE SIRASI KRİTİK: seat_select'in sıralaması kararlı (stable) → ekleme sırası
    # değişirse eşit-zamanlı sinyallerde koltuk sahibi değişir (~$3 kayar). Ankorla
    # BİREBİR aynı sıra: DONCH → SQZ → BB.
    trades = []
    for p in pre_d: trades += gen_donch_rr(p, rr)
    trades += other

    taken = A.seat_select(trades)
    r = np.array([R for _, R, _ in taken])
    exits = [pd.Timestamp(x) for x, _, _ in taken]
    slpct = np.array([sp for _, _, sp in taken])
    eff = np.minimum(A.RISKF, A.CAP * slpct)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    dd = A.maxdd(np.concatenate([[A.BAL0], eq]))
    mon = (pd.DataFrame({"p": pnl, "m": [x.tz_localize(None).to_period("M") for x in exits]})
           .groupby("m")["p"].sum() / A.BAL0 * 100)
    yr = np.array([x.year for x in exits])
    per_year = {int(y): float(pnl[yr == y].sum()) for y in sorted(set(yr))}
    return dict(n=len(taken), tot=float(pnl.sum()), dd=float(dd),
                wr=float((r > 0).mean() * 100),
                pf=float(r[r > 0].sum() / max(-r[r < 0].sum(), 1e-9)),
                meanR=float(r.mean()), worst=float(mon.min()),
                posm=float((mon > 0).mean() * 100), yr=per_year)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw_d = [fast_bt.load(c, source=source) for c in A.DONCH]
    raw_s = [fast_bt.load(c, source=source) for c in A.SQZ]
    raw_b = [fast_bt.load(c, source=source) for c in A.BB_COINS]

    print(f"\n{'=' * 100}")
    print("=== ANKOR ÜSTÜNDE donchian rr SWEEP (koltuk + boyut + maxDD dahil) ===")
    print(f"  12 coin, MAXPOS={A.MAXPOS}, CAP={A.CAP}, RISKF={A.RISKF}, BAL0=${A.BAL0:.0f}")

    # Pahalı kısımlar bir kez: donchian yönleri + rr'den etkilenmeyen kollar.
    pre_d = [precompute_donchian(m) for m in raw_d]
    other = []
    for m in raw_s: other += A.gen("squeeze", m)
    for m in raw_b: other += A.gen_bb(m)

    res = {}
    for rr in RRS:
        res[rr] = evaluate(rr, pre_d, other)

    # ── DOĞRULAMA: rr2.5 satırı ankorun kendisiyle BİREBİR aynı mı? ──
    # Hızlandırma (sinyalleri önden hesaplama) sonucu değiştirmiş olabilir. Ankoru
    # değiştirilmemiş A.gen ile koşup karşılaştırmadan aşağıdaki tablonun hiçbir
    # anlamı yok — bu oturumda araç bug'ları iki kez sahte sonuç üretti.
    ref = []
    for m in raw_d: ref += A.gen("donchian", m)
    ref_taken = A.seat_select(ref + other)
    rr_ = np.array([R for _, R, _ in ref_taken])
    sl_ = np.array([sp for _, _, sp in ref_taken])
    ref_tot = float((rr_ * np.minimum(A.RISKF, A.CAP * sl_) * A.BAL0).sum())
    v25 = res[2.5]
    ok = v25["n"] == len(ref_taken) and abs(v25["tot"] - ref_tot) < 0.01
    print(f"\n  DOĞRULAMA (hızlandırma sonucu bozdu mu?): "
          f"hızlı rr2.5 = {v25['n']} işlem / ${v25['tot']:+.2f}  vs  "
          f"ankor A.gen = {len(ref_taken)} işlem / ${ref_tot:+.2f}  → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA VAR — tablo GEÇERSİZ'}")
    if not ok:
        print("  Sapma olduğu için sweep tablosu basılmıyor.")
        return

    base = res[RRS[0]]
    years = sorted({y for v in res.values() for y in v["yr"]})
    hdr = (f"  {'rr':>5s} {'işlem':>6s} {'toplam$':>9s} {'Δ$':>8s} {'PF':>5s} {'WR%':>5s} "
           f"{'maxDD%':>7s} {'kötü ay%':>9s} {'poz-ay%':>8s} | " +
           " ".join(f"{y:>7d}" for y in years))
    print("\n" + hdr); print("  " + "-" * (len(hdr) - 2))
    for rr in RRS:
        v = res[rr]
        tag = "  ← CANLI" if rr == 2.5 else ""
        print(f"  {rr:>5.1f} {v['n']:>6d} {v['tot']:>+9.0f} {v['tot'] - base['tot']:>+8.0f} "
              f"{v['pf']:>5.2f} {v['wr']:>5.1f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
              f"{v['posm']:>8.0f} | " +
              " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + tag)

    print(f"\n  --- YIL BAZINDA TABANA GÖRE DEĞİŞİM (kural: hiçbir yıl >%10 kötüleşmeyecek) ---")
    print(f"  {'rr':>5s} " + " ".join(f"{y:>9d}" for y in years) + "   hüküm")
    for rr in RRS[1:]:
        v = res[rr]
        cells = []
        bad = []
        for y in years:
            b = base["yr"].get(y, 0.0); c = v["yr"].get(y, 0.0)
            rel = (c - b) / abs(b) * 100 if abs(b) > 1e-9 else 0.0
            cells.append(f"{rel:>+8.0f}%")
            if rel < -10: bad.append(y)
        ok_dd = v["dd"] <= base["dd"] + 2.0
        ok_tot = v["tot"] > base["tot"]
        why = []
        if bad: why.append(f"yıl kötüleşti: {bad}")
        if not ok_dd: why.append(f"maxDD +{v['dd'] - base['dd']:.1f}p")
        if not ok_tot: why.append("kâr artmadı")
        print(f"  {rr:>5.1f} " + " ".join(cells) +
              ("   ✓ geçti" if not why else "   ✗ " + ", ".join(why)))

    # ── MONOTON TEPE / DÜZLEŞME NOKTASI ──
    tots = [res[rr]["tot"] for rr in RRS]
    mx = max(tots)
    knee = next(rr for rr, t in zip(RRS, tots) if t >= 0.97 * mx)
    print(f"\n  --- SEÇİM KURALI (ekstrema overfit'tir) ---")
    print(f"      tepe ${mx:+.0f}; maksimumun %97'sine ulaşan EN KÜÇÜK rr = {knee}")
    print(f"      (rr2.5 de 2026-07-21'de tam bu kuralla seçilmişti — tutarlı kalıyorum)")


if __name__ == "__main__":
    main()
