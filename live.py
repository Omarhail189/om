"""Continuous terminal display using closed Yahoo minute candles."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd

from data.indicators import IndicatorEngine
from data.processor import DataProcessor
from strategies.opening import OpeningStrategy


NEW_YORK = ZoneInfo("America/New_York")
SIGNAL_NAMES = {
    "STRONG BUY": "شراء قوي", "BUY": "شراء", "WATCH": "مراقبة",
    "HOLD": "انتظار", "IGNORE": "لا دخول",
}
REASONS = {
    "Breakout": "اختراق قمة آخر 5 شموع", "EMA9>EMA20": "EMA9 أعلى من EMA20",
    "EMA20>EMA50": "EMA20 أعلى من EMA50", "Above EMA200": "السعر أعلى من EMA200",
    "MACD Bullish": "زخم MACD صاعد", "RSI OK": "RSI ضمن النطاق",
    "High Volume": "حجم تداول مرتفع", "Above VWAP": "السعر أعلى من VWAP",
    "ATR Strong": "ATR أعلى من متوسطه", "Cooldown Active": "انتظار بعد إشارة شراء سابقة",
    "Outside Trading Session": "خارج أوقات الاستراتيجية",
}
STATUS_NAMES = {
    "STARTING": "جارٍ الاتصال بالمصدر…",
    "UPDATING": "جارٍ جلب البيانات — التوصية معلّقة حتى انتهاء الفحص",
    "LIVE": "بيانات حديثة — تحليل آخر شمعة مغلقة",
    "WAITING": "بانتظار الجلسة — خارج الوقت المعتاد 09:30–16:00 نيويورك",
    "STALE": "بيانات متأخرة — التوصية الحالية معلّقة",
    "ERROR": "تعذر تحديث المصدر — التوصية الحالية معلّقة",
    "WARMUP": "مؤشرات آخر شمعة غير مكتملة — التوصية الحالية معلّقة",
}


@dataclass
class LiveSnapshot:
    latest_time: pd.Timestamp
    latest_price: float
    signals: pd.DataFrame
    complete_latest: bool


def utc_timestamp(now):
    stamp = pd.Timestamp(now)
    if stamp.tzinfo is None:
        raise ValueError("ساعة التشغيل يجب أن تتضمن المنطقة الزمنية.")
    return stamp.tz_convert("UTC")


def analyze_snapshot(df, now):
    """Discard open candles before indicators so they cannot affect a signal."""
    now = utc_timestamp(now)
    DataProcessor().validate(df)
    closed = df.loc[df["Datetime"] + pd.Timedelta(minutes=1) <= now].copy()
    if closed.empty:
        raise ValueError("لم تصل شموع دقيقة مغلقة يمكن تحليلها؛ تحقق من توقيت الجهاز والمصدر.")
    signals = OpeningStrategy().generate(IndicatorEngine().add_indicators(closed))
    latest = closed.iloc[-1]
    return LiveSnapshot(
        latest_time=latest["Datetime"], latest_price=float(latest["Close"]),
        signals=signals, complete_latest=signals.iloc[-1]["Datetime"] == latest["Datetime"],
    )


class LiveMonitor:
    def __init__(self, fetch, refresh=60, symbol="^GSPC"):
        self.fetch = fetch
        self.refresh = refresh
        self.symbol = symbol
        self.snapshot = None
        self.error = None
        self.checked_at = None
        self.next_delay = refresh
        self.failures = 0
        self.updating = False

    def step(self, now):
        self.checked_at = utc_timestamp(now)
        try:
            df = self.fetch()
            source_symbol = df.attrs.get("symbol")
            if source_symbol and source_symbol.lstrip("^") != self.symbol.lstrip("^"):
                raise ValueError(f"رمز المصدر {source_symbol} لا يطابق {self.symbol}.")
            snapshot = analyze_snapshot(df, now)
            if self.snapshot and snapshot.latest_time < self.snapshot.latest_time:
                raise ValueError("المصدر أعاد شموعًا أقدم من آخر تحديث مقبول.")
            self.snapshot = snapshot
            self.error = None
            self.failures = 0
            self.next_delay = self.refresh
        except (OSError, ValueError, RuntimeError) as exc:
            self.error = str(exc)
            self.failures += 1
            self.next_delay = min(self.refresh * 2 ** min(self.failures - 1, 10), 900)

    def status(self, now):
        if self.updating:
            return "UPDATING"
        if self.error:
            return "ERROR"
        if self.snapshot is None:
            return "STARTING"
        stamp = utc_timestamp(now)
        local = stamp.tz_convert(NEW_YORK)
        minutes = local.hour * 60 + local.minute
        if local.weekday() >= 5 or not 570 <= minutes < 960:
            return "WAITING"
        age = (stamp - self.snapshot.latest_time - pd.Timedelta(minutes=1)).total_seconds()
        if age < 0 or age > 180:
            return "STALE"
        if not self.snapshot.complete_latest:
            return "WARMUP"
        return "LIVE"

    def current(self, now):
        if self.status(now) == "LIVE":
            return self.snapshot.signals.iloc[-1]
        return None


def translated_reasons(text):
    return "؛ ".join(REASONS.get(part, part) for part in str(text).split(", ") if part) or "لا شروط متحققة"


def safe_text(text):
    # Network error messages must not inject terminal escape/control sequences.
    return " ".join("".join(char for char in str(text) if char.isprintable()).split())


def render_screen(monitor, now, rows=10, remaining=None, quote_feed=None):
    now = utc_timestamp(now)
    local = now.tz_convert(NEW_YORK)
    status = monitor.status(now)
    lines = [
        f"شاشة توصيات om | {monitor.symbol} | المصدر: Yahoo | "
        + ("سعر WebSocket وتحليل شموع دقيقة مغلقة" if quote_feed is not None else "شموع دقيقة مغلقة"),
        f"وقت العرض: {local:%Y-%m-%d %H:%M:%S %Z} | الحالة: {STATUS_NAMES[status]}",
    ]
    if quote_feed is not None:
        quote_status = quote_feed.status(now)
        connection = "متصل" if quote_feed.connected else ("جارٍ الاتصال" if quote_feed.connecting else "منقطع")
        lines.append(f"اتصال WebSocket: {connection} | Ping/Pong كل 20 ثانية | تجديد الاشتراك كل 15 ثانية")
        if quote_feed.last_pong_at is not None:
            pong_time = quote_feed.last_pong_at.astimezone(NEW_YORK)
            lines.append(f"آخر Pong: {pong_time:%H:%M:%S %Z} | زمن الرد: {quote_feed.latency_ms:.0f} ms")
        if quote_feed.error:
            lines.append(f"خطأ WebSocket: {safe_text(quote_feed.error)} | إعادة اتصال تلقائية")
        if quote_feed.quote is None:
            lines.append(f"السعر اللحظي: غير متاح؛ بانتظار أول سعر WebSocket للرمز {monitor.symbol} من Yahoo.")
        else:
            quote = quote_feed.quote
            age = max(0, int((now - quote.source_time).total_seconds()))
            label = "السعر اللحظي من المصدر" if quote_status == "FRESH" else "آخر سعر WebSocket (متأخر أو سابق)"
            lines.append(f"{label}: {quote.price:.2f} | وقت المصدر: {quote.source_time.astimezone(NEW_YORK):%Y-%m-%d %H:%M:%S %Z} | العمر: {age} ثانية")
        if quote_feed.invalid_messages:
            lines.append(f"رسائل أسعار غير صالحة أُهملت: {quote_feed.invalid_messages}")
    if monitor.checked_at is not None:
        lines.append(f"آخر جلب للشموع: {monitor.checked_at.tz_convert(NEW_YORK):%H:%M:%S %Z}")
    if monitor.error:
        lines.append(f"خطأ المصدر: {safe_text(monitor.error)}")
    snapshot = monitor.snapshot
    if snapshot is not None:
        candle = snapshot.latest_time.tz_convert(NEW_YORK)
        age = max(0, int((now - snapshot.latest_time - pd.Timedelta(minutes=1)).total_seconds()))
        label = "إغلاق آخر شمعة للتحليل (ليس السعر اللحظي)" if quote_feed is not None else "آخر سعر إغلاق من المصدر"
        lines.append(f"{label}: {snapshot.latest_price:.2f}")
        lines.append(f"آخر شمعة مغلقة (بداية): {candle:%Y-%m-%d %H:%M:%S %Z} | عمر نهايتها: {age} ثانية")
        current = monitor.current(now)
        if quote_feed is not None and quote_feed.status(now) != "FRESH":
            current = None
        if current is not None:
            signal = current["SIGNAL"]
            lines.append(f"التوصية الحالية: {SIGNAL_NAMES.get(signal, signal)} ({signal}) | نقاط الشروط: {int(current['SCORE'])}/110")
            lines.append(f"الأسباب: {translated_reasons(current['REASON'])}")
        else:
            lines.append("التوصية الحالية: معلّقة؛ الإشارات أدناه سجل سابق وليست دخولًا حاليًا.")
        if snapshot.complete_latest:
            last = snapshot.signals.iloc[-1]
            lines.append(
                f"المؤشرات عند الشمعة الأخيرة: RSI={last['RSI']:.1f} | RVOL={last['RVOL']:.2f} | "
                f"ATR={last['ATR']:.2f} | VWAP={last['VWAP']:.2f}"
            )
        if rows:
            lines.extend(["", "آخر الإشارات المحسوبة — الوقت بنيويورك، السعر، النقاط، القرار:"])
            for _, row in snapshot.signals.tail(rows).iterrows():
                stamp = row["Datetime"].tz_convert(NEW_YORK)
                signal = row["SIGNAL"]
                lines.append(f"{stamp:%m-%d %H:%M} | {row['Close']:.2f} | {int(row['SCORE']):3d} | {SIGNAL_NAMES.get(signal, signal)} ({signal})")
    else:
        lines.append("لا توجد شموع مقبولة لحساب التوصية بعد؛ لا تُستخدم الملفات التاريخية بدل المصدر.")
    wait = monitor.next_delay if remaining is None else remaining
    if quote_feed is not None:
        lines.extend(["", "تحديث السعر: فور وصول رسالة WebSocket؛ لا ينتظر جلب الشموع."])
        timing = "جارٍ جلب البيانات — الشموع للتحليل فقط…" if monitor.updating else f"جلب الشموع للتحليل: كل {monitor.refresh} ثانية | انتظار الجلب التالي/إعادة المحاولة: {wait} ثانية"
    else:
        timing = "جارٍ جلب البيانات من Yahoo…" if monitor.updating else f"الفحص التالي بعد {wait} ثانية"
    lines.extend([
        "", f"{timing} | للإيقاف: Ctrl+C",
        ("السعر عبر WebSocket والشموع تُحدّث مستقلًا؛ قد يتأخر المصدر." if quote_feed is not None else "تحديث دوري من Yahoo؛ قد يتأخر المصدر.")
        + " النقاط ليست نسبة نجاح. لا تنفيذ صفقات.",
    ])
    return "\n".join(lines)


def run_live(args, *, clock=None, sleep=None, stream=None):
    from data.downloader import YahooDownloader

    clock = clock or (lambda: datetime.now(timezone.utc))
    sleep = sleep or time.sleep
    stream = stream or sys.stdout
    symbol = "^GSPC" if args.symbol in {"GSPC", "^GSPC"} else "TSLA"
    downloader = YahooDownloader()
    monitor = LiveMonitor(
        lambda: downloader.fetch(symbol, period=args.period, interval="1m"),
        refresh=args.refresh, symbol=symbol,
    )
    tty = stream.isatty() and os.environ.get("TERM") != "dumb"

    displayed_status = None

    def show(remaining=None):
        nonlocal displayed_status
        stamp = clock()
        if tty:
            stream.write("\033[2J\033[H")
        stream.write(render_screen(monitor, stamp, rows=args.rows, remaining=remaining) + "\n")
        stream.flush()
        displayed_status = monitor.status(stamp)

    show()
    while True:
        # Never leave an actionable frame visible while a blocking request runs.
        monitor.updating = True
        show()
        monitor.step(clock())
        monitor.updating = False
        deadline = time.monotonic() + monitor.next_delay
        show()
        # Screen validity and clock are independent of the source polling period.
        while time.monotonic() < deadline:
            sleep(min(1, max(0, deadline - time.monotonic())))
            if tty or monitor.status(clock()) != displayed_status:
                show(remaining=max(0, math.ceil(deadline - time.monotonic())))
