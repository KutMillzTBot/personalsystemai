"""Data provider adapters."""

from .yfinance_provider import YFinanceProvider
from .csv_provider import CSVProvider
from .alpha_vantage_provider import AlphaVantageProvider
from .oanda_provider import OANDAProvider
from .mt5_provider import MT5Provider
from .multi_provider import MultiProvider
from .dummy_provider import DummyProvider
from .config import DataProviderConfig

MT4Provider = MT5Provider

__all__ = [
    'YFinanceProvider', 
    'CSVProvider', 
    'AlphaVantageProvider', 
    'OANDAProvider', 
    'MT5Provider',
    'MT4Provider', 
    'MultiProvider',
    'DummyProvider',
    'DataProviderConfig'
]
