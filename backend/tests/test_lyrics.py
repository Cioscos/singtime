import httpx
import pytest

from karaoke.models import LyricLine, Note, SongMeta, Word
from karaoke.pipeline.lyrics import (
    LyricsError,
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


def test_fetch_survives_network_error():
    def handler(req):
        raise httpx.ConnectError("giù")
    assert fetch_lrclib("A", "T", 200.0, client=lrclib(handler)) is None


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


def meta(**kw):
    return SongMeta(id="x", title="T", artist="A", duration_s=200.0, source_kind="file",
                    source_ref="f", separator_model="m", pitch_tracker="swiftf0", **kw)


def test_find_prefers_lrclib(tmp_path):
    lines, src, lang = find_lyrics(meta(), tmp_path / "v.flac", [], fetch=lambda *a, **k: "[00:01.00]ciao",
                                   transcribe_fn=lambda *a: pytest.fail("non deve trascrivere"))
    assert src == "lrclib" and lines[0].text == "ciao" and lang is None


def test_find_falls_back_to_whisper_with_user_language(tmp_path):
    seen = {}

    def fake(vocals, language):
        seen["lang"] = language
        return [LyricLine(1, 2, "hello", None)], "en"
    lines, src, lang = find_lyrics(meta(language="it", language_user=True), tmp_path / "v.flac", [],
                                   fetch=lambda *a, **k: None, transcribe_fn=fake)
    assert (src, lang, seen["lang"]) == ("whisper", "en", "it")


def test_find_auto_language_when_not_set_by_user(tmp_path):
    seen = {}

    def fake(vocals, language):
        seen["lang"] = language
        return [], "en"
    lines, src, _ = find_lyrics(meta(language="en"), tmp_path / "v.flac", [], fetch=lambda *a, **k: None, transcribe_fn=fake)
    assert seen["lang"] is None and src == "none" and lines == []


def test_find_without_artist_skips_lrclib(tmp_path):
    m = meta()
    m.artist = ""
    _, src, _ = find_lyrics(m, tmp_path / "v.flac", [], fetch=lambda *a, **k: pytest.fail("no"),
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
