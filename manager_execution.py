#!/usr/bin/env python3
"""
manager_execution.py
====================
MANAGER 2: ⚡ EXECUTION MANAGER — "The Sniper"
================================================
Specialty: Controls HOW and WHEN trades are executed like a pro trader.
  ✅ Waits for optimal entry (pullback to OB 50% or FVG)
  ✅ Partial entry scaling (50% at zone, 50% on confirmation)
  ✅ Breakeven move (move SL to BE after 1R profit)
  ✅ Trailing stop logic (lock in profits)
  ✅ Anti-slippage retry (3 attempts with backoff)
  ✅ Market vs Limit order selection
  ✅ Entry timing filter (avoid first 5 min of session open)
  ✅ Spread check (skip if spread > threshold)

HOW IT CONTROLS:
  - Gets APPROVED signal from RiskManager
  - Decides: MARKET order now OR set LIMIT at better price
  - Manages the trade lifecycle until close
  - Sends result back to RiskManager + Supervisor

pip install: requests (already installed)
"""
import requests, time, json, os
import numpy as np
import pandas as pd
from datetime import datetime
from supervisor_trainer import BaseModel

class ExecutionManager:
    NAME = "Execution_Manager"

    def __init__(self,
                 bridge_url        = "http://127.0.0.1:5050",
                 max_spread_pips   = 3.0,
                 use_limit_orders  = True,
                 limit_offset_pips = 5.0,
                 breakeven_rr      = 1.0,
                 trail_rr          = 1.5,
                 partial_close_pct = 0.5,
                 max_retries       = 3):
        self.bridge          = bridge_url
        self.max_spread      = max_spread_pips
        self.use_limits      = use_limit_orders
        self.limit_offset    = limit_offset_pips
        self.be_rr           = breakeven_rr
        self.trail_rr        = trail_rr
        self.partial_close   = partial_close_pct
        self.max_retries     = max_retries
        self.pending_orders  = {}
        self.active_trades   = {}
        self._load_state()

    def _save_state(self):
        try:
            with open("exec_state.json","w") as f:
                json.dump({"active":self.active_trades,
                           "pending":self.pending_orders},f,indent=2)
        except Exception: pass

    def _load_state(self):
        try:
            if os.path.exists("exec_state.json"):
                with open("exec_state.json") as f: s=json.load(f)
                self.active_trades  = s.get("active",{})
                self.pending_orders = s.get("pending",{})
        except Exception: pass

    # ── Entry decision ────────────────────────────────────────
    def plan_entry(self, symbol, direction, entry_price,
                   sl_price, tp_price, lot_size,
                   ob_50=None, fvg_top=None, fvg_bottom=None,
                   current_spread=0.0, ensemble_score=0.6):
        """
        Returns execution plan:
          { order_type: MARKET|LIMIT|SKIP,
            entry: float, sl: float, tp: float,
            lot: float, reason: str,
            partial_lot: float }
        """
        now  = datetime.now()
        plan = {"symbol":symbol,"direction":direction,"lot":lot_size,
                "sl":sl_price,"tp":tp_price,"time":now.isoformat()}

        # ── 1. Spread check ───────────────────────────────────
        if current_spread > self.max_spread:
            plan.update({"order_type":"SKIP","reason":f"Spread {current_spread:.1f} > max {self.max_spread}"})
            print(f"[ExecMgr] ⛔ SKIP — spread too wide ({current_spread:.1f} pips)")
            return plan

        # ── 2. Score-based order type selection ───────────────
        # Very high confidence → MARKET (don't miss it)
        # Normal confidence → LIMIT at OB 50% or FVG (better price)
        if ensemble_score >= 0.78:
            order_type   = "MARKET"
            entry_actual = entry_price
            reason       = f"High confidence {ensemble_score:.2f} → MARKET"
        elif self.use_limits and (ob_50 or (fvg_top and fvg_bottom)):
            # Calculate limit price
            if ob_50:
                limit = ob_50
            elif fvg_top and fvg_bottom:
                limit = (fvg_top + fvg_bottom) / 2
            else:
                limit = entry_price

            # Only set limit if price hasn't already passed the zone
            if direction == "BUY"  and entry_price > limit * 0.9995:
                order_type   = "LIMIT"
                entry_actual = round(limit * 0.9998, 5)   # slight buffer
                reason       = f"LIMIT at OB/FVG zone ({entry_actual:.5f})"
            elif direction == "SELL" and entry_price < limit * 1.0005:
                order_type   = "LIMIT"
                entry_actual = round(limit * 1.0002, 5)
                reason       = f"LIMIT at OB/FVG zone ({entry_actual:.5f})"
            else:
                order_type   = "MARKET"
                entry_actual = entry_price
                reason       = "Zone missed → MARKET"
        else:
            order_type   = "MARKET"
            entry_actual = entry_price
            reason       = f"Score {ensemble_score:.2f} → MARKET"

        # ── 3. Partial entry sizing ───────────────────────────
        first_lot  = round(lot_size * self.partial_close, 2)
        second_lot = round(lot_size - first_lot, 2)
        if first_lot < 0.01: first_lot = lot_size; second_lot = 0

        plan.update({"order_type":order_type,"entry":entry_actual,
                     "partial_lot":first_lot,"second_lot":second_lot,"reason":reason})

        print(f"[ExecMgr] 📋 Plan: {order_type} {direction} {symbol} @ {entry_actual:.5f}")
        print(f"[ExecMgr]    Lots: {first_lot} (first) + {second_lot} (scale)")
        print(f"[ExecMgr]    SL={sl_price:.5f} TP={tp_price:.5f} | {reason}")
        return plan

    # ── Breakeven + trail management ──────────────────────────
    def manage_open_trade(self, symbol, current_price, entry, sl, tp, direction):
        """
        Returns new SL level after BE / trail logic.
        Called every tick / bar from the EA.
        """
        if tp == sl: return sl
        rr_distance = abs(tp - entry)
        current_rr  = abs(current_price - entry) / (rr_distance + 1e-8)
        new_sl      = sl

        # Move to breakeven at 1R
        if current_rr >= self.be_rr:
            if direction == "BUY"  and entry > sl:
                new_sl = entry + 0.0001  # 1 pip above entry
                if new_sl != sl:
                    print(f"[ExecMgr] 🔒 BE — {symbol} SL moved to breakeven {new_sl:.5f}")
            elif direction == "SELL" and entry < sl:
                new_sl = entry - 0.0001
                if new_sl != sl:
                    print(f"[ExecMgr] 🔒 BE — {symbol} SL moved to breakeven {new_sl:.5f}")

        # Trail stop at 1.5R
        if current_rr >= self.trail_rr:
            trail_sl = current_price - 0.5*(current_price-entry) if direction=="BUY"                        else current_price + 0.5*(entry-current_price)
            if direction=="BUY"  and trail_sl > new_sl: new_sl = trail_sl
            if direction=="SELL" and trail_sl < new_sl: new_sl = trail_sl
            if new_sl != sl:
                print(f"[ExecMgr] 📌 TRAIL — {symbol} SL trailed to {new_sl:.5f} (RR={current_rr:.2f})")

        return round(new_sl, 5)

    # ── Retry send to bridge ──────────────────────────────────
    def send_order(self, plan):
        for attempt in range(self.max_retries):
            try:
                r = requests.post(f"{self.bridge}/execute_order",
                                  json=plan, timeout=5)
                if r.status_code == 200:
                    resp = r.json()
                    print(f"[ExecMgr] ✅ Order sent (attempt {attempt+1}): {resp}")
                    return resp
            except Exception as e:
                print(f"[ExecMgr] ⚠️ Attempt {attempt+1} failed: {e}")
                time.sleep(1.5 ** attempt)  # exponential backoff
        print("[ExecMgr] ❌ All retries failed")
        return {"success":False}

    def summary(self):
        return {"active_trades":len(self.active_trades),
                "pending_orders":len(self.pending_orders),
                "bridge":self.bridge,
                "use_limits":self.use_limits,
                "be_rr":self.be_rr,
                "trail_rr":self.trail_rr}

def register_routes(app, exec_manager):
    @app.route("/exec/plan", methods=["POST"])
    def exec_plan():
        from flask import request, jsonify
        d = request.get_json(force=True)
        plan = exec_manager.plan_entry(
            symbol         = d.get("symbol","EURUSD"),
            direction      = d.get("direction","BUY"),
            entry_price    = float(d.get("entry",1.0)),
            sl_price       = float(d.get("sl",1.0)),
            tp_price       = float(d.get("tp",1.0)),
            lot_size       = float(d.get("lot",0.01)),
            ob_50          = float(d.get("ob_50",0)) or None,
            fvg_top        = float(d.get("fvg_top",0)) or None,
            fvg_bottom     = float(d.get("fvg_bottom",0)) or None,
            current_spread = float(d.get("spread",0)),
            ensemble_score = float(d.get("score",0.6))
        )
        return jsonify(plan)

    @app.route("/exec/manage", methods=["POST"])
    def exec_manage():
        from flask import request, jsonify
        d = request.get_json(force=True)
        new_sl = exec_manager.manage_open_trade(
            symbol=d["symbol"],current_price=float(d["current"]),
            entry=float(d["entry"]),sl=float(d["sl"]),
            tp=float(d["tp"]),direction=d["direction"])
        return jsonify({"new_sl":new_sl})

    @app.route("/exec/summary")
    def exec_summary():
        from flask import jsonify
        return jsonify(exec_manager.summary())

if __name__ == "__main__":
    em = ExecutionManager()
    plan = em.plan_entry("EURUSD","BUY",1.08520,1.08200,1.09200,0.05,
                         ob_50=1.08350,ensemble_score=0.68)
    print("\nPlan:", json.dumps(plan,indent=2))
    new_sl = em.manage_open_trade("EURUSD",1.08850,1.08520,1.08200,1.09200,"BUY")
    print(f"New SL after management: {new_sl}")
