"""Yahoo quote protocol and connection state, separate from candle indicators."""

import base64
import binascii
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import time

from google.protobuf.message import DecodeError
from yfinance.pricing_pb2 import PricingData
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException


YAHOO_STREAM_URL = "wss://streamer.finance.yahoo.com/?version=2"


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    source_time: datetime


def decode_quote(raw):
    """Decode the version=2 JSON/base64/PricingData wire protocol."""
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict):
            raise ValueError("رسالة WebSocket ليست كائن JSON.")
        if "message" not in envelope:
            return None
        encoded = envelope["message"]
        if not isinstance(encoded, str):
            raise ValueError("بيانات السعر ليست base64 نصية.")
        message = PricingData()
        message.ParseFromString(base64.b64decode(encoded, validate=True))
        if not message.id or not math.isfinite(message.price) or message.price <= 0 or message.time <= 0:
            raise ValueError("رسالة السعر ينقصها رمز أو سعر موجب محدود أو توقيت صالح.")
        stamp = datetime.fromtimestamp(message.time / 1000, tz=timezone.utc)
        return Quote(message.id, float(message.price), stamp)
    except (TypeError, binascii.Error, DecodeError, OverflowError, OSError) as exc:
        raise ValueError("تعذر فك رسالة سعر WebSocket.") from exc


class QuoteFeed:
    def __init__(self, symbol):
        self.symbol = symbol
        self.quote = None
        self.received_at = None
        self.connected = False
        self.connecting = True
        self.error = None
        self.last_pong_at = None
        self.latency_ms = None
        self.reconnections = 0
        self.invalid_messages = 0
        self.has_session_quote = False

    def accept(self, raw, now):
        quote = decode_quote(raw)
        if quote is None or quote.symbol != self.symbol:
            return False
        if now.tzinfo is None:
            raise ValueError("ساعة الاستقبال يجب أن تتضمن منطقة زمنية.")
        if (quote.source_time - now).total_seconds() > 5:
            raise ValueError("توقيت السعر متقدم عن ساعة الجهاز بأكثر من 5 ثوانٍ.")
        if self.quote and quote.source_time < self.quote.source_time:
            return False
        self.quote = quote
        self.received_at = now
        self.has_session_quote = True
        return True

    def status(self, now):
        if not self.connected:
            return "DISCONNECTED"
        if self.quote is None or not self.has_session_quote:
            return "WAITING"
        age = (now - self.quote.source_time).total_seconds()
        return "FRESH" if -5 <= age <= 30 else "STALE"


class YahooPriceStream:
    """Persistent connection with verified Pong, resubscription and reconnect."""

    def __init__(self, symbol, *, url=YAHOO_STREAM_URL, clock=None,
                 ping_interval=20, ping_timeout=20, subscription_interval=15,
                 retry_base=1, retry_max=60):
        self.symbol = symbol
        self.url = url
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.subscription_interval = subscription_interval
        self.retry_base = retry_base
        self.retry_max = retry_max

    async def _heartbeat(self, ws, feed, notify):
        while True:
            await asyncio.sleep(self.ping_interval)
            started = time.monotonic()
            pong = await ws.ping()
            try:
                await asyncio.wait_for(pong, timeout=self.ping_timeout)
            except asyncio.TimeoutError as exc:
                raise ConnectionError(f"لم تصل نبضة Pong خلال {self.ping_timeout} ثانية.") from exc
            feed.last_pong_at = self.clock()
            feed.latency_ms = (time.monotonic() - started) * 1000
            notify()

    async def _subscribe_heartbeat(self, ws):
        while True:
            await asyncio.sleep(self.subscription_interval)
            await ws.send(json.dumps({"subscribe": [self.symbol]}))

    async def _receive(self, ws, feed, notify):
        async for raw in ws:
            try:
                changed = feed.accept(raw, self.clock())
            except ValueError:
                feed.invalid_messages += 1
                changed = True
            if changed:
                notify()

    async def _session(self, ws, feed, notify):
        await ws.send(json.dumps({"subscribe": [self.symbol]}))
        tasks = [
            asyncio.create_task(self._receive(ws, feed, notify)),
            asyncio.create_task(self._heartbeat(ws, feed, notify)),
            asyncio.create_task(self._subscribe_heartbeat(ws)),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            raise ConnectionError("أغلق المصدر اتصال WebSocket.")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, feed, notify):
        failures = 0
        while True:
            session_stable = False
            feed.connecting = True
            notify()
            try:
                # Our heartbeat awaits Pong explicitly so its actual time is visible.
                async with connect(self.url, ping_interval=None, open_timeout=15,
                                   close_timeout=2, max_size=65536, max_queue=16) as ws:
                    feed.connected = True
                    feed.connecting = False
                    feed.has_session_quote = False
                    feed.error = None
                    feed.last_pong_at = None
                    feed.latency_ms = None
                    notify()
                    try:
                        await self._session(ws, feed, notify)
                    finally:
                        session_stable = feed.has_session_quote or feed.last_pong_at is not None
                        feed.connected = False
                        feed.has_session_quote = False
                        notify()
                        await ws.close(code=1000)
            except (OSError, TimeoutError, WebSocketException) as exc:
                feed.error = str(exc) or type(exc).__name__
                failures = 1 if session_stable else failures + 1
                feed.reconnections += 1
            finally:
                feed.connected = False
                feed.connecting = False
                feed.has_session_quote = False
                notify()
            await asyncio.sleep(min(self.retry_base * 2 ** min(failures - 1, 10), self.retry_max))
