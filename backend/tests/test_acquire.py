import subprocess

import numpy as np
import pytest
import soundfile as sf

from karaoke.pipeline.acquire import (
    AcquireError, clean_title, file_metadata, file_song_id, normalize_audio, probe_url, youtube_id,
)


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=DZHs-SRJbzU",
    "https://youtu.be/DZHs-SRJbzU?t=10",
    "https://www.youtube.com/watch?v=DZHs-SRJbzU&list=PL123&index=2",   # Review Focus 1
    "https://music.youtube.com/watch?v=DZHs-SRJbzU",
    "https://www.youtube.com/shorts/DZHs-SRJbzU",
])
def test_youtube_id_forms(url):
    assert youtube_id(url) == "DZHs-SRJbzU"


def test_youtube_id_rejects_other_sites():
    assert youtube_id("https://example.com/watch?v=x") is None
    assert youtube_id("non è un url") is None


@pytest.mark.parametrize("raw,uploader,expected", [
    ("Artista - Titolo (Official Video)", None, ("Artista", "Titolo")),
    ("Artista - Titolo [Official Music Video] HD", None, ("Artista", "Titolo")),
    ("Artista – Titolo (Lyrics)", None, ("Artista", "Titolo")),
    ("Titolo (Audio)", "Artista - Topic", ("Artista", "Titolo")),
    ("Titolo", "ArtistaVEVO", ("Artista", "Titolo")),
])
def test_clean_title(raw, uploader, expected):
    assert clean_title(raw, uploader) == expected


def test_clean_title_prefers_structured_fields():
    assert clean_title("qualsiasi cosa", "canale", artist="A", track="T") == ("A", "T")


def test_clean_title_keeps_meaningful_parentheses():
    assert clean_title("Artista - Titolo (Parte Seconda)") == ("Artista", "Titolo (Parte Seconda)")


def test_probe_returns_info():
    fake = lambda url: {"id": "abc", "title": "A - T (Official Video)", "duration": 200, "uploader": "canale"}
    info = probe_url("https://youtu.be/DZHs-SRJbzU", extract=fake)
    assert (info.youtube_id, info.artist, info.title, info.duration_s) == ("abc", "A", "T", 200.0)


def test_probe_rejects_long_video():
    fake = lambda url: {"id": "abc", "title": "A - T", "duration": 3600}
    with pytest.raises(AcquireError, match="troppo lungo"):
        probe_url("https://youtu.be/DZHs-SRJbzU", extract=fake)


def test_probe_rejects_live():
    fake = lambda url: {"id": "abc", "title": "A - T", "duration": None, "is_live": True}
    with pytest.raises(AcquireError, match="diretta"):
        probe_url("https://youtu.be/DZHs-SRJbzU", extract=fake)


def test_probe_wraps_download_errors():
    def fake(url):
        raise RuntimeError("ERROR: [youtube] DZHs-SRJbzU: Video unavailable")
    with pytest.raises(AcquireError, match="non disponibile") as caught:
        probe_url("https://youtu.be/DZHs-SRJbzU", extract=fake)
    assert str(caught.value) == "Video non disponibile (Video unavailable)."   # senza i prefissi tecnici di yt-dlp


def test_probe_rejects_non_youtube():
    with pytest.raises(AcquireError, match="URL non valido"):
        probe_url("https://example.com/x")


def test_normalize_audio_writes_flac(tmp_path):
    src = tmp_path / "canzone è bella.wav"                         # Review Focus 4
    sf.write(src, 0.1 * np.sin(2 * np.pi * 220 * np.arange(22050 * 2) / 22050), 22050)
    dur = normalize_audio(src, tmp_path / "source.flac")
    info = sf.info(tmp_path / "source.flac")
    assert info.samplerate == 44100 and info.channels == 2 and abs(dur - 2.0) < 0.05


def test_normalize_takes_audio_from_a_video_file(tmp_path):         # Review Focus 4
    src = tmp_path / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", "-shortest", str(src)], check=True)
    dur = normalize_audio(src, tmp_path / "source.flac")
    assert sf.info(tmp_path / "source.flac").channels == 2 and abs(dur - 1.0) < 0.1


def test_normalize_rejects_non_audio(tmp_path):                    # Review Focus 4
    src = tmp_path / "note.txt"
    src.write_text("ciao")
    with pytest.raises(AcquireError, match="non contiene audio"):
        normalize_audio(src, tmp_path / "o.flac")
    assert not (tmp_path / "o.flac").exists()


def test_file_song_id_is_content_based(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"x" * 100)
    assert file_song_id(a) == file_song_id(b) and file_song_id(a).startswith("file-")


def test_file_metadata_falls_back_to_the_uploaded_name(tmp_path):
    src = tmp_path / "upload.wav"
    sf.write(src, np.zeros(4410), 44100)
    assert file_metadata(src) == ("", "upload")
    assert file_metadata(src, original_name="Città è già (live).wav") == ("", "Città è già (live)")
