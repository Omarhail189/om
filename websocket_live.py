"""Event-driven quotes and independently refreshed history in one terminal."""

import asyncio
from datetime import datetime, timezone
import os
import queue
import sys
import threading

from data.downloader import YahooDownloader
from data.streamer import QuoteFeed, YahooPriceStream, YAHOO_STREAM_URL
from live import LiveMonitor, render_screen


async def run_websocket_async(args, *, stream=None, clock=None, ws_url=YAHOO_STREAM_URL):
    stream = stream or sys.stdout
    clock = clock or (lambda: datetime.now(timezone.utc))
    symbol = "^GSPC" if args.symbol in {"GSPC", "^GSPC"} else "TSLA"
    quote_feed = QuoteFeed(symbol)
    changed = asyncio.Event()
    results = queue.Queue(maxsize=1)
    downloader = YahooDownloader()

    def take_history():
        value = results.get_nowait()
        if isinstance(value, BaseException):
            raise value
        return value

    monitor = LiveMonitor(take_history, refresh=args.refresh, symbol=symbol)
    tty = stream.isatty() and os.environ.get("TERM") != "dumb"
    last_status = None

    def show():
        nonlocal last_status
        now = clock()
        if tty:
            stream.write("\033[2J\033[H")
        stream.write(render_screen(monitor, now, rows=args.rows, quote_feed=quote_feed) + "\n")
        stream.flush()
        last_status = (monitor.status(now), quote_feed.status(now))

    async def refresh_history():
        while True:
            monitor.updating = True
            changed.set()

            def request():
                try:
                    value = downloader.fetch(symbol, period=args.period, interval="1m")
                except BaseException as exc:
                    value = exc
                results.put(value)

            # Only the project-owned HTTP request runs here. A blocked request
            # cannot delay socket heartbeat, quote delivery, or program exit.
            threading.Thread(target=request, name="om-history", daemon=True).start()
            while results.empty():
                await asyncio.sleep(0.05)
            monitor.step(clock())
            monitor.updating = False
            changed.set()
            await asyncio.sleep(monitor.next_delay)

    tasks = [
        asyncio.create_task(YahooPriceStream(symbol, url=ws_url, clock=clock).run(quote_feed, changed.set)),
        asyncio.create_task(refresh_history()),
    ]
    try:
        show()
        while True:
            try:
                await asyncio.wait_for(changed.wait(), timeout=1)
                changed.clear()
                redraw = True
            except asyncio.TimeoutError:
                now = clock()
                redraw = tty or last_status != (monitor.status(now), quote_feed.status(now))
            for task in tasks:
                if task.done():
                    task.result()
                    raise RuntimeError("توقفت إحدى مهام شاشة WebSocket.")
            if redraw:
                show()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        quote_feed.connected = False
        quote_feed.connecting = False
        monitor.updating = False
        show()


def run_websocket(args):
    asyncio.run(run_websocket_async(args))
