from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID, uuid4

import duckdb


@dataclass(frozen=True)
class SyncJob:
    job_id: UUID
    start_date: date
    end_date: date
    status: str
    total: int
    succeeded: int
    failed: int
    current_symbol: str | None
    created_at: datetime
    started_at: datetime
    finished_at: datetime | None


class SyncJobRepository:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection

    def create(self, start_date: str | date, end_date: str | date, total: int) -> UUID:
        job_id = uuid4()
        self.connection.execute(
            """
            insert into data_sync_jobs (job_id, start_date, end_date, status, total)
            values (?, ?, ?, 'running', ?)
            """,
            [job_id, start_date, end_date, total],
        )
        return job_id

    def get(self, job_id: UUID) -> SyncJob:
        row = self.connection.execute(
            """
            select job_id, start_date, end_date, status, total, succeeded, failed,
                   current_symbol, created_at, started_at, finished_at
            from data_sync_jobs where job_id = ?
            """,
            [job_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"sync job not found: {job_id}")
        return SyncJob(*row)

    def latest_completed_end_date(self) -> date | None:
        row = self.connection.execute(
            """
            select max(end_date) from data_sync_jobs
            where status in ('completed', 'completed_with_errors')
            """
        ).fetchone()
        return row[0] if row else None

    def mark_succeeded(self, job_id: UUID, symbol: str) -> None:
        self.connection.execute(
            """
            insert into sync_job_symbols (job_id, symbol, status)
            values (?, ?, 'succeeded')
            on conflict (job_id, symbol) do update set
              status = excluded.status, error = null, updated_at = now()
            """,
            [job_id, symbol],
        )
        self.connection.execute(
            """
            update sync_job_failures set resolved_at = now()
            where job_id = ? and symbol = ? and resolved_at is null
            """,
            [job_id, symbol],
        )
        self._refresh_counts(job_id, symbol)

    def mark_failed(self, job_id: UUID, symbol: str, error: str) -> None:
        self.connection.execute(
            """
            insert into sync_job_symbols (job_id, symbol, status, error)
            values (?, ?, 'failed', ?)
            on conflict (job_id, symbol) do update set
              status = excluded.status, error = excluded.error, updated_at = now()
            """,
            [job_id, symbol, error],
        )
        self.connection.execute(
            """
            insert into sync_job_failures (job_id, symbol, error)
            values (?, ?, ?)
            on conflict (job_id, symbol) do update set
              error = excluded.error, created_at = now(), resolved_at = null
            """,
            [job_id, symbol, error],
        )
        self._refresh_counts(job_id, symbol)

    def failed_symbols(self, job_id: UUID) -> list[str]:
        rows = self.connection.execute(
            """
            select symbol from sync_job_failures
            where job_id = ? and resolved_at is null order by symbol
            """,
            [job_id],
        ).fetchall()
        return [row[0] for row in rows]

    def succeeded_symbols(self, job_id: UUID) -> set[str]:
        rows = self.connection.execute(
            """
            select symbol from sync_job_symbols
            where job_id = ? and status = 'succeeded'
            """,
            [job_id],
        ).fetchall()
        return {row[0] for row in rows}

    def complete(self, job_id: UUID) -> None:
        failed = self.get(job_id).failed
        status = "completed_with_errors" if failed else "completed"
        self.connection.execute(
            """
            update data_sync_jobs
            set status = ?, finished_at = now()
            where job_id = ?
            """,
            [status, job_id],
        )

    def reopen(self, job_id: UUID) -> None:
        self.connection.execute(
            """
            update data_sync_jobs
            set status = 'running', finished_at = null
            where job_id = ?
            """,
            [job_id],
        )

    def _refresh_counts(self, job_id: UUID, current_symbol: str) -> None:
        self.connection.execute(
            """
            update data_sync_jobs set
              succeeded = (
                select count(*) from sync_job_symbols
                where job_id = ? and status = 'succeeded'
              ),
              failed = (
                select count(*) from sync_job_symbols
                where job_id = ? and status = 'failed'
              ),
              current_symbol = ?
            where job_id = ?
            """,
            [job_id, job_id, current_symbol, job_id],
        )
