from astock.data.updates import MarketUpdates


def test_completion_is_retained_until_each_subscriber_reads_it():
    updates = MarketUpdates()
    assert updates.wait(0, timeout=0) == 0
    updates.publish()
    assert updates.wait(0, timeout=0) == 1
    assert updates.wait(0, timeout=0) == 1
    assert updates.wait(1, timeout=0) == 1
    updates.publish()
    assert updates.wait(1, timeout=0) == 2
