from pathlib import Path

from astock.storage.database import Database
from astock.storage.jobs import SyncJobRepository


def test_sync_job_tracks_progress_failures_and_completion(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.duckdb")
    db.migrate()
    jobs = SyncJobRepository(db.connection)

    job_id = jobs.create(
        start_date="2023-01-01",
        end_date="2026-01-01",
        total=2,
    )
    jobs.mark_succeeded(job_id, "600000.SH")
    jobs.mark_failed(job_id, "000001.SZ", "provider timeout")

    running = jobs.get(job_id)
    assert running.status == "running"
    assert running.succeeded == 1
    assert running.failed == 1
    assert running.current_symbol == "000001.SZ"
    assert jobs.failed_symbols(job_id) == ["000001.SZ"]

    jobs.complete(job_id)

    completed = jobs.get(job_id)
    assert completed.status == "completed_with_errors"
    assert completed.finished_at is not None


def test_successful_retry_removes_active_failure(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.duckdb")
    db.migrate()
    jobs = SyncJobRepository(db.connection)
    job_id = jobs.create("2023-01-01", "2026-01-01", total=1)
    jobs.mark_failed(job_id, "000001.SZ", "temporary error")

    jobs.mark_succeeded(job_id, "000001.SZ")

    assert jobs.failed_symbols(job_id) == []
    job = jobs.get(job_id)
    assert job.succeeded == 1
    assert job.failed == 0
