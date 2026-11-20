from types import SimpleNamespace

import pytest

from karaoke.models import Note, Word
from karaoke.pipeline import align
from karaoke.pipeline.align import AlignedWord, anchors, match_key, place_lines, spoken_letters


def test_keys_ignore_case_accents_and_punctuation():
    assert [match_key(t) for t in ("Fürchtet,", "(I’m", "heiß", "geh'n!", "1,", "♪")] == \
        ["furchtet", "i'm", "heiss", "geh'n", "1", ""]
    assert spoken_letters("8mile") == "mile" and spoken_letters("10") == ""


def test_anchors_need_several_words_in_a_row():
    written = "uno due tre quattro e poi".split()
    heard = "ma uno due tre quattro boh poi".split()
    assert anchors(written, heard) == {0: 1, 1: 2, 2: 3, 3: 4}          # "poi" da solo combacia per caso


def test_anchors_keep_repeated_choruses_in_order():
    verse1, chorus, verse2 = "la prima strofa qui".split(), "canta con me".split(), "poi la seconda dopo".split()
    written = verse1 + chorus + verse2 + chorus
    heard = verse1 + chorus + chorus                                    # la seconda strofa non si è sentita
    found = anchors(written, heard)
    assert [found.get(i) for i in range(len(written))] == [0, 1, 2, 3, 4, 5, 6, None, None, None, None, 7, 8, 9]


# --- allineatori finti -------------------------------------------------------

def spread(score=0.9, calls=None):
    """Spalma le parole chieste lungo la finestra, una dopo l'altra."""
    def aligner(words, start, end):
        if calls is not None:
            calls.append((words, round(start, 3), round(end, 3)))
        slot = (end - start) / len(words)
        placed = []
        for k, word in enumerate(words):
            step = slot / len(word)
            placed.append(AlignedWord([(start + k * slot + i * step, start + k * slot + (i + 1) * step)
                                       for i in range(len(word))], score(words) if callable(score) else score))
        return placed
    return aligner


def fixed(where, score=0.9):
    """Ogni parola dove dice `where`: un tratto solo, oppure uno per lettera."""
    def aligner(words, start, end):
        return [AlignedWord(spans if isinstance(spans := where.get(word, (start, start)), list) else [spans], score)
                for word in words]
    return aligner


def heard(*words):
    return [Word(start, end, f" {text}") for text, start, end in words]


UNO_DUE_TRE = heard(("uno", 10, 10.5), ("due", 10.5, 11), ("tre", 11, 11.5))


def times(line):
    return [(w.start, w.end) for w in line.words]


# --- dal testo alle righe ----------------------------------------------------

def test_anchored_lines_are_aligned_one_by_one_around_where_they_were_heard():
    calls = []
    words = UNO_DUE_TRE + heard(("quattro", 20, 20.5), ("cinque", 20.5, 21), ("sei", 21, 21.5))
    lines, lost = place_lines(["Uno, due tre", "(quattro cinque sei)"], words,
                              [Note(10, 2, 60), Note(20, 2, 60)], 30.0, spread(calls=calls))
    assert calls == [(["*", "uno", "due", "tre", "*"], 8.5, 12.5),
                     (["*", "quattro", "cinque", "sei", "*"], 18.5, 22.5)]
    assert lost == 0 and [l.text for l in lines] == ["Uno, due tre", "quattro cinque sei"]
    assert [w.text for w in lines[0].words] == ["Uno,", "due", "tre"]
    assert lines[0].start == pytest.approx(9.3) and lines[0].end == pytest.approx(11.7)
    assert lines[1].start == pytest.approx(19.3)


def test_lines_nobody_sings_in_this_recording_are_dropped_and_counted():
    lines, lost = place_lines(["un'introduzione che qui non c'è", "uno due tre"], UNO_DUE_TRE,
                              [Note(10, 2, 60)], 30.0, spread())
    assert [l.text for l in lines] == ["uno due tre"] and lost == 1


def test_words_invented_where_nobody_sings_do_not_anchor():
    calls = []
    place_lines(["uno due tre"], UNO_DUE_TRE, [Note(40, 2, 60)], 60.0, spread(calls=calls))
    assert calls == [(["*", "uno", "due", "tre", "*"], 0.0, 60.0)]      # nessuna ancora: una finestra sola, tutto il brano


def test_a_line_the_aligner_did_not_recognise_keeps_the_times_it_was_heard_at():
    lines, _ = place_lines(["zero uno due tre"], UNO_DUE_TRE, [Note(10, 2, 60)], 30.0, spread(score=0.0))
    assert times(lines[0]) == [(10, 10.25), (10.25, 10.5), (10.5, 11), (11, 11.5)]   # "zero" si prende metà della vicina


def test_digits_take_the_times_they_were_heard_at():
    calls = []
    words = heard(("1,", 1, 2), ("2,", 2, 3), ("3,", 3, 4), ("via", 4, 5))
    lines, _ = place_lines(["1, 2, 3, via"], words, [Note(1, 5, 60)], 30.0, spread(calls=calls))
    assert calls[0][0] == ["*", "via", "*"]                             # le cifre l'allineatore non le sa leggere
    lines, _ = place_lines(["1, 2, 3, via"], words, [Note(1, 5, 60)], 30.0, fixed({"via": (4.1, 4.9)}))
    assert lines[0].text == "1, 2, 3, via" and times(lines[0]) == [(1, 2), (2, 3), (3, 4), (4.0, 4.9)]


@pytest.mark.parametrize("first_note, start", [(10.0, 10.0), (10.6, 10.5)])     # se no, poco prima della prima nota
def test_a_held_first_word_starts_where_it_was_heard_if_someone_sings_there(first_note, start):
    words = heard(("sono", 10, 10.4), ("qui", 10.4, 10.8), ("adesso", 10.8, 11.5))
    late = fixed({"sono": (10.9, 11.0), "qui": (11.0, 11.2), "adesso": (11.2, 11.8)})
    lines, _ = place_lines(["sono qui adesso"], words, [Note(first_note, 2, 60)], 30.0, late)
    assert lines[0].start == start and times(lines[0])[0] == (start, 11.0)


def test_a_first_word_left_behind_is_pulled_next_to_the_others():
    notes = [Note(4, 7, 60)]
    lines, _ = place_lines(["io vado via"], [], notes, 30.0,
                           fixed({"io": (5.0, 5.2), "vado": (9.0, 9.5), "via": (9.5, 10.0)}))
    assert times(lines[0])[0] == (8.8, 9.0)
    # Oppure è rimasta indietro solo la sua prima lettera, agganciata alla coda della riga prima.
    lines, _ = place_lines(["io vado via"], [], notes, 30.0,
                           fixed({"io": [(5.0, 5.1), (8.9, 9.0)], "vado": (9.0, 9.5), "via": (9.5, 10.0)}))
    assert times(lines[0])[0] == (8.75, 9.0)


@pytest.mark.parametrize("second_at, kept", [(14.0, True), (30.0, False)])
def test_an_unrecognised_line_stays_only_if_it_could_not_land_far_away(second_at, kept):
    words = UNO_DUE_TRE + heard(("quattro", second_at, second_at + 0.5), ("cinque", second_at + 0.5, second_at + 1),
                                ("sei", second_at + 1, second_at + 1.5))
    aligner = spread(score=lambda request: 0.0 if "riga" in request else 0.9)
    lines, lost = place_lines(["uno due tre", "riga mai sentita", "quattro cinque sei"], words,
                              [Note(9, 25, 60)], 40.0, aligner)
    assert ("riga mai sentita" in [l.text for l in lines]) is kept and lost == (0 if kept else 1)


def test_a_line_squeezed_into_no_room_is_dropped():
    lines, lost = place_lines(["parole lunghissime davvero"], [], [Note(0, 30, 60)], 30.0,
                              fixed({"parole": (5.0, 5.1), "lunghissime": (5.1, 5.2), "davvero": (5.2, 5.3)}))
    assert lines == [] and lost == 1


def test_lines_never_overlap():
    where = {"uno": (10, 11), "due": (11, 14), "tre": (12, 12.5), "quattro": (12.5, 13)}
    lines, _ = place_lines(["uno due", "tre quattro"], [], [Note(9, 6, 60)], 30.0, fixed(where))
    assert (lines[0].start, lines[0].end, lines[1].start, lines[1].end) == (10, 12.5, 12.5, 13)
    assert times(lines[0]) == [(10, 11), (11, 12.5)]


def test_text_that_does_not_fit_at_all_gives_no_lines():
    lines, lost = place_lines(["uno due tre", "", "♪"], [], [Note(0, 30, 60)], 30.0, lambda words, start, end: None)
    assert lines == [] and lost == 1                                    # le righe senza parole non contano


# --- l'allineatore vero, con un modello finto --------------------------------

def test_voice_aligner_works_in_chunks_and_answers_in_seconds(monkeypatch):
    import numpy as np
    import torch

    seen = []

    class FakeModel:
        def parameters(self):
            return iter([torch.zeros(1)])

        def __call__(self, wave):
            seen.append(wave.shape[1])
            return torch.zeros(1, wave.shape[1] // 320, 3), None

    def fake_align(emission, tokens):
        seen.append((len(emission), tokens))
        return [[SimpleNamespace(start=5, end=10, score=0.5), SimpleNamespace(start=10, end=20, score=1.0)]]

    monkeypatch.setattr(align, "_load_aligner",
                        lambda on_detail=None: (FakeModel(), lambda words: [[1, 2] for _ in words], fake_align))
    aligner = align.VoiceAligner(np.zeros(70 * 16000, dtype=np.float32))
    assert seen == [32 * 16000, 34 * 16000, 12 * 16000]                 # 30 s alla volta, con 2 s di contesto per lato

    answer = aligner(["ab"], 10.0, 12.0)
    assert seen[-1] == (100, [[1, 2]])                                  # 2 s a 20 ms l'uno
    assert answer[0].letters == [pytest.approx((10.1, 10.2)), pytest.approx((10.2, 10.4))]
    assert answer[0].score == pytest.approx((0.5 * 5 + 1.0 * 10) / 15)
    assert aligner(["ab"], 10.0, 10.04) is None                         # non c'è posto per due lettere
