"""
saglik_kaniti.py — "bot sağlam mı?" sorusunun KANITI. İstatistik değil, SAYIM.

sessizlik.py "4-5 gün sessizlik dağılıma uyuyor" dedi. Bu 'SORUN YOK' DEMEK DEĞİL —
sadece 'sessizlik tek başına kanıt değil' demek. Bu araç farklı bir soru soruyor:

    SON N GÜNDE KAÇ SİNYAL OLUŞMALIYDI?  KAÇ TANESİ AÇILDI?

Eşleşirse bot KANITLANMIŞ şekilde çalışıyor. Eşleşmezse hangi coin / hangi bar
kaçırıldığı ismiyle çıkar. Log'a GÜVENMİYOR: canlı kod direction==0 iken hiçbir
şey yazmıyor, yani boş log "sinyal yok" ile "sinyal yutuldu"yu ayırt etmiyor.
Bu yüzden sinyaller ÜRETİM SINIFLARIYLA sıfırdan yeniden hesaplanıyor.

DÖRT BAĞIMSIZ KONTROL:
  A) AYAR    — canlı .env gerçekten ankorun varsaydığı ayarlar mı?
  B) VERİ    — borsa mumları taze mi? (bayat veri = sessizce kör bot)
  C) SİNYAL  — üretim sınıflarıyla yeniden hesap: son N günde ne oluşmalıydı?
  D) SAYIM   — trades.db'deki GERÇEK girişlerle karşılaştır + açık pozisyon yaşı

⚠ ANKOR VERİSİNE DOKUNMAZ: ccxt'yi doğrudan çağırır, data/ altına HİÇBİR ŞEY
yazmaz (fast_bt._save_cache yoluna hiç girmez).

Kullanım (VPS'te, bot çalışırken güvenli — salt-okunur):
    python3 saglik_kaniti.py            # son 12 gün
    python3 saglik_kaniti.py 20         # son 20 gün
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from indicators import atr as atr_fn, adx as adx_fn
from config import load_config

TF_SAAT = {"1h": 1, "4h": 4}


# ───────────────────────── veri (ankor önbelleğine DOKUNMAZ) ─────────────────
def cek(coin: str, gun: int = 220) -> pd.DataFrame:
    """MEXC vadeli 1h — pencereli. fast_bt.load KULLANMAZ (o 1200 gün çeker ve
    _save_cache yoluna girer). Burada data/ altına hiçbir şey yazılmaz."""
    import ccxt
    ex = ccxt.mexc({"options": {"defaultType": "swap"}})
    sym = f"{coin}/USDT:USDT"
    since = int((datetime.now(timezone.utc) - timedelta(days=gun)).timestamp() * 1000)
    rows = []
    while True:
        b = ex.fetch_ohlcv(sym, "1h", since=since, limit=500)
        if not b:
            break
        rows += b
        if len(b) < 500:
            break
        since = b[-1][0] + 1
    if not rows:
        raise SystemExit(f"{coin}: MEXC vadeli veri çekilemedi ({sym})")
    m = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    m.index = pd.to_datetime(m["ts"], unit="ms", utc=True)
    m = m.drop_duplicates("ts").drop(columns=["ts"]).astype(float)
    return m


def resample(m, tf):
    return m.resample(tf).agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()


# ───────────────────────── C) SİNYAL YENİDEN HESABI ──────────────────────────
def mtf_ok(df_4h, direction, aktif):
    """main.py:_donchian_mtf_ok ile BİREBİR (kapalıysa hep True)."""
    if not aktif:
        return True
    d1d = df_4h.resample("1D").agg({"close": "last"}).dropna()
    if len(d1d) < 20:
        return True
    dema20 = d1d["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    up = float(d1d["close"].iloc[-1]) > float(dema20)
    return (direction == 1 and up) or (direction == -1 and not up)


def adaylar_donchian(coin, m, cfg, bas):
    """Üretim DonchianStrategy + canlı MTF kapısı. occ UYGULANMAZ —
    amaç 'ne oluşmalıydı', 'ne alınabilirdi' değil. Kesişimi D bölümü yapar."""
    from strategies.donchian import DonchianStrategy
    s = DonchianStrategy(channel=cfg.strategy.donchian_channel,
                         rr=cfg.strategy.donchian_rr,
                         sl_atr=cfg.strategy.donchian_sl_atr,
                         ema_trend=cfg.strategy.donchian_ema_trend,
                         buffer_atr=cfg.strategy.donchian_buffer_atr)
    d = resample(m, "4h")
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    idx = d.index
    out = []
    for i in range(260, len(d)):
        if idx[i] < bas:
            continue
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        sub = d.iloc[max(0, i - 259):i + 1]
        sg = s.analyze(sub, float(a))
        if sg.direction == 0:
            continue
        gecti = mtf_ok(sub, sg.direction, cfg.strategy.donchian_mtf_enabled)
        out.append({"coin": coin, "kol": "donchian", "ts": idx[i],
                    "yon": sg.direction, "fiyat": float(d["close"].values[i]),
                    "mtf": gecti})
    return out


def adaylar_squeeze(coin, m, cfg, bas):
    from strategies.squeeze import SqueezeStrategy
    s = SqueezeStrategy(kc_mult=cfg.strategy.squeeze_kc_mult,
                        min_squeeze_bars=cfg.strategy.squeeze_min_bars,
                        sl_atr=cfg.strategy.squeeze_sl_atr,
                        rr=cfg.strategy.squeeze_rr,
                        mtf_filter=cfg.strategy.squeeze_mtf)
    d = resample(m, "1h")
    a_ser = atr_fn(d["high"], d["low"], d["close"], 14).values
    x_ser = adx_fn(d["high"], d["low"], d["close"], 14).values
    idx = d.index
    out = []
    for i in range(260, len(d)):
        if idx[i] < bas:
            continue
        a = a_ser[i]
        if not np.isfinite(a) or a <= 0:
            continue
        xv = x_ser[i] if np.isfinite(x_ser[i]) else 20.0
        if xv <= 20.0:
            continue                      # canlı ADX rejim kapısı
        sub = d.iloc[max(0, i - 119):i + 1]
        sg = s.analyze(sub, float(a))
        if sg.direction == 0:
            continue
        out.append({"coin": coin, "kol": "squeeze", "ts": idx[i],
                    "yon": sg.direction, "fiyat": float(d["close"].values[i]),
                    "mtf": True})
    return out


# ───────────────────────── D) GERÇEK GİRİŞLER ────────────────────────────────
def defter(db_path, bas):
    if not os.path.exists(db_path):
        return None, None
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    q = ("SELECT id,symbol,side,entry_time,exit_time,exit_reason,pnl_usdt,"
         "strategy_scores,is_paper FROM trades WHERE entry_time >= ? ORDER BY entry_time")
    giris = [dict(r) for r in con.execute(q, (bas.isoformat(),))]
    acik = [dict(r) for r in con.execute(
        "SELECT id,symbol,side,entry_time,strategy_scores,is_paper FROM trades "
        "WHERE exit_time IS NULL ORDER BY entry_time")]
    con.close()
    return giris, acik


def _ts(v):
    t = pd.Timestamp(v)
    return t.tz_localize("UTC") if t.tzinfo is None else t


def acik_sayisi(tum, t):
    """t anında AÇIK pozisyon sayısı (MAX_POSITIONS kapısını yeniden kurar)."""
    n = 0
    for g in tum:
        if _ts(g["entry_time"]) <= t and (g.get("exit_time") is None
                                          or _ts(g["exit_time"]) > t):
            n += 1
    return n


def cooldown_aktif(tum, sym, kol, t, limit, dakika):
    """execution.py:271-293 ile aynı mantık: (sleeve:symbol) başına ardışık zarar
    sayacı; limit'e ulaşınca `dakika` kadar cooldown. Kazanç sayacı sıfırlar."""
    if not limit or not dakika:
        return False
    gec = sorted([g for g in tum
                  if g["symbol"] == sym and kol_of(g) == kol
                  and g.get("exit_time") and _ts(g["exit_time"]) <= t],
                 key=lambda g: _ts(g["exit_time"]))
    streak = 0
    bitis = None
    for g in gec:
        if (g.get("pnl_usdt") or 0.0) < 0:
            streak += 1
            if streak >= limit:
                bitis = _ts(g["exit_time"]) + timedelta(minutes=dakika)
        else:
            streak = 0
            bitis = None
    return bool(bitis and bitis > t)


def kol_of(rec):
    try:
        return json.loads(rec["strategy_scores"] or "{}").get("strategy", "?")
    except Exception:
        return "?"


# ───────────────────────────────── ana ───────────────────────────────────────
def main():
    gun = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    simdi = datetime.now(timezone.utc)
    bas = simdi - timedelta(days=gun)
    cfg = load_config()
    print(f"saglik_kaniti.py — son {gun} gün ({bas:%Y-%m-%d %H:%M} → {simdi:%Y-%m-%d %H:%M} UTC)")

    # ── A) AYAR ──────────────────────────────────────────────────────────────
    print(f"\n{'='*76}\nA) CANLI AYAR — ankorun varsaydıklarıyla aynı mı?\n{'='*76}")
    dsym = [s.split("/")[0] for s in (cfg.strategy.donchian_symbols or [])]
    ssym = [s.split("/")[0] for s in (cfg.strategy.squeeze_symbols or [])]
    print(f"  donchian açık={cfg.strategy.donchian_enabled} coinler={dsym}")
    print(f"    channel={cfg.strategy.donchian_channel} ema={cfg.strategy.donchian_ema_trend} "
          f"sl_atr={cfg.strategy.donchian_sl_atr} rr={cfg.strategy.donchian_rr} "
          f"buffer={cfg.strategy.donchian_buffer_atr}")
    print(f"  squeeze  açık={cfg.strategy.squeeze_enabled} coinler={ssym}")
    print(f"  MAX_POSITIONS={cfg.risk.max_positions}  "
          f"CONSEC_LOSS={getattr(cfg.risk,'consecutive_loss_limit','?')}  "
          f"COOLDOWN={getattr(cfg.risk,'cooldown_minutes','?')}dk  "
          f"MAX_CORR_DIR={getattr(cfg.risk,'max_correlated_direction','?')}")
    beklenen = {"donchian_channel": 40, "donchian_ema_trend": 200,
                "donchian_sl_atr": 2.0, "donchian_rr": 2.0, "donchian_buffer_atr": 0.0}
    sapma = [(k, getattr(cfg.strategy, k), v) for k, v in beklenen.items()
             if getattr(cfg.strategy, k) != v]
    if sapma:
        for k, g, b in sapma:
            print(f"  ⚠ SAPMA: {k} canlı={g} ankor={b}")
    else:
        print("  ✓ donchian parametreleri ankorla birebir")
    if not cfg.strategy.donchian_mtf_enabled:
        print("  ⚠ DONCHIAN_MTF=false → canlı MTF kapısı YOK, ankor onu HEP uygular.")
        print("    Bu sessizliğin sebebi DEĞİL (kapı yoksa DAHA ÇOK sinyal olur),")
        print("    ama canlı ≠ ankor demek. Not edildi.")
    else:
        print("  ✓ DONCHIAN_MTF açık (ankorla aynı)")

    # ── B) VERİ TAZELİĞİ + C) SİNYAL ─────────────────────────────────────────
    print(f"\n{'='*76}\nB) VERİ TAZELİĞİ (bayat veri = sessizce kör bot)\n{'='*76}")
    coinler = sorted(set(dsym) | set(ssym))
    veri, aday = {}, []
    for c in coinler:
        try:
            m = cek(c)
        except Exception as e:
            print(f"  {c:<5s} ⛔ VERİ ÇEKİLEMEDİ: {e}")
            continue
        veri[c] = m
        yas = (simdi - m.index[-1]).total_seconds() / 3600.0
        bayrak = "✓" if yas < 3 else "⚠ BAYAT"
        print(f"  {c:<5s} son 1h bar {m.index[-1]:%Y-%m-%d %H:%M}  yaş {yas:5.2f} saat  {bayrak}",
              flush=True)

    # ⚠ BAĞLANTI GUARD'I — bu araç veri eksikken HÜKÜM VERMEZ.
    # Smoke-test'te yakalandı: ccxt yokken C bölümü "hiç sinyal yok, sessizliğin
    # sebebi BU" diye YALANCI HÜKÜM basıyordu. Veri çekilemediyse "sinyal yok" ile
    # "bakamadık" ayırt edilemez; ikisini karıştırmak tam da botun sağlam olduğuna
    # yanlış yere ikna eden hatadır.
    eksik_veri = [c for c in coinler if c not in veri]
    if eksik_veri:
        print(f"\n  ⛔ DURDURULDU: {eksik_veri} için veri çekilemedi.")
        print("     Veri olmadan 'sinyal yok' ile 'bakamadık' ayırt EDİLEMEZ, o yüzden")
        print("     bu araç hüküm BASMIYOR. Eksikleri gider ve tekrar çalıştır:")
        print("       pip3 install ccxt        # modül yoksa")
        print("       (ağ/borsa erişimi VPS'te olmalı — PC'de MEXC engelli olabilir)")
        raise SystemExit(2)

    print(f"\n{'='*76}\nC) SİNYAL YENİDEN HESABI (üretim sınıfları, loga güvenmeden)\n{'='*76}")
    for c in coinler:
        if c not in veri:
            continue
        if c in dsym:
            aday += adaylar_donchian(c, veri[c], cfg, bas)
        if c in ssym:
            aday += adaylar_squeeze(c, veri[c], cfg, bas)
        print(f"  {c} tarandı", flush=True)
    aday.sort(key=lambda a: a["ts"])
    gecen = [a for a in aday if a["mtf"]]
    print(f"\n  Son {gun} günde ÜRETİLEN sinyal: {len(aday)}  "
          f"(MTF kapısını geçen: {len(gecen)})")
    if aday:
        for a in aday:
            print(f"    {a['ts']:%m-%d %H:%M}  {a['coin']:<5s} {a['kol']:<8s} "
                  f"{'LONG ' if a['yon']==1 else 'SHORT'}  @{a['fiyat']:.4f}"
                  f"{'' if a['mtf'] else '   ← MTF kapısı ELEDİ'}")
    else:
        print("    (hiç sinyal yok — sessizliğin sebebi BU, engellenme değil)")

    # ── D) SAYIM ─────────────────────────────────────────────────────────────
    print(f"\n{'='*76}\nD) GERÇEK GİRİŞLERLE KARŞILAŞTIRMA\n{'='*76}")
    giris, acik = defter(cfg.db_path, bas)
    if giris is None:
        print(f"  ⛔ DURDURULDU: trades.db bulunamadı ({cfg.db_path}).")
        print("     Gerçek girişlerle karşılaştırma olmadan 'sağlam' denemez.")
        print("     Bu aracı BOTUN ÇALIŞTIĞI MAKİNEDE (VPS, /opt/bot2) çalıştır.")
        raise SystemExit(2)
    canli = [g for g in giris if not g["is_paper"]]
    print(f"  trades.db: son {gun} günde {len(canli)} GERÇEK giriş "
          f"({len(giris)-len(canli)} paper hariç)")
    for g in canli:
        print(f"    {pd.Timestamp(g['entry_time']):%m-%d %H:%M}  "
              f"{g['symbol'].split('/')[0]:<5s} {kol_of(g):<8s} {g['side']:<5s} "
              f"{'AÇIK' if not g['exit_time'] else g['exit_reason']}")

    print(f"\n  --- AÇIK POZİSYONLAR (max_hold aşımı = GERÇEK arıza) ---")
    canli_acik = [a for a in acik if not a["is_paper"]]
    if not canli_acik:
        print("    yok")
    for a in canli_acik:
        et = pd.Timestamp(a["entry_time"])
        if et.tzinfo is None:
            et = et.tz_localize("UTC")
        yas = (simdi - et).total_seconds() / 3600.0
        k = kol_of(a)
        limit = 120.0 if k == "donchian" else float(cfg.risk.max_hold_candles)
        durum = "⛔ MAX_HOLD AŞILMIŞ — kapanmalıydı!" if yas > limit else "✓"
        print(f"    {a['symbol'].split('/')[0]:<5s} {k:<8s} {a['side']:<5s} "
              f"yaş {yas:6.1f}s / limit {limit:.0f}s  {durum}")

    # eşleştirme: her MTF-geçen sinyal için ±3 saat içinde giriş var mı?
    print(f"\n  --- EŞLEŞTİRME: oluşmalıydı → açıldı mı? ---")
    acik_o_an = {}          # coin → o sinyal anında pozisyon açık mıydı
    tum = [g for g in (canli + canli_acik)]
    eksik = []
    for a in gecen:
        sym = f"{a['coin']}/USDT:USDT"
        bulundu = any(
            g["symbol"] == sym and kol_of(g) == a["kol"]
            and abs((pd.Timestamp(g["entry_time"]).tz_localize("UTC")
                     if pd.Timestamp(g["entry_time"]).tzinfo is None
                     else pd.Timestamp(g["entry_time"])) - a["ts"]).total_seconds() < 3 * 3600
            for g in tum)
        # o an aynı coinde açık pozisyon var mıydı? (one-per-symbol kilidi)
        kilit = any(
            g["symbol"] == sym
            and (pd.Timestamp(g["entry_time"]).tz_localize("UTC")
                 if pd.Timestamp(g["entry_time"]).tzinfo is None
                 else pd.Timestamp(g["entry_time"])) <= a["ts"]
            and (g.get("exit_time") is None or
                 (pd.Timestamp(g["exit_time"]).tz_localize("UTC")
                  if pd.Timestamp(g["exit_time"]).tzinfo is None
                  else pd.Timestamp(g["exit_time"])) > a["ts"])
            for g in tum)
        n_acik = acik_sayisi(tum, a["ts"])
        cd = cooldown_aktif(tum, sym, a["kol"], a["ts"],
                            getattr(cfg.risk, "consecutive_loss_limit", 0),
                            getattr(cfg.risk, "cooldown_minutes", 0))
        if bulundu:
            hkm = "✓ AÇILDI"
        elif kilit:
            hkm = "○ coin doluydu (one-per-symbol) — BEKLENEN"
        elif n_acik >= cfg.risk.max_positions:
            hkm = f"○ koltuk doluydu ({n_acik}/{cfg.risk.max_positions}) — BEKLENEN"
        elif cd:
            hkm = "○ cooldown aktifti (ardışık zarar) — BEKLENEN"
        else:
            hkm = "⛔ AÇIKLANAMADI — İNCELE"
            eksik.append(a)
        print(f"    {a['ts']:%m-%d %H:%M} {a['coin']:<5s} {a['kol']:<8s} "
              f"{'LONG ' if a['yon']==1 else 'SHORT'}  {hkm}")

    # ── HÜKÜM ────────────────────────────────────────────────────────────────
    print(f"\n{'='*76}\nHÜKÜM\n{'='*76}")
    asim = [a for a in canli_acik
            if (simdi - (pd.Timestamp(a["entry_time"]).tz_localize("UTC")
                         if pd.Timestamp(a["entry_time"]).tzinfo is None
                         else pd.Timestamp(a["entry_time"]))).total_seconds() / 3600
            > (120.0 if kol_of(a) == "donchian" else float(cfg.risk.max_hold_candles))]
    bayat = [c for c in veri
             if (simdi - veri[c].index[-1]).total_seconds() / 3600 >= 3]
    if bayat:
        print(f"  ⛔ SORUN: {bayat} için borsa verisi bayat — bot kör olabilir.")
    if asim:
        print(f"  ⛔ SORUN: {[a['symbol'] for a in asim]} max_hold'u aştı, kapanmamış.")
    if eksik:
        print(f"  ⛔ {len(eksik)} sinyal AÇIKLANAMADI. Elenen ihtimaller: coin kilidi,")
        print(f"     MAX_POSITIONS koltuğu, (sleeve:coin) cooldown. Kalan ihtimaller:")
        print(f"     günlük zarar halt'ı, elle duraklatma, borsa/emir hatası, gerçek arıza.")
        print(f"     Bu barlar için journalctl'e BAKILMALI:")
        for a in eksik:
            print(f"       {a['ts']:%m-%d %H:%M} {a['coin']} {a['kol']}  →  "
                  f"journalctl -u btc-bot --since '{a['ts']:%Y-%m-%d %H:%M}' "
                  f"--until '{(a['ts']+timedelta(hours=1)):%Y-%m-%d %H:%M}' | grep -i {a['coin']}")
    if not (bayat or asim or eksik):
        if not gecen:
            print("  ✓ SAĞLAM. Son {} günde MTF'yi geçen HİÇ sinyal oluşmadı —".format(gun))
            print("    yani açılacak bir şey yoktu. Sessizlik SİNYAL YOKLUĞU,")
            print("    engellenme ya da arıza DEĞİL. (Üretim sınıflarıyla yeniden")
            print("    hesaplandı; loga güvenilmedi.)")
        else:
            print(f"  ✓ SAĞLAM. Oluşan {len(gecen)} sinyalin HEPSİ ya açıldı ya da")
            print("    açıklanabilir bir kilitle (coin dolu) elendi. Kayıp sinyal yok.")
        print("  ✓ Veri taze, açık pozisyonların hiçbiri max_hold'u aşmamış.")


def dogrula():
    """ÖZ-TEST: bu aracın sinyal yeniden hesabı ANKORLA aynı mı?

    Araç ancak replay'i ankorun üreticisiyle örtüşüyorsa değerli. Ankorun
    deployed_backtest.gen("donchian", m) çıktısı occ uyguladığı için ALT KÜME;
    dolayısıyla ankorun ürettiği HER giriş bu aracın aday listesinde OLMALI.
    Bir tanesi bile eksikse replay bozuktur ve hüküm basılmamalıdır.

    Çevrimdışı: data/ önbelleğini OKUR, yazmaz.
    """
    import copy
    import deployed_backtest as DB
    import fast_bt
    cfg = load_config()
    cfg = copy.deepcopy(cfg)
    cfg.strategy.donchian_mtf_enabled = True      # ankor MTF'yi HEP uygular
    cfg.strategy.donchian_channel = 40
    cfg.strategy.donchian_ema_trend = 200
    cfg.strategy.donchian_sl_atr = 2.0
    cfg.strategy.donchian_rr = 2.0
    cfg.strategy.donchian_buffer_atr = 0.0
    print("ÖZ-TEST: replay ankorla örtüşüyor mu? (çevrimdışı, data/ salt-okunur)\n")
    toplam_a, toplam_e = 0, 0
    for c in ["SOL", "ETH", "ADA", "NEAR", "BCH", "ICP", "BNB"]:
        m = fast_bt.load(c, source="local")
        d4 = resample(m, "4h")
        # son 400 4h bar ≈ 66 gün — ankorun ürettiği girişleri kapsayan pencere
        bas = d4.index[-400]
        son = d4.index[-2]                        # DB.gen son barı üretmez
        ank = [pd.Timestamp(t[0], tz="UTC") for t in DB.gen("donchian", m)]
        ank = [t for t in ank if bas <= t <= son]
        ben = {a["ts"] for a in adaylar_donchian(c, m, cfg, bas) if a["mtf"]}
        eksik = [t for t in ank if t not in ben]
        toplam_a += len(ank); toplam_e += len(eksik)
        durum = "✓" if not eksik else f"⛔ {len(eksik)} EKSİK"
        print(f"  {c:<5s} ankor {len(ank):>3d} giriş | replay adayı {len(ben):>3d}  {durum}")
        for t in eksik:
            print(f"        EKSİK: {t}")
    # squeeze kolu da doğrulanmalı — araç ikisini birden kullanıyor
    cfg.strategy.squeeze_kc_mult = 1.5
    cfg.strategy.squeeze_min_bars = 5
    cfg.strategy.squeeze_sl_atr = 2.0
    cfg.strategy.squeeze_rr = 2.5
    cfg.strategy.squeeze_mtf = True
    print()
    for c in ["XRP", "DOGE", "TRX", "XLM"]:
        m = fast_bt.load(c, source="local")
        d1 = resample(m, "1h")
        bas = d1.index[-1600]                     # ≈66 gün, 1h kolda
        son = d1.index[-2]
        ank = [pd.Timestamp(t[0], tz="UTC") for t in DB.gen("squeeze", m)]
        ank = [t for t in ank if bas <= t <= son]
        ben = {a["ts"] for a in adaylar_squeeze(c, m, cfg, bas)}
        eksik = [t for t in ank if t not in ben]
        toplam_a += len(ank); toplam_e += len(eksik)
        durum = "✓" if not eksik else f"⛔ {len(eksik)} EKSİK"
        print(f"  {c:<5s} ankor {len(ank):>3d} giriş | replay adayı {len(ben):>3d}  {durum}")
        for t in eksik:
            print(f"        EKSİK: {t}")

    print(f"\n  ankor girişi {toplam_a}, replay'de bulunamayan {toplam_e}")
    if toplam_e == 0:
        print("  ✓ ÖZ-TEST GEÇTİ — replay ankorun ürettiği her girişi yakalıyor.")
        print("    (Aday sayısı daha büyük: occ uygulanmıyor, bu BEKLENEN.)")
    else:
        raise SystemExit("  ⛔ ÖZ-TEST KALDI — bu araçla hüküm verilemez.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--dogrula":
        dogrula()
    else:
        main()
