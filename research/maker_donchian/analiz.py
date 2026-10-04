"""Donchian maker giriş testi — ON_KAYIT.md'deki modelin birebir uygulaması.
Girdi: sinyaller.csv (ikizin 413 donchian sinyali), islemler.csv.gz (veri/maker1 dalı, Binance aggTrades),
       ikiz veritabanı (yalnız sl0 için: Δ'yı R'ye çevirmek).
Kullanım: python analiz.py <islemler.csv.gz> <ikiz.db>"""
import csv
import gzip
import json
import sqlite3
import sys
from collections import defaultdict

import numpy as np

YOL = sys.argv[1]
DB = sys.argv[2] if len(sys.argv) > 2 else None
SURE = 48_000                    # 45 sn bekleme + 3 sn yoklama/iptal
UCRET = 1.0                      # taker ücreti, bp
SENARYO = {"TABAN": dict(G=75_000, Y=1.0, e=0.0), "MUHAFAZAKAR": dict(G=120_000, Y=0.5, e=0.5)}

sinyaller = list(csv.DictReader(open(__file__.rsplit("/", 1)[0] + "/sinyaller.csv")))
islem = defaultdict(list)
with gzip.open(YOL, "rt") as f:
    for r in csv.DictReader(f):
        islem[int(r["i"])].append((int(r["dt_ms"]), float(r["fiyat"])))
for v in islem.values():
    v.sort()

sl0 = {}
if DB:
    c = sqlite3.connect(DB)
    q = c.execute("select strategy_scores from trades where strategy_scores like '%\"strategy\": \"donchian\"%' "
                  "order by entry_time").fetchall()
    for i, (sc,) in enumerate(q):
        sl0[i] = json.loads(sc)["sl0"]


def fiyat_an(tr, x):
    """x anındaki son işlem fiyatı (x'ten önce işlem yoksa x'ten sonraki ilk işlem)."""
    son = None
    for dt, p in tr:
        if dt <= x:
            son = p
        else:
            return son if son is not None else p
    return son


def degerlendir(s, tr, G, Y, e):
    L = float(s["L"])
    uzun = s["yon"] == "long"
    sg = 1 if uzun else -1
    p0 = fiyat_an(tr, G)

    def piyasa(p):           # L'ye göre bp maliyet (pozitif = aleyhte)
        return sg * (p * (1 + sg * Y / 1e4) - L) / L * 1e4 + UCRET

    m = piyasa(p0)
    if sg * (p0 - L) < 0:    # limit piyasayı kesiyor → post-only reddi → hemen piyasa
        return m, m, "red"
    esik = L * (1 - sg * e / 1e4)
    doldu = any(G < dt <= G + SURE and sg * (p - esik) < 0 for dt, p in tr)
    if doldu:
        return m, 0.0, "doldu"
    return m, piyasa(fiyat_an(tr, G + SURE)), "yedek"


def bootstrap(d, hafta, n=10_000, seed=7):
    rng = np.random.default_rng(seed)
    gr = defaultdict(list)
    for x, h in zip(d, hafta):
        gr[h].append(x)
    bloklar = list(gr.values())
    ort = []
    for _ in range(n):
        sec = rng.integers(0, len(bloklar), len(bloklar))
        v = np.concatenate([bloklar[k] for k in sec])
        ort.append(v.mean())
    return np.percentile(ort, [2.5, 97.5])


def main():
    eksik = [i for i in range(len(sinyaller)) if len(islem.get(i, [])) < 2]
    gecerli = [i for i in range(len(sinyaller)) if i not in eksik]
    # akıl kontrolü: L, Binance'in kapanıştaki son işlem fiyatına yakın mı?
    sap = [abs(fiyat_an(islem[i], 0) / float(sinyaller[i]["L"]) - 1) * 1e4 for i in gecerli]
    print(f"sinyal {len(sinyaller)} · verili {len(gecerli)} · verisiz {len(eksik)}")
    print(f"akıl kontrolü |Binance kapanış − L|: medyan {np.median(sap):.1f} bp, %90 {np.percentile(sap, 90):.1f} bp")
    sonuc = {}
    for ad, prm in SENARYO.items():
        rows = []
        for i in gecerli:
            s = sinyaller[i]
            m, k, durum = degerlendir(s, islem[i], **prm)
            hafta = int(s["t_ms"]) // (7 * 86_400_000)
            yil = __import__("time").gmtime(int(s["t_ms"]) / 1000).tm_year
            L = float(s["L"])
            r_bp = abs(L - sl0[i]) / L * 1e4 if i in sl0 else None
            rows.append(dict(i=i, coin=s["coin"], yil=yil, hafta=hafta, m=m, k=k, d=m - k, durum=durum,
                             dR=(m - k) / r_bp if r_bp else None))
        d = np.array([r["d"] for r in rows])
        lo, hi = bootstrap(d, [r["hafta"] for r in rows])
        say = defaultdict(int)
        for r in rows:
            say[r["durum"]] += 1
        dR = [r["dR"] for r in rows if r["dR"] is not None]
        print(f"\n=== {ad} {prm}")
        print(f"  piyasa maliyeti ort {np.mean([r['m'] for r in rows]):+.2f} bp · maker ort "
              f"{np.mean([r['k'] for r in rows]):+.2f} bp")
        print(f"  Δ (piyasa − maker) ort {d.mean():+.2f} bp  %95 [{lo:+.2f}, {hi:+.2f}]  medyan {np.median(d):+.2f}")
        print(f"  durum: limitte doldu {say['doldu']} · post-only reddi {say['red']} · 45sn yedek {say['yedek']}"
              f"  (dolum oranı {say['doldu'] / len(rows):.0%})")
        if dR:
            print(f"  Δ R cinsinden ort {np.mean(dR):+.4f} R/işlem")
        for anahtar in ("coin", "yil"):
            gr = defaultdict(list)
            for r in rows:
                gr[r[anahtar]].append(r["d"])
            print("  " + anahtar + ": " + " · ".join(f"{k} {np.mean(v):+.1f}({len(v)})" for k, v in sorted(gr.items())))
        sonuc[ad] = dict(ort=float(d.mean()), lo=float(lo), hi=float(hi), n=len(rows), dolum=say["doldu"] / len(rows),
                         dR=float(np.mean(dR)) if dR else None)
    t, mu = sonuc["TABAN"], sonuc["MUHAFAZAKAR"]
    if t["ort"] > 0 and t["lo"] > 0 and mu["ort"] > 0:
        karar = "AÇIK KALSIN"
    else:
        karar = "KAPAT"
    print(f"\nÖN KAYITLI KARAR: {karar}")
    json.dump(dict(sonuc=sonuc, karar=karar), open("sonuc.json", "w"), indent=1)


main()
