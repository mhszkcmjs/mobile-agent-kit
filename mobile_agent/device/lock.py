"""
设备互斥锁 PRD §6.5。
进程内单例,带心跳 + 超时强制释放。MVP 单进程,不引 redis。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from mobile_agent.constants import DEVICE_LOCK_TIMEOUT_SEC


@dataclass
class LockHolder:
    task_id: str
    acquired_at: float
    last_heartbeat: float


class DeviceBusy(RuntimeError):
    pass


class DeviceLock:
    _instances: dict[str, "DeviceLock"] = {}
    _factory_lock = threading.Lock()

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self._mu = threading.Lock()
        self._holder: LockHolder | None = None

    @classmethod
    def for_device(cls, device_id: str) -> "DeviceLock":
        with cls._factory_lock:
            if device_id not in cls._instances:
                cls._instances[device_id] = cls(device_id)
            return cls._instances[device_id]

    def acquire(self, task_id: str, *, blocking: bool = False) -> bool:
        with self._mu:
            self._reap_if_expired_locked()
            if self._holder is not None and self._holder.task_id != task_id:
                if not blocking:
                    return False
            now = time.time()
            self._holder = LockHolder(
                task_id=task_id, acquired_at=now, last_heartbeat=now
            )
            return True

    def heartbeat(self, task_id: str) -> None:
        with self._mu:
            if self._holder and self._holder.task_id == task_id:
                self._holder.last_heartbeat = time.time()

    def release(self, task_id: str) -> None:
        with self._mu:
            if self._holder and self._holder.task_id == task_id:
                self._holder = None

    def force_release(self) -> None:
        with self._mu:
            self._holder = None

    @property
    def held_by(self) -> str | None:
        with self._mu:
            self._reap_if_expired_locked()
            return self._holder.task_id if self._holder else None

    def _reap_if_expired_locked(self) -> None:
        if self._holder is None:
            return
        if time.time() - self._holder.last_heartbeat > DEVICE_LOCK_TIMEOUT_SEC:
            self._holder = None
