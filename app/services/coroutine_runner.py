"""
Asyncio-based coroutine runner for Ghost Downloader 3.

The public interface:

- ``coroutineRunner.submit(work, done, failed)`` — schedule a coroutine
- ``coroutineRunner.cancel(workId)``              — cancel a pending/running task
- ``coroutineRunner.stop()``                      — cancel all tasks
"""

from __future__ import annotations

import asyncio
from typing import Callable
from uuid import uuid4

from loguru import logger


class CoroutineRunner:
    """Manages async tasks with completion/failure callbacks.

    This is **not** a thread — everything runs on the current event loop.
    Call ``start()`` before submitting work if you need to ensure the loop
    is running.
    """

    def __init__(self):
        self._pending: dict[str, tuple] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        """Create (or capture) an event loop for this runner."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

    def submit(
        self,
        work,
        done: Callable = None,
        failed: Callable = None,
        *args,
        **kwargs,
    ) -> str:
        """Submit an awaitable *work* for execution.

        Parameters
        ----------
        work : coroutine or awaitable
        done : callable, optional
            Called with ``(result, *args, **kwargs)`` on success.
        failed : callable, optional
            Called with ``(error_msg, *args, **kwargs)`` on exception.
        args, kwargs :
            Extra positional/keyword arguments forwarded to *done* / *failed*.

        Returns
        -------
        str
            A unique work ID that can be passed to ``cancel()``.
        """
        work_id = f"wrk_{uuid4().hex}"
        self._pending[work_id] = (done, failed, args, kwargs)

        async def _execute():
            result, error = None, None
            try:
                result = await work
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.opt(exception=e).error("async work failed: {}", work_id)
                error = str(e) or repr(e)
            finally:
                self._running.pop(work_id, None)

            entry = self._pending.pop(work_id, None)
            if entry is None:
                return
            cb_done, cb_failed, cb_args, cb_kwargs = entry
            if error is None:
                if cb_done:
                    try:
                        cb_done(result, *cb_args, **cb_kwargs)
                    except Exception as e2:
                        logger.opt(exception=e2).error("done callback failed")
            elif cb_failed:
                try:
                    cb_failed(error, *cb_args, **cb_kwargs)
                except Exception as e2:
                    logger.opt(exception=e2).error("failed callback errored")

        task = asyncio.create_task(_execute())
        self._running[work_id] = task
        self._pending.pop(work_id, None)  # moved from pending to running
        return work_id

    def cancel(self, work_id: str, finished: Callable = None) -> bool:
        """Cancel a pending or running task.

        Returns ``True`` if a running task was cancelled, ``False`` otherwise.
        """
        self._pending.pop(work_id, None)
        task = self._running.pop(work_id, None)
        if task is not None and not task.done():
            if finished is not None:
                task.add_done_callback(lambda _: finished())
            task.cancel()
            return True
        if finished is not None:
            finished()
        return False

    def stop(self) -> None:
        """Cancel all running tasks."""
        for task in list(self._running.values()):
            if not task.done():
                task.cancel()
        self._pending.clear()
        self._running.clear()

    @property
    def running_count(self) -> int:
        return len(self._running)

    @property
    def running_tasks(self) -> dict[str, asyncio.Task]:
        return dict(self._running)


# Module-level singleton
coroutineRunner = CoroutineRunner()
