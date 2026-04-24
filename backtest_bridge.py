#!/usr/bin/env python3
"""
backtest_bridge.py
==================
Connects your existing backtest system to SupervisorTrainer so
the supervisor pre-warms its model weights from historical
backtest performance BEFORE going live.

HOW IT WORKS:
  Your backtest already knows:
    - What each model predicted on each past day
    - What actually happened (price went up or down)

  BacktestBridge feeds that history into the supervisor's
  PerformanceTracker so it starts with informed weights
  instead of equal weights on day 1.

WIRING OPTIONS (pick whichever fits your system):
  Option A — Pass a DataFrame  (most common)
  Option B — Pass a CSV path
  Option C — Pass raw lists
  Option D — Streaming (feed one row at a time, e.g. live backtest)
  Option E — Register a callback (your backtest calls us automatically)

USAGE:
  from backtest_bridge import BacktestBridge
  from supervisor_trainer import SupervisorTrainer

  st     = SupervisorTrainer(ticker="AAPL")
  bridge = BacktestBridge(st)

  # Option A — your backtest DataFrame
  bridge.load_dataframe(your_backtest_df,
      model_col_map={
          "my_lstm_signal":     "LSTM_Prophet",
          "my_rl_signal":       "RL_Trader",
          "my_sentiment_score": "Sentiment_Scout",
      },
      actual_col="actual_direction",   # 1=up, 0=down
  )

  bridge.report()          # see pre-warmed weights
  results = st.run()       # now runs with informed weights
"""

import numpy as np
import pandas as pd
from typing import Callable


class BacktestBridge:
    """
    Feeds backtest results into SupervisorTrainer's PerformanceTracker
    so model weights are pre-warmed from historical performance.
    """

    def __init__(self, supervisor_trainer):
        """
        Parameters
        ----------
        supervisor_trainer : SupervisorTrainer instance
        """
        self.st      = supervisor_trainer
        self.tracker = supervisor_trainer.tracker
        self._fed    = 0   # total rows ingested

    # ──────────────────────────────────────────────────────────
    #  OPTION A — Feed a DataFrame directly
    # ──────────────────────────────────────────────────────────
    def load_dataframe(
        self,
        df: pd.DataFrame,
        model_col_map: dict[str, str],
        actual_col: str,
        date_col: str = None,
    ):
        """
        Parameters
        ----------
        df            : your backtest DataFrame
        model_col_map : {backtest_col_name -> supervisor_model_name}
                        e.g. {"lstm_pred": "LSTM_Prophet"}
        actual_col    : column name containing 1 (price up) or 0 (price down)
        date_col      : optional, for logging only

        Your backtest signals should be floats in [0, 1].
        If they are raw prices or percentages, use normalize=True below.
        """
        print(f"\n🔗 BacktestBridge — Loading DataFrame ({len(df)} rows)")
        print(f"   Model mapping: {model_col_map}")

        missing_models = []
        for bt_col, model_name in model_col_map.items():
            if model_name not in self.tracker._hist:
                self.tracker.init_model(model_name, initial_weight=1.0)
                missing_models.append(model_name)

        if missing_models:
            print(f"   ⚠️  Auto-registered new models: {missing_models}")

        count = 0
        for _, row in df.iterrows():
            actual = int(row[actual_col])
            for bt_col, model_name in model_col_map.items():
                pred = float(row[bt_col])
                # Auto-normalize if signal is outside [0, 1]
                if pred > 1.0 or pred < 0.0:
                    pred = self._normalize(pred, df[bt_col])
                self.tracker.record(model_name, pred, actual)
            count += 1

        self._fed += count
        print(f"   ✅ Fed {count} backtest rows into PerformanceTracker")
        self._print_weights()

    # ──────────────────────────────────────────────────────────
    #  OPTION B — Feed from a CSV file path
    # ──────────────────────────────────────────────────────────
    def load_csv(
        self,
        csv_path: str,
        model_col_map: dict[str, str],
        actual_col: str,
        date_col: str = None,
    ):
        """Load your backtest results from a CSV file."""
        print(f"\n🔗 BacktestBridge — Loading CSV: {csv_path}")
        df = pd.read_csv(csv_path)
        if date_col and date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col])
            df = df.sort_values(date_col)
        self.load_dataframe(df, model_col_map, actual_col, date_col)

    # ──────────────────────────────────────────────────────────
    #  OPTION C — Feed raw Python lists
    # ──────────────────────────────────────────────────────────
    def load_lists(
        self,
        model_predictions: dict[str, list],
        actuals: list,
    ):
        """
        Parameters
        ----------
        model_predictions : {"ModelName": [0.6, 0.4, 0.7, ...], ...}
        actuals           : [1, 0, 1, 1, 0, ...]   (1=up, 0=down)
        """
        print(f"\n🔗 BacktestBridge — Loading raw lists ({len(actuals)} rows)")
        for model_name, preds in model_predictions.items():
            if model_name not in self.tracker._hist:
                self.tracker.init_model(model_name, initial_weight=1.0)
            for pred, actual in zip(preds, actuals):
                self.tracker.record(model_name, float(pred), int(actual))
        self._fed += len(actuals)
        print(f"   ✅ Fed {len(actuals)} rows")
        self._print_weights()

    # ──────────────────────────────────────────────────────────
    #  OPTION D — Stream one row at a time (live backtest loop)
    # ──────────────────────────────────────────────────────────
    def feed_row(
        self,
        model_signals: dict[str, float],
        actual: int,
    ):
        """
        Call this inside your backtest loop on each iteration.

        Example:
            for day in my_backtest:
                bridge.feed_row(
                    model_signals={
                        "LSTM_Prophet":     day.lstm_pred,
                        "RL_Trader":        day.rl_pred,
                        "Sentiment_Scout":  day.sentiment,
                    },
                    actual=day.price_went_up,
                )
        """
        for model_name, pred in model_signals.items():
            if model_name not in self.tracker._hist:
                self.tracker.init_model(model_name, initial_weight=1.0)
            self.tracker.record(model_name, float(pred), int(actual))
        self._fed += 1

    # ──────────────────────────────────────────────────────────
    #  OPTION E — Register a callback hook
    #  Your backtest system calls the hook automatically
    # ──────────────────────────────────────────────────────────
    def register_callback(self) -> Callable:
        """
        Returns a callback function. Pass it to your backtest system
        so it automatically feeds results into the supervisor.

        Example:
            bridge   = BacktestBridge(st)
            on_step  = bridge.register_callback()

            # Inside your existing backtest engine:
            my_backtest.on_step_complete = on_step

            # Your backtest just needs to call:
            on_step({"LSTM_Prophet": 0.7, "RL_Trader": 0.55}, actual=1)
        """
        def _callback(model_signals: dict[str, float], actual: int):
            self.feed_row(model_signals, actual)
        print("   🔌 Callback registered — your backtest can now call it directly")
        return _callback

    # ──────────────────────────────────────────────────────────
    #  HELPERS
    # ──────────────────────────────────────────────────────────
    @staticmethod
    def _normalize(value: float, series: pd.Series) -> float:
        mn, mx = series.min(), series.max()
        if mx == mn:
            return 0.5
        return float((value - mn) / (mx - mn))

    def _print_weights(self):
        nw = self.tracker.normalized_weights()
        if not nw:
            return
        print("   📊 Pre-warmed weights after backtest ingestion:")
        for name, w in sorted(nw.items(), key=lambda x: -x[1]):
            bar = "█" * int(w * 40)
            print(f"      {name:<22} {w*100:5.1f}%  {bar}")

    def report(self):
        """Print a full performance summary from backtest data."""
        print(f"\n{'='*60}")
        print(f"  BacktestBridge Report — {self._fed} rows ingested")
        print(f"{'='*60}")
        summary = self.tracker.summary()
        nw      = self.tracker.normalized_weights()
        summary["Norm_Weight%"] = summary["Model"].map(lambda n: f"{nw.get(n,0)*100:.1f}%")
        print(summary.to_string(index=False))
        print()
        best = max(nw, key=nw.get)
        print(f"  🏆 Supervisor trusts most: {best} ({nw[best]*100:.1f}% weight)")
        print(f"  Total backtest rows fed  : {self._fed}")


# ================================================================
#  DEMO — shows all 5 wiring options
# ================================================================
if __name__ == "__main__":
    from supervisor_trainer import SupervisorTrainer

    st     = SupervisorTrainer(ticker="AAPL")
    bridge = BacktestBridge(st)

    # ── Simulate a backtest output DataFrame ─────────────────
    np.random.seed(42)
    n = 200
    fake_backtest = pd.DataFrame({
        "date":            pd.date_range("2023-01-01", periods=n, freq="B"),
        "lstm_signal":     np.random.uniform(0.3, 0.8, n),   # your LSTM output
        "rl_signal":       np.random.uniform(0.2, 0.9, n),   # your RL output
        "sentiment_score": np.random.uniform(0.4, 0.7, n),   # your sentiment
        "actual_up":       np.random.randint(0, 2, n),        # ground truth
    })

    # ── Option A: Feed the DataFrame ─────────────────────────
    bridge.load_dataframe(
        df=fake_backtest,
        model_col_map={
            "lstm_signal":     "LSTM_Prophet",
            "rl_signal":       "RL_Trader",
            "sentiment_score": "Sentiment_Scout",
        },
        actual_col="actual_up",
        date_col="date",
    )

    bridge.report()

    # ── Now run live — supervisor already knows which to trust ─
    print("\n▶ Running live session with pre-warmed weights...")
    results = st.run()
    st.status()
    st.get_signal()
