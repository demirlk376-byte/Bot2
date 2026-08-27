"""
sessizlik.py — "Bot kaç gün sessiz kalır?" sorusunun BACKTEST cevabı.

NEDEN: 2026-08-27'de canlı bot 4-5 gündür işlem açmıyordu ve elimizde bunun
NORMAL mi ANORMAL mi olduğunu söyleyecek TEK bir sayı yoktu. Teşhis aracı
yazmak yerine önce dağılımı bilmek gerekir: ankorun 1579 işleminde ardışık
GİRİŞLER arası boşluk ne kadar? 4-5 gün kaçıncı yüzdelik?

Üç soru:
  1) DAĞILIM      — portföy seviyesinde giriş-arası boşluk (medyan/p75/p90/max)
  2) KOŞULLU      — sert hareketten SONRA boşluk uzuyor mu? (hipotez testi)
  3) BOŞLUK KÖTÜ MÜ — uzun sessizliği bitiren işlemin R'si daha mı kötü?

Ayrıca: kaç sinyal "koltuk yok" (MAX_POSITIONS) ya da "coin dolu" (per-coin occ)
diye ELENDİ. Canlıdaki 'already holds a position' satırının backtest karşılığı.

Kullanım:  python3 sessizlik.py local
"""
from __future__ import annotations
import sys, heapq
import numpy as np, pandas as pd
import fast_bt
import deployed_backtest as DB


def topla(source):
    """Ankorun sinyal üretimini birebir çağırır, ama giriş zamanını da tutar."""
    ham = []
    for c in DB.DONCH:
        for t in DB.gen("donchian", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1], t[2], t[3], "donchian", c))
    for c in DB.SQZ:
        for t in DB.gen("squeeze", fast_bt.load(c, source=source)):
            ham.append((t[0], t[1], t[2], t[3], "squeeze", c))
    for c in DB.BB_COINS:
        for t in DB.gen_bb(fast_bt.load(c, source=source)):
            ham.append((t[0], t[1], t[2], t[3], "bb", c))
    return sorted(ham, key=lambda t: t[0])


def koltuk(ham):
    """deployed_backtest.seat_select ile AYNI mantık — ama alınanı ve ELENENİ ayırır."""
    openh = []; alinan = []; elenen = []; ctr = 0
    for e_ns, x_ts, R, slp, sleeve, coin in ham:
        while openh and openh[0][0].value <= e_ns:
            heapq.heappop(openh)
        if len(openh) < DB.MAXPOS:
            ctr += 1
            heapq.heappush(openh, (x_ts, ctr, R))
            alinan.append((pd.Timestamp(e_ns, tz="UTC"), x_ts, R, slp, sleeve, coin))
        else:
            elenen.append((pd.Timestamp(e_ns, tz="UTC"), sleeve, coin))
    return alinan, elenen


def yuzdelik(g, etiket):
    g = np.asarray(g, float)
    print(f"  {etiket:24s} n={len(g):>4d} | medyan {np.median(g):5.2f}g | "
          f"ort {g.mean():5.2f}g | p75 {np.percentile(g,75):5.2f}g | "
          f"p90 {np.percentile(g,90):5.2f}g | p95 {np.percentile(g,95):5.2f}g | "
          f"max {g.max():6.2f}g")
    for esik in (2, 3, 4, 5, 7, 10):
        pay = (g >= esik).mean()
        print(f"      ≥{esik:>2d} gün sessizlik: {pay*100:5.1f}%  "
              f"({int((g>=esik).sum())} kez)   → ~yılda {(g>=esik).sum()/YIL:.1f} kez")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print("sessizlik.py — ankorun giriş-arası boşluk dağılımı\n")
    ham = topla(source)
    alinan, elenen = koltuk(ham)
    girisler = pd.DatetimeIndex([a[0] for a in alinan])
    global YIL
    YIL = (girisler[-1] - girisler[0]).days / 365.25
    print(f"\n  ham sinyal {len(ham)} → alınan {len(alinan)} | "
          f"koltuk yok diye elenen {len(elenen)} ({len(elenen)/len(ham)*100:.0f}%)")
    print(f"  dönem {girisler[0].date()} → {girisler[-1].date()}  ({YIL:.2f} yıl)")

    # ---------- 1) DAĞILIM ----------
    print(f"\n{'='*74}\n1) PORTFÖY SEVİYESİNDE GİRİŞ-ARASI BOŞLUK\n{'='*74}")
    gp = np.diff(girisler.values).astype("timedelta64[s]").astype(float) / 86400.0
    yuzdelik(gp, "TÜM KOLLAR (canlı)")

    # BB YALNIZ hafta sonu çalışır → hafta İÇİ bir sessizlik serisinde BB yok.
    # "Bot 4 gündür işlem açmıyor" hafta içi söyleniyorsa doğru taban BUDUR.
    gh = pd.DatetimeIndex([a[0] for a in alinan if a[4] != "bb"])
    ghg = np.diff(gh.values).astype("timedelta64[s]").astype(float) / 86400.0
    print()
    yuzdelik(ghg, "BB'siz (donch+squeeze)")

    gd = pd.DatetimeIndex([a[0] for a in alinan if a[4] == "donchian"])
    gdg = np.diff(gd.values).astype("timedelta64[s]").astype(float) / 86400.0
    print()
    yuzdelik(gdg, "yalnız donchian")

    # en uzun kuraklıklar
    print(f"\n  --- EN UZUN 10 SESSİZLİK (tüm kollar) ---")
    sira = np.argsort(gp)[::-1][:10]
    for k in sira:
        print(f"    {girisler[k].date()} → {girisler[k+1].date()}   {gp[k]:6.2f} gün")

    # ---------- 2) KOŞULLU: sert hareket sonrası ----------
    print(f"\n{'='*74}\n2) SERT HAREKET SESSİZLİĞE YOL AÇIYOR MU?\n{'='*74}")
    btc = fast_bt.load("BTC", source=source)
    b4 = fast_bt.resample(btc, "4h")
    # her girişin ANINDAKİ önceki 7 günlük BTC getirisi (|%|) — lookahead yok
    r7 = (b4["close"] / b4["close"].shift(42) - 1.0)          # 42×4s = 7 gün
    r7 = r7.reindex(girisler[:-1], method="ffill").values
    ok = np.isfinite(r7)
    mag = np.abs(r7[ok]) * 100.0
    g_ok = gp[ok]
    print(f"  n={ok.sum()} giriş, girişten ÖNCEKİ 7 günlük |BTC getirisi| ile eşleştirildi")
    kes = np.percentile(mag, [20, 40, 60, 80])
    grup = np.digitize(mag, kes)
    print(f"\n  {'kuşak':<22s} {'n':>4s} {'|BTC 7g|':>10s} {'medyan boşluk':>14s} {'ort':>8s} {'≥4g %':>7s}")
    for q in range(5):
        m = grup == q
        if m.sum() < 5: continue
        print(f"  Q{q+1} {'(en sakin)' if q==0 else '(en sert)' if q==4 else '':<18s} "
              f"{m.sum():>4d} {mag[m].mean():>9.1f}% {np.median(g_ok[m]):>13.2f}g "
              f"{g_ok[m].mean():>7.2f}g {(g_ok[m]>=4).mean()*100:>6.1f}%")
    # Spearman — scipy yok, rank korelasyonu elle (bağlar için ortalama rank)
    def _rank(v):
        o = np.argsort(v, kind="mergesort"); r = np.empty(len(v), float)
        r[o] = np.arange(1, len(v) + 1)
        # bağları ortalama rank'a çek
        vs = v[o]; i = 0
        while i < len(vs):
            j = i
            while j + 1 < len(vs) and vs[j + 1] == vs[i]: j += 1
            if j > i: r[o[i:j + 1]] = (i + j + 2) / 2.0
            i = j + 1
        return r
    ra, rb = _rank(mag), _rank(g_ok)
    rho = np.corrcoef(ra, rb)[0, 1]
    nn = len(mag)
    t = rho * np.sqrt((nn - 2) / max(1e-12, 1 - rho ** 2))   # ~t(n-2)
    # normal yaklaşımıyla iki yönlü p (n>1000, t≈z)
    p = 2 * 0.5 * (1.0 - np.math.erf(abs(t) / np.sqrt(2))) if hasattr(np, "math") else \
        2 * 0.5 * (1.0 - __import__("math").erf(abs(t) / np.sqrt(2)))
    print(f"\n  Spearman(|BTC 7g hareket| , sonraki boşluk) = {rho:+.4f}  (t={t:+.2f}, p={p:.4f}, n={nn})")
    if p >= 0.05:
        print("  → İLİŞKİ YOK. 'Sert hareket kanalı genişletir, bot susar' hipotezi ÇÜRÜK.")
    elif rho < 0:
        print("  → TERS YÖNDE: sert hareket sessizliği KISALTIYOR (bot daha çok işlem açıyor).")
    else:
        print("  → HAREKET SESSİZLİĞİ AÇIKLIYOR.")

    # ---------- 3) SESSİZLİK KÖTÜ MÜ? ----------
    print(f"\n{'='*74}\n3) UZUN SESSİZLİĞİ BİTİREN İŞLEM DAHA MI KÖTÜ?\n{'='*74}")
    R = np.array([a[2] for a in alinan[1:]])       # boşluğun ARDINDAN gelen işlem
    for esik in (3, 4, 5, 7):
        m = gp >= esik
        if m.sum() < 10: continue
        a_, b_ = R[m], R[~m]
        se = np.sqrt(a_.var(ddof=1)/len(a_) + b_.var(ddof=1)/len(b_))
        z = (a_.mean() - b_.mean()) / se
        print(f"  boşluk ≥{esik}g: n={m.sum():>4d} ortR {a_.mean():+.3f}  |  "
              f"diğer n={(~m).sum():>4d} ortR {b_.mean():+.3f}  |  fark {a_.mean()-b_.mean():+.3f}R  z={z:+.2f}")
    print("  (z>2 → sessizlikten sonraki işlem DAHA İYİ; z<-2 → daha kötü; arası = fark yok)")

    # ---------- 4) KOLTUK/DOLU ELEMESİ ----------
    print(f"\n{'='*74}\n4) 'ALREADY HOLDS A POSITION' KARŞILIĞI\n{'='*74}")
    print(f"  MAX_POSITIONS={DB.MAXPOS} dolu olduğu için elenen sinyal: {len(elenen)} "
          f"({len(elenen)/len(ham)*100:.1f}% / ~yılda {len(elenen)/YIL:.0f})")
    if elenen:
        ec = pd.Series([e[2] for e in elenen]).value_counts()
        print(f"  en çok elenen coin: " + ", ".join(f"{k}:{v}" for k, v in ec.head(6).items()))
    # aynı anda kaç pozisyon açık — zaman ağırlıklı
    olay = []
    for a in alinan:
        olay.append((a[0], +1)); olay.append((pd.Timestamp(a[1]), -1))
    olay.sort()
    acik = 0; sure = {}; onceki = olay[0][0]
    for t, d in olay:
        sure[acik] = sure.get(acik, 0.0) + (t - onceki).total_seconds()
        acik += d; onceki = t
    tot = sum(sure.values())
    print(f"\n  Zamanın yüzdesiyle KAÇ POZİSYON AÇIK:")
    for k in sorted(sure):
        print(f"    {k} pozisyon: {sure[k]/tot*100:5.1f}%")
    dolu = sure.get(DB.MAXPOS, 0.0) / tot * 100
    print(f"  → Zamanın {dolu:.1f}%'inde tavan ({DB.MAXPOS}) DOLU: yeni sinyal giremez.")

    # ---------- 5) COIN BAŞINA DOLULUK ----------
    print(f"\n{'='*74}\n5) COIN BAŞINA 'DOLU' ORANI (one-per-symbol kilidi)\n{'='*74}")
    print("  Canlıdaki 'already holds a position' satırının backtest karşılığı:")
    print("  bir coin zamanın yüzde kaçında AÇIK pozisyonla kilitli?\n")
    bas, son = girisler[0], max(pd.Timestamp(a[1]) for a in alinan)
    kapsam = (son - bas).total_seconds()
    satir = []
    for c in DB.DONCH + DB.SQZ + DB.BB_COINS:
        t = [(a[0], pd.Timestamp(a[1])) for a in alinan if a[5] == c]
        if not t: continue
        # occ zaten üst üste binmeyi engelliyor → doğrudan topla
        acik_s = sum((x - e).total_seconds() for e, x in t)
        # ortalama tutma süresi
        ort = acik_s / len(t) / 3600.0
        satir.append((acik_s / kapsam * 100, c, len(t), ort))
    for pay, c, n, ort in sorted(satir, reverse=True):
        sleeve = ("donchian" if c in DB.DONCH else "squeeze" if c in DB.SQZ else "bb")
        print(f"    {c:<5s} ({sleeve:<8s}) n={n:>3d}  DOLU {pay:5.1f}% zamanın  |  "
              f"ort tutma {ort:5.1f} saat ({ort/24:.2f} gün)")
    dch = [x for x in satir if x[1] in DB.DONCH]
    print(f"\n  → donchian coinleri ORTALAMA zamanın {np.mean([x[0] for x in dch]):.1f}%'inde DOLU.")
    print(f"    Yani rastgele bir anda bir donchian sinyali gelirse ~{np.mean([x[0] for x in dch]):.0f}%")
    print(f"    ihtimalle 'already holds a position' ile ELENİR. Canlı log NORMAL.")

    # ---------- 6) ÖZET HÜKÜM ----------
    print(f"\n{'='*74}\n6) HÜKÜM\n{'='*74}")
    for g in (4, 5, 6, 7):
        pay = (gp >= g).mean() * 100
        yuz = (gp < g).mean() * 100
        print(f"  {g} gün sessizlik → yüzdelik {yuz:5.2f}  |  yılda ~{(gp>=g).sum()/YIL:.1f} kez"
              f"{'   ← ANKORDA HİÇ GÖRÜLMEDİ' if (gp>=g).sum()==0 else ''}")
    print(f"\n  Ankorun {YIL:.2f} yılında EN UZUN sessizlik: {gp.max():.2f} gün.")



if __name__ == "__main__":
    main()
