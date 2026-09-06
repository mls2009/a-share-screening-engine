import json
import logging
from datetime import datetime, time
from threading import Event, Thread
from uuid import uuid4

from pydantic import TypeAdapter

from astock.live.calendar import SHANGHAI
from astock.screening.models import Node


class ScreenScheduleRunner:
    """Run opted-in templates after the local daily market sync has completed."""

    def __init__(self, context, outbox=None):
        self.context = context
        self.outbox = outbox
        self.stop_event = Event()
        self.thread = None

    def run_due(self, now):
        now = now.astimezone(SHANGHAI)
        con = self.context.database.connection
        schedules = con.execute("""select d.definition_id, d.name, d.version, d.condition_tree,
            s.notify, s.last_date, s.last_version, s.last_run_id
            from screen_schedules s join screen_definitions d using(definition_id)
            where s.enabled""").fetchall()
        if not schedules:
            return 0
        if now.weekday() >= 5 or now.time() < time(16, 10):
            return 0
        if not hasattr(self.context.market_sync, "latest_completed_end_date"):
            return 0
        completed = self.context.market_sync.latest_completed_end_date()
        if completed is None or completed < now.date():
            return 0
        if not con.execute("select 1 from market_features where timeframe = '1d' and feature_date = ? limit 1", [now.date()]).fetchone():
            return 0
        count = 0
        for identifier, name, version, tree, notify, last_date, last_version, previous in schedules:
            if last_date == now.date() and last_version == version:
                continue
            try:
                result = self.context.screening.run(TypeAdapter(Node).validate_json(tree), as_of=now.date(), limit=1)
                current_symbols = {row[0] for row in con.execute("select symbol from screen_matches where run_id = ?", [result.run_id]).fetchall()}
                old_symbols = {row[0] for row in con.execute("select symbol from screen_matches where run_id = ?", [previous]).fetchall()} if previous and last_version == version else set()
                con.execute("begin transaction")
                try:
                    con.execute("update screen_schedules set last_date = ?, last_version = ?, last_run_id = ?, last_error = null where definition_id = ?", [now.date(), version, result.run_id, identifier])
                    if notify and self.outbox:
                        payload = {"kind": "screen_summary", "task_name": name, "date": str(now.date()), "matches": result.match_count,
                                   "entered": sorted(current_symbols - old_symbols), "exited": sorted(old_symbols - current_symbols), "baseline": previous is None or last_version != version}
                        con.execute("""insert into notification_outbox(message_id, signal_key, payload, status, next_attempt_at)
                            values (?, ?, ?, 'pending', ?) on conflict(signal_key) do nothing""",
                                    [uuid4(), f"screen:{identifier}:{version}:{now.date()}", json.dumps(payload), now.replace(tzinfo=None)])
                    con.execute("commit")
                except Exception:
                    con.execute("rollback")
                    raise
                count += 1
            except Exception as error:
                con.execute("update screen_schedules set last_error = ? where definition_id = ?", [str(error), identifier])
                logging.getLogger(__name__).exception("scheduled screening failed")
        return count

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.run_due(datetime.now(SHANGHAI))
                if self.outbox:
                    self.outbox.deliver_due(datetime.now(SHANGHAI))
            except Exception:
                logging.getLogger(__name__).exception("screen scheduler failed")
            self.stop_event.wait(60)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = Thread(target=self._loop, daemon=True, name="astock-screen-schedules")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)
