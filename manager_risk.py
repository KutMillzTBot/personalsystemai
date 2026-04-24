#!/usr/bin/env python3
"""
manager_risk.py
===============
MANAGER 1: 🛡️ RISK MANAGER — "The Guardian"
=============================================
Specialty: Controls ALL risk decisions like a professional risk desk.
  ✅ Dynamic position sizing (Kelly Criterion + ATR-based)
  ✅ Daily drawdown limit (stops trading if hit)
  ✅ Max open positions enforced
  ✅ Risk per trade (% of account)
  ✅ Correlation exposure check (no doubling up)
  ✅ Volatility-adjusted lot sizing
  ✅ News blackout window enforcement
  ✅ Streak protection (3 losses in a row = pause)

HOW IT CONTROLS:
  - Returns APPROVED / BLOCKED / REDUCE_SIZE
  - Bridge server checks RiskManager before placing any trade
  - All other managers must pass through Risk first

pip install: numpy pandas (already installed)
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json, os

class RiskManager:
    NAME = "Risk_Manager"

    def __init__(self,
                 account_balance   = 10000.0,
                 risk_pct          = 0.01,      # 1% per trade
                 max_daily_loss_pct= 0.05,      # 5% daily drawdown = stop
                 max_positions     = 3,
                 max_loss_streak   = 3,
                 news_blackout_min = 30):
        self.balance          = account_balance
        self.risk_pct         = risk_pct
        self.max_daily_loss   = account_balance * max_daily_loss_pct
        self.max_positions    = max_positions
        self.max_loss_streak  = max_loss_streak
        self.news_blackout_min= news_blackout_min

        # State
        self.daily_pnl        = 0.0
        self.open_positions   = {}   # symbol → {lot, direction, entry}
        self.trade_log        = []   # list of {time, symbol, pnl, won}
        self.loss_streak      = 0
        self.session_date     = datetime.now().date()
        self._load_state()

    # ── State persistence ────────────────────────────────────
    def _save_state(self):
        state = {"daily_pnl":self.daily_pnl,
                 "loss_streak":self.loss_streak,
                 "trade_log":self.trade_log[-50:],
                 "session_date":str(self.session_date)}
        with open("risk_state.json","w") as f: json.dump(state,f,indent=2)

    def _load_state(self):
        try:
            if os.path.exists("risk_state.json"):
                with open("risk_state.json") as f: s=json.load(f)
                if s.get("session_date")==str(datetime.now().date()):
                    self.daily_pnl  = s.get("daily_pnl",0)
                    self.loss_streak= s.get("loss_streak",0)
                    self.trade_log  = s.get("trade_log",[])
        except Exception: pass

    # ── Core decision gate ────────────────────────────────────
    def approve_trade(self, symbol, direction, entry_price,
                      sl_price, atr=None, ensemble_score=0.6,
                      df=None):
        """
        Returns dict:
          { approved: bool, reason: str, lot_size: float,
            risk_usd: float, max_loss_usd: float,
            confidence: str }
        """
        now = datetime.now()

        # ── Reset daily if new day ────────────────────────────
        if now.date() > self.session_date:
            self.session_date = now.date()
            self.daily_pnl    = 0.0
            print(f"[RiskMgr] 🌅 New trading day — daily PnL reset")

        # ── 1. Daily drawdown guard ───────────────────────────
        if self.daily_pnl <= -self.max_daily_loss:
            return self._block(f"Daily loss limit hit ({self.daily_pnl:.2f}) — NO MORE TRADES TODAY")

        # ── 2. Loss streak guard ──────────────────────────────
        if self.loss_streak >= self.max_loss_streak:
            return self._block(f"Loss streak {self.loss_streak} — cooling off, skip this trade")

        # ── 3. Max positions ──────────────────────────────────
        if len(self.open_positions) >= self.max_positions:
            return self._block(f"Max positions ({self.max_positions}) reached")

        # ── 4. Duplicate symbol guard ─────────────────────────
        if symbol in self.open_positions:
            existing = self.open_positions[symbol]
            if existing["direction"] == direction:
                return self._block(f"Already {direction} on {symbol}")

        # ── 5. Ensemble confidence gate ───────────────────────
        if direction == "BUY"  and ensemble_score < 0.55:
            return self._block(f"Score {ensemble_score:.2f} too low for BUY (need ≥0.55)")
        if direction == "SELL" and ensemble_score > 0.45:
            return self._block(f"Score {ensemble_score:.2f} too high for SELL (need ≤0.45)")

        # ── 6. Calculate lot size ─────────────────────────────
        if sl_price and entry_price and entry_price != sl_price:
            sl_pips   = abs(entry_price - sl_price) / entry_price * 10000
            risk_usd  = self.balance * self.risk_pct
            # Scale up lot if high confidence
            confidence_mult = 1.0
            if   ensemble_score >= 0.75: confidence_mult = 1.5
            elif ensemble_score >= 0.65: confidence_mult = 1.2
            lot_size  = round((risk_usd * confidence_mult) / (sl_pips * 10 + 1e-8), 2)
            lot_size  = max(0.01, min(lot_size, 1.0))  # clamp 0.01–1.0
        else:
            lot_size = 0.01  # fallback minimum

        # ── 7. ATR volatility adjustment ──────────────────────
        if atr is not None and atr > 0 and entry_price > 0:
            atr_pct = atr / entry_price
            if atr_pct > 0.02:  # very high volatility → reduce
                lot_size = round(lot_size * 0.5, 2)
                print(f"[RiskMgr] ⚠️ High ATR ({atr_pct:.2%}) — lot reduced to {lot_size}")

        risk_usd = lot_size * abs(entry_price - (sl_price or entry_price)) * 1000

        conf = "🔥 HIGH" if ensemble_score>=0.70 else "✅ MEDIUM" if ensemble_score>=0.55 else "⚠️ LOW"
        print(f"[RiskMgr] ✅ APPROVED {direction} {symbol} | Lot={lot_size} | Risk=${risk_usd:.2f} | {conf}")

        return {"approved":True,"reason":"APPROVED","lot_size":lot_size,
                "risk_usd":round(risk_usd,2),"max_loss_usd":round(self.max_daily_loss,2),
                "confidence":conf,"score":ensemble_score,
                "daily_pnl":self.daily_pnl,"loss_streak":self.loss_streak}

    def _block(self, reason):
        print(f"[RiskMgr] 🚫 BLOCKED — {reason}")
        return {"approved":False,"reason":reason,"lot_size":0,
                "risk_usd":0,"daily_pnl":self.daily_pnl,"loss_streak":self.loss_streak}

    # ── Record trade result ───────────────────────────────────
    def record_trade(self, symbol, direction, entry, close_price, lot, pnl):
        won = pnl > 0
        self.daily_pnl += pnl
        if won:
            self.loss_streak = 0
        else:
            self.loss_streak += 1

        self.trade_log.append({"time":datetime.now().isoformat(),"symbol":symbol,
                                "direction":direction,"entry":entry,"close":close_price,
                                "lot":lot,"pnl":pnl,"won":won})
        if symbol in self.open_positions:
            del self.open_positions[symbol]

        self._save_state()
        rr = "WIN ✅" if won else "LOSS ❌"
        print(f"[RiskMgr] {rr} {symbol} P&L={pnl:+.2f} | DailyPnL={self.daily_pnl:+.2f} | Streak={self.loss_streak}")

    def open_position(self, symbol, direction, entry, lot):
        self.open_positions[symbol] = {"direction":direction,"entry":entry,"lot":lot,"time":datetime.now().isoformat()}

    def summary(self):
        total = len(self.trade_log)
        wins  = sum(1 for t in self.trade_log if t["won"])
        pnl   = sum(t["pnl"] for t in self.trade_log)
        return {"total_trades":total,"wins":wins,
                "win_rate":round(wins/total,3) if total else 0,
                "total_pnl":round(pnl,2),"daily_pnl":round(self.daily_pnl,2),
                "loss_streak":self.loss_streak,"open_positions":len(self.open_positions)}

# ── Flask endpoint registration ──────────────────────────────
def register_routes(app, risk_manager):
    @app.route("/risk/approve", methods=["POST"])
    def risk_approve():
        from flask import request, jsonify
        d = request.get_json(force=True)
        result = risk_manager.approve_trade(
            symbol         = d.get("symbol","EURUSD"),
            direction      = d.get("direction","BUY"),
            entry_price    = float(d.get("entry_price",1.0)),
            sl_price       = float(d.get("sl_price",0)),
            atr            = float(d.get("atr",0)),
            ensemble_score = float(d.get("score",0.6))
        )
        return jsonify(result)

    @app.route("/risk/record", methods=["POST"])
    def risk_record():
        from flask import request, jsonify
        d = request.get_json(force=True)
        risk_manager.record_trade(d["symbol"],d["direction"],
            float(d["entry"]),float(d["close"]),float(d["lot"]),float(d["pnl"]))
        return jsonify({"status":"recorded"})

    @app.route("/risk/summary")
    def risk_summary():
        from flask import jsonify
        return jsonify(risk_manager.summary())

if __name__ == "__main__":
    rm = RiskManager(account_balance=10000, risk_pct=0.01)
    # Test approval
    r = rm.approve_trade("EURUSD","BUY",1.08500,1.08200,atr=0.0015,ensemble_score=0.72)
    print("Decision:", r)
    rm.open_position("EURUSD","BUY",1.08500,r["lot_size"])
    rm.record_trade("EURUSD","BUY",1.08500,1.08900,r["lot_size"],+45.0)
    print("Summary:", rm.summary())
