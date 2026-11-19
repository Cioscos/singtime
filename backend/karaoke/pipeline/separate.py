"""Passo 2: da `source.flac` a `vocals.flac` e `instrumental.flac`."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import numpy as np
import soundfile as sf

from ..library import INSTRUMENTAL, VOCALS

MODEL_DOWNLOAD_NOTICE = "Scarico il modello (solo la prima volta)…"

_STEM_LABEL = re.compile(r"\(([^)]+)\)")
# Un separatore già caricato per modello: i brani successivi non ricaricano i pesi.
_loaded: dict[tuple[str, str], Any] = {}


def device_info() -> tuple[bool, str | None]:
    """(gpu_disponibile, nome_gpu)."""
    import torch

    if torch.cuda.is_available():
        return True, torch.cuda.get_device_name(0)
    return False, None


def _real_separator(**kwargs: Any) -> Any:
    from audio_separator.separator import Separator

    return Separator(log_level=logging.WARNING, **kwargs)


def _stem_label(name: str) -> str:
    labels = _STEM_LABEL.findall(Path(name).name)
    return labels[-1].strip().lower() if labels else ""


def separate(source: Path, out_dir: Path, model_filename: str, models_dir: Path,
             on_detail: Callable[[str], None] | None = None,
             separator_factory: Callable[..., Any] | None = None) -> None:
    """Scrive in `out_dir` la traccia voce e la base; non lascia altri file."""
    models_dir.mkdir(parents=True, exist_ok=True)
    scratch = models_dir / "_scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)

    if on_detail is not None and not (models_dir / model_filename).exists():
        on_detail(MODEL_DOWNLOAD_NOTICE)

    key = (str(models_dir), model_filename)
    separator = _loaded.get(key) if separator_factory is None else None
    if separator is None:
        factory = separator_factory or _real_separator
        separator = factory(output_dir=str(scratch), model_file_dir=str(models_dir), output_format="FLAC")
        separator.load_model(model_filename=model_filename)
        if separator_factory is None:
            _loaded[key] = separator

    try:
        produced = [p if p.is_absolute() else scratch / p
                    for p in (Path(name) for name in separator.separate(str(source)))]
        vocals = [p for p in produced if _stem_label(p.name) == "vocals"]
        others = [p for p in produced if _stem_label(p.name) != "vocals"]
        if not vocals:
            raise RuntimeError("Il modello non ha prodotto la traccia voce.")
        if not others:
            raise RuntimeError("Il modello non ha prodotto la base strumentale.")

        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(vocals[0]), out_dir / VOCALS)
        if len(others) == 1:
            shutil.move(str(others[0]), out_dir / INSTRUMENTAL)
        else:
            # Modelli a più tracce (Demucs): la base è la somma di tutto ciò che non è voce.
            mix, rate = None, 0
            for path in others:
                data, rate = sf.read(str(path), dtype="float32", always_2d=True)
                mix = data if mix is None else mix[: len(data)] + data[: len(mix)]
            sf.write(str(out_dir / INSTRUMENTAL), np.clip(mix, -1.0, 1.0), rate, format="FLAC")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
