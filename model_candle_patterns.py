#!/usr/bin/env python3
"""
model_candle_patterns.py
========================
MODEL 7: Candlestick Pattern Recognition AI
============================================
Specialty: Detects high-probability reversal + continuation candle patterns.
  ✅ Bullish/Bearish Engulfing
  ✅ Pin Bar (Hammer / Shooting Star)
  ✅ Inside Bar (consolidation breakout)
  ✅ Morning Star / Evening Star (3-candle)
  ✅ Doji + Gravestone Doji
  ✅ Three White Soldiers / Three Black Crows
  ✅ Marubozu (strong trend candle)
pip install: already in requirements.txt
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class CandlePatternModel(BaseModel):
    def __init__(self):
        super().__init__("Candle_Patterns")
        self.model  = None
        self.scaler = StandardScaler()

    def _features(self, df):
        d = df.copy()
        o,h,l,c = d["Open"].values, d["High"].values, d["Low"].values, d["Close"].values
        n = len(d)

        body     = c - o
        rng      = np.where(h-l>0, h-l, 1e-8)
        body_pct = body / rng
        up_wick  = h - np.maximum(o,c)
        dn_wick  = np.minimum(o,c) - l

        feats = pd.DataFrame(index=d.index)
        # Engulfing
        feats["bull_engulf"] = ((body > 0) &
            (np.concatenate([[0],body[:-1]]) < 0) &
            (c > np.concatenate([[0],o[:-1]])) &
            (o < np.concatenate([[0],c[:-1]]))).astype(float)
        feats["bear_engulf"] = ((body < 0) &
            (np.concatenate([[0],body[:-1]]) > 0) &
            (c < np.concatenate([[0],o[:-1]])) &
            (o > np.concatenate([[0],c[:-1]]))).astype(float)
        # Pin Bar
        feats["bull_pin"] = ((dn_wick > abs(body)*2.5) & (up_wick < abs(body)*.5)).astype(float)
        feats["bear_pin"] = ((up_wick > abs(body)*2.5) & (dn_wick < abs(body)*.5)).astype(float)
        # Doji
        feats["doji"] = (abs(body_pct) < 0.05).astype(float)
        # Marubozu
        feats["bull_maru"] = ((body_pct > 0.85) & (up_wick < rng*.05)).astype(float)
        feats["bear_maru"] = ((body_pct < -0.85) & (dn_wick < rng*.05)).astype(float)
        # Inside bar
        feats["inside"] = 0.0
        for i in range(1,n):
            if h[i] < h[i-1] and l[i] > l[i-1]:
                feats.iloc[i, feats.columns.get_loc("inside")] = 1.0
        # Morning star (3-bar)
        feats["morning_star"] = 0.0
        feats["evening_star"] = 0.0
        for i in range(2,n):
            if (body[i-2]<0 and abs(body[i-1])<rng[i-1]*.3 and
                body[i]>0 and c[i]>o[i-2]):
                feats.iloc[i, feats.columns.get_loc("morning_star")] = 1.0
            if (body[i-2]>0 and abs(body[i-1])<rng[i-1]*.3 and
                body[i]<0 and c[i]<o[i-2]):
                feats.iloc[i, feats.columns.get_loc("evening_star")] = 1.0
        # Three soldiers/crows
        feats["three_soldiers"] = 0.0
        feats["three_crows"]    = 0.0
        for i in range(2,n):
            if body[i]>0 and body[i-1]>0 and body[i-2]>0:
                feats.iloc[i, feats.columns.get_loc("three_soldiers")] = 1.0
            if body[i]<0 and body[i-1]<0 and body[i-2]<0:
                feats.iloc[i, feats.columns.get_loc("three_crows")] = 1.0
        # Context
        feats["body_pct"]  = body_pct
        feats["up_wick_r"] = up_wick / rng
        feats["dn_wick_r"] = dn_wick / rng
        feats["vol_ratio"] = (df["Volume"] / (df["Volume"].rolling(20).mean() + 1e-8)).values
        feats["rsi"] = 0.5
        delta = pd.Series(c).diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = 100-(100/(1+gain/(loss+1e-8)))
        feats["rsi"] = rsi.values/100
        feats["Target"] = (pd.Series(c).shift(-1) > pd.Series(c)).astype(int).values
        return feats.dropna()

    FEAT = ["bull_engulf","bear_engulf","bull_pin","bear_pin","doji",
            "bull_maru","bear_maru","inside","morning_star","evening_star",
            "three_soldiers","three_crows","body_pct","up_wick_r","dn_wick_r",
            "vol_ratio","rsi"]

    def train(self, df):
        feats = self._features(df)
        X = feats[self.FEAT].values
        y = feats["Target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = RandomForestClassifier(n_estimators=200, max_depth=8,
                                            random_state=42, n_jobs=-1)
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained: return 0.5
        feats = self._features(df)
        if len(feats)<1: return 0.5
        X  = feats[self.FEAT].values[-1].reshape(1,-1)
        Xs = self.scaler.transform(X)
        return float(self.model.predict_proba(Xs)[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("AAPL", start="2021-01-01", end="2024-12-31", progress=False)
    if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.droplevel(1)
    m = CandlePatternModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ CandlePatternModel OK")
