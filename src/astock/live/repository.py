import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from astock.live.models import (
    MonitorTask,
    MonitorTaskCreate,
    PriceEvaluation,
    SignalState,
)
from astock.storage.database import Database

SHANGHAI = ZoneInfo("Asia/Shanghai")


class MonitoringRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _task(row: tuple) -> MonitorTask:
        return MonitorTask(
            task_id=row[0],
            name=row[1],
            symbols=json.loads(row[2]),
            comparator=row[3],
            threshold=row[4],
            cooldown_seconds=row[5],
            scope=row[6],
            enabled=row[7],
            created_at=row[8],
            updated_at=row[9],
        )

    def create_task(self, payload: MonitorTaskCreate) -> MonitorTask:
        task_id = uuid4()
        row = self.database.connection.execute(
            """
            insert into monitor_tasks
              (task_id, name, symbols, comparator, threshold, cooldown_seconds,
               scope, enabled)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            returning *
            """,
            [
                task_id,
                payload.name,
                json.dumps(payload.symbols),
                payload.comparator.value,
                payload.threshold,
                payload.cooldown_seconds,
                payload.scope.value,
                payload.enabled,
            ],
        ).fetchone()
        return self._task(row)

    def list_tasks(self, enabled: bool | None = None) -> list[MonitorTask]:
        sql = "select * from monitor_tasks"
        parameters = []
        if enabled is not None:
            sql += " where enabled = ?"
            parameters.append(enabled)
        sql += " order by created_at, task_id"
        return [
            self._task(row)
            for row in self.database.connection.execute(sql, parameters).fetchall()
        ]

    def get_task(self, task_id: UUID) -> MonitorTask | None:
        row = self.database.connection.execute(
            "select * from monitor_tasks where task_id = ?", [task_id]
        ).fetchone()
        return self._task(row) if row else None

    def set_enabled(self, task_id: UUID, enabled: bool) -> MonitorTask | None:
        row = self.database.connection.execute(
            """
            update monitor_tasks
            set enabled = ?, updated_at = current_timestamp
            where task_id = ?
            returning *
            """,
            [enabled, task_id],
        ).fetchone()
        return self._task(row) if row else None

    def delete_task(self, task_id: UUID) -> bool:
        connection = self.database.connection
        connection.execute("begin transaction")
        try:
            connection.execute("delete from signal_states where task_id = ?", [task_id])
            deleted = connection.execute(
                "delete from monitor_tasks where task_id = ? returning task_id", [task_id]
            ).fetchone()
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise
        return deleted is not None

    def get_state(self, task_id: UUID, symbol: str) -> SignalState:
        row = self.database.connection.execute(
            """
            select active, last_value, last_triggered_at
            from signal_states where task_id = ? and symbol = ?
            """,
            [task_id, symbol],
        ).fetchone()
        if row is None:
            return SignalState(task_id=str(task_id), symbol=symbol)
        return SignalState(
            task_id=str(task_id),
            symbol=symbol,
            active=row[0],
            last_value=row[1],
            last_triggered_at=(row[2].replace(tzinfo=SHANGHAI) if row[2] else None),
        )

    def list_signals(self, limit: int = 100) -> list[dict]:
        cursor = self.database.connection.execute(
            """
            select signal_key, task_id, symbol, quote_timestamp, triggered_at,
                   price, threshold, comparator, payload
            from signals order by triggered_at desc limit ?
            """,
            [limit],
        )
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def save_evaluation(
        self,
        task: MonitorTask,
        evaluation: PriceEvaluation,
        price: float,
        quote_timestamp: datetime,
    ) -> str | None:
        state = evaluation.state
        signal_key = hashlib.sha256(
            f"{task.task_id}|{state.symbol}|{quote_timestamp.isoformat()}|{task.threshold}".encode()
        ).hexdigest()
        payload = {
            "type": "price_signal",
            "task_name": task.name,
            "symbol": state.symbol,
            "comparator": task.comparator.value,
            "threshold": task.threshold,
            "price": price,
            "triggered_at": quote_timestamp.isoformat(),
        }
        connection = self.database.connection
        connection.execute("begin transaction")
        try:
            connection.execute(
                """
                insert into signal_states
                  (task_id, symbol, active, last_value, last_triggered_at)
                values (?, ?, ?, ?, ?)
                on conflict (task_id, symbol) do update set
                  active = excluded.active,
                  last_value = excluded.last_value,
                  last_triggered_at = excluded.last_triggered_at
                """,
                [
                    task.task_id,
                    state.symbol,
                    state.active,
                    state.last_value,
                    state.last_triggered_at,
                ],
            )
            created = None
            if evaluation.triggered:
                created = connection.execute(
                    """
                    insert into signals
                      (signal_key, task_id, symbol, quote_timestamp, triggered_at,
                       price, threshold, comparator, payload)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict do nothing
                    returning signal_key
                    """,
                    [
                        signal_key,
                        task.task_id,
                        state.symbol,
                        quote_timestamp,
                        state.last_triggered_at,
                        price,
                        task.threshold,
                        task.comparator.value,
                        json.dumps(payload, ensure_ascii=False),
                    ],
                ).fetchone()
                if created is not None:
                    connection.execute(
                        """
                        insert into notification_outbox
                          (message_id, signal_key, payload, status, next_attempt_at)
                        values (?, ?, ?, 'pending', ?)
                        """,
                        [
                            uuid4(),
                            signal_key,
                            json.dumps(payload, ensure_ascii=False),
                            quote_timestamp,
                        ],
                    )
            connection.execute("commit")
        except Exception:
            connection.execute("rollback")
            raise
        return signal_key if created is not None else None
