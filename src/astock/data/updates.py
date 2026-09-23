from threading import Condition


class MarketUpdates:
    """Notify open pages after a batch has finished writing market data."""

    def __init__(self):
        self._condition = Condition()
        self._revision = 0

    @property
    def revision(self):
        with self._condition:
            return self._revision

    def publish(self):
        with self._condition:
            self._revision += 1
            self._condition.notify_all()

    def wait(self, revision, timeout=20):
        with self._condition:
            self._condition.wait_for(lambda: self._revision != revision, timeout)
            return self._revision
