import pandas as pd
import ta

from data.processor import DataProcessor


class IndicatorEngine:

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:

        df = df.copy()

        # ==========================
        # EMA
        # ==========================
        df["EMA_9"] = ta.trend.ema_indicator(df["Close"], window=9)
        df["EMA_20"] = ta.trend.ema_indicator(df["Close"], window=20)
        df["EMA_50"] = ta.trend.ema_indicator(df["Close"], window=50)
        df["EMA_200"] = ta.trend.ema_indicator(df["Close"], window=200)

        # ==========================
        # RSI
        # ==========================
        df["RSI"] = ta.momentum.rsi(df["Close"], window=14)

        # ==========================
        # MACD
        # ==========================
        macd = ta.trend.MACD(df["Close"])

        df["MACD"] = macd.macd()
        df["MACD_SIGNAL"] = macd.macd_signal()
        df["MACD_HIST"] = macd.macd_diff()

        # ==========================
        # ATR
        # ==========================
        atr = ta.volatility.AverageTrueRange(
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            window=14,
        )

        df["ATR"] = atr.average_true_range()

        # ==========================
        # VWAP
        # ==========================
        vwap = ta.volume.VolumeWeightedAveragePrice(
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            volume=df["Volume"],
        )

        df["VWAP"] = vwap.volume_weighted_average_price()

        # ==========================
        # Relative Volume
        # ==========================
        df["RVOL"] = df["Volume"] / df["Volume"].rolling(20).mean()

        df.dropna(inplace=True)

        df.reset_index(drop=True, inplace=True)

        return df


if __name__ == "__main__":

    from pathlib import Path

    latest = sorted(Path("data/raw").glob("*.csv"))[-1]

    processor = DataProcessor()

    df = processor.load_csv(latest)

    engine = IndicatorEngine()

    df = engine.add_indicators(df)

    print(df.head())

    print()

    print(df.columns.tolist())

    print()

    print(df.info())
