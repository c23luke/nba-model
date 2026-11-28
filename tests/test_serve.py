from engine import serve


def test_wait_grows_and_caps():
    assert serve.wait_after(0) == 0
    assert [serve.wait_after(i) for i in (1, 2, 3, 4)] == [15, 30, 60, 120]
    assert serve.wait_after(20) == serve.MAX_WAIT


def test_failed_means_crash_or_too_short():
    assert serve.failed(1, 3000) and serve.failed(0, 5)
    assert not serve.failed(0, 3300)


def _run(codes, monkeypatch):
    """Play a list of launches. A 'good' launch is exit 0 and long; time is faked so nothing really waits."""
    clock = {"t": 0.0}
    monkeypatch.setattr(serve.time, "time", lambda: clock["t"])
    it = iter(codes)

    def launch():
        code = next(it)
        clock["t"] += 3300 if code == 0 else 2
        return code
    alerts, waits = [], []
    serve.main(launch=launch, sleep=waits.append, rounds=len(codes), alert=lambda t, b, log: alerts.append(t))
    return alerts, waits


def test_alerts_once_after_three_failures_then_on_recovery(monkeypatch):
    alerts, waits = _run([0, 1, 1, 1, 1, 1, 0, 0], monkeypatch)
    assert alerts == ["NBA watcher is DOWN", "NBA watcher is back"]
    assert waits == [0, 15, 30, 60, 120, 240, 0, 0]


def test_one_bad_launch_does_not_alert(monkeypatch):
    alerts, waits = _run([0, 1, 0], monkeypatch)
    assert alerts == [] and waits == [0, 15, 0]


def test_launch_that_raises_counts_as_a_failure(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(serve.time, "time", lambda: clock["t"])

    def boom():
        raise OSError("no python")
    alerts = []
    serve.main(launch=boom, sleep=lambda s: None, rounds=3, alert=lambda t, b, log: alerts.append(t))
    assert alerts == ["NBA watcher is DOWN"]
