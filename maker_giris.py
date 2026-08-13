"""
maker_giris.py — MAKER GİRİŞ + PİYASA YEDEĞİ: kaymayı geri kazanabilir miyiz?

NEDEN BU:
  ankor_denetim.py bugün tek başına en büyük sızıntıyı ölçtü: GİRİŞ KAYMASI 13.4bp
  ankorun $1476'sından $251 götürüyor (A0→A1). 3.6 yılda $251 = yılda ~$70.
  Bugün denenen 14 filtrenin HİÇBİRİ bu büyüklüğe yaklaşamadı. Ve kayma bir
  "sinyal kalitesi" sorunu değil — SAF YÜRÜTME maliyeti. Sinyali hiç bozmadan
  azaltılabilirse, bulunması gereken bir "edge" yok; sadece daha az ödemek var.

KODDA ZATEN VAR OLAN ŞEY:
  exchange.place_limit_order() post-only maker limit + piyasa yedeği ile hazır.
  MEXC vadelide maker ücreti %0, taker %0.01 (exchange.py:91-92). BB/MR kolu bu
  yolu CANLIDA KULLANIYOR. donchian/squeeze ise main.py'de force_market=True ile
  geliyor ve limit yolunu HİÇ görmüyor.

⚠️ BU DAHA ÖNCE DENENDİ VE GERİ ALINDI (2026-07-16 denetimi, main.py:640-647):
  "the former limit+no-fallback path adversely selected: runaway (strongest)
   releases never retraced and were skipped, fading ones filled."
  Yani: limit dolmazsa İŞLEM ATLANIYORDU. Momentum kolunda en güçlü kırılımlar
  hiç geri dönmez → tam da kazandıran işlemler kaçar, sönenler dolar. Haklı olarak
  geri alınmış.

  AMA geri alınan şey "maker giriş" değil, "YEDEKSİZ maker giriş"ti. Koddaki
  ayrım şu satır: execution.py:611
      is_structure_based = getattr(signal, "sl_price", 0.0) > 0
  donchian/squeeze sl_price'ı DOLDURUYOR (main.py:632,736) → bu bayrak True oluyor
  → fallback_market=False → dolmazsa ATLA. Oysa donchian/squeeze SL'i yapıya değil
  KAPANIŞA çapalıyor; piyasa yedeği R/R'yi bozmaz. Yani bayrak yanlış kolu yakalıyor.

  BU ARAÇ ŞUNU ÖLÇÜYOR: maker limit + 45sn sonra PİYASA YEDEĞİ.
  Bu kurguda HİÇBİR İŞLEM KAÇMAZ. Değişen tek şey ÖDENEN FİYAT:
    • limit dolarsa  → giriş tam sinyal kapanışında, kayma 0, giriş ücreti 0
    • dolmazsa       → 45sn sonra piyasa: 13.4bp kayma + bu 45sn'lik ek sürüklenme

  Dolayısıyla ters-seçim (adverse selection) İŞLEM SEÇİMİNİ değil yalnız FİYATI
  etkiler. Kritik soru tek: dolum oranı p, başabaş oranın üstünde mi?

BAŞABAŞ (kapalı form):
  kazanç/dolum = 13.4bp kayma + 1bp taker ücreti = 14.4bp
  kayıp/dolmama = δ bp (dolmama koşuluyla 45sn'lik aleyhe sürüklenme)
  p* = δ / (14.4 + δ)      → δ=5bp ise p*=%26 · δ=10bp ise %41 · δ=20bp ise %58

ÖLÇÜM (kolay yanılınan yer): p'yi 1 SAATLİK veriden ölçemem. Bu bir mikroyapı
sorusu. İki yol var:
  local → yerel 1 DAKİKALIK CSV'ler (BTC 12 ay, ETH 5 ay). ETH canlı donchian
          listesinde VAR. BTC yok — venue de Binance. VEKİL ölçüm, etiketli.
  mexc  → VPS'te, GERÇEK 11 coin ve GERÇEK borsada, her sinyalin etrafından
          hedefli 1dk penceresi çekilir (sürekli veri değil, ~1600 küçük istek).
          KESİN ölçüm budur.

ÖN-KAYIT (sonuca bakmadan): karar penceresi W=1dk (koddaki 45sn varsayılanına en
yakın satır, execution.py:623 — o değer bu araştırmadan ÖNCE seçilmişti). Diğer
pencereler yalnız BİLGİ için basılır; en iyisini seçmek optimizasyon olurdu.

BAR (ön-kayıtlı, gevşetilmez):  Δ$ > +28 · hiçbir yıl −%10'dan kötü değil ·
maxDD +2 puandan fazla kötüleşmiyor · EN KÖTÜ AY KÖTÜLEŞMİYOR.

DOĞRULAMA: maliyetsiz kol (cost=0, tam ücret) ankoru BİREBİR üretmeli
(1579 işlem / $1420.66, CAP=1.25). Üretmezse hiçbir satır okunmaz.

Kullanım:  py maker_giris.py local        # PC — vekil 1dk ölçümü
           py maker_giris.py mexc         # VPS — gerçek coin/borsa 1dk ölçümü
"""
import glob
import heapq
import os
import sys

import numpy as np
import pandas as pd

import fast_bt
import deployed_backtest as A
from indicators import atr as atr_fn, adx as adx_fn
from strategies.donchian import DonchianStrategy
from strategies.squeeze import SqueezeStrategy

CAP = 1.50                # canlı .env POSITION_CAP_FRACTION
KAYMA_BP = 13.4           # ölçülmüş taker giriş kayması (live_verify.py:44)
FONLAMA_YIL = 0.022       # ölçülmüş fonlama maliyeti
TAKER_BP = 1.0            # A.FEE = 0.0001 = 1bp (exchange.py:91)
PENCERE = [1, 2, 3, 5, 10, 15, 30, 60]     # dakika
KARAR_W = 1               # ÖN-KAYITLI karar penceresi (45sn'ye en yakın)
BAR_DOLAR = 28.0          # ön-kayıtlı eşik
DERINLIK_BP = 0.0         # varsayılan: fiyat seviyeyi GEÇSİN (kesin eşitsizlik)
# Dolum kuralı bandı: fiyatın limiti kaç bp GEÇMESİ şart koşulsun.
#   0  = seviyeyi geçsin (o fiyattaki kuyruk süpürüldü → biz de dolduk)
#   5  = yarım spread kadar geçsin
#  10  = tam bir spread kadar geçsin (EN KÖTÜMSER — karar bu satırdan verilir)
DERINLIKLER = [0.0, 2.0, 5.0, 10.0]


# ══════════════════════════════════════════════════════════════════════════════
# 1) SİNYAL ÇIKARIMI — maliyetten BAĞIMSIZ. Bir kez çalışır, tüm kollar kullanır.
# ══════════════════════════════════════════════════════════════════════════════
def sinyal_cek(sleeve, m):
    """A.gen'in sinyal kapılarının BİREBİR aynısı, ama occ UYGULANMAZ ve giriş
    fiyatı hesaplanmaz. occ çıkış barına bağlı, çıkış barı da maliyete bağlı —
    o yüzden occ maliyet döngüsünün İÇİNDE uygulanır (A.gen ile aynı sırada).

    Döner: (d, sinyaller) — sinyaller: [(i, d_, atr)], d = yeniden örneklenmiş df.
    A.gen'de occ kontrolü MTF/ADX kapılarından ÖNCE ama occ yalnız işlem ALININCA
    güncelleniyor; dolayısıyla 'kapıları geçen tüm sinyaller' + sonradan occ
    uygulaması AYNI kümeyi verir (kanıt: kontrol satırı ankoru birebir üretiyor)."""
    tf, win, sl_a, rr, mh = A.CFG[sleeve]
    d = fast_bt.resample(m, tf)
    atr_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    adx_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    _dc = d["close"].resample("1D").last().dropna()
    _dprev = _dc.ewm(span=20, adjust=False).mean().shift(1).reindex(d.index.normalize()).values
    up = d["close"].values > _dprev
    s = (DonchianStrategy(channel=40, rr=2.0, sl_atr=2.0, ema_trend=200, buffer_atr=0.0)
         if sleeve == "donchian" else
         SqueezeStrategy(kc_mult=1.5, min_squeeze_bars=5, sl_atr=2.0, rr=2.5, mtf_filter=True))
    n = len(d)
    sig = []
    for i in range(260, n - 1):
        a = atr_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if sleeve == "squeeze":
            xv = adx_ser[i] if np.isfinite(adx_ser[i]) else 20.0
            if xv <= 20.0:
                continue
        d_ = s.analyze(d.iloc[max(0, i - win):i + 1], float(a)).direction
        if d_ == 0:
            continue
        if sleeve == "donchian":
            dup = bool(up[i]) if not (isinstance(up[i], float) and np.isnan(up[i])) else True
            if not ((d_ == 1 and dup) or (d_ == -1 and not dup)):
                continue
        sig.append((i, d_, float(a)))
    return d, sig


def sinyal_cek_bb(m):
    """A.gen_bb'nin sinyal kapıları — occ maliyet döngüsünde."""
    from indicators import bollinger_bands
    from strategies.mean_reversion import MeanReversionStrategy
    from config import load_config
    s = MeanReversionStrategy(load_config().strategy)
    d = fast_bt.resample(m, A.BB_TF)
    cl = d["close"].values
    idx = d.index
    n = len(cl)
    up_b, _mid, lo_b = bollinger_bands(d["close"], 20, 2.0)
    outside = (cl < lo_b.values) | (cl > up_b.values)
    volma = d["volume"].rolling(20).mean().values
    volok = ~(np.isfinite(volma) & (d["volume"].values < volma))
    sig = []
    for i in np.where(outside & volok)[0]:
        i = int(i)
        if i < 260 or i >= n - 1:
            continue
        if idx[i].weekday() < 5:
            continue
        sub = d.iloc[max(0, i - 119):i + 1]
        av = atr_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if not np.isfinite(av) or av <= 0:
            continue
        adxr = adx_fn(sub["high"], sub["low"], sub["close"], 14).iloc[-1]
        if (float(adxr) if np.isfinite(adxr) else 20.0) >= A.BB_ADX_MAX:
            continue
        d_ = s.analyze(sub).direction
        if d_ == 0:
            continue
        sig.append((i, d_, float(av)))
    return d, sig


# ══════════════════════════════════════════════════════════════════════════════
# 2) MALİYETLİ SİMÜLASYON — sinyal kümesi sabit, sadece ÖDENEN FİYAT değişir
# ══════════════════════════════════════════════════════════════════════════════
def _R0(d, sig, sl_a, rr, mh):
    """Her sinyalin MALİYETSİZ R'si (occ'tan bağımsız, sinyal başına).
    Ters-seçimli kol bunu 'bu işlem kazanacak mıydı' anahtarı olarak kullanır."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    n = len(cl); out = {}
    for i, d_, a in sig:
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
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        out[i] = d_ * (ep - e) / sld
    return out


def sim_maliyet(d, sig, sl_a, rr, mh, kayma_bp, ucret_carp,
                kayma_kayb=None, ucret_kayb=None, r0=None):
    """kayma_bp = beklenen giriş kayması (bp, HER ZAMAN aleyhe)
       ucret_carp = giriş ücreti çarpanı (1.0 = tam taker, 0.0 = tam maker)
       Çıkış ücreti daima 1× taker (canlıda çıkış piyasa emri).
       kayma_bp=0, ucret_carp=1.0 → A.gen ile BİREBİR.

       kayma_kayb/ucret_kayb verilirse TERS-SEÇİMLİ kol: kazanacak işlemlere
       (r0>0) birinci maliyet, kaybedecek olanlara ikinci maliyet uygulanır.
       Ölçüm şunu gösterdi: limit KAZANAN işlemlerde çok daha AZ doluyor (fiyat
       kaçtığı için). Düz ortalama maliyet bu asimetriyi gizler — bu kol onu
       açığa çıkarır. 2026-07-16'da geri alınan sürümün ölüm sebebi tam buydu."""
    hi = d["high"].values; lo = d["low"].values; cl = d["close"].values
    idx = d.index; n = len(cl)
    out = []; occ = -1
    for i, d_, a in sig:
        if i <= occ:
            continue
        kb, uc = kayma_bp, ucret_carp
        if kayma_kayb is not None and r0 is not None and r0.get(i, 1.0) <= 0:
            kb, uc = kayma_kayb, ucret_kayb
        e = cl[i]
        if kb:
            e = e * (1 + d_ * kb / 10000.0)
        sld = sl_a * a
        slp = e - d_ * sld; tp = e + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - e) / sld - (uc + 1.0) * A.FEE * e / sld
        gun = (idx[j].value - idx[i].value) / 1e9 / 86400
        out.append((idx[i].value, idx[j].value, R, sld / e, gun))
        occ = j
    return out


def koltuk(ham):
    ev = sorted(ham, key=lambda z: z[0])
    oh = []; ctr = 0; al = []
    for e, x, R, slp, gun in ev:
        while oh and oh[0][0] <= e:
            heapq.heappop(oh)
        if len(oh) < A.MAXPOS:
            ctr += 1; heapq.heappush(oh, (x, ctr)); al.append((x, R, slp, gun))
    return al


def olc(al, cap, fonlama=False):
    r = np.array([a[1] for a in al]); sp = np.array([a[2] for a in al])
    gun = np.array([a[3] for a in al])
    eff = np.minimum(A.RISKF, cap * sp)
    pnl = r * eff * A.BAL0
    if fonlama:
        nom = np.minimum(A.RISKF / sp, cap) * A.BAL0
        pnl -= nom * FONLAMA_YIL * gun / 365.0
    ex = [pd.Timestamp(a[0]) for a in al]
    eq = A.BAL0 + np.cumsum(pnl)
    mon = pd.Series(pnl).groupby([x.to_period("M") for x in ex]).sum() / A.BAL0 * 100
    yil = pd.Series(pnl).groupby([x.year for x in ex]).sum() / A.BAL0 * 100
    kaz = pnl[pnl > 0].sum(); kay = -pnl[pnl < 0].sum()
    return dict(n=len(al), tot=float(pnl.sum()),
                pf=float(kaz / kay) if kay > 0 else float("inf"),
                wr=float((r > 0).mean() * 100), ortR=float(r.mean()),
                dd=float(A.maxdd(np.concatenate([[A.BAL0], eq]))),
                worst=float(mon.min()), yil=yil, pnl=pnl, ex=ex)


# ══════════════════════════════════════════════════════════════════════════════
# 3) DOLUM ÖLÇÜMÜ — 1 DAKİKALIK veri. Asıl bilinmeyen bu.
# ══════════════════════════════════════════════════════════════════════════════
def _csv_1m(paths):
    """Binance kline CSV → 1dk OHLCV (fast_bt.load'ın binance_csv yolu ile aynı)."""
    fr = []
    for f in paths:
        x = pd.read_csv(f)
        x.columns = ["ts", "o", "h", "l", "c", "v", "ct", "qv", "n", "a", "b", "g"][:x.shape[1]]
        fr.append(x[["ts", "o", "h", "l", "c", "v"]].astype(float))
    m = pd.concat(fr).drop_duplicates("ts").sort_values("ts")
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    return (m.rename(columns={"o": "open", "h": "high", "l": "low",
                              "c": "close", "v": "volume"}).drop(columns=["ts"]))


def yerel_1m():
    """Yerel 1dk kaynakları. ETH canlı donchian listesinde VAR; BTC yok ve venue
    Binance — bu bir VEKİL ölçümdür, etiketi her satırda taşınır."""
    src = {}
    b = sorted(glob.glob("BTCUSDT-1m-*.csv"))
    if b:
        src["BTC"] = _csv_1m(b)
    e = sorted(glob.glob(os.path.join("eth_data", "ETHUSDT-1m-*.csv")))
    if e:
        src["ETH"] = _csv_1m(e)
    return src


def _tf_delta(tf):
    return pd.Timedelta(hours=4) if tf == "4h" else pd.Timedelta(hours=1)


def dolum_olc(d1m, d_tf, sig, tf, sl_a, rr, mh, pencereler, derinlik_bp=DERINLIK_BP):
    """Her sinyal için: bar KAPANDIKTAN sonra W dakika içinde post-only limit
    (fiyat = sinyal kapanışı) dolar mı?

    ⚠ DOLUM KURALI EN KOLAY YANILINAN YER — ilk sürümde 'low <= L ise doldu'
    yazmıştım ve %98.4 çıktı. O sayı GERÇEK DEĞİL, kuralın kendisi neredeyse
    totolojiydi: 1dk barının açılışı ≈ L olduğu için low<=L hemen daima doğru.
    Fiziksel gerçek: limitimiz L'de KUYRUĞUN ARKASINDA. Bize gelmesi için
    fiyatın L'yi GEÇMESİ (o seviyedeki tüm emirleri süpürmesi) gerekir.
    Ayrıca post-only, emir anında karşı tarafı keserse REDDEDİLİR — o durumda
    kod anında piyasaya düşer (exchange.py:845) yani BUGÜNKÜ maliyet, ek zarar yok.

    Bu yüzden tek sayı değil BANT üretilir: derinlik_bp = fiyatın seviyeyi kaç bp
    GEÇMESİ şart koşulur. 0 = sadece geçsin (kesin eşitsizlik) · 10 = tam bir
    spread kadar geçsin (en kötümser). Karar KÖTÜMSER satırdan verilir.

    Ayrıca her sinyalin NİHAİ R'si hesaplanır → ters-seçim (dolum × sonuç) ölçülür.
    """
    hi = d_tf["high"].values; lo = d_tf["low"].values; cl = d_tf["close"].values
    idx = d_tf.index; n = len(cl)
    dt = _tf_delta(tf)
    l1 = d1m["low"].values; h1 = d1m["high"].values; c1 = d1m["close"].values
    t1 = d1m.index
    kayit = []
    for i, d_, a in sig:
        kapanis = idx[i] + dt                     # barın GERÇEKTEN kapandığı an
        p0 = t1.searchsorted(kapanis, side="left")
        if p0 >= len(t1):
            continue
        # 1dk verisi bu anı kapsıyor mu? (boşluk varsa sinyali ATLA — uydurma yok)
        if abs((t1[p0] - kapanis).total_seconds()) > 90:
            continue
        L = cl[i]
        # nihai R (maliyetsiz — yalnız sonucun İŞARETİ için)
        sld = sl_a * a
        slp = L - d_ * sld; tp = L + d_ * rr * sld
        ep = None; j = i
        for j in range(i + 1, min(i + 1 + mh, n)):
            if d_ == 1:
                if lo[j] <= slp: ep = slp; break
                if hi[j] >= tp: ep = tp; break
            else:
                if hi[j] >= slp: ep = slp; break
                if lo[j] <= tp: ep = tp; break
        if ep is None:
            j = min(i + mh, n - 1); ep = cl[j]
        R = d_ * (ep - L) / sld
        satir = {"t": kapanis, "d": d_, "R": R}
        # limitin GEÇİLMESİ gereken fiyat: long'da L'nin derinlik_bp ALTI
        hedef = L * (1 - d_ * derinlik_bp / 10000.0)
        for W in pencereler:
            p1 = min(p0 + W, len(t1))
            if p1 <= p0:
                satir[W] = None
                continue
            if d_ == 1:
                doldu = bool(l1[p0:p1].min() < hedef)      # KESİN geçiş
            else:
                doldu = bool(h1[p0:p1].max() > hedef)
            surukle = d_ * (c1[p1 - 1] - L) / L * 10000.0   # +: aleyhe
            satir[W] = (doldu, float(surukle))
        kayit.append(satir)
    return kayit


def dolum_ozet(kayit, W):
    """Bir pencere için: dolum oranı, dolmayanın aleyhe sürüklenmesi, net bp."""
    v = [k[W] for k in kayit if k.get(W) is not None]
    if not v:
        return None
    doldu = np.array([x[0] for x in v])
    sur = np.array([x[1] for x in v])
    p = float(doldu.mean())
    # dolmama koşullu sürüklenme; aleyhe olmayanı 0'a kırp (yedek emri o zaman
    # temel maliyetten daha kötü DEĞİL — kazanç saymıyoruz, sadece ceza yok)
    kalan = sur[~doldu]
    dlt = float(np.clip(kalan, 0, None).mean()) if len(kalan) else 0.0
    kazanc = p * (KAYMA_BP + TAKER_BP)
    kayip = (1 - p) * dlt
    return dict(n=len(v), p=p, delta=dlt, net_bp=kazanc - kayip,
                pstar=dlt / (KAYMA_BP + TAKER_BP + dlt) if (KAYMA_BP + TAKER_BP + dlt) else 0.0,
                doldu=doldu, R=np.array([k["R"] for k in kayit if k.get(W) is not None]),
                t=[k["t"] for k in kayit if k.get(W) is not None])


# ══════════════════════════════════════════════════════════════════════════════
def havuz(source, kayma_bp, ucret_carp, kesme, cache, kayma_kayb=None, ucret_kayb=None,
          maker_kollar=("donchian", "squeeze")):
    """kesme: BB'ye uygulanan kayma. BB HER İKİ KOLDA DA AYNI tutulur (canlıda BB
    zaten maker yolunu kullanıyor; farkı ona yazmak çifte sayım olur).

    maker_kollar: maker muamelesi GÖREN kollar. Geri kalanlar TAKER temelinde
    kalır. KARARIMIZ yalnız donchian'ı açmak (squeeze kontrol grubu olarak taker
    kalıyor) — o yüzden beklenen kâr artışı ('donchian',) ile hesaplanmalı.
    Her ikisini birden açık varsaymak kazancı ŞİŞİRİR."""
    ham = []
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        tf, win, sl_a, rr, mh = A.CFG[kol]
        maker = kol in maker_kollar
        for c in coins:
            d, sig = cache[(kol, c)]
            r0 = R0CACHE.get((kol, c)) if (maker and kayma_kayb is not None) else None
            if maker:
                ham += sim_maliyet(d, sig, sl_a, rr, mh, kayma_bp, ucret_carp,
                                   kayma_kayb, ucret_kayb, r0)
            else:
                ham += sim_maliyet(d, sig, sl_a, rr, mh, kesme, 1.0)
    for c in A.BB_COINS:
        d, sig = cache[("bb", c)]
        ham += sim_maliyet(d, sig, A.BB_SL_ATR, A.BB_RR, A.BB_MH, kesme, 1.0)
    return ham


R0CACHE = {}


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "local"
    print(f"\n{'=' * 118}")
    print("=== MAKER GİRİŞ + PİYASA YEDEĞİ — kayma geri kazanılabilir mi? ===")
    print("  Bugünün en büyük tek sızıntısı: 13.4bp giriş kayması = ankorun $251'i (yılda ~$70).")
    print("  Bu bir sinyal sorunu DEĞİL, saf yürütme maliyeti. Sinyal HİÇ değişmiyor.")

    # ── sinyalleri BİR KEZ çıkar ──
    cache = {}
    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        for c in coins:
            cache[(kol, c)] = sinyal_cek(kol, fast_bt.load(c, source=source))
    for c in A.BB_COINS:
        cache[("bb", c)] = sinyal_cek_bb(fast_bt.load(c, source=source))

    for kol, coins in (("donchian", A.DONCH), ("squeeze", A.SQZ)):
        tf, win, sl_a, rr, mh = A.CFG[kol]
        for c in coins:
            d, sig = cache[(kol, c)]
            R0CACHE[(kol, c)] = _R0(d, sig, sl_a, rr, mh)

    # ── KONTROL 1: maliyetsiz kol ankoru BİREBİR üretmeli ──
    k = olc(koltuk(havuz(source, 0.0, 1.0, 0.0, cache)), A.CAP)
    ok = abs(k["tot"] - 1420.66) < 1.0 and k["n"] == 1579
    print(f"\n  DOĞRULAMA 1 (maliyetsiz == ankor): {k['n']} işlem / ${k['tot']:+.2f} → "
          f"{'✓ BİREBİR' if ok else '✗ SAPMA — araç bozuk, hiçbir satır okunmaz'}")
    if not ok:
        return
    # ── KONTROL 2: ters-seçimli yol, iki maliyet EŞİTken düz yolla aynı olmalı.
    # Yoksa asimetri kolunun ölçtüğü şey asimetri değil, kendi hatasıdır.
    a_ = olc(koltuk(havuz(source, 7.0, 0.5, 7.0, cache)), CAP)
    b_ = olc(koltuk(havuz(source, 7.0, 0.5, 7.0, cache, 7.0, 0.5)), CAP)
    ok2 = abs(a_["tot"] - b_["tot"]) < 0.01 and a_["n"] == b_["n"]
    print(f"  DOĞRULAMA 2 (ters-seçim yolu, maliyetler eşitken düz yolla aynı): "
          f"${a_['tot']:+.2f} vs ${b_['tot']:+.2f} → {'✓' if ok2 else '✗ BOZUK'}")
    if not ok2:
        return

    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 118}")
    print("=== [1] DOLUM ORANI — asıl bilinmeyen. 1 DAKİKALIK veri gerekir. ===")
    print(f"  Post-only limit = sinyal kapanışı. Bar kapandıktan W dk içinde fiyat")
    print(f"  limite dönerse DOLAR (kayma 0 + ücret 0); dönmezse W sonunda PİYASA")
    print(f"  yedeği (13.4bp + o ana kadarki aleyhe sürüklenme). İŞLEM KAÇMAZ.")

    src1m = yerel_1m()
    band = []          # [(derinlik_bp, ozet_donchian, ozet_squeeze)]
    if not src1m:
        print("\n  ⚠ 1dk veri yok — dolum oranı ÖLÇÜLEMEZ. Yalnız duyarlılık tablosu basılır.")
    else:
        print(f"\n  ⚠⚠ VEKİL ÖLÇÜM VE İYİMSER TARAFA YANLI:")
        print(f"     kaynaklar {list(src1m)} — piyasadaki EN LİKİT iki enstrüman. Canlı")
        print(f"     evrende NEAR/ICP/XLM/TRX var; onlarda spread geniş, kuyruk uzun →")
        print(f"     GERÇEK dolum oranı buradan DÜŞÜK olur. BTC Binance venue, canlı değil.")
        print(f"     Kesin ölçüm VPS'te: 'py maker_giris.py mexc' (gerçek 11 coin/borsa).")
        # sinyalleri coin×kol başına BİR KEZ çıkar, derinlik bandını üstünde döndür
        s1m = {}
        for c, m1 in src1m.items():
            for kol in ("donchian", "squeeze"):
                s1m[(c, kol)] = sinyal_cek(kol, m1)
                print(f"    {c:4s} {kol:9s}: {len(s1m[(c, kol)][1]):4d} sinyal")
        for der in DERINLIKLER:
            kd, ks = [], []
            for (c, kol), (d_tf, sig) in s1m.items():
                tf, win, sl_a, rr, mh = A.CFG[kol]
                r = dolum_olc(src1m[c], d_tf, sig, tf, sl_a, rr, mh, PENCERE, der)
                (kd if kol == "donchian" else ks).extend(r)
            band.append((der, dolum_ozet(kd, KARAR_W), dolum_ozet(ks, KARAR_W), kd))

    if band:
        print(f"\n  --- DOLUM BANDI (W={KARAR_W}dk, ön-kayıtlı pencere) ---")
        print(f"  'derinlik' = limitin dolması için fiyatın seviyeyi kaç bp GEÇMESİ şart.")
        print(f"  Kuyruk pozisyonu bilinmiyor; bu yüzden tek sayı değil BANT veriliyor.")
        print(f"\n  {'derinlik':>9s} | {'DONCHIAN':^42s} | {'SQUEEZE':^42s}")
        print(f"  {'bp':>9s} | {'n':>4s} {'dolum%':>7s} {'δbp':>7s} {'p*':>7s} {'net bp':>8s} "
              f"| {'n':>4s} {'dolum%':>7s} {'δbp':>7s} {'p*':>7s} {'net bp':>8s}")
        for der, od_, os_, _ in band:
            def f(o):
                if o is None:
                    return f"{'—':>4s} {'—':>7s} {'—':>7s} {'—':>7s} {'—':>8s}"
                return (f"{o['n']:>4d} {o['p']*100:>6.1f}% {o['delta']:>7.1f} "
                        f"{o['pstar']*100:>6.1f}% {o['net_bp']:>+8.2f}")
            mark = "  ← EN KÖTÜMSER" if der == max(DERINLIKLER) else ""
            print(f"  {der:>9.0f} | {f(od_)} | {f(os_)}{mark}")

        kdk = band[-1][3]                        # en kötümser kuralın kayıtları
        o = band[-1][1]
        if o is not None and o["n"] > 30:
            dz = o["doldu"]; RR = o["R"]
            pw = dz[RR > 0].mean() * 100 if (RR > 0).any() else float("nan")
            pl = dz[RR <= 0].mean() * 100 if (RR <= 0).any() else float("nan")
            print(f"\n    ters-seçim (en kötümser kural): KAZANAN işlemlerde dolum %{pw:.1f} · "
                  f"KAYBEDENlerde %{pl:.1f}")
            print(f"      → PİYASA YEDEĞİ olduğu için işlem KAÇMIYOR. Bu fark yalnız indirimin")
            print(f"        nereye düştüğünü değiştirir, hangi işlemin alındığını DEĞİL.")
            print(f"        (2026-07-16'da geri alınan YEDEKSİZ sürümde bu fark ölümcüldü.)")
            ts = pd.Series([x.value for x in o["t"]]); med = ts.median()
            e1 = dz[ts.values <= med]; e2 = dz[ts.values > med]
            if len(e1) > 20 and len(e2) > 20:
                print(f"    kararlılık: ilk yarı %{e1.mean()*100:.1f} (n{len(e1)}) · "
                      f"ikinci yarı %{e2.mean()*100:.1f} (n{len(e2)})")

        print(f"\n  --- PENCERE DUYARLILIĞI (en kötümser kural, bilgi amaçlı) ---")
        print(f"  {'W dk':>5s} {'dolum%':>8s} {'dolmayan δbp':>13s} {'başabaş p*':>11s} {'NET bp':>8s}")
        for W in PENCERE:
            ow = dolum_ozet(kdk, W)
            if ow is None:
                continue
            mark = "  ← ÖN-KAYITLI" if W == KARAR_W else ""
            print(f"  {W:>5d} {ow['p']*100:>7.1f}% {ow['delta']:>12.1f} "
                  f"{ow['pstar']*100:>10.1f}% {ow['net_bp']:>+8.2f}{mark}")
    od = band[-1][1] if band else None

    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 118}")
    print("=== [2] PORTFÖY — ölçülen dolum oranıyla, ön-kayıtlı bara karşı ===")

    # temel (bugün): tam taker, 13.4bp kayma. BB her iki kolda AYNI.
    T = olc(koltuk(havuz(source, KAYMA_BP, 1.0, KAYMA_BP, cache)), CAP, fonlama=True)
    print(f"\n  TEMEL (bugünkü canlı yürütme: piyasa emri, 13.4bp kayma, tam taker)")
    print(f"    {T['n']} işlem  ${T['tot']:+.0f}  PF {T['pf']:.2f}  ortR {T['ortR']:+.4f}  "
          f"maxDD {T['dd']:.1f}  en kötü ay {T['worst']:+.1f}")

    adaylar = []
    for der, od_, os_, _ in band:
        if od_ is None:
            continue
        adaylar.append((f"kural: {der:.0f}bp geçiş · p={od_['p']*100:.0f}%", od_["p"],
                        od_["delta"], der == max(DERINLIKLER), None, None))
    # TERS-SEÇİMLİ KOL: dolum oranı kazanan/kaybeden işlemlerde AYRI. Düz ortalama
    # bu asimetriyi gizler; 2026-07-16'da geri alınan sürümün ölüm sebebi buydu.
    for der, od_, os_, _ in band:
        if od_ is None:
            continue
        dz = od_["doldu"]; RR = od_["R"]
        if (RR > 0).sum() < 10 or (RR <= 0).sum() < 10:
            continue
        pw = float(dz[RR > 0].mean()); pl = float(dz[RR <= 0].mean())
        adaylar.append((f"TERS-SEÇİMLİ {der:.0f}bp · kaz%{pw*100:.0f}/kayb%{pl*100:.0f}",
                        pw, od_["delta"], False, pw, pl))
    dl_ref = od["delta"] if od is not None else 5.0
    for p_ in (0.20, 0.30, 0.40, 0.50, 0.70):
        adaylar.append((f"duyarlılık p={p_*100:.0f}% (δ={dl_ref:.1f})", p_, dl_ref,
                        False, None, None))

    print(f"\n  {'kol':<32s} {'işlem':>6s} {'toplam$':>9s} {'Δ$':>7s} {'PF':>6s} {'ortR':>8s} "
          f"{'maxDD':>7s} {'ΔmaxDD':>7s} {'en kötü ay':>11s} {'Δay':>6s}  BAR")
    print(f"  {'TEMEL (bugün)':<32s} {T['n']:>6d} {T['tot']:>+9.0f} {'—':>7s} {T['pf']:>6.2f} "
          f"{T['ortR']:>+8.4f} {T['dd']:>7.1f} {'—':>7s} {T['worst']:>+11.1f} {'—':>6s}")
    kazanan = None
    for ad, p_, dl, kotumser, pw, pl in adaylar:
        kb = (1 - p_) * (KAYMA_BP + dl)          # beklenen giriş kayması
        uc = (1 - p_)                            # giriş ücreti çarpanı
        if pw is not None:
            kbk = (1 - pl) * (KAYMA_BP + dl); uck = (1 - pl)
            kb = (1 - pw) * (KAYMA_BP + dl); uc = (1 - pw)
            M = olc(koltuk(havuz(source, kb, uc, KAYMA_BP, cache, kbk, uck)),
                    CAP, fonlama=True)
        else:
            M = olc(koltuk(havuz(source, kb, uc, KAYMA_BP, cache)), CAP, fonlama=True)
        dd_ = M["dd"] - T["dd"]; day = M["worst"] - T["worst"]; dtot = M["tot"] - T["tot"]
        kotu_yil = any(y < -10.0 for y in M["yil"].values)
        gecti = (dtot > BAR_DOLAR) and (not kotu_yil) and (dd_ <= 2.0) and (day >= -0.05)
        mark = "  ← KARAR SATIRI" if kotumser else ""
        print(f"  {ad:<32s} {M['n']:>6d} {M['tot']:>+9.0f} {dtot:>+7.0f} {M['pf']:>6.2f} "
              f"{M['ortR']:>+8.4f} {M['dd']:>7.1f} {dd_:>+7.1f} {M['worst']:>+11.1f} "
              f"{day:>+6.1f}  {'✓ GEÇTİ' if gecti else '✗'}{mark}")
        if kotumser:
            kazanan = (ad, M, dtot, gecti)

    # ══════════════════════════════════════════════════════════════════════════
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 118}")
    print("=== [3] KAPSAM: yalnız DONCHIAN açılırsa ne kazanılır? ===")
    print("  KARAR yalnız donchian'ı açmak; squeeze KONTROL GRUBU olarak taker kalıyor.")
    print("  Yukarıdaki tablo İKİSİNİ birden açık varsayıyordu → beklenen kârı ŞİŞİRİR.")
    don_pay = sum(len(cache[("donchian", c)][1]) for c in A.DONCH)
    sqz_pay = sum(len(cache[("squeeze", c)][1]) for c in A.SQZ)
    print(f"  ham sinyal payı: donchian {don_pay} · squeeze {sqz_pay}")
    print(f"\n  {'dolum kuralı':<22s} {'HER İKİSİ Δ$':>13s} {'YALNIZ donchian Δ$':>19s} "
          f"{'$/yıl':>7s} {'ankor kârının %':>16s}")
    don_sonuc = {}
    for der, od_, os_, _ in band:
        if od_ is None:
            continue
        p_ = od_["p"]; dl = od_["delta"]
        dz = od_["doldu"]; RR = od_["R"]
        pw = float(dz[RR > 0].mean()); pl = float(dz[RR <= 0].mean())
        kb = (1 - pw) * (KAYMA_BP + dl); uc = (1 - pw)
        kbk = (1 - pl) * (KAYMA_BP + dl); uck = (1 - pl)
        ikisi = olc(koltuk(havuz(source, kb, uc, KAYMA_BP, cache, kbk, uck)),
                    CAP, fonlama=True)
        tek = olc(koltuk(havuz(source, kb, uc, KAYMA_BP, cache, kbk, uck,
                               maker_kollar=("donchian",))), CAP, fonlama=True)
        d1 = ikisi["tot"] - T["tot"]; d2 = tek["tot"] - T["tot"]
        print(f"  {der:>3.0f}bp geçiş · p=%{p_*100:<3.0f} {d1:>+13.0f} {d2:>+19.0f} "
              f"{d2/3.6:>+7.0f} {d2/T['tot']*100:>+15.1f}%")
        don_sonuc[der] = d2
    print(f"\n  (hepsi TERS-SEÇİMLİ modelle — kazanan/kaybeden dolum oranı AYRI)")
    if don_sonuc:
        iyi = don_sonuc[min(DERINLIKLER)]; kotu = don_sonuc[max(DERINLIKLER)]
        print(f"\n  ARALIK: en iyi ${iyi:+.0f} · en kötü ${kotu:+.0f} (3.6 yıl)")
        print(f"          yılda ${iyi/3.6:+.0f} ile ${kotu/3.6:+.0f} arası")

    print(f"\n{'=' * 118}\n=== HÜKÜM ===")
    if od is None:
        print("  Dolum oranı ölçülemedi (1dk veri yok). Duyarlılık tablosuna bak:")
        print("  hangi p'den itibaren kârlı olduğunu gösteriyor. VPS'te 'mexc' ile kesin ölç.")
    else:
        print(f"\n  EN KÖTÜMSER KURAL (fiyat limiti {max(DERINLIKLER):.0f}bp GEÇMELİ, W={KARAR_W}dk):")
        print(f"    donchian dolum %{od['p']*100:.1f} · dolmayan aleyhe sürüklenme "
              f"{od['delta']:.1f}bp · başabaş %{od['pstar']*100:.1f}")
        if od["p"] > od["pstar"]:
            print(f"    ✓ En kötümser kuralda bile dolum başabaşın ÜSTÜNDE "
                  f"({od['net_bp']:+.2f}bp/işlem).")
        else:
            print(f"    ✗ En kötümser kuralda dolum başabaşın ALTINDA — bu kurala göre zarar.")
        if kazanan:
            ad, M, dtot, gecti = kazanan
            if gecti:
                print(f"\n  PORTFÖY (karar satırı): ${dtot:+.0f} / 3.6 yıl = yılda ~${dtot/3.6:+.0f}.")
                print(f"    ÖN-KAYITLI BARI GEÇTİ. Bugün denenen 14 filtrenin hiçbiri bu")
                print(f"    büyüklüğe ulaşmadı — ve bu aday SİNYALİ HİÇ DEĞİŞTİRMİYOR:")
                print(f"    aynı işlemler, aynı sayı, sadece daha ucuz giriş.")
            else:
                print(f"\n  PORTFÖY (karar satırı): ${dtot:+.0f} — ön-kayıtlı bar GEÇİLMEDİ.")
        print(f"\n  ⚠ EN ZAYIF HALKA — 13.4bp'nin KENDİSİ: live_verify.py:44'te sabit olarak")
        print(f"    duruyor, ölçüm kodu dosyada YOK. gecikme_olc.py bar kapanışından 1dk")
        print(f"    sonraki sürüklenmeyi ~0bp ölçtü; yani 13.4bp gecikmeden GELMİYOR.")
        print(f"    Geriye spread/etki kalıyor — ki bu maker girişin tam olarak kurtardığı")
        print(f"    şeydir. Ama 13.4bp yanlışsa buradaki $ rakamı da yanlıştır. Ankoru")
        print(f"    denetlediğimiz gibi bu sabit de defterden YENİDEN ölçülmeli.")

    print(f"\n  KODDA DEĞİŞMESİ GEREKEN TEK ŞEY (uygulanırsa):")
    print(f"    1) main.py: donchian/squeeze/sr bloklarında force_market=True kaldırılır")
    print(f"    2) execution.py:611 — is_structure_based ayrımı sl_price'a bakıyor;")
    print(f"       donchian/squeeze sl_price DOLDURUYOR ama SL'i KAPANIŞA çapalıyor.")
    print(f"       Ayrım açık bir bayrağa taşınmalı (ör. signal.anchor_is_level) ki")
    print(f"       bu kollar fallback_market=True alsın. YEDEKSİZ yol 2026-07-16'da")
    print(f"       zaten denenip haklı olarak geri alındı — o hataya DÖNÜLMEMELİ.")
    print(f"\n  ⚠ CANLIYA ALMADAN ÖNCE: bu ölçüm 1dk BAR'ları kullanıyor, kuyruk")
    print(f"    pozisyonu modellenmiyor. Gerçek dolum oranı bundan DÜŞÜK olabilir.")
    print(f"    Kesin cevap defterde: BB kolu canlıda ZATEN maker yolunu kullanıyor.")
    print(f"    VPS'te 'py ucret_olc.py' + 'py live_verify.py' → BB'nin gerçekleşen")
    print(f"    dolum/ücret oranı, donchian/squeeze'in taker oranına karşı.")


if __name__ == "__main__":
    main()
