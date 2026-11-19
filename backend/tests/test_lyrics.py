import httpx
import pytest

from karaoke.models import LyricLine, Note, SongMeta, Word
from karaoke.pipeline.lyrics import (
    LrclibUnreachable, LyricsError,
    fetch_lrclib, find_lyrics, lines_from_lrc, lines_from_words, parse_lrc,
)

LRC = """[ar:Artista]
[ti:Titolo]
[00:12.00]Prima riga
[00:15.50]Seconda riga
[00:20.000]Terza con tre cifre
[00:25.00]
[00:40.10][01:10.20]Ritornello
"""


def test_parse_lrc_real_world_forms():                              # Review Focus 3
    e = parse_lrc(LRC)
    assert e == [(12.0, "Prima riga"), (15.5, "Seconda riga"), (20.0, "Terza con tre cifre"),
                 (25.0, ""), (40.1, "Ritornello"), (70.2, "Ritornello")]


def test_parse_lrc_garbage():
    assert parse_lrc("testo senza tempi\n\n") == []


def test_parse_lrc_sorts_by_time():
    assert parse_lrc("[00:30.00]dopo\n[00:10.00]prima") == [(10.0, "prima"), (30.0, "dopo")]


def test_lines_end_at_last_sung_note():
    notes = [Note(12.1, 0.5, 60), Note(13.0, 1.0, 62), Note(15.6, 0.4, 60)]
    lines = lines_from_lrc(parse_lrc(LRC), notes, 80.0)
    assert [l.text for l in lines] == ["Prima riga", "Seconda riga", "Terza con tre cifre", "Ritornello", "Ritornello"]
    assert lines[0].start == 12.0 and abs(lines[0].end - 14.0) < 1e-6     # fine dell'ultima nota prima della riga dopo
    assert lines[2].end == 25.0                                           # nessuna nota: finisce alla riga (vuota) successiva
    assert lines[-1].end == 80.0 and all(l.words is None for l in lines)


def lrclib(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://lrclib.net")


def test_fetch_exact_match_sends_only_song_data():
    def handler(req):
        assert req.url.path == "/api/get" and req.headers["user-agent"] == "karaoke-tracciato/0.1"
        assert set(req.url.params.keys()) == {"artist_name", "track_name", "duration"}
        return httpx.Response(200, json={"syncedLyrics": "[00:01.00]a", "duration": 200})
    assert fetch_lrclib("A", "T", 200.4, client=lrclib(handler)) == "[00:01.00]a"


def test_fetch_falls_back_to_search_within_tolerance():
    def handler(req):
        if req.url.path == "/api/get":
            return httpx.Response(404, json={})
        return httpx.Response(200, json=[
            {"syncedLyrics": "[00:01.00]lontano", "duration": 260},
            {"syncedLyrics": None, "duration": 200},
            {"syncedLyrics": "[00:01.00]giusto", "duration": 202.5}])
    assert fetch_lrclib("A", "T", 200.0, client=lrclib(handler)) == "[00:01.00]giusto"


def test_fetch_rejects_other_versions():                             # spec §6.5: versioni diverse
    def handler(req):
        if req.url.path == "/api/get":
            return httpx.Response(404, json={})
        return httpx.Response(200, json=[{"syncedLyrics": "[00:01.00]x", "duration": 204}])
    assert fetch_lrclib("A", "T", 200.0, client=lrclib(handler)) is None


def test_fetch_says_when_lrclib_cannot_be_reached():
    # "Non raggiungibile" non è "non ce l'ha": chi chiama deve poterli distinguere.
    def down(req):
        raise httpx.ConnectError("giù")
    with pytest.raises(LrclibUnreachable):
        fetch_lrclib("A", "T", 200.0, client=lrclib(down))
    with pytest.raises(LrclibUnreachable):
        fetch_lrclib("A", "T", 200.0, client=lrclib(lambda req: httpx.Response(503, json={})))


def test_lines_from_words_splits_long_segments():
    words = [Word(i * 0.5, i * 0.5 + 0.4, f"parola{i}") for i in range(12)]
    lines = lines_from_words([words], max_chars=48)
    assert len(lines) > 1 and all(len(l.text) <= 48 for l in lines)
    assert lines[0].start == 0.0 and lines[0].words[0].text == "parola0"
    assert sum(len(l.words) for l in lines) == 12


def test_lines_from_words_prefers_the_longest_pause():
    words = [Word(0, 1, "uno"), Word(1, 2, "due"), Word(5, 6, "tre"), Word(6, 7, "quattro")]
    lines = lines_from_words([words], max_chars=12)
    assert [l.text for l in lines] == ["uno due", "tre quattro"]
    assert (lines[0].end, lines[1].start) == (2, 5)


def test_lines_from_words_pulls_in_a_first_word_left_behind():
    # Whisper a volte ancora la prima parola all'inizio del segmento, molto prima del canto vero.
    words = [Word(32.0, 32.8, "It"), Word(45.6, 46.4, "is"), Word(46.4, 46.5, "a"), Word(46.5, 47.1, "page")]
    (line,) = lines_from_words([words])
    assert line.text == "It is a page"
    assert 44.5 <= line.start < 45.6 and line.words[0].end == 45.6


def test_lines_from_words_keeps_a_real_pause_after_the_first_word():
    words = [Word(118.8, 119.2, "Zwei,"), Word(121.3, 121.7, "hier"), Word(121.7, 122.6, "kommt")]
    (line,) = lines_from_words([words])
    assert line.start == 118.8 and line.words[0].end == 119.2


def meta(**kw):
    return SongMeta(id="x", title="T", artist="A", duration_s=200.0, source_kind="file",
                    source_ref="f", separator_model="m", pitch_tracker="swiftf0", **kw)


def test_find_prefers_lrclib(tmp_path):
    lines, src, lang, note = find_lyrics(meta(), tmp_path / "v.flac", [], fetch=lambda *a, **k: "[00:01.00]ciao",
                                   transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert src == "lrclib" and lines[0].text == "ciao" and lang is None


def sung(start, end):
    """Una nota al secondo, da `start` a `end`."""
    return [Note(float(t), 0.8, 60) for t in range(start, end)]


WHISPER_LINE = [LyricLine(10, 12, "trascritto", None)]


def test_find_drops_lrclib_text_timed_on_another_version(tmp_path):
    # Si canta da 10 s, ma il testo comincia a 40 s: i tempi sono quelli di un'altra versione.
    lrc = "[00:40.00]Prima riga\n[00:50.00]Seconda riga\n[01:00.00]Terza riga\n[01:10.00]"
    lines, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", sung(10, 70), fetch=lambda *a, **k: lrc,
                                transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert src == "whisper" and lines == WHISPER_LINE


def test_find_drops_lrclib_text_with_lines_nobody_could_sing(tmp_path):
    # Tre righe intere in mezzo secondo: chi ha sincronizzato il testo ha sbagliato.
    lrc = ("[00:10.00]Prima riga del testo\n[00:20.00]Una riga lunga da cantare\n[00:20.20]Un'altra riga lunga\n"
           "[00:20.40]E una terza riga lunga\n[00:20.60]Ultima riga\n[00:40.00]")
    lines, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", sung(10, 40), fetch=lambda *a, **k: lrc,
                                transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert src == "whisper" and lines == WHISPER_LINE


def test_find_keeps_lrclib_text_that_follows_the_voice(tmp_path):
    # Un vocalizzo senza parole e una riga frettolosa non bastano a scartare un testo buono.
    lrc = ("[00:10.00]Prima riga\n[00:20.00]Seconda riga\n[00:29.80]Una riga frettolosa\n[00:30.00]Terza riga\n"
           "[00:40.00]\n[00:60.00]Quarta riga\n[01:10.00]")
    notes = sung(10, 40) + sung(45, 50) + sung(60, 70)
    _, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", notes, fetch=lambda *a, **k: lrc,
                            transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert src == "lrclib"


def test_find_falls_back_to_whisper_with_user_language(tmp_path):
    seen = {}

    def fake(vocals, language):
        seen["lang"] = language
        return [LyricLine(1, 2, "hello", None)], "en"
    lines, src, lang, note = find_lyrics(meta(language="it", language_user=True), tmp_path / "v.flac", [],
                                   fetch=lambda *a, **k: None, transcribe_fn=fake)
    assert (src, lang, seen["lang"]) == ("whisper", "en", "it")


def test_find_auto_language_when_not_set_by_user(tmp_path):
    seen = {}

    def fake(vocals, language):
        seen["lang"] = language
        return [], "en"
    lines, src, _, note = find_lyrics(meta(language="en"), tmp_path / "v.flac", [], fetch=lambda *a, **k: None, transcribe_fn=fake)
    assert seen["lang"] is None and src == "none" and lines == []


def test_find_without_artist_skips_lrclib(tmp_path):
    m = meta()
    m.artist = ""
    _, src, _, note = find_lyrics(m, tmp_path / "v.flac", [], fetch=lambda *a, **k: pytest.fail("no"),
                            transcribe_fn=lambda *a: ([LyricLine(1, 2, "x", None)], "en"))
    assert src == "whisper"


def test_a_transcription_crash_says_why(tmp_path):
    def boom(vocals, language):
        raise RuntimeError("libreria CUDA mancante\n  dettagli interni")
    with pytest.raises(LyricsError, match=r"^Trascrizione non riuscita \(libreria CUDA mancante\)$"):
        find_lyrics(meta(), tmp_path / "v.flac", [], fetch=lambda *a, **k: None, transcribe_fn=boom)


@pytest.mark.parametrize("exact, search", [
    ([1, 2], []),                                                        # un elenco dove ci si aspetta un oggetto
    ({"syncedLyrics": 5, "duration": 200}, {"error": "manutenzione"}),   # testo non testuale, ricerca non in elenco
    ({"syncedLyrics": "[00:01.00]a", "duration": "200"}, "ciao"),        # durata scritta come testo
    (None, [None, "riga", 7, {"syncedLyrics": "[00:01.00]a", "duration": "duecento"}]),
])
def test_fetch_survives_unexpected_shapes(exact, search):
    def handler(req):
        return httpx.Response(200, json=exact if req.url.path == "/api/get" else search)
    assert fetch_lrclib("A", "T", 200.0, client=lrclib(handler)) is None


def test_fetch_skips_malformed_candidates_and_keeps_the_good_one():
    def handler(req):
        if req.url.path == "/api/get":
            return httpx.Response(404, json={})
        return httpx.Response(200, json=[None, {"syncedLyrics": ["x"], "duration": 200},
                                         {"syncedLyrics": "[00:01.00]buona", "duration": 201}])
    assert fetch_lrclib("A", "T", 200.0, client=lrclib(handler)) == "[00:01.00]buona"


def test_transcribe_decodes_the_audio_itself(tmp_path, monkeypatch):
    # faster-whisper 1.2 non sa aprire i file con le versioni recenti di PyAV:
    # il modello deve ricevere l'audio già decodificato, mono a 16 kHz.
    from types import SimpleNamespace

    import numpy as np
    import soundfile as sf

    from karaoke.pipeline import lyrics

    sf.write(tmp_path / "v.flac", np.zeros((44100, 2)), 44100)

    class FakeModel:
        def transcribe(self, audio, **kw):
            assert isinstance(audio, np.ndarray) and audio.ndim == 1 and len(audio) == 16000
            assert kw["word_timestamps"] is True and kw["language"] == "it"
            segment = SimpleNamespace(words=[SimpleNamespace(start=0.0, end=0.5, word=" ciao")])
            return iter([segment]), SimpleNamespace(language="it")

    monkeypatch.setattr(lyrics, "_load_whisper", lambda *a: FakeModel())
    lines, language = lyrics.transcribe(tmp_path / "v.flac", "it")
    assert lines[0].text == "ciao" and language == "it"


# --- la fonte scelta da chi gioca ---------------------------------------------

LATE_LRC = "[00:40.00]Prima riga\n[00:50.00]Seconda riga\n[01:00.00]Terza riga\n[01:10.00]"


def test_choice_lrclib_keeps_text_the_voice_check_would_drop(tmp_path):
    lines, src, _, note = find_lyrics(meta(lyrics_choice="lrclib"), tmp_path / "v.flac", sung(10, 70),
                                      fetch=lambda *a, **k: LATE_LRC,
                                      transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert src == "lrclib" and lines[0].start == 40.0 and note is None


@pytest.mark.parametrize("artist", ["A", ""])
def test_choice_lrclib_without_a_match_leaves_no_text_and_says_why(tmp_path, artist):
    m = meta(lyrics_choice="lrclib")
    m.artist = artist
    lines, src, lang, note = find_lyrics(m, tmp_path / "v.flac", sung(10, 70), fetch=lambda *a, **k: None,
                                         transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert (lines, src, lang) == ([], "none", None) and "LRCLIB" in note


def test_choice_whisper_skips_lrclib(tmp_path):
    lines, src, lang, note = find_lyrics(meta(lyrics_choice="whisper"), tmp_path / "v.flac", sung(10, 70),
                                         fetch=lambda *a, **k: pytest.fail("non deve cercare su LRCLIB"),
                                         transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert (lines, src, lang, note) == (WHISPER_LINE, "whisper", "en", None)


def test_choice_none_removes_the_text(tmp_path):
    found = find_lyrics(meta(lyrics_choice="none"), tmp_path / "v.flac", sung(10, 70),
                        fetch=lambda *a, **k: pytest.fail("non deve cercare su LRCLIB"),
                        transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert found == ([], "none", None, None)


def test_auto_says_why_lrclib_was_dropped(tmp_path):
    _, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", sung(10, 70), fetch=lambda *a, **k: LATE_LRC,
                                  transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert src == "whisper" and "LRCLIB" in note and "canto" in note


def test_auto_has_nothing_to_explain_when_lrclib_is_fine_or_absent(tmp_path):
    *_, note = find_lyrics(meta(), tmp_path / "v.flac", [], fetch=lambda *a, **k: "[00:01.00]ciao",
                           transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert note is None
    *_, note = find_lyrics(meta(), tmp_path / "v.flac", [], fetch=lambda *a, **k: None,
                           transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert note is None


# --- dalla revisione: rete assente, righe doppie, testo in anticipo -------------

def unreachable(*args, **kwargs):
    raise LrclibUnreachable("giù")


def test_auto_transcribes_when_lrclib_cannot_be_reached(tmp_path):
    lines, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", sung(10, 70), fetch=unreachable,
                                      transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert (lines, src, note) == (WHISPER_LINE, "whisper", None)


def test_choice_lrclib_with_lrclib_unreachable_is_an_error_not_an_empty_text(tmp_path):
    # Un errore del passo lascia sul disco il testo che c'era: svuotarlo sarebbe una perdita.
    with pytest.raises(LyricsError, match="LRCLIB non è raggiungibile"):
        find_lyrics(meta(lyrics_choice="lrclib"), tmp_path / "v.flac", sung(10, 70), fetch=unreachable,
                    transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))


@pytest.mark.parametrize("lrc", [
    # testo con la traduzione: due righe allo stesso istante
    "[00:10.00]Hello my old friend\n[00:10.00]Ciao vecchio amico mio\n[00:20.00]How are you today\n"
    "[00:20.00]Come stai oggi\n[00:30.00]See you again\n[00:30.00]Ci rivediamo\n[00:40.00]",
    # coro tra parentesi subito dopo la riga principale
    "[00:10.00]I really love you\n[00:10.20](really love you)\n[00:20.00]I really need you\n"
    "[00:20.20](really need you)\n[00:30.00]Stay with me\n[00:40.00]",
])
def test_find_keeps_lrclib_text_with_doubled_lines(tmp_path, lrc):
    _, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", sung(10, 40), fetch=lambda *a, **k: lrc,
                                  transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert src == "lrclib" and note is None


def test_find_drops_lrclib_text_that_runs_ahead_of_the_voice(tmp_path):
    # Il testo comincia a 10 s, ma fino a 30 s nessuno canta: le prime righe scorrono nel vuoto.
    lrc = "".join(f"[00:{t}.00]Riga che comincia a {t}\n" for t in range(10, 60, 5)) + "[01:00.00]"
    _, src, _, note = find_lyrics(meta(), tmp_path / "v.flac", sung(30, 60), fetch=lambda *a, **k: lrc,
                                  transcribe_fn=lambda *a: (WHISPER_LINE, "en"))
    assert src == "whisper" and "righe" in note


def test_find_keeps_lrclib_text_with_a_few_lines_nobody_sings(tmp_path):
    # Due righe parlate su dieci non bastano a dire che il testo è di un'altra versione.
    lrc = "".join(f"[00:{t}.00]Riga che comincia a {t}\n" for t in range(10, 60, 5)) + "[01:00.00]"
    _, src, _, _ = find_lyrics(meta(), tmp_path / "v.flac", sung(20, 60), fetch=lambda *a, **k: lrc,
                               transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert src == "lrclib"
