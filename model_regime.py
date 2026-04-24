#!/usr/bin/env python3
"""
model_regime.py
===============
MODEL 18: Adaptive Market Regime Detector AI
=============================================
Specialty: Classifies the market into one of 4 regimes in real time:
  STRONG TREND UP   → ride momentum, wider TP
  STRONG TREND DOWN → ride short, wider TP
  RANGING / CHOPPY  → fade extremes, tighter TP
  VOLATILE / NEWS   → reduce size or avoid
Then adjusts signal confidence based on regime fit.
pip install: hmmlearn
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

REGIMES = {0:"TREND_UP",1:"TREND_DN",2:"RANGING",3:"VOLATILE"}

class RegimeModel(BaseModel):
    def __init__(self):
        super().__init__("Regime_Detector")
        self.model  = None
        self.scaler = StandardScaler()

    def _classify_regime(self, c, h, l, i, lb=20):
        seg_c = c[max(0,i-lb):i+1]
        seg_h = h[max(0,i-lb):i+1]
        seg_l = l[max(0,i-lb):i+1]

        atr    = np.mean(seg_h - seg_l)
        trend  = (seg_c[-1]-seg_c[0])/(seg_c[0]+1e-8)
        volatility = np.std(np.diff(seg_c)/seg_c[:-1]) * 100

        if   volatility > 2.0:          return 3  # volatile
        elif trend >  0.02:             return 0  # trend up
        elif trend < -0.02:             return 1  # trend down
        else:                           return 2  # ranging

    def _build_features(self, df):
        c = df["Close"].values
        h = df["High"].values
        l = df["Low"].values
        v = df["Volume"].values
        n = len(c)
        rows = []

        for i in range(40, n-1):
            feat = {}
            reg5  = self._classify_regime(c,h,l,i,5)
            reg20 = self._classify_regime(c,h,l,i,20)
            reg50 = self._classify_regime(c,h,l,i,50)

            for lb,reg in [(5,reg5),(20,reg20),(50,reg50)]:
                feat[f"regime_{lb}"] = reg
                for r in range(4): feat[f"is_{REGIMES[r]}_{lb}"] = float(reg==r)

            # Regime alignment across timeframes
            feat["all_trend_up"]  = float(reg5==0 and reg20==0 and reg50==0)
            feat["all_trend_dn"]  = float(reg5==1 and reg20==1 and reg50==1)
            feat["all_ranging"]   = float(reg5==2 and reg20==2)
            feat["conflict"]      = float(reg5 != reg20)

            # ADX-like trend strength
            dmp = np.mean(np.maximum(np.diff(h[max(0,i-14):i+1]),0))
            dmm = np.mean(np.maximum(-np.diff(l[max(0,i-14):i+1]),0))
            atr = np.mean(h[max(0,i-14):i+1]-l[max(0,i-14):i+1])+1e-8
            feat["dmp_ratio"] = dmp/atr
            feat["dmm_ratio"] = dmm/atr
            feat["adx_like"]  = abs(dmp-dmm)/atr

            # Efficiency ratio (trending = high ER)
            net_move = abs(c[i]-c[max(0,i-20)])
            path     = sum(abs(np.diff(c[max(0,i-20):i+1]))) + 1e-8
            feat["efficiency"] = net_move/path

            # Volatility features
            rets = np.diff(c[max(0,i-20):i+1])/c[max(0,i-20):i]
            feat["volatility"] = np.std(rets)*100
            feat["vol_ratio"]  = v[i]/(np.mean(v[max(0,i-20):i])+1e-8)

            # Bollinger bandwidth
            roll20 = c[max(0,i-20):i+1]
            feat["bb_width"] = 4*np.std(roll20)/(np.mean(roll20)+1e-8)

            feat["target"] = int(c[i+1]>c[i])
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
        self.model = GradientBoostingClassifier(n_estimators=200,max_depth=6,
                                                learning_rate=0.05,random_state=42)
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
    raw = yf.download("^NDX",start="2020-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = RegimeModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ RegimeModel OK")
