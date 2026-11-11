"""Ephemeral in-memory store for extraction results (no images, no disk).

Entries expire after `ttl_seconds`; a server restart drops everything. This is
enough for the synchronous single-process demo described in the design doc.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .pipeline import Context
from .schemas import ExtractionPayload


@dataclass
class StoredExtraction:
    payload: ExtractionPayload
    context: Context
    created: float


class ProcessingStore:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._items: dict[str, StoredExtraction] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if now - v.created > self.ttl]:
            del self._items[key]

    def put(self, payload: ExtractionPayload, context: Context) -> None:
        with self._lock:
            self._purge()
            self._items[payload.processing_id] = StoredExtraction(payload, context, time.monotonic())

    def get(self, processing_id: str) -> StoredExtraction | None:
        with self._lock:
            self._purge()
            return self._items.get(processing_id)

    def delete(self, processing_id: str) -> bool:
        with self._lock:
            return self._items.pop(processing_id, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
