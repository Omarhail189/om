import pandas as pd
import numpy as np
import ta

from data.processor import DataProcessor


class IndicatorEngine:

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:

        DataProcessor().validate(df)
        if len(df) < 200:
            raise ValueError("يلزم توفير 200 شمعة على الأقل لحساب EMA_200.")
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

        numeric = df.select_dtypes(include="number").columns
        df[numeric] = df[numeric].replace([np.inf, -np.inf], np.nan)
        df.dropna(inplace=True)
        if df.empty:
            raise ValueError("لا توجد شموع صالحة بعد حساب المؤشرات؛ تحقق من طول البيانات والحجم.")

        df.reset_index(drop=True, inplace=True)

        return df


if __name__ == "__main__":
    import sys
    from main import main

    sys.exit(main(sys.argv[1:]))
