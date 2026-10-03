"""GELİŞTİRİCİ TESTİ — gerçek borsaya BAĞLANMAZ. Kullanım: python3 trend_hazirlik/sahte_borsa_testi.py normal
Deneme betiğini SAHTE borsayla uçtan uca koş (ağ yok). Senaryolar: normal, test sırasında SIGINT, temizlikte SIGINT."""
import asyncio, json, os, signal, sys, tempfile, types, importlib.util, itertools
SENARYO = sys.argv[1]
ids = itertools.count(1000)

class Sahte:
    def __init__(self, cfg):
        self.poz = {}            # positionType -> holdVol
        self.stop = []           # ekli stoplar
        self.plan = []
        self.last_http_response = None
        self.markets = {}
        self.has = {}
        self.yazma = 0
    async def load_markets(self):
        self.markets = {"DOT/USDT:USDT": {"id": "DOT_USDT", "baseId": "DOT", "swap": True, "linear": True,
                                          "info": {"contractSize": 0.1, "minVol": 1}}}
    def market(self, s): return self.markets[s]
    async def fetch_ticker(self, s): return {"last": 4.0}
    def price_to_precision(self, s, p): return f"{p:.3f}"
    def init_throttler(self): pass
    async def set_leverage(self, *a, **k): self.yazma += 1
    def _yan(self, d): self.last_http_response = json.dumps(d); return d
    async def create_order(self, sym, typ, side, vol, price, params):
        self.yazma += 1
        await asyncio.sleep(0.05)
        oid = str(next(ids))
        if "triggerPrice" in params:
            self.plan.append({"symbol": "DOT_USDT", "id": oid, "vol": vol, "triggerPrice": params["triggerPrice"],
                              "executeCycle": params.get("executeCycle")})
            self._yan({"success": True, "code": 0, "data": int(oid)}); return {"id": None}
        ro = params.get("reduceOnly")
        if ro:
            pt = 1 if side == "sell" else 2
            self.poz[pt] = max(0, self.poz.get(pt, 0) - vol)
            if self.poz[pt] == 0:
                self.stop = [s for s in self.stop if s["pt"] != pt]
        else:
            pt = 1 if side == "buy" else 2
            self.poz[pt] = self.poz.get(pt, 0) + vol
            if "stopLossPrice" in params:
                self.stop.append({"symbol": "DOT_USDT", "id": str(next(ids)), "orderId": oid, "pt": pt,
                                  "stopLossPrice": params["stopLossPrice"], "vol": vol})
        self._yan({"success": True, "code": 0, "data": {"orderId": oid}}); return {"id": oid}
    async def contractPrivateGetPositionPositionMode(self, p): return {"success": True, "code": 0, "data": 1}
    async def contractPrivateGetPositionOpenPositions(self, p):
        await asyncio.sleep(0.02)
        return {"success": True, "code": 0, "data": [{"symbol": "DOT_USDT", "positionType": k, "holdVol": v}
                                                     for k, v in self.poz.items() if v > 0]}
    async def contractPrivateGetStoporderOpenOrders(self, p): return {"success": True, "code": 0, "data": list(self.stop)}
    async def contractPrivateGetPlanorderListOrders(self, p): return {"success": True, "code": 0, "data": list(self.plan)}
    async def contractPrivateGetOrderListOpenOrdersSymbol(self, p): return {"success": True, "code": 0, "data": []}
    async def contractPrivatePostPlanorderCancel(self, lst):
        self.yazma += 1; ids_ = {x["orderId"] for x in lst}; self.plan = [o for o in self.plan if o["id"] not in ids_]
        return {"success": True, "code": 0}
    async def contractPrivatePostStoporderCancel(self, lst):
        self.yazma += 1; ids_ = {x["stopPlanOrderId"] for x in lst}; self.stop = [o for o in self.stop if o["id"] not in ids_]
        return {"success": True, "code": 0}
    async def contractPrivatePostOrderCancel(self, lst): self.yazma += 1; return {"success": True, "code": 0}
    async def close(self): pass

SON = {}
def fab(cfg):
    e = Sahte(cfg); SON["e"] = e; return e
pro = types.ModuleType("ccxt.pro"); pro.mexc = fab
import ccxt
ccxt.pro = pro; sys.modules["ccxt.pro"] = pro
cfgmod = types.ModuleType("config")
cfgmod.load_config = lambda: types.SimpleNamespace(exchange=types.SimpleNamespace(
    paper_mode=False, api_key="k", api_secret="s", symbols=["SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT"]))
sys.modules["config"] = cfgmod
spec = importlib.util.spec_from_file_location("d", os.path.join(os.path.dirname(os.path.abspath(__file__)), "mexc_hedge_deneme.py"))
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)
d.CIKTI = os.path.join(tempfile.gettempdir(), f"mexc_deneme_sahte_{SENARYO}.json")
_orig_sleep = asyncio.sleep
async def hizli(t, *a, **k): return await _orig_sleep(min(t, 0.05))
d.asyncio.sleep = hizli    # betik içindeki uyumaları kısalt (asyncio modülünü global yamamak yerine)
argv = ["x"] + (["--evet"] if SENARYO != "kuru" else []) + (["--coin", "SOL"] if SENARYO == "botcoin" else [])
sys.argv = argv

async def kos():
    loop = asyncio.get_running_loop()
    if SENARYO == "test_sirasinda_sigint":
        loop.call_later(0.35, os.kill, os.getpid(), signal.SIGINT)
    if SENARYO == "temizlikte_sigint":
        async def bekle():
            while not d.Deneme or "temizlik" not in (SON.get("rapor") or {}):
                await _orig_sleep(0.01)
        loop.call_later(1.2, os.kill, os.getpid(), signal.SIGINT)
        loop.call_later(1.25, os.kill, os.getpid(), signal.SIGINT)
    await d.main()
try:
    asyncio.run(kos())
except (KeyboardInterrupt, asyncio.CancelledError):
    print("KeyboardInterrupt dışarı çıktı")
e = SON.get("e")
r = json.load(open(d.CIKTI)) if os.path.exists(d.CIKTI) else {}
print(f"\n### {SENARYO}: yazma={e.yazma if e else None} poz={e.poz if e else None} stop={len(e.stop) if e else None} "
      f"plan={len(e.plan) if e else None} temizlik={r.get('temizlik')}")
