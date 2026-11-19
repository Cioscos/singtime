"""Prova dei modelli candidati sui brani dell'utente.

    uv run python -m karaoke.trial URL [URL…]   elabora ogni brano con tutti i candidati
    uv run python -m karaoke.trial --clean      elimina le varianti create dalla prova

Ogni variante è un brano a sé in libreria (id `<brano>--<etichetta>`), così la si
ascolta e la si guarda nella vista di verifica come qualunque altro brano.
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

from . import config
from .library import INSTRUMENTAL, LYRICS, NOTES_SWIFTF0, SOURCE, VOCALS, Library
from .models import STAGES, Note, SongMeta
from .pipeline import acquire
from .pipeline.pitch import F0_MAX, F0_MIN, hz_to_midi
from .pipeline.runner import DEFAULT_STAGES, Pipeline, StageFn

VARIANT_MARK = "--"
SEPARATOR_LABELS = {
    "model_bs_roformer_ep_317_sdr_12.9755.ckpt": "bs-roformer",
    "vocals_mel_band_roformer.ckpt": "mel-band",
    "htdemucs_ft.yaml": "demucs",
}
Timing = tuple[str, str, float]


def separator_label(model_filename: str) -> str:
    return SEPARATOR_LABELS.get(model_filename, Path(model_filename).stem)


def timed_stages(stages: dict[str, StageFn], timings: list[Timing]) -> dict[str, StageFn]:
    """Gli stessi passi, ma ognuno annota quanti secondi ha impiegato."""
    def wrap(name: str, fn: StageFn) -> StageFn:
        def timed(library: Library, song_id: str) -> None:
            started = time.perf_counter()
            try:
                fn(library, song_id)
            finally:
                timings.append((song_id, name, time.perf_counter() - started))
        return timed
    return {name: wrap(name, fn) for name, fn in stages.items()}


def make_variant(library: Library, base_id: str, *, separator_model: str | None = None,
                 pitch_tracker: str | None = None) -> tuple[str, str]:
    """Crea (o ritrova) la variante di un brano; restituisce (id, passo da cui ripartire)."""
    base = library.get(base_id)
    if separator_model is not None:
        label, from_stage, copied = separator_label(separator_model), "separate", [SOURCE]
    elif pitch_tracker is not None:
        label, from_stage, copied = pitch_tracker, "pitch", [SOURCE, VOCALS, INSTRUMENTAL]
    else:
        raise ValueError("Serve un separatore o un tracker diverso")

    variant_id = f"{base_id}{VARIANT_MARK}{label}"
    if not library.exists(variant_id):
        library.create(SongMeta(
            id=variant_id, title=f"{base.title} [{label}]", artist=base.artist,
            duration_s=base.duration_s, source_kind=base.source_kind, source_ref=base.source_ref,
            separator_model=separator_model or base.separator_model,
            pitch_tracker=pitch_tracker or base.pitch_tracker, language=base.language))
        for name in copied:
            shutil.copy(library.path(base_id, name), library.path(variant_id, name))
    first = STAGES.index(from_stage)
    for i, stage in enumerate(STAGES):
        library.set_stage(variant_id, stage, "done" if i < first else "pending")
    return variant_id, from_stage


def clean(library: Library) -> int:
    """Elimina tutte le varianti; restituisce quante erano."""
    variants = [meta.id for meta in library.list() if VARIANT_MARK in meta.id]
    for song_id in variants:
        library.delete(song_id)
    return len(variants)


def _copy_base_lyrics(library: Library, song_id: str) -> None:
    """Il testo non dipende dal modello in prova: si riusa quello del brano di partenza."""
    base_id = song_id.split(VARIANT_MARK)[0]
    source = library.path(base_id, LYRICS)
    if source.is_file():
        shutil.copy(source, library.path(song_id, LYRICS))
    else:
        library.write_lyrics(song_id, [])
    library.update(song_id, lyrics_source=library.get(base_id).lyrics_source or "none")


def write_swiftf0_notes(library: Library, song_id: str) -> None:
    """Le note come le segmenta swift-f0 da solo, per confronto con il nostro algoritmo."""
    import swift_f0

    vocals = library.path(song_id, VOCALS)
    if not vocals.is_file():
        return
    result = swift_f0.SwiftF0().detect_file(str(vocals), fmin=F0_MIN, fmax=F0_MAX)
    notes = [Note(start=float(n.start), duration=float(n.end - n.start),
                  pitch=float(hz_to_midi(n.pitch_hz)))
             for n in swift_f0.segment_notes(result) if n.end > n.start and n.pitch_hz > 0]
    library.write_notes(song_id, notes, NOTES_SWIFTF0)


def _report(library: Library, timings: list[Timing]) -> None:
    by_song: dict[str, dict[str, float]] = {}
    for song_id, stage, seconds in timings:
        by_song.setdefault(song_id, {})[stage] = seconds
    print()
    print(f"{'brano':<44}" + "".join(f"{s:>10}" for s in STAGES) + f"{'totale':>10}  note")
    for song_id, stages in by_song.items():
        meta = library.get(song_id)
        cells = "".join(f"{stages[s]:>9.1f}s" if s in stages else f"{'-':>10}" for s in STAGES)
        failed = next((f"ERRORE {s}: {st.error}" for s, st in meta.stages.items() if st.status == "error"), None)
        count = failed or (str(len(library.read_notes(song_id))) if meta.playable else "?")
        print(f"{meta.title[:42]:<44}{cells}{sum(stages.values()):>9.1f}s  {count}")


def run(urls: list[str]) -> None:
    library = Library(config.library_dir())
    timings: list[Timing] = []
    stages = timed_stages(DEFAULT_STAGES, timings)
    pipeline = Pipeline(library, stages)
    variant_pipeline = Pipeline(library, {**stages, "lyrics": _copy_base_lyrics})

    for url in urls:
        info = acquire.probe_url(url)
        base_id = f"yt-{info.youtube_id}"
        print(f"== {info.artist} - {info.title} ({base_id})")
        if not library.exists(base_id):
            library.create(SongMeta(
                id=base_id, title=info.title, artist=info.artist, duration_s=info.duration_s,
                source_kind="youtube", source_ref=acquire.watch_url(info.youtube_id),
                separator_model=config.SEPARATOR_MODEL, pitch_tracker=config.PITCH_TRACKER))
        if not pipeline.run(base_id):
            print("   elaborazione fallita, salto le varianti")
            continue
        write_swiftf0_notes(library, base_id)

        base = library.get(base_id)
        variants = [make_variant(library, base_id, separator_model=model)
                    for model in config.SEPARATOR_CANDIDATES if model != base.separator_model]
        variants += [make_variant(library, base_id, pitch_tracker=tracker)
                     for tracker in config.PITCH_CANDIDATES if tracker != base.pitch_tracker]
        for variant_id, from_stage in variants:
            print(f"   variante {variant_id}")
            variant_pipeline.run(variant_id, from_stage)
            write_swiftf0_notes(library, variant_id)

    _report(library, timings)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="karaoke.trial", description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="*", help="URL di YouTube dei brani di prova")
    parser.add_argument("--clean", action="store_true", help="elimina le varianti create dalla prova")
    args = parser.parse_args(argv)
    if args.clean:
        print(f"Varianti eliminate: {clean(Library(config.library_dir()))}")
    elif args.urls:
        run(args.urls)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
