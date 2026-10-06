"""Optional Yahoo download; offline analysis does not import yfinance."""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from config.settings import config
from data.processor import DataProcessor


class YahooDownloader:
    def __init__(self):
        self.raw_dir = config.raw_data_dir

    def download(self, symbol: str, period=None, interval=None) -> pd.DataFrame:
        print(f"تنزيل بيانات {symbol} من Yahoo…")
        try:
            raw = yf.download(
                symbol, period=period or config.history_period,
                interval=interval or config.interval,
                auto_adjust=True, progress=False, multi_level_index=False,
                ignore_tz=False, threads=False, timeout=20,
            )
        except Exception as exc:
            raise RuntimeError(f"تعذر الاتصال بمصدر البيانات: {exc}") from exc
        if raw is None or raw.empty:
            raise RuntimeError(f"لم تصل بيانات للرمز {symbol}. يمكنك استخدام --input لتحليل CSV محلي.")
        df = DataProcessor().normalize(raw.reset_index(), symbol=symbol)
        self.raw_dir = Path(self.raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filepath = self.raw_dir / f"{symbol.replace('^', '')}_{stamp}.csv"
        saved = df.copy()
        saved["Symbol"] = symbol
        saved.to_csv(filepath, index=False, mode="x")
        df.attrs["source_file"] = str(filepath.resolve())
        print(f"حُفظ المصدر: {filepath}")
        return df


if __name__ == "__main__":
    import sys
    from main import main

    sys.exit(main(["--download", *sys.argv[1:]]))
