"""Command-line entry point for the existing CSV → indicators → signals flow."""

import argparse
import hashlib
from pathlib import Path
import sys

from config.settings import config


class OmArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if parsed.live and parsed.interval != "1m":
            self.error("وضع --live يستخدم شموع 1m فقط.")
        if parsed.refresh is not None and not parsed.live:
            self.error("--refresh يُستخدم مع --live فقط.")
        if parsed.refresh is None:
            parsed.refresh = 60
        return parsed


def refresh_seconds(value):
    number = nonnegative_int(value)
    if not 30 <= number <= 900:
        raise argparse.ArgumentTypeError("فترة التحديث يجب أن تكون بين 30 و900 ثانية.")
    return number


def nonnegative_int(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("يجب إدخال عدد صحيح.") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("العدد يجب أن يكون صفرًا أو أكبر.")
    return number


def build_parser():
    parser = OmArgumentParser(description="تحليل CSV أو تشغيل شاشة توصيات مستمرة من Yahoo.")
    parser.add_argument("--symbol", choices=["GSPC", "^GSPC", "TSLA"], default="GSPC", help="الرمز؛ الافتراضي GSPC")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path, help="ملف CSV محدد؛ المسار النسبي من مجلد الطرفية الحالي")
    source.add_argument("--download", action="store_true", help="تنزيل بيانات جديدة بدل الملفات المحلية")
    source.add_argument("--live", action="store_true", help="شاشة توصيات مستمرة من Yahoo؛ شموع دقيقة مغلقة")
    parser.add_argument("--refresh", type=refresh_seconds, help="ثواني فحص المصدر في --live؛ الافتراضي 60، النطاق 30–900")
    parser.add_argument("--output-dir", type=Path, default=config.reports_dir, help="مجلد حفظ التقارير")
    parser.add_argument("--timezone", default="America/New_York", help="منطقة CSV فقط إذا لم يتضمن توقيته منطقة زمنية")
    parser.add_argument("--rows", type=nonnegative_int, default=10, help="عدد آخر الإشارات المعروضة؛ صفر لإخفائها")
    parser.add_argument("--period", default=config.history_period, help="فترة التنزيل فقط؛ الافتراضي 5d")
    parser.add_argument("--interval", choices=["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d"], default=config.interval, help="فاصل التنزيل فقط")
    return parser


def select_source(symbol, raw_dir):
    key = symbol.replace("^", "")
    candidates = list(Path(raw_dir).glob(f"{key}_*.csv"))
    if not candidates:
        raise FileNotFoundError(f"لا توجد ملفات للرمز {symbol} في {raw_dir}. استخدم --input أو --download.")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name)).resolve()


def run(args):
    if args.live:
        from live import run_live

        return run_live(args)

    from data.processor import DataProcessor
    from data.indicators import IndicatorEngine
    from strategies.opening import OpeningStrategy
    from reports.report_engine import ReportEngine

    symbol = "^GSPC" if args.symbol in {"GSPC", "^GSPC"} else "TSLA"
    if args.download:
        from data.downloader import YahooDownloader

        df = YahooDownloader().download(symbol, period=args.period, interval=args.interval)
        source = Path(df.attrs["source_file"])
    else:
        source = args.input.expanduser().resolve() if args.input else select_source(symbol, config.raw_data_dir)
        df = DataProcessor(source_timezone=args.timezone).load_csv(source)
    source_symbol = df.attrs.get("symbol")
    if source_symbol and source_symbol.lstrip("^") != symbol.lstrip("^"):
        raise ValueError(f"رمز الملف {source_symbol} لا يطابق الرمز المطلوب {symbol}.")
    input_rows = len(df)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    signals = OpeningStrategy().generate(IndicatorEngine().add_indicators(df))
    folder, summary = ReportEngine().save(
        signals, args.output_dir.expanduser().resolve(), symbol=symbol,
        source_file=source, input_rows=input_rows, input_sha256=digest,
    )
    print(f"الرمز: {symbol}\nالمصدر: {source}\nالشموع: {input_rows}؛ المحللة: {len(signals)}")
    print("عدد الإشارات: " + ", ".join(f"{name}={count}" for name, count in summary["signal_counts"].items()))
    if args.rows:
        print(signals[["Datetime", "Close", "SCORE", "SIGNAL", "REASON"]].tail(args.rows).to_string(index=False))
    print(f"نتائج التشغيل: {folder}")
    print("الملفات: signals.csv | summary.json | report.txt")
    return folder


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except ModuleNotFoundError as exc:
        print(f"اعتمادية غير مثبتة: {exc.name}. نفّذ bash setup.sh أو python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"خطأ: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("أُوقف التشغيل بواسطة المستخدم.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
