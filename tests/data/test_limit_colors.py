from astock.data.limit_colors import limit_state


def test_limit_color_requires_exact_tick_price():
    assert limit_state(11,11,9) == 'up'
    assert limit_state(9,11,9) == 'down'
    assert limit_state(10.98,11,9) is None
    assert limit_state(11,None,None) is None
    assert limit_state(11.00000001,11,9) == 'up'
