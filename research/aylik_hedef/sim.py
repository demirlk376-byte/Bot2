#!/usr/bin/env python3
"""Aylik kar hedefi durdurmasi -- bot-yalniz simulasyon, implementasyon A (event-list).

On kayit: /home/user/sweep/research/aylik_hedef/ON_KAYIT.md
  - Baslangic 1.0; risk = giris anindaki gerceklesmis deger * 0.035; cikista deger += R * risk.
  - R = pnl_usdt / (|entry_price - sl0| * quantity).
  - Ay basi degeri = ayin ilk anindaki gerceklesmis deger (00:00 UTC gun 1'e devreden deger).
  - Giriste (deger / ay_basi - 1) >= esik ise islem ATLANIR.
  - TABAN: kural yok, H10: 0.10, H15: 0.15.
  - Olcut: varyant IYI <=> her iki donemde (i) final carpan > TABAN ve (ii) maxDD <= TABAN maxDD + 1 puan.
Esit zaman damgasinda once CIKISLAR, sonra GIRISLER islenir. Aylar UTC.
Veritabanlari salt-okunur (immutable=1) acilir; bu dizin disina hicbir sey yazilmaz.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

BASE = "/tmp/claude-0/-home-user-Bot2/4f0a318a-bb3d-55e5-bc2c-d9194f822f40/scratchpad"
OUTDIR = BASE + "/aylik_hedef_A"
DB_KESIF = BASE + "/ikiz_kanit/ikiz_gercek.db"
DB_BAGIMSIZ = BASE + "/ikiz_kanit/ikiz_eski.db"
BAGIMSIZ_CUTOFF = "2023-04-07T00:00:00Z"

RISK = 0.035
VARIANTS = [("TABAN", None), ("H10", 0.10), ("H15", 0.15)]
STRATS = ("donchian", "mean_rev")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
EXIT, ENTRY = 0, 1  # sort key: exits before entries at equal timestamps


def parse_ts(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    assert dt.tzinfo is not None, s
    return dt.astimezone(timezone.utc)


def to_ms(dt):
    return (dt - EPOCH) // timedelta(milliseconds=1)


def load(db_path, cutoff=None):
    con = sqlite3.connect("file:" + db_path + "?immutable=1", uri=True)
    rows = con.execute(
        "SELECT symbol, side, entry_price, quantity, entry_time, exit_time, pnl_usdt, strategy_scores "
        "FROM trades WHERE pnl_usdt IS NOT NULL"
    ).fetchall()
    con.close()
    cut = parse_ts(cutoff) if cutoff else None
    trades, strat_all = [], {}
    for sym, side, ep, qty, et, xt, pnl, ss in rows:
        d = json.loads(ss)
        st = d.get("strategy")
        strat_all[st] = strat_all.get(st, 0) + 1
        ent = parse_ts(et)
        if cut is not None and not (ent < cut):
            continue
        if st not in STRATS:
            continue
        assert xt is not None, (sym, et)
        ex = parse_ts(xt)
        assert ex > ent, (sym, et, xt)  # zero-duration trades would break exit-before-entry ordering
        sl0 = float(d["sl0"])
        den = abs(float(ep) - sl0) * float(qty)
        assert den > 0, (sym, et)
        trades.append(dict(symbol=sym, side=side, entry=ent, exit=ex,
                           entry_ms=to_ms(ent), exit_ms=to_ms(ex), R=float(pnl) / den, strategy=st))
    assert "squeeze" not in strat_all, ("squeeze present", strat_all)
    return trades, strat_all


def build_events(trades):
    ev = []
    for i, t in enumerate(trades):
        ev.append((t["entry_ms"], ENTRY, i))
        ev.append((t["exit_ms"], EXIT, i))
    ev.sort()
    return ev


def mkey(dt):
    return dt.year * 12 + (dt.month - 1)


def mkey_ms(ms):
    return mkey(EPOCH + timedelta(milliseconds=ms))


def simulate(trades, events, thr, month_start_mode="carry"):
    """month_start_mode: 'carry' = value carried into the month before any of its events (spec);
    'midnight_in_start' = exits stamped exactly 00:00:00 UTC on day 1 are counted in the month-start value
    (sensitivity only; the spec uses 'carry')."""
    V = 1.0
    risk = {}
    taken = skipped = 0
    skipped_R = 0.0
    skipped_months, hit_months = set(), set()
    month_end = {}           # month key -> realized value at end of month (after its last event)
    cur_m, m_start = None, None
    first_m = mkey_ms(events[0][0])
    n = len(events)
    k = 0
    while k < n:
        ts = events[k][0]
        m = mkey_ms(ts)
        if m != cur_m:
            if cur_m is not None:
                month_end[cur_m] = V
            cur_m = m
            m_start = V  # carry-over value
            _d = EPOCH + timedelta(milliseconds=ts)
            pending_after_first = (month_start_mode == "midnight_in_start" and _d.day == 1
                                   and _d.hour == 0 and _d.minute == 0 and _d.second == 0 and _d.microsecond == 0)
        else:
            pending_after_first = False
        # all events at this timestamp: exits first (sorted by type), then entries
        j = k
        while j < n and events[j][0] == ts:
            j += 1
        batch = events[k:j]
        for _, typ, i in batch:
            if typ == EXIT and i in risk:
                V += trades[i]["R"] * risk.pop(i)
        if pending_after_first:
            # sensitivity: include exits stamped exactly at 00:00 day 1 in the month-start value
            m_start = V
        for _, typ, i in batch:
            if typ != ENTRY:
                continue
            gain = V / m_start - 1.0
            if thr is not None and gain >= thr:
                skipped += 1
                skipped_R += trades[i]["R"]
                skipped_months.add(m)
                continue
            taken += 1
            risk[i] = V * RISK
        if thr is not None and V / m_start - 1.0 >= thr:
            hit_months.add(m)
        k = j
    month_end[cur_m] = V
    assert not risk, "open positions left"
    last_m = cur_m
    # month-end series with forward fill, prepend 1.0 at month before first event
    keys = list(range(first_m - 1, last_m + 1))
    s, prev = [], 1.0
    for mk in keys:
        if mk == first_m - 1:
            s.append(1.0)
            continue
        if mk in month_end:
            prev = month_end[mk]
        s.append(prev)
    peak, mdd = -1.0, 0.0
    for v in s:
        peak = max(peak, v)
        mdd = max(mdd, 1.0 - v / peak)
    # yearly multipliers from month-end series
    yearly, prev_val = {}, 1.0
    years = sorted({mk // 12 for mk in keys if mk >= first_m})
    for y in years:
        ye = [v for mk, v in zip(keys, s) if mk // 12 == y]
        yearly[y] = ye[-1] / prev_val
        prev_val = ye[-1]
    return dict(final_mult=V, maxdd=mdd * 100.0, trades_taken=taken, trades_skipped=skipped,
                skipped_sumR=skipped_R, months_triggered=len(skipped_months), months_hit=len(hit_months),
                yearly=yearly, n_months=len(keys) - 1)


def main():
    periods = []
    tk, sk = load(DB_KESIF)
    periods.append(("KESIF", tk, sk))
    tb, sb = load(DB_BAGIMSIZ, BAGIMSIZ_CUTOFF)
    periods.append(("BAGIMSIZ", tb, sb))
    out = {"rows": [], "sensitivity_midnight_in_start": [], "meta": {}}
    res = {}
    for pname, trades, strat_all in periods:
        ev = build_events(trades)
        out["meta"][pname] = dict(n_trades=len(trades), strategies_all_rows=strat_all,
                                  first_entry=min(t["entry"] for t in trades).isoformat(),
                                  last_entry=max(t["entry"] for t in trades).isoformat(),
                                  last_exit=max(t["exit"] for t in trades).isoformat(),
                                  sumR=sum(t["R"] for t in trades))
        for vname, thr in VARIANTS:
            r = simulate(trades, ev, thr)
            res[(vname, pname)] = r
            row = dict(variant=vname, period=pname, final_mult=r["final_mult"], maxdd=r["maxdd"],
                       trades_taken=r["trades_taken"], trades_skipped=r["trades_skipped"],
                       skipped_sumR=r["skipped_sumR"], months_triggered=r["months_triggered"],
                       months_hit=r["months_hit"], n_months=r["n_months"],
                       yearly={str(y): v for y, v in r["yearly"].items()})
            out["rows"].append(row)
            r2 = simulate(trades, ev, thr, month_start_mode="midnight_in_start")
            out["sensitivity_midnight_in_start"].append(dict(variant=vname, period=pname,
                                                       final_mult=r2["final_mult"], maxdd=r2["maxdd"],
                                                       trades_skipped=r2["trades_skipped"]))
    verdicts = {}
    for vname, thr in VARIANTS[1:]:
        ok = True
        detail = []
        for pname in ("KESIF", "BAGIMSIZ"):
            b, h = res[("TABAN", pname)], res[(vname, pname)]
            c1 = h["final_mult"] > b["final_mult"]
            c2 = h["maxdd"] <= b["maxdd"] + 1.0
            detail.append(f"{pname}: mult {h['final_mult']:.4f} vs {b['final_mult']:.4f} ({'OK' if c1 else 'FAIL'}), "
                          f"maxDD {h['maxdd']:.2f} vs {b['maxdd']:.2f}+1 ({'OK' if c2 else 'FAIL'})")
            ok = ok and c1 and c2
        verdicts[vname] = ("IYI" if ok else "ELENDI") + " | " + "; ".join(detail)
    out["verdicts"] = verdicts

    # print
    for pname in ("KESIF", "BAGIMSIZ"):
        print(f"== {pname} ==", json.dumps(out["meta"][pname], default=str))
        for vname, _ in VARIANTS:
            r = res[(vname, pname)]
            print(f"  {vname:6s} final={r['final_mult']:.6f} maxDD={r['maxdd']:.4f} taken={r['trades_taken']} "
                  f"skipped={r['trades_skipped']} skR={r['skipped_sumR']:+.4f} mtrig={r['months_triggered']} "
                  f"mhit={r['months_hit']} months={r['n_months']}")
            print("         yearly:", " ".join(f"{y}:{v:.4f}" for y, v in r["yearly"].items()))
    print("sensitivity (exits at exactly 00:00 UTC day 1 counted in month-start):")
    for x in out["sensitivity_midnight_in_start"]:
        print("  ", x)
    for k, v in verdicts.items():
        print(k, "=>", v)
    with open(OUTDIR + "/results.json", "w") as f:
        json.dump(out, f, indent=1, default=str)


if __name__ == "__main__":
    sys.exit(main())
