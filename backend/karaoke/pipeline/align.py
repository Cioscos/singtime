"""Mette un testo già scritto sui tempi di questa registrazione.

Le parole vengono da chi le ha scritte (LRCLIB, di qualunque versione del brano), i tempi
dalla voce isolata. Whisper dice all'incirca dove cade ogni riga (le "ancore"); un
allineatore forzato mette poi le parole al loro posto dentro finestre brevi, così un
ritornello ripetuto non lo fa scivolare su quello dopo.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

from .. import config
from ..models import LyricLine, Note, Word
from .progress import ByteProgress, watching

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
WILDCARD = "*"                 # nella richiesta all'allineatore: "qui c'è voce che il testo non racconta"
ALIGNER_DOWNLOAD_LABEL = "Scarico il modello di allineamento"
_HOP = 320                     # campioni di voce per ogni passo del modello
_CHUNK_S = 30                  # la voce si guarda a pezzi: un brano intero non entra nella memoria della scheda
_CONTEXT_S = 2

Span = tuple[float, float]


@dataclass
class AlignedWord:
    """Dove l'allineatore ha messo una parola: i tratti delle sue lettere, e quanto ne è convinto (0–1)."""

    letters: list[Span]
    score: float


# Mette le parole (o WILDCARD) dentro [da, a] secondi, una risposta per parola; None se non ci stanno.
WindowAligner = Callable[[list[str], float, float], "list[AlignedWord] | None"]


# --- il testo ----------------------------------------------------------------

def match_key(token: str) -> str:
    """La parola ridotta a lettere e cifre senza accenti: così la scrive anche chi trascrive."""
    token = unicodedata.normalize("NFKD", token.lower().replace("’", "'").replace("ß", "ss"))
    return re.sub(r"[^a-z0-9']", "", token).strip("'")


def spoken_letters(key: str) -> str:
    """Quel che l'allineatore sa leggere: lettere e apostrofo. Le cifre no."""
    return re.sub(r"[0-9]", "", key).strip("'")


@dataclass
class _TextWord:
    text: str
    key: str
    letters: str


def _text_lines(text: list[str]) -> list[list[_TextWord]]:
    lines = []
    for raw in text:
        # I cori tra parentesi si cantano come il resto.
        words = [_TextWord(token, match_key(token), spoken_letters(match_key(token)))
                 for token in raw.strip("() \t").split()]
        words = [word for word in words if word.key]
        if words:
            lines.append(words)
    return lines


# --- le ancore ---------------------------------------------------------------

def anchors(written: list[str], heard: list[str]) -> dict[int, int]:
    """Quali parole scritte sono anche state sentite, e dove: indice scritto -> indice sentito.

    Si cerca la più lunga sottosequenza comune e si tengono solo i tratti di più parole
    di fila: una parola isolata ("i", "to") combacia ovunque e non dice niente.
    """
    n, m = len(written), len(heard)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, below, word = table[i], table[i + 1], written[i]
        for j in range(m - 1, -1, -1):
            row[j] = below[j + 1] + 1 if word == heard[j] else max(below[j], row[j + 1])
    runs: list[list[tuple[int, int]]] = []
    i = j = 0
    while i < n and j < m:
        if written[i] == heard[j] and table[i][j] == table[i + 1][j + 1] + 1:
            if runs and runs[-1][-1] == (i - 1, j - 1):
                runs[-1].append((i, j))
            else:
                runs.append([(i, j)])
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return {i: j for run in runs if len(run) >= config.ALIGN_MIN_ANCHOR_RUN for i, j in run}


# --- i tempi delle parole di una riga ----------------------------------------

def _first_start(word: AlignedWord) -> float:
    """L'attacco di una parola a inizio riga.

    La prima lettera si aggancia volentieri alla coda della riga prima (una vocale tenuta
    le somiglia): se dentro la parola c'è un buco, la parola comincia dopo il buco.
    """
    start = word.letters[0][0]
    for (_, before_end), (after_start, _) in zip(word.letters, word.letters[1:]):
        if after_start - before_end > config.ALIGN_FIRST_WORD_GAP_S:
            start = after_start - 0.15
    return start


def _heard_times(known: list[Span | None], span: Span) -> list[Span]:
    """I tempi di Whisper per tutta la riga: le parole che non ha sentito si dividono lo spazio tra le altre."""
    ends = [word[1] if word else None for word in known]
    ends[-1] = span[1]
    times: list[Span] = []
    mark = known[0][0] if known[0] else span[0]
    for k, word in enumerate(known):
        end = ends[k]
        if end is None:
            ahead, target = next((j, later) for j, later in enumerate(ends) if j > k and later is not None)
            end = mark + (target - mark) / (ahead - k + 1)
        start = max(mark, word[0]) if word else mark
        times.append((start, max(start, end)))
        mark = end
    return times


def _aligned_times(placed: list[AlignedWord | None], known: list[Span | None],
                   sung: Callable[[float, float], float], note_starts: list[float]) -> list[Span]:
    """I tempi dell'allineatore, ritoccati dove si sa che sbaglia; in `placed` c'è almeno una parola."""
    aligned = {k: word for k, word in enumerate(placed) if word is not None}
    spans = {k: (word.letters[0][0], word.letters[-1][1]) for k, word in aligned.items()}
    first, *others = sorted(spans)
    start, end = _first_start(aligned[first]), spans[first][1]
    if others and spans[others[0]][0] - end > config.WHISPER_LEFT_BEHIND_GAP_S:
        # Rimasta molto prima delle altre: va accanto a loro (come lyrics._pull_in_first_word).
        following = spans[others[0]][0]
        start, end = following - min(end - start, config.WHISPER_LEFT_BEHIND_WORD_S), following
    heard = known[first]
    if heard is not None:
        # Una parola tenuta a lungo l'allineatore la mette verso la fine; Whisper ne sente l'attacco.
        # A meno che abbia inghiottito la pausa prima (parola lunghissima) o che lì non canti nessuno.
        earlier = max(heard[0], heard[1] - config.ALIGN_MAX_FIRST_WORD_S)
        if sung(earlier, earlier + 0.2) < 0.1:
            later = [onset for onset in note_starts if onset >= earlier]
            earlier = min(later[0] - 0.1, start) if later else start
        if 0 < start - earlier < config.ALIGN_MAX_EARLIER_S:
            start = earlier
    spans[first] = (start, max(start, end))

    # Le parole che l'allineatore non sa leggere (cifre): dove le ha sentite Whisper, o attaccate alla vicina.
    times: list[Span] = []
    for k, heard in enumerate(known):
        if k in spans:
            times.append(spans[k])
        elif heard is not None:
            times.append(heard)
        else:
            after = [spans[j][0] for j in sorted(spans) if j > k]
            at = after[0] if after else times[-1][1]
            times.append((at, at))
    return times


# --- dal testo alle righe con i tempi ----------------------------------------

def place_lines(text: list[str], heard: list[Word], notes: list[Note], duration_s: float,
                aligner: WindowAligner) -> tuple[list[LyricLine], int]:
    """(le righe di `text` con i tempi di questa registrazione, quante righe non si sono ritrovate).

    `heard` sono le parole trascritte da Whisper, con i loro tempi approssimativi. Le righe
    che in questa registrazione non ci sono (un'altra versione ha strofe in più) si scartano.
    """
    lines = _text_lines(text)
    note_starts = [note.start for note in notes]

    def sung(a: float, b: float) -> float:
        return sum(max(0.0, min(b, note.start + note.duration) - max(a, note.start)) for note in notes)

    # Le note fanno da rivelatore di voce: una parola "sentita" dove nessuno canta è inventata,
    # e Whisper dà durata zero a quelle che ripete a vuoto.
    margin = config.ALIGN_VOICE_MARGIN_S
    voiced = [(word.start, word.end, match_key(word.text)) for word in heard
              if match_key(word.text) and word.end - word.start >= config.ALIGN_MIN_HEARD_WORD_S
              and sung(word.start - margin, word.end + margin) > 0]
    anchor = anchors([word.key for line in lines for word in line], [key for _, _, key in voiced])

    known: list[list[Span | None]] = []        # per riga e parola: i tempi di Whisper, se la parola è un'ancora
    whisper: dict[int, Span] = {}              # righe ancorate (Whisper ne ha sentita almeno metà): da dove a dove
    cursor = 0
    for li, line in enumerate(lines):
        times = [voiced[anchor[k]][:2] if k in anchor else None for k in range(cursor, cursor + len(line))]
        cursor += len(line)
        found = [span for span in times if span is not None]
        known.append(times)
        if len(found) >= max(1, math.ceil(len(line) / 2)):
            whisper[li] = (found[0][0], found[-1][1])

    placed: dict[int, list[AlignedWord | None]] = {}

    def align(group: list[int], start: float, end: float) -> bool:
        request: list[str] = [WILDCARD]
        owner: list[tuple[int, int] | None] = [None]
        for li in group:
            for wi, word in enumerate(lines[li]):
                if word.letters:
                    request.append(word.letters)
                    owner.append((li, wi))
            request.append(WILDCARD)
            owner.append(None)
        if len(request) == len(group) + 1 or end <= start:
            return False
        answer = aligner(request, start, end)
        if answer is None:
            return False
        for li in group:
            placed[li] = [None] * len(lines[li])
        for who, word in zip(owner, answer):
            if who is not None:
                placed[who[0]][who[1]] = word
        return True

    # Le righe ancorate, una per una, in una finestra stretta attorno a dove le ha sentite Whisper.
    anchored = sorted(whisper)
    overlap = config.ALIGN_WINDOW_OVERLAP_S
    for position, li in enumerate(anchored):
        low, high = whisper[li]
        previous_high = whisper[anchored[position - 1]][1] if position > 0 else 0.0
        next_low = whisper[anchored[position + 1]][0] if position + 1 < len(anchored) else duration_s
        align([li], max(previous_high - overlap, low - config.ALIGN_WINDOW_BEFORE_S),
              min(next_low + overlap, high + config.ALIGN_WINDOW_AFTER_S))

    def edge(li: int, end: bool) -> float:
        """Dove finisce (o comincia) una riga ancorata: dall'allineatore se l'ha messa, se no da Whisper."""
        words = [word for word in placed.get(li) or [] if word is not None]
        if not words:
            return whisper[li][1 if end else 0]
        return words[-1].letters[-1][1] if end else _first_start(words[0])

    # Le altre, a gruppi, nello spazio che resta tra due righe ancorate.
    blind: dict[int, float] = {}               # quanto è larga la finestra in cui la riga è stata messa alla cieca
    bounds = [-1, *anchored, len(lines)]
    for before, after in zip(bounds, bounds[1:]):
        group = list(range(before + 1, after))
        start = edge(before, True) if before >= 0 else 0.0
        end = edge(after, False) if after < len(lines) else duration_s
        if group and align(group, start, end):
            blind.update((li, end - start) for li in group)

    result: list[LyricLine] = []
    for li, line in enumerate(lines):
        got = [word for word in placed.get(li) or [] if word is not None]
        score = sum(word.score for word in got) / len(got) if got else 0.0
        if li in whisper and score < config.ALIGN_MIN_SCORE:
            # L'allineatore non ha riconosciuto niente (voci sovrapposte): valgono i tempi di Whisper.
            times = _heard_times(known[li], whisper[li])
        elif got:
            times = _aligned_times(placed[li], known[li], sung, note_starts)
        else:
            continue                                                    # non ci stava
        if result and times[0][0] < result[-1].end:
            times[0] = (min(result[-1].end, times[0][1]), times[0][1])
        words, floor = [], 0.0
        for word, (a, b) in zip(line, times):
            floor = max(floor, a)
            words.append(Word(round(floor, 3), round(max(floor, b), 3), word.text))
        start, end = words[0].start, max(word.end for word in words)
        if li not in whisper:
            # Nessuno l'ha sentita: se in più è finita dove non si canta, o l'allineatore non l'ha
            # riconosciuta e poteva metterla lontano, in questa registrazione non c'è.
            if sung(start, end) < (end - start) * config.ALIGN_MIN_SUNG_SHARE:
                continue
            if score < config.ALIGN_MIN_SCORE and blind.get(li, 0.0) > config.ALIGN_MAX_BLIND_WINDOW_S:
                continue
        if end - start < sum(len(word.letters) for word in line) * config.ALIGN_MIN_LETTER_S:
            continue                                                    # schiacciata: non c'era posto
        result.append(LyricLine(start, end, " ".join(word.text for word in line), words))

    for line, following in zip(result, result[1:]):
        if line.end > following.start:
            line.end = following.start
            for word in line.words or []:
                word.start, word.end = min(word.start, line.end), min(word.end, line.end)
    return result, len(lines) - len(result)


# --- l'allineatore vero ------------------------------------------------------

_aligner: dict[str, Any] = {}


def _load_aligner(on_detail: Callable[[str], None] | None = None) -> tuple[Any, Any, Any]:
    """(modello, da parole a simboli, allineatore). Il modello si scarica la prima volta."""
    if "loaded" in _aligner:
        return _aligner["loaded"]
    import torch
    import torchaudio

    bundle = torchaudio.pipelines.MMS_FA
    folder = config.models_dir() / "aligner"
    folder.mkdir(parents=True, exist_ok=True)

    def load() -> Any:
        model = bundle.get_model(with_star=True, dl_kwargs={"model_dir": str(folder), "progress": False})
        if torch.cuda.is_available():
            try:
                return model.to("cuda")
            except Exception as exc:
                log.warning("Allineatore su GPU non disponibile (%s): uso la CPU, sarà più lento.", exc)
        return model

    if on_detail is not None and not any(folder.glob("*.pt")):
        with watching(folder, 0, ByteProgress(on_detail, ALIGNER_DOWNLOAD_LABEL)):
            model = load()
    else:
        model = load()
    _aligner["loaded"] = (model, bundle.get_tokenizer(), bundle.get_aligner())
    return _aligner["loaded"]


class VoiceAligner:
    """Quanto ogni istante della voce somiglia a ogni lettera, calcolato una volta; poi si allinea a finestre."""

    def __init__(self, audio: Any, on_detail: Callable[[str], None] | None = None):
        """`audio`: la voce, mono a 16 kHz."""
        import torch

        model, self._tokenizer, self._align = _load_aligner(on_detail)
        device = next(model.parameters()).device
        wave = torch.from_numpy(audio)
        chunk, context = _CHUNK_S * SAMPLE_RATE, _CONTEXT_S * SAMPLE_RATE
        pieces = []
        with torch.inference_mode():
            for begin in range(0, len(wave), chunk):
                left = min(context, begin)
                emission, _ = model(wave[begin - left: begin + chunk + context].unsqueeze(0).to(device))
                keep = min(chunk, len(wave) - begin) // _HOP
                pieces.append(emission[0].cpu()[left // _HOP: left // _HOP + keep])
        self._emission = torch.cat(pieces)
        self._frame_s = len(wave) / SAMPLE_RATE / max(1, len(self._emission))

    def __call__(self, words: list[str], start: float, end: float) -> list[AlignedWord] | None:
        first = max(0, int(start / self._frame_s))
        last = min(len(self._emission), math.ceil(end / self._frame_s))
        tokens = self._tokenizer(words)
        if last - first < 2 * sum(len(word) for word in tokens):
            return None
        try:
            spans = self._align(self._emission[first:last], tokens)
        except Exception as exc:
            log.info("Allineamento non riuscito tra %.1f e %.1f s: %s", start, end, exc)
            return None
        seconds = self._frame_s
        return [AlignedWord([((first + c.start) * seconds, (first + c.end) * seconds) for c in letters],
                            sum(c.score * (c.end - c.start) for c in letters)
                            / max(1, sum(c.end - c.start for c in letters)))
                for letters in spans]
