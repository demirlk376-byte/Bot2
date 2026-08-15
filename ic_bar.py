"""
ic_bar.py — MEVCUT DONCHIAN'A 5 DAKİKALIK "BAR İÇİ" TEŞHİSİ.

FİKİR KULLANICININ: yeni strateji kurmak yerine, elimizdeki 5dk veriyi MEVCUT
sisteme filtre olarak kullanmak. Bugüne kadar test EDİLEMEZDİ — 5dk veri yoktu.

NEDEN BU, BUGÜNKÜ 14 EKSENDEN FARKLI:
  fake_kirilim.py sahte kırılım grubunu ZATEN bulmuştu: z=+6.39, ort R −0.2488.
  Yani NEGATİF ALT GRUP VAR ve bugünkü kuralın birinci şartını sağlıyor.
  Üç uygulaması da düştü çünkü o grubu ancak KIRILIM OLDUKTAN SONRA (fiyat geri
  düşünce) tanıyabiliyorduk — karar anında bilinmiyordu.
  5dk verisi tam bu boşluğu doldurabilir: 4 SAATLİK bar KAPANIRKEN, o barın
  İÇİNDEKİ 48 tane 5dk barı ZATEN KAPANMIŞTIR. Yani bar içi yapı karar anında
  BİLİNİYOR. Look-ahead yok, yeni bilgi var.

⚠ VENUE KARIŞIMI — bilerek ve etiketli:
  SİNYALLER: MEXC 1h (ankorun tam olarak kullandığı veri, birebir üretilir)
  ÖZELLİKLER: Binance 5dk (MEXC'te 5dk yok)
  Kapanış korelasyonu 0.99976, |fark| 0.83bp ölçüldü (veri_binance --venue-fark),
  o yüzden bar-içi ŞEKİL özellikleri taşınabilir kabul ediliyor. Ama bir özellik
  eşik geçerse MEXC'te doğrulanmadan üretime ALINMAZ.

⚠ BU AŞAMA YALNIZ TEŞHİS. Eşik seçilmiyor, filtre kurulmuyor. Önce sorulacak tek
  soru: herhangi bir özellik ORTALAMA R'Sİ NEGATİF bir alt grup ayırıyor mu?
  (Bugünkü kural: negatif alt grup GEREK şart. Yoksa filtre kesinlikle para
  kazandırmaz — donchian atr_orani'nda z=+2.15 vardı ama negatif grup yoktu ve
  walk-forward −$41 verdi.)

⚠ ÇOKLU TEST: 6 özellik deneniyor → Bonferroni α = 0.05/6 = 0.0083.
  Rapor hem ham hem düzeltilmiş eşiği basıyor.

Kullanım (VPS'te):  python3 ic_bar.py
"""
from __future__ import annotations

import heapq
import sys

import numpy as np
import pandas as pd

import deployed_backtest as A
import fast_bt
import mtf
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy

CACHE = "data"
KANAL = 40          # DonchianStrategy(channel=40) — ankorla aynı


def donchian_izli(m: pd.DataFrame):
    """A.gen('donchian', m) ile BİREBİR aynı işlemler, ama bar konumu ve
    KIRILIM SEVİYESİ de saklanıyor (A.gen bunları atıyor)."""
    tf, win, sl_a, rr, mh = A.CFG["donchian"]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(
        d.index.normalize()).values
    up = d["close"].values > _dprev
    s = DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
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
        # KIRILIM SEVİYESİ: kanal, SİNYAL BARINDAN ÖNCEKİ 40 bar (bar i hariç)
        k0 = max(0, i - KANAL)
        seviye = hi[k0:i].max() if d_ == 1 else lo[k0:i].min()
        out.append(dict(t0=idx[i], i=i, yon=d_, R=float(R), slp=float(sld / e),
                        exit_ts=idx[j], atr=float(a), seviye=float(seviye),
                        kapanis=float(e)))
        occ = j
    return out


def ozellikler(tr: dict, b5: pd.DataFrame, tf_saat: int = 4) -> dict | None:
    """4 saatlik barın İÇİNDEKİ 5dk barlarından özellikler.
    Hepsi karar anında (4h kapanışı) BİLİNİYOR — bar içi tüm 5dk barları kapanmış."""
    t0 = tr["t0"]; t1 = t0 + pd.Timedelta(hours=tf_saat)
    sub = b5.loc[(b5.index >= t0) & (b5.index < t1)]
    if len(sub) < 24:                      # 4 saatte 48 bar bekleriz; yarısından az → atla
        return None
    hi = sub["high"].values; lo = sub["low"].values
    cl = sub["close"].values; vol = sub["volume"].values
    n = len(sub); d_ = tr["yon"]; lvl = tr["seviye"]; a = tr["atr"]
    if a <= 0:
        return None
    # 1) UÇ NOKTA NE ZAMAN OLDU (0=barın başı, 1=sonu). Geç = kapanışa momentum.
    uc_i = int(np.argmax(hi) if d_ == 1 else np.argmin(lo))
    tepe_konum = uc_i / max(n - 1, 1)
    # 2) SEVİYE İLK NE ZAMAN GEÇİLDİ (erken geçip tutmak = güçlü)
    gec = np.where(hi > lvl)[0] if d_ == 1 else np.where(lo < lvl)[0]
    kirilim_ani = (gec[0] / max(n - 1, 1)) if len(gec) else 1.0
    # 3) SEVİYENİN ÖTESİNDE KAPANAN 5dk BAR ORANI (kırılımdan sonrası)
    if len(gec):
        sonra = cl[gec[0]:]
        ustunde = float((sonra > lvl).mean() if d_ == 1 else (sonra < lvl).mean())
    else:
        ustunde = 0.0
    # 4) UÇ NOKTADAN SONRAKİ GERİ ÇEKİLME (ATR biriminde) — fade ölçüsü
    if uc_i < n - 1:
        if d_ == 1:
            geri = (hi[uc_i] - lo[uc_i:].min()) / a
        else:
            geri = (hi[uc_i:].max() - lo[uc_i]) / a
    else:
        geri = 0.0
    # 5) HACMİN KAÇI KIRILIMDAN SONRA (katılım ölçüsü)
    tv = vol.sum()
    hacim_sonra = float(vol[gec[0]:].sum() / tv) if (len(gec) and tv > 0) else 0.0
    # 6) SON ÇEYREK NET HAREKET / bar aralığı (kapanışa doğru güç)
    q = max(n // 4, 1)
    ar = hi.max() - lo.min()
    son_ceyrek = float(d_ * (cl[-1] - cl[-q]) / ar) if ar > 0 else 0.0
    return dict(tepe_konum=tepe_konum, kirilim_ani=kirilim_ani, ustunde=ustunde,
                geri_cekilme=float(geri), hacim_sonra=hacim_sonra,
                son_ceyrek=son_ceyrek)


OZ = ["tepe_konum", "kirilim_ani", "ustunde", "geri_cekilme",
      "hacim_sonra", "son_ceyrek"]


def main() -> None:
    print("=" * 112)
    print("=== BAR İÇİ 5dk TEŞHİSİ — mevcut donchian'a yeni bilgi ===")
    print("  4 saatlik bar KAPANIRKEN içindeki 48 adet 5dk barı ZATEN kapanmıştır.")
    print("  Yani bar içi yapı KARAR ANINDA bilinir. Look-ahead yok, YENİ bilgi var.")
    print("  fake_kirilim.py negatif alt grubu bulmuştu (−0.2488R) ama karar anında")
    print("  tanıyamıyordu. Bu veri tam o boşluğu hedefliyor.")

    # ── KONTROL: ankor birebir üretiliyor mu? ──
    trades = []
    for c in A.DONCH: trades += A.gen("donchian", fast_bt.load(c, source="local"))
    for c in A.SQZ: trades += A.gen("squeeze", fast_bt.load(c, source="local"))
    for c in A.BB_COINS: trades += A.gen_bb(fast_bt.load(c, source="local"))
    taken = A.seat_select(trades)
    r = np.array([R for _, R, _ in taken]); sp = np.array([s for _, _, s in taken])
    tot = (r * np.minimum(A.RISKF, A.CAP * sp) * A.BAL0).sum()
    ok = len(taken) == 1579 and abs(tot - 1420.66) < 1.0
    print(f"\n  DOĞRULAMA (ankor): {len(taken)} işlem / ${tot:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — durduruldu'}")
    if not ok:
        return

    # ── donchian işlemleri + bar içi özellikler ──
    kayit = []
    eksik = 0
    for c in A.DONCH:
        m = fast_bt.load(c, source="local")
        tr = donchian_izli(m)
        p5 = f"{CACHE}/{c}_bnc_5m.csv"
        try:
            b5 = pd.read_csv(p5, index_col=0, parse_dates=True)
            if b5.index.tz is None:
                b5.index = b5.index.tz_localize("UTC")
        except FileNotFoundError:
            print(f"  {c}: 5dk veri YOK ({p5}) — veri_binance.py ile çek"); continue
        n0 = len(kayit)
        for t in tr:
            o = ozellikler(t, b5)
            if o is None:
                eksik += 1; continue
            kayit.append({**t, **o, "coin": c})
        print(f"  {c:<5s} {len(tr):>4d} sinyal → {len(kayit)-n0:>4d} özellik çıkarıldı",
              flush=True)
    if len(kayit) < 200:
        print(f"\n  ⛔ n={len(kayit)} çok az."); return
    kap = len(kayit) / (len(kayit) + eksik) * 100
    print(f"\n  toplam {len(kayit)} donchian sinyali · 5dk kapsama %{kap:.0f}"
          f" (eşleşmeyen {eksik})")
    if kap < 80:
        print(f"  ⛔ KAPSAMA GUARD'I: %{kap:.0f} < %80. Hüküm verilmez.")
        return

    df = pd.DataFrame(kayit)
    R = df["R"].values
    print(f"  bu sinyallerin ort R'si {R.mean():+.4f} (ankor donchian tabanı)")

    # ── TEŞHİS: her özellik NEGATİF alt grup ayırıyor mu? ──
    print(f"\n{'='*112}")
    print("=== ÖZELLİK BAZINDA BEŞTE BİRLİK DİLİMLER (Q1=en düşük) ===")
    print("  ARANAN: ortalama R'si NEGATİF bir dilim. Yoksa filtre PARA KAZANDIRMAZ")
    print("  (bugün kanıtlandı: negatif grup GEREK şart).")
    print(f"\n  {'özellik':<14s} {'Q1':>9s} {'Q2':>9s} {'Q3':>9s} {'Q4':>9s} {'Q5':>9s}"
          f" {'z(uç)':>7s} {'negatif dilim?':>16s}")
    bulgu = []
    for k in OZ:
        v = df[k].values
        q = pd.qcut(pd.Series(v).rank(method="first"), 5, labels=False)
        ort = [R[q == i].mean() for i in range(5)]
        n_i = [int((q == i).sum()) for i in range(5)]
        # uç dilimler arası z
        a1, a5 = R[q == 0], R[q == 4]
        z = (a5.mean() - a1.mean()) / np.sqrt(a5.var(ddof=1)/len(a5) + a1.var(ddof=1)/len(a1))
        neg = [i for i, o in enumerate(ort) if o < 0]
        etk = ("Q" + ",Q".join(str(i+1) for i in neg)) if neg else "YOK"
        print(f"  {k:<14s} " + " ".join(f"{o:>+9.4f}" for o in ort) +
              f" {z:>+7.2f} {etk:>16s}")
        if neg:
            for i in neg:
                bulgu.append((k, i, ort[i], n_i[i], R[q == i]))

    print(f"\n{'='*112}\n=== HÜKÜM ===")
    if not bulgu:
        print("  ✗ HİÇBİR özellik negatif ortalamalı dilim ayırmıyor.")
        print("    Bugünkü kurala göre bu eksende filtre PARA KAZANDIRAMAZ.")
        print("    Bar içi 5dk yapısı donchian sinyalinin kalitesini AYRIŞTIRMIYOR.")
        return
    print(f"  {len(bulgu)} negatif dilim bulundu. Bonferroni: 6 özellik → α=0.0083")
    print(f"\n  {'özellik':<14s} {'dilim':>6s} {'n':>6s} {'ort R':>9s} "
          f"{'%95 aralık':>20s} {'p':>9s} {'geçti?':>8s}")
    from math import erf, sqrt
    for k, i, o, n_i, arr in sorted(bulgu, key=lambda x: x[2]):
        se = arr.std(ddof=1) / np.sqrt(len(arr))
        t = o / se
        p = 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))
        print(f"  {k:<14s} {'Q'+str(i+1):>6s} {n_i:>6d} {o:>+9.4f} "
              f"[{o-1.96*se:>+8.4f},{o+1.96*se:>+8.4f}] {p:>9.5f} "
              f"{'✓' if p < 0.0083 else '✗':>8s}")
    print(f"\n  ⚠ BU YALNIZ TEŞHİS. Geçen bir dilim OLSA BİLE filtre kurulmadan önce:")
    print(f"    1. o dilimi kesmenin PORTFÖY etkisi ölçülmeli (koltuk seçimi değişir)")
    print(f"    2. TRAIN/TEST/OOS ayrı ayrı tutmalı")
    print(f"    3. MEXC 5dk verisiyle doğrulanmalı (özellikler Binance'ten)")
    print(f"    Bugün donchian atr_orani z=+2.15 ile 'anlamlı'ydı ama negatif grup")
    print(f"    yoktu ve walk-forward −$41 verdi. Anlamlılık ≠ para.")


if __name__ == "__main__":
    main()
