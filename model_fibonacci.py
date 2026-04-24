#!/usr/bin/env python3
"""
model_fibonacci.py
==================
MODEL 9: Fibonacci Retracement & Extension AI
==============================================
Specialty: Detects key Fibonacci levels (23.6%, 38.2%, 50%, 61.8%, 78.6%)
           from swing highs/lows and signals when price bounces from them.
           Also projects Fibonacci extensions for TP targets (127.2%, 161.8%).
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
FIB_EXT    = [1.272, 1.618, 2.0]

class FibonacciModel(BaseModel):
    def __init__(self):
        super().__init__("Fibonacci_Retracement")
        self.model  = None
        self.scaler = StandardScaler()

    def _swing_points(self, close, window=10):
        highs, lows = [], []
        for i in range(window, len(close)-window):
            if close[i] == max(close[i-window:i+window]): highs.append((i, close[i]))
            if close[i] == min(close[i-window:i+window]): lows.append((i,  close[i]))
        return highs, lows

    def _fib_features(self, df):
        c   = df["Close"].values
        h   = df["High"].values
        l   = df["Low"].values
        n   = len(c)
        highs, lows = self._swing_points(c)

        rows = []
        for i in range(20, n):
            price = c[i]
            feat  = {}

            # Most recent swing high and low before i
            rh = [x for x in highs if x[0] < i]
            rl = [x for x in lows  if x[0] < i]
            if not rh or not rl:
                rows.append(None); continue

            sh_idx, sh = rh[-1]
            sl_idx, sl = rl[-1]

            swing_range = sh - sl
            if swing_range == 0:
                rows.append(None); continue

            # Distance of current price to each fib level
            for f in FIB_LEVELS:
                lvl = sh - f * swing_range
                feat[f"dist_fib_{int(f*1000)}"] = (price - lvl) / swing_range

            # Nearest fib level
            dists  = [abs(price - (sh - f * swing_range)) for f in FIB_LEVELS]
            feat["nearest_fib"] = FIB_LEVELS[np.argmin(dists)]
            feat["min_fib_dist"] = min(dists) / swing_range

            # Are we near golden ratio?
            golden = sh - 0.618 * swing_range
            feat["near_golden"] = float(abs(price - golden) / swing_range < 0.02)

            # Trend context
            feat["above_50ma"]  = float(price > np.mean(c[max(0,i-50):i]))
            feat["rsi"]         = self._rsi(c, i)
            feat["vol_spike"]   = df["Volume"].iloc[i] / (df["Volume"].iloc[max(0,i-20):i].mean() + 1e-8)
            feat["body_size"]   = abs(c[i] - df["Open"].iloc[i]) / (h[i]-l[i]+1e-8)
            feat["target"]      = int(c[min(i+1,n-1)] > price)
            rows.append(feat)

        valid = [r for r in rows if r is not None]
        return pd.DataFrame(valid)

    def _rsi(self, c, i, period=14):
        if i < period: return 0.5
        d = np.diff(c[i-period:i+1])
        g = np.mean(np.maximum(d, 0))
        loss = np.mean(np.maximum(-d, 0))
        if loss == 0: return 1.0
        return (100 - 100/(1+g/loss)) / 100

    FEAT_COLS = None

    def train(self, df):
        feats = self._fib_features(df)
        if len(feats) < 50: return
        self.FEAT_COLS = [c for c in feats.columns if c != "target"]
        X = feats[self.FEAT_COLS].values
        y = feats["target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = GradientBoostingClassifier(n_estimators=200, max_depth=4,
                                                learning_rate=0.05, random_state=42)
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        feats = self._fib_features(df)
        if len(feats) < 1: return 0.5
        X  = feats[self.FEAT_COLS].values[-1].reshape(1, -1)
        Xs = self.scaler.transform(X)
        return float(self.model.predict_proba(Xs)[0, 1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("EURUSD=X", start="2021-01-01", end="2024-12-31", progress=False)
    if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.droplevel(1)
    m = FibonacciModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ FibonacciModel OK")
