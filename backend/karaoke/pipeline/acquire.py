"""Passo 1: da un file o da un URL di YouTube a `source.flac` più i metadati."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import soundfile as sf

from .. import config


class AcquireError(Exception):
    """Errore di acquisizione; il messaggio è in italiano e va mostrato così com'è."""


@dataclass
class UrlInfo:
    youtube_id: str
    title: str
    artist: str
    duration_s: float


# --- URL di YouTube ----------------------------------------------------------

_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_PATH_PREFIXES = ("/shorts/", "/embed/", "/live/")


def youtube_id(url: str) -> str | None:
    """L'identificativo del video, qualunque sia la forma dell'URL; None se non è YouTube."""
    url = url.strip()
    if "://" not in url:
        url = "https://" + url          # incollato senza "https://": capita spesso
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    candidate: str | None = None
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host in _YT_HOSTS:
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            for prefix in _YT_PATH_PREFIXES:
                if parsed.path.startswith(prefix):
                    candidate = parsed.path[len(prefix):].split("/")[0]
    return candidate if candidate and _YT_ID.match(candidate) else None


def watch_url(video_id: str) -> str:
    """URL canonico: senza playlist né altri parametri."""
    return f"https://www.youtube.com/watch?v={video_id}"


# --- pulizia dei titoli ------------------------------------------------------

_JUNK_WORDS = (r"official|video|videoclip|audio|lyrics?|testo|visuali[sz]er|"
               r"hd|hq|4k|remaster(?:ed)?|mv")
_JUNK_GROUP = re.compile(rf"\s*[\(\[][^\)\]]*\b(?:{_JUNK_WORDS})\b[^\)\]]*[\)\]]", re.IGNORECASE)
_JUNK_TAIL = re.compile(r"(?:\s+(?:hd|hq|4k))+\s*$", re.IGNORECASE)
_SEPARATOR = re.compile(r"\s+[-–—]\s+")


def _clean_uploader(uploader: str | None) -> str:
    name = (uploader or "").strip()
    name = re.sub(r"\s*-\s*Topic$", "", name)
    name = re.sub(r"\s*VEVO$", "", name)
    return name.strip()


def clean_title(raw_title: str, uploader: str | None = None,
                artist: str | None = None, track: str | None = None) -> tuple[str, str]:
    """Ricava (artista, titolo) da un titolo di YouTube, che di solito è sporco."""
    if artist and track:
        return artist.strip(), track.strip()
    title = _JUNK_GROUP.sub("", raw_title)
    title = _JUNK_TAIL.sub("", title).strip()
    parts = _SEPARATOR.split(title, maxsplit=1)
    if len(parts) == 2 and all(p.strip() for p in parts):
        return parts[0].strip(), parts[1].strip()
    return _clean_uploader(uploader), title


# --- yt-dlp ------------------------------------------------------------------

def _ydl_options(**extra: Any) -> dict[str, Any]:
    return {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, **extra}


def _extract_info(url: str) -> dict[str, Any]:
    from yt_dlp import YoutubeDL

    with YoutubeDL(_ydl_options()) as ydl:
        return ydl.extract_info(url, download=False) or {}


def too_long_message(duration_s: float) -> str:
    return (f"Brano troppo lungo ({round(duration_s / 60)} minuti): "
            f"il limite è {config.MAX_DURATION_S // 60} minuti.")


def probe_url(url: str, extract: Callable[[str], dict[str, Any]] = _extract_info) -> UrlInfo:
    """Controlla che l'URL sia un video scaricabile, senza scaricarlo."""
    video_id = youtube_id(url)
    if video_id is None:
        raise AcquireError("URL non valido: incolla il link di un video di YouTube.")
    try:
        info = extract(watch_url(video_id))
    except Exception as exc:
        raise AcquireError(f"Video non disponibile ({_short(exc)}).") from exc
    if info.get("is_live"):
        raise AcquireError("Il video è una diretta: non si può scaricare.")
    duration = info.get("duration")
    if not duration:
        raise AcquireError("Video non disponibile (durata sconosciuta).")
    if duration > config.MAX_DURATION_S:
        raise AcquireError(too_long_message(duration))
    artists = info.get("artists") or []
    artist, title = clean_title(
        info.get("title") or "", info.get("uploader") or info.get("channel"),
        artist=info.get("artist") or (artists[0] if artists else None), track=info.get("track"))
    return UrlInfo(youtube_id=info.get("id") or video_id, title=title, artist=artist,
                   duration_s=float(duration))


def _short(exc: Exception) -> str:
    # yt-dlp premette "ERROR: [youtube] <id>: " (o "ERROR: \r[download] …") al messaggio vero.
    text = re.sub(r"^ERROR:\s*", "", str(exc).strip())
    text = next((line.strip() for line in text.splitlines() if line.strip()), "")
    text = re.sub(r"^\[[^\]]+\]\s*(?:\S+:\s*)?", "", text)
    return (text.rstrip(".") or type(exc).__name__)[:200]


def download_options(dest_dir: Path) -> dict[str, Any]:
    """Opzioni di yt-dlp per scaricare solo l'audio.

    Il download a blocchi evita il rallentamento che YouTube applica ad alcuni
    video quando si chiede il file in un colpo solo (fino al timeout).
    """
    return _ydl_options(format="bestaudio/best", outtmpl=str(dest_dir / "download.%(ext)s"),
                        http_chunk_size=1024 * 1024, socket_timeout=20, retries=5)


def download_audio(url: str, dest_dir: Path) -> Path:
    """Scarica solo l'audio, nel formato migliore disponibile."""
    from yt_dlp import YoutubeDL

    dest_dir.mkdir(parents=True, exist_ok=True)
    video_id = youtube_id(url)
    target = watch_url(video_id) if video_id else url
    options = download_options(dest_dir)
    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(target, download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as exc:
        raise AcquireError(f"Download non riuscito ({_short(exc)}).") from exc
    if not path.is_file():
        found = sorted(dest_dir.glob("download.*"))
        if not found:
            raise AcquireError("Download non riuscito (nessun file ricevuto).")
        path = found[0]
    return path


# --- file --------------------------------------------------------------------

def normalize_audio(src: Path, dest: Path) -> float:
    """Converte in FLAC 44,1 kHz stereo e restituisce la durata in secondi."""
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:a:0", "-vn",
               "-ac", "2", "-ar", "44100", str(dest)]
    try:
        result = subprocess.run(command, capture_output=True)
    except FileNotFoundError as exc:
        raise AcquireError("ffmpeg non trovato: installalo e riprova.") from exc
    if result.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise AcquireError("Il file non contiene audio leggibile.")
    return float(sf.info(str(dest)).duration)


def file_song_id(path: Path) -> str:
    """Identificativo basato sul contenuto: lo stesso file dà sempre lo stesso brano."""
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "file-" + digest.hexdigest()[:12]


def file_metadata(path: Path, original_name: str | None = None) -> tuple[str, str]:
    """(artista, titolo) dai tag del file; senza tag, il titolo è il nome del file."""
    tags: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=artist,title",
             "-of", "json", str(path)], capture_output=True)
        if result.returncode == 0:
            raw = json.loads(result.stdout.decode("utf-8", "replace") or "{}")
            tags = {k.lower(): str(v) for k, v in (raw.get("format", {}).get("tags") or {}).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    fallback = Path(original_name).stem if original_name else path.stem
    return tags.get("artist", "").strip(), tags.get("title", "").strip() or fallback
