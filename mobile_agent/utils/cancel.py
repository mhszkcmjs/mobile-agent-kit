"""任务级取消令牌 PRD §11.7 双向取消。"""
from __future__ import annotations

import threading


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: str | None = None

    def cancel(self, reason: str = "user_requested") -> None:
        self._reason = reason
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledByUser(self._reason or "cancelled")


class CancelledByUser(RuntimeError):
    """用户主动取消。Device 层每个 action 之前必须 raise_if_cancelled()。"""
