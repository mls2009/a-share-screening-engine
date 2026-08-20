from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.live.models import MonitorTaskCreate, PriceEvaluation, SignalState
from astock.live.repository import MonitoringRepository
from astock.storage.database import Database

NOW = datetime(2026, 8, 20, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def _repository(tmp_path: Path) -> MonitoringRepository:
    database = Database(tmp_path / "monitor.duckdb")
    database.migrate()
    return MonitoringRepository(database)


def test_task_crud_round_trip(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    created = repository.create_task(
        MonitorTaskCreate(
            name="茅台突破 1500",
            symbols=["600519.SH"],
            comparator="cross_above",
            threshold=1500,
        )
    )

    assert repository.list_tasks()[0].task_id == created.task_id
    disabled = repository.set_enabled(created.task_id, False)
    assert disabled is not None and disabled.enabled is False
    assert repository.delete_task(created.task_id) is True
    assert repository.list_tasks() == []


def test_trigger_and_outbox_are_idempotent(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    task = repository.create_task(
        MonitorTaskCreate(
            name="突破 100",
            symbols=["600519.SH"],
            comparator="cross_above",
            threshold=100,
        )
    )
    evaluation = PriceEvaluation(
        triggered=True,
        state=SignalState(
            task_id=str(task.task_id),
            symbol="600519.SH",
            active=True,
            last_value=101,
            last_triggered_at=NOW,
        ),
    )

    first = repository.save_evaluation(task, evaluation, 101, NOW)
    second = repository.save_evaluation(task, evaluation, 101, NOW)

    assert first is not None
    assert second is None
    connection = repository.database.connection
    assert connection.execute("select count(*) from signals").fetchone()[0] == 1
    assert connection.execute("select count(*) from notification_outbox").fetchone()[0] == 1
    assert repository.get_state(task.task_id, "600519.SH").last_value == 101
