#!/usr/bin/env python3
"""
model_volume_orderflow.py
=========================
MODEL 5: Volume Profile + Order Flow AI
========================================
Specialty: Reads WHERE the market is trading (volume by price level)
           and detects institutional order flow patterns.
           Best at: identifying support/resistance zones and
                    smart money accumulation/distribution.

Strategy:
  - VWAP deviation: price vs volume-weighted average → mean reversion
  - Volume delta: buying vs selling pressure each candle
  - OBV trend: On-Balance Volume confirms price moves
  - CMF: Chaikin Money Flow — institutional buying/selling
  - Volume spike detection: unusual activity = smart money moving
  - Price-volume divergence: price up on low volume = weak move

To add to SupervisorTrainer:
  from model_volume_orderflow import VolumeOrderFlowModel
  st.register(VolumeOrderFlowModel(), initial_weight=1.0)

pip install: already covered by requirements.txt
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel


class VolumeOrderFlowModel(BaseModel):
    """
    Volume Profile + Order Flow analysis.
    Uses GradientBoosting — better than MLP for tabular volume data.
    Specialty: institutional footprint detection.
    """

    def __init__(self):
        super().__init__("Volume_OrderFlow")
        self.model  = None
        self.scaler = StandardScaler()

    # ── Feature Engineering ─────────────────────────────────
    def _build_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]

        # ── VWAP (rolling 20-period) ─────────────────────────
        tp         = (high + low + close) / 3
        df["VWAP"] = (tp * volume).rolling(20).sum() / volume.rolling(20).sum()
        df["VWAP_dev"] = (close - df["VWAP"]) / (df["VWAP"] + 1e-8)

        # ── OBV — On-Balance Volume ──────────────────────────
        obv = [0]
        for i in range(1, len(df)):
            if close.iloc[i] > close.iloc[i-1]:
                obv.append(obv[-1] + volume.iloc[i])
            elif close.iloc[i] < close.iloc[i-1]:
                obv.append(obv[-1] - volume.iloc[i])
            else:
                obv.append(obv[-1])
        df["OBV"]       = obv
        df["OBV_slope"] = pd.Series(obv).diff(5).values / (volume.rolling(5).mean() + 1e-8)

        # ── CMF — Chaikin Money Flow (20-period) ─────────────
        mf_mult    = ((close - low) - (high - close)) / (high - low + 1e-8)
        mf_volume  = mf_mult * volume
        df["CMF"]  = mf_volume.rolling(20).sum() / (volume.rolling(20).sum() + 1e-8)

        # ── Volume Delta (proxy: candle body direction) ──────
        df["candle_body"]   = (close - df["Open"]) / (high - low + 1e-8)
        df["vol_delta"]     = df["candle_body"] * volume
        df["vol_delta_ma"]  = df["vol_delta"].rolling(10).mean()
        df["vol_delta_norm"]= df["vol_delta"] / (volume + 1e-8)

        # ── Volume Spike (volume > 2x 20-period average) ─────
        vol_ma20           = volume.rolling(20).mean()
        df["vol_spike"]    = (volume / (vol_ma20 + 1e-8)).clip(0, 5)
        df["vol_trend"]    = volume.rolling(5).mean() / (volume.rolling(20).mean() + 1e-8)

        # ── Price-Volume Divergence ───────────────────────────
        price_chg          = close.pct_change(5)
        vol_chg            = volume.pct_change(5)
        df["pv_div"]       = price_chg / (vol_chg.replace(0, np.nan).abs() + 1e-8)
        df["pv_div"]       = df["pv_div"].clip(-3, 3).fillna(0)

        # ── Accumulation / Distribution ───────────────────────
        df["AD"]           = mf_mult * volume
        df["AD_cumsum"]    = df["AD"].cumsum()
        df["AD_slope"]     = df["AD_cumsum"].diff(10) / (volume.rolling(10).mean() + 1e-8)

        # ── Support / Resistance (High Volume Nodes) ─────────
        df["hvn"]          = (df["vol_spike"] > 1.5).astype(int)  # near high-vol node
        df["at_hvn"]       = (df["hvn"].rolling(5).sum() > 0).astype(int)

        # ── Returns ──────────────────────────────────────────
        df["Returns"]      = close.pct_change()
        df["Returns_5"]    = close.pct_change(5)

        # ── Target ───────────────────────────────────────────
        df["Target"] = (close.shift(-1) > close).astype(int)
        return df.dropna()

    FEAT = ["VWAP_dev","OBV_slope","CMF","vol_delta_norm","vol_delta_ma",
            "vol_spike","vol_trend","pv_div","AD_slope","at_hvn",
            "candle_body","Returns","Returns_5"]

    def train(self, df: pd.DataFrame):
        df2  = self._build_volume_features(df)
        X    = df2[self.FEAT].values
        y    = df2["Target"].values
        Xs   = self.scaler.fit_transform(X)
        # GradientBoosting — handles volume skew better than MLP
        self.model = GradientBoostingClassifier(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.8,
            random_state=42,
        )
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df: pd.DataFrame) -> float:
        if not self.is_trained:
            return 0.5
        df2 = self._build_volume_features(df)
        if len(df2) < 1:
            return 0.5
        X  = df2[self.FEAT].values[-1].reshape(1, -1)
        Xs = self.scaler.transform(X)
        return float(self.model.predict_proba(Xs)[0, 1])


# ── Self-test ────────────────────────────────────────────────
if __name__ == "__main__":
    import yfinance as yf
    print("Testing VolumeOrderFlowModel...")
    raw = yf.download("AAPL", start="2021-01-01", end="2024-12-31", progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)
    m = VolumeOrderFlowModel()
    split = int(len(raw) * 0.8)
    m.train(raw.iloc[:split])
    sig = m.predict(raw)
    print(f"  Signal: {sig:.4f}  ({'BUY' if sig > 0.55 else 'SELL' if sig < 0.45 else 'HOLD'})")
    print("  ✅ VolumeOrderFlowModel OK")
