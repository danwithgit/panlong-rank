from app.db import session


def test_sqlite_connect_args_wait_for_locks():
    args = session._connect_args("sqlite:////tmp/panlong.sqlite3")

    assert args["check_same_thread"] is False
    assert args["timeout"] >= 30
