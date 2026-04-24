#!/usr/bin/env python3
"""
model_liquidity_sweep.py
========================
MODEL 11: Liquidity Sweep & Stop Hunt AI
=========================================
Specialty: Detects when price sweeps above recent highs or below recent lows
           to grab liquidity (stop hunts), then reverses. One of the most
           powerful ICT concepts — catches institutional liquidity raids.
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class LiquiditySweepModel(BaseModel):
    def __init__(self):
        super().__init__("Liquidity_Sweep")
        self.model  = None
        self.scaler = StandardScaler()

    def _build_features(self, df):
        o = df["Open"].values
        h = df["High"].values
        l = df["Low"].values
        c = df["Close"].values
        v = df["Volume"].values
        n = len(c)
        rows = []

        for i in range(30, n-1):
            price = c[i]
            feat  = {}

            # Equal highs / lows (liquidity pools)
            recent_h = h[i-20:i]
            recent_l = l[i-20:i]
            prev_hh  = max(recent_h)
            prev_ll  = min(recent_l)

            # Sweep detection: wick above/below then close inside
            bull_sweep = (h[i] > prev_hh) and (c[i] < prev_hh)  # swept highs → bearish
            bear_sweep = (l[i] < prev_ll) and (c[i] > prev_ll)  # swept lows  → bullish

            feat["bull_sweep"]   = float(bull_sweep)  # price swept high = bearish reversal
            feat["bear_sweep"]   = float(bear_sweep)  # price swept low  = bullish reversal
            feat["sweep_size"]   = max(h[i]-prev_hh, prev_ll-l[i], 0) / (price+1e-8)
            feat["wick_ratio"]   = (h[i]-max(o[i],c[i])) / (h[i]-l[i]+1e-8)
            feat["lower_wick"]   = (min(o[i],c[i])-l[i]) / (h[i]-l[i]+1e-8)

            # Equal highs/lows cluster (stacked stops)
            tol = np.std(recent_h) * 0.1
            eq_highs = sum(1 for x in recent_h if abs(x-prev_hh) < tol)
            eq_lows  = sum(1 for x in recent_l if abs(x-prev_ll) < tol)
            feat["eq_highs"]    = float(eq_highs)
            feat["eq_lows"]     = float(eq_lows)

            # Volume on sweep bar
            avg_vol = np.mean(v[i-20:i]) + 1e-8
            feat["vol_on_sweep"] = v[i] / avg_vol
            feat["vol_spike"]    = float(v[i] > avg_vol * 1.5)

            # Momentum reversal after sweep
            feat["close_above_mid"] = float(c[i] > (h[i]+l[i])/2)
            feat["inside_range"]    = float(h[i-1] > h[i] and l[i-1] < l[i])

            # RSI
            delta = np.diff(c[i-15:i+1])
            g = np.mean(np.maximum(delta,0)); ls = np.mean(np.maximum(-delta,0))
            feat["rsi"] = (100-(100/(1+g/(ls+1e-8))))/100

            # Context
            feat["above_ema20"] = float(price > np.mean(c[max(0,i-20):i]))
            feat["dist_hh"]     = (price - prev_hh) / price
            feat["dist_ll"]     = (prev_ll - price) / price
            feat["target"]      = int(c[i+1] > price)
            rows.append(feat)

        return pd.DataFrame(rows)

    FEAT_COLS = None

    def train(self, df):
        feats = self._build_features(df)
        if len(feats) < 30: return
        self.FEAT_COLS = [c for c in feats.columns if c!="target"]
        X  = feats[self.FEAT_COLS].values
        y  = feats["target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = MLPClassifier(hidden_layer_sizes=(128,64,32),activation="relu",
                                   solver="adam",max_iter=400,random_state=42,
                                   early_stopping=True,learning_rate_init=0.001)
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        feats = self._build_features(df)
        if len(feats)<1: return 0.5
        X = feats[self.FEAT_COLS].values[-1].reshape(1,-1)
        return float(self.model.predict_proba(self.scaler.transform(X))[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("GBPUSD=X",start="2021-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = LiquiditySweepModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ LiquiditySweepModel OK")
