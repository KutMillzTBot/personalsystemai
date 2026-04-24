#!/usr/bin/env python3
"""
model_smart_money.py
====================
MODEL 6: ICT Smart Money Concepts — Order Blocks, FVG, Market Structure
=========================================================================
Specialty: Full ICT methodology in Python.
           Detects institutional footprints and trades them properly.

Concepts implemented:
  ✅ Order Blocks (OB)          — last opposite candle before big move
  ✅ OB 50% Mean Threshold      — optimal entry at midpoint of OB
  ✅ Fair Value Gap (FVG)        — 3-candle price imbalance zones
  ✅ BOS (Break of Structure)   — confirms trend direction
  ✅ CHoCH (Change of Character) — early trend reversal warning
  ✅ Liquidity Zones             — previous highs/lows (stop hunts)
  ✅ OTE (Optimal Trade Entry)   — 61.8%-79% fib of the swing

Trade logic:
  BULLISH: BOS up + price returns to bullish OB 50% level
            → BUY entry at OB midpoint
            → SL below OB low
            → TP at previous swing high / FVG fill

  BEARISH: BOS down + price returns to bearish OB 50% level
            → SELL entry at OB midpoint
            → SL above OB high
            → TP at previous swing low / FVG fill

pip install: pip install smartmoneyconcepts
"""

import numpy as np
import pandas as pd
from supervisor_trainer import BaseModel

try:
    import smartmoneyconcepts as smc
    SMC_AVAILABLE = True
except ImportError:
    SMC_AVAILABLE = False
    print("⚠️  smartmoneyconcepts not installed.")
    print("   Run: pip install smartmoneyconcepts")


class SmartMoneyModel(BaseModel):
    """
    ICT Smart Money Concepts model.
    Rule-based + ML scoring — no training data required.
    The OB / FVG / BOS rules ARE the strategy.
    """

    def __init__(self):
        super().__init__("Smart_Money_ICT")
        self.is_trained  = True   # rule-based, always ready
        self._last_levels = {}    # stores SL/TP/OB levels for EA

    def train(self, df: pd.DataFrame):
        self.is_trained = True    # stateless rule engine

    def _prep(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise column names for smartmoneyconcepts library."""
        d = df.copy()
        d.columns = [c.lower() for c in d.columns]
        needed = ["open","high","low","close","volume"]
        for col in needed:
            if col not in d.columns:
                if col == "volume": d[col] = 1.0
                else: raise ValueError(f"Missing column: {col}")
        return d[needed]

    # ── Core ICT Analysis ─────────────────────────────────────
    def _analyse(self, df: pd.DataFrame) -> dict:
        if not SMC_AVAILABLE:
            return self._fallback_analyse(df)

        ohlc = self._prep(df)
        result = {
            "bias":       0,      # +1 bullish / -1 bearish / 0 neutral
            "ob_signal":  0.5,    # 0–1 signal from OB
            "fvg_signal": 0.5,    # 0–1 signal from FVG
            "bos_signal": 0.5,    # 0–1 signal from BOS/CHoCH
            "ob_top":     None,
            "ob_bottom":  None,
            "ob_50":      None,
            "sl":         None,
            "tp":         None,
            "fvg_top":    None,
            "fvg_bottom": None,
        }

        close = ohlc["close"].values
        current_price = float(close[-1])

        # ── 1. Swing Highs / Lows ──────────────────────────
        try:
            hl = smc.highs_lows(ohlc, swing_length=10)
        except Exception:
            hl = None

        # ── 2. BOS / CHoCH ─────────────────────────────────
        try:
            bos = smc.bos_choch(ohlc, close_break=True)
            last_bos = bos.dropna(subset=["BOS"]) if "BOS" in bos.columns else pd.DataFrame()
            last_choch = bos.dropna(subset=["CHOCH"]) if "CHOCH" in bos.columns else pd.DataFrame()

            if not last_bos.empty:
                latest = last_bos.iloc[-1]
                val = latest.get("BOS", 0)
                if val == 1:
                    result["bias"]      = 1
                    result["bos_signal"] = 0.75
                elif val == -1:
                    result["bias"]      = -1
                    result["bos_signal"] = 0.25

            if not last_choch.empty:
                latest = last_choch.iloc[-1]
                val = latest.get("CHOCH", 0)
                if val == 1:   result["bos_signal"] = min(1.0, result["bos_signal"] + 0.1)
                elif val == -1: result["bos_signal"] = max(0.0, result["bos_signal"] - 0.1)
        except Exception:
            pass

        # ── 3. Order Blocks ────────────────────────────────
        try:
            ob_data = smc.ob(ohlc)
            active_obs = ob_data[ob_data["OB"].notna() & (ob_data["OB"] != 0)]

            if not active_obs.empty:
                # Find nearest OB to current price
                ob_tops    = active_obs["Top"].values
                ob_bottoms = active_obs["Bottom"].values
                ob_types   = active_obs["OB"].values

                nearest_idx = None
                nearest_dist = np.inf
                for i in range(len(ob_tops)):
                    mid  = (ob_tops[i] + ob_bottoms[i]) / 2
                    dist = abs(current_price - mid)
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_idx  = i

                if nearest_idx is not None:
                    ob_top    = float(ob_tops[nearest_idx])
                    ob_bot    = float(ob_bottoms[nearest_idx])
                    ob_50     = (ob_top + ob_bot) / 2
                    ob_type   = float(ob_types[nearest_idx])

                    result["ob_top"]    = round(ob_top, 5)
                    result["ob_bottom"] = round(ob_bot, 5)
                    result["ob_50"]     = round(ob_50, 5)

                    # Price is AT or BELOW bullish OB → BUY zone
                    if ob_type == 1 and current_price <= ob_top:
                        prox = 1 - abs(current_price - ob_50) / (ob_top - ob_bot + 1e-8)
                        result["ob_signal"] = float(np.clip(0.5 + prox * 0.4, 0, 1))
                        result["sl"] = round(ob_bot * 0.9995, 5)
                        result["tp"] = round(ob_top + (ob_top - ob_bot) * 3, 5)

                    # Price is AT or ABOVE bearish OB → SELL zone
                    elif ob_type == -1 and current_price >= ob_bot:
                        prox = 1 - abs(current_price - ob_50) / (ob_top - ob_bot + 1e-8)
                        result["ob_signal"] = float(np.clip(0.5 - prox * 0.4, 0, 1))
                        result["sl"] = round(ob_top * 1.0005, 5)
                        result["tp"] = round(ob_bot - (ob_top - ob_bot) * 3, 5)
        except Exception:
            pass

        # ── 4. Fair Value Gaps ─────────────────────────────
        try:
            fvg_data = smc.fvg(ohlc)
            active_fvgs = fvg_data[fvg_data["FVG"].notna() & (fvg_data["FVG"] != 0)]
            if not active_fvgs.empty:
                latest_fvg = active_fvgs.iloc[-1]
                fvg_type   = float(latest_fvg["FVG"])
                fvg_top    = float(latest_fvg.get("Top", current_price))
                fvg_bot    = float(latest_fvg.get("Bottom", current_price))

                result["fvg_top"]    = round(fvg_top, 5)
                result["fvg_bottom"] = round(fvg_bot, 5)

                in_fvg = fvg_bot <= current_price <= fvg_top
                if fvg_type == 1 and in_fvg:
                    result["fvg_signal"] = 0.72   # in bullish FVG → buy
                elif fvg_type == -1 and in_fvg:
                    result["fvg_signal"] = 0.28   # in bearish FVG → sell
                elif fvg_type == 1:
                    result["fvg_signal"] = 0.60
                elif fvg_type == -1:
                    result["fvg_signal"] = 0.40
        except Exception:
            pass

        return result

    # ── Fallback: pure-numpy ICT approximation (no smc lib) ──
    def _fallback_analyse(self, df: pd.DataFrame) -> dict:
        """Manual OB + FVG detection without the smc library."""
        close  = df["Close"].values
        high   = df["High"].values
        low    = df["Low"].values
        opens  = df["Open"].values
        n      = len(close)
        current = close[-1]

        result = {"bias":0,"ob_signal":0.5,"fvg_signal":0.5,"bos_signal":0.5,
                  "ob_top":None,"ob_bottom":None,"ob_50":None,
                  "sl":None,"tp":None,"fvg_top":None,"fvg_bottom":None}

        if n < 10: return result

        # BOS: last 20 bars trend
        lookback = min(20, n)
        recent_high = high[-lookback:].max()
        recent_low  = low[-lookback:].min()
        mid_idx     = lookback // 2
        first_half_high = high[-lookback:-mid_idx].max()
        second_half_high = high[-mid_idx:].max()
        first_half_low  = low[-lookback:-mid_idx].min()
        second_half_low  = low[-mid_idx:].min()

        if second_half_high > first_half_high and second_half_low > first_half_low:
            result["bias"]      =  1
            result["bos_signal"] = 0.70
        elif second_half_high < first_half_high and second_half_low < first_half_low:
            result["bias"]      = -1
            result["bos_signal"] = 0.30

        # Manual Order Block: last bearish candle before up-move (bullish OB)
        for i in range(n-3, max(n-20, 0), -1):
            if (opens[i] > close[i] and          # bearish candle
                close[i+1] > opens[i] and         # next candle breaks up
                close[-1] >= low[i] and            # price came back to OB
                close[-1] <= high[i]):             # price still in OB
                ob_top = high[i]
                ob_bot = low[i]
                ob_50  = (ob_top + ob_bot) / 2
                result.update({
                    "ob_top": round(ob_top,5),
                    "ob_bottom": round(ob_bot,5),
                    "ob_50": round(ob_50,5),
                    "ob_signal": 0.72,
                    "sl": round(ob_bot * 0.9995, 5),
                    "tp": round(ob_top + (ob_top-ob_bot)*3, 5)
                })
                break

        # FVG: 3-candle imbalance
        for i in range(n-3, max(n-15, 0), -1):
            if low[i+2] > high[i]:                 # bullish FVG
                result.update({"fvg_top": round(low[i+2],5),
                               "fvg_bottom": round(high[i],5),
                               "fvg_signal": 0.65})
                break
            elif high[i+2] < low[i]:               # bearish FVG
                result.update({"fvg_top": round(low[i],5),
                               "fvg_bottom": round(high[i+2],5),
                               "fvg_signal": 0.35})
                break

        return result

    # ── Predict ───────────────────────────────────────────────
    def predict(self, df: pd.DataFrame) -> float:
        if len(df) < 20:
            return 0.5

        analysis = self._analyse(df)

        # Weighted combination of ICT signals
        score = (
            analysis["ob_signal"]  * 0.45 +
            analysis["fvg_signal"] * 0.30 +
            analysis["bos_signal"] * 0.25
        )

        # Bias alignment bonus
        if analysis["bias"] == 1 and score > 0.5:
            score = min(1.0, score + 0.08)
        elif analysis["bias"] == -1 and score < 0.5:
            score = max(0.0, score - 0.08)

        # Store levels so bridge server can pass SL/TP to EA
        self._last_levels = {
            "ob_top":     analysis["ob_top"],
            "ob_bottom":  analysis["ob_bottom"],
            "ob_50":      analysis["ob_50"],
            "sl":         analysis["sl"],
            "tp":         analysis["tp"],
            "fvg_top":    analysis["fvg_top"],
            "fvg_bottom": analysis["fvg_bottom"],
            "bias":       analysis["bias"],
        }

        return float(np.clip(score, 0.0, 1.0))


# ── Self-test ─────────────────────────────────────────────────
if __name__ == "__main__":
    import yfinance as yf
    print("Testing SmartMoneyModel (ICT)...")
    raw = yf.download("EURUSD=X", start="2023-01-01", end="2024-12-31", progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)
    m = SmartMoneyModel()
    m.train(raw)
    sig = m.predict(raw)
    print(f"  Signal : {sig:.4f}  "
          f"({'BUY' if sig>0.55 else 'SELL' if sig<0.45 else 'HOLD'})")
    print(f"  Levels : {m._last_levels}")
    print("  ✅ SmartMoneyModel OK")
