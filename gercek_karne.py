"""
gercek_karne.py — GERÇEK KOL KARNESİ: her işlemin sonucu BORSANIN kendi kayıtlarından (YALNIZ OKUR).

Defter (trades.db) kârı borsadan fazla yazıyor (DURUM 4t): ücret 1bp sabit yazılıyor, funding hiç
yazılmıyor, eski çıkışlar seviye fiyatından. Bu araç her canlı işlem için borsanın dolum (fetch_my_trades)
ve funding (fetch_funding_history) kayıtlarından gerçek net sonucu, defterle farkını ve kol bazında
gerçek R'yi verir.

EMİR DÜZEYİNDE EŞLEŞTİRME (hedge modu: aynı sembolün aynı bacağında birden çok kol AYNI ANDA pozisyon
tutabilir; her kolun kendi giriş emri ve kendi stop'u vardır):
  1. Dolumlar EMİRLERE toplanır (sembol, orderId): açılış/kapanış, bacak, ilk/son dolum, baz miktar,
     tutar (Σ fiyat × kontrat × kontrat büyüklüğü), USDT ücret.
  2. Giriş = aynı sembol+bacakta orderId == trades.id olan açılış emri (canlı işlemde trades.id = MEXC
     giriş emri kimliği). Kimlik bulunamazsa YEDEK: başka bir defter işlemine ait olmayan, kullanılmamış,
     defter girişine ≤ 15 dk ve miktarı defterdekinin %2'si içinde olan en yakın açılış emri.
  3. Çıkış = girişten sonraki, aynı sembol+bacaktaki kapanış emirleri, MİKTARLA paylaştırılır: önce
     miktarı işleminkiyle birebir tutan emirler — ilk tur defter çıkışına ≤ 15 dk (%2), ikinci tur ≤ 6 saat,
     miktar AYNI (defter çıkışı geç yazılmışsa: bot kapalıyken tetiklenen stoplar yeniden başlatmada 'şimdi'
     saatiyle kaydedilir; defter çıkışının ≤ 15 dk yakınında işlemi tek başına karşılayan, çekişmesiz kapanış
     miktarı varsa ikinci tur o işleme uygulanmaz). Birebir turlarda aday (işlem, emir) çiftleri AÇGÖZLÜ
     atanır (her işlem ve emir bir kez), sıra anahtarı (⌊|Δt| / 150 sn⌋, fiyat terimi, |Δt|); Δt = emir
     zamanı − defter çıkışı. Dış kapanışlar 120 sn'lik mutabakat döngüsünde yazılır, defter çıkış saati ancak
     ~1 döngü hassastır: aynı 150 sn'lik 'zaman kovasında' fiyat karar verir, farklı kovalarda zaman (fiyat
     zamanı ASLA ezmez). Fiyat terimi = |emir ortalama fiyatı − defter çıkış fiyatı| / |giriş − sl0|, yalnız
     defter çıkış fiyatı güvenilirse (exit_price_estimated işaretsiz ve eski mutabakatın SL/TP seviyesinden
     yazılmış satır değil; çıkış fiyatı hiç yoksa defter stop fiyatı); değilse 0 (zaman karar verir). Aynı
     kovada açgözlü seçilen çiftler, yalnız KENDİ ARALARINDA yeniden dağıtılarak Σ fiyat terimi küçülüyorsa
     global düzenlenir — çift sayısı en büyüklenmez (uzak kovadaki bir çifti mümkün kılmak için yakın kovadaki
     çift bırakılmaz). Sonra kalan işlemler için emirler |emir zamanı − defter çıkışı| sırasıyla (≤ 15 dk
     öncelikli, en fazla 6 saat) tüketilir; büyük bir emir (ör. bacağın tamamını kapatan uzlaştırma) birden
     çok işleme BÖLÜNÜR. Miktar %2 içinde karşılanamazsa işlem "eşleşmedi" sayılır (tahmin yok).
  4. Gerçek net = yön × (çıkış tutarı payı − giriş tutarı payı) − (giriş + çıkış ücreti payı) + funding payı;
     giriş tutarı ve giriş ücreti KAPSANAN miktarla orantılanır (kapanışı bulunan kısım).
     Funding kaydı (bacağı biliniyorsa yalnız o bacak) o anda o bacakta açık olan TÜM işlemlere baz
     miktarla orantılı paylaştırılır. Paydaya raporlanmayan pozisyonlar da girer (payları raporlanmaz):
     açık defter işlemleri (giriş emri bulunamazsa defter giriş saati ve miktarıyla), girişi bulunamayan
     kapanmış işlemler ve yarım yazılmış satırlar (exit_time dolu, pnl NULL) — bu ikisi defter giriş→çıkış
     saati ve defter miktarıyla.
Eşleşmeyen işlem rakama KATILMAZ.

HİÇBİR emir/ayar göndermez (kaldıraç ayarı bile yok). Kullanım (VPS):
    cd /opt/bot2 && venv/bin/python gercek_karne.py
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import erken_uyari as EU  # noqa: E402
from config import load_config  # noqa: E402

GIRIS_YEDEK_MS = 15 * 60_000     # kimlik bulunamazsa giriş emri defter girişine en fazla bu kadar uzak
CIKIS_TERCIH_MS = 15 * 60_000    # kapanış emri defter çıkışına bu kadar yakınsa öncelikli
CIKIS_AZAMI_MS = 6 * 3_600_000   # kapanış emri defter çıkışından en fazla bu kadar uzak olabilir
MIKTAR_TOL = 0.02                # miktar eşleşme ve kapsama toleransı (%2)
UZAK_MIKTAR_TOL = 1e-6           # uzak (>15 dk) birebir eşleşmede miktar AYNI olmalı: botun stop/kapanış emri giriş
                                 # emrinin kontrat sayısını taşır; %2 tolerans saatler içinde tesadüfi eşleşme üretir
KOVA_MS = 150_000                # birebir turda zaman kovası: canlı bot dış kapanışları 120 sn'lik mutabakat döngüsünde
                                 # yazar (main.py asyncio.sleep(120)) → defter exit_time ancak ~1 döngü hassas; aynı
                                 # kovadaki çiftler arasında fiyat, farklı kovalar arasında zaman karar verir
EPS = 1e-9


def ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def bacak_adi(side) -> str:
    return "long" if str(side).lower() in ("long", "buy") else "short"


_SUTUNLAR = ("symbol, side, entry_price, exit_price, quantity, sl_price, entry_time, exit_time, pnl_usdt,"
             " exit_reason, strategy_scores")


def defter_oku(db: str) -> tuple[list[dict], list[dict], set[str]]:
    """(kapanmış canlı işlemler, RAPORLANMAYAN canlı satırlar, TÜM canlı defter kimlikleri). Kapanmış süzgeci
    EU.islemleri_oku ile aynı (is_paper=0, exit_time ve pnl dolu, aynı sıra); ek olarak trades.id okunur
    (canlı işlemde = MEXC giriş emri kimliği; sütun yoksa None) ve tp_price (eski seviye kaydı tespiti için;
    sütun yoksa None). Raporlanmayan satırlar = AÇIK işlemler (exit_time NULL) + YARIM yazılmış satırlar
    (exit_time dolu, pnl NULL); yalnız funding paydasına girerler (pozisyon gerçekti). Kimlik kümesi yedek
    eşleştirmenin başkasının emrini almasını engeller."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        sutun = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
        idq = "id" if "id" in sutun else "NULL AS id"
        tpq = "tp_price" if "tp_price" in sutun else "NULL AS tp_price"
        satirlar = [dict(r) for r in con.execute(f"SELECT {idq}, {tpq}, {_SUTUNLAR} FROM trades WHERE is_paper=0")]
    finally:
        con.close()
    kapali = [t for t in satirlar if t["exit_time"] is not None and t["pnl_usdt"] is not None]
    acik = [t for t in satirlar if t["exit_time"] is None or t["pnl_usdt"] is None]
    kapali.sort(key=lambda t: (t["exit_time"], t["entry_time"]))
    return kapali, acik, {str(t["id"]) for t in satirlar if t["id"] not in (None, "")}


async def dolumlar(ex, sym, bas, bit, gun=7, sayfa_boyu=100):
    """Tüm dolumlar: 7 günlük pencereler × sayfa numarası (MEXC order_deals sırası ve 100 sınırı yüzünden
    'son zamandan devam' yöntemi kayıp verir). Kimliğe göre tekilleştirilir."""
    out, gorulen, hata = [], set(), None
    w = bas
    while w < bit:
        w2 = min(w + gun * 86_400_000, bit)
        for sayfa in range(1, 60):
            try:
                r = await ex.fetch_my_trades(sym, w, sayfa_boyu, {"end_time": w2, "page_num": sayfa})
            except Exception as e:
                hata = str(e)
                break
            yeni = [x for x in (r or []) if x.get("id") not in gorulen]
            for x in yeni:
                gorulen.add(x.get("id"))
            out += yeni
            await asyncio.sleep(0.2)
            if len(r or []) < sayfa_boyu or not yeni:
                break
        w = w2
    return out, hata


async def fundingler(ex, sym, bas, sayfa_boyu=100):
    """Funding kayıtları: sayfa numarasıyla geriye doğru, bas'tan eski kayda ulaşınca dur."""
    out, gorulen, hata = [], set(), None
    for sayfa in range(1, 200):
        try:
            r = await ex.fetch_funding_history(sym, None, sayfa_boyu, {"page_num": sayfa})
        except Exception as e:
            hata = str(e)
            break
        yeni = [x for x in (r or []) if (x.get("id"), x.get("timestamp")) not in gorulen]
        for x in yeni:
            gorulen.add((x.get("id"), x.get("timestamp")))
        out += yeni
        await asyncio.sleep(0.2)
        if len(r or []) < sayfa_boyu or not yeni or min(int(x.get("timestamp") or 0) for x in yeni) < bas:
            break
    return out, hata


def guven(rs):
    if len(rs) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(20261004)
    a = np.asarray(rs, float)
    o = [rng.choice(a, len(a)).mean() for _ in range(5000)]
    return float(np.percentile(o, 2.5)), float(np.percentile(o, 97.5))


# ───────────────────────────── emir düzeyinde eşleştirme ─────────────────────────────

def emirleri_kur(dolum: dict) -> dict:
    """Dolumları EMİRLERE topla. MEXC order_deals 'side' (info.side): 1 long aç, 2 short kapat, 3 short aç,
    4 long kapat (ccxt'nin normalize 'side' alanı 2/3/4 için YANLIŞ — kullanılmaz). Alış = 1/2, satış = 3/4.
    Baz miktar = kontrat × kontrat büyüklüğü (x['_cs']). orderId yoksa her dolum kendi emri sayılır."""
    out = {}
    for s, ds in dolum.items():
        em = {}
        for x in ds:
            info = x.get("info") or {}
            kod = str(info.get("side") or "")
            if kod not in ("1", "2", "3", "4"):
                continue
            oid = x.get("order") or info.get("orderId")
            oid = str(oid) if oid not in (None, "") else f"dolum:{x.get('id')}"
            v = float(x["amount"]) * float(x.get("_cs") or 1.0)
            tutar = float(x["price"]) * v                 # ccxt 'cost' alanına güvenme
            fee = x.get("fee") or {}
            ucr = float(fee.get("cost") or 0) if (fee.get("currency") or "USDT").upper() == "USDT" else 0.0
            ts = int(x["timestamp"])
            e = em.get((oid, kod))
            if e is None:
                e = em[(oid, kod)] = dict(sembol=s, oid=oid, kod=kod, bacak="long" if kod in ("1", "4") else "short",
                                          ac=kod in ("1", "3"), ilk=ts, son=ts, adet=0.0, tutar=0.0, ucret=0.0,
                                          dolum=0, paylar=[])
            e["ilk"], e["son"] = min(e["ilk"], ts), max(e["son"], ts)
            e["adet"] += v
            e["tutar"] += tutar
            e["ucret"] += ucr
            e["dolum"] += 1
        lst = sorted(em.values(), key=lambda e: (e["ilk"], e["oid"]))
        for e in lst:
            e["kalan"] = e["adet"]
        out[s] = lst
    return out


def _miktar_tutar(a: float, b: float, tol: float = MIKTAR_TOL) -> bool:
    return b > 0 and abs(a - b) <= tol * b


def _macar(M: list[list[int]]) -> list[int]:
    """Kare TAM SAYI maliyet matrisinde toplamı en küçük atama (Macar yöntemi, O(n³)); satır → sütun.
    Tam sayı aritmetiği: sözlüksel (çift sayısı, fiyat, zaman) maliyeti tek sayıya kayıpsız gömülebilir."""
    n = len(M)
    u, v, p, yol = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, kul = [None] * (n + 1), [False] * (n + 1)
        while True:
            kul[j0] = True
            i0, delta, j1 = p[j0], None, 0
            for j in range(1, n + 1):
                if not kul[j]:
                    cur = M[i0 - 1][j - 1] - u[i0] - v[j]
                    if minv[j] is None or cur < minv[j]:
                        minv[j], yol[j] = cur, j0
                    if delta is None or minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if kul[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = yol[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, n + 1):
        out[p[j] - 1] = j - 1
    return out


def _sayi(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _skor_sozluk(t: dict) -> dict:
    s = EU._skor(t)
    return s if isinstance(s, dict) else {}


def _evet(v) -> bool:
    return v is True or v == 1 or str(v).strip().lower() == "true"


def _seviye_kaydi(t: dict, xp: float, sk: dict) -> bool:
    """Eski mutabakat satırı mı: çıkış GERÇEK dolumdan değil SL/TP SEVİYESİNDEN yazılmış (2026-08-30 öncesi
    main.py: exit_price = pos.sl_price / pos.tp_price; ne exit_price_estimated ne exit_fee_source vardı).
    Tespit: exit_reason sl_hit/tp_hit ve exit_price o seviyeye eşit, exit_fee_source YOK (2026-10-04'ten beri
    her kapanış onu yazar; o satırlarda fiyat ya dolumdur ya işaretlidir). Ayırt edilemeyen satır güvenilir
    sayılır — fiyat zaten yalnız aynı zaman kovasında etkili."""
    if "exit_fee_source" in sk:
        return False
    neden = str(t.get("exit_reason") or "").strip().lower()
    seviye = _sayi(t.get("sl_price")) if neden == "sl_hit" else _sayi(t.get("tp_price")) if neden == "tp_hit" else 0.0
    return seviye > 0 and abs(xp - seviye) <= 1e-9 * seviye


def _fiyat_ref(t: dict):
    """Birebir turda kova içi eşitlik bozucu için GÜVENİLİR defter çıkış fiyatı, yoksa None (zaman karar verir).
    None: exit_price_estimated işaretli (fiyat seviye / mark / GİRİŞ fiyatına düşmüş) ya da eski seviye kaydı.
    Çıkış fiyatı hiç yoksa (NULL/≤0, işaretsiz) defter stop fiyatı (yoksa None)."""
    sk = _skor_sozluk(t)
    if _evet(sk.get("exit_price_estimated")):
        return None
    xp = _sayi(t.get("exit_price"))
    if xp > 0:
        return None if _seviye_kaydi(t, xp, sk) else xp
    sl = _sayi(t.get("sl_price"))
    return sl if sl > 0 else None


def hesapla(islemler: list[dict], aciklar: list[dict], dolum: dict, fon: dict, tum_idler=()) -> dict:
    """Saf hesap (ağ yok): defter işlemleri + dolumlar + funding → satırlar ve tanı sayıları.
    aciklar: raporlanmayan canlı satırlar — exit_time NULL ise AÇIK işlem (giriş emri aranır), exit_time dolu
    (pnl NULL, yarım yazılmış) ise yalnız funding paydasına defter giriş→çıkış saati ve miktarıyla girer."""
    emirler = emirleri_kur(dolum)
    acilis = defaultdict(list)       # (sembol, bacak) → açılış emirleri
    kapanis = defaultdict(list)      # (sembol, bacak) → kapanış emirleri
    kimlik = {}                      # (sembol, orderId) → açılış emri
    for s, lst in emirler.items():
        for e in lst:
            (acilis if e["ac"] else kapanis)[(s, e["bacak"])].append(e)
            if e["ac"]:
                kimlik[(s, e["oid"])] = e
    defter_idleri = {str(t["id"]) for t in islemler + aciklar if t.get("id") not in (None, "")} | set(tum_idler)

    # İşlem kayıtları (kapanmış + açık + yarım yazılmış); açık ve yarımlar yalnız funding paydası için.
    # Yarım satır (exit_time dolu, pnl NULL) emir eşleştirmesine GİRMEZ (kimliği yedeği zaten engeller).
    K = []
    for t in islemler:
        K.append(dict(t=t, acik=False, yarim=False, bacak=bacak_adi(t["side"]), g=ms(t["entry_time"]),
                      c=ms(t["exit_time"]), giris=None, yol=None, paylar=[]))
    for t in aciklar:
        yarim = t.get("exit_time") not in (None, "")
        K.append(dict(t=t, acik=not yarim, yarim=yarim, bacak=bacak_adi(t["side"]), g=ms(t["entry_time"]),
                      c=ms(t["exit_time"]) if yarim else None, giris=None, yol=None, paylar=[]))

    # 2a) Giriş: orderId == trades.id
    for k in K:
        if k["yarim"]:
            continue
        tid = k["t"].get("id")
        e = kimlik.get((k["t"]["symbol"], str(tid))) if tid not in (None, "") else None
        if e is not None and e["bacak"] == k["bacak"] and not e.get("_kullanan"):
            e["_kullanan"] = k
            k["giris"], k["yol"] = e, "kimlik"
    # 2b) Yedek: zaman (≤15 dk) + miktar (%2); başka defter işleminin kimliği olan emir ALINMAZ.
    #     En yakın çiftler önce (açgözlü sıra işlem sırasına bağlı kalmasın).
    ciftler = []
    for i, k in enumerate(K):
        if k["giris"] is not None or k["yarim"]:
            continue
        q = float(k["t"]["quantity"] or 0)
        for e in acilis.get((k["t"]["symbol"], k["bacak"]), []):
            if e.get("_kullanan") or e["oid"] in defter_idleri:
                continue
            dt = abs(e["ilk"] - k["g"])
            if dt <= GIRIS_YEDEK_MS and _miktar_tutar(e["adet"], q):
                ciftler.append((dt, i, e["ilk"], e["oid"], e))
    for dt, i, _, _, e in sorted(ciftler, key=lambda c: c[:4]):
        k = K[i]
        if k["giris"] is None and not e.get("_kullanan"):
            e["_kullanan"] = k
            k["giris"], k["yol"] = e, "yedek"

    # 3) Çıkış: kapanış emirlerini MİKTARLA paylaştır (yalnız kapanmış ve girişi bulunan işlemler)
    def pay_al(k, e, al):
        e["kalan"] -= al
        pay = dict(emir=e, adet=al, islem=k)
        e["paylar"].append(pay)
        k["paylar"].append(pay)

    def adaylar(k, azami):
        out = []
        for e in kapanis.get((k["t"]["symbol"], k["bacak"]), []):
            if e["kalan"] <= EPS * max(1.0, e["adet"]) or e["ilk"] < k["giris"]["ilk"]:
                continue
            dt = abs(e["ilk"] - k["c"])
            if dt <= azami:
                out.append((dt, e))
        return out

    cikacak = [k for k in K if not k["acik"] and k["giris"] is not None]
    _ref_olcek = {}

    def fiyat_terimi(i, e) -> float:
        """Kova içi eşitlik bozucu, R biriminde: |emir ortalama fiyatı − defter çıkış fiyatı| / |giriş − sl0|.
        Güvenilir defter fiyatı yoksa 0 (bu işlemin tüm adayları eşit → zaman karar verir)."""
        if i not in _ref_olcek:
            t = cikacak[i]["t"]
            ref = _fiyat_ref(t)
            olcek = abs(_sayi(t.get("entry_price")) - _sayi(_skor_sozluk(t).get("sl0") or t.get("sl_price")))
            _ref_olcek[i] = (ref, olcek if olcek > 0 else (ref or 1.0))
        ref, olcek = _ref_olcek[i]
        return 0.0 if ref is None else abs(e["tutar"] / e["adet"] - ref) / olcek

    def bos_emir(e) -> bool:
        return abs(e["kalan"] - e["adet"]) <= EPS * max(1.0, e["adet"])

    def kova_ici_duzenle(secilen, havuz):
        """Aynı zaman kovasında açgözlü seçilen çiftleri (secilen) YALNIZ KENDİ işlem ve emirleri arasında, bu
        kovadaki aday çiftlerle (havuz) yeniden dağıt: Σ fiyat terimi en küçük; eşitlikte açgözlü seçim korunur.
        Eşleşen işlem/emir kümesi ve çift sayısı DEĞİŞMEZ (çift sayısı en büyüklenmez). Açgözlü 'en yakın fiyat
        çifti' çöküşte iki stopun kaydığı durumda (her ikisi aynı döngüde yazılmış) çapraz çifti seçerdi."""
        isl, emr = {a[3] for a, _ in secilen}, {id(e) for _, e in secilen}
        aday = [(a, e) for a, e in havuz if a[3] in isl and id(e) in emr]
        ana = {}

        def kok(x):
            while ana.setdefault(x, x) != x:
                ana[x] = ana[ana[x]]
                x = ana[x]
            return x

        for a, e in aday:
            u, v = kok(("i", a[3])), kok(("e", id(e)))
            if u != v:
                ana[u] = v
        bilesen = defaultdict(list)
        for a, e in aday:
            bilesen[kok(("i", a[3]))].append((a, e))
        secili = {(a[3], id(e)) for a, e in secilen}
        out = []
        for grup in bilesen.values():
            I = sorted({a[3] for a, _ in grup})
            E = sorted({id(e): e for _, e in grup}.values(), key=lambda e: (e["ilk"], e["oid"]))
            n = len(I)
            assert n == len(E)                            # açgözlü seçim bileşende tam eşleşmedir
            if n == 1:
                out += [c for c in grup if (c[0][3], id(c[1])) in secili]
                continue
            ri, rj = {i: r for r, i in enumerate(I)}, {id(e): s for s, e in enumerate(E)}
            # sözlüksel tam sayı maliyet: (Σ fiyat terimi @1e-9 R, açgözlü seçimden sapan çift sayısı)
            mal = {(ri[a[3]], rj[id(e)]): (int(round(a[1] * 1e9)) * (n + 1) + ((a[3], id(e)) not in secili), (a, e))
                   for a, e in grup}
            yasak = n * max(c for c, _ in mal.values()) + 1         # aday olmayan çift: hiç seçilmez
            sec = _macar([[mal[(r, s)][0] if (r, s) in mal else yasak for s in range(n)] for r in range(n)])
            assert all((r, sec[r]) in mal for r in range(n))
            out += [mal[(r, sec[r])][1] for r in range(n)]
        return out

    def birebir_ata(ciftler):
        """(dt, i, emir ilk, oid, emir) aday çiftlerini birebir ata (emir dokunulmamış, işlem boş olmalı).
        Anahtar (⌊dt / KOVA_MS⌋, fiyat terimi, dt): kovalar sırayla; kovada fiyat, sonra zaman sırasıyla AÇGÖZLÜ
        (her işlem ve emir bir kez), sonra kova_ici_duzenle. Çift sayısı en büyüklenmez: yakın kovada
        eşleşebilen işlem/emir, uzak kovadaki başka bir çifti mümkün kılmak için bırakılmaz (deftere girmemiş
        bir pozisyonun aynı büyüklükteki kapanışı işlemin kendi kapanışını başka kola verdirmesin)."""
        kovalar = defaultdict(list)
        for dt, i, ilk, oid, e in ciftler:
            kv = int(dt) // KOVA_MS
            kovalar[kv].append(((kv, fiyat_terimi(i, e), dt, i, ilk, oid), e))
        for kv in sorted(kovalar):
            havuz = sorted((c for c in kovalar[kv] if not cikacak[c[0][3]]["paylar"] and bos_emir(c[1])),
                           key=lambda c: c[0])
            secilen, ki, ke = [], set(), set()
            for a, e in havuz:
                if a[3] not in ki and id(e) not in ke:
                    ki.add(a[3])
                    ke.add(id(e))
                    secilen.append((a, e))
            for a, e in kova_ici_duzenle(secilen, havuz):
                k = cikacak[a[3]]
                pay_al(k, e, min(e["kalan"], k["giris"]["adet"]))
                k["uzak_birebir"] = a[2] > CIKIS_TERCIH_MS

    # 3a) Birebir (yakın): miktarı işleminkiyle %2 tutan, defter çıkışına ≤15 dk kapanış emri (kova içinde fiyat)
    birebir_ata([(dt, i, e["ilk"], e["oid"], e) for i, k in enumerate(cikacak)
                 for dt, e in adaylar(k, CIKIS_TERCIH_MS) if _miktar_tutar(e["adet"], k["giris"]["adet"])])
    # 3a') Birebir (uzak, ≤6 sa): defter çıkışı GEÇ yazılmış olabilir — bot kapalıyken tetiklenen stoplar
    #      yeniden başlatmada mutabakatla kaydedilir ve exit_time = kayıt anıdır (main.py, execution.py
    #      log_trade_close: datetime.now()). O zaman hiçbir kapanış emri ≤15 dk içinde değildir ve 3b'nin
    #      'en yakın emir' açgözlülüğü aynı bacaktaki kolların emirlerini birbirine verir. Her işlemin kendi
    #      büyüklüğünde emri varsa birebir eşlenir (birebir_ata). Burada miktar AYNI olmalı (UZAK_MIKTAR_TOL):
    #      %2 ile, defter saati doğru bir işlem (kapanışı yakındaki birleşik emir) 5 sa uzaktaki başka iki kolun
    #      birleşik emrini (ör. 1950+50 = 2000 ~ 1970) 'birebir' sanıp alırdı.
    #      KORUMA: defter çıkışının ≤15 dk yakınında işlemi karşılayacak kapanış miktarı varsa ve bu miktar, o
    #      emirleri ≤6 sa aday olarak görebilen TÜM boştaki işlemlerin talebine yetiyorsa (çekişme yok) defter
    #      saati güvenilir sayılır: işlemin gerçek kapanışı oradaki (birebir olmayan, ör. bacağı kapatan)
    #      emirdir; uzaktaki aynı büyüklükte bir emir (deftere girmemiş/eşleşmemiş bir pozisyonun kapanışı)
    #      ALINMAZ — 3b'ye kalır. Talep yalnız 'yakın görenler' olsaydı, birleşik kapanışın sahipleri defter
    #      saatleri 15–30 dk kayık diye sayılmaz ve işlem 22 dk uzaktaki kendi emri yerine onlarınkini alırdı.
    #      Aynı büyüklükte kollar (bu turda miktar AYNI; 3a'da %2) aynı emirlere aday olduğunda birebir_ata
    #      zamanı 150 sn'lik kovalarla okur: emir iki işleme de aynı kovada uzaksa (ör. yeniden başlatmada
    #      ikisi aynı döngüde yazıldı) defter çıkış/stop fiyatı ayırır; kovalar farklıysa zaman kazanır.
    bos = [i for i, k in enumerate(cikacak) if not k["paylar"]]
    aday_6s = {i: {id(e) for _, e in adaylar(cikacak[i], CIKIS_AZAMI_MS)} for i in bos}

    def yakin_guvenilir(i) -> bool:
        ys = [e for _, e in adaylar(cikacak[i], CIKIS_TERCIH_MS)]
        arz = sum(e["kalan"] for e in ys)
        if arz < (1 - MIKTAR_TOL) * cikacak[i]["giris"]["adet"]:
            return False
        kim = {id(e) for e in ys}
        talep = sum(cikacak[j]["giris"]["adet"] for j in bos if aday_6s[j] & kim)
        return arz >= (1 - MIKTAR_TOL) * talep

    birebir_ata([(dt, i, e["ilk"], e["oid"], e) for i, k in enumerate(cikacak)
                 if not k["paylar"] and not yakin_guvenilir(i)
                 for dt, e in adaylar(k, CIKIS_AZAMI_MS)
                 if dt > CIKIS_TERCIH_MS and _miktar_tutar(e["adet"], k["giris"]["adet"], UZAK_MIKTAR_TOL)])
    # 3b) Kalanlar: |emir − defter çıkışı| sırasıyla (≤15 dk öncelikli, en fazla 6 sa) tüket, gerekirse BÖL
    for k in sorted((k for k in cikacak if not k["paylar"]), key=lambda k: (k["c"], k["g"])):
        q = k["giris"]["adet"]
        gerek = q
        for dt, e in sorted(adaylar(k, CIKIS_AZAMI_MS),
                            key=lambda a: (a[0] > CIKIS_TERCIH_MS, a[0], a[1]["ilk"], a[1]["oid"])):
            if gerek <= MIKTAR_TOL * q:
                break
            al = min(e["kalan"], gerek)
            pay_al(k, e, al)
            gerek -= al
        if gerek > MIKTAR_TOL * q:                  # karşılanamadı → geri al, tahmin etme
            k["kapsanan"] = q - gerek
            for p in k["paylar"]:
                p["emir"]["kalan"] += p["adet"]
                p["emir"]["paylar"] = [x for x in p["emir"]["paylar"] if x is not p]   # kimlikle (== değil)
            k["paylar"] = []

    # 4) Funding: o anda o bacakta açık tüm işlemlere baz miktarla orantılı
    katilimci = defaultdict(list)    # (sembol, bacak) → [(giriş ms, miktar, [(kapanış ms, miktar)], k)]
    for k in K:
        s = k["t"]["symbol"]
        if k["acik"]:
            g = k["giris"]["ilk"] if k["giris"] else k["g"]
            q = k["giris"]["adet"] if k["giris"] else float(k["t"]["quantity"] or 0)
            katilimci[(s, k["bacak"])].append((g, q, [], k))
        elif k["giris"] is not None and k["paylar"]:
            katilimci[(s, k["bacak"])].append((k["giris"]["ilk"], sum(p["adet"] for p in k["paylar"]),
                                               [(p["emir"]["ilk"], p["adet"]) for p in k["paylar"]], k))
        elif k["giris"] is not None:                # çıkışı karşılanamadı ama pozisyon gerçekti
            katilimci[(s, k["bacak"])].append((k["giris"]["ilk"], k["giris"]["adet"], [(k["c"], k["giris"]["adet"])], k))
        else:                                       # girişi bulunamayan kapanmış işlem / yarım yazılmış satır:
            ql = float(k["t"]["quantity"] or 0)     # pozisyon gerçekti → defter giriş→çıkış ve defter miktarı
            katilimci[(s, k["bacak"])].append((k["g"], ql, [(k["c"], ql)], k))
    for k in K:
        k["funding"] = 0.0
    # 'sahipsiz' (o anda açık defter işlemi yok) yalnız kapanmış işlemlerin kapsadığı aralıkta sayılır;
    # sayfalamanın getirdiği daha eski / daha yeni kayıtlar tanıyı şişirmesin
    f_lo = min((k["g"] for k in K if not k["acik"] and not k["yarim"]), default=0)
    f_hi = max((k["c"] for k in K if not k["acik"] and not k["yarim"]), default=0)
    f_dagitilan = f_sahipsiz = 0
    f_sahipsiz_usdt = 0.0
    for s, fs in fon.items():
        for f in fs:
            ts = int(f.get("timestamp") or 0)
            tutar = float(f.get("amount") or 0)
            pt = str((f.get("info") or {}).get("positionType") or "")
            bacaklar = ("long",) if pt == "1" else ("short",) if pt == "2" else ("long", "short")
            agir = []
            for b in bacaklar:
                for g, q, cik, k in katilimci.get((s, b), []):
                    if g >= ts:
                        continue
                    w = q - sum(a for c, a in cik if c < ts)
                    if w > EPS * max(1.0, q):
                        agir.append((w, k))
            top = sum(w for w, _ in agir)
            if top <= 0:
                if f_lo <= ts <= f_hi:
                    f_sahipsiz += 1
                    f_sahipsiz_usdt += tutar
                continue
            f_dagitilan += 1
            for w, k in agir:
                k["funding"] += tutar * w / top

    # 5) Satırlar
    satirlar, eslesmeyen = [], []
    for k in K:
        if k["acik"] or k["yarim"]:
            continue
        t = k["t"]
        sl = EU._skor(t).get("sl0") or t["sl_price"]
        risk = abs(t["entry_price"] - sl) * t["quantity"]
        kol = EU.kol_adi(t.get("strategy_scores"))
        temel = dict(kol=kol, id=t.get("id"), symbol=t["symbol"], side=t["side"], entry_time=t["entry_time"],
                     defter=t["pnl_usdt"], yol=k["yol"])
        if k["giris"] is None or not k["paylar"]:
            if k["giris"] is None:
                bos = [e for e in acilis.get((t["symbol"], k["bacak"]), []) if not e.get("_kullanan")]
                if bos:
                    e = min(bos, key=lambda e: abs(e["ilk"] - k["g"]))
                    q = float(t["quantity"] or 0)
                    neden = (f"giriş emri yok (kimlik bulunamadı; en yakın boş açılış emri "
                             f"{(e['ilk'] - k['g']) / 60_000:+.0f} dk, miktar oranı "
                             f"{(e['adet'] / q if q else float('nan')):.2f})")
                else:
                    neden = "giriş emri yok (bu bacakta boş açılış emri yok)"
            else:
                neden = (f"çıkış karşılanamadı (miktarın %{100 * k.get('kapsanan', 0) / k['giris']['adet']:.0f}'i "
                         f"±{CIKIS_AZAMI_MS // 3_600_000} sa içinde)")
            satirlar.append(dict(temel, eslesti=False, cikis=k["c"], neden=neden))
            eslesmeyen.append((t, neden))
            continue
        gi = k["giris"]
        kapsanan = sum(p["adet"] for p in k["paylar"])
        yon = 1.0 if k["bacak"] == "long" else -1.0
        giris_tutar = gi["tutar"] * kapsanan / gi["adet"]
        cikis_tutar = sum(p["emir"]["tutar"] * p["adet"] / p["emir"]["adet"] for p in k["paylar"])
        # giriş ücreti de tutar gibi KAPSANAN miktarla orantılı: kapanışı bulunmayan kısmın (ör. %98–100 kapsama)
        # giriş tutarı hesaba girmiyorsa ücreti de girmemeli
        ucret = (gi["ucret"] * kapsanan / gi["adet"]
                 + sum(p["emir"]["ucret"] * p["adet"] / p["emir"]["adet"] for p in k["paylar"]))
        net = yon * (cikis_tutar - giris_tutar) - ucret + k["funding"]
        ana = max(k["paylar"], key=lambda p: p["adet"])["emir"]
        satirlar.append(dict(temel, eslesti=True, gercek=net, ucret=ucret, funding=k["funding"],
                             R=net / risk if risk > 0 else None, giris_fark_dk=(gi["ilk"] - k["g"]) / 60_000,
                             cikis_fark_dk=(ana["ilk"] - k["c"]) / 60_000,
                             cikis=max(p["emir"]["son"] for p in k["paylar"]),
                             adet=kapsanan, emirler=[p["emir"]["oid"] for p in k["paylar"]]))

    kap = [e for lst in kapanis.values() for e in lst]
    kapali_K = [k for k in K if not k["acik"] and not k["yarim"]]
    tani = dict(
        acilis_emri=sum(len(v) for v in acilis.values()), kapanis_emri=len(kap),
        kimlik=sum(1 for k in kapali_K if k["yol"] == "kimlik"),
        yedek=sum(1 for k in kapali_K if k["yol"] == "yedek"),
        giris_yok=sum(1 for k in kapali_K if k["giris"] is None),
        cikis_yok=sum(1 for k in kapali_K if k["giris"] is not None and not k["paylar"]),
        bolunen=sum(1 for e in kap if len(e["paylar"]) >= 2),
        uzak_birebir=sum(1 for k in kapali_K if k.get("uzak_birebir")),
        kismi_kalan=sum(1 for e in kap if e["paylar"] and e["kalan"] > MIKTAR_TOL * e["adet"]),
        hic_kullanilmayan=sum(1 for e in kap if not e["paylar"]),
        kapanis_adet=sum(e["adet"] for e in kap), dagitilan_adet=sum(e["adet"] - e["kalan"] for e in kap),
        f_dagitilan=f_dagitilan, f_sahipsiz=f_sahipsiz, f_sahipsiz_usdt=f_sahipsiz_usdt,
        acik_islem=sum(1 for k in K if k["acik"]), yarim_islem=sum(1 for k in K if k["yarim"]),
    )
    return dict(satirlar=satirlar, eslesmeyen=eslesmeyen, tani=tani, emirler=emirler)


def yazdir(sonuc: dict, islemler: list[dict], dolum: dict, fon: dict, hata: dict) -> None:
    satirlar, eslesmeyen, tani = sonuc["satirlar"], sonuc["eslesmeyen"], sonuc["tani"]
    print("=" * 100)
    print(f"  GERÇEK KOL KARNESİ — borsanın dolum, ücret ve funding kayıtlarından · {len(islemler)} canlı işlem")
    print("=" * 100)
    print(f"{'kol':<12}{'eşleşen':>8}{'defter USDT':>13}{'GERÇEK USDT':>13}{'fark':>9}{'gerçek ort R':>14}"
          f"{'%95 aralık':>18}{'ücret':>8}{'funding':>9}")
    gr = defaultdict(list)
    for x in satirlar:
        gr[x["kol"]].append(x)
    top_d = top_g = 0.0
    for kol, xs in sorted(gr.items(), key=lambda kv: -sum(x.get("gercek", 0) for x in kv[1] if x["eslesti"])):
        e = [x for x in xs if x["eslesti"]]
        d = sum(x["defter"] for x in e)
        g = sum(x["gercek"] for x in e)
        rs = [x["R"] for x in e if x["R"] is not None]
        lo, hi = guven(rs)
        top_d += d
        top_g += g
        ar = f"[{lo:+.2f}, {hi:+.2f}]" if np.isfinite(lo) else "—"
        print(f"{kol:<12}{len(e):>4}/{len(xs):<3}{d:>13.2f}{g:>13.2f}{g - d:>9.2f}"
              f"{(np.mean(rs) if rs else float('nan')):>+14.2f}{ar:>18}"
              f"{sum(x['ucret'] for x in e):>8.2f}{sum(x['funding'] for x in e):>9.2f}")
    print("-" * 100)
    print(f"(okunan dolum: {sum(len(v) for v in dolum.values())}, funding kaydı: {sum(len(v) for v in fon.values())})")
    print(f"{'TOPLAM':<12}{sum(x['eslesti'] for x in satirlar):>4}/{len(satirlar):<3}{top_d:>13.2f}{top_g:>13.2f}"
          f"{top_g - top_d:>9.2f}")
    oran = 100 * tani["dagitilan_adet"] / tani["kapanis_adet"] if tani["kapanis_adet"] > 0 else 0.0
    print(f"(borsadan kurulan emir: {tani['acilis_emri']} açılış, {tani['kapanis_emri']} kapanış · kapanış "
          f"miktarının %{oran:.0f}'i işlemlere dağıtıldı)")
    print(f"(eşleşme: giriş {tani['kimlik']} emir kimliğiyle, {tani['yedek']} yedek (zaman+miktar), "
          f"{tani['giris_yok']} bulunamadı · çıkışı karşılanamayan {tani['cikis_yok']} · bölünen kapanış emri "
          f"{tani['bolunen']} (2+ işleme paylaştırıldı))")
    if tani["uzak_birebir"]:
        print(f"(çıkış: {tani['uzak_birebir']} işlemin kapanış emri defter çıkışından 15 dk'dan uzakta, birebir "
              f"miktarla eşlendi — defter çıkışı geç yazılmış, ör. bot kapalıyken tetiklenen stop)")
    # SON 7 GÜN — çıkışı (borsadaki son dolum) son 7 günde olan işlemler, kol kol
    sinir = int(datetime.now().timestamp() * 1000) - 7 * 86_400_000
    yakin = [x for x in satirlar if x.get("cikis", 0) >= sinir]
    print(f"\nSON 7 GÜN (kapanan işlem: {len(yakin)})")
    if yakin:
        print(f"{'kol':<12}{'işlem':>6}{'GERÇEK USDT':>13}{'defter USDT':>13}")
        g7 = defaultdict(list)
        for x in yakin:
            g7[x["kol"]].append(x)
        for kol, xs in sorted(g7.items(), key=lambda kv: -sum(x.get("gercek", 0) for x in kv[1])):
            e = [x for x in xs if x["eslesti"]]
            esl = "" if len(e) == len(xs) else f"  ({len(xs) - len(e)} eşleşmedi)"
            print(f"{kol:<12}{len(xs):>6}{sum(x['gercek'] for x in e):>13.2f}{sum(x['defter'] for x in xs):>13.2f}{esl}")
        print(f"{'TOPLAM':<12}{len(yakin):>6}{sum(x.get('gercek', 0) for x in yakin):>13.2f}"
              f"{sum(x['defter'] for x in yakin):>13.2f}")
    else:
        print("  bu hafta kapanan işlem yok")
    if not any(sonuc["emirler"].values()) and any(dolum.values()):
        x = next(d for ds in dolum.values() for d in ds)
        print(f"(uyarı: dolumlarda yön kodu okunamadı; info alanları: {sorted((x.get('info') or {}).keys())})")
    fk = [x["giris_fark_dk"] for x in satirlar if x["eslesti"]]
    if fk:
        print(f"(defter girişi ile borsa ilk dolumu arasındaki fark, dakika: medyan {np.median(fk):+.1f}, "
              f"en büyük {max(fk, key=abs):+.1f})")
    ck = [x["cikis_fark_dk"] for x in satirlar if x["eslesti"]]
    if ck:
        print(f"(defter çıkışı ile atanan kapanış emri arasındaki fark, dakika: medyan {np.median(ck):+.1f}, "
              f"en büyük {max(ck, key=abs):+.1f})")
    if tani["f_sahipsiz"] or tani["acik_islem"] or tani["yarim_islem"] or tani["giris_yok"]:
        print(f"(funding: {tani['f_dagitilan']} kayıt işlemlere paylaştırıldı, {tani['f_sahipsiz']} kayıt o anda "
              f"açık defter işlemi yokken ({tani['f_sahipsiz_usdt']:+.2f} USDT, sayılmadı) · payda {tani['acik_islem']} "
              f"açık işlemi, {tani['yarim_islem']} yarım yazılmış satırı ve girişi bulunamayan {tani['giris_yok']} "
              f"işlemi de içerir; payları raporlanmaz)")
    if eslesmeyen:
        print("\nEşleşmeyenlerden örnekler (neden):")
        for t, neden in eslesmeyen[:5]:
            print(f"  {t['symbol']:<16}{t['side']:<6}giriş {t['entry_time'][:19]}  {neden}")
    if hata:
        print("\n⚠ Bazı sembollerde okuma hatası (o sembolün işlemleri eşleşmemiş olabilir):")
        for s, (e1, e2) in hata.items():
            print(f"  {s}: dolum={e1} funding={e2}")
    print("\nNot: 'GERÇEK' = işlemin kendi giriş emri ve ona miktarla paylaştırılan kapanış emirleri: satış tutarı −")
    print("alış tutarı − gerçek ücret payı + gerçek funding payı (borsa kaydı). Eşleşmeyen işlemler toplama katılmaz.")
    print("Borsa equity − yatırılan ile kıyaslarken açık pozisyonun uPnL'ini ekleyin.")


async def main():
    cfg = load_config()
    if cfg.exchange.paper_mode:
        print("PAPER modda — çalıştırılmadı.")
        return
    islemler, aciklar, tum_idler = defter_oku(cfg.db_path)
    if not islemler:
        print("Canlı kapanmış işlem yok.")
        return
    import ccxt.pro as ccxtpro
    ex = ccxtpro.mexc({"apiKey": cfg.exchange.api_key, "secret": cfg.exchange.api_secret,
                       "options": {"defaultType": "swap", "defaultSubType": "linear"}, "enableRateLimit": True})
    ex.has["fetchCurrencies"] = False
    try:
        await ex.load_markets()
        bas = min(ms(t["entry_time"]) for t in islemler) - 86_400_000
        semboller = sorted({t["symbol"] for t in islemler})
        dolum, fon, hata = {}, {}, {}
        bit = max(ms(t["exit_time"]) for t in islemler) + 86_400_000
        for s in semboller:
            d, e1 = await dolumlar(ex, s, bas, bit)
            f, e2 = await fundingler(ex, s, bas) if hasattr(ex, "fetch_funding_history") else ([], "yok")
            dolum[s], fon[s] = sorted(d, key=lambda x: x["timestamp"]), f
            if e1 or e2:
                hata[s] = (e1, e2)
            cs = float((ex.market(s).get("contractSize") or 1))
            for x in dolum[s]:
                x["_cs"] = cs
    finally:
        await ex.close()

    sonuc = hesapla(islemler, aciklar, dolum, fon, tum_idler)
    yazdir(sonuc, islemler, dolum, fon, hata)
    return sonuc


async def telegram_gonder(metin: str) -> None:
    """Çıktıyı Telegram'a eş genişlikli yazıyla gönderir (haftalık zamanlanmış görev için: --telegram)."""
    import html
    import aiohttp
    tg = load_config().telegram
    if not (tg.token and tg.chat_id):
        print("Telegram ayarı yok (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID) — gönderilmedi.")
        return
    satirlar, parca, parcalar = metin.splitlines(), "", []
    for sat in satirlar:                       # Telegram sınırı 4096 karakter (kaçışlı metin üzerinden)
        sat = html.escape(sat)[:3500]
        if len(parca) + len(sat) + 1 > 3500:
            parcalar.append(parca)
            parca = ""
        parca += sat + "\n"
    if parca.strip():
        parcalar.append(parca)
    url = f"https://api.telegram.org/bot{tg.token}/sendMessage"
    async with aiohttp.ClientSession() as oturum:
        for pr in parcalar:
            async with oturum.post(url, json={"chat_id": tg.chat_id, "parse_mode": "HTML",
                                              "text": f"<pre>{pr}</pre>"}) as r:
                if r.status != 200:
                    print(f"Telegram gönderimi başarısız: HTTP {r.status}")


async def _telegramli() -> None:
    import contextlib
    import io
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon):
            await main()
    except Exception as e:                     # karne hata verirse bunu da bildir
        tampon.write(f"\n⚠ Gerçek karne çalışırken hata: {type(e).__name__}: {e}\n")
    metin = tampon.getvalue()
    print(metin)
    await telegram_gonder("📊 HAFTALIK GERÇEK KARNE\n" + metin)


if __name__ == "__main__":
    asyncio.run(_telegramli() if "--telegram" in sys.argv else main())
