"""Run one function over many items in worker processes, each capped in memory,
so one oversized feed fails alone instead of taking the host down."""

import multiprocessing
import resource
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool


class WorkerError(Exception):
    """An item's failure, as "ExceptionType: message"."""


def limit_memory(max_bytes: int | None) -> None:
    """Cap this process's address space; allocations past it raise MemoryError."""
    if max_bytes:
        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))


def guarded[T, R](fn: Callable[[T], R], item: T) -> R | WorkerError:
    """The result or a WorkerError. The error is formatted inside `except` and
    returned after it, so the failed call's frames, and the memory they hold,
    are gone before the result is sent back."""
    try:
        return fn(item)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return WorkerError(error)


def isolated[T, R](
    fn: Callable[[T], R], item: T, max_bytes: int | None
) -> R | WorkerError:
    """`fn(item)` in a process of its own, so a crash fails only this item."""
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("forkserver"),
        initializer=limit_memory,
        initargs=(max_bytes,),
    ) as pool:
        try:
            return pool.submit(guarded, fn, item).result()
        except BrokenProcessPool:
            return WorkerError("BrokenProcessPool: worker died")


def run_all[T, R](
    fn: Callable[[T], R],
    items: Iterable[T],
    workers: int,
    max_bytes: int | None = None,
) -> Iterator[tuple[T, R | WorkerError]]:
    """(item, result or WorkerError) as each finishes, `workers` at a time.
    `workers` <= 1 runs in this process, uncapped."""
    if workers <= 1:
        for item in items:
            yield item, guarded(fn, item)
        return
    with ThreadPoolExecutor(max_workers=workers) as threads:
        futures = {
            threads.submit(isolated, fn, item, max_bytes): item for item in items
        }
        for future in as_completed(futures):
            yield futures[future], future.result()
