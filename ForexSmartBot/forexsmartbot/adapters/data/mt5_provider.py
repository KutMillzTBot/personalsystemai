"""MT5 data provider backed by the shared Supervisor bridge."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from ...core.interfaces import IDataProvider


TIMEFRAME_MAP = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D1",
}


def _period_to_range(period: str) -> tuple[int, int]:
    now = datetime.utcnow()
    if period == "1d":
        start = now - timedelta(days=1)
    elif period == "5d":
        start = now - timedelta(days=5)
    elif period == "1mo":
        start = now - timedelta(days=30)
    elif period == "3mo":
        start = now - timedelta(days=90)
    else:
        start = now - timedelta(days=30)
    return int(start.timestamp()), int(now.timestamp())


class MT5Provider(IDataProvider):
    """Market data provider using `/deriv/candles` and bridge snapshot routes."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5050):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}".rstrip("/")
        self.session = requests.Session()

    def _get(self, path: str, **params) -> Optional[dict]:
        try:
            response = self.session.get(f"{self.base_url}{path}", params=params or None, timeout=8)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def _normalize_symbol(self, symbol: str) -> str:
        symbol = symbol.replace("=X", "").upper()
        return symbol

    def _to_frame(self, payload: dict) -> pd.DataFrame:
        raw_rows = payload.get("candles") or payload.get("bars") or []
        if not raw_rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        rows = []
        index = []
        for candle in raw_rows:
            epoch = candle.get("epoch") or candle.get("time") or candle.get("timestamp") or candle.get("t")
            if epoch is None:
                continue
            index.append(datetime.utcfromtimestamp(int(epoch)))
            rows.append(
                {
                    "Open": float(candle.get("open", candle.get("o", 0))),
                    "High": float(candle.get("high", candle.get("h", 0))),
                    "Low": float(candle.get("low", candle.get("l", 0))),
                    "Close": float(candle.get("close", candle.get("c", 0))),
                    "Volume": float(candle.get("volume", candle.get("tick_volume", candle.get("v", 0)))),
                }
            )

        df = pd.DataFrame(rows, index=pd.DatetimeIndex(index))
        return df.sort_index()

    def get_data(self, symbol: str, start: str, end: str, interval: str = "1h") -> pd.DataFrame:
        timeframe = TIMEFRAME_MAP.get(interval, "H1")
        try:
            start_ts = int(datetime.fromisoformat(start).timestamp())
            end_ts = int(datetime.fromisoformat(end).timestamp())
        except Exception:
            start_ts, end_ts = _period_to_range("1mo")

        payload = self._get(
            "/deriv/candles",
            symbol=self._normalize_symbol(symbol),
            timeframe=timeframe,
            start=start_ts,
            end=end_ts,
            count=500,
        )
        if not payload:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        return self._to_frame(payload)

    def get_latest_price(self, symbol: str) -> Optional[float]:
        payload = self._get("/signal", symbol=self._normalize_symbol(symbol))
        if payload and payload.get("price") is not None:
            try:
                return float(payload["price"])
            except (TypeError, ValueError):
                pass

        hist = self._get(
            "/deriv/candles",
            symbol=self._normalize_symbol(symbol),
            timeframe="M15",
            count=2,
        )
        df = self._to_frame(hist or {})
        if not df.empty:
            return float(df["Close"].iloc[-1])
        return None

    def get_historical_data(self, symbol: str, period: str = "1d", interval: str = "1h") -> pd.DataFrame:
        timeframe = TIMEFRAME_MAP.get(interval, "H1")
        payload = self._get(
            "/deriv/candles",
            symbol=self._normalize_symbol(symbol),
            timeframe=timeframe,
            count=1000 if period not in {"1d", "5d"} else 200,
        )
        if not payload:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        return self._to_frame(payload)

    def is_available(self) -> bool:
        payload = self._get("/health")
        return bool(payload)
