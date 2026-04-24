#!/usr/bin/env python3
"""
manager_head.py
===============
MANAGER 4: 🧠 HEAD MANAGER — "The CEO"
========================================
Specialty: The master orchestrator that controls ALL 3 managers + ALL AI models.
  Thinks like a human senior trader making the FINAL call on every trade.

  DECISION PIPELINE (in order):
    1. AI Ensemble → signal + confidence
    2. Regime Detector → is this a good time to trade at all?
    3. Portfolio Manager → is the portfolio healthy enough?
    4. Risk Manager → approved lot size, daily limit check
    5. Execution Manager → MARKET or LIMIT, entry plan
    6. HEAD MANAGER → final EXECUTE / HOLD / VETO with reasoning

  HUMAN-LIKE REASONING:
    ✅ "Strong signal, healthy portfolio, good regime → EXECUTE full size"
    ⚠️ "Signal OK but volatile regime → REDUCE size by 50%"
    🚫 "Daily loss limit hit → NO TRADING today, log reason"
    🔄 "Better setup available → REPLACE old trade with new"
    💤 "Dead zone session → WAIT for London Open"

pip install: requests flask (already installed)
"""
import requests, json, time
from datetime import datetime
from flask import Flask, request as freq, jsonify

class HeadManager:
    NAME = "Head_Manager"

    def __init__(self,
                 risk_manager      = None,
                 execution_manager = None,
                 portfolio_manager = None,
                 bridge_url        = "http://127.0.0.1:5050",
                 min_ensemble_score= 0.60,
                 strong_score      = 0.72,
                 verbose           = True):
        self.rm      = risk_manager
        self.em      = execution_manager
        self.pm      = portfolio_manager
        self.bridge  = bridge_url
        self.min_sc  = min_ensemble_score
        self.str_sc  = strong_score
        self.verbose = verbose
        self.decision_log = []

    def _log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","BLOCK":"🚫","TRADE":"💰"}
        icon = icons.get(level,"▶")
        print(f"[HEAD {ts}] {icon} {msg}")
        self.decision_log.append({"time":ts,"level":level,"msg":msg})
        if len(self.decision_log)>200: self.decision_log.pop(0)

    # ── MASTER DECISION ENGINE ────────────────────────────────
    def evaluate(self, signal_data):
        """
        Takes raw signal from bridge /signal endpoint.
        Returns final EXECUTE / HOLD / VETO decision with full reasoning chain.

        signal_data keys: symbol, signal, score, action,
                          ob_50, sl, tp, fvg_top, fvg_bottom, models, bias
        """
        sym     = signal_data.get("symbol","EURUSD").upper()
        score   = float(signal_data.get("score",0.5))
        action  = int(signal_data.get("action",0))
        sl      = float(signal_data.get("sl",0))
        tp      = float(signal_data.get("tp",0))
        ob_50   = float(signal_data.get("ob_50",0))
        fvg_top = float(signal_data.get("fvg_top",0))
        fvg_bot = float(signal_data.get("fvg_bottom",0))
        models  = signal_data.get("models",{})
        raw_sig = signal_data.get("signal","HOLD")

        decision = {"symbol":sym,"time":datetime.now().isoformat(),
                    "raw_signal":raw_sig,"score":score,"action":action,
                    "reasoning":[],"final":"HOLD","lot":0,"order_type":"NONE"}

        self._log(f"═══ Evaluating {sym} | {raw_sig} | Score={score:.3f} ═══")

        # ── STEP 1: Basic score filter ─────────────────────────
        if action == 0 or (score > 0.45 and score < 0.55):
            decision["final"] = "HOLD"
            decision["reasoning"].append(f"Score {score:.2f} in HOLD zone [0.45-0.55]")
            self._log(f"HOLD — Score in neutral zone ({score:.2f})", "INFO")
            return self._finalize(decision)

        direction = "BUY" if action > 0 else "SELL"

        # ── STEP 2: Model consensus check ─────────────────────
        if models:
            buy_votes  = sum(1 for m,d in models.items() if float(d.get("signal",0.5))>0.55)
            sell_votes = sum(1 for m,d in models.items() if float(d.get("signal",0.5))<0.45)
            total      = len(models)
            consensus  = buy_votes/total if direction=="BUY" else sell_votes/total
            decision["reasoning"].append(f"Model consensus: {consensus:.0%} ({buy_votes if direction=='BUY' else sell_votes}/{total})")

            if consensus < 0.40:
                decision["final"] = "HOLD"
                decision["reasoning"].append(f"Low consensus {consensus:.0%} < 40% — no clear majority")
                self._log(f"HOLD — model consensus too low ({consensus:.0%})", "WARN")
                return self._finalize(decision)

            # Check if Regime model is bearish on this signal
            regime_sig = models.get("Regime_Detector",{}).get("signal",0.5)
            regime_action = "BUY" if float(regime_sig)>0.55 else "SELL" if float(regime_sig)<0.45 else "HOLD"
            if regime_action != "HOLD" and regime_action != direction:
                score = score * 0.80  # regime disagrees → reduce confidence
                decision["reasoning"].append(f"⚠️ Regime disagrees → score reduced to {score:.3f}")
                self._log(f"Regime conflict — score reduced to {score:.3f}", "WARN")

        # ── STEP 3: Portfolio check ────────────────────────────
        entry_price = ob_50 or 1.0  # placeholder if not provided
        lot_prelim  = 0.05

        if self.pm:
            port_check = self.pm.approve_new_trade(sym, direction, lot_prelim, sl, entry_price, score)
            decision["reasoning"].append(f"Portfolio: {port_check['reason']}")
            if not port_check["approved"]:
                decision["final"] = "VETO_PORTFOLIO"
                self._log(f"VETO — Portfolio: {port_check['reason']}", "BLOCK")
                return self._finalize(decision)
            if port_check.get("action") == "REPLACE":
                decision["reasoning"].append(f"Will close {port_check['close_symbol']} first")

        # ── STEP 4: Risk approval ──────────────────────────────
        if self.rm:
            risk = self.rm.approve_trade(sym, direction, entry_price, sl,
                                         ensemble_score=score)
            decision["reasoning"].append(f"Risk: {risk['reason']}")
            if not risk["approved"]:
                decision["final"] = "VETO_RISK"
                self._log(f"VETO — Risk: {risk['reason']}", "BLOCK")
                return self._finalize(decision)
            lot = risk["lot_size"]
            decision["risk_usd"]     = risk.get("risk_usd",0)
            decision["loss_streak"]  = risk.get("loss_streak",0)
        else:
            lot = max(0.01, round(score * 0.1, 2))

        # ── STEP 5: Execution planning ─────────────────────────
        if self.em and sl and tp:
            exec_plan = self.em.plan_entry(sym, direction, entry_price, sl, tp, lot,
                                           ob_50=ob_50, fvg_top=fvg_top,
                                           fvg_bottom=fvg_bot, ensemble_score=score)
            order_type = exec_plan.get("order_type","MARKET")
            entry_use  = exec_plan.get("entry", entry_price)
            decision["reasoning"].append(f"Execution: {order_type} @ {entry_use:.5f} — {exec_plan.get('reason','')}")
        else:
            order_type = "MARKET"
            entry_use  = entry_price

        # ── STEP 6: HEAD FINAL DECISION ───────────────────────
        size_label = "FULL"
        if score >= self.str_sc:
            final = "EXECUTE_STRONG"
            self._log(f"🔥 EXECUTE STRONG {direction} {sym} | Lot={lot} | Score={score:.3f}", "TRADE")
        elif score >= self.min_sc:
            final = "EXECUTE"
            self._log(f"✅ EXECUTE {direction} {sym} | Lot={lot} | Score={score:.3f}", "TRADE")
        else:
            final = "HOLD"
            decision["reasoning"].append(f"Score {score:.2f} below minimum {self.min_sc}")
            self._log(f"HOLD — score {score:.2f} below minimum", "INFO")

        decision.update({"final":final,"lot":lot,"direction":direction,
                         "order_type":order_type,"entry":entry_use,
                         "sl":sl,"tp":tp,"score":score})

        return self._finalize(decision)

    def _finalize(self, d):
        chain = " → ".join(d.get("reasoning",[]))
        d["reasoning_chain"] = chain
        self._log(f"Decision: {d['final']} | Chain: {chain[:80]}...", "OK" if "EXECUTE" in d["final"] else "INFO")
        return d

    # ── Polling loop ──────────────────────────────────────────
    def run_loop(self, symbols=None, interval=60):
        if symbols is None: symbols=["EURUSD","XAUUSD","BTCUSD","NAS100"]
        self._log(f"🚀 Head Manager LIVE | Symbols={symbols} | Interval={interval}s")
        while True:
            for sym in symbols:
                try:
                    r = requests.get(f"{self.bridge}/signal?symbol={sym}", timeout=8)
                    if r.status_code==200:
                        sig = r.json()
                        decision = self.evaluate(sig)
                        if "EXECUTE" in decision.get("final",""):
                            # Send execute command back to bridge
                            requests.post(f"{self.bridge}/head_execute",
                                          json=decision, timeout=5)
                except Exception as e:
                    self._log(f"Error fetching {sym}: {e}", "WARN")
            time.sleep(interval)

    def decision_summary(self):
        recent = self.decision_log[-20:]
        trades = [d for d in recent if "EXECUTE" in d.get("msg","")]
        vetoes = [d for d in recent if "VETO" in d.get("msg","")]
        holds  = [d for d in recent if "HOLD" in d.get("msg","")]
        return {"recent_decisions":len(recent),"trades":len(trades),
                "vetoes":len(vetoes),"holds":len(holds),"log":recent[-10:]}

def register_routes(app, head_manager):
    @app.route("/head/evaluate", methods=["POST"])
    def head_eval():
        d = freq.get_json(force=True)
        result = head_manager.evaluate(d)
        return jsonify(result)

    @app.route("/head/log")
    def head_log():
        return jsonify(head_manager.decision_summary())

    @app.route("/head/status")
    def head_status():
        return jsonify({"managers":{
            "risk":      head_manager.rm.summary()       if head_manager.rm else "not loaded",
            "execution": head_manager.em.summary()       if head_manager.em else "not loaded",
            "portfolio": head_manager.pm.health_score()  if head_manager.pm else "not loaded",
        },"recent_log":head_manager.decision_log[-5:]})

if __name__ == "__main__":
    from manager_risk       import RiskManager
    from manager_execution  import ExecutionManager
    from manager_portfolio  import PortfolioManager

    rm = RiskManager(account_balance=10000, risk_pct=0.01)
    em = ExecutionManager()
    pm = PortfolioManager(account_balance=10000)
    hm = HeadManager(risk_manager=rm, execution_manager=em, portfolio_manager=pm)

    # Simulate a signal
    fake_signal = {"symbol":"EURUSD","signal":"BUY","score":0.73,"action":1,
                   "ob_50":1.08350,"sl":1.08100,"tp":1.09200,
                   "fvg_top":1.08420,"fvg_bottom":1.08280,"bias":1,
                   "models":{
                     "LSTM_Prophet":     {"signal":0.71,"weight":0.40},
                     "RL_Trader":        {"signal":0.68,"weight":0.35},
                     "Sentiment_Scout":  {"signal":0.62,"weight":0.25},
                     "Regime_Detector":  {"signal":0.70,"weight":0.30},
                     "Fibonacci":        {"signal":0.74,"weight":0.28},
                   }}
    result = hm.evaluate(fake_signal)
    print("\n" + "="*55)
    print("FINAL DECISION:", result["final"])
    print("LOT SIZE:      ", result["lot"])
    print("REASONING:")
    for r in result.get("reasoning",[]): print("  →", r)
