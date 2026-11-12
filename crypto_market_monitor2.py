#!/usr/bin/env python3
"""Read-only public market monitor for Binance Spot and Bybit Spot.

This program collects public best-bid/best-ask quotes and estimates hypothetical
cross-exchange price differences. It never connects to accounts or places orders.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import websockets

# ----------------------------- Configuration -----------------------------
SYMBOLS = ("BTCUSDT", "ETHUSDT", "ETHBTC")

# Simulation assumption only; NOT a statement of either exchange's actual fee.
# 0.001 means 0.1% per hypothetical buy/sell leg.
FEE_RATE = 0.001

MAX_QUOTE_AGE_MS = 3000
MAX_PAIR_SKEW_MS = 1500
DISPLAY_INTERVAL = 1.0
DB_PATH = "market_monitor.db"

BINANCE_WS = (
    "wss://stream.binance.com:9443/stream?streams="
    + "/".join(s.lower() + "@bookTicker" for s in SYMBOLS)
)
BYBIT_WS = "wss://stream.bybit.com/v5/public/spot"
RECONNECT_MIN_SECONDS = 1
RECONNECT_MAX_SECONDS = 30
# -------------------------------------------------------------------------


@dataclass
class Quote:
    exchange: str
    symbol: str
    bid: float
    bid_size: float
    ask: float
    ask_size: float
    received_mono: float
    received_utc: str


latest: Dict[Tuple[str, str], Quote] = {}
connection_state = {"BINANCE": "starting", "BYBIT": "starting"}
last_error = {"BINANCE": "", "BYBIT": ""}
last_db_write: Dict[Tuple[str, str], float] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def valid_number(value) -> Optional[float]:
    try:
        number = float(value)
        if number > 0 and number < float("inf"):
            return number
    except (TypeError, ValueError):
        pass
    return None


def store_quote(db: sqlite3.Connection, quote: Quote) -> None:
    key = (quote.exchange, quote.symbol)
    now = time.monotonic()
    # Limit persistence to approximately one row per symbol/exchange per second.
    if now - last_db_write.get(key, 0.0) < 1.0:
        return
    db.execute(
        """INSERT INTO quotes
           (timestamp_utc, exchange, symbol, bid, bid_size, ask, ask_size)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (quote.received_utc, quote.exchange, quote.symbol,
         quote.bid, quote.bid_size, quote.ask, quote.ask_size),
    )
    last_db_write[key] = now


def save_opportunity(db: sqlite3.Connection, symbol: str, buy_exchange: str,
                     sell_exchange: str, buy_ask: float, sell_bid: float,
                     gross_pct: float, net_pct: float,
                     buy_age_ms: float, sell_age_ms: float) -> None:
    db.execute(
        """INSERT INTO comparisons
           (timestamp_utc, symbol, buy_exchange, sell_exchange, buy_ask,
            sell_bid, gross_pct, estimated_net_pct, buy_age_ms, sell_age_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (utc_now(), symbol, buy_exchange, sell_exchange, buy_ask, sell_bid,
         gross_pct, net_pct, buy_age_ms, sell_age_ms),
    )


def init_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            bid REAL NOT NULL,
            bid_size REAL NOT NULL,
            ask REAL NOT NULL,
            ask_size REAL NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            symbol TEXT NOT NULL,
            buy_exchange TEXT NOT NULL,
            sell_exchange TEXT NOT NULL,
            buy_ask REAL NOT NULL,
            sell_bid REAL NOT NULL,
            gross_pct REAL NOT NULL,
            estimated_net_pct REAL NOT NULL,
            buy_age_ms REAL NOT NULL,
            sell_age_ms REAL NOT NULL
        )"""
    )
    db.commit()
    return db


def update_quote(exchange: str, symbol: str, bid, bid_size, ask, ask_size,
                 db: sqlite3.Connection) -> None:
    if symbol not in SYMBOLS:
        return
    b, bs, a, ass = (valid_number(bid), valid_number(bid_size),
                     valid_number(ask), valid_number(ask_size))
    if None in (b, bs, a, ass) or b > a:
        return
    quote = Quote(exchange, symbol, b, bs, a, ass, time.monotonic(), utc_now())
    latest[(exchange, symbol)] = quote
    store_quote(db, quote)


async def run_binance(db: sqlite3.Connection) -> None:
    delay = RECONNECT_MIN_SECONDS
    while True:
        try:
            connection_state["BINANCE"] = "connecting"
            async with websockets.connect(
                BINANCE_WS, ping_interval=20, ping_timeout=20, close_timeout=5
            ) as ws:
                connection_state["BINANCE"] = "connected"
                last_error["BINANCE"] = ""
                delay = RECONNECT_MIN_SECONDS
                async for raw in ws:
                    try:
                        message = json.loads(raw)
                        data = message.get("data", {})
                        update_quote(
                            "BINANCE", data.get("s"), data.get("b"), data.get("B"),
                            data.get("a"), data.get("A"), db
                        )
                    except (ValueError, TypeError, AttributeError):
                        continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            connection_state["BINANCE"] = "reconnecting"
            last_error["BINANCE"] = str(exc)[:160]
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_SECONDS)


async def bybit_ping(ws) -> None:
    while True:
        await asyncio.sleep(20)
        await ws.send(json.dumps({"op": "ping"}))


async def run_bybit(db: sqlite3.Connection) -> None:
    delay = RECONNECT_MIN_SECONDS
    topics = ["orderbook.1." + symbol for symbol in SYMBOLS]
    while True:
        ping_task = None
        try:
            connection_state["BYBIT"] = "connecting"
            async with websockets.connect(
                BYBIT_WS, ping_interval=None, close_timeout=5, max_size=2**20
            ) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                ping_task = asyncio.create_task(bybit_ping(ws))
                connection_state["BYBIT"] = "connected"
                last_error["BYBIT"] = ""
                delay = RECONNECT_MIN_SECONDS
                # Keep each side of the depth-1 book until changed by a delta.
                book: Dict[str, dict] = {}
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if msg.get("op") == "pong" or msg.get("success") is True:
                        continue
                    topic = msg.get("topic", "")
                    if not topic.startswith("orderbook.1."):
                        continue
                    data = msg.get("data") or {}
                    symbol = data.get("s") or topic.rsplit(".", 1)[-1]
                    if symbol not in SYMBOLS:
                        continue
                    if msg.get("type") == "snapshot" or symbol not in book:
                        book[symbol] = {"bid": None, "bid_size": None,
                                        "ask": None, "ask_size": None}
                    current = book[symbol]
                    # Empty side in a delta means unchanged. A zero-size level
                    # removes that side; it is not treated as a valid quote.
                    for side, price_key, size_key in (
                        ("b", "bid", "bid_size"), ("a", "ask", "ask_size")
                    ):
                        levels = data.get(side) or []
                        if levels:
                            price = valid_number(levels[0][0])
                            size = valid_number(levels[0][1])
                            if price is None or size is None:
                                current[price_key] = current[size_key] = None
                            else:
                                current[price_key] = price
                                current[size_key] = size
                    if all(current.get(k) is not None for k in
                           ("bid", "bid_size", "ask", "ask_size")):
                        update_quote(
                            "BYBIT", symbol, current["bid"], current["bid_size"],
                            current["ask"], current["ask_size"], db
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            connection_state["BYBIT"] = "reconnecting"
            last_error["BYBIT"] = str(exc)[:160]
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_SECONDS)
        finally:
            if ping_task:
                ping_task.cancel()


def quote_age_ms(q: Quote, now: float) -> float:
    return max(0.0, (now - q.received_mono) * 1000.0)


def comparison(symbol: str, buy: Quote, sell: Quote, now: float):
    buy_age = quote_age_ms(buy, now)
    sell_age = quote_age_ms(sell, now)
    skew = abs(buy.received_mono - sell.received_mono) * 1000.0
    if buy_age > MAX_QUOTE_AGE_MS or sell_age > MAX_QUOTE_AGE_MS:
        return None
    if skew > MAX_PAIR_SKEW_MS or buy.ask <= 0:
        return None
    gross = (sell.bid / buy.ask - 1.0) * 100.0
    # Hypothetical fee on both legs; ignores depth, slippage and other costs.
    net = ((sell.bid * (1.0 - FEE_RATE)) /
           (buy.ask * (1.0 + FEE_RATE)) - 1.0) * 100.0
    return gross, net, buy_age, sell_age


def fmt(value: Optional[float], digits: int = 8) -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def dashboard(db: sqlite3.Connection) -> None:
    now = time.monotonic()
    lines = [
        "CRYPTO MARKET MONITOR v0.2  |  PUBLIC DATA / READ-ONLY / SIMULATION",
        f"UTC: {utc_now()}   Assumed fee: {FEE_RATE * 100:.3f}% per leg"
        f"   Max quote age: {MAX_QUOTE_AGE_MS} ms",
        "Connections: " + " | ".join(
            f"{name}: {connection_state[name]}" for name in ("BINANCE", "BYBIT")
        ),
        "",
        "PAIR     EXCHANGE     BID                 ASK                 AGE",
        "-" * 82,
    ]
    for symbol in SYMBOLS:
        for exchange in ("BINANCE", "BYBIT"):
            q = latest.get((exchange, symbol))
            if q:
                age = quote_age_ms(q, now)
                state = "fresh" if age <= MAX_QUOTE_AGE_MS else "STALE"
                lines.append(
                    f"{symbol:<8} {exchange:<10} {q.bid:<19.10g} "
                    f"{q.ask:<19.10g} {age:7.0f} ms {state}"
                )
            else:
                lines.append(f"{symbol:<8} {exchange:<10} waiting for data...")
        b = latest.get(("BINANCE", symbol))
        y = latest.get(("BYBIT", symbol))
        if b and y:
            by = comparison(symbol, b, y, now)  # buy Binance, sell Bybit
            yb = comparison(symbol, y, b, now)  # buy Bybit, sell Binance
            if by:
                g1, n1, _, _ = by
                g2, n2, _, _ = yb if yb else (None, None, None, None)
                best = max(n1, n2) if n2 is not None else n1
                lines.extend([
                    f"  BUY BINANCE -> SELL BYBIT: gross {g1:+.4f}%"
                    f" | estimated net {n1:+.4f}%",
                    (f"  BUY BYBIT   -> SELL BINANCE: gross {g2:+.4f}%"
                     f" | estimated net {n2:+.4f}%") if yb
                    else "  Reverse direction: waiting for synchronized quotes",
                    f"  Better displayed estimate: {best:+.4f}% (not an executable signal)",
                ])
                # Persist both synchronized comparisons.
                save_opportunity(db, symbol, "BINANCE", "BYBIT",
                                 b.ask, y.bid, g1, n1,
                                 quote_age_ms(b, now), quote_age_ms(y, now))
                if yb:
                    save_opportunity(db, symbol, "BYBIT", "BINANCE",
                                     y.ask, b.bid, g2, n2,
                                     quote_age_ms(y, now), quote_age_ms(b, now))
            else:
                lines.append("  Comparison: waiting (stale or time-skewed quotes)")
        lines.append("")
    lines.extend([
        "-" * 82,
        f"SQLite: {os.path.abspath(DB_PATH)}",
        "Ctrl+C to stop. No account access, API keys, or order execution.",
    ])
    print("\033[H\033[2J" + "\n".join(lines), end="", flush=True)
    db.commit()


async def display_loop(db: sqlite3.Connection) -> None:
    while True:
        dashboard(db)
        await asyncio.sleep(DISPLAY_INTERVAL)


async def main() -> None:
    db = init_db()
    tasks = [
        asyncio.create_task(run_binance(db), name="binance"),
        asyncio.create_task(run_bybit(db), name="bybit"),
        asyncio.create_task(display_loop(db), name="dashboard"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        db.commit()
        db.close()
        print("\nStopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
