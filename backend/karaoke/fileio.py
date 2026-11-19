"""Scrittura sicura dei file JSON di stato."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# Su Windows non si può sostituire un file mentre un altro thread lo sta leggendo:
# l'errore dura un istante, quindi si riprova poche volte prima di arrendersi.
_REPLACE_ATTEMPTS = 6
_REPLACE_WAIT_S = 0.02


def write_json(path: Path, data: Any) -> None:
    """Scrittura atomica: un file a metà non deve mai sostituire quello buono."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Un nome diverso per ogni thread: due scritture insieme non si pestano i piedi.
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_WAIT_S * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
