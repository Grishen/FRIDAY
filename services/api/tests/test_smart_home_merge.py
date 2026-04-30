from friday_api.smart_home.state_merge import merge_state


def test_merge_state_shallow_override() -> None:
    base = {"on": False, "brightness": 40}
    out = merge_state(base, {"on": True})
    assert out == {"on": True, "brightness": 40}


def test_merge_state_nested() -> None:
    base = {"meta": {"a": 1, "b": 2}}
    out = merge_state(base, {"meta": {"b": 3}})
    assert out == {"meta": {"a": 1, "b": 3}}
