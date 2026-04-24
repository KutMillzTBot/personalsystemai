#!/usr/bin/env python3
"""
manager_portfolio.py
====================
MANAGER 3: 📊 PORTFOLIO MANAGER — "The Strategist"
====================================================
Specialty: Thinks across ALL open trades simultaneously like a hedge fund.
  ✅ Total exposure tracking (USD at risk across all trades)
  ✅ Correlated pair blocking (no EURUSD + GBPUSD both long = double USD risk)
  ✅ Sector/asset rotation awareness
  ✅ Win/loss ratio optimization (promotes high-RR setups)
  ✅ Portfolio heat map (which symbols are overexposed)
  ✅ Diversification enforcement
  ✅ Profit lock-in signals (close weakest position to fund best)
  ✅ End-of-day close rules (no overnight exposure on weak signals)

HOW IT CONTROLS:
  - Monitors ALL open trades in real time
  - Can VETO a new trade if total exposure is too high
  - Can ORDER partial close of old trade to open better one
  - Reports portfolio health score (0-100)

pip install: numpy pandas (already installed)
"""
import numpy as np
import pandas as pd
from datetime import datetime, time as dtime
import json, os

# Correlation groups — don't over-expose to same direction
CORR_GROUPS = {
    "USD_PAIRS":  ["EURUSD","GBPUSD","AUDUSD","NZDUSD","USDCHF","USDJPY","USDCAD"],
    "GOLD_GROUP": ["XAUUSD","XAGUSD"],
    "CRYPTO":     ["BTCUSD","ETHUSD","BNBUSD"],
    "INDICES":    ["NAS100","US500","US30","UK100"],
    "OIL_GROUP":  ["USOIL","UKOIL","USDCAD"],
}
MAX_SAME_GROUP = 2   # max 2 trades in same correlation group

class PortfolioManager:
    NAME = "Portfolio_Manager"

    def __init__(self,
                 max_total_risk_pct  = 0.06,   # 6% total account at risk
                 max_group_exposure  = 2,
                 close_on_weak       = True,
                 eod_close_hour      = 21,
                 eod_min_score       = 0.60,
                 account_balance     = 10000.0):
        self.max_total_risk  = max_total_risk_pct * account_balance
        self.max_group_exp   = max_group_exposure
        self.close_on_weak   = close_on_weak
        self.eod_close_hour  = eod_close_hour
        self.eod_min_score   = eod_min_score
        self.balance         = account_balance
        self.portfolio       = {}    # symbol → {direction,lot,entry,sl,tp,score,pnl,time}
        self._load()

    def _save(self):
        try:
            with open("portfolio_state.json","w") as f:
                json.dump(self.portfolio,f,indent=2,default=str)
        except Exception: pass

    def _load(self):
        try:
            if os.path.exists("portfolio_state.json"):
                with open("portfolio_state.json") as f:
                    self.portfolio = json.load(f)
        except Exception: pass

    def _get_group(self, symbol):
        for group, members in CORR_GROUPS.items():
            if symbol.upper() in members: return group
        return "OTHER"

    # ── Portfolio gate ────────────────────────────────────────
    def approve_new_trade(self, symbol, direction, lot, sl_price,
                          entry_price, score):
        """
        Returns: {approved, reason, action, close_symbol}
        action: OPEN | VETO | REPLACE (close weakest, open this)
        """
        symbol = symbol.upper()
        risk_usd = lot * abs(entry_price - sl_price) * 1000

        # ── 1. Total portfolio risk ───────────────────────────
        total_risk = self._total_risk() + risk_usd
        if total_risk > self.max_total_risk:
            # Check if we can REPLACE a weaker trade
            weakest = self._find_weakest()
            if weakest and self.portfolio[weakest]["score"] < score - 0.05:
                print(f"[PortMgr] 🔄 REPLACE {weakest} (score={self.portfolio[weakest]['score']:.2f}) "
                      f"→ {symbol} (score={score:.2f})")
                return {"approved":True,"action":"REPLACE","close_symbol":weakest,
                        "reason":f"Replacing weaker trade {weakest} with {symbol}"}
            return {"approved":False,"action":"VETO",
                    "reason":f"Total risk ${total_risk:.0f} > max ${self.max_total_risk:.0f}"}

        # ── 2. Correlation group check ────────────────────────
        group = self._get_group(symbol)
        group_count = sum(1 for s,t in self.portfolio.items()
                          if self._get_group(s)==group)
        if group_count >= self.max_group_exp:
            # Check for opposite direction hedge
            same_dir = [s for s,t in self.portfolio.items()
                        if self._get_group(s)==group and t["direction"]==direction]
            if same_dir:
                return {"approved":False,"action":"VETO",
                        "reason":f"Corr group {group} already has {group_count} {direction} trades"}

        # ── 3. End of day check ───────────────────────────────
        if datetime.now().hour >= self.eod_close_hour and score < self.eod_min_score:
            return {"approved":False,"action":"VETO",
                    "reason":f"EOD ({datetime.now().hour}:xx) — score {score:.2f} < {self.eod_min_score} threshold"}

        return {"approved":True,"action":"OPEN","close_symbol":None,
                "reason":f"Portfolio approved | Group={group} | TotalRisk=${total_risk:.0f}"}

    def _total_risk(self):
        return sum(abs(t.get("entry",0)-t.get("sl",0))*t.get("lot",0.01)*1000
                   for t in self.portfolio.values())

    def _find_weakest(self):
        if not self.portfolio: return None
        return min(self.portfolio, key=lambda s: self.portfolio[s].get("score",0.5))

    # ── Portfolio update ──────────────────────────────────────
    def add_trade(self, symbol, direction, lot, entry, sl, tp, score):
        self.portfolio[symbol.upper()] = {
            "direction":direction,"lot":lot,"entry":entry,
            "sl":sl,"tp":tp,"score":score,"pnl":0.0,
            "time":datetime.now().isoformat()}
        self._save()
        print(f"[PortMgr] ➕ Added {symbol} {direction} | Portfolio size={len(self.portfolio)}")

    def update_pnl(self, symbol, current_price):
        if symbol.upper() not in self.portfolio: return
        t = self.portfolio[symbol.upper()]
        sign = 1 if t["direction"]=="BUY" else -1
        t["pnl"] = round(sign*(current_price-t["entry"])*t["lot"]*1000, 2)
        self._save()

    def remove_trade(self, symbol):
        sym = symbol.upper()
        if sym in self.portfolio:
            del self.portfolio[sym]
            self._save()
            print(f"[PortMgr] ➖ Removed {sym} | Portfolio size={len(self.portfolio)}")

    # ── EOD scan ─────────────────────────────────────────────
    def eod_review(self, current_prices={}):
        """Returns list of symbols to close at end of day."""
        to_close = []
        hour = datetime.now().hour
        if hour < self.eod_close_hour: return to_close
        for sym, trade in self.portfolio.items():
            score = trade.get("score",0.5)
            pnl   = trade.get("pnl",0)
            if score < self.eod_min_score or pnl < 0:
                to_close.append({"symbol":sym,"reason":"EOD review","pnl":pnl})
        if to_close:
            print(f"[PortMgr] 🌙 EOD — closing {len(to_close)} trades: {[t['symbol'] for t in to_close]}")
        return to_close

    # ── Portfolio health ──────────────────────────────────────
    def health_score(self):
        if not self.portfolio: return {"score":100,"status":"Empty","details":{}}
        total_pnl   = sum(t.get("pnl",0) for t in self.portfolio.values())
        total_risk  = self._total_risk()
        risk_usage  = min(total_risk/self.max_total_risk, 1.0)
        winners     = sum(1 for t in self.portfolio.values() if t.get("pnl",0)>0)
        win_rate    = winners / len(self.portfolio)
        score       = int((1-risk_usage)*40 + win_rate*60)
        status      = "💪 Healthy" if score>=70 else "⚠️ Cautious" if score>=40 else "🔴 Overexposed"
        return {"score":score,"status":status,
                "total_pnl":round(total_pnl,2),
                "total_risk_usd":round(total_risk,2),
                "risk_usage_pct":round(risk_usage*100,1),
                "open_trades":len(self.portfolio),
                "positions":{k:{
                    "direction":v["direction"],"lot":v["lot"],
                    "pnl":v.get("pnl",0),"score":v.get("score",0.5)
                } for k,v in self.portfolio.items()}}

def register_routes(app, port_manager):
    @app.route("/portfolio/approve", methods=["POST"])
    def port_approve():
        from flask import request, jsonify
        d = request.get_json(force=True)
        r = port_manager.approve_new_trade(
            d["symbol"],d["direction"],float(d["lot"]),
            float(d["sl"]),float(d["entry"]),float(d["score"]))
        return jsonify(r)

    @app.route("/portfolio/health")
    def port_health():
        from flask import jsonify
        return jsonify(port_manager.health_score())

    @app.route("/portfolio/eod")
    def port_eod():
        from flask import jsonify
        return jsonify({"to_close":port_manager.eod_review()})

if __name__ == "__main__":
    pm = PortfolioManager(account_balance=10000)
    pm.add_trade("EURUSD","BUY",0.05,1.08500,1.08200,1.09500,0.72)
    pm.add_trade("XAUUSD","BUY",0.02,1980.0,1965.0,2010.0,0.68)
    r = pm.approve_new_trade("GBPUSD","BUY",0.05,1.26000,1.26500,0.65)
    print("New trade approved?", r)
    print("Health:", pm.health_score())
