"""
LIQUIDITY_SWEEP_V1 komut arayüzü (şartname §24).

  python -m research.liquidity_sweep_v1.cli doctor     [--data DIR]
  python -m research.liquidity_sweep_v1.cli verify     [--data DIR]          # pytest + uyum kapıları
  python -m research.liquidity_sweep_v1.cli freeze     [--data DIR]          # manifesti dondurur, run_id üretir
  python -m research.liquidity_sweep_v1.cli discovery  --run RUN_DIR
  python -m research.liquidity_sweep_v1.cli validation --run RUN_DIR
  python -m research.liquidity_sweep_v1.cli final      --run RUN_DIR
  python -m research.liquidity_sweep_v1.cli report     --run RUN_DIR
  python -m research.liquidity_sweep_v1.cli run-all    [--data DIR] --jobs 1

Veri: research_data/liquidity_sweep_v1/veri (veri/sweep5m dalından). Çıktı:
research_outputs/liquidity_sweep_v1/<run_id>/. Hiçbir canlı dosya/DB/env yazılmaz; ağ yok.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import data_contract as D
from . import events as EV
from . import levels as LV
from . import metrics as MT
from . import replay_adapter as RA
from . import selection as SL
from . import setups as SU

PKG = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(PKG))
DEFAULT_DATA = os.path.join(ROOT, "research_data", "liquidity_sweep_v1", "veri")
DEFAULT_OUT = os.path.join(ROOT, "research_outputs", "liquidity_sweep_v1")
PHASES = ("DISCOVERY", "VALIDATION", "FINAL")
# Önceki veri kullanımı (PnL görmeden kayıt): 1H MEXC 2023-04-06→2026-07-19 bot geliştirmesinde
# defalarca; Binance 5m 13 coin ~1065 gün (≈2023-09→2026-08) 2026-08-14 Sweep+Reclaim/VWAP/BB
# araştırmasında; 2026-09-22 SMC/ICT ailesi. Hiçbir dönem "untouched" değildir.
PREVIOUS_DATA_USE = {
    "DISCOVERY": "previously_examined",
    "VALIDATION": "previously_examined",
    "FINAL": "previously_examined",
    "not": "2023-04→2026-07 1H MEXC bot geliştirmesinde; Binance 5m ~2023-09→2026-08 eski Sweep+Reclaim "
           "testinde (DURUM.md 4e) kullanıldı. 2026-07-19 sonrası 1H ikizde yok ama 5m eski testte olabilir → "
           "FINAL bağımsız değildir.",
}
_LOG = None


# ───────────────────────────── yardımcılar ───────────────────────────────────
def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    if _LOG:
        with open(_LOG, "a") as f:
            f.write(line + "\n")


def atomic_write(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, indent=1, ensure_ascii=False, default=_js).encode())


def _js(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return str(x)


def write_csv(path, df: pd.DataFrame, gz=False):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    b = buf.getvalue().encode()
    if gz:
        b = gzip.compress(b, mtime=0)
    atomic_write(path, b)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def code_hashes():
    out = {}
    for f in sorted(os.listdir(PKG)):
        if f.endswith(".py"):
            out[f] = sha_bytes(open(os.path.join(PKG, f), "rb").read())
    return out


def git(*a):
    try:
        return subprocess.check_output(["git", "-C", ROOT, *a], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def config_dict():
    return {k: getattr(C, k) for k in dir(C) if k.isupper() and not k.startswith("_")
            and isinstance(getattr(C, k), (int, float, str, list, tuple, dict))}


def t2s(ms):
    return D.ms_to_str(ms)


# ───────────────────────────── hazırlık ──────────────────────────────────────
class World:
    """Veri + türetilmiş seriler + aile bazında seviye/olaylar (bir kez, kronolojik)."""

    def __init__(self, data_dir=None, symbols=None, universe=None):
        t0 = time.time()
        self.data_dir = data_dir
        self.U = universe if universe is not None else D.build_universe(data_dir, symbols)
        self.dates = D.partition_dates(self.U)
        self.derived = {s: LV.Derived(sd) for s, sd in self.U["symbols"].items()}
        self.books, self.events, self.notes = {}, {}, {}
        g1 = self.U["g1"]
        for fam in C.LEVEL_FAMILIES:
            self.books[fam], self.events[fam], self.notes[fam] = {}, {}, {}
            for s, dv in self.derived.items():
                b = LV.LevelBook(fam, dv)
                evs, notes = EV.detect(fam, dv, b)
                b.finalize(D.last_complete_day_ms(dv.sd) or g1)
                notes["L4_INVALID_INDICATOR"] = b.invalid_indicator
                self.books[fam][s], self.events[fam][s], self.notes[fam][s] = b, evs, notes
        self._setups = {}
        log(f"dünya hazır: {len(self.derived)} sembol, {time.time() - t0:.0f} sn")

    def window(self, phase):
        return self.dates[phase]

    def setups(self, fam, K, phase):
        key = (fam, K, phase)
        if key not in self._setups:
            a, b = self.window(phase)
            self._setups[key] = SU.run_machine(fam, K, self.events[fam], self.derived, a, b)
        return self._setups[key]

    def signals(self, vid, phase):
        fam, K, F = vid.split("_")
        recs = self.setups(fam, K, phase)
        sig = [r for r in recs if r.terminal_status == "SIGNAL" and (F == "F0" or r.F1_pass)]
        return recs, sig


def run_variant(W: World, vid, phase, cost, C0, outdir=None, record_equity=True):
    recs, sig = W.signals(vid, phase)
    res = RA.simulate(vid, phase, W.window(phase), sig, W.U, cost, C0, record_equity=record_equity)
    m = MT.run_metrics(res, recs, W.window(phase), C0, phase)
    fam, K, F = vid.split("_")
    m.update(variant_id=vid, cost_scenario=cost.name, signals=len(sig),
             sweep_events=sum(1 for r in recs),
             trend_rejected=sum(1 for r in recs if r.terminal_status == "SIGNAL" and F == "F1"
                                and not r.F1_pass and r.F1_reason == "TREND_REJECTED"),
             trend_invalid_indicator=sum(1 for r in recs if r.terminal_status == "SIGNAL" and F == "F1"
                                         and not r.F1_pass and r.F1_reason == "INVALID_INDICATOR"),
             reclaim_count=sum(1 for r in recs if r.reclaim_time is not None),
             structure_break_count=sum(1 for r in recs if r.first_break_time is not None
                                       and r.terminal_status not in ("WEAK_FIRST_BREAK", "INVALID_INDICATOR")),
             fvg_count=sum(1 for r in recs if r.fvg_known_at is not None),
             retest_count=sum(1 for r in recs if r.retest_time is not None),
             setup_terminals=pd.Series([r.terminal_status for r in recs]).value_counts().to_dict() if recs else {})
    a_, b_ = W.window(phase)
    lv_hi = lv_lo = 0
    for b in W.books[fam].values():
        for L in b.levels:
            if a_ <= L.known_at < b_:
                lv_hi += L.side == "HIGH"
                lv_lo += L.side == "LOW"
    elig_h = 0
    for sd in W.U["symbols"].values():
        k0, k1 = (a_ - sd.g0) // C.M5, (b_ - sd.g0) // C.M5
        elig_h += int(sd.valid5[k0:k1].sum()) * 5 / 60
    m.update(levels_created=dict(HIGH=int(lv_hi), LOW=int(lv_lo)), eligible_symbol_hours=float(elig_h),
             _trade_nets=[t["net_PnL"] for t in res.trades])
    if outdir:
        d = os.path.join(outdir, phase, f"{vid}_{cost.name}")
        tr = pd.DataFrame(res.trades)
        write_csv(os.path.join(d, "trades.csv"), tr)
        ev = events_frame(recs, res, vid, F)
        write_csv(os.path.join(d, "events.csv"), ev)
        if record_equity:
            eq = pd.DataFrame(res.equity, columns=RA.EQUITY_FIELDS)
            eq["timestamp_utc"] = pd.to_datetime(eq["timestamp_utc"], unit="ms", utc=True)
            write_csv(os.path.join(d, "equity_5m.csv.gz"), eq, gz=True)
        write_json(os.path.join(d, "metrics.json"), _strip(m))
    return m, res


def events_frame(recs, res, vid, F):
    port = {}
    for o in res.outcomes:
        port.setdefault(o["market_event_id"], []).append(o["terminal_status"])
    rows = []
    for r in recs:
        d = r.as_dict()
        term = r.terminal_status
        if term == "SIGNAL":
            if F == "F1" and not r.F1_pass:
                term = r.F1_reason or "TREND_REJECTED"
            else:
                p = port.get(r.market_event_id, [])
                term = "CLOSED" if "CLOSED" in p else (p[-1] if p else "OUTSIDE_PARTITION")
        d.update(variant_id=vid, terminal_status=term,
                 ATR15_frozen=r.ATR15_frozen)
        rows.append(d)
    df = pd.DataFrame(rows)
    for c in ("level_known_at", "level_expires_at", "sweep_open", "sweep_close", "terminal_time", "reclaim_time",
              "micro_reference_known_at", "first_break_time", "fvg_known_at", "retest_time", "signal_time"):
        if c in df:
            df[c] = df[c].map(lambda x: t2s(x) if x is not None and x == x else None)
    return df


# ───────────────────────────── komutlar ──────────────────────────────────────
def cmd_doctor(a):
    info = dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__,
                head=git("rev-parse", "HEAD"), branch=git("rev-parse", "--abbrev-ref", "HEAD"),
                dirty=bool(git("status", "--porcelain")), data_dir=a.data, data_exists=os.path.isdir(a.data))
    if info["data_exists"]:
        oz = json.load(open(os.path.join(a.data, "indirme_ozeti.json")))
        info["download_created"] = oz.get("olusturma")
        info["files"] = {k: dict(satir=v.get("satir"), ilk=v.get("ilk"), son=v.get("son"),
                                 eksik_bar=v.get("eksik_bar")) for k, v in oz["dosyalar"].items()}
    print(json.dumps(info, indent=1, ensure_ascii=False, default=str))
    return info


def gates_hash(out_root):
    p = os.path.join(out_root, "_verify", "fidelity_gates.json")
    if not os.path.exists(p):
        raise SystemExit("uyum kapıları koşulmamış (cli verify) — dondurma reddedildi")
    rep = json.load(open(p))
    if not rep.get("all_ok"):
        raise SystemExit("uyum kapıları GEÇMEDİ — METRICS_INVALID; dondurma reddedildi")
    if rep.get("source_hashes") != code_hashes():
        raise SystemExit("uyum raporu farklı kod sürümüyle üretilmiş — önce cli verify")
    return D.sha256_file(p)


def cmd_freeze(a):
    global _LOG
    gh = gates_hash(a.out)
    W = World(a.data)
    U, dates = W.U, W.dates
    if dates is None:
        raise SystemExit("ana evren kurulamadı (ısınma/veri yetersiz)")
    gaps = {s: D.gaps_in(sd, dates["T0"] - 0, dates["T1"]) for s, sd in U["symbols"].items()}
    man = dict(
        spec_version=C.SPEC_VERSION, created_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        base_commit=git("rev-parse", "HEAD"),
        dirty_diff_hash=sha_bytes((git("diff", "HEAD") or "").encode()),
        dependency_versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__),
        config=config_dict(), config_hash=sha_bytes(json.dumps(config_dict(), sort_keys=True, default=str).encode()),
        source_hashes=code_hashes(), data_hashes=U["raw_hashes"], data_download_created=U["download_summary_created"],
        source_exchange=("MEXC" if U["source"] == "mexc_5m" else "BINANCE_USDM (MEXC venue vekili)"),
        source_rule="choose_source(): MEXC tüm semboller için tam kapsamlı değilse tüm evren Binance USDⓈ-M",
        source_report=U["source_report"], market_type="USDT-margined linear perpetual",
        symbol_mapping={s: dict(ccxt=f"{s}/USDT:USDT", mexc=f"{s}_USDT", binance=f"{s}USDT") for s in C.UNIVERSE},
        active_universe=list(U["symbols"]), excluded_symbols_with_reasons=U["excluded"],
        survivorship_note="evren bugünkü sembol listesi; hepsi 2023-01 öncesi listelenmiş (veri başlangıcı) — "
                          "delist olmuş semboller yok → hayatta kalma yanlılığı mümkün",
        contract_metadata={s: dict(tick=sd.tick, contract_size=sd.contract_size, vol_unit=sd.vol_unit,
                                   min_vol=sd.min_vol, source=sd.meta_source) for s, sd in U["symbols"].items()},
        fee_profile=C.TWIN_MARKET_PROFILE.as_dict(), stress_profile=C.TWIN_MARKET_PROFILE.stress().as_dict(),
        fallback_profile_not_used=C.SPEC_FALLBACK_PROFILE.as_dict(),
        slippage_profile="toplam aleyhe fiyat farkı (spread dahil); ayrıca yarım spread EKLENMEZ",
        funding_mode={s: sd.funding_source for s, sd in U["symbols"].items()},
        funding_mark_proxy="settlement anında bilinen son 5m kapanış (gerçek mark fiyatı yok)",
        data_quality=U["quality"], data_gaps_in_main_period=gaps,
        dates_ms={k: int(dates[k]) for k in ("T0", "T1", "B1", "B2")},
        T0=t2s(dates["T0"]), T1=t2s(dates["T1"]), B1=t2s(dates["B1"]), B2=t2s(dates["B2"]), N_days=dates["N_days"],
        partitions={p: [t2s(dates[p][0]), t2s(dates[p][1])] for p in PHASES},
        warmup=dict(h1=C.WARMUP_1H, lower_tf=C.WARMUP_LOWER_TF),
        risk_caps=dict(C0=C.C0_FALLBACK, C0_source="ikiz PAPER_INITIAL_BALANCE varsayılanı 10.000 (araştırma varsayımı)",
                       per_trade_risk_usdt=C.PER_TRADE_RISK_FRAC * C.C0_FALLBACK,
                       portfolio_initial_stop_risk_cap=C.PORTFOLIO_RISK_CAP_FRAC * C.C0_FALLBACK,
                       live_gates_applied=C.LIVE_GATES, live_gates_not_applied=C.LIVE_GATES_NOT_APPLIED),
        execution_resolution="5m (bar içi çift temas → stop önce, AMBIGUOUS_SL_TP)",
        event_order_version=C.EVENT_ORDER_VERSION,
        rng=dict(seed=C.BOOT_SEED, generator="numpy.random.default_rng (PCG64)", numpy=np.__version__),
        previous_data_use=PREVIOUS_DATA_USE, variant_ids=C.VARIANT_IDS, fidelity_gates_hash=gh,
        overall_decision_rule=SL.overall_without_final.__doc__,
    )
    core = json.dumps({k: v for k, v in man.items() if k not in ("created_at_utc",)}, sort_keys=True,
                      default=_js).encode()
    mh = sha_bytes(core)
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{(man['base_commit'] or 'nogit')[:8]}_{mh[:8]}"
    man["run_id"], man["manifest_hash"] = run_id, mh
    out = os.path.join(a.out, run_id)
    os.makedirs(out, exist_ok=True)
    _LOG = os.path.join(out, "run.log")
    write_json(os.path.join(out, "experiment_manifest.json"), man)
    write_json(os.path.join(out, "data_quality.json"), dict(quality=U["quality"], gaps=gaps,
                                                            source_report=U["source_report"],
                                                            excluded=U["excluded"],
                                                            level_notes={f: W.notes[f] for f in W.notes}))
    lv = []
    for fam, bs in W.books.items():
        for s, b in bs.items():
            for L in b.levels:
                lv.append(dict(level_id=L.level_id, symbol=s, family=fam, side=L.side, price=L.price,
                               origin_times="|".join(t2s(x) for x in L.origin_times), known_at=t2s(L.known_at),
                               expires_at=t2s(L.expires_at), selected_at_bar_start=t2s(L.selected_at_bar_start)
                               if L.selected_at_bar_start else None,
                               consumed_at=t2s(L.consumed_at) if L.consumed_at else None,
                               consume_reason=L.consume_reason))
    write_csv(os.path.join(out, "levels.csv.gz"), pd.DataFrame(lv), gz=True)
    log(f"manifest donduruldu: {run_id} (hash {mh[:12]})")
    print(out)
    return out, W


def load_manifest(run_dir):
    man = json.load(open(os.path.join(run_dir, "experiment_manifest.json")))
    # kod/konfig/veri değiştiyse eski manifestle devam ETME (resume yalnız aynı hashlerde)
    if man["source_hashes"] != code_hashes() or man["config_hash"] != sha_bytes(
            json.dumps(config_dict(), sort_keys=True, default=str).encode()):
        raise SystemExit("KOD/KONFİG HASH DEĞİŞTİ — bu run_id ile devam edilemez (yeni freeze gerekir)")
    for path, h in man["data_hashes"].items():
        if not os.path.exists(path) or D.sha256_file(path) != h:
            raise SystemExit(f"VERİ HASH DEĞİŞTİ: {path} — bu run_id ile devam edilemez")
    return man


def world_for(man, a, W=None):
    """Aşama komutları tarihleri MANİFESTTEN alır; yeniden hesaplanan değer farklıysa reddeder."""
    W = W or World(a.data)
    frozen = man["dates_ms"]
    for k, v in frozen.items():
        if int(W.dates[k]) != int(v):
            raise SystemExit(f"TARİH {k} manifestten farklı ({W.dates[k]} != {v}) — reddedildi")
    return W


def _phase(W, run_dir, man, phase, vids, tag):
    global _LOG
    _LOG = os.path.join(run_dir, "run.log")
    C0 = man["risk_caps"]["C0"]
    results = {}
    last = time.time()
    for i, vid in enumerate(vids):
        mm = []
        for cost in (C.TWIN_MARKET_PROFILE, C.TWIN_MARKET_PROFILE.stress()):
            m, _ = run_variant(W, vid, phase, cost, C0, outdir=run_dir)
            mm.append(m)
        results[vid] = tuple(mm)
        if time.time() - last > 50 or i == len(vids) - 1:
            log(f"{tag}: {i + 1}/{len(vids)} varyant tamam")
            last = time.time()
    return results


def _strip(m):
    return {k: v for k, v in m.items() if k not in ("flags",) and not k.startswith("_")}


def cmd_discovery(a, W=None):
    man = load_manifest(a.run)
    W = world_for(man, a, W)
    res = _phase(W, a.run, man, "DISCOVERY", C.VARIANT_IDS, "keşif")
    sel, rows = SL.select(res, "DISCOVERY")
    obj = dict(manifest_hash=man["manifest_hash"], phase="DISCOVERY", selected=sel,
               statuses={v: ("SELECTED_FOR_VALIDATION" if v in sel else None) for v in C.VARIANT_IDS},
               rows=rows, metrics={v: dict(NORMAL=_strip(res[v][0]), STRESS=_strip(res[v][1])) for v in res})
    obj["hash"] = sha_bytes(json.dumps(obj, sort_keys=True, default=_js).encode())
    write_json(os.path.join(a.run, "selection_discovery.json"), obj)
    log(f"keşif bitti: uygun {sum(r['eligible'] for r in rows)}, seçilen {sel}")
    return W, obj


def _verified(path, man):
    if not os.path.exists(path):
        raise SystemExit(f"{os.path.basename(path)} yok")
    obj = json.load(open(path))
    h = obj.pop("hash", None)
    if h != sha_bytes(json.dumps(obj, sort_keys=True, default=_js).encode()):
        raise SystemExit(f"{os.path.basename(path)} hash tutmuyor — değiştirilmiş; reddedildi")
    if obj.get("manifest_hash") != man["manifest_hash"]:
        raise SystemExit(f"{os.path.basename(path)} farklı manifestle üretilmiş — reddedildi")
    obj["hash"] = h
    return obj


def cmd_validation(a, W=None):
    man = load_manifest(a.run)
    p = os.path.join(a.run, "selection_discovery.json")
    if not os.path.exists(p):
        raise SystemExit("selection_discovery.json yok — doğrulama koşulamaz")
    disc = _verified(p, man)
    sel = disc["selected"]
    obj = dict(manifest_hash=man["manifest_hash"], phase="VALIDATION", candidates=sel, selected=[], rows=[])
    if sel:
        W = world_for(man, a, W)
        res = _phase(W, a.run, man, "VALIDATION", sel, "doğrulama")
        chosen, rows = SL.select(res, "VALIDATION")
        obj.update(selected=chosen, rows=rows,
                   statuses={v: ("SELECTED_FOR_FINAL" if v in chosen else "NOT_SELECTED") for v in sel},
                   metrics={v: dict(NORMAL=_strip(res[v][0]), STRESS=_strip(res[v][1])) for v in res})
    else:
        obj["skip_reason"] = "keşifte uygun aday yok"
    obj["hash"] = sha_bytes(json.dumps(obj, sort_keys=True, default=_js).encode())
    write_json(os.path.join(a.run, "selection_final.json"), obj)
    log(f"doğrulama: finale seçilen {obj['selected']}")
    return W, obj


def cmd_final(a, W=None):
    man = load_manifest(a.run)
    p = os.path.join(a.run, "selection_final.json")
    if not os.path.exists(p):
        raise SystemExit("selection_final.json yok — final performansı hesaplanamaz")
    sf = _verified(p, man)
    disc = _verified(os.path.join(a.run, "selection_discovery.json"), man)
    if not set(sf["selected"]) <= set(sf.get("candidates", [])) <= set(disc["selected"]):
        raise SystemExit("final adayı doğrulama/keşif seçimlerinin alt kümesi değil — reddedildi")
    if os.path.exists(os.path.join(a.run, "final_result.json")):
        raise SystemExit("final_result.json zaten var — aynı run_id ile ikinci final koşusu yapılmaz")
    obj = dict(manifest_hash=man["manifest_hash"], phase="FINAL", candidate=None)
    if not sf["selected"]:
        obj["skip_reason"] = "doğrulamadan uygun aday yok — final AÇILMADI"
    else:
        vid = sf["selected"][0]
        W = world_for(man, a, W)
        res = _phase(W, a.run, man, "FINAL", [vid], "final")
        mN, mS = res[vid]
        nets = sorted(mN.get("_trade_nets", []), reverse=True)
        top5 = float(sum(nets[5:])) if nets else 0.0
        indep = man["previous_data_use"]["FINAL"] == "untouched"
        dec, why = SL.final_decision(mN, mS, top5, indep)
        obj.update(candidate=vid, decision=dec, reason=why, top5_removed_net_USDT=top5, final_independent=indep,
                   metrics=dict(NORMAL=_strip(mN), STRESS=_strip(mS)))
    write_json(os.path.join(a.run, "final_result.json"), obj)
    return W, obj


def cmd_report(a):
    man = load_manifest(a.run)
    if os.path.exists(os.path.join(a.run, "RUN_FAILED.json")):
        raise SystemExit("RUN_FAILED — karar üretilmez (RUN_FAILED.json)")
    disc = json.load(open(os.path.join(a.run, "selection_discovery.json")))
    sf = json.load(open(os.path.join(a.run, "selection_final.json"))) if os.path.exists(
        os.path.join(a.run, "selection_final.json")) else None
    fin = json.load(open(os.path.join(a.run, "final_result.json"))) if os.path.exists(
        os.path.join(a.run, "final_result.json")) else None
    rows = []
    for ph, blob in (("DISCOVERY", disc), ("VALIDATION", sf), ("FINAL", fin)):
        if not blob or "metrics" not in blob:
            continue
        mets = blob["metrics"] if ph != "FINAL" else {blob["candidate"]: blob["metrics"]}
        for vid, mm in mets.items():
            for cost, m in mm.items():
                rows.append(dict(phase=ph, variant_id=vid, cost=cost, closed=m["closed"],
                                 signals=m.get("signals"), fills=m.get("fills"),
                                 expectancy_net_R=m.get("expectancy_net_R"), CI=m.get("nominal_CI"),
                                 LCB=m.get("LCB"), win_rate=m.get("win_rate"), PF_usdt=m.get("profit_factor_usdt"),
                                 PF_R=m.get("profit_factor_R"), net_USDT=m["net_USDT"], return_pct=m["return_pct"],
                                 MDD_close_pct=m["MDD_close_pct"], underwater_longest_h=m["underwater_longest_h"],
                                 entry_fees=m["entry_fees"], exit_fees=m["exit_fees"], funding=m["funding"],
                                 ambiguous_exits=m.get("ambiguous_exits"), metrics_valid=m["metrics_valid"],
                                 full_weeks=m["full_weeks"], weeks_with_trades=m["weeks_with_trades"],
                                 blocked=json.dumps(m.get("blocked_reasons", {}), ensure_ascii=False)))
    st = {r["variant_id"]: r for r in disc["rows"]}
    for r in rows:
        if r["phase"] == "DISCOVERY":
            r.update(status=st[r["variant_id"]]["status"], reason=st[r["variant_id"]]["reason"])
    write_csv(os.path.join(a.run, "variant_results.csv"), pd.DataFrame(rows))
    breakdowns(a.run)
    if fin and fin.get("decision"):
        decision, why = fin["decision"], fin["reason"]
    else:
        decision, why = SL.overall_without_final(disc["rows"], sf["rows"] if sf else [])
    summ = dict(run_id=man["run_id"], manifest_hash=man["manifest_hash"], decision=decision, reason=why,
                discovery_eligible=[r["variant_id"] for r in disc["rows"] if r["eligible"]],
                discovery_status_counts=pd.Series([r["reason"] for r in disc["rows"]]).value_counts().to_dict(),
                validation_selected=disc["selected"], final_selected=(sf or {}).get("selected"))
    write_json(os.path.join(a.run, "decision.json"), summ)
    print(json.dumps(summ, indent=1, ensure_ascii=False, default=_js))
    return summ


def _guarded(a, phase, fn, *args):
    """Yakalanmayan/yutulan istisna yok: hata RUN_FAILED olarak yazılır ve süreç sıfırdan farklı çıkar."""
    import traceback
    try:
        return fn(*args)
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        log(f"RUN_FAILED {phase}: {type(e).__name__}: {e}")
        if getattr(a, "run", None):
            write_json(os.path.join(a.run, "RUN_FAILED.json"), dict(status="RUN_FAILED", phase=phase,
                                                                    error=f"{type(e).__name__}: {e}", traceback=tb))
        raise SystemExit(2)


def breakdowns(run_dir):
    """Teşhis dökümleri (aday seçimi için KULLANILMAZ): yıl/çeyrek/coin/yön ve K/F grupları,
    F0↔F1 ortak market_event_id karşılaştırması. Boş dönemler de yazılır."""
    allr = []
    for vid in C.VARIANT_IDS:
        p = os.path.join(run_dir, "DISCOVERY", f"{vid}_NORMAL", "trades.csv")
        try:
            t = pd.read_csv(p)
        except Exception:
            continue
        if len(t):
            allr.append(t)
    if not allr:
        return
    t = pd.concat(allr, ignore_index=True)
    ts = pd.to_datetime(t["exit_interval_start"], unit="ms", utc=True)
    t["yil"], t["ceyrek"] = ts.dt.year, ts.dt.tz_localize(None).dt.to_period("Q").astype(str)
    t["L"], t["K"], t["F"] = zip(*t["variant_id"].str.split("_"))
    out = []
    for by in (["variant_id", "yil"], ["variant_id", "ceyrek"], ["variant_id", "symbol"], ["variant_id", "side"],
               ["L"], ["K"], ["F"], ["L", "K"]):
        g = t.groupby(by)
        df = pd.DataFrame(dict(islem=g.size(), ort_net_R=g["net_R"].mean(), toplam_net_R=g["net_R"].sum(),
                               net_USDT=g["net_PnL"].sum(), kazanma=g["net_PnL"].apply(lambda x: (x > 0).mean())))
        df = df.reset_index()
        df.insert(0, "kirilim", "+".join(by))
        out.append(df)
    write_csv(os.path.join(run_dir, "breakdowns_discovery_NORMAL.csv"), pd.concat(out, ignore_index=True))
    rows = []
    for L in C.LEVEL_FAMILIES:
        for K in C.ENTRY_MODELS:
            ev = {}
            for F in C.TREND_OPTS:
                p = os.path.join(run_dir, "DISCOVERY", f"{L}_{K}_{F}_NORMAL", "events.csv")
                try:
                    ev[F] = pd.read_csv(p).set_index("market_event_id")["terminal_status"]
                except Exception:
                    ev[F] = pd.Series(dtype=str)
            f0, f1 = ev["F0"], ev["F1"]
            sig0 = f0[~f0.isin(["K1_RECLAIM_MISSING", "K2_NOT_APPLICABLE", "K2_TIMEOUT", "K3_TIMEOUT", "K4_TIMEOUT",
                                "NO_MICRO_PIVOT", "STRUCTURE_ALREADY_BROKEN", "WEAK_FIRST_BREAK", "NO_FVG",
                                "FVG_INVALIDATED", "STOP_BEFORE_ENTRY", "LEVEL_EXPIRED", "DATA_INVALID",
                                "DOUBLE_SIDED_SWEEP", "BLOCKED_ACTIVE_SETUP", "INVALID_GEOMETRY", "CENSORED",
                                "INVALID_INDICATOR"])]
            rej = f1[f1.isin(["TREND_REJECTED", "INVALID_INDICATOR"])].index
            rej_in_f0 = sig0.reindex(rej).dropna()
            rows.append(dict(L=L, K=K, F0_sinyal=len(sig0), F1_trend_ret=len(rej),
                             F1_ret_edilenlerin_F0_dolumu=int((rej_in_f0 == "CLOSED").sum()),
                             F1_ret_edilenlerin_F0_portfoy_engeli=int((~rej_in_f0.isin(["CLOSED", "FILLED"])).sum())))
    write_csv(os.path.join(run_dir, "f0_f1_karsilastirma.csv"), pd.DataFrame(rows))


def cmd_run_all(a):
    if a.jobs != 1:
        raise SystemExit("yalnız --jobs 1 desteklenir (VPS'te canlı botla paralel iş açılmaz)")
    out, W = cmd_freeze(a)
    a.run = out
    W, _ = _guarded(a, "DISCOVERY", cmd_discovery, a, W)
    W, _ = _guarded(a, "VALIDATION", cmd_validation, a, W)
    W, _ = _guarded(a, "FINAL", cmd_final, a, W)
    return _guarded(a, "REPORT", cmd_report, a)


def main(argv=None):
    p = argparse.ArgumentParser(prog="liquidity_sweep_v1")
    p.add_argument("cmd", choices=["doctor", "verify", "freeze", "discovery", "validation", "final", "report",
                                   "run-all"])
    p.add_argument("--data", default=DEFAULT_DATA)
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--run", default=None)
    p.add_argument("--jobs", type=int, default=1)
    a = p.parse_args(argv)
    if a.cmd == "verify":
        from . import verify as V
        rep = V.main(a)
        if not rep.get("all_ok"):
            raise SystemExit(1)
        return rep
    {"doctor": cmd_doctor, "freeze": cmd_freeze, "discovery": cmd_discovery, "validation": cmd_validation,
     "final": cmd_final, "report": cmd_report, "run-all": cmd_run_all}[a.cmd](a)


if __name__ == "__main__":
    main()
