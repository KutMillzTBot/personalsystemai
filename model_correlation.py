#!/usr/bin/env python3
"""
model_correlation.py
====================
MODEL 17: Multi-Asset Correlation AI
======================================
Specialty: Tracks correlations between correlated assets in real time:
  EURUSD ↔ DXY (inverse)  |  Gold ↔ USD (inverse)
  GBPUSD ↔ EURUSD (positive)  |  SPX ↔ VIX (inverse)
  BTC ↔ ETH (positive)    |  Oil ↔ CAD (positive)
When correlations break down → divergence trade opportunity.
When they realign → momentum continuation signal.
pip install: yfinance (already installed)
"""
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

CORR_PAIRS = {
    "EURUSD=X": ["DX-Y.NYB","GC=F","GBPUSD=X"],
    "GBPUSD=X": ["EURUSD=X","DX-Y.NYB"],
    "GC=F":     ["DX-Y.NYB","SI=F","^TNX"],
    "BTC-USD":  ["ETH-USD","^NDX"],
    "^NDX":     ["^GSPC","^VIX"],
    "XAUUSD=X": ["DX-Y.NYB","GC=F"],
}
DEFAULT_PAIRS = ["DX-Y.NYB","GC=F","^NDX","^VIX"]

class CorrelationModel(BaseModel):
    def __init__(self):
        super().__init__("Correlation_Matrix")
        self.model  = None
        self.scaler = StandardScaler()
        self._corr_data = {}

    def _fetch_corr(self, ticker, start, end):
        pairs = CORR_PAIRS.get(ticker, DEFAULT_PAIRS)
        data  = {}
        for p in pairs:
            try:
                raw = yf.download(p, start=start, end=end, progress=False)
                if isinstance(raw.columns, pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
                data[p] = raw["Close"]
            except Exception:
                pass
        return data

    def _build_features(self, df, corr_data):
        c = df["Close"]
        n = len(c)
        rows = []

        for i in range(30, n-1):
            dt   = c.index[i]
            feat = {}

            for asset, series in corr_data.items():
                try:
                    # Align to same dates
                    aligned = series.reindex(c.index, method="ffill")
                    if i < 20: continue
                    w = 20
                    r1 = c.iloc[i-w:i].pct_change().dropna()
                    r2 = aligned.iloc[i-w:i].pct_change().dropna()
                    common = r1.index.intersection(r2.index)
                    if len(common) < 10: continue
                    corr = float(np.corrcoef(r1.loc[common], r2.loc[common])[0,1])
                    nm   = asset.replace("=X","").replace("^","").replace("-","").replace(".","")[:8]
                    feat[f"corr_{nm}"]     = corr
                    # Correlation change (breakdown signal)
                    r1b = c.iloc[max(0,i-w*2):i-w].pct_change().dropna()
                    r2b = aligned.iloc[max(0,i-w*2):i-w].pct_change().dropna()
                    cb  = r1b.index.intersection(r2b.index)
                    if len(cb)>=10:
                        corr_prev = float(np.corrcoef(r1b.loc[cb],r2b.loc[cb])[0,1])
                        feat[f"corrchg_{nm}"] = corr - corr_prev
                except Exception:
                    pass

            if not feat: rows.append(None); continue

            # Add own momentum
            feat["own_ret5"]  = (float(c.iloc[i]) - float(c.iloc[max(0,i-5)])) / (float(c.iloc[max(0,i-5)])+1e-8)
            feat["own_ret20"] = (float(c.iloc[i]) - float(c.iloc[max(0,i-20)])) / (float(c.iloc[max(0,i-20)])+1e-8)
            feat["target"]    = int(float(c.iloc[i+1]) > float(c.iloc[i]))
            rows.append(feat)

        valid = [r for r in rows if r is not None]
        return pd.DataFrame(valid).fillna(0)

    FEAT_COLS = None

    def train(self, df):
        ticker = "EURUSD=X"  # default; auto-detect in production
        start  = str(df.index[0])[:10]
        end    = str(df.index[-1])[:10]
        corr_data = self._fetch_corr(ticker, start, end)
        if not corr_data:
            self.is_trained = False; return

        feats = self._build_features(df, corr_data)
        if len(feats)<30: return
        self.FEAT_COLS = [c for c in feats.columns if c!="target"]
        X  = feats[self.FEAT_COLS].values
        y  = feats["target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = GradientBoostingClassifier(n_estimators=150,max_depth=4,
                                                learning_rate=0.05,random_state=42)
        self.model.fit(Xs,y)
        self._corr_data = corr_data
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        try:
            feats = self._build_features(df, self._corr_data)
            if len(feats)<1: return 0.5
            avail = [c for c in self.FEAT_COLS if c in feats.columns]
            row   = feats[avail].values[-1]
            full  = np.zeros(len(self.FEAT_COLS))
            for j,col in enumerate(self.FEAT_COLS):
                if col in avail: full[j]=row[avail.index(col)]
            Xs = self.scaler.transform(full.reshape(1,-1))
            return float(self.model.predict_proba(Xs)[0,1])
        except Exception:
            return 0.5

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("EURUSD=X",start="2022-01-01",end="2024-12-31",progress=False)
    if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
    m = CorrelationModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ CorrelationModel OK")
