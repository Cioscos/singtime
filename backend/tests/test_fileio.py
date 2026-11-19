import json
import os

import pytest

from karaoke import fileio


def leftovers(folder):
    return sorted(p.name for p in folder.iterdir())


def test_write_json_replaces_the_file_and_leaves_no_scratch(tmp_path):
    path = tmp_path / "dati.json"
    fileio.write_json(path, {"a": 1})
    fileio.write_json(path, {"a": "è"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": "è"}
    assert leftovers(tmp_path) == ["dati.json"]


def test_write_json_creates_the_folder(tmp_path):
    path = tmp_path / "nuova" / "dati.json"
    fileio.write_json(path, [1])
    assert json.loads(path.read_text(encoding="utf-8")) == [1]


def test_write_json_retries_while_windows_holds_the_file(tmp_path, monkeypatch):
    # Su Windows sostituire un file mentre un altro thread lo legge dà PermissionError per un istante.
    path = tmp_path / "dati.json"
    fileio.write_json(path, {"v": 1})
    real_replace, calls = os.replace, []

    def busy_twice(src, dst):
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError(13, "Accesso negato")
        real_replace(src, dst)

    monkeypatch.setattr(fileio.os, "replace", busy_twice)
    monkeypatch.setattr(fileio.time, "sleep", lambda s: None)
    fileio.write_json(path, {"v": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2} and len(calls) == 3


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "dati.json"
    fileio.write_json(path, {"v": 1})

    def always_busy(src, dst):
        raise PermissionError(13, "Accesso negato")

    monkeypatch.setattr(fileio.os, "replace", always_busy)
    monkeypatch.setattr(fileio.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        fileio.write_json(path, {"v": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 1}
    assert leftovers(tmp_path) == ["dati.json"]
