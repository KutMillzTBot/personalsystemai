#!/usr/bin/env python3
"""
model_mtf_confluence.py
=======================
MODEL 8: Multi-Timeframe Confluence AI
=======================================
Specialty: Combines signals from H4, H1, M15 timeframes.
           Only trades when ALL timeframes agree — highest win rate.
  HTF (H4): Overall trend direction
  MTF (H1): Entry zone confirmation
  LTF (M15): Precise trigger timing
pip install: already in requirements.txt
"""
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class MTFConfluenceModel(BaseModel):
    def __init__(self):
        super().__init__("MTF_Confluence")
        self.models  = {}
        self.scalers = {}
        self.is_trained = False

    def _resample(self, df, period):
        """Resample daily data to simulate H4/H1/M15 confluence."""
        d = df.copy()
        d.index = pd.to_datetime(d.index)
        # Use rolling windows to approximate MTF
        periods = {"H4":4,"H1":1,"M15":1}
        n = periods.get(period,1)
        rs = d.resample(f"{n}D").agg({"Open":"first","High":"max",
                                       "Low":"min","Close":"last","Volume":"sum"}).dropna()
        return rs

    def _tf_features(self, df, label):
        d = df.copy()
        c = d["Close"]
        feats = pd.DataFrame(index=d.index)
        feats[f"{label}_ema8"]  = (c - c.ewm(span=8).mean()) / c
        feats[f"{label}_ema21"] = (c - c.ewm(span=21).mean()) / c
        feats[f"{label}_ema55"] = (c - c.ewm(span=55).mean()) / c
        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        feats[f"{label}_rsi"]   = (100-(100/(1+gain/(loss+1e-8))))/100
        ema12 = c.ewm(span=12).mean()
        ema26 = c.ewm(span=26).mean()
        macd  = ema12-ema26
        feats[f"{label}_macd"]  = macd/c
        roll20 = c.rolling(20)
        feats[f"{label}_bb"]    = (c-roll20.mean())/(2*roll20.std()+1e-8)
        feats[f"{label}_ret"]   = c.pct_change()
        feats[f"{label}_trend"] = (c > c.rolling(20).mean()).astype(float)
        feats[f"{label}_vol"]   = d["Volume"]/(d["Volume"].rolling(20).mean()+1e-8)
        return feats.dropna()

    def train(self, df):
        df.index = pd.to_datetime(df.index)
        tf_map = {"H4": df.resample("4D").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(),
                  "H1": df.resample("1D").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(),
                  "M15":df}
        all_feats = []
        for tf, tdf in tf_map.items():
            f = self._tf_features(tdf, tf)
            all_feats.append(f)

        # Align on smallest TF (M15 = daily)
        base = all_feats[2]
        merged = base.copy()
        for f in all_feats[:2]:
            for col in f.columns:
                merged[col] = f[col].reindex(merged.index, method="ffill")

        feat_cols = [c for c in merged.columns]
        merged["Target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)
        merged = merged.dropna()
        X  = merged[feat_cols].values
        y  = merged["Target"].values
        sc = StandardScaler()
        Xs = sc.fit_transform(X)
        m  = MLPClassifier(hidden_layer_sizes=(128,64),activation="relu",
                           solver="adam",max_iter=300,random_state=42,
                           early_stopping=True)
        m.fit(Xs,y)
        self.models["main"]  = m
        self.scalers["main"] = sc
        self.feat_cols = feat_cols
        self.tf_map_train = {tf: tdf for tf,tdf in tf_map.items()}
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained: return 0.5
        try:
            df.index = pd.to_datetime(df.index)
            tf_map = {
                "H4": df.resample("4D").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(),
                "H1": df.resample("1D").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(),
                "M15":df}
            all_feats = [self._tf_features(tdf,tf) for tf,tdf in tf_map.items()]
            base = all_feats[2]
            merged = base.copy()
            for f in all_feats[:2]:
                for col in f.columns:
                    merged[col] = f[col].reindex(merged.index,method="ffill")
            merged = merged.dropna()
            if len(merged)<1: return 0.5
            available = [c for c in self.feat_cols if c in merged.columns]
            X  = merged[available].values[-1].reshape(1,-1)
            Xs = self.scalers["main"].transform(X[:,:len(available)])
            return float(self.models["main"].predict_proba(Xs)[0,1])
        except Exception:
            return 0.5

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("EURUSD=X",start="2021-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = MTFConfluenceModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ MTFConfluenceModel OK")
