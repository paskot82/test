#!/usr/bin/env python3
"""
Read-only public market-data monitor for Binance Spot and Bybit Spot.
No API keys, account access, orders, deposits, or withdrawals.
"""

import asyncio
import json
import signal
import time
from datetime import datetime, timezone

import websockets

SYMBOLS = ("BTCUSDT", "ETHUSDT", "ETHBTC")

BINANCE_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(
    f"{symbol.lower()}@bookTicker" for symbol in SYMBOLS
)
BYBIT_URL = "wss://stream.bybit.com/v5/public/spot"

latest = {
    "BINANCE": {},
    "BYBIT": {},
}
stop_event = asyncio.Event()


def utc_now():
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def print_quote(exchange, symbol, bid, bid_size, ask, ask_size):
    latest[exchange][symbol] = {
        "bid": bid,
        "bid_size": bid_size,
        "ask": ask,
        "ask_size": ask_size,
        "received_at": time.time(),
    }
    print(
        f"{utc_now()} UTC | {exchange:7} | {symbol:8} "
        f"| bid {bid:>16} ({bid_size}) "
        f"| ask {ask:>16} ({ask_size})",
        flush=True,
    )


async def run_binance():
    delay = 1
    while not stop_event.is_set():
        try:
            print(f"[{utc_now()}] Connecting Binance public market stream...", flush=True)
            async with websockets.connect(
                BINANCE_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=2**20,
            ) as ws:
                print(f"[{utc_now()}] Binance connected.", flush=True)
                delay = 1
                async for raw in ws:
                    msg = json.loads(raw)
                    data = msg.get("data", {})
                    symbol = data.get("s")
                    if symbol in SYMBOLS:
                        print_quote(
                            "BINANCE",
                            symbol,
                            data.get("b", "0"),
                            data.get("B", "0"),
                            data.get("a", "0"),
                            data.get("A", "0"),
                        )
                    if stop_event.is_set():
                        break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[{utc_now()}] Binance connection error: {exc}", flush=True)

        if not stop_event.is_set():
            print(f"Binance reconnecting in {delay}s...", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def bybit_ping(ws):
    while True:
        await asyncio.sleep(20)
        await ws.send(json.dumps({"op": "ping"}))


async def run_bybit():
    delay = 1

    while not stop_event.is_set():
        ping_task = None

        try:
            print(
                f"[{utc_now()}] Connecting Bybit public market stream...",
                flush=True
            )

            async with websockets.connect(
                BYBIT_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
                max_size=2**20,
            ) as ws:

                subscription = {
                    "op": "subscribe",
                    "args": [
                        f"orderbook.1.{symbol}"
                        for symbol in SYMBOLS
                    ],
                }

                await ws.send(json.dumps(subscription))

                ping_task = asyncio.create_task(bybit_ping(ws))

                print(
                    f"[{utc_now()}] Bybit connected; orderbook subscription sent.",
                    flush=True
                )

                delay = 1

                async for raw in ws:
                    msg = json.loads(raw)

                    # Ответ на подписку
                    if msg.get("op") == "subscribe":
                        if msg.get("success"):
                            print(
                                f"[{utc_now()}] Bybit subscription successful.",
                                flush=True
                            )
                        else:
                            print(
                                f"Bybit subscription error: {msg}",
                                flush=True
                            )
                        continue

                    topic = msg.get("topic", "")

                    if not topic.startswith("orderbook.1."):
                        continue

                    data = msg.get("data", {})

                    symbol = data.get("s")

                    if symbol not in SYMBOLS:
                        continue

                    bids = data.get("b", [])
                    asks = data.get("a", [])

                    if not bids or not asks:
                        continue

                    bid = bids[0]
                    ask = asks[0]

                    print_quote(
                        "BYBIT",
                        symbol,
                        bid[0],
                        bid[1],
                        ask[0],
                        ask[1],
                    )

                    if stop_event.is_set():
                        break

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                f"[{utc_now()}] Bybit connection error: {exc}",
                flush=True
            )

        finally:
            if ping_task:
                ping_task.cancel()

                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

        if not stop_event.is_set():
            print(
                f"Bybit reconnecting in {delay}s...",
                flush=True
            )

            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
async def main():
    loop = asyncio.get_running_loop()

    def request_stop():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            # Some Android/Windows event loops do not support add_signal_handler.
            pass

    print("=" * 88)
    print("READ-ONLY CRYPTO MARKET MONITOR | Binance Spot + Bybit Spot")
    print("Public market data only. No account access and no trading.")
    print(f"Pairs: {', '.join(SYMBOLS)}")
    print("Press Ctrl+C to stop.")
    print("=" * 88, flush=True)

    tasks = [
        asyncio.create_task(run_binance()),
        asyncio.create_task(run_bybit()),
    ]

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print(f"\n[{utc_now()}] Stopped.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
