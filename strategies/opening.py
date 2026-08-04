import pandas as pd

from data.processor import DataProcessor
from data.indicators import IndicatorEngine


class OpeningStrategy:

    def generate(self, df: pd.DataFrame):

        df = df.copy()

        # ======================================
        # Breakout (أعلى قمة آخر 5 شموع)
        # ======================================

        df["RECENT_HIGH"] = (
            df["High"]
            .rolling(window=5)
            .max()
            .shift(1)
        )

        # ATR المتوسط لآخر 50 شمعة
        df["ATR_MEAN"] = (
            df["ATR"]
            .rolling(50)
            .mean()
        )

        scores = []
        signals = []
        reasons = []

        # لمنع تكرار الإشارة
        cooldown = 10
        last_signal_index = -1000

        for idx, row in df.iterrows():

            score = 0
            why = []

            # ======================================
            # فلتر وقت التداول
            # أول 210 دقيقة + آخر 60 دقيقة
            # ======================================

            t = row["Datetime"].tz_convert("America/New_York")

            minutes = t.hour * 60 + t.minute

            market_open = 9 * 60 + 30
            first_session_end = 13 * 60
            last_session_start = 15 * 60
            market_close = 16 * 60

            in_session = (
                (market_open <= minutes < first_session_end)
                or
                (last_session_start <= minutes < market_close)
            )

            if not in_session:

                scores.append(0)
                signals.append("IGNORE")
                reasons.append("Outside Trading Session")

                continue

            # ======================================
            # Cooldown
            # ======================================

            if idx - last_signal_index < cooldown:

                scores.append(0)
                signals.append("HOLD")
                reasons.append("Cooldown Active")

                continue

            # ======================================
            # Breakout
            # ======================================

            if row["Close"] > row["RECENT_HIGH"]:
                score += 15
                why.append("Breakout")

            # ======================================
            # الاتجاه
            # ======================================

            if row["EMA_9"] > row["EMA_20"]:
                score += 15
                why.append("EMA9>EMA20")

            if row["EMA_20"] > row["EMA_50"]:
                score += 15
                why.append("EMA20>EMA50")

            if row["Close"] > row["EMA_200"]:
                score += 10
                why.append("Above EMA200")

            # ======================================
            # MACD
            # ======================================

            if row["MACD"] > row["MACD_SIGNAL"]:
                score += 15
                why.append("MACD Bullish")

            # ======================================
            # RSI
            # ======================================

            if 55 <= row["RSI"] <= 70:
                score += 10
                why.append("RSI OK")

            # ======================================
            # Volume
            # ======================================

            if row["RVOL"] >= 1.8:
                score += 10
                why.append("High Volume")

            # ======================================
            # VWAP
            # ======================================

            if row["Close"] > row["VWAP"]:
                score += 10
                why.append("Above VWAP")

            # ======================================
            # ATR ديناميكي
            # ======================================

            if row["ATR"] > row["ATR_MEAN"]:
                score += 10
                why.append("ATR Strong")

            # ======================================
            # القرار النهائي
            # ======================================

            if score >= 90:
                signal = "STRONG BUY"
                last_signal_index = idx

            elif score >= 75:
                signal = "BUY"
                last_signal_index = idx

            elif score >= 60:
                signal = "WATCH"

            else:
                signal = "IGNORE"

            scores.append(score)
            signals.append(signal)
            reasons.append(", ".join(why))

        df["SCORE"] = scores
        df["SIGNAL"] = signals
        df["REASON"] = reasons

        return df


if __name__ == "__main__":

    from pathlib import Path

    latest = sorted(Path("data/raw").glob("*.csv"))[-1]

    processor = DataProcessor()

    df = processor.load_csv(latest)

    indicators = IndicatorEngine()

    df = indicators.add_indicators(df)

    strategy = OpeningStrategy()

    df = strategy.generate(df)

    print(
        df[
            [
                "Datetime",
                "Close",
                "SCORE",
                "SIGNAL",
                "REASON",
            ]
        ].tail(40)
    )

    print("\n" + "=" * 60)
    print("Signal Summary")
    print("=" * 60)

    print(df["SIGNAL"].value_counts())

    print("\n" + "=" * 60)
    print("Average Score")
    print("=" * 60)

    print(round(df["SCORE"].mean(), 2))

    print("\n" + "=" * 60)
    print("Top Signals")
    print("=" * 60)

    top = (
        df[df["SIGNAL"].isin(["BUY", "STRONG BUY"])]
        .sort_values("SCORE", ascending=False)
        .head(20)
    )

    print(
        top[
            [
                "Datetime",
                "Close",
                "SCORE",
                "SIGNAL",
                "REASON",
            ]
        ]
    )
