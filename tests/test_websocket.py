"""Isolated WebSocket server/quotes for tests; never a live-mode fallback."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
import inspect
import io
import json
import http
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import pandas as pd

from yfinance.pricing_pb2 import PricingData
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.frames import Opcode
from data.processor import DataProcessor


NOW = datetime(2026, 7, 24, 14, 1, tzinfo=timezone.utc)


def wire(symbol="^GSPC", price=7300.25, stamp=NOW):
    quote = PricingData(id=symbol, price=price, time=int(stamp.timestamp() * 1000))
    return json.dumps({"type": "pricing", "message": base64.b64encode(quote.SerializeToString()).decode()})


class QuoteTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("data.streamer"), "WebSocket quote module is missing")
        from data import streamer
        return streamer

    def test_actual_protobuf_frame_preserves_price_and_millisecond_source_time(self):
        api = self.api()
        quote = api.decode_quote(wire())
        self.assertEqual(quote.symbol, "^GSPC")
        self.assertEqual(quote.price, 7300.25)
        self.assertEqual(quote.source_time, NOW)
        self.assertIsNone(api.decode_quote('{"type":"heartbeat"}'))

    def test_wrong_symbol_out_of_order_and_future_do_not_replace_latest(self):
        api = self.api()
        feed = api.QuoteFeed("^GSPC")
        self.assertTrue(feed.accept(wire(), NOW))
        self.assertFalse(feed.accept(wire(symbol="TSLA"), NOW))
        self.assertFalse(feed.accept(wire(stamp=NOW - timedelta(seconds=1)), NOW))
        with self.assertRaises(ValueError):
            feed.accept(wire(stamp=NOW + timedelta(seconds=6)), NOW)
        self.assertEqual(feed.quote.source_time, NOW)
        self.assertEqual(feed.quote.price, 7300.25)


    def test_bad_frames_prices_and_missing_timestamps_are_rejected(self):
        api = self.api()
        invalid = ["not json", "[]", '{"message":"%%%"}', wire(price=float("nan")),
                   wire(price=float("inf")), wire(price=0), wire(price=-1),
                   wire(stamp=datetime(1970, 1, 1, tzinfo=timezone.utc))]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                api.decode_quote(raw)

    def test_connection_and_quote_freshness_are_independent(self):
        api = self.api()
        feed = api.QuoteFeed("^GSPC")
        feed.connected = True
        self.assertEqual(feed.status(NOW), "WAITING")
        feed.accept(wire(), NOW)
        self.assertEqual(feed.status(NOW + timedelta(seconds=30)), "FRESH")
        self.assertEqual(feed.status(NOW + timedelta(seconds=31)), "STALE")
        feed.connected = False
        self.assertEqual(feed.status(NOW), "DISCONNECTED")
        self.assertEqual(feed.quote.price, 7300.25)


async def wait_until(predicate, timeout=2):
    async def waiting():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(waiting(), timeout)


def history_fixture():
    root = Path(__file__).resolve().parents[1]
    df = DataProcessor().load_csv(root / "data/raw/GSPC_20260726_190400.csv").tail(600).copy()
    df["Datetime"] += pd.Timestamp(NOW - timedelta(minutes=1)) - df.iloc[-1]["Datetime"]
    return df.reset_index(drop=True)


class DisplayTests(unittest.TestCase):
    def test_quote_updates_are_distinct_from_candle_close_and_suspend_when_stale(self):
        from live import LiveMonitor, render_screen
        from data.streamer import QuoteFeed
        self.assertIn("quote_feed", inspect.signature(render_screen).parameters, "Quote display not connected")
        monitor = LiveMonitor(history_fixture)
        monitor.step(NOW)
        feed = QuoteFeed("^GSPC")
        feed.connected = True
        feed.accept(wire(), NOW)
        screen = render_screen(monitor, NOW, rows=0, quote_feed=feed)
        self.assertIn("السعر اللحظي من المصدر: 7300.25", screen)
        self.assertIn("إغلاق آخر شمعة للتحليل (ليس السعر اللحظي): 7412.88", screen)
        self.assertIn("تحديث السعر: فور وصول رسالة WebSocket", screen)
        self.assertIn("جلب الشموع للتحليل: كل 60 ثانية", screen)
        self.assertNotIn("الفحص التالي بعد", screen)
        self.assertIn("التوصية الحالية: انتظار", screen)
        stale = render_screen(monitor, NOW + timedelta(seconds=31), rows=0, quote_feed=feed)
        self.assertIn("التوصية الحالية: معلّقة", stale)
        self.assertIn("متأخر", stale)
        feed.connected = False
        disconnected = render_screen(monitor, NOW, rows=0, quote_feed=feed)
        self.assertIn("التوصية الحالية: معلّقة", disconnected)

    def test_live_defaults_to_websocket_and_poll_is_explicit(self):
        from main import build_parser
        args = build_parser().parse_args(["--live"])
        self.assertTrue(hasattr(args, "transport"), "WebSocket entry point is missing")
        self.assertEqual(args.transport, "websocket")
        self.assertEqual(build_parser().parse_args(["--live", "--transport", "poll"]).transport, "poll")


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_prices_and_cancel_keep_working_while_history_request_is_blocked(self):
        self.assertIsNotNone(importlib.util.find_spec("websocket_live"), "Async screen runner is missing")
        from websocket_live import run_websocket_async
        from main import build_parser
        args = build_parser().parse_args(["--live", "--rows", "0"])
        release = threading.Event()
        second = asyncio.Event()
        out = io.StringIO()
        raw = history_fixture().set_index("Datetime")[["Open", "High", "Low", "Close", "Volume"]]
        def network(*unused, **kwargs):
            release.wait(timeout=5)
            return raw
        async def server(ws):
            await ws.recv()
            await ws.send(wire(price=7300.25))
            await second.wait()
            await ws.send(wire(price=7301.25))
            await ws.wait_closed()
        with patch("data.downloader.yf.download", side_effect=network):
            async with serve(server, "127.0.0.1", 0) as listener:
                url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
                task = asyncio.create_task(run_websocket_async(args, stream=out, clock=lambda: NOW, ws_url=url))
                try:
                    await wait_until(lambda: "7300.25" in out.getvalue(), timeout=1)
                    self.assertIn("جارٍ جلب البيانات", out.getvalue())
                    second.set()
                    await wait_until(lambda: "7301.25" in out.getvalue(), timeout=1)
                    task.cancel()
                    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=0.5)
                finally:
                    second.set()
                    release.set()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def api(self):
        from data import streamer
        self.assertTrue(hasattr(streamer, "YahooPriceStream"), "Open WebSocket transport is missing")
        return streamer

    async def test_open_connection_keeps_receiving_with_pong_and_subscription_heartbeat(self):
        api = self.api()
        subscriptions = []
        close_codes = []
        async def server(ws):
            try:
                async for raw in ws:
                    subscriptions.append(json.loads(raw))
                    if len(subscriptions) == 1:
                        await ws.send(wire())
            except ConnectionClosed:
                pass
            finally:
                close_codes.append(ws.close_code)
        async with serve(server, "127.0.0.1", 0) as listener:
            url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            feed = api.QuoteFeed("^GSPC")
            client = api.YahooPriceStream("^GSPC", url=url, clock=lambda: NOW,
                                        ping_interval=0.02, ping_timeout=0.1,
                                        subscription_interval=0.02)
            task = asyncio.create_task(client.run(feed, lambda: None))
            try:
                await wait_until(lambda: feed.quote is not None and feed.last_pong_at is not None and len(subscriptions) >= 2)
                self.assertTrue(feed.connected)
                self.assertEqual(feed.quote.price, 7300.25)
                self.assertEqual(feed.last_pong_at, NOW)
                self.assertGreaterEqual(feed.latency_ms, 0)
                self.assertTrue(all(message == {"subscribe": ["^GSPC"]} for message in subscriptions))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertFalse(feed.connected)
            await wait_until(lambda: bool(close_codes))
            self.assertEqual(close_codes, [1000])

    async def test_normal_close_reconnects_and_resubscribes_then_receives_new_price(self):
        api = self.api()
        subscriptions = []
        second_ready, send_second = asyncio.Event(), asyncio.Event()
        async def server(ws):
            raw = await ws.recv()
            subscriptions.append(json.loads(raw))
            if len(subscriptions) == 2:
                second_ready.set()
                await send_second.wait()
            await ws.send(wire(price=7300.25 + len(subscriptions)))
            if len(subscriptions) == 1:
                await ws.close(code=1000)
            else:
                await ws.wait_closed()
        async with serve(server, "127.0.0.1", 0) as listener:
            url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            feed = api.QuoteFeed("^GSPC")
            task = asyncio.create_task(api.YahooPriceStream(
                "^GSPC", url=url, clock=lambda: NOW, retry_base=0.01,
            ).run(feed, lambda: None))
            try:
                await wait_until(lambda: second_ready.is_set() and feed.connected)
                self.assertEqual(feed.status(NOW), "WAITING")
                send_second.set()
                await wait_until(lambda: feed.quote is not None and feed.quote.price == 7302.25)
                self.assertTrue(feed.connected)
                self.assertGreaterEqual(feed.reconnections, 1)
                self.assertEqual(subscriptions[:2], [{"subscribe": ["^GSPC"]}] * 2)
            finally:
                send_second.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_failed_handshakes_back_off_after_an_earlier_pong(self):
        api = self.api()
        feed = api.QuoteFeed("^GSPC")
        handshakes = 0
        delays = []
        original_sleep = asyncio.sleep
        async def record_sleep(seconds):
            if seconds in [0.02, 0.04, 0.08]:
                delays.append(seconds)
            await original_sleep(seconds)
        def process_request(ws, request):
            nonlocal handshakes
            handshakes += 1
            if handshakes > 1:
                return ws.respond(http.HTTPStatus.SERVICE_UNAVAILABLE, "test outage")
        async def server(ws):
            await ws.recv()
            await ws.send(wire())
            await wait_until(lambda: feed.last_pong_at is not None)
            await ws.close(code=1000)
        async with serve(server, "127.0.0.1", 0, process_request=process_request) as listener:
            url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            with patch("data.streamer.asyncio.sleep", side_effect=record_sleep):
                task = asyncio.create_task(api.YahooPriceStream(
                    "^GSPC", url=url, clock=lambda: NOW, ping_interval=0.005,
                    retry_base=0.02, retry_max=0.08,
                ).run(feed, lambda: None))
                try:
                    await wait_until(lambda: len(delays) >= 3)
                    self.assertEqual(delays[:3], [0.02, 0.04, 0.08])
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_missing_pong_suspends_before_a_blocked_close_handshake(self):
        api = self.api()
        closing = asyncio.Event()
        feed = api.QuoteFeed("^GSPC")
        errors = []
        def notify():
            if feed.error:
                errors.append(feed.error)
        async def broken_server(ws):
            receive_frame = ws.protocol.recv_frame
            def ignore_control(frame):
                if frame.opcode is Opcode.PING:
                    return
                if frame.opcode is Opcode.CLOSE:
                    closing.set()
                    return
                receive_frame(frame)
            # An isolated faulty peer ignores control frames on a real socket.
            ws.protocol.recv_frame = ignore_control
            await ws.recv()
            await ws.send(wire())
            await ws.wait_closed()
        async with serve(broken_server, "127.0.0.1", 0) as listener:
            url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            task = asyncio.create_task(api.YahooPriceStream(
                "^GSPC", url=url, clock=lambda: NOW, ping_interval=0.01,
                ping_timeout=0.02, retry_base=0.2,
            ).run(feed, notify))
            try:
                await wait_until(closing.is_set)
                self.assertIsNotNone(feed.quote)
                self.assertFalse(feed.connected, "Failed socket remains actionable while close waits")
                self.assertEqual(feed.status(NOW), "DISCONNECTED")
                await wait_until(lambda: any("Pong" in error for error in errors), timeout=3)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_malformed_message_does_not_destroy_good_quote_or_connection(self):
        api = self.api()
        async def server(ws):
            await ws.recv()
            await ws.send(wire())
            await ws.send('{"message":"%%%"}')
            await ws.send(wire(price=7301.25))
            await ws.wait_closed()
        async with serve(server, "127.0.0.1", 0) as listener:
            url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
            feed = api.QuoteFeed("^GSPC")
            task = asyncio.create_task(api.YahooPriceStream("^GSPC", url=url, clock=lambda: NOW).run(feed, lambda: None))
            try:
                await wait_until(lambda: feed.quote is not None and feed.quote.price == 7301.25)
                self.assertEqual(feed.invalid_messages, 1)
                self.assertTrue(feed.connected)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)



if __name__ == "__main__":
    unittest.main()
