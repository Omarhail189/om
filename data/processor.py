from pathlib import Path
import pandas as pd


class DataProcessor:

    REQUIRED_COLUMNS = [
        "Datetime",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]

    def load_csv(self, file_path):

        # قراءة الملف الخام بدون Header
        raw = pd.read_csv(file_path, header=None)

        # استخراج أسماء الأعمدة من أول سطر
        columns = raw.iloc[0].tolist()

        # حذف أول 3 أسطر (Price / Ticker / Datetime)
        df = raw.iloc[3:].copy()

        df.columns = columns

        # تغيير اسم أول عمود
        df.rename(columns={"Price": "Datetime"}, inplace=True)

        # تحويل التاريخ
        df["Datetime"] = pd.to_datetime(df["Datetime"])

        # تحويل الأعمدة الرقمية
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(inplace=True)

        df.reset_index(drop=True, inplace=True)

        return df

    def validate(self, df):

        for col in self.REQUIRED_COLUMNS:

            if col not in df.columns:
                raise ValueError(f"Missing column: {col}")

        return True


if __name__ == "__main__":

    raw_dir = Path("data/raw")

    latest = sorted(raw_dir.glob("*.csv"))[-1]

    processor = DataProcessor()

    df = processor.load_csv(latest)

    processor.validate(df)

    print(df.head())

    print()

    print(df.info())
