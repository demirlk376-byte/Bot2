"""
pw_mtf_sleeve.py — AYNI COİNLERDE ÇOK ZAMAN DİLİMLİ DONCHIAN: kuyruk duvarına çarpamayan ilk aday.

BU NEDEN DİĞER HER ŞEYDEN FARKLI:
Bu oturumda reddedilen ALTI eksenin hepsi aynı sebeple düştü — eşzamanlı korele maruziyeti
artırıyorlardı ve en kötü ay çöküyordu (coin ekleme −%58.7, fonlama tavanı −%59.0, aralık kolu
−%84.1; üç BAĞIMSIZ mekanizma, aynı büyüklükte çöküş).

Bu aday o duvara ÇARPAMAZ, çünkü MEXC NETTED MOD: bir sembolde aynı anda TEK pozisyon.
6h sinyali gelirse ve o coinde 4h pozisyonu AÇIKSA, sinyal düşer. Yani:
  · aynı coinde eşzamanlı maruziyet ARTAMAZ (fiziksel kısıt, tercih değil)
  · yeni coin YOK → yeni korelasyon kaynağı YOK
  · kol yalnızca coinin BOŞTA geçtiği zamanı doldurur
Bu, "kâr eklemek için kuyruk satın alma" takasından yapısal olarak muaf tek yol.

VE EDGE ZATEN DOĞRULANMIŞ: power_test.py 22 coin × 4 zaman diliminde donchian'ı ölçtü;
2h/4h/6h/12h'in DÖRDÜNDE de çalışıyor. Yeni bir fikir icat etmiyoruz — kanıtlanmış aynı
kuralı, aynı coinlerde, boş zamana uyguluyoruz.

MODELLEME — kritik nokta: SEMBOL BAŞINA TEK POZİSYON, ZAMAN DİLİMLERİ ARASI.
Her coin için tüm zaman dilimlerinin sinyalleri birleştirilir, giriş zamanına göre sıralanır
ve İLK GELEN ALIR mantığıyla tek bir işgal zinciri kurulur (canlıdaki one-per-symbol guard'ın
ta kendisi). Bu yapılmazsa aynı coinde iki pozisyon açık olur → canlıda İMKÂNSIZ olan bir
şeyi ölçmüş oluruz ve sonuç SAHTE çıkar.

DOĞRULAMA: yalnız 4h ile koşulduğunda ankorla BİREBİR (1579 işlem / $+1420.66) çıkmalı.
Çıkmıyorsa araç bozuktur ve tablo basılmaz.

ÖN-KAYITLI BAR (bugün altı ekseni reddeden barın AYNISI, gevşetilmedi):
  Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek · maxDD +2 puandan fazla artmayacak ·
  EN KÖTÜ AY KÖTÜLEŞMEYECEK.

Kullanım:  py pw_mtf_sleeve.py local
"""
import sys
import heapq

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, ema as ema_fn

TFS_EXTRA = ["2h", "6h", "8h", "12h"]
BASE_TF = "4h"


def gen_donch_tf(m, tf, apply_occ=False):
    """A.gen("donchian")'ın SATIR SATIR kopyası — tek fark: tf parametrik ve occ opsiyonel.

    Kanalı elle yeniden yazmak İLK DENEMEDE ARACI BOZDU (1697 işlem / $1366 vs ankor
    1579 / $1421): DonchianStrategy.analyze() pencere-yerel çalışıyor ve elle yazılmış
    rolling(40) ile aynı sinyalleri üretmiyor. Ders: üretim sınıfını taklit etme, ÇAĞIR.

    apply_occ=False → HAM sinyaller. Sembol-içi işgal, tüm zaman dilimleri birleştikten
    SONRA tek zincirde kurulur (netted mod = canlıdaki one-per-symbol guard). Burada occ
    uygulamak her zaman dilimini diğerlerinden habersiz bırakır ve gerçek modeli bozar."""
    _tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    if len(d) < 400:
        return []
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = A.DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0: continue
        sg = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)); d_ = sg.direction
        if d_ == 0: continue
        if apply_occ and i <= occ: continue
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
        out.append((idx[i].value, idx[j], R, sld / e)); occ = j
    return out


def one_per_symbol(streams):
    """NETTED MOD: bir sembolde aynı anda TEK pozisyon, zaman dilimleri ARASI.
    Tüm sinyaller giriş zamanına göre sıralanır; açık pozisyon varken gelen HER sinyal
    (hangi zaman dilimi olursa olsun) DÜŞER. Canlıdaki one-per-symbol guard budur."""
    ev = sorted([t for s in streams for t in s], key=lambda t: t[0])
    out = []
    busy_until = None
    for entry_ns, exit_ts, R, slp in ev:
        # A.gen'in kuralı "i <= occ ise atla" — yani ÇIKIŞ BARININ KENDİSİNDE giriş YOK.
        # Bu yüzden karşılaştırma "<" değil "<=" olmak zorunda. ("<" kullanmak çıkış barında
        # yeni giriş açar ve tek-zaman-dilimli kontrol testi ankoru tutturamaz.)
        if busy_until is not None and entry_ns <= busy_until:
            continue
        out.append((entry_ns, exit_ts, R, slp))
        busy_until = exit_ts.value
    return out


def build(raw, tfs):
    """Donchian kolunu verilen zaman dilimi kümesiyle kur. Diğer kollar DEĞİŞMEZ.
    SLEEVE SIRASI ankorla birebir: DONCH → SQZ → BB (seat_select sıralaması kararlı)."""
    trades = []
    for c in A.DONCH:
        streams = [gen_donch_tf(raw[c], tf, apply_occ=False) for tf in tfs]
        trades += one_per_symbol(streams)
    for c in A.SQZ: trades += A.gen("squeeze", raw[c])
    for c in A.BB_COINS: trades += A.gen_bb(raw[c])
    taken = A.seat_select(trades)
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
                wr=float((r > 0).mean() * 100),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))), worst=float(mon.min()),
                posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()})


def verdict(v, b, years):
    why = []
    if v["tot"] - b["tot"] <= 28: why.append(f"kâr {v['tot']-b['tot']:+.0f}$")
    bad = [y for y in years if abs(b["yr"].get(y, 0)) > 1e-9
           and (v["yr"].get(y, 0) - b["yr"].get(y, 0)) / abs(b["yr"].get(y, 0)) < -0.10]
    if bad: why.append("yıl kötü " + ",".join(
        f"{y}:{(v['yr'].get(y,0)-b['yr'].get(y,0))/abs(b['yr'].get(y,0))*100:.0f}%" for y in bad))
    if v["dd"] > b["dd"] + 2: why.append(f"maxDD {b['dd']:.1f}→{v['dd']:.1f}")
    if v["worst"] < b["worst"] - 0.05: why.append(f"en kötü ay {b['worst']:.1f}→{v['worst']:.1f}")
    return why


def show(tag, v, b, years, mark=""):
    print(f"  {tag:<26s} {v['n']:>5d} {v['tot']:>+8.0f} {v['tot']-b['tot']:>+7.0f} {v['pf']:>5.2f} "
          f"{v['wr']:>5.1f} {v['dd']:>7.1f} {v['worst']:>+9.1f} {v['posm']:>8.0f} | " +
          " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + mark)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {c: fast_bt.load(c, source=source) for c in set(A.DONCH + A.SQZ + A.BB_COINS)}

    print(f"\n{'=' * 122}")
    print("=== AYNI COİNLERDE ÇOK ZAMAN DİLİMLİ DONCHIAN ===")
    print(f"  coinler DEĞİŞMİYOR ({A.DONCH}) — yalnızca zaman dilimi ekleniyor.")
    print("  NETTED MOD: sembol başına tek pozisyon, zaman dilimleri ARASI → eşzamanlı")
    print("  maruziyet ARTAMAZ. Kol yalnızca coinin BOŞTA geçtiği zamanı doldurur.")

    base = build(raw, [BASE_TF])
    years = sorted(base["yr"])
    ok = base["n"] == 1579 and abs(base["tot"] - 1420.66) < 0.01
    print(f"\n  DOĞRULAMA (yalnız 4h = ankor mu): {base['n']} işlem / ${base['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — araç bozuk, tablo basılmıyor'}")
    if not ok:
        print(f"     (beklenen 1579 / $+1420.66 — gen_donch_tf A.gen ile aynı sonucu vermiyor)")
        return

    hdr = (f"  {'zaman dilimi kümesi':<26s} {'işlem':>5s} {'toplam$':>8s} {'Δ$':>7s} {'PF':>5s} "
           f"{'WR%':>5s} {'maxDD%':>7s} {'kötü ay%':>9s} {'poz-ay%':>8s} | " +
           " ".join(f"{y:>7d}" for y in years))

    print(f"\n--- A) 4h'e TEK zaman dilimi ekle ---")
    print(hdr)
    show("4h (CANLI)", base, base, years, "  ← ANKOR")
    single = {}
    for tf in TFS_EXTRA:
        v = build(raw, [BASE_TF, tf])
        single[tf] = v
        w = verdict(v, base, years)
        show(f"4h + {tf}", v, base, years, "  ★ GEÇTİ" if not w else "")

    print(f"\n--- B) BİRDEN FAZLA zaman dilimi ---")
    print(hdr)
    show("4h (CANLI)", base, base, years, "  ← ANKOR")
    combos = [["4h", "6h", "12h"], ["4h", "2h", "6h"], ["4h", "6h", "8h", "12h"],
              ["4h", "2h", "6h", "8h", "12h"]]
    multi = {}
    for cb in combos:
        v = build(raw, cb)
        multi[" + ".join(cb)] = v
        w = verdict(v, base, years)
        show(" + ".join(cb), v, base, years, "  ★ GEÇTİ" if not w else "")

    print(f"\n--- C) TEK BAŞINA her zaman dilimi (4h olmadan — edge var mı) ---")
    print(hdr)
    show("4h (CANLI)", base, base, years, "  ← ANKOR")
    for tf in TFS_EXTRA:
        show(f"yalnız {tf}", build(raw, [tf]), base, years)

    print(f"\n{'=' * 122}\n=== HÜKÜM (ön-kayıtlı bar, gevşetilmedi) ===")
    print("  Δ$>+28 · hiçbir yıl >%10 kötü · maxDD +2p içinde · EN KÖTÜ AY kötüleşmeyecek")
    hits = []
    for lbl, v in list(single.items()) + list(multi.items()):
        w = verdict(v, base, years)
        tag = ("4h + " + lbl) if lbl in single else lbl
        if not w:
            hits.append(tag); print(f"  ★ GEÇTİ  {tag}")
        else:
            print(f"  ✗        {tag:<26s} — {'; '.join(w)}")
    print(f"\n  SONUÇ: {'DEPLOY ADAYI → ' + hits[0] if hits else 'hiçbiri geçmedi.'}")
    if hits:
        print("  NOT: geçen varyant DEPLOY DEĞİL, ADAY. Bağımsız çürütme gerekiyor:")
        print("       (a) one_per_symbol zinciri gerçekten canlı davranışı mı modelliyor,")
        print("       (b) fazladan işlemler slippage'i (+13.4bp) kaldırıyor mu,")
        print("       (c) etki tek coine/yıla mı bağlı.")


if __name__ == "__main__":
    main()
