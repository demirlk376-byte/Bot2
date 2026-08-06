"""
sentinel.py — BOTUN DIŞINDAN çalışan ölü-adam anahtarı (dead man's switch).

NEDEN GEREKLİ: mevcut heartbeat'i BOTUN KENDİSİ gönderiyor (main.heartbeat_loop).
Bu, bot çalışırken faydalı ama ölümü tespit EDEMEZ — ölen şeyin kendi sinyaliyle
ölümü anlaşılmaz. Bot tamamen düşerse (crash loop, OOM, disk dolu, API anahtarı
iptali, systemd pes eder) telefona HİÇBİR ŞEY gelmez. Ve "sessizlik" ile "her şey
yolunda" ayırt edilemez. Bir ay başında kimse yokken bu kabul edilemez.

BU SCRIPT AYRI BİR SÜREÇTİR (systemd timer). Botun kodundan HİÇBİR ŞEY import etmez —
sadece stdlib + requests. Böylece bot import hatasıyla çökse bile nöbetçi ayakta kalır.

KONTROLLER (hepsi salt-okunur, borsaya hiç dokunmaz):
  1. systemd servisi aktif mi
  2. /tmp/bot_alive dosyası taze mi (bot 5 dk'da bir yazıyor)
  3. disk doluluk (log + trades.db büyür; dolu disk botu sessizce öldürür)
  4. bot sürecinin bellek kullanımı (bir ayda sızıntı birikir)
  5. trades.db okunabiliyor mu + en son işlem ne kadar eski (canlı ama TIKANMIŞ bot:
     süreç ayakta, sinyal üretmiyor — heartbeat bunu "sağlıklı" gösterir)

ALARM POLİTİKASI: yalnız SORUNDA mesaj atar (sessizlik = sağlık). Aynı sorun için
COOLDOWN_H saatte birden fazla mesaj atmaz — spam yok, ama sorun sürerse hatırlatır.
Sorun düzelince "düzeldi" mesajı atar, böylece kapanışı da görürsün.

--report: periyodik ÖZET gönderir (sağ olduğunun kanıtı). Sessizliğin belirsizliğini
bu çözer: haftalık özet GELMİYORSA nöbetçinin kendisi de düşmüş demektir.

Kullanım:
  python3 sentinel.py                 # sağlık kontrolü (timer bunu çağırır)
  python3 sentinel.py --report        # özet gönder
  python3 sentinel.py --test          # bildirim yolunu test et (zorla mesaj atar)
"""
import os, sys, json, time, sqlite3, shutil, subprocess
from datetime import datetime, timezone

BOT_DIR = os.environ.get("BOT_DIR", "/opt/bot2")
SERVICE = os.environ.get("BOT_SERVICE", "btc-bot")


def _load_env(path):
    """BOT_DIR/.env dosyasını ortama yükle — YALNIZCA HENÜZ TANIMLI OLMAYAN anahtarları.

    NEDEN GEREKLİ (2026-08-06'da canlıda yakalandı): sentinel yalnız os.environ okuyordu.
    systemd birimlerinde EnvironmentFile=.env var, ama ELLE çalıştırıldığında
    (`python3 sentinel.py --report`) hiçbir kimlik bilgisi görünmüyor ve rapor
    "hiçbir bildirim kanalı çalışmadı" diyor. Bu, gerçek bir arıza ile elle-çalıştırma
    artefaktını AYIRT EDİLEMEZ hale getiriyordu — nöbetçinin tam olarak yapmaması
    gereken şey. Ayrıca systemd'nin EnvironmentFile ayrıştırıcısı `export` önekini ve
    bazı tırnak biçimlerini KABUL ETMEZ; kendi ayrıştırıcımız o tuzağa da düşmez.

    ORTAM DEĞİŞKENİ ÖNCELİKLİDİR: systemd/kabuk tarafından verilen değer EZİLMEZ."""
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("export "):
                    s = s[7:].lstrip()
                if "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip(); v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass
    except Exception:
        pass        # .env okunamazsa sessizce geç — nöbetçi bu yüzden ÇÖKMEMELİ


_load_env(os.path.join(BOT_DIR, ".env"))
ALIVE_FILE = os.environ.get("ALIVE_FILE", "/tmp/bot_alive")
DB_PATH = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))
STATE = os.environ.get("SENTINEL_STATE", "/var/lib/bot2-sentinel.json")

ALIVE_MAX_MIN = int(os.environ.get("ALIVE_MAX_MIN", "20"))      # 5dk'da bir yazılır → 20dk cömert
DISK_MIN_PCT = float(os.environ.get("DISK_MIN_PCT", "10"))      # boş disk %
MEM_MAX_MB = float(os.environ.get("MEM_MAX_MB", "1200"))        # bot RSS tavanı (tipik ~260MB)
NO_TRADE_MAX_H = float(os.environ.get("NO_TRADE_MAX_H", "168")) # 7 gün hiç işlem = şüpheli
COOLDOWN_H = float(os.environ.get("COOLDOWN_H", "6"))
# OI 15 dk'da bir yazılıyor; 2 saat sessizlik = toplayıcı durmuş demektir.
OI_CSV = os.environ.get("OI_CSV", os.path.join(BOT_DIR, "data", "oi_log.csv"))
OI_MAX_H = float(os.environ.get("OI_MAX_H", "2"))

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID") or ""
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or ""
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")


def notify(text):
    """Telegram + ntfy'ye gönder. Biri çalışmazsa diğerini dener; ikisi de
    başarısızsa stdout'a basar (journal'da kalır)."""
    sent = False
    if TG_TOKEN and TG_CHAT:
        try:
            import requests
            r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                              json={"chat_id": TG_CHAT, "text": text}, timeout=20)
            sent = r.ok
            if not r.ok: print(f"telegram HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"telegram hata: {e}")
    if NTFY_TOPIC:
        try:
            import requests
            r = requests.post(f"{NTFY_URL}/{NTFY_TOPIC}",
                              data=text.encode("utf-8"), timeout=20)
            sent = sent or r.ok
        except Exception as e:
            print(f"ntfy hata: {e}")
    print(text)
    if not sent:
        print("UYARI: hiçbir bildirim kanalı çalışmadı (TELEGRAM_TOKEN/CHAT_ID veya NTFY_TOPIC?)")
    return sent


def load_state():
    try:
        with open(STATE) as f: return json.load(f)
    except Exception: return {}


def save_state(s):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f: json.dump(s, f)
    except Exception as e:
        print(f"durum yazılamadı ({STATE}): {e}")


def svc_active():
    try:
        r = subprocess.run(["systemctl", "is-active", SERVICE],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip() == "active", r.stdout.strip()
    except Exception as e:
        return None, f"kontrol edilemedi: {e}"


def bot_rss_mb():
    """Servisin ana PID'inin RSS'i (MB). Bulunamazsa None."""
    try:
        r = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", SERVICE],
                           capture_output=True, text=True, timeout=15)
        pid = int((r.stdout or "0").strip() or 0)
        if pid <= 0: return None
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        return None
    return None


def last_trade_age_h():
    """En son işlem girişinden bu yana geçen saat. DB okunamazsa (None, hata)."""
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=15)
        cur = con.execute("SELECT MAX(entry_time) FROM trades WHERE is_paper=0")
        row = cur.fetchone(); con.close()
        if not row or not row[0]: return None, None
        ts = str(row[0])
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None: t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0, None
    except Exception as e:
        return None, str(e)


def checks():
    """(anahtar, sorun_var_mı, mesaj) listesi döndürür."""
    out = []

    active, raw = svc_active()
    if active is False:
        out.append(("service", True, f"🔴 {SERVICE} servisi ÇALIŞMIYOR (durum: {raw})"))
    elif active is None:
        out.append(("service", True, f"⚠️ servis durumu okunamadı: {raw}"))
    else:
        out.append(("service", False, f"servis aktif"))

    try:
        age_min = (time.time() - float(open(ALIVE_FILE).read().strip())) / 60.0
        bad = age_min > ALIVE_MAX_MIN
        out.append(("alive", bad,
                    (f"🔴 heartbeat {age_min:.0f} dk eski (>{ALIVE_MAX_MIN}) — bot donmuş olabilir"
                     if bad else f"heartbeat {age_min:.0f} dk")))
    except Exception as e:
        out.append(("alive", True, f"🔴 heartbeat dosyası okunamadı ({ALIVE_FILE}): {e}"))

    try:
        du = shutil.disk_usage(BOT_DIR)
        free_pct = du.free / du.total * 100
        bad = free_pct < DISK_MIN_PCT
        out.append(("disk", bad,
                    (f"🔴 disk %{free_pct:.1f} boş (<{DISK_MIN_PCT}) — dolu disk botu öldürür"
                     if bad else f"disk %{free_pct:.0f} boş")))
    except Exception as e:
        out.append(("disk", True, f"⚠️ disk okunamadı: {e}"))

    rss = bot_rss_mb()
    if rss is not None:
        bad = rss > MEM_MAX_MB
        out.append(("mem", bad,
                    (f"🔴 bot belleği {rss:.0f}MB (>{MEM_MAX_MB}) — sızıntı olabilir"
                     if bad else f"bellek {rss:.0f}MB")))

    # OI toplayıcı sessizce ölürse, sahte kırılım için kalan TEK araştırma yolunun
    # verisini bir ay boyunca kaybederiz — ve geçmiş OI sonradan satın alınamaz,
    # sadece biriktirilebilir. Bu yüzden nöbetin kapsamında.
    if os.path.exists(OI_CSV):
        try:
            age_h = (time.time() - os.path.getmtime(OI_CSV)) / 3600.0
            bad = age_h > OI_MAX_H
            out.append(("oi", bad,
                        (f"⚠️ OI logu {age_h:.1f} saat güncellenmedi (>{OI_MAX_H}) — "
                         f"toplayıcı durmuş olabilir"
                         if bad else f"OI logu {age_h*60:.0f} dk önce yazıldı")))
        except Exception as e:
            out.append(("oi", True, f"⚠️ OI logu okunamadı: {e}"))

    age_h, err = last_trade_age_h()
    if err:
        out.append(("db", True, f"🔴 trades.db okunamadı: {err}"))
    elif age_h is None:
        out.append(("db", False, "canlı işlem kaydı yok"))
    else:
        bad = age_h > NO_TRADE_MAX_H
        out.append(("db", bad,
                    (f"⚠️ {age_h/24:.1f} gündür yeni işlem yok — bot ayakta ama TIKANMIŞ olabilir"
                     if bad else f"son işlem {age_h:.0f} saat önce")))
    return out


def summary_text():
    """trades.db'den kompakt özet (tek Telegram mesajına sığar)."""
    lines = []
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=15)
        n_open = con.execute(
            "SELECT COUNT(*) FROM trades WHERE is_paper=0 AND exit_price IS NULL").fetchone()[0]
        row = con.execute(
            "SELECT COUNT(*), SUM(pnl_usdt), SUM(CASE WHEN pnl_usdt>0 THEN 1 ELSE 0 END) "
            "FROM trades WHERE is_paper=0 AND exit_price IS NOT NULL").fetchone()
        n_cl, pnl, wins = (row or (0, 0, 0))
        pnl = pnl or 0.0; wins = wins or 0
        gp = con.execute("SELECT SUM(pnl_usdt) FROM trades WHERE is_paper=0 AND pnl_usdt>0"
                         ).fetchone()[0] or 0.0
        gl = con.execute("SELECT SUM(pnl_usdt) FROM trades WHERE is_paper=0 AND pnl_usdt<0"
                         ).fetchone()[0] or 0.0
        bal = con.execute("SELECT ending_balance FROM daily_stats WHERE is_paper=0 "
                          "ORDER BY date DESC LIMIT 1").fetchone()
        con.close()
        pf = (gp / abs(gl)) if gl else float("inf")
        wr = (wins / n_cl * 100) if n_cl else 0.0
        if bal and bal[0]: lines.append(f"bakiye ${float(bal[0]):,.2f}")
        lines.append(f"açık {n_open} · kapanan {n_cl}")
        if n_cl:
            lines.append(f"PnL ${pnl:+.2f} · WR %{wr:.0f} · PF {pf:.2f}")
            lines.append("(çıpa: PF 1.44 / WR %43 — n<30 ise gürültü)")
    except Exception as e:
        lines.append(f"trades.db okunamadı: {e}")
    return "\n".join(lines)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if arg == "--test":
        ok = notify(f"✅ Nöbetçi bildirim testi · {stamp}\n\n" + summary_text())
        sys.exit(0 if ok else 1)

    if arg == "--report":
        # TÜM kontroller listelenir, sorunlular dahil. Yalnız sağlıklıları
        # göstermek, servis ölüyken "iyi görünen" bir rapor üretirdi — bir ay
        # uzaktayken en yanıltıcı çıktı bu olurdu.
        cs = checks()
        bad = [m for _, b, m in cs if b]
        good = " · ".join(m for _, b, m in cs if not b)
        head = "🚨 Bot özeti — SORUN VAR" if bad else "📊 Bot özeti"
        body = f"{head} · {stamp}\n\n{summary_text()}\n"
        if bad: body += "\n" + "\n".join(bad) + "\n"
        if good: body += f"\n{good}"
        notify(body)
        return

    st = load_state()
    now = time.time()
    problems, recovered = [], []
    for key, bad, msg in checks():
        last = st.get(key, {}).get("last_alert", 0)
        was_bad = st.get(key, {}).get("bad", False)
        if bad:
            if now - last >= COOLDOWN_H * 3600:
                problems.append(msg)
                st[key] = {"bad": True, "last_alert": now}
            else:
                st[key] = {"bad": True, "last_alert": last}
        else:
            if was_bad:
                recovered.append(f"✅ düzeldi: {msg}")
            st[key] = {"bad": False, "last_alert": 0}

    if problems:
        notify(f"🚨 BOT UYARISI · {stamp}\n\n" + "\n".join(problems) +
               f"\n\n{summary_text()}")
    elif recovered:
        notify(f"✅ Durum normale döndü · {stamp}\n\n" + "\n".join(recovered))
    else:
        # Bastırılmış sorun ile gerçek sağlığı AYIR: devam eden bir arıza
        # sırasında journal'a "temiz" yazmak, logu okuyan kişiyi yanıltır.
        still = [k for k, v in st.items() if v.get("bad")]
        if still:
            print(f"{stamp} — SORUN SÜRÜYOR ({', '.join(still)}) — "
                  f"cooldown nedeniyle mesaj atılmadı")
        else:
            print(f"{stamp} — tüm kontroller temiz (mesaj atılmadı)")
    save_state(st)


if __name__ == "__main__":
    main()
