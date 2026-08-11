"""
live_verify.py — CANLI SONUÇLARI ANKORLA KARŞILAŞTIR: overfit edilemeyen tek kanıt.

NEDEN BU, BUGÜNKÜ 18 TESTİN TOPLAMINDAN DEĞERLİ: backtest'te ne yaparsak yapalım, aynı
2023-2026 verisine bakıyoruz ve her yeni test o veriyi biraz daha aşındırıyor. Canlı işlemler
GELECEKTEN geliyor — hiçbir parametre onlara bakılarak seçilmedi. Ledger'ın kendi notu:
"Bu tek veri, buradaki 14 testin toplamından fazlasını söyler — overfit edilemeyen TEK şey o."

⚠️ İSTATİSTİK DÜRÜSTLÜĞÜ — bu aracın en kolay yanlış kullanılacağı yer:
n=68 ile PF/WR karşılaştırmak GÜRÜLTÜ ölçmektir. Bu yüzden her karşılaştırma bir GÜVEN
ARALIĞI ile birlikte veriliyor ve "sapma var mı" sorusu p-değeriyle yanıtlanıyor.
"Canlı WR %35, ankor %43.5, demek ki bozulmuş" ÇIKARIMI YANLIŞ olur — ancak güven aralığı
ankoru DIŞLIYORSA sapmadan söz edilebilir. Araç bunu sizin yerinize hesaplıyor.

ÖLÇÜLENLER (her biri ayrı bir arıza türünü yakalar):
 1. R DAĞILIMI — ortalama R ve güven aralığı. Ankor +0.237R bekliyor.
    Bu, "edge hâlâ var mı" sorusunun doğrudan cevabı; PF/WR türev metriklerdir.
 2. GİRİŞ KAYMASI (slippage) — sinyal fiyatı vs gerçekleşen giriş. Ölçülen 13.4bp,
    net kârın ~%12'si. Büyüdüyse yürütme bozulmuş demektir (likidite, emir tipi, gecikme).
 3. STOP/HEDEF İSABETİ — çıkışların kaçı SL, kaçı TP, kaçı maxhold. Ankor dağılımıyla
    kıyaslanır. Sapma, stop'ların canlıda beklendiği yerde durmadığını gösterir.
 4. KOL BAZINDA — donchian/squeeze/bb ayrı. Bir kol bozulduysa toplamda gizlenebilir.
 5. BEKLENEN vs GERÇEKLEŞEN PnL — her işlem için R'den beklenen dolar ile defterdeki
    pnl_usdt karşılaştırılır. Sistematik fark = boyutlandırma veya muhasebe hatası.
 6. AÇIK POZİSYON HARİÇ — kapanmamış işlemler ORTALAMAYA KATILMAZ (hayatta kalma yanlılığı:
    açık kalanlar sistematik olarak kazananlardır, dahil etmek sonucu şişirir).

Kullanım (VPS'te):  cd /opt/bot2 && python3 live_verify.py
"""
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone

BOT_DIR = os.environ.get("BOT_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("TRADES_DB", os.path.join(BOT_DIR, "trades.db"))

# ── ANKOR BEKLENTİLERİ (deployed_backtest.py local, 1579 işlem / $+1420.66) ──
ANK_R = 0.237          # ortalama R
ANK_WR = 0.435         # kazanma oranı
ANK_PF = 1.45
ANK_SLIP_BP = 13.4     # ölçülen donchian giriş kayması
# MEXC taker ücreti (taraf başına). Beklenen-PnL karşılaştırmasını NET-NET
# yapmak için gerekli; brüt beklenen ile net gerçekleşeni kıyaslamak ücret
# kadar sahte "sistematik sapma" üretiyordu.
TAKER_FEE = float(os.environ.get("TAKER_FEE", "0.0002"))
ANK_EXIT = {"sl": 0.561, "tp": 0.213, "mh": 0.226}   # power_test taban dağılımı

# ⚠️ ANKOR YALNIZ BU ÜÇ KOLUN BACKTESTİ. Defterde KAPALI kolların da işlemleri var
# (asia_bo/orb/fvg/sr_breakout — 2026-07-16 öncesi). Onları ortalamaya katmak ANKORLA
# KIYASLANAMAZ bir sayı üretir: 2026-08-10 koşusunda tam bu oldu — 72 işlemin 33'ü kapalı
# kollardandı, ort R'yi +0.11'den −0.10'a çekti ve araç "ankorun ALTINDA" uyarısı verdi.
# Kapalı kollar çok daha KÜÇÜK boyutla açıldığı için R'yi aşağı çekerken dolarda neredeyse
# hiç iz bırakmıyor ($-6.06). Ortalama R her işleme EŞİT ağırlık verir, dolar ise BOYUTA
# göre — bu ikisini karıştırmak yanlış teşhis üretir.
DEPLOY_SLEEVES = ("donchian", "squeeze", "bb")


def wilson(k, n, z=1.96):
    """Oran için Wilson güven aralığı — küçük n'de normal yaklaşımdan ÇOK daha dürüst."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def tconf(vals, z=1.96):
    """Ortalama için güven aralığı (n küçükken t≈z kabul, n>30 için yeterli)."""
    n = len(vals)
    if n < 2:
        return (float("nan"), float("nan"), float("nan"))
    m = sum(vals) / n
    var = sum((v - m) ** 2 for v in vals) / (n - 1)
    se = math.sqrt(var / n)
    return m, m - z * se, m + z * se


def sleeve_of(scores_json):
    try:
        d = json.loads(scores_json) if scores_json else {}
    except Exception:
        d = {}
    s = (d.get("strategy") or d.get("sleeve") or "").lower()
    if "donch" in s or "breakout" in s: return "donchian"
    if "squeeze" in s: return "squeeze"
    if "mean" in s or "bb" in s: return "bb"
    return "?"


def main():
    if not os.path.exists(DB):
        print(f"✗ {DB} bulunamadı. /opt/bot2 içinde çalıştırın."); return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    rows = con.execute(
        "SELECT symbol, side, entry_price, exit_price, quantity, sl_price, tp_price,"
        " entry_time, exit_time, pnl_usdt, strategy_scores FROM trades WHERE is_paper=0"
    ).fetchall()
    con.close()

    closed = [r for r in rows if r[3] and r[8] and r[9] is not None]
    openp = [r for r in rows if not r[8]]
    print("=" * 84)
    print("CANLI vs ANKOR — örneklem-dışı doğrulama")
    print("=" * 84)
    print(f"\n  kapanan {len(closed)} · açık {len(openp)}  "
          f"(açıklar ORTALAMAYA KATILMIYOR — hayatta kalma yanlılığı)")
    if len(closed) < 20:
        print("  ✗ n<20 — hiçbir karşılaştırma anlamlı değil. Daha fazla işlem gerek.")
        return

    # ── 1) R DAĞILIMI ──
    Rs = []; Rs_act = []; wins = 0; wins_act = 0; gp = 0.0; gl = 0.0; slip_bp = []; exits = {"sl": 0, "tp": 0, "mh": 0}
    by_sleeve = {}
    pnl_err = []; fees_est = []
    for (sym, side, ep, xp, qty, slp, tpp, et, xt, pnl, sc) in closed:
        d_ = 1 if str(side).lower() in ("long", "buy", "1") else -1
        risk = abs(ep - slp)
        if risk <= 0:
            continue
        R = d_ * (xp - ep) / risk
        Rs.append(R)
        if pnl > 0: wins += 1; gp += pnl
        else: gl += -pnl
        # çıkış türü: hangi seviyeye daha yakın kapandı
        d_sl = abs(xp - slp); d_tp = abs(xp - tpp)
        if d_sl < risk * 0.10: exits["sl"] += 1
        elif d_tp < abs(tpp - ep) * 0.10: exits["tp"] += 1
        else: exits["mh"] += 1
        sl_name = sleeve_of(sc)
        by_sleeve.setdefault(sl_name, []).append((R, pnl))
        if sl_name in DEPLOY_SLEEVES:
            Rs_act.append(R)
            if pnl > 0: wins_act += 1
        # Beklenen dolar: R × risk$ ; risk$ = |giriş−sl| × miktar.
        # ⚠ BU BRÜT — ücret HARİÇ. Defterdeki pnl_usdt ise NET (ücret dahil).
        # İkisini çıplak karşılaştırmak, ücret kadar bir farkı "sistematik sapma"
        # diye işaretler: 2026-08-10 canlı koşusunda tam bu oldu (−$0.0196/işlem,
        # aralık [−0.0231,−0.0161], "⚠ sistematik fark VAR"). Sayı doğruydu ama
        # TEŞHİS yanlıştı — bot hatası değil, benim 'beklenen' tanımım eksikti.
        # Düzeltme: beklenene gidiş-dönüş ücreti EKLENİR, böylece karşılaştırma
        # net-net olur ve alarm yalnız GERÇEK bir sapmada çalar.
        notional = ep * qty
        fee_rt = 2 * TAKER_FEE * notional
        exp_usd = R * risk * qty - fee_rt
        if pnl is not None:
            pnl_err.append(pnl - exp_usd)
            fees_est.append(fee_rt)

    n = len(Rs)
    na = len(Rs_act)
    m, lo, hi = tconf(Rs)
    print(f"\n[1] ORTALAMA R — 'edge hâlâ var mı' sorusunun DOĞRUDAN cevabı")
    if na >= 20 and na < n:
        ma, loa, hia = tconf(Rs_act)
        print(f"    AKTİF KOLLAR (ankorla kıyaslanabilir TEK sayı — {', '.join(DEPLOY_SLEEVES)})")
        print(f"      canlı  {ma:+.4f}R   %95 aralık [{loa:+.4f}, {hia:+.4f}]   n={na}")
        print(f"      ankor  {ANK_R:+.4f}R")
        print(f"    tüm defter (kapalı kollar DAHİL, ankorla KIYASLANAMAZ)")
        print(f"      canlı  {m:+.4f}R   n={n}   ← {n-na} işlem kapalı kollardan")
        m, lo, hi, n = ma, loa, hia, na          # hüküm AKTİF üzerinden verilir
    else:
        print(f"    canlı  {m:+.4f}R   %95 aralık [{lo:+.4f}, {hi:+.4f}]   n={n}")
        print(f"    ankor  {ANK_R:+.4f}R")
    if lo > 0:
        print(f"    ✓ aralık SIFIRIN ÜSTÜNDE → edge canlıda da POZİTİF (istatistiksel olarak)")
    elif hi < 0:
        print(f"    ⛔ aralık SIFIRIN ALTINDA → edge canlıda NEGATİF. Ciddi.")
    else:
        print(f"    ~ aralık sıfırı içeriyor → n henüz yetmiyor, 'pozitif' DENEMEZ")
    if lo <= ANK_R <= hi:
        print(f"    ✓ ankor ({ANK_R:+.3f}) aralığın İÇİNDE → sapma YOK")
    else:
        yon = "ALTINDA" if hi < ANK_R else "ÜSTÜNDE"
        print(f"    ⚠ ankor aralığın {yon} → gerçek sapma olabilir (n arttıkça netleşir)")

    # ── 2) KAZANMA ORANI ──
    if len(Rs_act) >= 20 and len(Rs_act) < len(Rs):
        wins, n = wins_act, len(Rs_act)          # aktif kollar üzerinden
    wl, wh = wilson(wins, n)
    print(f"\n[2] KAZANMA ORANI (aktif kollar)")
    print(f"    canlı %{wins/n*100:.1f}  %95 aralık [%{wl*100:.1f}, %{wh*100:.1f}]  ankor %{ANK_WR*100:.1f}")
    print(f"    {'✓ ankor aralık içinde — sapma yok' if wl <= ANK_WR <= wh else '⚠ ankor aralık DIŞINDA'}")
    pf = gp / gl if gl > 0 else float("inf")
    print(f"    PF {pf:.2f} (ankor {ANK_PF:.2f}) — n<200'de PF çok oynak, tek başına okuma")

    # ── 3) ÇIKIŞ DAĞILIMI ──
    print(f"\n[3] ÇIKIŞ TÜRÜ — stop'lar beklendiği yerde mi duruyor")
    print(f"    {'tür':>6s} {'canlı':>10s} {'ankor':>8s}")
    for k, lbl in (("sl", "stop"), ("tp", "hedef"), ("mh", "süre")):
        c = exits[k] / n
        cl_, ch_ = wilson(exits[k], n)
        flag = "" if cl_ <= ANK_EXIT[k] <= ch_ else "  ⚠ aralık dışı"
        print(f"    {lbl:>6s} %{c*100:>8.1f} %{ANK_EXIT[k]*100:>7.1f}{flag}")

    # ── 4) KOL BAZINDA ──
    print(f"\n[4] KOL BAZINDA (bir kol bozulduysa toplamda gizlenir)")
    print(f"    {'kol':<10s} {'n':>4s} {'ort R':>9s} {'toplam$':>9s}")
    for k in sorted(by_sleeve):
        v = by_sleeve[k]
        rr = [x[0] for x in v]; pp = sum(x[1] for x in v)
        mm = sum(rr) / len(rr)
        print(f"    {k:<10s} {len(v):>4d} {mm:>+9.4f} {pp:>+9.2f}"
              + ("   (n<20 → gürültü)" if len(v) < 20 else ""))

    # ── 5) MUHASEBE TUTARLILIĞI ──
    if pnl_err:
        me, elo, ehi = tconf(pnl_err)
        ort_fee = sum(fees_est) / len(fees_est) if fees_est else 0.0
        print(f"\n[5] BEKLENEN vs GERÇEKLEŞEN PnL (boyutlandırma/muhasebe kontrolü)")
        print(f"    beklenen NET (ücret ${TAKER_FEE*1e4:.0f}bp/taraf düşülmüş, "
              f"ort ${ort_fee:.4f}/işlem)")
        print(f"    ortalama fark ${me:+.4f}  %95 [{elo:+.4f}, {ehi:+.4f}] · toplam ${sum(pnl_err):+.2f}")
        if elo <= 0 <= ehi:
            print(f"    ✓ sıfır aralık içinde → sistematik sapma YOK")
        else:
            # Kalan farkı ücret ölçeğiyle kıyasla: ücretin bir kısmı kadarsa
            # ücret varsayımı (TAKER_FEE) hafif yanlış demektir — bot hatası değil.
            oran = abs(me) / ort_fee if ort_fee > 0 else float("inf")
            if oran < 1.5:
                print(f"    ~ fark ücret ölçeğinde (ücretin {oran:.1f} katı) → büyük ihtimalle")
                print(f"      TAKER_FEE varsayımı hafif yanlış. Gerçek ücreti MEXC'ten teyit edip")
                print(f"      TAKER_FEE=<oran> ile yeniden koşun. Bot hatası DEĞİL.")
            else:
                print(f"    ⚠ fark ücretin {oran:.1f} KATI — bu ücretle açıklanamaz.")
                print(f"      Boyutlandırma veya muhasebe gözden geçirilmeli.")

    # ── 6) SÜRE ──
    try:
        ts = [datetime.fromisoformat(str(r[7]).replace("Z", "+00:00")) for r in closed]
        ts = [t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t for t in ts]
        gun = (max(ts) - min(ts)).days or 1
        print(f"\n[6] KAPSAM: {gun} gün · günde {n/gun:.1f} işlem "
              f"(ankor {1579/1216:.1f}/gün)")
        print(f"    ankor hızında {n} işleme ulaşmak {n/(1579/1216):.0f} gün sürerdi")
    except Exception:
        pass

    print(f"\n{'=' * 84}")
    print("NASIL OKUNUR:")
    print("  [1] EN ÖNEMLİ satır. Aralık sıfırın üstündeyse edge canlıda da var demektir.")
    print("      Ankor aralığın içindeyse 'backtest tutuyor' diyebiliriz.")
    print("  n<100 iken PF ve WR TEK BAŞINA okunmaz — aralıklara bakın, noktaya değil.")
    print("  Bu araç ay sonunda TEKRAR koşulmalı; asıl değer n büyüdükçe ortaya çıkar.")
    print("=" * 84)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"✗ hata: {type(e).__name__}: {e}")
        sys.exit(1)
