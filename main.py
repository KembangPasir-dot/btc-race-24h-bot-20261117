"""Long-only BTC trend, bounce and rolling-low strategy.

Signals use closes already received; orders execute at the following open.
The SDK handles hello, batch sequence replies and done without extra stdout.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
from makefun_bars import run

FAST = 9
SLOW = 21
TP_BPS = 120
STOP_BPS = 80
LEVEL_TP_BPS = 150
LEVEL_STOP_BPS = 100
DIP_BPS = 80


class Strategy:
    def __init__(self):
        self.closes = []
        self.fast = None
        self.slow = None
        self.entry = None
        self.pending = None
        self.ever_filled = False
        self.count = 0

    def on_batch(self, state, batch):
        symbol = state.hello["symbols"][0]["symbol"]
        held = state.positions.get(symbol)
        if self.pending is not None:
            if held:
                self.entry = self.pending
                self.ever_filled = True
            self.pending = None
        if not held:
            self.entry = None
        bars = [b for b in batch["bars"] if b["symbol"] == symbol]
        if not bars:
            return []
        close = int(bars[0]["c"])
        previous = self.closes[-1] if self.closes else close
        gap = 0 if self.fast is None else self.fast - self.slow
        if self.fast is None:
            self.fast = self.slow = float(close)
        else:
            self.fast += 2 / (FAST + 1) * (close - self.fast)
            self.slow += 2 / (SLOW + 1) * (close - self.slow)
        self.closes.append(close)
        self.closes = self.closes[-120:]
        if state.warming_up:
            return []
        self.count += 1
        if held:
            if self.entry is None:
                return []
            price, tp, stop = self.entry
            if close * 10000 >= price * (10000 + tp) or close * 10000 < price * (10000 - stop):
                return [{"side": "sell", "symbol": symbol, "qty": held.qty,
                         "max_slippage_bps": 100}]
            return []
        cross = gap <= 0 and self.fast > self.slow
        threshold = 50 if self.count >= 720 and not self.ever_filled else DIP_BPS
        bounce = close > previous
        dip = (len(self.closes) >= 15 and bounce and
               close * 10000 <= self.closes[-15] * (10000 - threshold))
        level = (len(self.closes) >= 120 and bounce and
                 close * 1000 <= min(self.closes) * 1001)
        if not (cross or dip or level):
            return []
        amount = min(state.cash, state.weight_room(symbol))
        if amount < int(state.hello["fees"]["min_notional_quote_units"]):
            return []
        # Base signal has priority, then dip, then the wider level entry.
        tp, stop = (TP_BPS, STOP_BPS) if cross or dip else (LEVEL_TP_BPS, LEVEL_STOP_BPS)
        self.pending = (close, tp, stop)
        return [{"side": "buy", "symbol": symbol,
                 "notional_quote_units": amount, "max_slippage_bps": 100}]


if __name__ == "__main__":
    run(Strategy().on_batch)
