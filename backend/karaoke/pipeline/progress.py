"""Avanzamento dei download dei modelli, da mostrare accanto al passo in corso."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Generator

_MEGABYTE = 1024 * 1024


class ByteProgress:
    """Trasforma i byte scaricati in un testo breve, senza ripetere due volte lo stesso."""

    def __init__(self, on_detail: Callable[[str], None], label: str):
        self._on_detail = on_detail
        self._label = label
        self._last: str | None = None

    def report(self, done: int, total: int) -> None:
        if total > 0:
            text = f"{self._label}: {min(100, int(done * 100 / total))}%"
        else:
            text = f"{self._label}: {done // _MEGABYTE} MB"
        if text != self._last:
            self._last = text
            self._on_detail(text)


def reporting_bar(bar_class: Callable[..., Any], progress: ByteProgress) -> Callable[..., Any]:
    """Una barra come quella data, che in più racconta a `progress` quanto ha scaricato."""

    class ReportingBar:
        def __init__(self, *args: Any, **kwargs: Any):
            self._bar = bar_class(*args, **kwargs)

        def update(self, n: int = 1) -> Any:
            result = self._bar.update(n)
            progress.report(int(self._bar.n), int(self._bar.total or 0))
            return result

        def __getattr__(self, name: str) -> Any:
            return getattr(self._bar, name)

    return ReportingBar


def _folder_size(folder: Path) -> int:
    total = 0
    try:
        for path in folder.rglob("*"):
            try:
                # I collegamenti (la cache di Hugging Face ne usa) puntano a file già contati.
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue  # file spostato mentre lo si guardava
    except OSError:
        pass
    return total


class FolderWatcher:
    """Misura un download da quanto cresce una cartella, quando la libreria non dice altro."""

    def __init__(self, folder: Path, total: int, progress: ByteProgress):
        self._folder = folder
        self._total = total
        self._progress = progress
        self._baseline = _folder_size(folder)

    def poll(self) -> None:
        self._progress.report(max(0, _folder_size(self._folder) - self._baseline), self._total)


@contextmanager
def watching(folder: Path, total: int, progress: ByteProgress, interval_s: float = 1.0) -> Generator[None]:
    """Tiene d'occhio la cartella da un thread a parte finché dura il blocco."""
    watcher = FolderWatcher(folder, total, progress)
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval_s):
            watcher.poll()

    thread = threading.Thread(target=loop, name="download-progress", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
