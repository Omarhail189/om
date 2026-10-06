import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from data.processor import DataProcessor
from data.indicators import IndicatorEngine


ROOT = Path(__file__).resolve().parents[1]
GSPC = ROOT / "data/raw/GSPC_20260726_190400.csv"
TSLA = ROOT / "data/raw/TSLA_20260726_190359.csv"


class ProcessorTests(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            path.write_text(text, encoding="utf-8")
            return DataProcessor().load_csv(path)

    def test_existing_yahoo_data_is_normalized_to_utc(self):
        df = DataProcessor().load_csv(GSPC)
        self.assertEqual(len(df), 2730)
        self.assertEqual(str(df["Datetime"].dt.tz), "UTC")
        self.assertEqual(df.iloc[0]["Datetime"].isoformat(), "2026-07-16T13:30:00+00:00")
        self.assertEqual(df.attrs["symbol"], "^GSPC")

    def test_single_header_and_naive_new_york_time_keep_all_rows(self):
        df = self.load_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-01-05 09:30:00,10,12,9,11,100\n"
            "2026-07-06 09:30:00,11,13,10,12,120\n"
        )
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["Datetime"].isoformat(), "2026-01-05T14:30:00+00:00")
        self.assertEqual(df.iloc[1]["Datetime"].isoformat(), "2026-07-06T13:30:00+00:00")

    def test_different_explicit_dst_offsets_are_supported(self):
        df = self.load_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-01-05 09:30:00-05:00,10,12,9,11,100\n"
            "2026-07-06 09:30:00-04:00,11,13,10,12,120\n"
        )
        self.assertEqual(str(df["Datetime"].dt.tz), "UTC")
        self.assertEqual(df.iloc[1]["Datetime"].hour, 13)

    def test_rows_are_sorted_before_rolling_indicators(self):
        df = self.load_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-07-06T13:31:00Z,11,13,10,12,120\n"
            "2026-07-06T13:30:00Z,10,12,9,11,100\n"
        )
        self.assertEqual(df["Close"].tolist(), [11, 12])

    def test_bad_input_is_rejected_instead_of_silently_dropping_rows(self):
        bad_rows = [
            "not-a-date,10,12,9,11,100",
            "2026-07-06T13:30:00Z,10,12,9,bad,100",
            "2026-07-06T13:30:00Z,10,12,9,11,-1",
            "2026-07-06T13:30:00Z,10,8,9,11,100",
            "2026-07-06T13:30:00Z,10,12,9,inf,100",
        ]
        for row in bad_rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.load_text("Datetime,Open,High,Low,Close,Volume\n" + row + "\n")

    def test_missing_column_is_reported(self):
        with self.assertRaisesRegex(ValueError, "Volume"):
            self.load_text("Datetime,Open,High,Low,Close\n2026-07-06T13:30:00Z,10,12,9,11\n")

    def test_duplicate_candles_are_rejected(self):
        with self.assertRaises(ValueError):
            self.load_text(
                "Datetime,Open,High,Low,Close,Volume\n"
                "2026-07-06T13:30:00Z,10,12,9,11,100\n"
                "2026-07-06T13:30:00Z,10,12,9,11,100\n"
            )

    def test_mixed_naive_and_aware_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            self.load_text(
                "Datetime,Open,High,Low,Close,Volume\n"
                "2026-07-06 09:30:00,10,12,9,11,100\n"
                "2026-07-06T13:31:00Z,10,12,9,11,100\n"
            )

    def test_multiple_tickers_are_rejected(self):
        with self.assertRaises(ValueError):
            self.load_text(
                "Price,Close,High,Low,Open,Volume\n"
                "Ticker,TSLA,AAPL,TSLA,TSLA,TSLA\nDatetime,,,,,\n"
                "2026-07-06T13:30:00Z,11,12,9,10,100\n"
            )

    def test_compact_date_tokens_are_dates_not_nanoseconds(self):
        for header in ["Date", " Date "]:
            with self.subTest(header=header):
                df = self.load_text(header + ",Open,High,Low,Close,Volume\n20260706,10,12,9,11,100\n")
                self.assertEqual(df.iloc[0]["Datetime"].isoformat(), "2026-07-06T04:00:00+00:00")

    def test_extra_csv_field_cannot_become_a_silent_index(self):
        with self.assertRaises(ValueError):
            self.load_text(
                "Datetime,Open,High,Low,Close,Volume\n"
                "BAD,2026-07-06T13:30:00Z,10,12,9,11,100\n"
            )

    def test_duplicate_header_cannot_hide_bad_values(self):
        with self.assertRaises(ValueError):
            self.load_text(
                "Datetime,Open,High,Low,Close,Close,Volume\n"
                "2026-07-06T13:30:00Z,10,12,9,11,BAD,100\n"
            )


class IndicatorTests(unittest.TestCase):
    def test_short_dataset_has_a_clear_error(self):
        df = DataProcessor().load_csv(TSLA).head(100)
        with self.assertRaisesRegex(ValueError, "200"):
            IndicatorEngine().add_indicators(df)

    def test_zero_volume_data_cannot_produce_usable_indicators(self):
        df = DataProcessor().load_csv(TSLA).head(250).copy()
        df["Volume"] = 0
        with self.assertRaises(ValueError):
            IndicatorEngine().add_indicators(df)


class CLITests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "main.py"), *args],
            cwd=cwd, text=True, capture_output=True, timeout=30,
        )

    def test_both_symbols_produce_reports_from_another_directory(self):
        for symbol, source in [("GSPC", GSPC), ("TSLA", TSLA)]:
            with self.subTest(symbol=symbol), tempfile.TemporaryDirectory() as tmp:
                before = hashlib.sha256(source.read_bytes()).hexdigest()
                result = self.run_cli("--symbol", symbol, "--output-dir", tmp, "--rows", "0", cwd=tmp)
                self.assertEqual(result.returncode, 0, result.stderr)
                summaries = list(Path(tmp).glob("*/summary.json"))
                self.assertEqual(len(summaries), 1, result.stdout)
                summary = json.loads(summaries[0].read_text())
                self.assertEqual(summary["symbol"], "^GSPC" if symbol == "GSPC" else "TSLA")
                self.assertEqual(summary["input_rows"], 2730)
                self.assertEqual(summary["analyzed_rows"], 2531)
                self.assertEqual(summary["input_sha256"], before)
                self.assertEqual(sum(summary["signal_counts"].values()), 2531)
                signals = pd.read_csv(summaries[0].parent / "signals.csv")
                self.assertEqual(len(signals), 2531)
                self.assertTrue({"SIGNAL", "SCORE", "REASON"}.issubset(signals.columns))
                self.assertTrue((summaries[0].parent / "report.txt").is_file())
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_explicit_input_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("--symbol", "TSLA", "--input", str(TSLA), "--output-dir", tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            summaries = list(Path(tmp).glob("*/summary.json"))
            self.assertEqual(len(summaries), 1)
            summary = json.loads(summaries[0].read_text())
            self.assertEqual(summary["source_file"], str(TSLA))

    def test_wrong_symbol_does_not_label_tsla_as_gspc(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("--symbol", "GSPC", "--input", str(TSLA), "--output-dir", tmp)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(list(Path(tmp).glob("*/summary.json")))

    def test_invalid_arguments_and_missing_file_return_failure_without_traceback(self):
        for args in [("--symbol", "UNKNOWN"), ("--input", "/missing/sample.csv"), ("--rows", "-1")]:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)

    def test_download_and_input_cannot_be_combined(self):
        result = self.run_cli("--input", str(GSPC), "--download")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_separate_runs_do_not_overwrite_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(2):
                result = self.run_cli("--output-dir", tmp, "--rows", "0")
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(Path(tmp).glob("*/summary.json"))), 2)


class DownloaderTests(unittest.TestCase):
    def test_downloaded_dataframe_is_saved_as_a_readable_csv(self):
        from data.downloader import YahooDownloader

        # Only the network call is replaced. Parsing, UTC normalization and IO are real.
        downloaded = pd.DataFrame(
            {"Open": [10], "High": [12], "Low": [9], "Close": [11], "Volume": [100]},
            index=pd.DatetimeIndex(["2026-07-06 09:30:00"], tz="America/New_York", name="Datetime"),
        )
        with tempfile.TemporaryDirectory() as tmp, patch("data.downloader.yf.download", return_value=downloaded):
            downloader = YahooDownloader()
            downloader.raw_dir = Path(tmp)
            result = downloader.download("^GSPC")
            paths = list(Path(tmp).glob("GSPC_*.csv"))
            self.assertEqual(len(paths), 1)
            loaded = DataProcessor().load_csv(paths[0])
            self.assertEqual(str(result["Datetime"].dt.tz), "UTC")
            self.assertEqual(loaded.attrs["symbol"], "^GSPC")
            self.assertEqual(loaded.iloc[0]["Close"], 11)

    def test_empty_download_does_not_create_a_csv(self):
        from data.downloader import YahooDownloader

        with tempfile.TemporaryDirectory() as tmp, patch("data.downloader.yf.download", return_value=pd.DataFrame()):
            downloader = YahooDownloader()
            downloader.raw_dir = Path(tmp)
            with self.assertRaises(RuntimeError):
                downloader.download("TSLA")
            self.assertFalse(list(Path(tmp).glob("*.csv")))


if __name__ == "__main__":
    unittest.main()
