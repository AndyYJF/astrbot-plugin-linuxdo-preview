from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic


@dataclass(slots=True)
class _Entry[T]:
    value: T
    expires_at: float


class TTLCache[T]:
    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self._ttl_seconds = max(0, ttl_seconds)
        self._max_entries = max(1, max_entries)
        self._items: OrderedDict[str, _Entry[T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= monotonic():
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return entry.value

    def put(self, key: str, value: T) -> None:
        if self._ttl_seconds <= 0:
            return
        self._items[key] = _Entry(
            value=value,
            expires_at=monotonic() + self._ttl_seconds,
        )
        self._items.move_to_end(key)
        self._prune()

    def contains(self, key: str) -> bool:
        return self.get(key) is not None

    def _prune(self) -> None:
        now = monotonic()
        expired = [key for key, entry in self._items.items() if entry.expires_at <= now]
        for key in expired:
            self._items.pop(key, None)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)
