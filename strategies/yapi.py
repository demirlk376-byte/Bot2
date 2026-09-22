"""
yapi.py — YAPI ZINCIRI:  supurme -> [displacement] -> MSS -> [FVG] -> limit retest

⚠ NEDEN TEK KOL, ALTI AYRI STRATEJI DEGIL.
Kullanicinin onerdigi A2/A3/A4 ve "Liquidity Sweep + FVG" aileleri AYNI zincirin
farkli kesitleri. Ayri ayri kurmak, tespit tabanini (n~1752, sigma_R~1.35)
gereksiz yere bolerdi. Burada her bacak bir ANAHTAR:
    supurme_sart=False            -> A2  (BOS + FVG retest, supurme yok)
    fvg_sart=False                -> A3  (supurme + MSS, dogrudan giris)
    ikisi de True                 -> A4 / "Liquidity Sweep + FVG"
    displacement_atr>0            -> displacement kapisi

NEDEN 1h (4h DEGIL). MSS kapisi cok seciciydi: 4h'te 8 coinde supurme
barlarinin yalnizca %1-10'u MSS onayi aliyor (n=3579 -> 35..342). 1h dort kat
bar verir; olculebilir orneklem ancak orada olusuyor.

NEDEN 5m/15m DEGIL. Olculdu (DURUM.md): 5m taban/15m setup/1h rejim kurulumunda
Sweep+Reclaim n=24.307 brut edge -0.0103, VWAP n=29.991 -0.0105, BB/Keltner
n=9.824 -0.0026 -- ucu de MALIYET ONCESI sifir. Sebebi yazili: o olcekte yapisal
stoplar %0.56-0.81 ve 20.3bp gidis-donus maliyet bunun 0.32-0.52 R'si.
Uretimdeki 1h/4h sistem kismen bu yuzden calisiyor: stoplar %2-3, maliyet 0.10R.

STANDART SL/TP (kullanicinin istedigi): yapisal SL = supurulen swing'in otesi,
TP = sabit RR. Ilk turda TP varyanti YOK ki setup'lar karsilastirilabilir kalsin.

GELECEGE BAKIS YOK: bir swing ancak k bar SONRA onaylanir; i barinda yalnizca
j+k <= i olan swingler bilinir (bkz. onayli_swingler).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

VARSAYILAN_K = 2          # fractal yari-genisligi (swing i barinda i+k'de onaylanir)
VARSAYILAN_MSS_BAR = 12   # supurmeden sonra MSS icin en fazla kac bar beklenir
VARSAYILAN_BEKLE_BAR = 12 # MSS'ten sonra limit emri kac bar acik kalir
VARSAYILAN_RR = 2.0
VARSAYILAN_SL_TAMPON = 0.25   # yapisal SL'e eklenen ATR payi


@dataclass
class Kurulum:
    yon: int                 # +1 long | -1 short
    giris: float             # emir fiyati (limit ise seviye, degilse kapanis)
    sl: float
    tp: float
    limit_mi: bool           # True -> dolum beklenir, kayma YOK
    supurme_bar: int
    mss_bar: int
    fvg_bar: int             # -1 = FVG kullanilmadi
    gecerlilik_bar: int      # limit emrinin son gecerli bar indisi


def onayli_swingler(high: np.ndarray, low: np.ndarray, k: int = VARSAYILAN_K):
    """Her i bari icin, O ANDA BILINEN en son onayli swing high/low indisi.

    Bir swing high j, high[j] o pencerenin tepesiyse olusur ama ancak j+k
    barinda ONAYLANIR (sonraki k barin da gorulmesi gerekir). Bu yuzden
    son_sh[i], j+k <= i sartini saglayan en buyuk j'dir. Gelecege bakis YOK.
    """
    n = len(high)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for j in range(k, n - k):
        pencere_h = high[j - k:j + k + 1]
        pencere_l = low[j - k:j + k + 1]
        if high[j] == pencere_h.max() and (pencere_h == high[j]).sum() == 1:
            sh[j] = True
        if low[j] == pencere_l.min() and (pencere_l == low[j]).sum() == 1:
            sl[j] = True
    son_sh = np.full(n, -1, dtype=np.int64)
    son_sl = np.full(n, -1, dtype=np.int64)
    a = b = -1
    for i in range(n):
        j = i - k                      # i barinda j=i-k'ye kadar onaylanmis olur
        if j >= 0:
            if sh[j]:
                a = j
            if sl[j]:
                b = j
        son_sh[i] = a
        son_sl[i] = b
    return son_sh, son_sl


def _fvg_bul(high, low, bas, son, yon):
    """[bas, son] araliginda EN SON bosluk (fair value gap).
    bogа (yon=+1): low[i] > high[i-2]  -> bolge [high[i-2], low[i]]
    ayi (yon=-1): high[i] < low[i-2]  -> bolge [high[i], low[i-2]]
    Doner: (i, alt, ust) veya None."""
    for i in range(son, max(bas, 2) - 1, -1):
        if yon > 0 and low[i] > high[i - 2]:
            return i, float(high[i - 2]), float(low[i])
        if yon < 0 and high[i] < low[i - 2]:
            return i, float(high[i]), float(low[i - 2])
    return None


def kurulumlari_bul(
    high, low, close, atr,
    *,
    k: int = VARSAYILAN_K,
    supurme_sart: bool = True,
    mss_sart: bool = True,     # False -> YAPI KIRILIMI ARANMAZ (null kolu)
    mss_olay: bool = False,    # True -> MSS bir OLAY (yeni kirilim); False -> DURUM
    tek_kok: bool = False,     # True -> kok swing YALNIZCA onaylandigi barda aranir
    sabit_sl_atr: float = 0.0, # >0 -> YAPISAL SL YERINE duz ATR stop (KONTROL)
    ref_or: bool = False,      # True -> TEK NET KURAL: son penceredeki referanslarin EN ZAYIFI
    null_gecikme: int = 4,     # null kolunda s'den kac bar sonra girilir
    fvg_sart: bool = True,
    displacement_atr: float = 0.0,
    fvg_derinlik: float = 0.0,
    sahte_seviye_atr: float = 0.0,   # >0 -> FVG YERINE duz ATR mesafesi (PLASEBO)
    mss_bar: int = VARSAYILAN_MSS_BAR,
    bekle_bar: int = VARSAYILAN_BEKLE_BAR,
    rr: float = VARSAYILAN_RR,
    sl_tampon: float = VARSAYILAN_SL_TAMPON,
    bas: int = 300,
):
    """Zinciri tarar ve Kurulum listesi dondurur. Her bar yalnizca KENDINE ve
    GECMISE bakar."""
    high = np.asarray(high, dtype="float64")
    low = np.asarray(low, dtype="float64")
    close = np.asarray(close, dtype="float64")
    atr = np.asarray(atr, dtype="float64")
    n = len(close)
    son_sh, son_sl = onayli_swingler(high, low, k)
    cikti: list[Kurulum] = []

    # ⚠ ust sinir n-1: MSS en erken s+1'de olabilir, yani son bar bile
    # gecerli bir supurme bari olabilir. Once n-2 yazmistim; bu, seriyi
    # kesip 'gelecege bakis' testi yaparken son kurulumu KAYBEDIYORDU ve
    # testi sahte bir sizinti alarmi veriyordu.
    if ref_or:
        # ⚠ TEK NET KURAL olarak yazilmis hali. Coklu tarama, ayni MSS bari
        # icin bircok (kok, referans) ikilisi deniyor ve "en az biri asildi"
        # anlamina geliyordu -- yani penceredeki referanslarin EN ZAYIFI.
        # Burada o kural DOGRUDAN ifade ediliyor: numaralandirma yok, tek
        # kosul. Coklu taramanin +0.20'si GERCEK bir kuraldan geliyorsa bu kol
        # da onu uretmeli; uretmiyorsa edge numaralandirma artefaktiydi.
        return _ref_or_kurulumlari(
            high, low, close, atr, k=k, mss_bar=mss_bar, bekle_bar=bekle_bar,
            rr=rr, sl_tampon=sl_tampon, bas=bas, seviye_atr=sahte_seviye_atr,
            sabit_sl_atr=sabit_sl_atr, ref_kapali=not mss_sart,
            piyasa=not fvg_sart)

    for s in range(max(bas, k + 3), n - 1):
        for yon in (1, -1):
            # --- 1) SUPURME: son onayli swing'in fitille delinip geri alinmasi
            if yon > 0:
                j = son_sl[s]
                if j < 0:
                    continue
                seviye = float(low[j])
                supuruldu = (low[s] < seviye) and (close[s] > seviye)
            else:
                j = son_sh[s]
                if j < 0:
                    continue
                seviye = float(high[j])
                supuruldu = (high[s] > seviye) and (close[s] < seviye)
            if supurme_sart and not supuruldu:
                continue
            if not supurme_sart:
                # A2: supurme aranmiyor -> her bar MSS adayi olabilir, ama
                # ayni MSS'i defalarca almamak icin yalnizca swing'in kendisi
                # taze oldugunda basla.
                if j != (son_sl[s] if yon > 0 else son_sh[s]) or s - j > mss_bar:
                    continue
                # ⚠ tek_kok: YALNIZCA swing'in ONAYLANDIGI barda basla.
                # Varsayilan (False) her s barini deniyor; ayni MSS icin bircok
                # (kok, referans) ikilisi uretiliyor ve dedupe sonrasi EN ESKI
                # kok kaliyor -> daha GENIS stop. Bu bir tercih degil, tarama
                # sirasinin YAN URUNU. Uretim kolu en YENI koku kullaniyor ve
                # edge 3 kat dusuk cikti. Bu bayrak farki TEK MOTORDA olcer.
                if tek_kok and s != j + k:
                    continue

            # --- 2) MSS: supurmeden SONRA, karsi taraftaki son onayli swing'in
            #            KAPANISLA kirilmasi. Referans supurme anindakidir.
            ref = son_sh[s] if yon > 0 else son_sl[s]
            if ref < 0:
                continue
            ref_seviye = float(high[ref]) if yon > 0 else float(low[ref])
            if mss_sart:
                m = -1
                for t in range(s + 1, min(s + 1 + mss_bar, n)):
                    otede = ((yon > 0 and close[t] > ref_seviye) or
                             (yon < 0 and close[t] < ref_seviye))
                    if mss_olay:
                        # ⚠ OLAY semantigi: kirilim BU BARDA yeni olmali.
                        # DURUM semantiginde (varsayilan) fiyatin seviyenin
                        # otesinde OLMASI yetiyor -- offline tarayici boyle
                        # calisiyordu ve olculen +0.1440 ORADAN geliyor.
                        onceki_otede = ((yon > 0 and close[t - 1] > ref_seviye) or
                                        (yon < 0 and close[t - 1] < ref_seviye))
                        otede = otede and not onceki_otede
                    if otede:
                        m = t
                        break
                if m < 0:
                    continue
            else:
                # ⚠ NULL KOLU -- GEOMETRISI ESLESTIRILMIS.
                # Ilk surumde m = s yazmistim: giris bari supurme barinin
                # KENDISI oluyordu, yani giris yapisal SL'e cok yakin dusuyor,
                # risk paydasi sifira gidiyor ve R patliyordu (olculdu: PF 0.15,
                # R = -3.47 +- 6.66 -- bu bir olcum degil, payda artefaktidir).
                # Dogrusu: MSS'in ZAMANLAMASINI koru, BILGISINI kaldir. Kurulum
                # yine s'den `null_gecikme` bar sonra kurulur ama hicbir yapi
                # sarti aranmaz.
                m = s + null_gecikme
                if m >= n:
                    continue

            # --- 3) DISPLACEMENT (istege bagli): MSS bari guclu olmali
            if displacement_atr > 0:
                if not atr[m] > 0:
                    continue
                if abs(close[m] - close[m - 1]) < displacement_atr * atr[m]:
                    continue

            # --- 4) YAPISAL SL: supurulen swing'in otesi
            pay = sl_tampon * (atr[m] if atr[m] > 0 else 0.0)
            sl = seviye - pay if yon > 0 else seviye + pay
            if sabit_sl_atr > 0:
                # ⚠ KONTROL KOLU. "Yapisal" SL'in yerine AYNI mekanikte duz bir
                # ATR stop. Depo bunu daha once olctu (sl_placement_test):
                # duz genis ATR PF 1.43 > swing stop PF 1.31 -> "likidite
                # cercevesi ekstra edge KATMIYOR, sadece stop-genisligi etkisi".
                # Bu bayrak o hukmun BURADA da gecerli olup olmadigini olcer.
                if not atr[m] > 0:
                    continue
                sl = close[m] - yon * sabit_sl_atr * atr[m]

            # --- 5) GIRIS
            if sahte_seviye_atr > 0:
                # ⚠ PLASEBO KOLU. Ayni zincir, ayni SL/TP, ayni limit dolum
                # modeli -- ama seviye FVG'den DEGIL, MSS kapanisindan duz bir
                # ATR mesafesi. FVG bilgi tasiyorsa bu kol ondan KOTU olmali.
                # Tasimiyorsa edge'in kaynagi "limitle geri cekilmeden al"dir,
                # yapi degil.
                if not atr[m] > 0:
                    continue
                giris = close[m] - yon * sahte_seviye_atr * atr[m]
                limit_mi, fvg_bar = True, -2
            elif fvg_sart:
                bulgu = _fvg_bul(high, low, s + 1, m, yon)
                if bulgu is None:
                    continue
                fi, alt, ust = bulgu
                if not ust > alt:
                    continue
                # derinlik 0.0 = bolgenin YAKIN kenari (sig retest)
                #          1.0 = uzak kenari (tam dolum)
                giris = (ust - fvg_derinlik * (ust - alt)) if yon > 0 else \
                        (alt + fvg_derinlik * (ust - alt))
                limit_mi, fvg_bar = True, fi
            else:
                giris = float(close[m])
                limit_mi, fvg_bar = False, -1

            risk = (giris - sl) if yon > 0 else (sl - giris)
            if not risk > 0:
                continue
            tp = giris + yon * rr * risk
            cikti.append(Kurulum(yon, float(giris), float(sl), float(tp),
                                 limit_mi, s, m, fvg_bar,
                                 min(m + bekle_bar, n - 1)))
    return cikti


# ==========================================================================
#  URETIM KOLU — main.py'nin cagirdigi, BAR BAR calisan surum
# ==========================================================================

@dataclass
class YapiSignal:
    direction: int = 0
    strength: float = 0.0
    reason: str = ""
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_price: float = 0.0
    bekleyen_yas: int = 0


class YapiStrategy:
    """swing -> MSS -> seviyeye geri cekilmede LIMIT giris.

    ⚠ NEDEN BEKLEME MANTIGI BURADA, BORSADA DEGIL.
    PaperExchange.place_limit_order duran bir emri MODELLEMIYOR: cagrildigi
    anda limit fiyatindan DOLDURUYOR. Kolu dogrudan ona baglasaydik IKIZ her
    emri piyasadan ~1 ATR iyi fiyattan, HER ZAMAN, ANINDA doldururdu ve
    uydurma bir edge uretirdi. Bunun yerine kurulum burada BEKLETILIYOR ve
    sinyal ancak fiyat seviyeye GERCEKTEN dokundugu mumda uretiliyor --
    on elemede olculen modelin (ikiz_on_eleme.kos_yapi) birebir aynisi.

    ⚠ CANLI ile IKIZ arasindaki BILINEN FARK: canlida emir MSS aninda konup
    saatlerce durabilir; burada ise dokunus mumunun KAPANISINDA sinyal uretilip
    seviyeye limit konuyor (execution.py 600sn pencere, piyasa yedegi YOK).
    Bu fark IKIZ'i degil CANLIYI dezavantajli yapar (dokunusu kacirabiliriz),
    yani hukum guvenli tarafta kalir. Emrin saatlerce durmasi execution/exchange
    tarafinda bekleyen-emir modeli ister; o ayri bir istir.

    Durum: sembol basina ornek. main.py her coin icin ayri ornek tutar.
    """

    def __init__(
        self,
        k: int = VARSAYILAN_K,
        seviye_atr: float = 1.0,
        mss_bar: int = VARSAYILAN_MSS_BAR,
        bekle_bar: int = VARSAYILAN_BEKLE_BAR,
        rr: float = VARSAYILAN_RR,
        sl_tampon: float = VARSAYILAN_SL_TAMPON,
        mss_olay: bool = False,   # True -> OLAY semantigi (olculdu: 3 kat zayif)
    ):
        self._k = int(k)
        self._seviye_atr = float(seviye_atr)
        self._mss_bar = int(mss_bar)
        self._bekle_bar = int(bekle_bar)
        self._rr = float(rr)
        self._sl_tampon = float(sl_tampon)
        self._mss_olay = bool(mss_olay)
        self._adaylar: dict[int, dict] = {}  # yon -> {ref, kok, yas}
        self._bekleyen: list[dict] = []  # MSS oldu, dolum bekleniyor
        self._last_ts = None

    def _min_bars(self) -> int:
        return self._k * 2 + self._mss_bar + 10

    def analyze(self, df, atr_val: float) -> YapiSignal:
        if df is None or len(df) < self._min_bars():
            return YapiSignal(reason=f"insufficient data ({0 if df is None else len(df)})")
        if atr_val is None or atr_val <= 0:
            return YapiSignal(reason="ATR yok")

        last_ts = df.index[-1]
        h = df["high"].to_numpy(dtype="float64")
        l = df["low"].to_numpy(dtype="float64")
        c = df["close"].to_numpy(dtype="float64")

        if self._last_ts == last_ts:
            return YapiSignal(reason="ayni bar")

        # ⚠ KESINTI/BACKFILL KORUMASI (fvg.py'deki ayni hata). Besleme bir
        # kopukluktan sonra TUM kacan mumlari doldurur ama kapanis geri
        # cagrisini yalnizca EN YENISI icin tetikler. Bekleyen emirler o arada
        # dolmus/bayatlamis olabilir; bilemedigimiz icin HEPSINI IPTAL et.
        if (self._last_ts is not None and len(df.index) >= 2
                and df.index[-2] != self._last_ts):
            self._adaylar.clear()
            self._bekleyen.clear()
        self._last_ts = last_ts

        # ⚠ DURUM SEMANTIGI (parite hatasiyla, iki kez ogrenildi).
        # MSS'i bir OLAY olarak kodlamistim: "yapi BU BARDA kirildi". On eleme
        # ise DURUM olarak calisiyordu: "fiyat SU AN yapinin otesinde".
        # 13 coinde olculdu (dolum payi 0.05 ATR):
        #   DURUM  n=11050 PF 1.22 R=+0.1123  (TRAIN +0.0875 / TEST +0.1403)
        #   OLAY   n= 9901 PF 1.07 R=+0.0391  (TRAIN +0.0331 / TEST +0.0459)
        # Orneklem benzer -- guc sorunu degil, SEMANTIK farki. Kirilim aninda
        # girmek zayif; yapinin OTESINDEYKEN geri cekilmeleri almak guclu.
        # Bu, bu depoda tekrar eden bulguyla ayni yone bakiyor: "olayi bekle"
        # varyantlarinin hepsi basarisiz oldu.
        #
        # ASAMALAR:
        #   aday    : onayli swing + O ANDAKI karsi swing referansi (yon basina 1)
        #   bekleyen: fiyat referansin otesinde -> her bar TAZELENEN limit
        for a in self._adaylar.values():
            a["yas"] += 1
        self._adaylar = {y: a for y, a in self._adaylar.items()
                         if a["yas"] <= self._mss_bar * 2}
        for b in self._bekleyen:
            b["yas"] += 1
        self._bekleyen = [b for b in self._bekleyen if b["yas"] <= self._bekle_bar]

        # --- 1) ONCE dolum: bu barda tazelenen emir AYNI barda dolamaz.
        secilen = None
        for b in self._bekleyen:
            if b["yas"] < 1:
                continue
            degdi = (l[-1] <= b["giris"]) if b["yon"] > 0 else (h[-1] >= b["giris"])
            if degdi:
                secilen = b
                break
        if secilen is not None:
            self._bekleyen = [b for b in self._bekleyen if b["yon"] != secilen["yon"]]
            yon = secilen["yon"]
            ad = "long" if yon > 0 else "short"
            return YapiSignal(
                direction=yon, strength=0.75,
                reason=(f"yapi {ad}: yapinin otesinde, seviye "
                        f"{secilen['giris']:.6g} (SL {secilen['sl']:.6g})"),
                sl_price=secilen["sl"], tp_price=secilen["tp"],
                entry_price=secilen["giris"], bekleyen_yas=secilen["yas"])

        # --- 2) YENI onayli swing -> o yonun adayini TAZELE.
        # Referans, swing'in onaylandigi ANDAKI karsi swing'dir.
        kuyruk = max(120, self._mss_bar * 6, self._k * 4 + 20)
        if len(c) > kuyruk:
            h_k, l_k, c_k = h[-kuyruk:], l[-kuyruk:], c[-kuyruk:]
        else:
            h_k, l_k, c_k = h, l, c
        son_sh, son_sl = onayli_swingler(h_k, l_k, self._k)
        i = len(h_k) - 1
        j = i - self._k
        if j >= 0:
            if son_sl[i] == j and son_sh[i] >= 0:
                self._adaylar[1] = {"ref": float(h_k[son_sh[i]]),
                                    "kok": float(l_k[j]), "yas": 0}
            if son_sh[i] == j and son_sl[i] >= 0:
                self._adaylar[-1] = {"ref": float(l_k[son_sl[i]]),
                                     "kok": float(h_k[j]), "yas": 0}

        # --- 3) DURUM: fiyat referansin otesinde mi? Oyleyse limiti TAZELE.
        # Yon basina EN FAZLA BIR bekleyen emir tutulur. Long'da fiyat
        # yukselirken en YENI seviye en YUKSEKTIR, yani zaten ilk dolacak
        # olandir; fiyat duserse eski (daha yuksek) seviye bu bardan ONCE
        # zaten dolmus olurdu (adim 1 once calisiyor). Bu yuzden tek emri
        # tazelemek, offline tarayicinin "her bar yeni emir, ilk dolan kazanir"
        # davranisiyla pratikte ayni -- ve CANLIDA uygulanabilir olan budur.
        c_son = float(c_k[i])
        for yon, a in self._adaylar.items():
            if a["yas"] < 1:
                continue
            otede = (c_son > a["ref"]) if yon > 0 else (c_son < a["ref"])
            if self._mss_olay:
                onceki = (float(c_k[i - 1]) > a["ref"]) if yon > 0 else \
                         (float(c_k[i - 1]) < a["ref"])
                otede = otede and not onceki
            if not otede:
                continue
            sl = a["kok"] - yon * self._sl_tampon * atr_val
            giris = c_son - yon * self._seviye_atr * atr_val
            risk = (giris - sl) if yon > 0 else (sl - giris)
            if not risk > 0:
                continue
            self._bekleyen = [b for b in self._bekleyen if b["yon"] != yon]
            self._bekleyen.append({"yon": yon, "giris": giris, "sl": sl,
                                   "tp": giris + yon * self._rr * risk, "yas": 0})

        return YapiSignal(reason=f"aday {len(self._adaylar)} / bekleyen {len(self._bekleyen)}")


def _ref_or_kurulumlari(high, low, close, atr, *, k, mss_bar, bekle_bar,
                        rr, sl_tampon, bas, seviye_atr, sabit_sl_atr,
                        ref_kapali=False, piyasa=False):
    """Coklu taramanin ifade ettigi kuralin TEK KOSUL halindeki yazimi.

    m barinda long kurulumu:
      son `mss_bar` bar icindeki HER s icin, s'de gecerli olan swing high
      referansi toplanir (o s'de swing low da `mss_bar`'dan taze olmak sarti).
      Kosul: close[m] bu referanslarin EN DUSUGUNUN uzerinde.
    Short aynasi. SL duz ATR, TP sabit RR.
    """
    n = len(close)
    son_sh, son_sl = onayli_swingler(high, low, k)
    cikti: list[Kurulum] = []
    for m in range(max(bas, k + 3) + 1, n):
        for yon in (1, -1):
            refler = []
            for s in range(max(0, m - mss_bar), m):
                kok = son_sl[s] if yon > 0 else son_sh[s]
                ref = son_sh[s] if yon > 0 else son_sl[s]
                if kok < 0 or ref < 0 or s - kok > mss_bar:
                    continue
                refler.append(float(high[ref]) if yon > 0 else float(low[ref]))
            if not refler:
                continue
            esik = min(refler) if yon > 0 else max(refler)
            # ⚠ NULL KOLU: referans kosulunu KALDIR, geri kalan ayni kalsin.
            if not ref_kapali:
                if not ((close[m] > esik) if yon > 0 else (close[m] < esik)):
                    continue
            if not atr[m] > 0:
                continue
            # ⚠ PIYASA KOLU: limit geri cekilmesi yerine kapanista gir.
            giris = float(close[m]) - (0.0 if piyasa else yon * seviye_atr * atr[m])
            sl = float(close[m]) - yon * (sabit_sl_atr or 2.0) * atr[m]
            risk = (giris - sl) if yon > 0 else (sl - giris)
            if not risk > 0:
                continue
            cikti.append(Kurulum(yon, giris, sl, giris + yon * rr * risk,
                                 not piyasa, m, m, -2, min(m + bekle_bar, n - 1)))
    return cikti
