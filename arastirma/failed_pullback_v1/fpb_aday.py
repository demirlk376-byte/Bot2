"""
FAILED_PULLBACK_V1 — başarısız trend devamı adayı (araştırma uyarlaması).

Linda Raschke'nin "başarısız trend devamı" fikrinden ESİNLENİR; aşağıdaki sayısal
kurallar bu deneyin tanımıdır, onun birebir sistemi değildir. Kurallar deneyden
ÖNCE sabitlendi (kullanıcı tanımı, 2026-09-30); sonuca göre değiştirilmez.

Short:  güçlü yükseliş (a) → ilk EMA20 teması (p, dibi = P) → P ve EMA20 altında
        kapanış (f) → tepe P'ye ulaşır ama kapanış P ve EMA20 altında (q) → short.
Long :  aynanın tersi.

Yalnız KAPANMIŞ 1h mumları, sırayla, tek tek işlenir (akış). Göstergeler akışta
özyinelemeli hesaplanır; indicators.py ile aynı formüller (ema: ewm span=20
adjust=False; ATR/ADX: Wilder = ewm alpha=1/14 adjust=False, ilk değerle tohumlu).
Eşdeğerlik test_fpb.py'de gerçek veride sınanır.

Gelecek bilgisi yok: bir çubuğun kararı yalnız o çubuk ve öncekilerle verilir;
sonraki çubuklar önceki sinyalleri DEĞİŞTİREMEZ (kesme testi).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

ADX_ESIK = 30.0
EMA_N = 20
ADX_N = 14
ATR_N = 14
ISINMA = 100          # a olabilmek için ÖNCESİNDE en az 100 tamamlanmış mum
P_PENCERE = 12        # p ∈ [a+1, a+12]
F_PENCERE = 6         # f ∈ [p+1, p+6]
Q_PENCERE = 6         # q ∈ [f+1, f+6]
STOP_ATR = 0.1
RR = 2.0
MAX_TUTUS = 12        # giriş mumu 1 sayılır; 12 tam mumdan sonra sonraki açılışta çıkış
SAAT_MS = 3_600_000
STRATEJI = "failed_pullback"


class AkisGosterge:
    """EMA20, Wilder ATR14, Wilder ADX14 — indicators.py ile aynı özyineleme."""
    __slots__ = ("n", "ema", "atr", "pdm", "mdm", "adx", "_h", "_l", "_c",
                 "_a_ema", "_a_atr")

    def __init__(self):
        self.n = 0
        self.ema = self.atr = self.pdm = self.mdm = self.adx = None
        self._h = self._l = self._c = None
        self._a_ema = 2.0 / (EMA_N + 1)
        self._a_atr = 1.0 / ATR_N

    def guncelle(self, h: float, l: float, c: float) -> None:
        if self.n == 0:
            tr = h - l
            up = dn = float("nan")
        else:
            tr = max(h - l, abs(h - self._c), abs(l - self._c))
            up = h - self._h
            dn = self._l - l
        pdm = up if (up == up and dn == dn and up > dn and up > 0) else 0.0
        mdm = dn if (up == up and dn == dn and dn > up and dn > 0) else 0.0
        if self.n == 0:
            self.ema = c
            self.atr = tr
            self.pdm = pdm
            self.mdm = mdm
        else:
            self.ema = self.ema + self._a_ema * (c - self.ema)
            self.atr = self.atr + self._a_atr * (tr - self.atr)
            a = 1.0 / ADX_N
            self.pdm = self.pdm + a * (pdm - self.pdm)
            self.mdm = self.mdm + a * (mdm - self.mdm)
        dx = None
        if self.atr and self.atr > 0:
            pdi = 100.0 * self.pdm / self.atr
            mdi = 100.0 * self.mdm / self.atr
            top = pdi + mdi
            if top != 0:
                dx = 100.0 * abs(pdi - mdi) / top
        if dx is not None:
            # pandas ewm: baştaki NaN'lar atlanır, ilk geçerli dx tohumdur
            self.adx = dx if self.adx is None else self.adx + (1.0 / ADX_N) * (dx - self.adx)
        self._h, self._l, self._c = h, l, c
        self.n += 1


@dataclass
class Kurulum:
    yon: int                 # -1 short kurulumu (yükseliş sonrası), +1 long
    a_i: int
    a_ts: int
    adx_a: float
    asama: str = "p"         # p → f → q
    p_i: int = -1
    p_ts: int = 0
    P: float = 0.0
    f_i: int = -1
    f_ts: int = 0
    uc: Optional[float] = None   # q penceresindeki en yüksek tepe (short) / en düşük dip (long)


@dataclass
class Olay:
    tur: str                 # hazirlik | iptal | sinyal | gecersiz | tekrar_mum | eksik_mum
    sembol: str
    ts: int                  # olayın gerçekleştiği mumun AÇILIŞ ms
    yon: int = 0
    neden: str = ""
    a_ts: int = 0
    p_ts: int = 0
    f_ts: int = 0
    q_ts: int = 0
    P: float = 0.0
    E_plan: float = 0.0
    S: float = 0.0
    T: float = 0.0
    atr_q: float = 0.0
    adx_a: float = 0.0
    kimlik: str = ""         # sembol|a_ts — bir hazırlıktan en fazla bir sinyal

    def sozluk(self) -> dict:
        return asdict(self)


class FPBDurum:
    """Tek sembolün akış durumu. isle() her kapanmış 1h mum için bir kez çağrılır."""

    def __init__(self, sembol: str, gosterge=None):
        self.sembol = sembol
        # gosterge: guncelle(h,l,c) + ema/atr/adx alanları. Testler senaryo
        # göstergesi verir; üretimde her zaman AkisGosterge.
        self.g = gosterge if gosterge is not None else AkisGosterge()
        self.i = -1                      # işlenen son mumun sırası
        self.son_ts: Optional[int] = None
        self.kur: Optional[Kurulum] = None
        # a koşulu için gereken geçmiş (son 4 mum): (ts, ema, adx)
        self._gecmis: list = []
        self._onceki_kapanis = None
        self._onceki_ema = None

    # ── yardımcılar ─────────────────────────────────────────────────────────
    def _olay(self, tur, ts, **k) -> Olay:
        return Olay(tur=tur, sembol=self.sembol, ts=ts, **k)

    def _iptal(self, ts, neden) -> Olay:
        k = self.kur
        self.kur = None
        return self._olay("iptal", ts, yon=k.yon, neden=neden, a_ts=k.a_ts,
                          p_ts=k.p_ts, f_ts=k.f_ts, P=k.P, adx_a=k.adx_a,
                          kimlik=f"{self.sembol}|{k.a_ts}")

    # ── ana adım ────────────────────────────────────────────────────────────
    def isle(self, ts: int, o: float, h: float, l: float, c: float) -> list:
        olaylar = []
        if self.son_ts is not None and ts <= self.son_ts:
            # aynı ya da eski mum: yeniden İŞLENMEZ (durum ve göstergeler değişmez)
            return [self._olay("tekrar_mum", ts)]
        bosluk = self.son_ts is not None and ts - self.son_ts > SAAT_MS
        if bosluk:
            olaylar.append(self._olay("eksik_mum", ts,
                                      neden=f"{(ts - self.son_ts) // SAAT_MS - 1} saat eksik"))
            if self.kur is not None:
                olaylar.append(self._iptal(ts, "eksik_mum"))
            self._gecmis = []           # süreklilik koptu; a için 4 ardışık mum gerekir

        onceki_kapanis, onceki_ema = self._onceki_kapanis, self._onceki_ema
        self.g.guncelle(h, l, c)
        self.i += 1
        self.son_ts = ts
        ema, atr, adx = self.g.ema, self.g.atr, self.g.adx
        i = self.i

        aktif_idi = self.kur is not None
        if aktif_idi:
            olaylar.extend(self._ilerle(i, ts, h, l, c, ema, atr,
                                        onceki_kapanis, onceki_ema))

        # Yeni hazırlık: yalnız bu mumdan ÖNCE aktif kurulum yoksa. Aktif kurulum
        # bu mumda bitse bile bu mumdaki ADX geçişi aktifken oluştu → sayılmaz.
        self._gecmis.append((ts, ema, adx))
        if len(self._gecmis) > 4:
            self._gecmis.pop(0)
        if not aktif_idi and i >= ISINMA and len(self._gecmis) == 4 and adx is not None:
            ts3, ema3, _ = self._gecmis[0]
            _, _, adx_once = self._gecmis[2]
            if adx_once is not None and adx_once <= ADX_ESIK < adx:
                yon = 0
                if c > ema and ema > ema3:
                    yon = -1            # güçlü yükseliş → short kurulumu
                elif c < ema and ema < ema3:
                    yon = 1             # güçlü düşüş → long kurulumu
                if yon:
                    self.kur = Kurulum(yon=yon, a_i=i, a_ts=ts, adx_a=adx)
                    olaylar.append(self._olay("hazirlik", ts, yon=yon, a_ts=ts,
                                              adx_a=adx, kimlik=f"{self.sembol}|{ts}"))

        self._onceki_kapanis, self._onceki_ema = c, ema
        return olaylar

    def _ilerle(self, i, ts, h, l, c, ema, atr, onceki_kapanis, onceki_ema) -> list:
        k = self.kur
        y = k.yon
        if k.asama == "p":
            # short: dip EMA20'ye ilk kez ulaşır/altına iner; long: tepe EMA20'ye ulaşır/geçer
            temas = (l <= ema) if y == -1 else (h >= ema)
            if temas:
                on_kosul = (onceki_kapanis > onceki_ema) if y == -1 else (onceki_kapanis < onceki_ema)
                if not on_kosul:
                    return [self._iptal(ts, "ilk_temas_on_kosul_yok")]
                tutundu = (c > ema) if y == -1 else (c < ema)
                if not tutundu:
                    return [self._iptal(ts, "ilk_temas_ema_otesinde_kapandi")]
                k.asama, k.p_i, k.p_ts = "f", i, ts
                k.P = l if y == -1 else h
                return []
            if i >= k.a_i + P_PENCERE:
                return [self._iptal(ts, "p_zaman_asimi")]
            return []
        if k.asama == "f":
            kayip = (c < k.P and c < ema) if y == -1 else (c > k.P and c > ema)
            if kayip:
                k.asama, k.f_i, k.f_ts = "q", i, ts
                k.uc = None
                return []
            if i >= k.p_i + F_PENCERE:
                return [self._iptal(ts, "f_zaman_asimi")]
            return []
        # asama q
        # stop için uç: f+1..q (q dahil) en yüksek tepe (short) / en düşük dip (long)
        if y == -1:
            k.uc = h if k.uc is None else max(k.uc, h)
        else:
            k.uc = l if k.uc is None else min(k.uc, l)
        if y == -1:
            geri_aldi = c >= k.P
            teyit = (h >= k.P) and (c < k.P) and (c < ema)
        else:
            geri_aldi = c <= k.P
            teyit = (l <= k.P) and (c > k.P) and (c > ema)
        if geri_aldi:
            return [self._iptal(ts, "P_geri_alindi")]
        if teyit:
            E = c
            if y == -1:
                S = k.uc + STOP_ATR * atr
                T = E - RR * (S - E)
                gecerli = S > E > T
            else:
                S = k.uc - STOP_ATR * atr
                T = E + RR * (E - S)
                gecerli = T > E > S
            ol = self._olay("sinyal" if gecerli else "gecersiz", ts, yon=y,
                            neden="" if gecerli else "S/E/T sirasi bozuk",
                            a_ts=k.a_ts, p_ts=k.p_ts, f_ts=k.f_ts, q_ts=ts, P=k.P,
                            E_plan=E, S=S, T=T, atr_q=atr, adx_a=k.adx_a,
                            kimlik=f"{self.sembol}|{k.a_ts}")
            self.kur = None              # hazırlık TÜKETİLDİ (sonuç ne olursa olsun)
            return [ol]
        if i >= k.f_i + Q_PENCERE:
            return [self._iptal(ts, "q_zaman_asimi")]
        return []


def seriyi_isle(sembol: str, ts, o, h, l, c) -> list:
    """Tüm seriyi akışla işler (bağımsız sinyal çıkarımı ve kesme testi için)."""
    d = FPBDurum(sembol)
    out = []
    for k in range(len(ts)):
        out.extend(d.isle(int(ts[k]), float(o[k]), float(h[k]), float(l[k]), float(c[k])))
    return out
