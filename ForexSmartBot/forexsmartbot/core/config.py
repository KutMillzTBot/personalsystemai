from pydantic import BaseModel, Field
from typing import List, Literal
import os
from dotenv import load_dotenv

# Ensure .env is loaded before reading environment variables
# This is safe to call multiple times - it only loads if not already loaded
load_dotenv(override=False)

class AppConfig(BaseModel):
    broker: Literal["PAPER", "MT5"] = "PAPER"
    account_balance: float = 10_000

    trade_amount_min: float = 10
    trade_amount_max: float = 100
    risk_pct: float = 0.02
    max_drawdown_pct: float = 0.25

    mt5_host: str = "127.0.0.1"
    mt5_port: int = 5050

    symbols: List[str] = Field(default_factory=lambda: ["EURUSD","USDJPY","GBPUSD"])

    @classmethod
    def from_env(cls) -> "AppConfig":
        broker = os.getenv("BROKER", "PAPER").upper()
        account_balance = float(os.getenv("ACCOUNT_BALANCE", "10000"))
        trade_amount_min = float(os.getenv("TRADE_AMOUNT_MIN", "10"))
        trade_amount_max = float(os.getenv("TRADE_AMOUNT_MAX", "100"))
        risk_pct = float(os.getenv("RISK_PCT", "0.02"))
        max_dd = float(os.getenv("MAX_DRAWDOWN_PCT", "0.25"))
        mt5_host = os.getenv("MT5_BRIDGE_HOST", os.getenv("MT4_ZMQ_HOST", "127.0.0.1"))
        mt5_port = int(os.getenv("MT5_BRIDGE_PORT", os.getenv("MT4_ZMQ_PORT", "5050")))
        symbols = [s.strip() for s in os.getenv("SYMBOLS","EURUSD,USDJPY,GBPUSD").split(",")]
        return cls(broker=broker, account_balance=account_balance,
                   trade_amount_min=trade_amount_min, trade_amount_max=trade_amount_max,
                   risk_pct=risk_pct, max_drawdown_pct=max_dd,
                   mt5_host=mt5_host, mt5_port=mt5_port, symbols=symbols)
