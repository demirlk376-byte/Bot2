"""
cvd_kol.py — CVD (Kumulatif Hacim Deltasi) 4H LONG KOLU · AYRI HAVUZ OLCUMU.

=============================================================================
NEDEN BU TEST (arsiv denetiminin gerekcesi)
=============================================================================
Bu aile daha once UC KEZ denendi ve ucu de ledger'a duzgun islenmedi:
  (1) research_orderflow_vwap.py — taker_buy_ratio'yu BB-fade tabanina kova
      filtresi olarak ekledi. RED, ledger'a hic girmedi.
  (2) research_orderflow_delta.py (commit 3ce9c79) — TAM BU AILE. Docstring'deki
      hukum "edge YOK" DEGIL: "BTC absorpsiyon saglam gorunuyor, TR+TE ikisi de
      pozitif, AMA yil-yil kirilim var (2024 PF 0.58) → canli para icin
      yeterince saglam degil, monitor moduna al" idi.
  (3) orderflow.py + analyze_orderflow.py — canli monitor-only kolektor.
      orderflow_log.csv bu makinede YOK (VPS'te). Ileri deneyin sonucu bu
      depodan BILINMIYOR.

Onceki reddin gerekcesini gecersiz kilan UC yeni sey:
  · Red "edge yok" degil "guven yetmiyor" idi → AYRI HAVUZ mimarisi (ayri_havuz.py)
    bu kategoriyi canlandirabilir: BTC kitapta olmadigi icin kol SIFIR islem
    itiyor; bar "kitabi gec"ten "kendi orneklemende sifiri gec"e dusuyor.
  · GENIS STOP KURALI (kayma = 15.85bp / stop_mesafesi) onceki isin tek calistigi
    zaman dilimini (1h, ~0.137R kayma) yapisal olarak yanlis ilan ediyor. 4H'de
    maliyet ~0.061R.
  · Veri oncekinden 3.3x buyuk (2023-01..2026-04, git 647d765^ + disk).

KULLANICININ ASIL FIKRI (yeni tepe + dusen CVD -> SHORT) BU DOSYADA YOK ve
BILEREK YOK: onceki olcumde short bacak n=1400'de -0.1531R, z=-4.80, hem TRAIN
hem TEST'te ayni yanlis isaret (K2: short tarafta edge yok). Sadece AYNASI
(yeni dip + yukselen CVD -> LONG) test edilir.

=============================================================================
ON-KAYITLI TASARIM (parametreler KOSMADAN ONCE sabitlendi, argmax YOK)
=============================================================================
ASAMA 0 — VERI KAPISI (kol testinden ONCE; bloke ederse test YAPILMAZ)
  (c) Her coin icin taker verisinde >24 saatlik bosluk SAYISI raporlanir. CVD
      cumsum oldugu icin 24 saatten buyuk bosluklu coin ELENIR.
  (d0) CAPRAZ-COIN ON SARTI: >=6 coin veri denetiminden gecmeli. Gecmezse
      SONUC = "olculemedi", kol KURULMAZ. Tek coin (BTC) GECERLI SAYILMAZ.

ASAMA 1 — SINYAL (LONG-ONLY; short bacak on-kayitla YASAK)
  Barlar : 4H — fast_bt.resample(data/{COIN}_fut_1h.csv, "4H")  [MEXC fiyati,
           ankorun kaynagi]. Taker ORANI Binance'ten gelir, FIYAT MEXC kalir.
  delta_t = volume_mexc_t * (2*buy_ratio_binance_t - 1) ;  CVD = cumsum(delta)
  GIRIS (bar KAPANISINDA):
      low[i] <= min(low[i-lb : i+1])                     (yeni lb-bar dibi)
      VE CVD[i] > CVD[p], p = i-lb + argmin(low[i-lb:i]) (onceki dipten beri net alim)
      -> LONG. Short ayna KULLANILMAZ.
  IZGARA ORTASI (sabit): lb=20, SL=2.0*ATR14(4H), RR=2.0, max_hold=24 bar, trend filtresi YOK.
  Duyarlilik izgarasi (SADECE aile testi icin, secim icin DEGIL):
      lb{10,20,40} x SL{1.5,2.0,3.0} x RR{1.5,2.0,2.5} x mh{12,24,48} = 81 hucre.

ASAMA 2 — GECME BARI (gevsetme yok)
  (d0) >=6 coin veri kapisindan gecmeli.
  (d1) AILE: 81 hucrenin TEST medyan R'si > 0 VE pozitif hucre orani >= %70
       (etkin df 10-20; %55 YETMEZ — 1D trend kolunu yanlis kalibre kural gecirmisti).
  (d2) COIN-DISI TEKRAR: izgara-ortasi hucre coin bazinda, coinlerin >=%60'inda
       kaymali ort R > 0. BTC TEK BASINA GECERLI SAYILMAZ.
  (a)  ayri_havuz.olcek_bul ile kolun olcegi kitabin bilesik maxDD'sine esitlenir,
       sonra kar_sabit ile Delta$ >= +36.
  (b)  TEST diliminde (giris >= 2025-01-01) de pozitif.
  (c)  en kotu ay taban %-32.62'den kotulesmiyor.

LOOKAHEAD ONLEMLERI
  · Sinyal yalniz kapanmis barin verisiyle; giris sinyal barinin KAPANISI
    (kitapla ayni varsayim), cikis taramasi i+1'den.
  · CVD[i]-CVD[p] gecmis pencere toplamidir. Pencerede EKSIK taker bari varsa
    sinyal URETILMEZ (bosluk uzerinden cumsum farki alinmaz).
  · ATR14 yalniz i'ye kadarki barlardan (ewm, nedensel).
  · Binance taker MEXC barina ayni 4H kovasinda (open_time) joinlenir; ileri kaydirma yok.
  · TRAIN: giris VE cikis < 2025-01-01. TEST: giris >= 2025-01-01. Siniri gecen
    islem hicbir kovaya girmez.

=============================================================================
OLCULEN SONUC (2026-09-13) — HUKUM: GECMEDI / "OLCULEMEDI"
=============================================================================
TABAN DOGRULANDI: koltuk(base_trades,7) = 1579 islem. Kaymali kitap +$1331.66,
ort R +0.1764, bilesik maxDD %52.23, en kotu ay %-32.62, TEST +$623.13 — ankorla birebir.

ASAMA 0 BLOKE ETTI (karar burada bitiyor):
  · 12 canli coinin 0'inda taker verisi var. data.binance.vision, fapi.binance.com,
    api.binance.com, data-api.binance.vision, api.bybit.com — HEPSI proxy'de 403
    (connect_rejected). Indirme bu oturumda YAPILAMADI.
  · BTC: 6576 4H bar 2023-01-01..2026-04-30 AMA 2884 SAATLIK (120 gun) DELIK var:
    2025-01..2025-04 — tam TRAIN/TEST sinirinda. Kural (c) BTC'yi ELER.
    (Brief "2023-01..2026-04, 40 ay" diyordu; gercegi 36 ay + 4 aylik delik.)
  · ETH: 912 4H bar, 2164h delik. ELER.
  · (d0) 0/12 >= 6 DEGIL → ON-KAYITLI HUKUM: "olculemedi, kol kurulmaz."

KAYIT (karar DEGIL) — BTC+ETH, delik-guvenli pencere korumasiyla olculdu:
  izgara ortasi lb20/SL2.0/RR2.0/mh24, LONG-only:
    kol tek basina n=85 · hamR +0.3923 · KAYMALI R +0.3335 · z=+2.52 · kayma 0.059R
      → kitabin +0.1764'unu GECIYOR (yaklasik 2x)
    TRAIN n=39 +0.1839 (z+0.97) | TEST n=46 +0.4603 (z+2.50) → TRAIN/TEST 0.40x
      yani YURUYEN-ILERI BOZULMA YOK; TEST daha guclu (12 fikri olduren duvarin TERSI)
    coin: BTC n=75 +0.3867 (z+2.73) | ETH n=10 -0.0662 → (d2) 1/2 = %50 < %60 GECMEDI
    yil-yil: 2023 +0.4730(n16) · 2024 -0.0173(n23) · 2025 +0.2987(n30) · 2026 +0.7633(n16)
      → 2024 KIRILIMI 2026-06 reddindekiyle AYNI, aynen tekrar uretti.
  AYRI HAVUZ (risk esitlenmis): S=1 D$ +139.17 / DTEST +103.87 / en kotu ay -22.24
    S=2,3 D$ +147.53 / DTEST +112.23 / en kotu ay -22.24 → (a)(b)(c) UCU DE GECTI
    kitap 1579/1579 KORUNDU (ayri havuz sifir itme, dogrulandi)
    kitap+kol bilesik maxDD %49.00 < %52.23 → olcek_bul 1.000 dondu, D$ risk cezasi GORMEDI
  AILE 81 hucre: TUM medyan +0.1714 (poz %100) · TRAIN +0.1406 (%97.5) ·
    TEST medyan +0.1735 (poz %87.7) → brief esigiyle (d1) GECTI, p=0.0037
    AMA 81 hucre = 3 lb x 27 CIKIS kurali; ayni lb ayni giris setini paylasiyor
    (lb10:186, lb20:111, lb40:61 ortak sinyal). Aile testi CIKIS saglamligini olcer,
    SINYAL bagimsizligini DEGIL. Gercekci df=3 → 3/3 pozitif → p=0.1250 ANLAMLI DEGIL.

KONTROLLER (sinyalin gercek olup olmadigini ayirt eden kisim):
  1) NULL — CVD sarti KALDIRILINCA: lb10 -0.0374 (n271) · lb20 -0.0511 (n201) ·
     lb40 -0.0083 (n131). HAM 4H dip-alimi 3/3 SIFIR-NEGATIF (K3 ile tutarli).
     CVD katkisi: +0.2001R / +0.3845R / +0.2564R — 3/3 POZITIF.
  4) PERMUTASYON (2000 tekrar, ayni sayida RASTGELE alt-kume):
     lb10 p=0.0010 · lb20 p=0.0000 · lb40 p=0.0070 — 3/3 ANLAMLI.
     CVD "herhangi bir %42 alt-kume" DEGIL; tasidigi bilgi gercek.

NIHAI: GECMEDI. Sebep "edge yok" DEGIL, ON-KAYITLI CAPRAZ-COIN SARTI (d0, d2)
  karsilanamadi ve bu bir VERI isi — 12 coinin taker verisi bu oturumda proxy
  yuzunden indirilemedi. Sonuc tek coine (BTC, n=75, yilda ~26 islem) dayaniyor;
  ikinci coin (ETH, n=10) NEGATIF. Ustelik 2024 kirilimi eski reddi tekrar uretti.
  Tek coin + 85 islem + tekrar eden 2024 kirilimi CANLI PARAYA KONMAZ.
  SONRAKI ADIM VERI, KOL DEGIL: kullanici makinesinde/VPS'te
    data.binance.vision/data/futures/um/monthly/klines/{SYM}USDT/1h/{SYM}USDT-1h-{YYYY-MM}.zip
    SYM in {SOL,ETH,ADA,NEAR,BCH,ICP,BNB,XRP,DOGE,TRX,XLM,LTC}, 2023-01..2026-07
    (~550 dosya, ~17 MB) + BTC 2025-01..2025-04 deligi. Sonra bu dosya DEGISMEDEN
    tekrar kosulur; (d0)+(d2) ancak o zaman olculebilir.

Kullanim:  python3 cvd_kol.py            (tam olcum: ASAMA 0 + kol + ayri havuz + aile)
           python3 cvd_kol.py veri       (sadece ASAMA 0 veri kapisi)
           python3 cvd_kol.py kontrol    (NULL + bagimsizlik + risk + permutasyon)
"""
from __future__ import annotations
import sys, os, glob, itertools
import numpy as np, pandas as pd

sys.path.insert(0, "/home/user/Bot2")
import fast_bt
import deployed_backtest as DB
import daily_trend_test as D
from indicators import atr as atr_fn
from ayri_havuz import koltuk, kar_sabit, dd_bilesik, olcek_bul, KAYMA, SPLIT

FEE = DB.FEE
SCRATCH = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"

# ── ON-KAYITLI PARAMETRELER (izgara ortasi) ─────────────────────────────────
LB, SL_A, RR, MH = 20, 2.0, 2.0, 24
LB_G, SL_G, RR_G, MH_G = [10, 20, 40], [1.5, 2.0, 3.0], [1.5, 2.0, 2.5], [12, 24, 48]

TABAN_KOTU_AY = -32.62          # ankor: kaymali kitap en kotu ay
TABAN_ORT_R = 0.1764            # ankor: kaymali kitap ort R

COINS_LIVE = DB.DONCH + DB.SQZ + DB.BB_COINS      # 12 canli coin
# Taker (agresif alim hacmi) kaynagi olan coinler. Binance 1m klines, kolon
# taker_buy_volume. BTC: git 647d765^ (2023-01..2024-12) + disk (2025-05..2026-04).
TAKER_SRC = {
    "BTC": [f"{SCRATCH}/btc1m/BTCUSDT-1m-*.csv", "/home/user/Bot2/BTCUSDT-1m-*.csv"],
    "ETH": ["/home/user/Bot2/eth_data/ETHUSDT-1m-*.csv"],
}


# ───────────────────────── ASAMA 0: VERI ─────────────────────────
def taker_4h(coin):
    """Binance 1m -> 4H taker buy_ratio serisi (open_time kovasinda)."""
    pats = TAKER_SRC.get(coin)
    if not pats: return None
    fs = []
    for p in pats: fs += sorted(glob.glob(p))
    if not fs: return None
    fr = []
    for f in fs:
        d = pd.read_csv(f, usecols=["open_time", "volume", "taker_buy_volume"])
        fr.append(d.astype(float))
    m = (pd.concat(fr, ignore_index=True)
           .drop_duplicates(subset="open_time").sort_values("open_time"))
    m.index = pd.to_datetime(m["open_time"], unit="ms", utc=True)
    r = m.resample("4h").agg({"volume": "sum", "taker_buy_volume": "sum"})
    r = r[r["volume"] > 0]
    r["buy_ratio"] = (r["taker_buy_volume"] / r["volume"]).clip(0, 1)
    return r[["buy_ratio"]]


def veri_denetim(verbose=True):
    """Her canli coin icin taker verisi var mi, >24h bosluk kac tane?"""
    rapor = []
    for c in COINS_LIVE + ["BTC"]:
        t = taker_4h(c)
        if t is None or len(t) == 0:
            rapor.append((c, 0, None, None, -1, "taker verisi YOK")); continue
        d = t.index.to_series().diff().dt.total_seconds() / 3600.0
        bos = int((d > 24).sum())
        enb = float(d.max()) if len(d) > 1 else 0.0
        gecti = bos == 0
        rapor.append((c, len(t), t.index[0].date(), t.index[-1].date(), bos,
                      f"en buyuk bosluk {enb:.0f}h · {'GECTI' if gecti else 'ELENDI (>24h bosluk)'}"))
    if verbose:
        print(f"\n{'='*104}\n=== ASAMA 0 · VERI KAPISI (taker/agresif-alim hacmi) ===\n{'-'*104}")
        print(f"  {'coin':<6} {'4H bar':>7} {'bas':>12} {'son':>12} {'>24h bosluk':>12}  durum")
        for c, n, a, b, bos, s in rapor:
            print(f"  {c:<6} {n:>7} {str(a):>12} {str(b):>12} {bos if bos>=0 else '-':>12}  {s}")
        gecen = [r[0] for r in rapor if r[0] in COINS_LIVE and r[4] == 0]
        print(f"\n  CANLI coinlerden veri kapisini gecen: {len(gecen)}/12  {gecen}")
        print(f"  (d0) ON SART: >=6 coin →  {'GECTI' if len(gecen) >= 6 else 'GECMEDI → SONUC: OLCULEMEDI'}")
        print(f"{'='*104}")
    return rapor


# ───────────────────────── ASAMA 1: SINYAL + SIM ─────────────────────────
def bar4h(coin):
    """MEXC 4H bar (fiyat/hacim ankorun kaynagindan) + Binance taker orani (LEFT JOIN).
       delta = volume_mexc * (2*buy_ratio - 1). Eslesmeyen bar sinyal uretmez."""
    m = fast_bt.load(coin, source="local")
    d = fast_bt.resample(m, "4h")
    t = taker_4h(coin)
    if t is None: return None
    d = d.join(t, how="left")                       # LEFT JOIN, ileri kaydirma YOK
    d["gecerli"] = d["buy_ratio"].notna().values
    br = d["buy_ratio"].fillna(0.5).values          # eksik bar: delta=0, ama gecerli=False
    d["delta"] = d["volume"].values * (2.0 * br - 1.0)
    d.loc[~d["gecerli"], "delta"] = 0.0
    d["cvd"] = d["delta"].cumsum()
    return d


def sinyal(d, lb):
    """LONG-only: yeni lb-bar dibi + onceki dipten beri net taker ALIMI.
       Pencerede EKSIK taker bari varsa sinyal URETILMEZ."""
    lo = d["low"].values; cvd = d["cvd"].values; ok = d["gecerli"].values
    out = []
    for i in range(lb + 15, len(lo)):
        w = lo[i - lb:i + 1]
        if lo[i] > w.min(): continue                # yeni dip degil
        if not ok[i - lb:i + 1].all(): continue     # pencerede taker bosluğu → atla
        p = i - lb + int(np.argmin(lo[i - lb:i]))   # onceki dip (mevcut bar HARIC)
        if cvd[i] > cvd[p]:
            out.append(i)
    return out


def sim(d, idx, sl_a, rr, mh, coin):
    """Giris sinyal barinin KAPANISI, cikis taramasi i+1'den. Coin basina tek pozisyon."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    at = atr_fn(d["high"], d["low"], d["close"], 14).values
    ix = d.index; n = len(cl); out = []; occ = -1
    for i in idx:
        if i <= occ or i >= n - 1: continue
        a = at[i]
        if not np.isfinite(a) or a <= 0: continue
        e = cl[i]; sld = sl_a * a; slp = e - sld; tp = e + rr * sld; ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if lo[j] <= slp: ep = slp; break
            if hi[j] >= tp: ep = tp; break
        if ep is None: j = min(i + mh, n - 1); ep = cl[j]
        R = (ep - e) / sld - 2 * FEE * e / sld
        out.append((ix[i].value, ix[j], R, sld / e, "cvd", coin)); occ = j
    return out


def kol_uret(dfs, lb, sl_a, rr, mh):
    t = []
    for c, d in dfs.items(): t += sim(d, sinyal(d, lb), sl_a, rr, mh, c)
    return t


# ───────────────────────── raporlama ─────────────────────────
def netR(tr):
    if not tr: return np.array([])
    R = np.array([t[2] for t in tr]); sp = np.array([t[3] for t in tr])
    return R - KAYMA / sp


def ozet_R(tr, etiket):
    if not tr: print(f"  {etiket:<38s} n=0"); return
    Rn = netR(tr); Rh = np.array([t[2] for t in tr])
    sp = np.array([t[3] for t in tr])
    z = Rn.mean() / Rn.std(ddof=1) * np.sqrt(len(Rn)) if len(Rn) > 1 and Rn.std(ddof=1) > 0 else 0.0
    print(f"  {etiket:<38s} n={len(Rn):<5d} stop%={np.median(sp)*100:5.2f} "
          f"kayma={np.mean(KAYMA/sp):.3f}R  hamR={Rh.mean():+.4f}  KAYMALI R={Rn.mean():+.4f} z={z:+.2f}")


def tr_te(tr):
    TR = [t for t in tr if t[0] < SPLIT.value and pd.Timestamp(t[1]) < SPLIT]
    TE = [t for t in tr if t[0] >= SPLIT.value]
    return TR, TE


def main():
    # ── ASAMA 0 ──
    rapor = veri_denetim()
    gecen = [r[0] for r in rapor if r[0] in COINS_LIVE and r[4] == 0]
    d0 = len(gecen) >= 6

    # ── TABAN DOGRULAMA (zorunlu) ──
    kitap = D.base_trades("local")
    A = koltuk(kitap, 7)
    if len(A) != 1579:
        sys.exit(f"⛔ taban {len(A)} islem, 1579 degil — KIYAS GECERSIZ, durduruldu.")
    dd_A = dd_bilesik(A); kar_A, ay_A = kar_sabit(A)
    kar_A_te, _ = kar_sabit([t for t in A if t[0] >= SPLIT.value])
    RA = netR([(t[0], t[1], t[2], t[3]) for t in A])
    print(f"\n=== TABAN DOGRULANDI: {len(A)} islem ===")
    print(f"  kaymali kitap: ${kar_A:+.2f} · ort R {RA.mean():+.4f} · bilesik maxDD %{dd_A:.2f} "
          f"· en kotu ay %{ay_A.min():.2f} · TEST ${kar_A_te:+.2f}")

    if not d0:
        print(f"\n{'!'*104}")
        print(f"  (d0) CAPRAZ-COIN ON SARTI KARSILANMADI: {len(gecen)}/12 canli coin.")
        print(f"  ON-KAYITLI HUKUM: 'Gecmezse SONUC = olculemedi, kol kurulmaz.'")
        print(f"  Asagidaki BTC olcumu KARAR DEGIL, sonraki ajan icin KAYIT'tir.")
        print(f"{'!'*104}")

    # ── olculebilir coinler ──
    # Kapiyi gecen (bosluksuz) coin varsa KARAR onlarla verilir. Yoksa: taker
    # verisi VAR ama bosluklu coinler "KAYIT" olarak olculur — karar DEGIL.
    # Bosluk tehlikesi (cumsum farkini delik uzerinden almak) sinyal() icindeki
    # ok[i-lb:i+1].all() korumasiyla YAPISAL olarak kapatildi: pencerede tek bir
    # eksik taker bari varsa o bar sinyal URETMEZ.
    gecen_k = [r[0] for r in rapor if r[4] == 0]
    kayit_k = [r[0] for r in rapor if r[4] is not None and r[4] > 0]
    olcu, kayit_modu = (gecen_k, False) if gecen_k else (kayit_k, True)
    if not olcu:
        print("\n  Hicbir coinde taker verisi yok — kol HIC kosulamaz. SONUC: OLCULEMEDI.")
        return
    if kayit_modu:
        print(f"\n  ⚠ KAYIT MODU: bosluksuz coin YOK. On-kayitli kural (c) {olcu} coin(ler)ini"
              f" ELER.\n    Asagidaki sayilar KARAR DEGIL, sonraki ajan icin olculmus KAYITTIR.")
    dfs = {}
    for c in olcu:
        d = bar4h(c)
        if d is not None and d["gecerli"].sum() > 200: dfs[c] = d
    print(f"\n  olculebilen coin: {list(dfs)} "
          f"(4H bar: {{{', '.join(f'{c}:{int(d.gecerli.sum())}' for c, d in dfs.items())}}})")

    # ── IZGARA ORTASI HUCRE ──
    kol = kol_uret(dfs, LB, SL_A, RR, MH)
    print(f"\n{'='*104}\n=== IZGARA ORTASI: lb={LB} SL={SL_A}*ATR14 RR={RR} mh={MH} bar (LONG-only) ===\n{'-'*104}")
    ozet_R(kol, "KOL TEK BASINA (tum donem)")
    print(f"  → kitap kaymali ort R {TABAN_ORT_R:+.4f} ile kiyas: "
          f"{'GECIYOR' if len(kol) and netR(kol).mean() > TABAN_ORT_R else 'GECMIYOR'}")
    TR, TE = tr_te(kol)
    ozet_R(TR, "  TRAIN (giris+cikis < 2025-01-01)")
    ozet_R(TE, "  TEST  (giris >= 2025-01-01)")
    for c in dfs:
        ozet_R([t for t in kol if t[5] == c], f"  coin {c}")
    print(f"\n  yil-yil (kaymali):")
    for y in sorted({pd.Timestamp(t[0]).year for t in kol}):
        yt = [t for t in kol if pd.Timestamp(t[0]).year == y]
        ozet_R(yt, f"    {y}")

    # (d2) coin-disi tekrar
    poz = [c for c in dfs if len([t for t in kol if t[5] == c]) and
           netR([t for t in kol if t[5] == c]).mean() > 0]
    print(f"\n  (d2) coin-disi tekrar: {len(poz)}/{len(dfs)} coinde kaymali ort R > 0 "
          f"→ {'GECTI' if len(dfs) >= 2 and len(poz)/len(dfs) >= 0.60 else 'GECMEDI (tek coin GECERLI SAYILMAZ)'}")

    # ── AYRI HAVUZ (a)(b)(c) ──
    print(f"\n{'='*104}\n=== AYRI HAVUZ · RISK EsITLENMIS (hedef bilesik maxDD %{dd_A:.2f}) ===\n{'-'*104}")
    print(f"  {'S koltuk':<12} {'kol n':>6} {'olcek':>7} {'TUM $':>9} {'D$':>8} {'TEST $':>9} "
          f"{'DTEST':>8} {'kotu ay':>8}  BAR(a,b,c)")
    for S in (1, 2, 3):
        C = A + koltuk(kol, S)
        nk = sum(1 for t in C if t[4] == "cvd")
        nkitap = len(C) - nk
        o = olcek_bul(C, dd_A)
        k, ay = kar_sabit(C, o)
        kte, _ = kar_sabit([t for t in C if t[0] >= SPLIT.value], o)
        dd, dte = k - kar_A, kte - kar_A_te
        gec = dd >= 36 and dte > 0 and ay.min() >= ay_A.min()
        print(f"  {'S='+str(S):<12} {nk:>6} {o:>7.3f} {k:>9.2f} {dd:>+8.2f} {kte:>9.2f} "
              f"{dte:>+8.2f} {ay.min():>+8.2f}  {'GECTI' if gec else 'GECMEDI'}"
              f"   [kitap {nkitap}/1579 korundu]")

    # ── AILE TESTI (81 hucre) ──
    print(f"\n{'='*104}\n=== AILE TESTI · 81 hucre (lb x SL x RR x mh) — SECIM ICIN DEGIL ===\n{'-'*104}")
    sig = {lb: {c: sinyal(d, lb) for c, d in dfs.items()} for lb in LB_G}
    hep, te_ort, tr_ort, ns = [], [], [], []
    for lb, sl_a, rr, mh in itertools.product(LB_G, SL_G, RR_G, MH_G):
        t = []
        for c, d in dfs.items(): t += sim(d, sig[lb][c], sl_a, rr, mh, c)
        if not t: continue
        a, b = tr_te(t)
        hep.append(netR(t).mean()); ns.append(len(t))
        te_ort.append(netR(b).mean() if b else np.nan)
        tr_ort.append(netR(a).mean() if a else np.nan)
    hep = np.array(hep); te = np.array(te_ort, dtype=float); tra = np.array(tr_ort, dtype=float)
    tev = te[~np.isnan(te)]
    from math import comb
    df_eff = 15
    k = int(round((tev > 0).mean() * df_eff))
    p = sum(comb(df_eff, j) for j in range(k, df_eff + 1)) / 2 ** df_eff
    print(f"  hucre sayisi {len(hep)} · ort islem/hucre {np.mean(ns):.0f}")
    print(f"  TUM DONEM ort R : medyan {np.median(hep):+.4f} · pozitif %{(hep>0).mean()*100:.1f} "
          f"· aralik [{hep.min():+.4f}, {hep.max():+.4f}]")
    print(f"  TRAIN     ort R : medyan {np.nanmedian(tra):+.4f} · pozitif %{(tra[~np.isnan(tra)]>0).mean()*100:.1f}")
    print(f"  TEST      ort R : medyan {np.median(tev):+.4f} · pozitif %{(tev>0).mean()*100:.1f} "
          f"· aralik [{tev.min():+.4f}, {tev.max():+.4f}]")
    print(f"  (d1) BAR: TEST medyani > 0 VE pozitif oran >= %70 → "
          f"{'GECTI' if np.median(tev) > 0 and (tev>0).mean() >= 0.70 else 'GECMEDI'}")
    print(f"       binom (etkin df={df_eff}, {k}/{df_eff} pozitif): p={p:.4f} "
          f"{'(anlamli)' if p < 0.05 else '(sansa gore ANLAMLI DEGIL)'}")
    mtr, mte = np.nanmedian(tra), np.median(tev)
    if mtr > 0 and mte > 0:
        print(f"  TRAIN/TEST orani: {mtr/mte:.2f}x "
              f"{'→ YURUYEN-ILERI BOZULMA (>3x)' if mtr/mte > 3 else ''}")
    else:
        print(f"  TRAIN/TEST orani: medyanlardan biri <=0 (TRAIN {mtr:+.4f}, TEST {mte:+.4f})")
    print(f"{'='*104}\n")


# ───────────────────────── KONTROL / NULL ─────────────────────────
def ham_dip(d, lb):
    """CVD SARTI YOK: sadece yeni lb-bar dibi -> LONG. Kolun NULL'u.
       CVD filtresi gercekten bir sey ekliyor mu, yoksa 'BTC 4H dibi al' mi?"""
    lo = d["low"].values; ok = d["gecerli"].values
    return [i for i in range(lb + 15, len(lo))
            if lo[i] <= lo[i - lb:i + 1].min() and ok[i - lb:i + 1].all()]


def kontrol():
    """NULL kontrolu + bagimsizlik duzeltmesi + risk denetimi."""
    rapor = veri_denetim(verbose=False)
    olcu = [r[0] for r in rapor if r[4] is not None and r[4] > 0] or \
           [r[0] for r in rapor if r[4] == 0]
    dfs = {}
    for c in olcu:
        d = bar4h(c)
        if d is not None and d["gecerli"].sum() > 200: dfs[c] = d

    kitap = D.base_trades("local"); A = koltuk(kitap, 7)
    if len(A) != 1579: sys.exit(f"⛔ taban {len(A)} — KIYAS GECERSIZ.")
    dd_A = dd_bilesik(A)

    print(f"\n{'='*104}\n=== KONTROL 1 · NULL: CVD filtresi bir sey EKLIYOR mu? ===")
    print(f"  (ayni barlar, ayni cikis kurali; tek fark CVD sarti)\n{'-'*104}")
    for lb in LB_G:
        ham = []; cvd = []
        for c, d in dfs.items():
            ham += sim(d, ham_dip(d, lb), SL_A, RR, MH, c)
            cvd += sim(d, sinyal(d, lb), SL_A, RR, MH, c)
        ozet_R(ham, f"lb={lb} HAM yeni-dip LONG (CVD YOK)")
        ozet_R(cvd, f"lb={lb} CVD-filtreli LONG")
        if ham and cvd:
            print(f"      → CVD katkisi: {netR(cvd).mean() - netR(ham).mean():+.4f}R "
                  f"(gecen sinyal %{len(cvd)/len(ham)*100:.0f})")

    print(f"\n{'='*104}\n=== KONTROL 2 · AILE BAGIMSIZLIGI (81 hucre kac BAGIMSIZ testtir?) ===\n{'-'*104}")
    print(f"  81 hucre = 3 lb x 27 cikis kurali. AYNI lb AYNI giris setini kullanir:")
    for lb in LB_G:
        n = sum(len(sinyal(d, lb)) for d in dfs.values())
        print(f"    lb={lb}: {n} ortak giris sinyali → 27 hucre bunlari paylasiyor")
    print(f"  Yani aile testi CIKIS saglamligini olcer, SINYAL bagimsizligini DEGIL.")
    from math import comb
    # gercek pozitif orani (TEST) yeniden olculur, sonra iki df varsayimiyla binom
    sig = {lb: {c: sinyal(d, lb) for c, d in dfs.items()} for lb in LB_G}
    te_ort = []
    for lb, sl_a, rr, mh in itertools.product(LB_G, SL_G, RR_G, MH_G):
        t = []
        for c, d in dfs.items(): t += sim(d, sig[lb][c], sl_a, rr, mh, c)
        _, b = tr_te(t)
        if b: te_ort.append(netR(b).mean())
    frak = float(np.mean(np.array(te_ort) > 0))
    print(f"  TEST'te pozitif hucre orani: %{frak*100:.1f} ({len(te_ort)} hucre)")
    for df_eff, ad in [(15, "brief varsayimi"), (3, "gercekci: lb basina 1 bagimsiz sinyal seti")]:
        k = int(round(frak * df_eff))
        p_ = sum(comb(df_eff, j) for j in range(k, df_eff + 1)) / 2 ** df_eff
        print(f"    etkin df={df_eff:>2} ({ad}): {k}/{df_eff} pozitif → p={p_:.4f} "
              f"{'ANLAMLI' if p_ < 0.05 else 'ANLAMLI DEGIL'}")

    print(f"\n{'='*104}\n=== KONTROL 4 · PERMUTASYON: CVD OZEL mi, herhangi bir %42 alt-kume mi? ===")
    print(f"  NULL: ayni HAM yeni-dip sinyallerinden CVD ile ayni SAYIDA sinyal RASTGELE secilir.\n{'-'*104}")
    rng = np.random.default_rng(20260913)
    for lb in LB_G:
        ger = []; ham_ix = {}
        for c, d in dfs.items():
            ham_ix[c] = ham_dip(d, lb)
            ger += sim(d, sinyal(d, lb), SL_A, RR, MH, c)
        if not ger: continue
        g = netR(ger).mean()
        hedef = {c: len(sinyal(d, lb)) for c, d in dfs.items()}
        null = []
        for _ in range(2000):
            t = []
            for c, d in dfs.items():
                k = min(hedef[c], len(ham_ix[c]))
                if k == 0: continue
                pick = sorted(rng.choice(len(ham_ix[c]), size=k, replace=False))
                t += sim(d, [ham_ix[c][j] for j in pick], SL_A, RR, MH, c)
            if t: null.append(netR(t).mean())
        null = np.array(null)
        pct = float((null >= g).mean())
        print(f"  lb={lb}: GERCEK CVD {g:+.4f}R · NULL ort {null.mean():+.4f} sd {null.std():.4f} "
              f"· p={pct:.4f} {'ANLAMLI' if pct < 0.05 else 'ANLAMLI DEGIL'}")

    print(f"\n{'='*104}\n=== KONTROL 3 · RISK: ayri havuz maxDD'yi gercekten yukseltmiyor mu? ===\n{'-'*104}")
    kol = kol_uret(dfs, LB, SL_A, RR, MH)
    print(f"  A) yalniz kitap        : bilesik maxDD %{dd_A:.2f}")
    for S in (1, 2, 3):
        C = A + koltuk(kol, S)
        print(f"  C) kitap + kol (S={S})  : bilesik maxDD %{dd_bilesik(C, 1.0):.2f} "
              f"(olcek 1.0) → {'kol maxDD EKLEMIYOR' if dd_bilesik(C,1.0) <= dd_A else 'kol maxDD EKLIYOR'}")
    print(f"  NOT: olcek_bul 1.000 dondurduyse Delta$ HIC risk-cezasi GORMEMIS demektir;")
    print(f"       kol o kadar kucuk ki kitabin DD'sine dokunmuyor. Bu 'bedava kar' DEGIL,")
    print(f"       'olcum gorunmez kadar kucuk' anlamina da gelir (n=85, ~26 islem/yil).")
    print(f"{'='*104}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "veri":
        veri_denetim()
    elif len(sys.argv) > 1 and sys.argv[1] == "kontrol":
        kontrol()
    else:
        main()
