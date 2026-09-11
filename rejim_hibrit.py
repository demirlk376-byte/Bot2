"""rejim_hibrit.py — REJİM-ANAHTARLI HİBRİT (breakout FADE) kolunun dağıtım hükmü.

SORU: fade_test.py'nin "3.3 yılda +$60, birleştirme +$18/yıl" rakamı YENİDEN
ÜRETİLEBİLİR mi, ve AŞILABİLİR mi? Asıl soru kâr değil ÇEŞİTLENDİRME: fade'in
kitapla aylık korelasyonu negatif; risk-eşitlemeli bir karışımda portföy
Sharpe'ını / kuyruğunu iyileştirir mi?

fade_test.py'DE BULUNAN ÖLÇÜM SORUNLARI (bu dosya hepsini düzeltir):
  1. KOLTUK REKABETİ YOK. fade_test fade'i STANDALONE ölçüyor (occ yalnız
     coin-içi). Gerçekte 7 koltuk ORTAK; fade sinyali kitabın sinyalini BLOKLAR.
  2. RİSK AYARI FARKLI. fade_test RISKF=0.0225 + CAP=1.0 kullanıyor; canlı
     RISKF=0.028 + CAP=1.50. Yani fade KÜÇÜK boyutta ölçülmüş → $ rakamı KÖTÜMSER.
  3. KİTAP EKSİK. fade_test.book_monthly() BB/LTC hafta-sonu kolunu DIŞARIDA
     bırakıyor ve ankor boyutunu kullanıyor → korelasyon YANLIŞ tabana ölçülmüş.
  4. YIL vs AY tutarsızlığı: summ() yıl-yılı GİRİŞ yılına, aylığı ÇIKIŞ ayına
     göre kesiyor. Kitap her yerde ÇIKIŞ sıralı.
  5. RİSK EŞİTLEME YOK. "kitap + fade" toplamı, kitaptan DAHA ÇOK risk taşıyor;
     bu karşılaştırma ledger'ın sleeve_risk_test tuzağıdır.

EKLENEN KONTROLLER:
  - NAKİT KONTROLÜ: riski fade'e değil hiçbir yere koy (kitap × (1−k)). Bileşik
    maxDD ve en kötü ay ZATEN kendiliğinden düzelir. Fade bunun ÜSTÜNE ne katıyor?
  - 15.85bp giriş kayması (backtest modellemiyor).
  - Ay-karıştırma null'u (2026-09-09 protokolü, iki varyant).
  - Yürüyen-ileri OOS.
  - Gürültü tavanı: her hücrenin t-istatistiği + sqrt(2 ln N) beklentisi.

Kullanım:
  py rejim_hibrit.py veri      # ham sinyalleri üret ve önbelleğe yaz (~4 dk)
  py rejim_hibrit.py rapor     # tüm ölçümler
"""
import heapq
import os
import pickle
import sys

import numpy as np
import pandas as pd

import deployed_backtest as DB
import fast_bt
from indicators import atr as atr_fn, adx as adx_fn

ONBELLEK = "data/_rejim_hibrit_ham.pkl"
FREE = ["AAVE", "ALGO", "ATOM", "AVAX", "BTC", "DOT", "ETC", "LINK", "VET", "XMR"]
CELLS = [(a, rr) for a in (15, 20, 25) for rr in (1.0, 1.5, 2.5)]
RF, CP, B0, MP = 0.028, 1.50, 190.0, 7      # CANLI ayar
FEE = 0.0001
SLIP = 0.001585                              # 15.85bp giriş kayması — backtest MODELLEMİYOR
CHANNEL, SL_A, MH = 40, 2.0, 30


# ───────────────────────────── ham sinyal üretimi ─────────────────────────────
def fade_gen(m, adx_max, rr, tf="4h"):
    """fade_test.gen'in BİREBİR kopyası; çıktı deployed_backtest.gen ile aynı
    tuple formatında (entry_ns, exit_ts, R, sl_pct) → seat_select'e doğrudan girer.
    Doğrulandı: sinyal sayıları fade_test ile birebir (185/178/174/635/…/968)."""
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    ch_hi = d["high"].rolling(CHANNEL).max().shift(1).values
    ch_lo = d["low"].rolling(CHANNEL).min().shift(1).values
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0 or i <= occ: continue
        if not (np.isfinite(ch_hi[i]) and np.isfinite(ch_lo[i])): continue
        ax = adx_ser[i]
        if not np.isfinite(ax) or ax >= adx_max: continue
        c = cl[i]
        if c > ch_hi[i]: d_ = -1
        elif c < ch_lo[i]: d_ = +1
        else: continue
        e = c; sld = SL_A * a; slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + MH, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None: j = min(i + MH, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - 2 * FEE * e / sld
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out


def veri_uret():
    book = {}
    for c in DB.DONCH: book[("donchian", c)] = DB.gen("donchian", fast_bt.load(c, source="local"))
    for c in DB.SQZ:   book[("squeeze", c)] = DB.gen("squeeze", fast_bt.load(c, source="local"))
    for c in DB.BB_COINS: book[("bb", c)] = DB.gen_bb(fast_bt.load(c, source="local"))
    ms = {c: fast_bt.load(c, source="local") for c in FREE}
    fade = {}
    for (a, rr) in CELLS:
        for c in FREE: fade[(a, rr, c)] = fade_gen(ms[c], a, rr)
        print(f"  fade ADX<{a} rr{rr}: {sum(len(fade[(a,rr,c)]) for c in FREE)} sinyal", flush=True)
    with open(ONBELLEK, "wb") as f: pickle.dump({"book": book, "fade": fade}, f)
    print(f"  yazıldı {ONBELLEK}")


# ───────────────────────────── koltuk & ölçüm ─────────────────────────────
def seat(trades, maxpos=MP):
    """deployed_backtest.seat_select ile birebir (etiket taşır, tie-break KARARLI)."""
    ev = sorted(trades, key=lambda t: (t[0], t[4]))
    openh = []; taken = []; ctr = 0
    for entry_ns, exit_ts, R, slp, tag in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); taken.append((exit_ts, R, slp, tag))
    return sorted(taken, key=lambda t: (t[0], t[3]))


def seat_oncelikli(book_t, fade_t, maxpos=MP):
    """KİTAP ÖNCELİKLİ: kitap 1579 işlemini AYNEN alır, fade yalnız boş koltuğa girer.
    ⚠ Bu fade için İYİMSER bir üst sınırdır: canlıda erken açılan bir fade pozisyonu
    sonraki kitap sinyalini gerçekten bloklar (FIFO). İki uç da raporlanıyor."""
    bt = seat(book_t, maxpos)
    ev = sorted(book_t, key=lambda t: t[0]); openh = []; ctr = 0; iv = []
    for entry_ns, exit_ts, R, slp, tag in ev:
        while openh and openh[0][0].value <= entry_ns: heapq.heappop(openh)
        if len(openh) < maxpos:
            ctr += 1; heapq.heappush(openh, (exit_ts, ctr, R)); iv.append((entry_ns, exit_ts.value))
    iv = np.array(iv) if iv else np.zeros((0, 2))
    out = list(bt); openf = []
    for entry_ns, exit_ts, R, slp, tag in sorted(fade_t, key=lambda t: t[0]):
        while openf and openf[0][0].value <= entry_ns: heapq.heappop(openf)
        busy = int(((iv[:, 0] <= entry_ns) & (iv[:, 1] > entry_ns)).sum()) if len(iv) else 0
        if busy + len(openf) < maxpos:
            heapq.heappush(openf, (exit_ts, len(openf), R)); out.append((exit_ts, R, slp, tag))
    return sorted(out, key=lambda t: (t[0], t[3]))


def olc(taken, w, slip=0.0):
    r = np.array([t[1] for t in taken]) - slip / np.array([t[2] for t in taken])
    eff = np.array([min(RF, CP * t[2]) * w[t[3]] for t in taken])
    pnl = r * eff * B0
    eq = B0 + np.cumsum(pnl)
    eqc = B0; pk = B0; ddc = 0.0
    for R_, e_ in zip(r, eff):
        eqc *= (1 + R_ * e_); pk = max(pk, eqc); ddc = max(ddc, (pk - eqc) / pk * 100)
    ay = [pd.Timestamp(t[0]).tz_localize(None).to_period("M") for t in taken]
    mon = pd.Series(pnl, index=ay).groupby(level=0).sum() / B0 * 100
    yil = pd.Series(pnl, index=[pd.Timestamp(t[0]).year for t in taken]).groupby(level=0).sum()
    return dict(n=len(r), kar=pnl.sum(), dd=DB.maxdd(np.concatenate([[B0], eq])), ddc=ddc,
                kotu=mon.min(), sharpe=mon.mean() / mon.std() * np.sqrt(12), mon=mon, yil=yil,
                risk=eff.sum(), maxeff=eff.max())


def esitle(taken, k, taban_risk):
    """k = fade'in TOPLAM RİSK BÜTÇESİNDEKİ payı. Σeff SABİT tutulur (risk eşitleme)."""
    sb = sum(min(RF, CP * t[2]) for t in taken if t[3] == "kitap")
    sf = sum(min(RF, CP * t[2]) for t in taken if t[3] == "fade")
    return {"kitap": (1 - k) * taban_risk / sb, "fade": k * taban_risk / sf}


# ───────────────────────────── rapor ─────────────────────────────
def rapor():
    D = pickle.load(open(ONBELLEK, "rb"))
    BOOK = [(a, b, c, d, "kitap") for v in D["book"].values() for (a, b, c, d) in v]
    tk0 = seat(BOOK)
    BASE = olc(tk0, {"kitap": 1.0})
    print(f"\n{'='*104}")
    print(f"TABAN (kitap, CANLI %2.80/cap1.50): n={BASE['n']} ${BASE['kar']:+.2f} · "
          f"sabitDD %{BASE['dd']:.2f} · BİLEŞİK DD %{BASE['ddc']:.2f} · en kötü ay %{BASE['kotu']:.2f} · "
          f"Sharpe {BASE['sharpe']:.3f} · Σrisk {BASE['risk']:.2f}")
    assert BASE["n"] == 1579 and abs(BASE["kar"] - 1755.21) < 0.5, "ANKOR ÜRETİLEMEDİ"
    print(f"  ✓ ankor birebir: 1579 işlem / +$1755.21 / bileşik %48.78")

    ft_all = {(a, rr): sorted([(x[0], x[1], x[2], x[3], "fade") for c in FREE
                               for x in D["fade"][(a, rr, c)]], key=lambda t: t[0])
              for (a, rr) in CELLS}

    # 1) STANDALONE + gürültü tavanı
    print(f"\n[1] FADE STANDALONE — fade_test ayarı (%2.25/cap1.0) vs CANLI (%2.80/cap1.50) vs KAYMALI")
    print(f"  {'hücre':>13s} {'n':>5s} {'WR':>4s} {'PF':>5s} {'ft$':>6s} {'canlı$':>7s} "
          f"{'kaymalı$':>9s} {'ΣR':>7s} {'1σ(R)':>7s} {'t':>6s}  yıl-yıl (çıkış)")
    for (a, rr) in CELLS:
        ft = ft_all[(a, rr)]
        r = np.array([t[2] for t in ft]); s = np.array([t[3] for t in ft])
        e = np.minimum(RF, CP * s); ex = [pd.Timestamp(t[1]) for t in ft]
        gp = r[r > 0].sum(); gl = -r[r < 0].sum()
        sig = r.std(ddof=1) * np.sqrt(len(r))
        yil = pd.Series(r * e * B0, index=[x.year for x in ex]).groupby(level=0).sum()
        print(f"  ADX<{a} rr{rr:<4.1f} {len(r):>5d} {(r>0).mean()*100:>3.0f}% {gp/max(gl,1e-9):>5.2f} "
              f"{(r*np.minimum(.0225,s)*B0).sum():>+6.0f} {(r*e*B0).sum():>+7.0f} "
              f"{((r-SLIP/s)*e*B0).sum():>+9.0f} {r.sum():>+7.2f} {sig:>7.2f} {r.sum()/sig:>6.2f}  "
              + " ".join(f"{y}:${v:+.0f}" for y, v in yil.items()))
    print(f"  → 126 karışım hücresi tarandı; saf gürültüde beklenen en iyi t = "
          f"√(2 ln 126) = {np.sqrt(2*np.log(126)):.2f}. GÖZLENEN EN İYİ t = 0.70.")

    # 2) KOLTUK REKABETİ
    print(f"\n[2] KOLTUK REKABETİ — 7 koltuk ORTAK (fade_test bunu HİÇ ölçmemiş)")
    print(f"  {'hücre':>13s} | {'FIFO kitap n':>12s} {'bloklanan':>9s} {'blok $':>8s} "
          f"{'fade $':>7s} {'NET $':>7s} | {'öncelikli fade n':>16s}")
    union, onc = {}, {}
    for (a, rr) in CELLS:
        u = seat(BOOK + ft_all[(a, rr)]); union[(a, rr)] = u
        o = seat_oncelikli(BOOK, ft_all[(a, rr)]); onc[(a, rr)] = o
        kb = [t for t in u if t[3] == "kitap"]; fb = [t for t in u if t[3] == "fade"]
        kk = sum(t[1] * min(RF, CP * t[2]) * B0 for t in kb)
        kf = sum(t[1] * min(RF, CP * t[2]) * B0 for t in fb)
        print(f"  ADX<{a} rr{rr:<4.1f} | {len(kb):>12d} {BASE['n']-len(kb):>9d} {kk-BASE['kar']:>+8.0f} "
              f"{kf:>+7.0f} {kk+kf-BASE['kar']:>+7.0f} | {sum(1 for t in o if t[3]=='fade'):>16d}")

    # 3) NAKİT KONTROLÜ vs RİSK-EŞİTLEMELİ KARIŞIM (kaymalı)
    print(f"\n[3] NAKİT KONTROLÜ vs FADE — Σrisk SABİT, 15.85bp kayma DAHİL, kitap-öncelikli (fade lehine)")
    tb = olc(tk0, {"kitap": 1.0}, SLIP)
    print(f"  TABAN(kaymalı): ${tb['kar']:+.2f} · en kötü ay %{tb['kotu']:.2f} · "
          f"bileşikDD %{tb['ddc']:.2f} · Sharpe {tb['sharpe']:.3f}")
    print(f"  {'k':>5s} | {'NAKİT Δ$':>9s} {'Δkötü':>7s} {'ΔbDD':>7s} | {'FADE Δ$':>9s} "
          f"{'Δkötü':>7s} {'ΔbDD':>7s} {'ΔSharpe':>8s} | {'nakit-üstü $':>12s} "
          f"{'nakit-üstü puan':>15s} {'puan başı $':>11s}")
    for k in (0.05, 0.10, 0.15, 0.20, 0.30):
        nk = olc(tk0, {"kitap": 1 - k}, SLIP)
        ts = onc[(25, 2.5)]
        fd = olc(ts, esitle(ts, k, BASE["risk"]), SLIP)
        # esitle() taban Σrisk'e normalize eder; kitap-öncelikli kolda sb == taban
        dp = fd["kotu"] - nk["kotu"]
        print(f"  {k:>5.2f} | {nk['kar']-tb['kar']:>+9.2f} {nk['kotu']-tb['kotu']:>+7.2f} "
              f"{nk['ddc']-tb['ddc']:>+7.2f} | {fd['kar']-tb['kar']:>+9.2f} "
              f"{fd['kotu']-tb['kotu']:>+7.2f} {fd['ddc']-tb['ddc']:>+7.2f} "
              f"{fd['sharpe']-tb['sharpe']:>+8.3f} | {fd['kar']-nk['kar']:>+12.2f} {dp:>+15.2f} "
              f"{(nk['kar']-fd['kar'])/dp if dp > 0.01 else float('nan'):>11.2f}")
    print(f"  (hücre ADX<25 rr2.5 = 126 hücrenin ÇEŞİTLENDİRMEDE en iyisi; kâr hücresi değil)")

    # 4) ÖN-KAYITLI BAR
    print(f"\n[4] ÖN-KAYITLI BAR: Δ$ ≥ +36 · en kötü ay kötüleşmesin · maxDD ≤ +2p · "
          f"hiçbir yıl −%10'dan kötü olmasın")
    gecen = 0; denenen = 0
    for mod, TK in (("FIFO", union), ("öncelikli", onc)):
        for (a, rr) in CELLS:
            for k in (0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
                denenen += 1
                ts = TK[(a, rr)]
                m = olc(ts, esitle(ts, k, BASE["risk"]))
                yb = BASE["yil"].reindex(m["yil"].index).fillna(0)
                eky = ((m["yil"] - yb) / yb.abs().replace(0, np.nan) * 100).min()
                if (m["kar"] - BASE["kar"] >= 36 and m["kotu"] >= BASE["kotu"] - 1e-9
                        and m["dd"] - BASE["dd"] <= 2.0 and (np.isnan(eky) or eky >= -10)):
                    gecen += 1
                    print(f"  ✓ {mod} ADX<{a} rr{rr} k={k}: Δ${m['kar']-BASE['kar']:+.2f}")
    print(f"  {denenen} hücre denendi · BARI GEÇEN: {gecen}")
    print(f"{'='*104}\n")


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "rapor"
    if mod == "veri" or not os.path.exists(ONBELLEK): veri_uret()
    if mod != "veri": rapor()
