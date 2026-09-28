import os
import signal

from cape_flier.pool import WorkerError, run_all


def work(item):
    if item == "big":
        return bytearray(400_000_000)
    if item == "kill":
        os.kill(os.getpid(), signal.SIGKILL)
    if item == "bad":
        raise ValueError("bad feed")
    return item.upper()


def test_inline_reports_errors():
    results = dict(run_all(work, ["a", "bad"], workers=1))
    assert results["a"] == "A"
    assert isinstance(results["bad"], WorkerError)
    assert str(results["bad"]) == "ValueError: bad feed"


def test_memory_cap_fails_only_that_item():
    results = dict(run_all(work, ["big", "a", "b"], workers=2, max_bytes=300_000_000))
    assert str(results["big"]).startswith("MemoryError")
    assert results["a"] == "A" and results["b"] == "B"


def test_killed_worker_fails_alone():
    items = ["kill", *"abcdef"]
    results = dict(run_all(work, items, workers=2))
    assert str(results["kill"]) == "BrokenProcessPool: worker died"
    assert all(results[item] == item.upper() for item in "abcdef")
