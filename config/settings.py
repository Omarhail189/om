"""Project-relative paths; importing settings never creates directories."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    symbols: list = field(default_factory=lambda: ["TSLA", "^GSPC"])
    interval: str = "1m"
    history_period: str = "5d"
    random_state: int = 42
    test_size: float = 0.2
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])

    @property
    def raw_data_dir(self):
        return self.base_dir / "data" / "raw"

    @property
    def processed_data_dir(self):
        return self.base_dir / "data" / "processed"

    @property
    def models_dir(self):
        return self.base_dir / "models"

    @property
    def reports_dir(self):
        return self.base_dir / "reports"

    @property
    def logs_dir(self):
        return self.base_dir / "logs"


config = Config()
