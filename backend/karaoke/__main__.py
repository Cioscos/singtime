"""Avvio con un comando: `uv run karaoke`."""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser

from . import config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="karaoke", description="Karaoke a tracciato")
    parser.add_argument("--no-browser", action="store_true", help="non aprire il browser all'avvio")
    parser.add_argument("--port", type=int, default=config.PORT, help="porta locale")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    import uvicorn

    from .api import create_app
    from .jobs import JobQueue
    from .library import Library
    from .pipeline.runner import Pipeline

    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    library = Library(config.library_dir())
    jobs = JobQueue(Pipeline(library))
    jobs.start()
    static_dir = config.REPO_ROOT / "frontend" / "dist"
    app = create_app(library, jobs, static_dir=static_dir)

    url = f"http://{config.HOST}:{args.port}/"
    print(f"Karaoke in ascolto su {url}  (Ctrl+C per uscire)")
    print(f"Dati in {config.data_dir()}")
    if not static_dir.is_dir():
        print("Interfaccia non ancora costruita: esegui `npm --prefix frontend run build`.")
    elif not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    try:
        uvicorn.run(app, host=config.HOST, port=args.port, log_level="warning")
    finally:
        jobs.stop()


if __name__ == "__main__":
    main()
