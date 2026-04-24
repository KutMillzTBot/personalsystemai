import json
from dataclasses import dataclass

import requests


@dataclass
class MT5Bridge:
    host: str
    port: int

    def __post_init__(self):
        self.base_url = f"http://{self.host}:{self.port}".rstrip("/")
        self.session = requests.Session()

    def send(self, method: str, path: str, **kwargs):
        if method.upper() == "GET":
            response = self.session.get(f"{self.base_url}{path}", params=kwargs or None, timeout=8)
        else:
            response = self.session.post(f"{self.base_url}{path}", json=kwargs or {}, timeout=8)
        response.raise_for_status()
        return response.json()

    def price(self, symbol: str):
        return self.send("GET", "/signal", symbol=symbol)

    def order(self, symbol: str, side: int, volume: float, sl: float | None = None, tp: float | None = None):
        payload = {
            "symbol": symbol,
            "side": "BUY" if side > 0 else "SELL",
            "lot": volume,
            "sl": sl,
            "tp": tp,
            "order_type": "BUY" if side > 0 else "SELL",
        }
        return self.send("POST", "/trades/manual", **payload)

    def close_all(self, symbol: str):
        return self.send("POST", "/trades/close_all", symbol=symbol)
    
    def historical_data(self, symbol: str, timeframe: str, start_time: int, end_time: int):
        return self.send("GET", "/deriv/candles", symbol=symbol, timeframe=timeframe, start=start_time, end=end_time, count=1000)
    
    def symbol_info(self, symbol: str):
        return self.send("GET", "/signal", symbol=symbol)
    
    def account_info(self):
        return self.send("GET", "/account")
    
    def ping(self):
        return self.send("GET", "/health")
