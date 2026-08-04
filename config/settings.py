from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # الأسهم
    symbols: list = field(default_factory=lambda: [
        "TSLA",
        "^GSPC",
    ])

    # إعدادات البيانات
    interval: str = "1m"
    history_period: str = "7d"

    # التدريب
    random_state: int = 42
    test_size: float = 0.2

    # مسار المشروع
    base_dir: Path = Path(__file__).resolve().parent.parent

    raw_data_dir: Path = base_dir / "data" / "raw"
    processed_data_dir: Path = base_dir / "data" / "processed"
    models_dir: Path = base_dir / "models"
    reports_dir: Path = base_dir / "reports"
    logs_dir: Path = base_dir / "logs"

    def __post_init__(self):
        for folder in [
            self.raw_data_dir,
            self.processed_data_dir,
            self.models_dir,
            self.reports_dir,
            self.logs_dir,
        ]:
            folder.mkdir(parents=True, exist_ok=True)


config = Config()
