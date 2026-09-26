"""
canli_disa_aktar.py — canlı trades.db'yi SALT OKUNUR biçimde CSV'ye aktarır.

Yalnız standart kütüphane. Bot modüllerini (main, exchange, config) İÇE AKTARMAZ,
borsaya bağlanmaz, emir gönderemez, .env okumaz. Veritabanı `mode=ro` ile açılır.

VPS'te:
    cd /opt/bot2 && python3 arastirma/paylasim_paketi_2026-09-26/canli_disa_aktar.py \
        --db /opt/bot2/trades.db --cikti /tmp/canli_disa_aktarim

Çıktı klasörü:
    islemler_kapali.csv   is_paper=0, exit_time dolu
    islemler_acik.csv     is_paper=0, exit_time boş
    bakiye_gunluk.csv     daily_stats (tüm satırlar, is_paper sütunuyla)
    meta.csv              meta tablosu (anahtar adında key/secret/token/pass geçenler hariç)
    diger_<tablo>.csv     şemada başka tablo varsa, aynen
    manifest.json         aktarım zamanı, şema, satır sayıları, dosya sha256, repo commit'i
Bilinmeyen alan BOŞ bırakılır; sıfırla doldurulmaz. Türetilmiş sütunlar `turetilmis_` önekli.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone

GIZLI = re.compile(r"key|secret|token|pass|chat|api", re.I)


def _yaz(yol, basliklar, satirlar):
    with open(yol, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(basliklar)
        for s in satirlar:
            w.writerow(["" if v is None else v for v in s])


def _sha(yol):
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for p in iter(lambda: f.read(1 << 20), b""):
            h.update(p)
    return h.hexdigest()


def _skor_anahtarlari(satirlar, idx):
    anahtar = []
    for s in satirlar:
        try:
            d = json.loads(s[idx]) if s[idx] else {}
        except (TypeError, ValueError):
            continue
        for k in d:
            if k not in anahtar:
                anahtar.append(k)
    return anahtar


def islemler(con, kolonlar, cikti):
    satirlar = con.execute(f"SELECT {', '.join(kolonlar)} FROM trades WHERE is_paper=0 "
                           "ORDER BY entry_time").fetchall()
    ix = {k: i for i, k in enumerate(kolonlar)}
    ss = _skor_anahtarlari(satirlar, ix["strategy_scores"]) if "strategy_scores" in ix else []
    ek = [f"ss_{k}" for k in ss] + ["turetilmis_yon", "turetilmis_fiyat_pnl_usdt", "turetilmis_ilk_stop_kaynagi"]
    basliklar = list(kolonlar) + ek
    kapali, acik = [], []
    for s in satirlar:
        try:
            d = json.loads(s[ix["strategy_scores"]]) if "strategy_scores" in ix and s[ix["strategy_scores"]] else {}
        except (TypeError, ValueError):
            d = {}
        ssv = [(json.dumps(d[k]) if isinstance(d.get(k), (dict, list)) else d.get(k)) for k in ss]
        taraf = str(s[ix["side"]]).lower()
        yon = 1 if taraf in ("long", "buy") else (-1 if taraf in ("short", "sell") else None)
        cik = s[ix["exit_price"]] if "exit_price" in ix else None
        fpnl = (yon * (cik - s[ix["entry_price"]]) * s[ix["quantity"]]
                if yon is not None and cik is not None else None)
        ilk_stop = "ss_sl0" if d.get("sl0") is not None else "yok (sl_price son stoptur, tasinmis olabilir)"
        satir = list(s) + ssv + [yon, fpnl, ilk_stop]
        (acik if s[ix["exit_time"]] in (None, "") else kapali).append(satir)
    _yaz(os.path.join(cikti, "islemler_kapali.csv"), basliklar, kapali)
    _yaz(os.path.join(cikti, "islemler_acik.csv"), basliklar, acik)
    paper = con.execute("SELECT COUNT(*) FROM trades WHERE is_paper<>0").fetchone()[0]
    ilk = satirlar[0][ix["entry_time"]] if satirlar else None
    return dict(kapali=len(kapali), acik=len(acik), paper_disarida=paper, ilk_canli_giris=ilk,
                strategy_scores_anahtarlari=ss)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/opt/bot2/trades.db")
    ap.add_argument("--cikti", default="/tmp/canli_disa_aktarim")
    a = ap.parse_args()
    if not os.path.exists(a.db):
        raise SystemExit(f"veritabanı yok: {a.db}")
    os.makedirs(a.cikti, exist_ok=True)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True, timeout=15)
    tablolar = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    sema = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in tablolar}
    man = dict(aktarim_utc=datetime.now(timezone.utc).isoformat(), db=os.path.abspath(a.db),
               sema=sema, satir={})
    if "trades" in sema:
        man["satir"]["trades"] = islemler(con, sema["trades"], a.cikti)
    if "daily_stats" in sema:
        r = con.execute(f"SELECT {', '.join(sema['daily_stats'])} FROM daily_stats ORDER BY date").fetchall()
        _yaz(os.path.join(a.cikti, "bakiye_gunluk.csv"), sema["daily_stats"], r)
        man["satir"]["daily_stats"] = len(r)
    if "meta" in sema:
        r = [x for x in con.execute("SELECT key, value FROM meta ORDER BY key") if not GIZLI.search(x[0])]
        _yaz(os.path.join(a.cikti, "meta.csv"), ["key", "value"], r)
        man["satir"]["meta"] = len(r)
    for t in tablolar:
        if t in ("trades", "daily_stats", "meta") or t.startswith("sqlite_"):
            continue
        kol = [k for k in sema[t] if not GIZLI.search(k)]
        r = con.execute(f"SELECT {', '.join(kol)} FROM {t}").fetchall()
        _yaz(os.path.join(a.cikti, f"diger_{t}.csv"), kol, r)
        man["satir"][t] = len(r)
    con.close()
    try:
        kok = os.path.dirname(os.path.abspath(a.db))
        man["repo_commit"] = subprocess.run(["git", "-C", kok, "rev-parse", "HEAD"], capture_output=True,
                                            text=True, timeout=10).stdout.strip() or None
    except Exception:
        man["repo_commit"] = None
    man["dosyalar"] = {f: _sha(os.path.join(a.cikti, f)) for f in sorted(os.listdir(a.cikti))
                       if f != "manifest.json"}
    with open(os.path.join(a.cikti, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    print(f"tamam: {a.cikti}  ({json.dumps(man['satir'], ensure_ascii=False, default=str)[:300]})")


if __name__ == "__main__":
    main()
