from dataclasses import dataclass
from datetime import datetime


@dataclass
class StructureEvent:
    pattern: str
    direction: str
    confidence: float
    time: int
    symbol: str = ""
    zone_high: float = 0.0
    zone_low: float = 0.0
    top: float = 0.0
    bottom: float = 0.0


class MarketStructureEngine:
    def __init__(self, swing_lookback: int = 5):
        self.swing_lookback = swing_lookback
        self._last_bos = None

    def detect(self, symbol: str, candles: list) -> list:
        if not candles or len(candles) < 5:
            return []
        events = []
        swings = self._swing_points(candles)
        if swings.get("last_high") and swings.get("last_low"):
            events += self._liquidity_sweep(symbol, candles[-1], swings)
            events += self._bos(symbol, candles[-1], swings)
        events += self._order_block(symbol, candles)
        events += self._fvg(symbol, candles)
        events += self._mss(symbol, events)
        return events

    def _swing_points(self, candles: list) -> dict:
        last_high = None
        last_low = None
        for i in range(2, len(candles) - 2):
            h = float(candles[i].get("h", candles[i].get("high", 0)))
            l = float(candles[i].get("l", candles[i].get("low", 0)))
            prev_h = float(candles[i - 1].get("h", candles[i - 1].get("high", 0)))
            next_h = float(candles[i + 1].get("h", candles[i + 1].get("high", 0)))
            prev_l = float(candles[i - 1].get("l", candles[i - 1].get("low", 0)))
            next_l = float(candles[i + 1].get("l", candles[i + 1].get("low", 0)))
            if h > prev_h and h > next_h:
                last_high = h
            if l < prev_l and l < next_l:
                last_low = l
        return {"last_high": last_high, "last_low": last_low}

    def _liquidity_sweep(self, symbol: str, candle: dict, swings: dict) -> list:
        events = []
        high = float(candle.get("h", candle.get("high", 0)))
        low = float(candle.get("l", candle.get("low", 0)))
        close = float(candle.get("c", candle.get("close", 0)))
        ts = int(candle.get("time", 0))
        prev_high = swings.get("last_high")
        prev_low = swings.get("last_low")
        if prev_high and high > prev_high and close < prev_high:
            events.append(StructureEvent("liquidity_sweep", "buy_side", 0.72, ts, symbol=symbol))
        if prev_low and low < prev_low and close > prev_low:
            events.append(StructureEvent("liquidity_sweep", "sell_side", 0.72, ts, symbol=symbol))
        return events

    def _order_block(self, symbol: str, candles: list) -> list:
        events = []
        bodies = [abs(float(c.get("c", c.get("close", 0))) - float(c.get("o", c.get("open", 0)))) for c in candles[-20:]]
        avg_body = sum(bodies) / len(bodies) if bodies else 0
        last = candles[-1]
        body = abs(float(last.get("c", last.get("close", 0))) - float(last.get("o", last.get("open", 0))))
        if avg_body > 0 and body > avg_body * 2:
            # find previous opposite candle
            direction = "bullish" if float(last.get("c", last.get("close", 0))) > float(last.get("o", last.get("open", 0))) else "bearish"
            for c in reversed(candles[-10:-1]):
                c_dir = "bullish" if float(c.get("c", c.get("close", 0))) > float(c.get("o", c.get("open", 0))) else "bearish"
                if c_dir != direction:
                    high = float(c.get("h", c.get("high", 0)))
                    low = float(c.get("l", c.get("low", 0)))
                    ts = int(c.get("time", 0))
                    events.append(StructureEvent("order_block", direction, 0.68, ts, symbol=symbol, zone_high=high, zone_low=low))
                    break
        return events

    def _fvg(self, symbol: str, candles: list) -> list:
        events = []
        if len(candles) < 3:
            return events
        c1, c2, c3 = candles[-3], candles[-2], candles[-1]
        c1_high = float(c1.get("h", c1.get("high", 0)))
        c1_low = float(c1.get("l", c1.get("low", 0)))
        c3_high = float(c3.get("h", c3.get("high", 0)))
        c3_low = float(c3.get("l", c3.get("low", 0)))
        ts = int(c3.get("time", 0))
        if c1_high < c3_low:
            events.append(StructureEvent("fvg", "bullish", 0.66, ts, symbol=symbol, top=c3_low, bottom=c1_high))
        if c1_low > c3_high:
            events.append(StructureEvent("fvg", "bearish", 0.66, ts, symbol=symbol, top=c1_low, bottom=c3_high))
        return events

    def _bos(self, symbol: str, candle: dict, swings: dict) -> list:
        events = []
        close = float(candle.get("c", candle.get("close", 0)))
        ts = int(candle.get("time", 0))
        if swings.get("last_high") and close > swings["last_high"]:
            self._last_bos = "bullish"
            events.append(StructureEvent("bos", "bullish", 0.7, ts, symbol=symbol))
        if swings.get("last_low") and close < swings["last_low"]:
            self._last_bos = "bearish"
            events.append(StructureEvent("bos", "bearish", 0.7, ts, symbol=symbol))
        return events

    def _mss(self, symbol: str, events: list) -> list:
        # MSS when BOS flips direction
        bos = [e for e in events if e.pattern == "bos"]
        if not bos:
            return []
        latest = bos[-1]
        if self._last_bos and latest.direction != self._last_bos:
            return [StructureEvent("mss", latest.direction, 0.7, latest.time, symbol=symbol)]
        return []
