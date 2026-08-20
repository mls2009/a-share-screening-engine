import json
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from astock.storage.database import Database

SHANGHAI = ZoneInfo("Asia/Shanghai")


class Notifier(Protocol):
    def send(self, payload: dict) -> object: ...


class OutboxWorker:
    def __init__(
        self,
        database: Database,
        notifier: Notifier,
        max_attempts: int = 8,
    ) -> None:
        self.database = database
        self.notifier = notifier
        self.max_attempts = max_attempts

    def deliver_due(self, now: datetime) -> int:
        local_now = now.astimezone(SHANGHAI).replace(tzinfo=None)
        lease_expired_before = local_now - timedelta(minutes=5)
        self.database.connection.execute(
            """
            update notification_outbox
            set status = 'pending', next_attempt_at = ?, updated_at = current_timestamp
            where status = 'sending' and updated_at <= ?
            """,
            [local_now, lease_expired_before],
        )
        rows = self.database.connection.execute(
            """
            select message_id, payload, attempts
            from notification_outbox
            where status = 'pending' and next_attempt_at <= ?
            order by next_attempt_at, message_id
            """,
            [local_now],
        ).fetchall()
        sent = 0
        for message_id, raw_payload, attempts in rows:
            claimed = self.database.connection.execute(
                """
                update notification_outbox
                set status = 'sending', attempts = attempts + 1,
                    updated_at = current_timestamp
                where message_id = ? and status = 'pending'
                returning attempts
                """,
                [message_id],
            ).fetchone()
            if claimed is None:
                continue
            current_attempts = claimed[0]
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            result = self.notifier.send(payload)
            if result.success:
                self.database.connection.execute(
                    """
                    update notification_outbox
                    set status = 'sent', last_error = null, updated_at = current_timestamp
                    where message_id = ?
                    """,
                    [message_id],
                )
                sent += 1
                continue
            if current_attempts >= self.max_attempts:
                status = "failed"
                next_attempt = local_now
            else:
                status = "pending"
                delay = min(5 * 2 ** (current_attempts - 1), 1800)
                next_attempt = local_now + timedelta(seconds=delay)
            self.database.connection.execute(
                """
                update notification_outbox
                set status = ?, next_attempt_at = ?, last_error = ?,
                    updated_at = current_timestamp
                where message_id = ?
                """,
                [status, next_attempt, result.error, message_id],
            )
        return sent
