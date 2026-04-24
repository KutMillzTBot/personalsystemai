#!/usr/bin/env python3
"""
model_elliott_wave.py
=====================
MODEL 12: Elliott Wave Pattern AI
===================================
Specialty: Identifies Elliott Wave structures (5-wave impulse + 3-wave
           correction ABC). Counts wave degrees and predicts which wave
           the market is currently in to time entries.
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class ElliottWaveModel(BaseModel):
    def __init__(self):
        super().__init__("Elliott_Wave")
        self.model  = None
        self.scaler = StandardScaler()

    def _find_pivots(self, c, window=5):
        pivots = []
        for i in range(window, len(c)-window):
            seg = c[i-window:i+window+1]
            if c[i] == max(seg): pivots.append((i, c[i], "H"))
            elif c[i] == min(seg): pivots.append((i, c[i], "L"))
        return pivots

    def _wave_features(self, df):
        c = df["Close"].values
        h = df["High"].values
        l = df["Low"].values
        n = len(c)
        pivots = self._find_pivots(c)
        rows   = []

        for i in range(40, n-1):
            past = [(idx,val,typ) for idx,val,typ in pivots if idx < i]
            if len(past) < 8:
                rows.append(None); continue

            last8 = past[-8:]
            vals  = [v for _,v,_ in last8]
            types = [t for _,_,t in last8]
            diffs = np.diff(vals)

            feat = {}
            feat["wave1"] = diffs[0] if len(diffs)>0 else 0
            feat["wave2"] = diffs[1] if len(diffs)>1 else 0
            feat["wave3"] = diffs[2] if len(diffs)>2 else 0
            feat["wave4"] = diffs[3] if len(diffs)>3 else 0
            feat["wave5"] = diffs[4] if len(diffs)>4 else 0
            feat["waveA"] = diffs[5] if len(diffs)>5 else 0
            feat["waveB"] = diffs[6] if len(diffs)>6 else 0

            # Wave 3 should be longest impulse (Elliott rule)
            imp_waves = [abs(feat["wave1"]),abs(feat["wave3"]),abs(feat["wave5"])]
            feat["w3_longest"] = float(abs(feat["wave3"]) == max(imp_waves))

            # Fibonacci relationships between waves
            if feat["wave1"] != 0:
                feat["w2_retrace"] = abs(feat["wave2"]) / abs(feat["wave1"])
                feat["w3_ext"]     = abs(feat["wave3"]) / abs(feat["wave1"])
                feat["w4_retrace"] = abs(feat["wave4"]) / abs(feat["wave3"]+1e-8)
            else:
                feat["w2_retrace"] = feat["w3_ext"] = feat["w4_retrace"] = 0

            # Alternation rule: waves 2 and 4 alternate type
            feat["alternation"] = float(types[-8] != types[-6]) if len(types)>=8 else 0

            # Current position context
            feat["above_ema20"] = float(c[i] > np.mean(c[max(0,i-20):i]))
            feat["above_ema50"] = float(c[i] > np.mean(c[max(0,i-50):i]))
            feat["last_type_H"] = float(types[-1]=="H")
            feat["swing_size"]  = abs(diffs[-1]) / (c[i]+1e-8)
            feat["num_pivots"]  = len(past)

            # RSI
            delta = np.diff(c[max(0,i-14):i+1])
            g  = np.mean(np.maximum(delta,0))
            ls = np.mean(np.maximum(-delta,0))
            feat["rsi"] = (100-(100/(1+g/(ls+1e-8))))/100

            feat["target"] = int(c[i+1] > c[i])
            rows.append(feat)

        return pd.DataFrame([r for r in rows if r is not None])

    FEAT_COLS = None

    def train(self, df):
        feats = self._wave_features(df)
        if len(feats)<30: return
        self.FEAT_COLS = [c for c in feats.columns if c!="target"]
        X  = feats[self.FEAT_COLS].values
        y  = feats["target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = RandomForestClassifier(n_estimators=300,max_depth=10,
                                            random_state=42,n_jobs=-1)
        self.model.fit(Xs,y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        feats = self._wave_features(df)
        if len(feats)<1: return 0.5
        X = feats[self.FEAT_COLS].values[-1].reshape(1,-1)
        return float(self.model.predict_proba(self.scaler.transform(X))[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("BTC-USD",start="2020-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = ElliottWaveModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ ElliottWaveModel OK")
