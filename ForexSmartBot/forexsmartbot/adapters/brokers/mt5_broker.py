"""MetaTrader 5 broker adapter backed by the shared Supervisor bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import requests

from ...core.interfaces import IBroker, Position


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class MT5BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 5050

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}".rstrip("/")


class MT5Broker(IBroker):
    """MT5 broker implementation using the shared Flask bridge."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5050):
        self._config = MT5BridgeConfig(host=host, port=port)
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._connected = False

    def _get(self, path: str, **params) -> Optional[dict]:
        try:
            response = self._session.get(
                f"{self._config.base_url}{path}",
                params=params or None,
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def _post(self, path: str, payload: Optional[dict] = None) -> Optional[dict]:
        try:
            response = self._session.post(
                f"{self._config.base_url}{path}",
                json=payload or {},
                timeout=8,
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def connect(self) -> bool:
        status = self._get("/health")
        self._connected = bool(status)
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        return bool(self._get("/health"))

    def get_price(self, symbol: str) -> Optional[float]:
        signal = self._get("/signal", symbol=symbol)
        if signal:
            price = signal.get("price")
            if price is not None:
                return _safe_float(price, None)

        positions = self._get("/positions")
        if positions and isinstance(positions.get("positions"), list):
            for position in positions["positions"]:
                if str(position.get("symbol", "")).upper() == symbol.upper():
                    current = position.get("current_price") or position.get("entry")
                    if current is not None:
                        return _safe_float(current, None)
        return None

    def submit_order(
        self,
        symbol: str,
        side: int,
        quantity: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[str]:
        payload = {
            "symbol": symbol,
            "side": "BUY" if side > 0 else "SELL",
            "lot": quantity,
            "sl": stop_loss,
            "tp": take_profit,
            "order_type": "BUY" if side > 0 else "SELL",
        }
        result = self._post("/trades/manual", payload)
        if not result:
            return None

        if result.get("queued_mt"):
            return str(result.get("queued_id") or result.get("order_id") or result.get("status") or "mt5_queued")
        return str(result.get("order_id") or result.get("status") or "mt5_submitted")

    def close_all(self, symbol: str) -> bool:
        result = self._post("/trades/close_all", {"symbol": symbol})
        return bool(result and result.get("ok", True))

    def get_positions(self) -> Dict[str, Position]:
        response = self._get("/positions")
        if not response:
            return {}

        positions: Dict[str, Position] = {}
        for raw in response.get("positions", []):
            symbol = str(raw.get("symbol", "")).upper()
            if not symbol:
                continue

            order_side = str(raw.get("type", raw.get("side", "BUY"))).upper()
            side = 1 if "BUY" in order_side or "LONG" in order_side else -1
            entry_price = _safe_float(raw.get("entry"), 0.0)
            current_price = _safe_float(raw.get("current_price", entry_price), entry_price)
            pnl = _safe_float(raw.get("pnl"), 0.0)

            positions[symbol] = Position(
                symbol=symbol,
                side=side,
                quantity=_safe_float(raw.get("lot"), 0.0),
                entry_price=entry_price,
                current_price=current_price,
                unrealized_pnl=pnl,
                stop_loss=_safe_float(raw.get("sl"), 0.0) or None,
                take_profit=_safe_float(raw.get("tp"), 0.0) or None,
            )
        return positions

    def get_balance(self) -> float:
        response = self._get("/account")
        if response and isinstance(response.get("account"), dict):
            return _safe_float(response["account"].get("balance"), 10000.0)
        return 10000.0

    def get_equity(self) -> float:
        response = self._get("/account")
        if response and isinstance(response.get("account"), dict):
            return _safe_float(response["account"].get("equity"), self.get_balance())
        return self.get_balance()
