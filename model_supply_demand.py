#!/usr/bin/env python3
"""
model_supply_demand.py
======================
MODEL 10: Supply & Demand Zone AI
===================================
Specialty: Identifies institutional Supply (sell) and Demand (buy) zones
           from explosive impulsive moves. Signals when price returns to
           test these untouched zones — highest probability entries.
No extra installs needed.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel

class SupplyDemandModel(BaseModel):
    def __init__(self):
        super().__init__("Supply_Demand_Zones")
        self.model  = None
        self.scaler = StandardScaler()

    def _detect_zones(self, df, window=5, impulse_mult=1.5):
        o = df["Open"].values
        h = df["High"].values
        l = df["Low"].values
        c = df["Close"].values
        v = df["Volume"].values
        avg_range = np.mean(h - l)
        zones = []  # (type, top, bottom, idx, strength)

        for i in range(window, len(c)-window):
            move = abs(c[i] - c[i-1])
            if move < avg_range * impulse_mult: continue
            vol_spike = v[i] / (np.mean(v[max(0,i-20):i]) + 1e-8)

            if c[i] > c[i-1]:  # Bullish impulse → Demand zone formed before
                zone_top = max(o[i-window:i])
                zone_bot = min(l[i-window:i])
                zones.append(("demand", zone_top, zone_bot, i, move * vol_spike))
            else:               # Bearish impulse → Supply zone formed before
                zone_top = max(h[i-window:i])
                zone_bot = min(o[i-window:i])
                zones.append(("supply", zone_top, zone_bot, i, move * vol_spike))
        return zones

    def _build_features(self, df):
        c   = df["Close"].values
        n   = len(c)
        zones = self._detect_zones(df)
        rows  = []

        for i in range(50, n):
            price = c[i]
            feat  = {}

            # Find zones price is currently testing (returning to)
            demand_count, supply_count = 0, 0
            near_d_str, near_s_str = 0, 0
            for ztype, ztop, zbot, zidx, zstr in zones:
                if zidx >= i: continue  # zone must be in the past
                in_zone = zbot <= price <= ztop
                if ztype == "demand" and in_zone:
                    demand_count += 1
                    near_d_str   = max(near_d_str, zstr)
                elif ztype == "supply" and in_zone:
                    supply_count += 1
                    near_s_str   = max(near_s_str, zstr)

            feat["in_demand"] = float(demand_count > 0)
            feat["in_supply"] = float(supply_count > 0)
            feat["dem_str"]   = near_d_str
            feat["sup_str"]   = near_s_str
            feat["zone_diff"] = demand_count - supply_count

            # Nearest zone distances
            dists_d = [abs(price-(ztop+zbot)/2) for zt,ztop,zbot,zi,_ in zones if zt=="demand" and zi<i]
            dists_s = [abs(price-(ztop+zbot)/2) for zt,ztop,zbot,zi,_ in zones if zt=="supply" and zi<i]
            feat["dist_demand"] = min(dists_d)/price if dists_d else 1.0
            feat["dist_supply"] = min(dists_s)/price if dists_s else 1.0

            # Context
            feat["above_ema20"] = float(price > np.mean(c[max(0,i-20):i]))
            feat["above_ema50"] = float(price > np.mean(c[max(0,i-50):i]))
            rets = np.diff(c[max(0,i-5):i+1])
            feat["momentum"]    = float(np.sum(rets > 0)) / max(len(rets),1)
            feat["vol_ratio"]   = df["Volume"].iloc[i] / (df["Volume"].iloc[max(0,i-20):i].mean()+1e-8)
            feat["target"]      = int(c[min(i+1,n-1)] > price)
            rows.append(feat)

        return pd.DataFrame(rows)

    FEAT_COLS = None

    def train(self, df):
        feats = self._build_features(df)
        if len(feats) < 30: return
        self.FEAT_COLS = [c for c in feats.columns if c != "target"]
        X  = feats[self.FEAT_COLS].values
        y  = feats["target"].values
        Xs = self.scaler.fit_transform(X)
        self.model = RandomForestClassifier(n_estimators=200, max_depth=8,
                                            random_state=42, n_jobs=-1)
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df):
        if not self.is_trained or self.FEAT_COLS is None: return 0.5
        feats = self._build_features(df)
        if len(feats) < 1: return 0.5
        X  = feats[self.FEAT_COLS].values[-1].reshape(1,-1)
        Xs = self.scaler.transform(X)
        return float(self.model.predict_proba(Xs)[0,1])

if __name__ == "__main__":
    import yfinance as yf
    raw = yf.download("XAUUSD=X", start="2021-01-01", end="2024-12-31", progress=False)
    if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.droplevel(1)
    m = SupplyDemandModel()
    m.train(raw.iloc[:int(len(raw)*.8)])
    print(f"  Signal: {m.predict(raw):.4f}  ✅ SupplyDemandModel OK")
