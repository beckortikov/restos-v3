def test_session_round_trip():
    from pos.auth.session import SessionStore

    s = SessionStore()
    assert s.token is None
    s.token = "abc123"
    assert s.token == "abc123"
    s.token = None
    assert s.token is None


def test_session_clear():
    from pos.auth.session import SessionStore

    s = SessionStore()
    s.token = "xyz"
    s.clear()
    assert s.token is None
