"""Aylık kâr hedefi durdurması — EK (yalnız keşif): bot + trend (B0, %1) ortak sermaye motoru.
ÖN KAYIT: /home/user/sweep/research/aylik_hedef/ON_KAYIT.md (eşikler: TABAN / H10 / H15; değiştirilmez).
Kural: (motorun hesap değeri [trend açık PnL dahil] / ayın ilk adımındaki hesap değeri − 1) ≥ eşik olunca
o UTC ayın kalanında yeni bot girişleri + yeni trend girişleri + piramit ekleri engellenir (ay içi kilit).
Motor: research/trend_gelistirme/birlesik.py MotorBirlesik (repo DEĞİŞTİRİLMEZ, alt sınıf burada).
Bot işlemleri: aylik_tablo.py ile aynı kurulum, --kalibre YOK.
Çalıştırma: cd /home/user/sweep && PYTHONPATH=/home/user/sweep PYTHONDONTWRITEBYTECODE=1 python3 -B <bu dosya>
"""
import json, os, sqlite3, sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/user/sweep")
from research.trend_gelistirme import birlesik as BL
from research.trend_gelistirme.motor import H4
from research.trend_gelistirme.veri import yukle, BOT12
from research.trend_gelistirme.kos import MAL

OUT = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/aylik_hedef_T"
DB = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad/ikiz_kanit/ikiz_gercek.db"
SON = BL.ms("2026-07-18")
STRAT = {"donchian", "mean_rev"}
C0 = 10_000.0
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def ms_of(s):
    t = pd.Timestamp(s)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return int((t - EPOCH) // pd.Timedelta(milliseconds=1))


def bot_islemleri(db):
    """aylik_tablo.py:bot_islemleri ile aynı (KALIBRE=False); ek: strateji filtresi + squeeze yokluğu assert."""
    c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    rows = c.execute("select entry_price,quantity,entry_time,exit_time,pnl_usdt,strategy_scores from trades "
                     "order by entry_time").fetchall()
    c.close()
    tum_strat = {json.loads(sc or "{}").get("strategy") for *_, sc in rows}
    assert "squeeze" not in tum_strat, tum_strat
    out = []
    for E, q, et, xt, pnl, sc in rows:
        j = json.loads(sc or "{}")
        sl0 = float(j.get("sl0") or 0); risk = abs(E - sl0) * q
        if risk <= 0 or pnl is None:
            continue
        kol = j.get("strategy")
        if kol not in STRAT:
            continue
        R = pnl / risk
        out.append(dict(a=ms_of(et), z=ms_of(xt), R=R, notional=E * q, pnl=R * risk, kol=kol))
    df = pd.DataFrame(out).sort_values("a").reset_index(drop=True)
    assert set(df.kol) <= STRAT and "squeeze" not in set(df.kol)
    kap = df.sort_values("z")[["z", "pnl"]].to_numpy()
    df["ikiz_bakiye"] = [10_000 + kap[kap[:, 0] <= a, 1].sum() for a in df.a]
    df["teminat_oran"] = (df.notional / df.ikiz_bakiye) / 10.0
    df = df[df.kol != "squeeze"]
    return df[(df.a >= BL.A) & (df.z < SON)].reset_index(drop=True)


def ay_of(t_ms):
    d = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
    return (d.year, d.month)


class MotorAylikHedef(BL.MotorBirlesik):
    """Ay içi hedef kilidi. esik=None → TABAN (MotorBirlesik ile birebir aynı olmalı)."""

    def __init__(self, *a, esik=None, kilit=True, **k):
        super().__init__(*a, **k)
        self.esik, self.kilit = esik, kilit
        self._ay = None
        self._ay_bas = None
        self._tetik = False
        self._engel = False
        self.ay_bas_deger = {}       # ay -> ayın ilk adımındaki hesap değeri (00:00 UTC gün 1'e taşınan)
        self.tetik_ilk = {}          # ay -> ilk tetik anı (adım t, ms) ve o andaki oran
        self.engelli_adim = 0
        self.hedef_bot_atlanan = []  # (a, R, kol)

    def _lot_ac(self, p, coin, tur, t, O, deger):
        if self._engel:
            return None, "AYLIK_HEDEF"
        return super()._lot_ac(p, coin, tur, t, O, deger)

    def _adim(self, t):
        deger0 = self.son_deger      # motorun o anki hesap değeri (trend açık PnL dahil, bot gerçekleşmiş)
        ay = ay_of(t)
        if ay != self._ay:
            self._ay, self._ay_bas, self._tetik = ay, deger0, False
            self.ay_bas_deger[ay] = deger0
        engel = False
        if self.esik is not None:
            oran = deger0 / self._ay_bas - 1
            ust = oran >= self.esik
            if ust and ay not in self.tetik_ilk:
                self.tetik_ilk[ay] = (int(t), float(oran))
            if self.kilit:
                self._tetik = self._tetik or ust
                engel = self._tetik
            else:
                engel = ust
        if engel:
            self.engelli_adim += 1
            T = t + H4
            # Bu adımın bot girişlerini kural gereği tüket (MotorBirlesik döngüsü onları görmesin)
            while self.bi < len(self.bot) and self.bot.a[self.bi] < T:
                r = self.bot.iloc[self.bi]
                self.bi += 1
                if r.a < t:          # temel motor da bunları sessizce atlar
                    continue
                self.hedef_bot_atlanan.append((int(r.a), float(r.R), str(r.kol)))
        self._engel = engel
        try:
            super()._adim(t)
        finally:
            self._engel = False


def ay_sonu(seri_df, etiket="bar_basi"):
    """Ay sonu değerleri. etiket='bar_basi': T anındaki değer, barın başladığı ayın (t=T−4H) sonu sayılır
    (yani ay sonu = sonraki ayın 1'i 00:00 UTC'deki değer = sonraki ayın 'ay başı' değeri; kural ile tutarlı).
    etiket='yardimci': aylik_tablo.py'deki gibi T'nin ayı."""
    tt = seri_df.t - (H4 if etiket == "bar_basi" else 0)
    ts = pd.to_datetime(tt, unit="ms", utc=True)
    ay = seri_df.deger.set_axis(ts).resample("ME").last().ffill()
    bas = pd.Series([C0], index=[ay.index[0] - pd.offsets.MonthEnd(1)])
    return pd.concat([bas, ay])


def aylik_tablo(s):
    yuzde = s.pct_change().dropna() * 100
    tab = yuzde.groupby([yuzde.index.year, yuzde.index.month]).first().unstack()
    tab["YIL"] = [(1 + yuzde[yuzde.index.year == y] / 100).prod() * 100 - 100 for y in tab.index]
    return yuzde, tab


def mdd(s):
    v = s / C0
    return float((1 - v / v.cummax()).max() * 100)


def main():
    bot = bot_islemleri(DB)
    veri, _ = yukle(BOT12)
    prof = MAL["NORMAL"]
    sonuc, tablolar = {}, {}

    # Doğrulama: alt sınıf esik=None ≡ MotorBirlesik
    ref = BL.MotorBirlesik(veri, "ETH", "B0", prof, t_bas=BL.A, t_bit=SON, bot=bot).kos()
    ref_seri = pd.DataFrame(ref.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])

    for ad, esik in (("TABAN", None), ("H10", 0.10), ("H15", 0.15)):
        m = MotorAylikHedef(veri, "ETH", "B0", prof, t_bas=BL.A, t_bit=SON, bot=bot, esik=esik).kos()
        seri = pd.DataFrame(m.seri, columns=["t", "deger", "acik_poz", "acik_risk", "teminat"])
        if ad == "TABAN":
            assert len(seri) == len(ref_seri) and np.array_equal(seri.to_numpy(), ref_seri.to_numpy()), "TABAN != MotorBirlesik"
            assert m.bot_alinan == ref.bot_alinan and m.bot_atlanan == ref.bot_atlanan
        seri.to_csv(os.path.join(OUT, f"seri_{ad}.csv"), index=False)
        pd.DataFrame(m.islemler).to_csv(os.path.join(OUT, f"trend_islemler_{ad}.csv"), index=False)
        s = ay_sonu(seri)
        yuzde, tab = aylik_tablo(s)
        tab.round(2).to_csv(os.path.join(OUT, f"aylik_{ad}.csv"))
        tablolar[ad] = tab
        olay = pd.Series([o["tur"] for o in m.olaylar]).value_counts().to_dict() if m.olaylar else {}
        tetik = {f"{y}-{mo:02d}": dict(ilk_tetik_utc=str(pd.Timestamp(tt, unit="ms", tz="UTC")), oran_pct=round(o * 100, 2),
                                       ay_getiri_pct=round(float(yuzde.get(pd.Timestamp(year=y, month=mo, day=1, tz="UTC") + pd.offsets.MonthEnd(0), np.nan)), 2))
                 for (y, mo), (tt, o) in sorted(m.tetik_ilk.items())}
        hb = m.hedef_bot_atlanan
        # ay başı değeri kontrolü: kuraldaki ay başı = ay sonu serisindeki önceki ay sonu (bar_basi etiketi)
        kontrol = []
        for (y, mo), v in m.ay_bas_deger.items():
            k = pd.Timestamp(year=y, month=mo, day=1, tz="UTC") - pd.Timedelta(days=1)
            k = k + pd.offsets.MonthEnd(0)
            if k in s.index and pd.Timestamp(year=y, month=mo, day=1, tz="UTC") >= pd.Timestamp(BL.A, unit="ms", tz="UTC").replace(day=1):
                kontrol.append(abs(s[k] - v))
        sonuc[ad] = dict(
            esik=esik, son_carpan=float(seri.deger.iloc[-1] / C0),
            mdd_ay_sonu_pct=mdd(s),
            mdd_4h_seri_pct=float(((1 - seri.deger / np.maximum.accumulate(np.r_[C0, seri.deger.to_numpy()])[1:]).max()) * 100),
            tetik_ay_sayisi=len(m.tetik_ilk), tetik_aylar=tetik, engelli_4h_adim=m.engelli_adim,
            bot_islem_havuzu=len(bot), bot_alinan=m.bot_alinan, bot_atlanan_teminat=m.bot_atlanan,
            bot_atlanan_hedef=len(hb), bot_atlanan_hedef_R_toplam=float(sum(x[1] for x in hb)),
            bot_atlanan_hedef_kol=pd.Series([x[2] for x in hb]).value_counts().to_dict() if hb else {},
            trend_islem=len(m.islemler), trend_pnl=float(sum(x["pnl"] for x in m.islemler)),
            trend_giris_engel_hedef=int(olay.get("GIRIS_ATLANDI_AYLIK_HEDEF", 0)),
            trend_ek_engel_hedef=int(olay.get("EK_ATLANDI_AYLIK_HEDEF", 0)),
            olaylar=olay, yillik_pct={int(k): round(float(v), 2) for k, v in tab["YIL"].items()},
            ay_bas_kontrol_maks_fark=float(max(kontrol)) if kontrol else None,
            ay_sonu_degerleri={str(k.date()): round(float(v), 2) for k, v in s.items()})
        print(f"\n=== {ad} (eşik {esik}) · son x{sonuc[ad]['son_carpan']:.3f} · maxDD(ay sonu) {sonuc[ad]['mdd_ay_sonu_pct']:.2f}% "
              f"· tetik ay {len(m.tetik_ilk)} · bot hedef-atlanan {len(hb)} (ΣR {sonuc[ad]['bot_atlanan_hedef_R_toplam']:.2f}) "
              f"· trend giriş/ek engeli {sonuc[ad]['trend_giris_engel_hedef']}/{sonuc[ad]['trend_ek_engel_hedef']}")
        print(tab.round(1).to_string())

    # Yardımcı (aylik_tablo.py) etiketiyle TABAN — eski aylik_NORMAL.csv ile karşılaştırma için
    s_y = ay_sonu(ref_seri, etiket="yardimci")
    _, tab_y = aylik_tablo(s_y)
    tab_y.round(2).to_csv(os.path.join(OUT, "aylik_TABAN_yardimci_etiket.csv"))
    sonuc["_TABAN_yardimci_etiket"] = dict(son_carpan=float(ref_seri.deger.iloc[-1] / C0), mdd_ay_sonu_pct=mdd(s_y))
    sonuc["_kurulum"] = dict(db=DB, kalibre=False, motor="MotorBirlesik(veri,'ETH','B0',MAL['NORMAL'],t_bas=BL.A,t_bit=SON,bot=bot)",
                             t_bas=str(pd.Timestamp(BL.A, unit="ms", tz="UTC")), t_bit=str(pd.Timestamp(SON, unit="ms", tz="UTC")),
                             bot_islem=len(bot), bot_kol=bot.kol.value_counts().to_dict(),
                             kilit="ay içi kilit: ilk tetikten ay sonuna kadar", deger="motorun son_deger'i (trend açık PnL dahil; bot açık PnL yok)")
    json.dump(sonuc, open(os.path.join(OUT, "sonuc.json"), "w"), indent=1, ensure_ascii=False, default=str)
    print("\nTABAN yardımcı etiketi (aylik_tablo.py):")
    print(tab_y.round(1).to_string())


if __name__ == "__main__":
    main()
