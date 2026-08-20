from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTOCK_", env_file=".env")

    data_dir: Path = Path("data")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "astock.duckdb"

    @property
    def bars_dir(self) -> Path:
        return self.data_dir / "bars"

    def ensure_directories(self) -> None:
        self.bars_dir.mkdir(parents=True, exist_ok=True)
