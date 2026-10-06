"""Persist each analysis in its own folder, without overwriting prior runs."""

from datetime import datetime, timezone
import json
from pathlib import Path


class ReportEngine:
    def save(self, df, output_dir, *, symbol, source_file, input_rows, input_sha256):
        now = datetime.now(timezone.utc)
        folder = Path(output_dir) / f"{symbol.replace('^', '')}_{now.strftime('%Y%m%dT%H%M%S%fZ')}"
        folder.mkdir(parents=True, exist_ok=False)
        summary = {
            "symbol": symbol,
            "strategy": "opening",
            "generated_at_utc": now.isoformat(),
            "source_file": str(Path(source_file).resolve()),
            "input_sha256": input_sha256,
            "input_rows": input_rows,
            "analyzed_rows": len(df),
            "excluded_indicator_rows": input_rows - len(df),
            "start_utc": df["Datetime"].iloc[0].isoformat(),
            "end_utc": df["Datetime"].iloc[-1].isoformat(),
            "average_score": round(float(df["SCORE"].mean()), 2),
            "signal_counts": {str(name): int(count) for name, count in df["SIGNAL"].value_counts().items()},
        }
        df.to_csv(folder / "signals.csv", index=False)
        (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        text = (
            f"تقرير تحليل {symbol}\n"
            f"المصدر: {summary['source_file']}\n"
            f"SHA256: {input_sha256}\n"
            f"عدد شموع المصدر: {input_rows}\n"
            f"الشموع المحللة: {len(df)}\n"
            f"الفترة المحللة بتوقيت UTC: {summary['start_utc']} → {summary['end_utc']}\n"
            f"متوسط نقاط الشروط: {summary['average_score']}\n"
            "عدد الإشارات:\n"
            + "\n".join(f"  {name}: {count}" for name, count in summary["signal_counts"].items())
            + "\n\nهذه إشارات شروط الاستراتيجية الحالية. SCORE مجموع نقاط الشروط وليس احتمال نجاح.\n"
            "هذا التشغيل لا يقيس الربحية ولا ينفذ صفقات أو تدريب نماذج.\n"
        )
        (folder / "report.txt").write_text(text, encoding="utf-8")
        return folder, summary
