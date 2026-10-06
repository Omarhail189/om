"""Live fixtures are isolated; user-facing live mode never uses sample prices."""

from datetime import datetime, timedelta, timezone
import importlib.util
import io
import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from data.downloader import YahooDownloader
from data.processor import DataProcessor


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 24, 14, 1, tzinfo=timezone.utc)


def fixture(last="2026-07-24T14:00:00Z"):
    df = DataProcessor().load_csv(ROOT / "data/raw/GSPC_20260726_190400.csv").tail(600).copy()
    df["Datetime"] += pd.Timestamp(last) - df.iloc[-1]["Datetime"]
    return df.reset_index(drop=True)


def yahoo_frame(df):
    return df.set_index("Datetime")[["Open", "High", "Low", "Close", "Volume"]]


class LiveFetchTests(unittest.TestCase):
    def test_live_fetch_normalizes_without_writing_sources(self):
        self.assertTrue(hasattr(YahooDownloader, "fetch"), "Live needs a fetch without file writes")
        with tempfile.TemporaryDirectory() as tmp, patch(
            "data.downloader.yf.download", return_value=yahoo_frame(fixture())
        ):
            downloader = YahooDownloader()
            downloader.raw_dir = Path(tmp)
            result = downloader.fetch("^GSPC", period="5d", interval="1m")
            self.assertEqual(str(result["Datetime"].dt.tz), "UTC")
            self.assertEqual(result.attrs["symbol"], "^GSPC")
            self.assertEqual(len(result), 600)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class LiveAnalysisTests(unittest.TestCase):
    def live(self):
        self.assertIsNotNone(importlib.util.find_spec("live"), "Continuous analysis module is missing")
        import live
        return live

    def test_open_minute_is_excluded_until_it_closes(self):
        live = self.live()
        df = fixture("2026-07-24T14:01:00Z")
        snapshot = live.analyze_snapshot(df, NOW + timedelta(seconds=59))
        self.assertEqual(snapshot.latest_time.isoformat(), "2026-07-24T14:00:00+00:00")
        closed = live.analyze_snapshot(df, NOW + timedelta(minutes=1))
        self.assertEqual(closed.latest_time.isoformat(), "2026-07-24T14:01:00+00:00")

    def test_fresh_signal_is_suspended_when_its_candle_becomes_stale(self):
        live = self.live()
        monitor = live.LiveMonitor(lambda: fixture())
        monitor.step(NOW)
        self.assertEqual(monitor.status(NOW), "LIVE")
        self.assertIsNotNone(monitor.current(NOW))
        self.assertEqual(monitor.status(NOW + timedelta(seconds=180)), "LIVE")
        self.assertEqual(monitor.status(NOW + timedelta(seconds=181)), "STALE")
        self.assertIsNone(monitor.current(NOW + timedelta(seconds=181)))

    def test_before_open_and_weekend_do_not_present_old_buy_as_current(self):
        live = self.live()
        monitor = live.LiveMonitor(lambda: fixture())
        monitor.step(NOW)
        for clock in [datetime(2026, 7, 25, 14, 1, tzinfo=timezone.utc),
                      datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)]:
            self.assertEqual(monitor.status(clock), "WAITING")
            self.assertIsNone(monitor.current(clock))

    def test_invalid_latest_volume_indicators_never_use_earlier_signal(self):
        live = self.live()
        df = fixture()
        df.loc[df.index[-14:], "Volume"] = 0
        monitor = live.LiveMonitor(lambda: df)
        monitor.step(NOW)
        self.assertEqual(monitor.status(NOW), "WARMUP")
        self.assertIsNone(monitor.current(NOW))

    def test_source_failure_suspends_then_new_candle_recovers(self):
        live = self.live()
        responses = iter([fixture(), RuntimeError("HTTP 429"), fixture("2026-07-24T14:01:00Z")])
        def fetch():
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value
        monitor = live.LiveMonitor(fetch)
        monitor.step(NOW)
        accepted = monitor.snapshot.latest_time
        monitor.step(NOW + timedelta(seconds=60))
        self.assertEqual(monitor.status(NOW + timedelta(seconds=60)), "ERROR")
        self.assertIsNone(monitor.current(NOW + timedelta(seconds=60)))
        self.assertEqual(monitor.snapshot.latest_time, accepted)
        self.assertIn("429", monitor.error)
        monitor.step(NOW + timedelta(seconds=120))
        self.assertEqual(monitor.status(NOW + timedelta(seconds=120)), "LIVE")
        self.assertEqual(monitor.snapshot.latest_time.isoformat(), "2026-07-24T14:01:00+00:00")
        self.assertEqual(monitor.next_delay, 60)

    def test_regressed_source_is_rejected_and_never_replaces_latest(self):
        live = self.live()
        responses = iter([fixture(), fixture("2026-07-24T13:59:00Z")])
        monitor = live.LiveMonitor(lambda: next(responses))
        monitor.step(NOW)
        monitor.step(NOW + timedelta(minutes=1))
        self.assertEqual(monitor.status(NOW + timedelta(minutes=1)), "ERROR")
        self.assertEqual(monitor.snapshot.latest_time.isoformat(), "2026-07-24T14:00:00+00:00")

    def test_retry_backoff_is_capped_and_no_local_data_is_used(self):
        live = self.live()
        def fetch():
            raise RuntimeError("connection failed")
        monitor = live.LiveMonitor(fetch)
        delays = []
        for _ in range(7):
            monitor.step(NOW)
            delays.append(monitor.next_delay)
        self.assertEqual(delays, [60, 120, 240, 480, 900, 900, 900])
        self.assertIsNone(monitor.snapshot)


    def test_screen_shows_clock_price_signal_reasons_and_stale_state(self):
        live = self.live()
        monitor = live.LiveMonitor(lambda: fixture())
        monitor.step(NOW)
        screen = live.render_screen(monitor, NOW, rows=3)
        self.assertIn("7412.88", screen)
        self.assertIn("10:00", screen)
        self.assertIn("التوصية", screen)
        self.assertIn("الأسباب", screen)
        self.assertIn("RSI", screen)
        stale = live.render_screen(monitor, NOW + timedelta(minutes=10), rows=3)
        self.assertIn("متأخرة", stale)
        self.assertIn("معلّقة", stale)
        self.assertNotIn("\x1b", stale)

    def test_wrong_symbol_does_not_publish_under_requested_symbol(self):
        live = self.live()
        df = fixture()
        df.attrs["symbol"] = "TSLA"
        monitor = live.LiveMonitor(lambda: df, symbol="^GSPC")
        monitor.step(NOW)
        self.assertEqual(monitor.status(NOW), "ERROR")
        self.assertIsNone(monitor.snapshot)


class LiveCliTests(unittest.TestCase):
    def test_visible_signal_expires_before_a_long_source_refresh(self):
        from main import build_parser
        from live import run_live
        args = build_parser().parse_args(["--live", "--refresh", "900", "--rows", "0"])
        stamp = NOW
        out = io.StringIO()
        def wait(seconds):
            nonlocal stamp
            stamp += timedelta(seconds=seconds)
            if (stamp - NOW).total_seconds() >= 182:
                raise KeyboardInterrupt
        with patch("data.downloader.yf.download", return_value=yahoo_frame(fixture())), patch(
            "live.time.monotonic", side_effect=lambda: (stamp - NOW).total_seconds()
        ), self.assertRaises(KeyboardInterrupt):
            run_live(args, clock=lambda: stamp, sleep=wait, stream=out)
        last = out.getvalue().split("شاشة توصيات om")[-1]
        self.assertIn("متأخرة", last)
        self.assertIn("التوصية الحالية: معلّقة", last)

    def test_visible_signal_is_suspended_while_waiting_for_network(self):
        from main import build_parser
        from live import run_live
        args = build_parser().parse_args(["--live", "--rows", "0"])
        out = io.StringIO()
        stamp = NOW
        calls = 0
        last_during_fetch = None
        def network(*unused, **kwargs):
            nonlocal calls, last_during_fetch
            calls += 1
            if calls == 2:
                last_during_fetch = out.getvalue().split("شاشة توصيات om")[-1]
                raise KeyboardInterrupt
            return yahoo_frame(fixture())
        def wait(seconds):
            nonlocal stamp
            stamp += timedelta(seconds=seconds)
        with patch("data.downloader.yf.download", side_effect=network), patch(
            "live.time.monotonic", side_effect=lambda: (stamp - NOW).total_seconds()
        ), self.assertRaises(KeyboardInterrupt):
            run_live(args, clock=lambda: stamp, sleep=wait, stream=out)
        self.assertIn("التوصية الحالية: معلّقة", last_during_fetch)

    def test_parser_accepts_live_and_rejects_mixed_source_or_wrong_cadence(self):
        from main import build_parser
        try:
            args = build_parser().parse_args(["--live", "--symbol", "TSLA"])
        except SystemExit:
            self.fail("--live entry point is missing")
        self.assertTrue(args.live)
        self.assertEqual(args.refresh, 60)
        bad = [
            ["--live", "--input", "old.csv"], ["--live", "--download"],
            ["--live", "--interval", "5m"], ["--live", "--refresh", "29"],
            ["--live", "--refresh", "0"], ["--refresh", "30"],
        ]
        for argv in bad:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    build_parser().parse_args(argv)
                self.assertEqual(failure.exception.code, 2)

    def test_real_loop_updates_recovers_and_does_not_write_each_refresh(self):
        from main import build_parser
        try:
            args = build_parser().parse_args(["--live", "--rows", "2"])
        except SystemExit:
            self.fail("--live entry point is missing")
        from live import run_live
        stamp = NOW
        waits = []
        frames = iter([
            yahoo_frame(fixture()), RuntimeError("HTTP 429"),
            yahoo_frame(fixture("2026-07-24T14:02:00Z")),
        ])
        def network(symbol, **kwargs):
            self.assertEqual(symbol, "^GSPC")
            self.assertEqual(kwargs["interval"], "1m")
            self.assertEqual(kwargs["period"], "5d")
            item = next(frames)
            if isinstance(item, Exception):
                raise item
            return item
        def wait(seconds):
            nonlocal stamp
            waits.append(seconds)
            stamp += timedelta(seconds=seconds)
            if (stamp - NOW).total_seconds() >= 180:
                raise KeyboardInterrupt
        out = io.StringIO()
        # Patch the downloader's IO target, not its normalization or analysis.
        with tempfile.TemporaryDirectory() as tmp, patch("data.downloader.yf.download", side_effect=network), patch(
            "live.time.monotonic", side_effect=lambda: (stamp - NOW).total_seconds()
        ):
            from data.downloader import YahooDownloader
            original_init = YahooDownloader.__init__
            def init(downloader):
                original_init(downloader)
                downloader.raw_dir = Path(tmp)
            with patch.object(YahooDownloader, "__init__", init), self.assertRaises(KeyboardInterrupt):
                run_live(args, clock=lambda: stamp, sleep=wait, stream=out)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(sum(waits), 180)
        self.assertLessEqual(max(waits), 1)
        text = out.getvalue()
        self.assertIn("10:00:00", text)
        self.assertIn("10:02:00", text)
        self.assertIn("429", text)
        self.assertIn("معلّقة", text)
        self.assertNotIn("\x1b", text)
        self.assertIn("بيانات حديثة", text.split("HTTP 429")[-1])

    def test_cli_ctrl_c_during_network_returns_130_without_traceback(self):
        from main import main, build_parser
        try:
            build_parser().parse_args(["--live"])
        except SystemExit:
            self.fail("--live entry point is missing")
        out, err = io.StringIO(), io.StringIO()
        with patch("data.downloader.yf.download", side_effect=KeyboardInterrupt), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(["--live"])
        self.assertEqual(result, 130)
        self.assertIn("أُوقف", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())



if __name__ == "__main__":
    unittest.main()
