"""
verify_3_fixes.py — 3 kritik duzeltmeyi somut kanitla dogrular.

  FIX 1: POSITION_CAP_FRACTION=5.0  -> BTC trade acabiliyor
  FIX 2: DAILY_MAX_LOSS_PCT=0.35    -> -30% devam, -37% durdurur
  FIX 3: Izole margin'de giris emrine leverage parametresi ekleniyor
         (sahte MEXC istemcisiyle create_order parametreleri yakalanir)

Hicbir canli emir gonderilmez. Tamamen yerel.
"""
from __future__ import annotations
import asyncio, os, sys

os.environ.setdefault("PAPER_MODE", "true")
os.environ.setdefault("SYMBOLS", "BTC,ETH,SOL,BNB,XRP")
os.environ.setdefault("MAX_RISK_PCT", "0.08")
os.environ.setdefault("RISK_SCALE", "1.25")
os.environ.setdefault("POSITION_CAP_FRACTION", "5.0")
os.environ.setdefault("MAX_POSITIONS", "15")
os.environ.setdefault("DAILY_MAX_LOSS_PCT", "0.35")
os.environ.setdefault("MEXC_API_KEY", "x")
os.environ.setdefault("MEXC_API_SECRET", "x")
for k in ("SYMBOL","TELEGRAM_TOKEN","TELEGRAM_CHAT_ID","NTFY_TOPIC",
          "WEB_DASHBOARD_TOKEN","DB_PATH","PRIMARY_TF","CONFIRM_TF",
          "MARGIN_MODE","NTFY_SERVER","FUNDING_MODE","ORDERFLOW_MODE","WHALE_MODE"):
    os.environ.setdefault(k, {"PRIMARY_TF":"1h","CONFIRM_TF":"4h","DB_PATH":"/tmp/v.db",
                              "MARGIN_MODE":"isolated","NTFY_SERVER":"https://ntfy.sh",
                              "FUNDING_MODE":"monitor","ORDERFLOW_MODE":"monitor",
                              "WHALE_MODE":"monitor"}.get(k,""))

PASS="\033[92mGECTI\033[0m"; FAIL="\033[91mKALDI\033[0m"
res=[]
def chk(n,ok,d=""):
    res.append(ok); print(f"  [{PASS if ok else FAIL}] {n}"+(f"  — {d}" if d else ""))

print("="*60); print("  3 KRITIK DUZELTME DOGRULAMA"); print("="*60)

# ── FIX 1 & 2: config + sizing + daily loss ──────────────────
from config import load_config
from risk import RiskManager, MIN_BTC_ORDER
cfg=load_config(); rm=RiskManager(cfg.risk)

print("\n[FIX 1] POSITION_CAP_FRACTION=5.0 -> BTC trade acilir")
chk("cap_fraction = 5.0", cfg.risk.position_cap_fraction==5.0, f"{cfg.risk.position_cap_fraction}")
s=rm.build_trade_setup(direction=1, entry_price=105000, atr=1000, balance=93.0,
                       leverage=10, symbol="BTC/USDT:USDT")
chk("BTC $105k'da trade acilir", s is not None and s.quantity>=MIN_BTC_ORDER,
    f"qty={s.quantity if s else 0:.4f} margin=${s.margin_required if s else 0:.2f}")
# eski bug kontrolu: cap=1.0 ile BTC BLOK olurdu
from config import RiskConfig
import copy
old=copy.copy(cfg.risk); old.position_cap_fraction=1.0
rm_old=RiskManager(old)
s_old=rm_old.build_trade_setup(direction=1, entry_price=105000, atr=1000,
                               balance=93.0, leverage=10, symbol="BTC/USDT:USDT")
chk("(eski cap=1.0 BTC'yi BLOK ederdi - bug dogrulandi)", s_old is None,
    "None" if s_old is None else f"qty={s_old.quantity:.4f}")

print("\n[FIX 2] DAILY_MAX_LOSS_PCT=0.35")
chk("daily_max_loss = 0.35", abs(cfg.risk.daily_max_loss-0.35)<1e-9, f"{cfg.risk.daily_max_loss}")
chk("-30% zararda DEVAM", rm.check_daily_loss_limit(93.0,65.0,0.0))
chk("-37% zararda DURDURUR", not rm.check_daily_loss_limit(93.0,58.0,0.0))
_o = copy.copy(cfg.risk); _o.daily_max_loss = 0.05
chk("(eski 0.05 ile -10% bile durdururdu - bug dogrulandi)",
    not RiskManager(_o).check_daily_loss_limit(93.0, 83.0, 0.0))

# ── FIX 3: izole margin leverage parametresi ─────────────────
print("\n[FIX 3] Izole margin giris emrinde leverage parametresi")
from exchange import LiveExchange

class FakeMexc:
    """create_order'a gelen params'i yakalayan sahte ccxt istemcisi."""
    def __init__(self): self.captured=[]
    def market(self, s): return {"contractSize": 0.0001 if "BTC" in s else 1.0}
    def amount_to_precision(self, s, a): return str(round(float(a), 3))
    async def create_order(self, symbol, typ, side, amount, price, params):
        self.captured.append({"type":typ,"params":dict(params)})
        # MEXC'in gercek davranisini taklit et: izole + leverage yoksa REDDET
        if params.get("openType")==1 and "leverage" not in params:
            raise Exception("mexc createSwapOrder() requires a leverage parameter "
                            "for isolated margin orders")
        return {"id":"123","average":price or 100.0,"status":"closed",
                "info":{"dealAvgPrice":price or 100.0}}
    async def fetch_order(self, oid, s):
        return {"status":"closed","average":100.0,"info":{}}

async def run_fix3():
    # IZOLE mod
    ex=LiveExchange("x","x",leverage=10,margin_mode="isolated")
    fake=FakeMexc(); ex._exchange=fake
    try:
        await ex.place_market_order("BTC/USDT:USDT","buy",0.003,{})
        mk_ok = any(c["params"].get("leverage")==10 for c in fake.captured)
        chk("MARKET emrinde leverage=10 var (izole)", mk_ok,
            f"params={fake.captured[-1]['params']}")
    except Exception as e:
        chk("MARKET emri (izole)", False, f"HATA: {str(e)[:50]}")

    # LIMIT (maker) izole
    fake2=FakeMexc(); ex._exchange=fake2
    try:
        await ex.place_limit_order("BTC/USDT:USDT","buy",0.003,100000.0,{})
        lm_ok = any(c["params"].get("leverage")==10 for c in fake2.captured)
        chk("LIMIT emrinde leverage=10 var (izole)", lm_ok,
            f"params={fake2.captured[0]['params']}")
    except Exception as e:
        chk("LIMIT emri (izole)", False, f"HATA: {str(e)[:50]}")

    # CROSS mod: leverage OLMAMALI (hesap seviyesinde)
    exc=LiveExchange("x","x",leverage=10,margin_mode="cross")
    fake3=FakeMexc(); exc._exchange=fake3
    try:
        await exc.place_market_order("BTC/USDT:USDT","buy",0.003,{})
        cross_no_lev = all("leverage" not in c["params"] for c in fake3.captured)
        chk("CROSS modda leverage EKLENMEZ (dogru)", cross_no_lev,
            f"openType={fake3.captured[-1]['params'].get('openType')}")
    except Exception as e:
        chk("CROSS emri", False, f"HATA: {str(e)[:50]}")

asyncio.run(run_fix3())

print("\n"+"="*60)
t=len(res); p=sum(res)
if p==t:
    print(f"  \033[92m3 DUZELTME DE DOGRULANDI: {p}/{t}\033[0m")
    print("  Sistem canli trade acmaya hazir.")
else:
    print(f"  \033[91m{t-p} KONTROL KALDI ({p}/{t})\033[0m")
print("="*60)
sys.exit(0 if p==t else 1)
