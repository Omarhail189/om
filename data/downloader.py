from pathlib import Path
from datetime import datetime

import pandas as pd
import yfinance as yf

from config.settings import config


class YahooDownloader:
    def __init__(self):
        self.raw_dir = config.raw_data_dir

    def download(self, symbol: str) -> pd.DataFrame:
        print(f"[INFO] Downloading {symbol}")

        df = yf.download(
            symbol,
            period=config.history_period,
            interval=config.interval,
            auto_adjust=True,
            progress=False,
        )

        if df.empty:
            raise RuntimeError(f"No data received for {symbol}")

        filename = (
            symbol.replace("^", "")
            + "_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".csv"
        )

        filepath = self.raw_dir / filename

        df.to_csv(filepath)

        print(f"[OK] Saved -> {filepath}")

        return df


if __name__ == "__main__":

    downloader = YahooDownloader()

    for symbol in config.symbols:
        df = downloader.download(symbol)
        print(df.tail())
