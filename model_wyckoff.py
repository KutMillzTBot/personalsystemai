#!/usr/bin/env python3
"""
model_wyckoff.py
================
MODEL 15: Wyckoff Market Cycle AI
===================================
Specialty: Identifies the 4 Wyckoff phases:
  Phase A — Stopping the trend (PSY, SC, AR, ST)
  Phase B — Building the cause
  Phase C — The spring/upthrust (shakeout)
  Phase D — Trending move begins
  Phase E — Trend in full force
Uses volume + price spread analysis (VSA - Volume Spread Analysis).
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class WyckoffModel(BaseModel):
    def __init__(self):
        super().__init__("Wyckoff_Cycle")
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

        for i in range(50, n-1):
            feat = {}
            # Spread (range) classification
            spread   = h[i] - l[i]
            avg_sprd = np.mean(h[max(0,i-20):i] - l[max(0,i-20):i]) + 1e-8
            avg_vol  = np.mean(v[max(0,i-20):i]) + 1e-8

            feat["spread_ratio"] = spread / avg_sprd
            feat["vol_ratio"]    = v[i] / avg_vol
            feat["close_pos"]    = (c[i] - l[i]) / (spread + 1e-8)  # 0=bottom, 1=top

            # VSA bar types
            feat["up_bar"]       = float(c[i] > o[i])
            feat["down_bar"]     = float(c[i] < o[i])
            feat["narrow_spread"]= float(spread < avg_sprd * 0.5)
            feat["wide_spread"]  = float(spread > avg_sprd * 1.5)

            # Wyckoff effort vs result
            feat["high_vol_up"]  = float(v[i]>avg_vol*1.5 and c[i]>o[i])   # effort up
            feat["high_vol_dn"]  = float(v[i]>avg_vol*1.5 and c[i]<o[i])   # effort dn
            feat["low_vol_up"]   = float(v[i]<avg_vol*0.5 and c[i]>o[i])   # no effort
            feat["low_vol_dn"]   = float(v[i]<avg_vol*0.5 and c[i]<o[i])

            # Spring detection (downward shakeout on low volume = bullish)
            recent_low = min(l[max(0,i-20):i])
            feat["spring"]       = float(l[i] < recent_low and c[i] > recent_low and v[i] < avg_vol)

            # Upthrust detection (false breakout high = bearish)
            recent_high = max(h[max(0,i-20):i])
            feat["upthrust"]     = float(h[i] > recent_high and c[i] < recent_high and v[i] < avg_vol)

            # Phase indicators (longer lookback)
            c40 = c[max(0,i-40):i]
            feat["trend_40"]     = (c[i]-c40[0])/(c40[0]+1e-8) if len(c40)>0 else 0
            feat["vol_trend"]    = np.mean(v[max(0,i-5):i]) / avg_vol
            feat["price_vs_va"]  = (c[i] - np.mean(c[max(0,i-20):i])) / (np.std(c[max(0,i-20):i])+1e-8)

            # Accumulation vs distribution score
            feat["accum_score"]  = feat["high_vol_up"] - feat["high_vol_dn"] + feat["spring"]
            feat["distrib_score"]= feat["high_vol_dn"] - feat["high_vol_up"] + feat["upthrust"]

            # RSI
            delta = np.diff(c[max(0,i-14):i+1])
            g  = np.mean(np.maximum(delta,0))
            ls = np.mean(np.maximum(-delta,0))
            feat["rsi"] = (100-(100/(1+g/(ls+1e-8))))/100

            feat["target"] = int(c[i+1] > c[i])
            rows.append(feat)

        return pd.DataFrame(rows)

    FEAT_COLS = None

    def train(self, df):
        feats = self._build_features(df)
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
        feats = self._build_features(df)
        if len(feats)<1: return 0.5
        X = feats[self.FEAT_COLS].values[-1].reshape(1,-1)
        return float(self.model.predict_proba(self.scaler.transform(X))[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("AAPL",start="2019-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = WyckoffModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ WyckoffModel OK")
