"""Read single-symbol OHLCV CSV files without guessing or discarding bad rows."""

import csv
from itertools import chain
from pathlib import Path

import numpy as np
import pandas as pd


class DataProcessor:
    REQUIRED_COLUMNS = ["Datetime", "Open", "High", "Low", "Close", "Volume"]

    def __init__(self, source_timezone="America/New_York"):
        self.source_timezone = source_timezone

    def load_csv(self, file_path):
        path = Path(file_path).expanduser().resolve()
        try:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream, strict=True)
                preview = [next(reader, []) for _ in range(3)]
                if not preview[0]:
                    raise ValueError("ملف CSV فارغ.")
                header = [name.strip() for name in preview[0]]
                if len(header) != len(set(header)):
                    raise ValueError("أسماء أعمدة CSV مكررة.")
                for number, record in enumerate(chain(preview[1:], reader), start=2):
                    if record and len(record) != len(header):
                        raise ValueError(f"عدد حقول CSV غير مطابق للرأس في السجل {number}.")
        except csv.Error as exc:
            raise ValueError(f"بنية CSV غير صالحة: {exc}") from exc
        symbol = None
        yahoo_header = bool(preview[1]) and preview[1][0] == "Ticker"
        if yahoo_header:
            if not preview[2] or preview[2][0] not in {"Datetime", "Date"}:
                raise ValueError("رأس ملف Yahoo غير مكتمل.")
            tickers = {value.strip() for value in preview[1][1:] if value.strip()}
            if len(tickers) != 1:
                raise ValueError("يجب أن يحتوي CSV على رمز واحد فقط.")
            symbol = tickers.pop()
        try:
            # Date-like tokens must remain text: 20260706 is a date, never nanoseconds.
            df = pd.read_csv(
                path, skiprows=[1, 2] if yahoo_header else None, encoding="utf-8-sig",
                dtype={name: "string" for name in preview[0] if name.strip() in {"Price", "Datetime", "Date", "Timestamp"}},
            )
        except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
            raise ValueError(f"تعذر قراءة CSV: {exc}") from exc
        df = self.normalize(df, symbol=symbol)
        df.attrs["source_file"] = str(path)
        return df

    def normalize(self, df, symbol=None):
        df = df.copy()
        df.columns = [str(column).strip() for column in df.columns]
        if "Datetime" not in df.columns:
            for alias in ["Date", "Timestamp", "Price"]:
                if alias in df.columns:
                    df.rename(columns={alias: "Datetime"}, inplace=True)
                    break
        if "Symbol" in df.columns:
            symbols = set(df["Symbol"].dropna().astype(str).str.strip())
            if len(symbols) != 1 or (symbol and symbol not in symbols):
                raise ValueError("يجب أن يحتوي CSV على رمز واحد متطابق.")
            symbol = symbols.pop()
        self.validate(df)
        df = df[self.REQUIRED_COLUMNS].copy()
        for column in self.REQUIRED_COLUMNS[1:]:
            try:
                df[column] = pd.to_numeric(df[column], errors="raise")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"قيمة غير رقمية في العمود {column}.") from exc
        if not np.isfinite(df[self.REQUIRED_COLUMNS[1:]].to_numpy(dtype=float)).all():
            raise ValueError("بيانات الأسعار والحجم تحتوي قيمًا مفقودة أو غير محدودة.")
        if (df["Volume"] < 0).any() or (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
            raise ValueError("الأسعار يجب أن تكون موجبة والحجم غير سالب.")
        if (df["High"] < df[["Open", "Low", "Close"]].max(axis=1)).any() or (
            df["Low"] > df[["Open", "High", "Close"]].min(axis=1)
        ).any():
            raise ValueError("قيم OHLC غير متسقة داخل الشمعة.")
        try:
            timestamps = df["Datetime"].map(pd.Timestamp)
            if timestamps.isna().any():
                raise ValueError("تاريخ مفقود")
            aware = timestamps.map(lambda value: value.tzinfo is not None)
            if aware.any() and not aware.all():
                raise ValueError("خلط توقيت محلي وتوقيت ذي منطقة زمنية")
            if aware.all():
                df["Datetime"] = pd.to_datetime(df["Datetime"], format="mixed", utc=True, errors="raise")
            else:
                df["Datetime"] = (
                    pd.to_datetime(df["Datetime"], format="mixed", errors="raise")
                    .dt.tz_localize(self.source_timezone, ambiguous="raise", nonexistent="raise")
                    .dt.tz_convert("UTC")
                )
        except Exception as exc:
            raise ValueError(f"تعذر تفسير Datetime والمنطقة الزمنية {self.source_timezone}: {exc}") from exc
        if df["Datetime"].duplicated().any():
            raise ValueError("يوجد توقيت شمعة مكرر؛ صحح الملف قبل التحليل.")
        df = df.sort_values("Datetime", kind="stable").reset_index(drop=True)
        df.attrs["symbol"] = symbol
        return df

    def validate(self, df):
        missing = [column for column in self.REQUIRED_COLUMNS if column not in df.columns]
        if missing:
            raise ValueError("Missing column: " + ", ".join(missing))
        if df.empty:
            raise ValueError("لا توجد شموع في ملف البيانات.")
        return True


if __name__ == "__main__":
    import sys
    from main import main

    sys.exit(main(sys.argv[1:]))
