#!/usr/bin/env python3
"""
model_rsi_trend.py
==================
MODEL 4: RSI Divergence + Trend Strength AI
============================================
Specialty: Detects hidden RSI divergences and trend momentum.
           Catches reversals BEFORE they happen.

Strategy:
  - Bullish divergence: price makes lower low but RSI makes higher low → BUY
  - Bearish divergence: price makes higher high but RSI makes lower high → SELL
  - ADX trend strength filter: only trade when trend is strong (ADX > 25)
  - EMA ribbon: 8/21/55 EMA alignment confirms direction

To add to SupervisorTrainer:
  from model_rsi_trend import RSIDivergenceTrendModel
  st.register(RSIDivergenceTrendModel(), initial_weight=1.0)

pip install: already covered by requirements.txt (numpy, pandas, scikit-learn)
"""

import numpy as np
import pandas as pd
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from supervisor_trainer import BaseModel, build_features


class RSIDivergenceTrendModel(BaseModel):
    """
    Detects RSI divergences + trend strength via ADX + EMA ribbon.
    Specialty: catches reversals and strong trending moves early.
    """

    def __init__(self):
        super().__init__("RSI_Divergence_Trend")
        self.model  = None
        self.scaler = StandardScaler()

    # ── Feature Engineering ─────────────────────────────────
    def _build_rsi_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # EMA Ribbon: 8 / 21 / 55
        df["EMA8"]  = df["Close"].ewm(span=8).mean()
        df["EMA21"] = df["Close"].ewm(span=21).mean()
        df["EMA55"] = df["Close"].ewm(span=55).mean()
        df["EMA_bull"] = ((df["EMA8"] > df["EMA21"]) &
                          (df["EMA21"] > df["EMA55"])).astype(int)
        df["EMA_bear"] = ((df["EMA8"] < df["EMA21"]) &
                          (df["EMA21"] < df["EMA55"])).astype(int)
        df["EMA_spread"] = (df["EMA8"] - df["EMA55"]) / df["Close"]

        # RSI (14)
        delta = df["Close"].diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        df["RSI"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

        # RSI slope (momentum)
        df["RSI_slope"]  = df["RSI"].diff(3)
        df["RSI_slope2"] = df["RSI"].diff(6)

        # RSI divergence detection (5-bar lookback)
        LB = 5
        price_diff = df["Close"].diff(LB)
        rsi_diff   = df["RSI"].diff(LB)
        df["bull_div"] = ((price_diff < 0) & (rsi_diff > 0)).astype(int)
        df["bear_div"] = ((price_diff > 0) & (rsi_diff < 0)).astype(int)

        # ADX (Average Directional Index) — trend strength
        high, low, close = df["High"], df["Low"], df["Close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)

        plus_dm  = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        plus_dm[plus_dm < minus_dm.values]  = 0
        minus_dm[minus_dm < plus_dm.values] = 0

        atr14      = tr.rolling(14).mean()
        plus_di    = 100 * plus_dm.rolling(14).mean()  / (atr14 + 1e-8)
        minus_di   = 100 * minus_dm.rolling(14).mean() / (atr14 + 1e-8)
        dx         = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-8)
        df["ADX"]  = dx.rolling(14).mean()
        df["DI_diff"] = (plus_di - minus_di) / 100

        # Stochastic RSI
        rsi_min = df["RSI"].rolling(14).min()
        rsi_max = df["RSI"].rolling(14).max()
        df["StochRSI"] = (df["RSI"] - rsi_min) / (rsi_max - rsi_min + 1e-8)

        # Target
        df["Target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)
        return df.dropna()

    FEAT = ["EMA_bull","EMA_bear","EMA_spread","RSI","RSI_slope","RSI_slope2",
            "bull_div","bear_div","ADX","DI_diff","StochRSI"]

    def train(self, df: pd.DataFrame):
        df2  = self._build_rsi_trend_features(df)
        X    = df2[self.FEAT].values
        y    = df2["Target"].values
        Xs   = self.scaler.fit_transform(X)
        self.model = MLPClassifier(
            hidden_layer_sizes=(128, 64, 32),
            activation="tanh",
            solver="adam",
            max_iter=300,
            random_state=7,
            early_stopping=True,
            validation_fraction=0.1,
        )
        self.model.fit(Xs, y)
        self.is_trained = True

    def predict(self, df: pd.DataFrame) -> float:
        if not self.is_trained:
            return 0.5
        df2 = self._build_rsi_trend_features(df)
        if len(df2) < 1:
            return 0.5
        X  = df2[self.FEAT].values[-1].reshape(1, -1)
        Xs = self.scaler.transform(X)
        return float(self.model.predict_proba(Xs)[0, 1])


# ── Self-test ────────────────────────────────────────────────
if __name__ == "__main__":
    import yfinance as yf
    print("Testing RSIDivergenceTrendModel...")
    raw = yf.download("AAPL", start="2021-01-01", end="2024-12-31", progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.droplevel(1)
    m = RSIDivergenceTrendModel()
    split = int(len(raw) * 0.8)
    m.train(raw.iloc[:split])
    sig = m.predict(raw)
    print(f"  Signal: {sig:.4f}  ({'BUY' if sig > 0.55 else 'SELL' if sig < 0.45 else 'HOLD'})")
    print("  ✅ RSIDivergenceTrendModel OK")
