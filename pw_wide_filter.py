"""
pw_wide_filter.py — GENİŞ EVREN + KALİTE FİLTRESİ: bugün ayrı ayrı düşen iki fikrin BİRLEŞİMİ.

KULLANICI SORUSU: "stratejiyi daha yüksek WR olacak şekilde filtreleyip daha fazla coin
kullansak ne olur?"

NEDEN BU, TEKRAR DEĞİL — bugün ikisi AYRI AYRI test edildi ve ikisi de düştü:
 · FİLTRE tek başına (290 deneme): sabit 7-coin havuzundan işlem SİLİYOR. Permütasyon
   testi NE silinirse silinsin silmenin negatif beklenti olduğunu gösterdi.
 · COIN EKLEME tek başına (pw_coins): en kötü ay −%21 → −%58.7. Eşzamanlı korele maruziyet.

BİRLEŞİM YAPISAL OLARAK FARKLI: geniş evren BOLLUK yaratır, filtre o bolluktan SEÇER.
Silme değil seçme. Ve işlem sayısı ankorunkine yakın tutulursa maruziyet de patlamaz —
coin ekleme'nin çöktüğü mekanizma (daha ÇOK eşzamanlı pozisyon) devreye girmez.

BUGÜNKÜ İKİ ÖLÇÜM BUNU DESTEKLİYOR:
 1. pw_seat: koltuk KIT olduğunda kalite sıralaması GERÇEKTEN kazandırıyor — MP=3'te
    "günlük trend hizası" +$168, z=+2.77, TRAIN/TEST aynı işaret, 4/4 yıl pozitif.
    7 coinle koltuk kıt DEĞİL (zamanın %3.25'i dolu) → o yüzden orada işe yaramadı.
    22 coinle koltuk KIT olur → mekanizma devreye girebilir.
 2. pw_gate: EMA200 kapısı işlemlerin yalnız %12'sini eliyor ve KAZANDIRIYOR. Yani az
    silen, bağlam-temelli bir kapı bu sistemde çalışıyor. Sorun "filtre" değil, "çok silmek".

TASARIM: donchian kolu N coinle koşulur (N = 7/12/17/22) ve giriş anında bir KALİTE
ÖLÇÜSÜ eşiği uygulanır. Eşik, toplam işlem sayısı ankorunkine (1579) YAKIN kalacak
şekilde seçilir — böylece "daha çok işlem" değil "aynı sayıda AMA daha seçilmiş işlem"
karşılaştırması yapılır. Bu, iki etkiyi (bolluk vs maruziyet) birbirinden ayırır.

KALİTE ÖLÇÜLERİ (hepsi giriş anında bilinen, lookahead YOK):
  adx      — trend gücü
  guc      — kırılım gücü: (kapanış − kanal) / ATR, yani kanalı ne kadar aştı
  mesafe   — EMA200'e uzaklık, ATR biriminde (trend olgunluğu)
  gunluk   — günlük EMA20'ye uzaklık, ATR biriminde (üst zaman dilimi hizası gücü)

ÖN-KAYITLI BAR (bugün ALTI ekseni reddeden barın AYNISI, gevşetilmedi):
  Δ$ > +28 · hiçbir yıl >%10 kötüleşmeyecek · maxDD +2 puandan fazla artmayacak ·
  EN KÖTÜ AY KÖTÜLEŞMEYECEK.
Ayrıca kullanıcının sorduğu için WR ayrıca raporlanır — AMA WR tek başına kabul ölçütü
DEĞİLDİR: rr2.5'te WR'yi yükseltmek kolaydır (hedefi yaklaştır), kârı yükseltmek zordur.

Kullanım:  py pw_wide_filter.py local
"""
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn, ema as ema_fn

ALL22 = ["AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETC",
         "ETH", "ICP", "LINK", "LTC", "NEAR", "SOL", "TRX", "VET", "XLM", "XMR", "XRP"]
# Evren genişletme sırası: pw_coins'in TRAIN'de sabitlediği sıra (TEST'e bakılmadan)
GENISLEME = ["TRX", "ALGO", "AAVE", "AVAX", "BTC", "LINK", "DOT", "ATOM", "VET",
             "XRP", "XLM", "DOGE", "LTC", "XMR", "ETC"]


def gen_kalite(m):
    """A.gen("donchian") ile AYNI sinyaller + her işleme KALİTE ÖLÇÜLERİ eklenir.
    Ölçüler yalnız GİRİŞ BARINDA bilinen bilgiden hesaplanır — lookahead yok.
    Dönüş: (entry_ns, exit_ts, R, sl_pct, {kalite})"""
    tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    e200 = ema_fn(d["close"], 200).values
    ch_hi = d["high"].rolling(40).max().shift(1).values
    ch_lo = d["low"].rolling(40).min().shift(1).values
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
        if d_ == 0 or i <= occ: continue
        dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
        if not ((d_ == 1 and dup) or (d_ == -1 and not dup)): continue
        e = cl[i]; sld = sl_a * a
        # ── KALİTE ÖLÇÜLERİ (giriş anında bilinen) ──
        kanal = ch_hi[i] if d_ == 1 else ch_lo[i]
        guc = (d_ * (e - kanal) / a) if np.isfinite(kanal) else np.nan
        mesafe = (d_ * (e - e200[i]) / a) if np.isfinite(e200[i]) else np.nan
        gunluk = (d_ * (e - _dprev[i]) / a) if np.isfinite(_dprev[i]) else np.nan
        adxv = adx_ser[i] if np.isfinite(adx_ser[i]) else np.nan
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
        out.append((idx[i].value, idx[j], R, sld / e,
                    {"adx": adxv, "guc": guc, "mesafe": mesafe, "gunluk": gunluk}))
        occ = j
    return out


def kur(donch, raw, olcu=None, esik=None):
    """Ankoru verilen coin listesi + kalite eşiğiyle koştur.
    Filtre ÜRETİM SIRASINDA uygulanır: elenen sinyal occ'u ilerletmez, koltuğu meşgul etmez.
    SLEEVE SIRASI ankorla birebir (DONCH→SQZ→BB)."""
    trades = []
    for c in donch:
        for t in gen_kalite(raw[c]):
            if olcu is not None:
                v = t[4].get(olcu)
                if not np.isfinite(v) or v < esik:
                    continue
            trades.append(t[:4])
    for c in A.SQZ: trades += A.gen("squeeze", raw[c])
    for c in A.BB_COINS: trades += A.gen_bb(raw[c])
    taken = A.seat_select(trades)
    r = np.array([R for _, R, _ in taken]); sp = np.array([s for _, _, s in taken])
    ex = [pd.Timestamp(x) for x, _, _ in taken]
    pnl = r * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.tz_localize(None).to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yr = pd.Series(pnl).groupby([x.year for x in ex]).sum()
    gp = r[r > 0].sum(); gl = -r[r < 0].sum()
    return dict(n=len(r), tot=float(pnl.sum()), wr=float((r > 0).mean() * 100),
                pf=float(gp / gl) if gl > 0 else float("inf"),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))), worst=float(mon.min()),
                posm=float((mon > 0).mean() * 100),
                yr={int(k): float(v) for k, v in yr.items()})


def hüküm(v, b, years):
    w = []
    if v["tot"] - b["tot"] <= 28: w.append(f"kâr {v['tot']-b['tot']:+.0f}$")
    for y in years:
        bb = b["yr"].get(y, 0)
        if abs(bb) > 1e-9 and (v["yr"].get(y, 0) - bb) / abs(bb) < -0.10:
            w.append(f"{y} kötü"); break
    if v["dd"] > b["dd"] + 2: w.append("maxDD")
    if v["worst"] < b["worst"] - 0.05: w.append("en kötü ay")
    return w


def satir(tag, v, b, years, mark=""):
    print(f"  {tag:<24s} {v['n']:>5d} {v['tot']:>+8.0f} {v['tot']-b['tot']:>+7.0f} "
          f"{v['wr']:>5.1f} {v['pf']:>5.2f} {v['dd']:>7.1f} {v['worst']:>+9.1f} "
          f"{v['posm']:>7.0f} | " + " ".join(f"{v['yr'].get(y, 0.0):>+7.0f}" for y in years) + mark)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    raw = {}
    for c in ALL22:
        try: raw[c] = fast_bt.load(c, source=source)
        except SystemExit: pass

    print(f"\n{'=' * 122}")
    print("=== GENİŞ EVREN + KALİTE FİLTRESİ — 'daha çok coin AMA daha seçici' ===")
    print("  Fikir: geniş evren BOLLUK yaratır, filtre SEÇER. Silme değil seçme.")
    print("  Kontrol: işlem sayısı ankorunkine (1579) yakın tutulur → maruziyet patlamaz.")

    taban = kur(A.DONCH, raw)
    years = sorted(taban["yr"])
    ok = taban["n"] == 1579 and abs(taban["tot"] - 1420.66) < 0.01
    print(f"\n  DOĞRULAMA: taban {taban['n']} işlem / ${taban['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — sonuçlar geçersiz'}")
    if not ok:
        return

    hdr = (f"  {'küme':<24s} {'işlem':>5s} {'toplam$':>8s} {'Δ$':>7s} {'WR%':>5s} {'PF':>5s} "
           f"{'maxDD%':>7s} {'kötü ay%':>9s} {'poz-ay':>7s} | " + " ".join(f"{y:>7d}" for y in years))

    # ── A) FİLTRESİZ geniş evren (referans: bugün çöken senaryo) ──
    print(f"\n--- A) FİLTRESİZ geniş evren (bugün çöken senaryo — referans) ---")
    print(hdr)
    satir("7 coin (CANLI)", taban, taban, years, "  ← ANKOR")
    genis = {}
    for k in (5, 10, 15):
        syms = A.DONCH + [c for c in GENISLEME[:k] if c in raw]
        genis[k] = kur(syms, raw)
        satir(f"{len(syms)} coin filtresiz", genis[k], taban, years)

    # ── B) GENİŞ EVREN + KALİTE EŞİĞİ ──
    print(f"\n--- B) GENİŞ EVREN + KALİTE EŞİĞİ (işlem sayısı ankora yakın tutulur) ---")
    olculer = {
        "adx":    [18, 22, 26, 30],
        "guc":    [0.0, 0.15, 0.30, 0.50],
        "mesafe": [0.0, 0.5, 1.0, 2.0],
        "gunluk": [0.0, 0.5, 1.0, 2.0],
    }
    sonuc = {}
    for k in (10, 15):
        syms = A.DONCH + [c for c in GENISLEME[:k] if c in raw]
        print(f"\n  ── {len(syms)} coin ──")
        print(hdr)
        satir("7 coin (CANLI)", taban, taban, years, "  ← ANKOR")
        for olcu, esikler in olculer.items():
            for e in esikler:
                v = kur(syms, raw, olcu, e)
                if v["n"] < 900 or v["n"] > 2400:      # ankordan çok uzaksa atla
                    continue
                w = hüküm(v, taban, years)
                sonuc[(len(syms), olcu, e)] = v
                satir(f"{olcu}≥{e}", v, taban, years, "  ★ GEÇTİ" if not w else "")

    # ── HÜKÜM ──
    print(f"\n{'=' * 122}\n=== HÜKÜM (ön-kayıtlı bar, gevşetilmedi) ===")
    print("  Δ$>+28 · hiçbir yıl >%10 kötü · maxDD +2p içinde · EN KÖTÜ AY kötüleşmeyecek")
    gecen = [(k, v) for k, v in sonuc.items() if not hüküm(v, taban, years)]
    for k, v in gecen:
        print(f"  ★ {k[0]} coin · {k[1]}≥{k[2]} → ${v['tot']:+.0f} ({v['tot']-taban['tot']:+.0f}) "
              f"WR %{v['wr']:.1f} · en kötü ay {v['worst']:+.1f}")
    if not gecen:
        print("  hiçbiri geçmedi.")

    # ── WR ÖZEL: kullanıcı sorduğu için ayrıca ──
    print(f"\n  --- WR'Yİ EN ÇOK YÜKSELTENLER (kâr ne olursa olsun) ---")
    print(f"  {'küme':<28s} {'WR%':>6s} {'ΔWR':>6s} {'toplam$':>9s} {'Δ$':>7s}")
    for k, v in sorted(sonuc.items(), key=lambda x: -x[1]["wr"])[:6]:
        print(f"  {f'{k[0]}c {k[1]}≥{k[2]}':<28s} {v['wr']:>6.1f} "
              f"{v['wr']-taban['wr']:>+6.1f} {v['tot']:>+9.0f} {v['tot']-taban['tot']:>+7.0f}")
    print(f"  {'7 coin (CANLI)':<28s} {taban['wr']:>6.1f} {0:>+6.1f} {taban['tot']:>+9.0f} {0:>+7.0f}")
    print(f"\n  ⚠ WR TEK BAŞINA ÖLÇÜT DEĞİL: rr2.5'te WR'yi yükseltmek kolaydır")
    print(f"  (hedefi yaklaştır), kârı yükseltmek zordur. Yukarıda WR ile Δ$ birlikte okunmalı.")


if __name__ == "__main__":
    main()
