"""
pw_expo.py — EŞZAMANLI MARUZİYET TAVANI: ölçülmüş mekanizmayı hedefleyen tek eksen.

BU TEST NEDEN VAR (tahmin değil, bugün ölçülen bir mekanizma):
pw_coins.py doz-yanıtı çok net bir yapı gösterdi — coin eklendikçe
   kâr:        +1421 → +1737 (K=8'de tepe, sonra düşüş)
   maxDD:       24.4 → 20-21%   ← ÇEŞİTLENDİRME ÇALIŞIYOR
   en kötü ay: −21.0 → −58.7%   ← MONOTON ÇÖKÜŞ, her coinle birlikte
Yani coin eklemek portföyü drawdown açısından İYİLEŞTİRİYOR ama tek bir ayı
felakete çeviriyor. Sebep koltuk değil (koltuk zamanın %3.25'inde dolu):
sebep EŞZAMANLI KORELE MARUZİYET. Kripto hep birlikte hareket eder; kötü bir
ayda 7 koltuğun 7'si de aynı yönde açık olabiliyor ve hepsi birden kaybediyor.
Koltukların "bol" olması tam da bunu ENGELLEYEN bir şey olmadığı anlamına geliyor.

HİPOTEZ: aynı YÖNDE eşzamanlı açık pozisyon sayısını L ile sınırla. Bu, kârın bir
kısmından feragat edip aylık kuyruğu geri kazanabilir. Kripto'da "aynı yön" korelasyon
için sağlam ve TAHMİN GEREKTİRMEYEN bir vekildir — korelasyon penceresi tahmin etmek
hem gürültülü hem de lookahead riski taşır (bu oturumda pairs_verify.py tam bu hatayı
yapmıştı: seviye korelasyonu kullanıp geçerli bir bulguyu neredeyse yanlış sebeple çürüttü).

İKİ AYRI SORU, İKİ AYRI ÖN-KAYITLI BAR:

 S1 — KÂR BARI (bugün beş ekseni reddeden barın AYNISI, gevşetilmedi):
      Δ$ > +28 · hiçbir yıl >%10 kötü · maxDD +2p içinde · en kötü ay kötüleşmeyecek.

 S2 — KUYRUK BARI (YENİ ve AYRI bir soru, gevşetme değil):
      Kullanıcı bir ay boyunca sistemin başında OLMAYACAK. "Kârı sabit tutup en kötü ayı
      −%21'den −%14'e indiren" bir değişiklik onun için çok değerlidir ve S1 barı bunu
      REDDEDERDİ. Bu benim çerçevemdeki bir kusurdu; ayrı bir hedef olarak ÖN-KAYITLIYORUM:
        en kötü ay ≥3 puan İYİLEŞECEK · kâr %5'ten (≈$71) fazla düşmeyecek ·
        maxDD kötüleşmeyecek · hiçbir yıl >%15 kötüleşmeyecek.
      Bu iki bar AYRI raporlanır. Bir varyantın S2'yi geçmesi S1'i geçtiği anlamına GELMEZ.

DOĞRULUK: yön bilgisi gen()'e eklendi. Tavan KAPALIYKEN (L=∞) sonucun ankorla BİREBİR
($+1420.66 / 1579 işlem) çıkması, yön eklemenin hiçbir şeyi bozmadığının kanıtıdır.

Kullanım:  py pw_expo.py local
"""
import sys
import heapq

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn

ALL22 = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
# pw_coins T3'ün TRAIN sırası (TEST'e bakılmadan sabitlendi) — yeniden kullanılıyor
TRAIN_ORDER = ["TRX", "ALGO", "AAVE", "AVAX", "BTC", "LINK", "DOT", "ATOM", "VET"]


def gen_dir(sleeve, m):
    """A.gen ile SATIR SATIR aynı; ek olarak YÖN döner. Kontrol akışı değişmedi."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (A.DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         A.SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0 or i <= occ: continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a
        slp = e - d_ * sld; tp = e + d_ * rr * sld
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
        out.append((idx[i].value, idx[j], R, sld / e, d_)); occ = j
    return out


def gen_bb_dir(m):
    """A.gen_bb'nin yön dönen kopyası."""
    out = []
    for entry_ns, exit_ts, R, slp in A.gen_bb(m):
        out.append((entry_ns, exit_ts, R, slp, 0))   # BB yönü ayrı sayılır (mean-rev)
    return out


def seat_select_expo(trades, L=None, side_aware=True):
    """A.seat_select + eşzamanlı AYNI YÖN tavanı.

    L=None → tavan yok, A.seat_select ile BİREBİR aynı davranış (doğrulama için).
    L verildiğinde: aynı yönde açık pozisyon sayısı L'ye ulaşmışsa sinyal ATLANIR
    (koltuk saklanmaz — bekleyip daha iyisini almak lookahead olurdu; sadece reddedilir,
    tıpkı koltuk dolduğunda olduğu gibi). BB kolu (yön 0) tavandan MUAF: mean-reversion
    trend koluyla aynı riski taşımaz ve canlıda ayrı bir mantıkla çalışıyor."""
    ev = sorted(trades, key=lambda t: t[0])
    openh = []; taken = []; ctr = 0
    cnt = {1: 0, -1: 0}
    for entry_ns, exit_ts, R, slp, d_ in ev:
        while openh and openh[0][0].value <= entry_ns:
            _x, _c, _r, od = heapq.heappop(openh)
            if od in cnt: cnt[od] -= 1
        if len(openh) >= A.MAXPOS:
            continue
        if L is not None and side_aware and d_ in cnt and cnt[d_] >= L:
            continue
        ctr += 1
        heapq.heappush(openh, (exit_ts, ctr, R, d_))
        if d_ in cnt: cnt[d_] += 1
        taken.append((exit_ts, R, slp))
    return sorted(taken, key=lambda t: t[0])


def portfolio(donch_syms, raw, L=None):
    trades = []
    for c in donch_syms: trades += gen_dir("donchian", raw[c])
    for c in A.SQZ: trades += gen_dir("squeeze", raw[c])
    for c in A.BB_COINS: trades += gen_bb_dir(raw[c])
    taken = seat_select_expo(trades, L)
    r = np.array([R for _, R, _ in taken])
    slp = np.array([sp for _, _, sp in taken])
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    eff = np.minimum(A.RISKF, A.CAP * slp)
    pnl = r * eff * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), tot=float(pnl.sum()), pf=float(gp / gl) if gl > 0 else float("inf"),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))), worst=float(mon.min()),
                posm=float((mon > 0).mean() * 100), yr={int(k): float(v) for k, v in yr.items()})


def bar_kar(v, b, years):
    why = []
    if v["tot"] - b["tot"] <= 28: why.append(f"kâr {v['tot']-b['tot']:+.0f}$")
    for y in years:
        if abs(b["yr"].get(y, 0)) > 1e-9 and (v["yr"].get(y, 0) - b["yr"].get(y, 0)) / abs(b["yr"].get(y, 0)) < -0.10:
            why.append(f"{y} kötü"); break
    if v["dd"] > b["dd"] + 2: why.append("maxDD")
    if v["worst"] < b["worst"] - 0.05: why.append("en kötü ay")
    return why


def bar_kuyruk(v, b, years):
    why = []
    if v["worst"] < b["worst"] + 3: why.append(f"en kötü ay yalnız {v['worst']-b['worst']:+.1f}p")
    if v["tot"] < b["tot"] * 0.95: why.append(f"kâr {v['tot']-b['tot']:+.0f}$ (>%5 düşüş)")
    if v["dd"] > b["dd"] + 0.05: why.append(f"maxDD {b['dd']:.1f}→{v['dd']:.1f}")
    for y in years:
        if abs(b["yr"].get(y, 0)) > 1e-9 and (v["yr"].get(y, 0) - b["yr"].get(y, 0)) / abs(b["yr"].get(y, 0)) < -0.15:
            why.append(f"{y} >%15 kötü"); break
    return why


def show(tag, v, b, years, mark=""):
    print(f"  {tag:<28s} {v['n']:>5d} {v['tot']:>+8.0f} {v['tot']-b['tot']:>+7.0f} {v['pf']:>5.2f} "
          f"{v['dd']:>7.1f} {v['worst']:>+9.1f} {v['posm']:>8.0f} | " +
          " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + mark)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in ALL22:
        try: raw[c] = fast_bt.load(c, source=source)
        except SystemExit: pass

    print(f"\n{'=' * 120}")
    print("=== EŞZAMANLI AYNI-YÖN MARUZİYET TAVANI ===")
    print("  Hedeflenen mekanizma ÖLÇÜLDÜ: coin eklendikçe maxDD İYİLEŞİYOR (24.4→20.1)")
    print("  ama en kötü ay MONOTON ÇÖKÜYOR (−21.0→−58.7). Koltuk bol olduğu için")
    print("  eşzamanlı korele maruziyeti sınırlayan HİÇBİR ŞEY yok. Bu test onu ekliyor.")

    base = portfolio(A.DONCH, raw, None)
    years = sorted(base["yr"])
    okv = base["n"] == 1579 and abs(base["tot"] - 1420.66) < 0.01
    print(f"\n  DOĞRULAMA (tavan KAPALI ankorla birebir mi): {base['n']} işlem / ${base['tot']:+.2f}"
          f"  → {'✓ BİREBİR' if okv else '✗ SAPMA — yön ekleme bir şeyi bozmuş, sonuçlar geçersiz'}")
    if not okv:
        return

    hdr = (f"  {'küme':<28s} {'işlem':>5s} {'toplam$':>8s} {'Δ$':>7s} {'PF':>5s} {'maxDD%':>7s} "
           f"{'kötü ay%':>9s} {'poz-ay%':>8s} | " + " ".join(f"{y:>7d}" for y in years))

    print(f"\n{'=' * 120}\n=== A) MEVCUT 7 COIN + maruziyet tavanı (coin EKLEMEDEN) ===")
    print(hdr)
    show("TABAN (tavan yok)", base, base, years, "  ← CANLI")
    res_a = {}
    for L in (5, 4, 3, 2, 1):
        v = portfolio(A.DONCH, raw, L)
        res_a[L] = v
        show(f"L={L} (aynı yönde en fazla {L})", v, base, years)

    print(f"\n{'=' * 120}\n=== B) COIN EKLE + maruziyet tavanı (kârı al, kuyruğu geri kazan) ===")
    print(f"  eklenen sıra TRAIN'de sabitlendi (TEST'e bakılmadan): {TRAIN_ORDER}")
    res_b = {}
    for K in (2, 4, 6, 8):
        add = [c for c in TRAIN_ORDER[:K] if c in raw]
        print(f"\n  --- K={K} coin eklendi: {add} ---")
        print(hdr)
        show("TABAN (canlı 7, tavan yok)", base, base, years, "  ← CANLI")
        for L in (None, 5, 4, 3, 2):
            v = portfolio(A.DONCH + add, raw, L)
            res_b[(K, L)] = v
            show(f"K={K}, L={'yok' if L is None else L}", v, base, years)

    print(f"\n{'=' * 120}\n=== HÜKÜM — İKİ AYRI BAR ===")
    print(f"\n  S1 KÂR BARI (bugün beş ekseni reddeden bar, GEVŞETİLMEDİ):")
    print(f"     Δ$>+28 · hiçbir yıl >%10 kötü · maxDD +2p içinde · en kötü ay kötüleşmeyecek")
    hits1 = []
    for lbl, v in [(f"sadece L={L}", res_a[L]) for L in res_a] + \
                  [(f"K={k}, L={l}", v) for (k, l), v in res_b.items()]:
        w = bar_kar(v, base, years)
        if not w: hits1.append(lbl); print(f"     ★ GEÇTİ  {lbl}")
    if not hits1: print(f"     (hiçbiri geçmedi)")

    print(f"\n  S2 KUYRUK BARI (ayrı hedef: bir ay uzakta olacaksınız):")
    print(f"     en kötü ay ≥3p İYİLEŞECEK · kâr >%5 düşmeyecek · maxDD kötüleşmeyecek · yıl >%15 kötüleşmeyecek")
    hits2 = []
    for lbl, v in [(f"sadece L={L}", res_a[L]) for L in res_a] + \
                  [(f"K={k}, L={l}", v) for (k, l), v in res_b.items()]:
        w = bar_kuyruk(v, base, years)
        if not w:
            hits2.append((lbl, v))
            print(f"     ★ GEÇTİ  {lbl:<16s} kâr {v['tot']-base['tot']:+.0f}$ · "
                  f"en kötü ay {base['worst']:.1f}→{v['worst']:.1f} ({v['worst']-base['worst']:+.1f}p) · "
                  f"maxDD {base['dd']:.1f}→{v['dd']:.1f}")
    if not hits2: print(f"     (hiçbiri geçmedi)")

    print(f"\n  NOT: S2'yi geçmek S1'i geçmek DEĞİLDİR. S2, kârdan feragat edip kuyruk satın")
    print(f"  alan bir takastır ve öyle raporlanmalıdır — 'bulduk' diye paketlenemez.")


if __name__ == "__main__":
    main()
