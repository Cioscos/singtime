"""La coda di elaborazione: un brano alla volta, perché la scheda grafica è una sola."""

from __future__ import annotations

import logging
import queue
import threading

from .pipeline.runner import Pipeline

log = logging.getLogger(__name__)

_STOP = object()


class JobQueue:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._waiting: list[str] = []
        self._current: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="karaoke-jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._queue.put(_STOP)
            self._thread.join(timeout=5)
            self._thread = None

    def enqueue(self, song_id: str, from_stage: str | None = None) -> None:
        with self._lock:
            self._waiting.append(song_id)
        self._queue.put((song_id, from_stage))

    def position(self, song_id: str) -> int | None:
        """0 se è in elaborazione, 1 se è il prossimo…; None se non è in coda."""
        with self._lock:
            if self._current == song_id:
                return 0
            if song_id in self._waiting:
                return self._waiting.index(song_id) + 1
            return None

    def join(self) -> None:
        self._queue.join()

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job is _STOP:
                self._queue.task_done()
                return
            song_id, from_stage = job
            with self._lock:
                self._waiting.remove(song_id)
                self._current = song_id
            try:
                self.pipeline.run(song_id, from_stage)
            except Exception:  # un brano che va storto non deve fermare la coda
                log.exception("Elaborazione fallita per %s", song_id)
            finally:
                with self._lock:
                    self._current = None
                self._queue.task_done()
