#!/usr/bin/env python3
"""
model_sessions.py
=================
MODEL 13: Market Sessions AI
==============================
Specialty: Tracks London Open (7-10am GMT), NY Open (12-3pm GMT),
           and Asian Session (Tokyo 00-08 GMT) — each has different
           volatility profiles. Learns which session is best to trade
           each symbol and adjusts signal strength accordingly.
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class SessionsModel(BaseModel):
    def __init__(self):
        super().__init__("Market_Sessions")
        self.model  = None
        self.scaler = StandardScaler()

    def _session_features(self, df):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        c = df["Close"].values
        h = df["High"].values
        l = df["Low"].values
        v = df["Volume"].values
        n = len(df)
        rows = []

        for i in range(30, n-1):
            hour = df.index[i].hour
            dow  = df.index[i].dayofweek  # 0=Mon,4=Fri

            feat = {}
            # Session encoding
            feat["london"]   = float(7 <= hour < 10)
            feat["ny"]       = float(12 <= hour < 15)
            feat["overlap"]  = float(12 <= hour < 16)  # London+NY overlap
            feat["tokyo"]    = float(0  <= hour < 8)
            feat["dead_zone"]= float(20 <= hour or hour < 0)

            # Day-of-week tendencies
            feat["monday"]  = float(dow==0)
            feat["friday"]  = float(dow==4)
            feat["midweek"] = float(1 <= dow <= 3)

            # Session volatility vs average
            day_range = h[i] - l[i]
            avg_range = np.mean(h[max(0,i-20):i] - l[max(0,i-20):i]) + 1e-8
            feat["range_ratio"]  = day_range / avg_range
            feat["vol_ratio"]    = v[i] / (np.mean(v[max(0,i-20):i]) + 1e-8)

            # London open gap
            if i >= 1:
                feat["open_gap"] = (c[i] - c[i-1]) / c[i-1]
            else:
                feat["open_gap"] = 0

            # First-hour breakout (London/NY momentum)
            feat["first_hr_bull"] = float(c[i] > h[max(0,i-3)])
            feat["first_hr_bear"] = float(c[i] < l[max(0,i-3)])

            # Trend context
            feat["above_ema20"] = float(c[i] > np.mean(c[max(0,i-20):i]))
            feat["momentum_5"]  = (c[i] - c[max(0,i-5)]) / (c[max(0,i-5)]+1e-8)
            delta = np.diff(c[max(0,i-14):i+1])
            g  = np.mean(np.maximum(delta,0))
            ls = np.mean(np.maximum(-delta,0))
            feat["rsi"] = (100-(100/(1+g/(ls+1e-8))))/100
            feat["target"] = int(c[i+1] > c[i])
            rows.append(feat)

        return pd.DataFrame(rows)

    FEAT_COLS = None

    def train(self, df):
        feats = self._session_features(df)
        if len(feats)<30: return
        self.FEAT_COLS = [c for c in feats.columns if c!="target"]
        X  = feats[self.FEAT_COLS].values
        y  = feats["target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = GradientBoostingClassifier(n_estimators=200,max_depth=5,
                                                learning_rate=0.05,random_state=42)
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        feats = self._session_features(df)
        if len(feats)<1: return 0.5
        X = feats[self.FEAT_COLS].values[-1].reshape(1,-1)
        return float(self.model.predict_proba(self.scaler.transform(X))[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("EURUSD=X",start="2021-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = SessionsModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ SessionsModel OK")
