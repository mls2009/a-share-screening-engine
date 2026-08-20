from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.notifications.feishu import FeishuNotifier, sign
from astock.notifications.outbox import OutboxWorker
from astock.storage.database import Database

NOW = datetime(2026, 8, 20, 2, tzinfo=UTC)
SHANGHAI = ZoneInfo("Asia/Shanghai")
PAYLOAD = {
    "type": "price_signal",
    "task_name": "茅台突破 1500",
    "symbol": "600519.SH",
    "comparator": "cross_above",
    "threshold": 1500,
    "price": 1501,
    "triggered_at": "2026-08-20T10:00:00+08:00",
}


def test_feishu_signature_and_card_payload() -> None:
    captured = {}

    def transport(url: str, payload: dict, timeout: float) -> dict:
        captured.update(url=url, payload=payload, timeout=timeout)
        return {"code": 0, "msg": "ok"}

    notifier = FeishuNotifier("https://example.test/hook", "test-secret", transport)
    result = notifier.send(PAYLOAD, timestamp=1599360473)

    assert sign("1599360473", "test-secret") == "wSds2BzzFIIGf/WrhUO+NI1q/9j+FRJd3JNHKAq0NZY="
    assert result.success is True
    assert captured["payload"]["msg_type"] == "interactive"
    assert captured["payload"]["sign"] == sign("1599360473", "test-secret")
    assert "600519.SH" in str(captured["payload"]["card"])


def test_outbox_retries_then_marks_sent(tmp_path: Path) -> None:
    database = Database(tmp_path / "outbox.duckdb")
    database.migrate()
    database.connection.execute(
        """
        insert into notification_outbox
          (message_id, payload, status, next_attempt_at)
        values ('00000000-0000-0000-0000-000000000001', ?, 'pending', ?)
        """,
        [PAYLOAD, NOW],
    )

    class FlakyNotifier:
        calls = 0

        def send(self, payload: dict):
            self.calls += 1
            return type("Result", (), {
                "success": self.calls > 1,
                "error": None if self.calls > 1 else "temporary failure",
            })()

    notifier = FlakyNotifier()
    worker = OutboxWorker(database, notifier)
    assert worker.deliver_due(NOW) == 0
    first = database.connection.execute(
        "select status, attempts, next_attempt_at from notification_outbox"
    ).fetchone()
    expected_retry = NOW.astimezone(SHANGHAI).replace(tzinfo=None) + timedelta(seconds=5)
    assert first == ("pending", 1, expected_retry)

    assert worker.deliver_due(NOW + timedelta(seconds=5)) == 1
    assert database.connection.execute(
        "select status, attempts from notification_outbox"
    ).fetchone() == ("sent", 2)
