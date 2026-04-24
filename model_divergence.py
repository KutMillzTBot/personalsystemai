#!/usr/bin/env python3
"""
model_divergence.py
===================
MODEL 14: Multi-Indicator Divergence Hunter AI
===============================================
Specialty: Detects HIDDEN and REGULAR divergences across RSI, MACD,
           and OBV simultaneously. Divergences are the earliest warning
           of trend reversals — far earlier than crossovers.
  Regular Divergence  → trend reversal signal
  Hidden Divergence   → trend continuation signal
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class DivergenceModel(BaseModel):
    def __init__(self):
        super().__init__("Divergence_Hunter")
        self.model  = None
        self.scaler = StandardScaler()

    def _compute_indicators(self, c, v):
        # RSI
        delta = pd.Series(c).diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = 100 - (100 / (1 + gain / (loss+1e-8)))

        # MACD histogram
        ema12 = pd.Series(c).ewm(span=12).mean()
        ema26 = pd.Series(c).ewm(span=26).mean()
        macd  = ema12 - ema26
        macd_h= macd - macd.ewm(span=9).mean()

        # OBV
        obv = [0]
        for i in range(1,len(c)):
            if c[i]>c[i-1]: obv.append(obv[-1]+v[i])
            elif c[i]<c[i-1]: obv.append(obv[-1]-v[i])
            else: obv.append(obv[-1])
        return rsi.values, macd_h.values, np.array(obv)

    def _divergence_at(self, price_series, ind_series, i, lb=10):
        if i < lb*2: return 0, 0
        p = price_series[i-lb:i+1]
        s = ind_series[i-lb:i+1]

        ph = max(p); pl = min(p)
        sh = max(s); sl = min(s)
        ph_i = np.argmax(p); pl_i = np.argmin(p)
        sh_i = np.argmax(s); sl_i = np.argmin(s)

        reg_bear = (ph_i > len(p)//2) and (sh_i < len(s)//2)  # price HH, ind LH
        reg_bull = (pl_i > len(p)//2) and (sl_i < len(s)//2)  # price LL, ind HL
        hid_bull = (pl_i < len(p)//2) and (sl_i > len(s)//2)  # price HL, ind LL
        hid_bear = (ph_i < len(p)//2) and (sh_i > len(s)//2)  # price LH, ind HH

        bull = float(reg_bull or hid_bull)
        bear = float(reg_bear or hid_bear)
        return bull, bear

    def _build_features(self, df):
        c = df["Close"].values
        v = df["Volume"].values
        n = len(c)
        rsi, macd_h, obv = self._compute_indicators(c, v)
        rows = []

        for i in range(40, n-1):
            feat = {}
            # RSI divergence
            feat["rsi_bull"], feat["rsi_bear"] = self._divergence_at(c, rsi, i)
            # MACD divergence
            feat["macd_bull"], feat["macd_bear"] = self._divergence_at(c, macd_h, i)
            # OBV divergence
            feat["obv_bull"], feat["obv_bear"]  = self._divergence_at(c, obv, i)

            # Confluence: all 3 agree
            feat["triple_bull"] = float(feat["rsi_bull"] and feat["macd_bull"] and feat["obv_bull"])
            feat["triple_bear"] = float(feat["rsi_bear"] and feat["macd_bear"] and feat["obv_bear"])
            feat["dual_bull"]   = float((feat["rsi_bull"]+feat["macd_bull"]+feat["obv_bull"])>=2)
            feat["dual_bear"]   = float((feat["rsi_bear"]+feat["macd_bear"]+feat["obv_bear"])>=2)

            # Raw indicator values
            feat["rsi_val"]    = rsi[i]/100 if not np.isnan(rsi[i]) else 0.5
            feat["macd_h_val"] = macd_h[i] if not np.isnan(macd_h[i]) else 0
            feat["obv_slope"]  = (obv[i]-obv[max(0,i-10)])/(abs(obv[max(0,i-10)])+1e-8)

            # Context
            feat["above_ema20"] = float(c[i] > np.mean(c[max(0,i-20):i]))
            feat["target"]      = int(c[i+1] > c[i])
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
        self.model = RandomForestClassifier(n_estimators=250,max_depth=9,
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
    raw = yf.download("GC=F",start="2020-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = DivergenceModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ DivergenceModel OK")
