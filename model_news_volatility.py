#!/usr/bin/env python3
"""
model_news_volatility.py
========================
MODEL 16: News Volatility Anticipation AI
==========================================
Specialty: Learns historical volatility patterns around high-impact news
           events (NFP, CPI, FOMC, GDP). Avoids trading INTO news (risk)
           and catches the post-news directional breakout.
           Uses day-of-week + time patterns as economic calendar proxy.
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class NewsVolatilityModel(BaseModel):
    def __init__(self):
        super().__init__("News_Volatility")
        self.model  = None
        self.scaler = StandardScaler()

    # High-impact news tends to fall on specific days
    # NFP: 1st Friday of month | CPI: 2nd week | FOMC: Wed every 6 weeks
    def _is_nfp_week(self, dt):
        return dt.day <= 7 and dt.dayofweek == 4  # 1st Friday

    def _is_fomc_like(self, dt):
        # Approx FOMC: Wednesday in 2nd or 4th week of odd months
        return dt.dayofweek == 2 and dt.month % 2 == 1 and 8 <= dt.day <= 21

    def _build_features(self, df):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        c = df["Close"].values
        h = df["High"].values
        l = df["Low"].values
        v = df["Volume"].values
        n = len(df)
        rows = []

        for i in range(30, n-1):
            dt = df.index[i]
            feat = {}

            # Calendar signals
            feat["nfp_week"]   = float(self._is_nfp_week(dt))
            feat["fomc_week"]  = float(self._is_fomc_like(dt))
            feat["month_end"]  = float(dt.day >= 25)
            feat["month_start"]= float(dt.day <= 5)
            feat["monday"]     = float(dt.dayofweek == 0)
            feat["friday"]     = float(dt.dayofweek == 4)

            # Pre-news compression (tight range before big move)
            ranges     = h[max(0,i-5):i] - l[max(0,i-5):i]
            avg_range  = np.mean(h[max(0,i-20):i] - l[max(0,i-20):i]) + 1e-8
            feat["range_comp"] = np.mean(ranges) / avg_range  # <1 = compression
            feat["vol_quiet"]  = float(np.mean(v[max(0,i-5):i]) < np.mean(v[max(0,i-20):i]) * 0.7)

            # Post-news breakout momentum
            feat["breakout_h"] = float(h[i] > max(h[max(0,i-5):i]))
            feat["breakout_l"] = float(l[i] < min(l[max(0,i-5):i]))
            feat["vol_spike"]  = v[i] / (np.mean(v[max(0,i-20):i]) + 1e-8)
            feat["range_exp"]  = (h[i]-l[i]) / avg_range  # >2 = news bar

            # Volatility regime
            feat["atr_ratio"]  = np.mean(h[max(0,i-14):i]-l[max(0,i-14):i]) / avg_range
            feat["close_pos"]  = (c[i]-l[i]) / (h[i]-l[i]+1e-8)

            # RSI + trend
            delta = np.diff(c[max(0,i-14):i+1])
            g  = np.mean(np.maximum(delta,0))
            ls = np.mean(np.maximum(-delta,0))
            feat["rsi"]        = (100-(100/(1+g/(ls+1e-8))))/100
            feat["trend_20"]   = float(c[i] > np.mean(c[max(0,i-20):i]))
            feat["target"]     = int(c[i+1] > c[i])
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
        self.model = RandomForestClassifier(n_estimators=200,max_depth=8,
                                            class_weight="balanced",
                                            random_state=42,n_jobs=-1)
        self.model.fit(Xs,y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        feats = self._build_features(df)
        if len(feats)<1: return 0.5
        X = feats[self.FEAT_COLS].values[-1].reshape(1,-1)
        return float(self.model.predict_proba(self.scaler.transform(X))[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("EURUSD=X",start="2020-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = NewsVolatilityModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ NewsVolatilityModel OK")
