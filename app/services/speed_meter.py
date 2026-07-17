"""
Asyncio-based speed meter for Ghost Downloader 3.

Records bytes transferred and enforces download speed limits:

- ``speedMeter.addSpeed(n)``   — record *n* bytes transferred
- ``await speedMeter.waitForSpeedLimit()`` — block if speed limit is exceeded
"""

from __future__ import annotations

import asyncio

from app.config.cfg import cfg


class SpeedMeter:
    """Tracks transfer speed and enforces optional rate limiting.

    A background task calls ``_tick()`` every second to compute the current
    speed.  ``waitForSpeedLimit()`` is a coroutine that sleeps while the
    1-second byte count exceeds the configured limit.
    """

    def __init__(self):
        self._bytes = 0
        self._task: asyncio.Task | None = None
        self._speed = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._bytes = 0
        self._speed = 0

    def addSpeed(self, byteCount: int) -> None:
        self._bytes += byteCount

    async def waitForSpeedLimit(self) -> None:
        while cfg.isSpeedLimitEnabled.value and self._bytes > cfg.speedLimitation.value:
            await asyncio.sleep(0.1)

    @property
    def speed(self) -> int:
        return self._speed

    async def _run(self) -> None:
        """Background loop: compute speed every second."""
        while True:
            await asyncio.sleep(1)
            self._speed = self._bytes
            self._bytes = 0


# Module-level singleton — imported by feature packs as:
#   from app.services.speed_meter import speedMeter
speedMeter = SpeedMeter()
