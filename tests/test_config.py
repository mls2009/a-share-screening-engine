from pathlib import Path

from astock.config import Settings


def test_settings_create_data_directories(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    settings.ensure_directories()

    assert settings.database_path == tmp_path / "data" / "astock.duckdb"
    assert settings.bars_dir.is_dir()
